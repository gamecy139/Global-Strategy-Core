"""
WW1 MILITARY TECHNOLOGY SYSTEM
--------------------------------
Manages military technology research progression and unlock checks.

This is a SEPARATE system from the economic TechnologySystem.  Military
research runs on its own queue — one active military research per country
at a time, independent of economic tech or reform research.

Database tables used
---------------------
  military_technologies — per-country military tech research state.

All data is keyed by (server_id, scenario_id) for full multi-server
and multi-scenario isolation.

Research queue
--------------
Only ONE active military research is allowed per country at a time.
The queue is enforced against the ``military_technologies`` table only;
it does not interact with the economic ``technologies`` or ``reforms`` tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ww1_economy.db                 import EconomyDB
from ww1_economy.military_tech_data import (
    MilTechDef,
    MILITARY_TECH_TREE,
    UNIT_TECH_REQUIREMENTS,
    TECH_GATED_UNITS,
)
from ww1_economy.tech_data import DAYS_PER_MONTH


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class StartMilResearchResult:
    allowed:    bool
    reason:     str
    tech_id:    str = ""
    start_day:  int = 0
    end_day:    int = 0
    duration_days: int = 0


@dataclass
class MilResearchCompletionEvent:
    country_id:    str
    tech_id:       str
    name:          str
    unlocked_units: list[str]
    unlocked_techs: list[str]   # child tech_ids now researchable


@dataclass
class MilTechStatus:
    tech_id:        str
    name:           str
    is_unlocked:    bool
    is_researching: bool
    research_start_day:     int
    research_duration_days: int
    research_end_day:       int
    prerequisites:  list[str]
    unlocks_units:  list[str]


# ---------------------------------------------------------------------------
# MilitaryTechSystem
# ---------------------------------------------------------------------------

class MilitaryTechSystem:
    """
    Manages the full military technology research lifecycle.

    Parameters
    ----------
    db : EconomyDB
        Shared database instance (must have been initialised via ``db.init()``).
    """

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
    ) -> StartMilResearchResult:
        """
        Begin researching a military technology.

        Rules enforced
        --------------
        1. tech_id must exist in MILITARY_TECH_TREE.
        2. Tech must not already be unlocked.
        3. No active military research already in progress for this country.
        4. All prerequisite techs must already be is_unlocked.
        5. research_end_day = current_day + duration_days (no speed modifier;
           military research runs at a fixed rate, unlike economic research
           which benefits from infrastructure bonuses).

        Returns
        -------
        StartMilResearchResult with ``allowed=True`` on success.
        """
        if tech_id not in MILITARY_TECH_TREE:
            return StartMilResearchResult(
                allowed=False,
                reason=(
                    f"Unknown military tech_id '{tech_id}'. "
                    f"Valid: {sorted(MILITARY_TECH_TREE)}"
                ),
            )

        tdef = MILITARY_TECH_TREE[tech_id]

        row = self._db.get_military_technology(
            server_id, scenario_id, country_id, tech_id
        )
        if row and int(row.get("is_unlocked", 0)):
            return StartMilResearchResult(
                allowed=False,
                reason=f"Military tech '{tech_id}' is already unlocked.",
                tech_id=tech_id,
            )

        block = self._ensure_no_active_research(server_id, scenario_id, country_id)
        if block:
            return StartMilResearchResult(
                allowed=False, reason=block, tech_id=tech_id
            )

        for prereq in tdef.prerequisites:
            prereq_row = self._db.get_military_technology(
                server_id, scenario_id, country_id, prereq
            )
            if not prereq_row or not int(prereq_row.get("is_unlocked", 0)):
                return StartMilResearchResult(
                    allowed=False,
                    reason=f"Prerequisite military tech '{prereq}' is not yet unlocked.",
                    tech_id=tech_id,
                )

        duration_days = tdef.duration_days
        end_day       = current_day + duration_days

        self._db.upsert_military_technology(
            server_id              = server_id,
            scenario_id            = scenario_id,
            country_id             = country_id,
            tech_id                = tech_id,
            is_unlocked            = False,
            is_researching         = True,
            research_start_day     = current_day,
            research_duration_days = duration_days,
            research_end_day       = end_day,
        )

        return StartMilResearchResult(
            allowed      = True,
            reason       = "Military research started.",
            tech_id      = tech_id,
            start_day    = current_day,
            end_day      = end_day,
            duration_days = duration_days,
        )

    # ------------------------------------------------------------------
    # Research — daily completion processing
    # ------------------------------------------------------------------

    def process_completions(
        self,
        server_id:   str,
        scenario_id: str,
        current_day: int,
    ) -> list[MilResearchCompletionEvent]:
        """
        Check all in-progress military research for this scenario and complete
        any that have reached their research_end_day.

        Call once per game day (or from TickSystem.daily_tick).
        Returns completion events for every tech completed in this call.
        """
        events: list[MilResearchCompletionEvent] = []
        for row in self._db.get_researching_military_techs_for_scenario(
            server_id, scenario_id
        ):
            if current_day >= int(row["research_end_day"]):
                tid  = row["tech_id"]
                cid  = row["country_id"]
                tdef = MILITARY_TECH_TREE.get(tid)
                if tdef is None:
                    continue
                self._db.complete_military_technology(
                    server_id, scenario_id, cid, tid
                )
                # Determine which child techs are now researchable
                child_techs = self._get_newly_researchable(
                    server_id, scenario_id, cid, tid
                )
                events.append(MilResearchCompletionEvent(
                    country_id     = cid,
                    tech_id        = tid,
                    name           = tdef.name,
                    unlocked_units = list(tdef.unlocks_units),
                    unlocked_techs = child_techs,
                ))
        return events

    # ------------------------------------------------------------------
    # Unlock checks
    # ------------------------------------------------------------------

    def is_tech_unlocked(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        tech_id:     str,
    ) -> bool:
        """Return True if the given military tech is fully unlocked."""
        row = self._db.get_military_technology(
            server_id, scenario_id, country_id, tech_id
        )
        if row is None:
            return False
        return bool(int(row.get("is_unlocked", 0)))

    def is_unit_recruitable(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        unit_name:   str,
    ) -> bool:
        """
        Return True if ``unit_name`` can be recruited by this country.

        Units not in TECH_GATED_UNITS do not need a tech (always True).
        For gated units the required military tech must be is_unlocked=1.
        """
        if unit_name not in TECH_GATED_UNITS:
            return True
        required_tech = UNIT_TECH_REQUIREMENTS[unit_name]
        return self.is_tech_unlocked(server_id, scenario_id, country_id, required_tech)

    def validate_recruitment(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        unit_name:   str,
    ) -> tuple[bool, str]:
        """
        Validate that a country may recruit the given unit.

        Returns
        -------
        (True, "") if recruitment is allowed.
        (False, reason_string) if blocked.
        """
        unit_row = self._db.get_troop_definition(server_id, scenario_id, unit_name)
        if unit_row is None:
            return False, (
                f"Unit '{unit_name}' is not defined for this scenario. "
                f"Call TroopDefinitionSystem.seed_definitions() first."
            )
        required_tech = unit_row["required_tech"]
        if not self.is_tech_unlocked(server_id, scenario_id, country_id, required_tech):
            return False, (
                f"Cannot recruit '{unit_name}': "
                f"required military tech '{required_tech}' is not yet unlocked."
            )
        return True, ""

    # ------------------------------------------------------------------
    # Status / queries
    # ------------------------------------------------------------------

    def get_unlocked_techs(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> list[str]:
        """Return list of military tech_ids that are fully unlocked."""
        rows = self._db.get_military_technologies_for_country(
            server_id, scenario_id, country_id
        )
        return [r["tech_id"] for r in rows if int(r.get("is_unlocked", 0))]

    def get_status(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict[str, MilTechStatus]:
        """
        Return a status dict mapping tech_id → MilTechStatus for every
        military technology in the tree.
        """
        rows    = self._db.get_military_technologies_for_country(
            server_id, scenario_id, country_id
        )
        by_id   = {r["tech_id"]: r for r in rows}
        result: dict[str, MilTechStatus] = {}
        for tid, tdef in MILITARY_TECH_TREE.items():
            row = by_id.get(tid, {})
            result[tid] = MilTechStatus(
                tech_id                = tid,
                name                   = tdef.name,
                is_unlocked            = bool(int(row.get("is_unlocked", 0))),
                is_researching         = bool(int(row.get("is_researching", 0))),
                research_start_day     = int(row.get("research_start_day", 0)),
                research_duration_days = int(row.get("research_duration_days", 0)),
                research_end_day       = int(row.get("research_end_day", 0)),
                prerequisites          = list(tdef.prerequisites),
                unlocks_units          = list(tdef.unlocks_units),
            )
        return result

    def get_active_research(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict | None:
        """Return the active military research row for a country, or None."""
        return self._db.get_active_military_research(
            server_id, scenario_id, country_id
        )

    def get_researchable_techs(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> list[str]:
        """
        Return all tech_ids that are currently researchable for a country:
        not yet unlocked, not currently researching, and all prerequisites met.
        """
        unlocked = set(self.get_unlocked_techs(server_id, scenario_id, country_id))
        rows     = self._db.get_military_technologies_for_country(
            server_id, scenario_id, country_id
        )
        researching = {
            r["tech_id"] for r in rows if int(r.get("is_researching", 0))
        }
        available: list[str] = []
        for tid, tdef in MILITARY_TECH_TREE.items():
            if tid in unlocked or tid in researching:
                continue
            if all(p in unlocked for p in tdef.prerequisites):
                available.append(tid)
        return sorted(available)

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
        Return an error string if the country already has active military
        research, or None if the queue is free.
        """
        active = self._db.get_active_military_research(
            server_id, scenario_id, country_id
        )
        if active:
            return (
                f"Country is already researching military tech "
                f"'{active['tech_id']}'. "
                f"Only one military research item is allowed at a time."
            )
        return None

    def _get_newly_researchable(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        just_completed: str,
    ) -> list[str]:
        """
        After completing ``just_completed``, return child tech_ids whose
        prerequisites are now all satisfied.
        """
        unlocked = set(self.get_unlocked_techs(server_id, scenario_id, country_id))
        unlocked.add(just_completed)
        newly: list[str] = []
        for tid, tdef in MILITARY_TECH_TREE.items():
            if tid in unlocked:
                continue
            if just_completed in tdef.prerequisites:
                if all(p in unlocked for p in tdef.prerequisites):
                    newly.append(tid)
        return sorted(newly)
