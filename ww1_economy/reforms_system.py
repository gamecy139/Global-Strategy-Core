"""
WW1 ECONOMY — REFORMS SYSTEM
------------------------------
Manages research, unlocking, and adoption of political/economic reforms.

Lifecycle
---------
  start_research_reform()  → sets is_researching=1, research timing
  process_completions()    → when research_end_day reached → is_unlocked=1
  adopt_reform()           → spends 100 gold, sets is_adopted=1 (max 3)
  unadopt_reform()         → clears is_adopted (no refund)

Effects
-------
  compute_effects()        → aggregates bonuses from all adopted reforms.
  Reforms that are UNLOCKED but not ADOPTED apply no effects.

Shared research queue
---------------------
Only ONE item (tech OR reform) may be actively researched per country.
This constraint is checked jointly with TechnologySystem.

All data is keyed by (server_id, scenario_id) for full multi-server
and multi-scenario isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ww1_economy.db        import EconomyDB
from ww1_economy.treasury_system import TreasurySystem
from ww1_economy.tech_data  import (
    ReformDef,
    REFORM_TREE,
    REFORM_ADOPTION_COST,
    MAX_ADOPTED_REFORMS,
    DAYS_PER_MONTH,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class StartReformResearchResult:
    allowed:     bool
    reason:      str
    reform_id:   str   = ""
    start_day:   int   = 0
    end_day:     int   = 0
    speed_used:  float = 0.0


@dataclass
class AdoptReformResult:
    allowed:       bool
    reason:        str
    reform_id:     str   = ""
    gold_spent:    float = 0.0
    treasury_after: float = 0.0
    adopted_count: int   = 0


@dataclass
class ReformCompletionEvent:
    country_id: str
    reform_id:  str
    name:       str


@dataclass
class ReformEffects:
    """Aggregate effects of all currently adopted reforms."""
    opinion_bonus:                int   = 0
    economy_efficiency_pct:       float = 0.0
    recruitment_cost_pct:         float = 0.0
    population_growth_pct:        float = 0.0
    non_core_conversion_cost_pct: float = 0.0
    blocks_war_declaration:       bool  = False
    adopted_reform_ids:           list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ReformsSystem
# ---------------------------------------------------------------------------

class ReformsSystem:
    """
    Manages political and economic reform research, unlocking, and adoption.

    Parameters
    ----------
    db : EconomyDB
        Shared database instance (must have been initialised via ``db.init()``).
    treasury : TreasurySystem
        Used to deduct the adoption cost (100 gold).
    """

    def __init__(self, db: EconomyDB, treasury: TreasurySystem) -> None:
        self._db      = db
        self._treasury = treasury

    # ------------------------------------------------------------------
    # Reform research — start
    # ------------------------------------------------------------------

    def start_research_reform(
        self,
        server_id:    str,
        scenario_id:  str,
        country_id:   str,
        reform_id:    str,
        current_day:  int,
        research_speed_pct: float = 1.0,
    ) -> StartReformResearchResult:
        """
        Begin researching a reform.

        Parameters
        ----------
        research_speed_pct : float
            Current research speed in % — supplied by the caller from
            TechnologySystem.compute_research_speed().final_speed.

        Rules enforced
        --------------
        1. reform_id must exist in REFORM_TREE.
        2. No active research (tech OR reform) for this country.
        3. All prerequisite reforms must be is_unlocked.
        4. Reform must not already be unlocked.
        """
        if reform_id not in REFORM_TREE:
            return StartReformResearchResult(
                allowed=False,
                reason=f"Unknown reform_id '{reform_id}'. "
                       f"Valid: {sorted(REFORM_TREE)}",
            )

        rdef = REFORM_TREE[reform_id]

        # Already unlocked?
        row = self._db.get_reform(server_id, scenario_id, country_id, reform_id)
        if row and int(row.get("is_unlocked", 0)):
            return StartReformResearchResult(
                allowed=False,
                reason=f"'{reform_id}' is already unlocked.",
                reform_id=reform_id,
            )

        # Active research in either queue?
        block = self._ensure_no_active_research(server_id, scenario_id, country_id)
        if block:
            return StartReformResearchResult(
                allowed=False, reason=block, reform_id=reform_id
            )

        # Prerequisites met?
        for prereq in rdef.prerequisites:
            prereq_row = self._db.get_reform(
                server_id, scenario_id, country_id, prereq
            )
            if not prereq_row or not int(prereq_row.get("is_unlocked", 0)):
                return StartReformResearchResult(
                    allowed=False,
                    reason=f"Prerequisite reform '{prereq}' is not yet unlocked.",
                    reform_id=reform_id,
                )

        # Compute end day (same formula as TechnologySystem)
        speed = max(0.5, research_speed_pct)
        effective_days = int(rdef.duration_days / (speed / 100.0))
        end_day = current_day + effective_days

        # Persist
        self._db.upsert_reform(
            server_id          = server_id,
            scenario_id        = scenario_id,
            country_id         = country_id,
            reform_id          = reform_id,
            is_unlocked        = False,
            is_adopted         = False,
            is_researching     = True,
            research_start_day = current_day,
            research_end_day   = end_day,
        )

        return StartReformResearchResult(
            allowed    = True,
            reason     = "Reform research started.",
            reform_id  = reform_id,
            start_day  = current_day,
            end_day    = end_day,
            speed_used = speed,
        )

    # ------------------------------------------------------------------
    # Reform research — daily process
    # ------------------------------------------------------------------

    def process_completions(
        self,
        server_id:   str,
        scenario_id: str,
        current_day: int,
    ) -> list[ReformCompletionEvent]:
        """
        Check all in-progress reform research and complete any that have
        reached their research_end_day.

        Returns completion events for all reforms completed in this call.
        """
        events: list[ReformCompletionEvent] = []
        for row in self._db.get_researching_reforms_for_scenario(
            server_id, scenario_id
        ):
            if current_day >= int(row["research_end_day"]):
                rid = row["reform_id"]
                cid = row["country_id"]
                rdef = REFORM_TREE.get(rid)
                if rdef is None:
                    continue
                self._db.complete_reform(server_id, scenario_id, cid, rid)
                events.append(ReformCompletionEvent(
                    country_id = cid,
                    reform_id  = rid,
                    name       = rdef.name,
                ))
        return events

    # ------------------------------------------------------------------
    # Adoption
    # ------------------------------------------------------------------

    def adopt_reform(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        reform_id:   str,
    ) -> AdoptReformResult:
        """
        Adopt a previously-unlocked reform.

        Rules
        -----
        • Reform must be is_unlocked.
        • Reform must not already be is_adopted.
        • Adopted count must be < MAX_ADOPTED_REFORMS (3).
        • "No Offence Policy" cannot be adopted during war.
        • Costs REFORM_ADOPTION_COST (100) gold from treasury.
        """
        if reform_id not in REFORM_TREE:
            return AdoptReformResult(
                allowed=False,
                reason=f"Unknown reform_id '{reform_id}'.",
            )
        rdef = REFORM_TREE[reform_id]

        row = self._db.get_reform(server_id, scenario_id, country_id, reform_id)
        if row is None or not int(row.get("is_unlocked", 0)):
            return AdoptReformResult(
                allowed=False,
                reason=f"Reform '{reform_id}' is not yet unlocked.",
                reform_id=reform_id,
            )

        if int(row.get("is_adopted", 0)):
            return AdoptReformResult(
                allowed=False,
                reason=f"Reform '{reform_id}' is already adopted.",
                reform_id=reform_id,
            )

        # Max active reforms check
        adopted = self._db.get_adopted_reforms(server_id, scenario_id, country_id)
        if len(adopted) >= MAX_ADOPTED_REFORMS:
            return AdoptReformResult(
                allowed=False,
                reason=(
                    f"Cannot adopt more than {MAX_ADOPTED_REFORMS} reforms "
                    f"simultaneously. Currently at {len(adopted)}."
                ),
                reform_id=reform_id,
                adopted_count=len(adopted),
            )

        # War-restricted adoption
        if rdef.cannot_adopt_during_war:
            country_row = self._db.get_country(
                server_id, scenario_id, country_id
            )
            if country_row and int(country_row.get("in_active_war", 0)):
                return AdoptReformResult(
                    allowed=False,
                    reason=(
                        f"'{rdef.name}' cannot be adopted while at war."
                    ),
                    reform_id=reform_id,
                )

        # Treasury deduction
        success, balance = self._treasury.deduct(
            server_id, scenario_id, country_id, REFORM_ADOPTION_COST
        )
        if not success:
            return AdoptReformResult(
                allowed=False,
                reason=(
                    f"Insufficient treasury. Adoption costs "
                    f"{REFORM_ADOPTION_COST:.0f} gold; "
                    f"country has {balance:.2f} gold."
                ),
                reform_id=reform_id,
                treasury_after=balance,
            )

        # Adopt
        self._db.adopt_reform(server_id, scenario_id, country_id, reform_id)
        adopted_after = len(adopted) + 1

        return AdoptReformResult(
            allowed        = True,
            reason         = "Reform adopted successfully.",
            reform_id      = reform_id,
            gold_spent     = REFORM_ADOPTION_COST,
            treasury_after = balance,
            adopted_count  = adopted_after,
        )

    def unadopt_reform(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        reform_id:   str,
    ) -> dict:
        """Remove the adopted flag from a reform (no gold refund)."""
        row = self._db.get_reform(server_id, scenario_id, country_id, reform_id)
        if row is None or not int(row.get("is_adopted", 0)):
            return {"allowed": False, "reason": f"'{reform_id}' is not currently adopted."}
        self._db.unadopt_reform(server_id, scenario_id, country_id, reform_id)
        return {"allowed": True, "reason": f"'{reform_id}' removed from active reforms."}

    # ------------------------------------------------------------------
    # Effects
    # ------------------------------------------------------------------

    def compute_effects(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> ReformEffects:
        """
        Aggregate the effects of all currently adopted reforms.
        Only ADOPTED reforms contribute; UNLOCKED-but-not-adopted do not.
        """
        adopted_rows = self._db.get_adopted_reforms(
            server_id, scenario_id, country_id
        )
        effects = ReformEffects()
        for row in adopted_rows:
            rid = row["reform_id"]
            if rid not in REFORM_TREE:
                continue
            rdef = REFORM_TREE[rid]
            effects.opinion_bonus                  += rdef.opinion_bonus
            effects.economy_efficiency_pct         += rdef.economy_efficiency_pct
            effects.recruitment_cost_pct           += rdef.recruitment_cost_pct
            effects.population_growth_pct          += rdef.population_growth_pct
            effects.non_core_conversion_cost_pct   += rdef.non_core_conversion_cost_pct
            if rdef.blocks_war_declaration:
                effects.blocks_war_declaration = True
            effects.adopted_reform_ids.append(rid)
        return effects

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_status(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict:
        """Return a dict of reform_id → status dict for all known reforms."""
        rows = self._db.get_reforms_for_country(
            server_id, scenario_id, country_id
        )
        by_id = {r["reform_id"]: r for r in rows}
        result: dict[str, dict] = {}
        for rid, rdef in REFORM_TREE.items():
            row = by_id.get(rid, {})
            result[rid] = {
                "name":             rdef.name,
                "is_unlocked":      bool(int(row.get("is_unlocked", 0))),
                "is_adopted":       bool(int(row.get("is_adopted", 0))),
                "is_researching":   bool(int(row.get("is_researching", 0))),
                "research_end_day": int(row.get("research_end_day", 0)),
            }
        return result

    def is_war_declaration_blocked(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> bool:
        """Return True if any adopted reform blocks war declaration."""
        effects = self.compute_effects(server_id, scenario_id, country_id)
        return effects.blocks_war_declaration

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_no_active_research(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> str | None:
        """Return an error string if the country has any active research."""
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
                f"Country is already researching reform "
                f"'{reform_row['reform_id']}'. "
                f"Only one research item is allowed at a time."
            )
        return None
