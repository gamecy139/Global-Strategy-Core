"""
WW1 ECONOMY — TECHNOLOGY SYSTEM
---------------------------------
Manages research progression, research speed computation, and technology
unlock checking for infrastructure-gated buildings.

Database tables used
---------------------
  technologies  — one row per (server, scenario, country, tech) with
                  is_unlocked / is_researching / research timing.
  buildings     — queried to count completed infra buildings per province
                  (for research-speed bonuses with diminishing returns).
  countries     — queried for opinion, unrest, in_active_war.
  provinces     — queried to get province list per country.

All data is keyed by (server_id, scenario_id) for full multi-server
and multi-scenario isolation.

Research queue
--------------
Only ONE active research item (tech OR reform) is allowed per country
at a time.  This constraint is enforced jointly by TechnologySystem and
ReformsSystem: both call _ensure_no_active_research() which checks BOTH
the technologies and reforms tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ww1_economy.db       import EconomyDB
from ww1_economy.tech_data import (
    TechDef,
    TECH_TREE,
    BUILDING_TECH_REQUIREMENTS,
    TECH_GATED_BUILDINGS,
    RESEARCH_SPEED_BONUSES,
    DAYS_PER_MONTH,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ResearchSpeedResult:
    """Detailed breakdown of research speed for one country."""
    base:              float
    infra_bonus:       float
    opinion_modifier:  float
    unrest_modifier:   float
    war_modifier:      float
    raw_speed:         float    # before clamping
    final_speed:       float    # clamped to ≥ 0.5 %
    modifiers:         list[tuple[str, float]] = field(default_factory=list)


@dataclass
class StartResearchResult:
    allowed:      bool
    reason:       str
    tech_id:      str      = ""
    start_day:    int      = 0
    end_day:      int      = 0
    speed_used:   float    = 0.0


@dataclass
class ResearchCompletionEvent:
    country_id:       str
    tech_id:          str
    name:             str
    unlocked_buildings: list[str]
    unlocked_techs:     list[str]


# ---------------------------------------------------------------------------
# TechnologySystem
# ---------------------------------------------------------------------------

class TechnologySystem:
    """
    Manages the full technology research lifecycle.

    Parameters
    ----------
    db : EconomyDB
        Shared database instance (must have been initialised via ``db.init()``).
    """

    SPEED_MIN: float = 0.5   # minimum research speed (%)

    def __init__(self, db: EconomyDB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Research — start
    # ------------------------------------------------------------------

    def start_research(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        tech_id:     str,
        current_day: int,
    ) -> StartResearchResult:
        """
        Begin researching a technology.

        Rules enforced
        --------------
        1. tech_id must exist in TECH_TREE.
        2. No active research (tech OR reform) for this country.
        3. All prerequisite techs must already be is_unlocked.
        4. Tech must not already be unlocked.
        5. research_end_day = current_day + (duration_days / research_speed * 100).
           (research_speed is in %; dividing gives the effective slow-down factor.)

        Returns a StartResearchResult.
        """
        if tech_id not in TECH_TREE:
            return StartResearchResult(
                allowed=False,
                reason=f"Unknown tech_id '{tech_id}'. "
                       f"Valid: {sorted(TECH_TREE)}",
            )

        tdef = TECH_TREE[tech_id]

        # Already unlocked?
        row = self._db.get_technology(server_id, scenario_id, country_id, tech_id)
        if row and int(row.get("is_unlocked", 0)):
            return StartResearchResult(
                allowed=False, reason=f"'{tech_id}' is already unlocked.",
                tech_id=tech_id,
            )

        # Active research?
        block = self._ensure_no_active_research(server_id, scenario_id, country_id)
        if block:
            return StartResearchResult(allowed=False, reason=block, tech_id=tech_id)

        # Prerequisites met?
        for prereq in tdef.prerequisites:
            prereq_row = self._db.get_technology(
                server_id, scenario_id, country_id, prereq
            )
            if not prereq_row or not int(prereq_row.get("is_unlocked", 0)):
                return StartResearchResult(
                    allowed=False,
                    reason=f"Prerequisite '{prereq}' is not yet unlocked.",
                    tech_id=tech_id,
                )

        # Compute end day
        speed_result = self.compute_research_speed(
            server_id, scenario_id, country_id
        )
        speed = speed_result.final_speed          # in %
        # Duration in days divided by (speed / 100) gives effective days
        effective_days = int(tdef.duration_days / (speed / 100.0))
        end_day = current_day + effective_days

        # Persist
        self._db.upsert_technology(
            server_id          = server_id,
            scenario_id        = scenario_id,
            country_id         = country_id,
            tech_id            = tech_id,
            is_unlocked        = False,
            is_researching     = True,
            research_start_day = current_day,
            research_end_day   = end_day,
        )

        return StartResearchResult(
            allowed    = True,
            reason     = "Research started.",
            tech_id    = tech_id,
            start_day  = current_day,
            end_day    = end_day,
            speed_used = speed,
        )

    # ------------------------------------------------------------------
    # Research — daily process
    # ------------------------------------------------------------------

    def process_completions(
        self,
        server_id:   str,
        scenario_id: str,
        current_day: int,
    ) -> list[ResearchCompletionEvent]:
        """
        Check all in-progress tech research for this scenario and complete
        any that have reached their research_end_day.

        Call this once per game day (or from TickSystem.daily_tick).
        Returns completion events for all techs completed in this call.
        """
        events: list[ResearchCompletionEvent] = []
        for row in self._db.get_researching_techs_for_scenario(
            server_id, scenario_id
        ):
            if current_day >= int(row["research_end_day"]):
                tid = row["tech_id"]
                cid = row["country_id"]
                tdef = TECH_TREE.get(tid)
                if tdef is None:
                    continue
                self._db.complete_technology(
                    server_id, scenario_id, cid, tid
                )
                events.append(ResearchCompletionEvent(
                    country_id        = cid,
                    tech_id           = tid,
                    name              = tdef.name,
                    unlocked_buildings = list(tdef.unlocks_buildings),
                    unlocked_techs    = list(tdef.unlocks_techs),
                ))
        return events

    # ------------------------------------------------------------------
    # Research speed
    # ------------------------------------------------------------------

    def compute_research_speed(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> ResearchSpeedResult:
        """
        Compute the research speed (in %) for a country.

        Formula
        -------
        base = 1.0 %
        + infra_bonus  (Library/School/University with province diminishing returns)
        + opinion_modifier  (+0.5 if opinion > 80, -1.5 if opinion < 30)
        + unrest_modifier   (-2.0 if unrest > 50)
        + war_modifier      (-2.0 if in_active_war AND speed_before_war > 3%)
        clamped to ≥ 0.5 %

        Diminishing returns on provinces:
          Province index 1-3  → 100 % of building bonuses
          Province index 4-6  → 50 %
          Province index 7-10 → 25 %
          Province 11+        → 10 %
        """
        mods: list[tuple[str, float]] = []
        base: float = 1.0

        # ── Infrastructure bonuses with province diminishing returns ──────────
        infra_bonus = self._compute_infra_bonus(
            server_id, scenario_id, country_id, mods
        )

        # ── Opinion & unrest modifiers ─────────────────────────────────────────
        opinion_mod: float = 0.0
        unrest_mod:  float = 0.0
        war_mod:     float = 0.0

        country_row = self._db.get_country(server_id, scenario_id, country_id)
        if country_row:
            opinion = int(country_row.get("population_opinion") or 50)
            unrest  = float(country_row.get("unrest") or 0.0)
            in_war  = bool(int(country_row.get("in_active_war") or 0))

            if opinion > 80:
                opinion_mod = 0.5
                mods.append(("opinion>80", 0.5))
            elif opinion < 30:
                opinion_mod = -1.5
                mods.append(("opinion<30", -1.5))

            if unrest > 50:
                unrest_mod = -2.0
                mods.append(("unrest>50", -2.0))

            # War penalty: only if speed (before war) exceeds 3 %
            pre_war_speed = base + infra_bonus + opinion_mod + unrest_mod
            if in_war and pre_war_speed > 3.0:
                war_mod = -2.0
                mods.append(("war_active", -2.0))
        else:
            in_war = False

        raw_speed   = base + infra_bonus + opinion_mod + unrest_mod + war_mod
        final_speed = max(self.SPEED_MIN, raw_speed)

        return ResearchSpeedResult(
            base             = base,
            infra_bonus      = infra_bonus,
            opinion_modifier = opinion_mod,
            unrest_modifier  = unrest_mod,
            war_modifier     = war_mod,
            raw_speed        = raw_speed,
            final_speed      = final_speed,
            modifiers        = mods,
        )

    def _compute_infra_bonus(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        mods:        list[tuple[str, float]],
    ) -> float:
        """
        Sum infra building bonuses across owned provinces with diminishing
        returns applied per province.

        Province ordering: ascending province_id (deterministic).
        Each province that has at least one completed infra building counts.
        """
        _DR = {1: 1.0, 2: 0.5, 3: 0.25, 4: 0.10}  # bracket → DR factor

        def _bracket(rank: int) -> float:
            if rank <= 3:
                return _DR[1]
            if rank <= 6:
                return _DR[2]
            if rank <= 10:
                return _DR[3]
            return _DR[4]

        # Get all provinces owned by country
        provinces = self._db.get_provinces_by_country(
            server_id, scenario_id, country_id
        )
        if not provinces:
            return 0.0

        # Sort by province_id ascending for a deterministic order
        provinces.sort(key=lambda r: r["province_id"])

        total_bonus: float = 0.0
        province_rank: int = 0

        for prov in provinces:
            pid = str(prov["province_id"])
            buildings = self._db.get_buildings_in_province(
                server_id, scenario_id, pid
            )
            # Find completed infra buildings in this province
            prov_bonus: float = 0.0
            for b in buildings:
                if not int(b.get("is_completed", 0)):
                    continue
                bt_str = b["building_type"]
                if bt_str in RESEARCH_SPEED_BONUSES:
                    prov_bonus += RESEARCH_SPEED_BONUSES[bt_str]

            if prov_bonus > 0.0:
                province_rank += 1
                dr = _bracket(province_rank)
                contributed = prov_bonus * dr
                total_bonus += contributed
                mods.append((
                    f"infra@prov{pid}(×{dr:.0%})",
                    round(contributed, 4),
                ))

        return total_bonus

    # ------------------------------------------------------------------
    # Unlock checks
    # ------------------------------------------------------------------

    def is_unlocked(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        tech_id:     str,
    ) -> bool:
        """Return True if the given tech is fully unlocked for this country."""
        row = self._db.get_technology(server_id, scenario_id, country_id, tech_id)
        if row is None:
            return False
        return bool(int(row.get("is_unlocked", 0)))

    def is_building_unlocked(
        self,
        server_id:    str,
        scenario_id:  str,
        country_id:   str,
        building_name: str,
    ) -> bool:
        """
        Return True if ``building_name`` can be constructed by this country.

        Buildings not in TECH_GATED_BUILDINGS require NO tech and always
        return True.  For tech-gated buildings, the required tech must be
        is_unlocked=1.
        """
        if building_name not in TECH_GATED_BUILDINGS:
            return True
        required_tech = BUILDING_TECH_REQUIREMENTS[building_name]
        return self.is_unlocked(server_id, scenario_id, country_id, required_tech)

    def get_unlocked_techs(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> list[str]:
        """Return list of tech_ids that are fully unlocked."""
        rows = self._db.get_technologies_for_country(
            server_id, scenario_id, country_id
        )
        return [r["tech_id"] for r in rows if int(r.get("is_unlocked", 0))]

    def get_status(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict:
        """Return a dict of tech_id → status dict for all known techs."""
        rows = self._db.get_technologies_for_country(
            server_id, scenario_id, country_id
        )
        by_id = {r["tech_id"]: r for r in rows}
        result: dict[str, dict] = {}
        for tid, tdef in TECH_TREE.items():
            row = by_id.get(tid, {})
            result[tid] = {
                "name":             tdef.name,
                "is_unlocked":      bool(int(row.get("is_unlocked", 0))),
                "is_researching":   bool(int(row.get("is_researching", 0))),
                "research_end_day": int(row.get("research_end_day", 0)),
            }
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_no_active_research(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> str | None:
        """
        Return an error string if the country has any active research
        (tech OR reform), or None if the queue is free.
        """
        tech_row = self._db.get_active_research(
            server_id, scenario_id, country_id
        )
        if tech_row:
            return (
                f"Country is already researching tech '{tech_row['tech_id']}'. "
                f"Only one research item is allowed at a time."
            )
        reform_row = self._db.get_active_reform_research(
            server_id, scenario_id, country_id
        )
        if reform_row:
            return (
                f"Country is already researching reform '{reform_row['reform_id']}'. "
                f"Only one research item is allowed at a time."
            )
        return None
