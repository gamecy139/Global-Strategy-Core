"""
WW1 TROOP DEFINITION SYSTEM
-----------------------------
Manages the scenario-scoped ``troop_definitions`` table.

Responsibilities
----------------
1. **Seeding** — writes all entries from ``unit_data.UNIT_DEFINITIONS`` into
   the DB for a given (server_id, scenario_id) via ``seed_definitions()``.
   The operation is idempotent (uses INSERT OR IGNORE).

2. **Lookup** — retrieves unit definitions filtered by name, category, or
   required military tech.

3. **Validation** — checks whether a country may recruit a given unit by
   consulting MilitaryTechSystem.validate_recruitment().

All data is keyed by (server_id, scenario_id) for full multi-server
and multi-scenario isolation.  No global datasets; everything is
scenario-scoped.
"""

from __future__ import annotations

from dataclasses import dataclass

from ww1_economy.db                    import EconomyDB
from ww1_economy.unit_data             import UNIT_DEFINITIONS, UnitDef, UNIT_CATEGORIES
from ww1_economy.military_tech_data    import MILITARY_TECH_TREE
from ww1_economy.military_tech_system  import MilitaryTechSystem


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SeedResult:
    seeded:   int    # number of rows actually inserted (0 = already existed)
    total:    int    # total unit definitions processed
    scenario: str


@dataclass
class RecruitmentValidation:
    allowed:       bool
    reason:        str
    unit_name:     str
    required_tech: str
    gold_cost:     float
    population_required: int
    recruitment_time_days: int


# ---------------------------------------------------------------------------
# TroopDefinitionSystem
# ---------------------------------------------------------------------------

class TroopDefinitionSystem:
    """
    Manages scenario-scoped troop definitions and recruitment validation.

    Parameters
    ----------
    db : EconomyDB
        Shared database instance (must have been initialised via ``db.init()``).
    mil_tech : MilitaryTechSystem
        Military tech system used to check unlock status during validation.
    """

    def __init__(self, db: EconomyDB, mil_tech: MilitaryTechSystem) -> None:
        self._db       = db
        self._mil_tech = mil_tech

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    def seed_definitions(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> SeedResult:
        """
        Insert all unit definitions from ``unit_data.UNIT_DEFINITIONS`` into
        the ``troop_definitions`` table for this (server_id, scenario_id).

        Idempotent — existing rows are silently skipped (INSERT OR IGNORE).

        Returns
        -------
        SeedResult describing how many rows were inserted vs. skipped.
        """
        inserted = 0
        for udef in UNIT_DEFINITIONS.values():
            before = self._db.get_troop_definition(
                server_id, scenario_id, udef.unit_name
            )
            self._db.seed_troop_definition(
                server_id             = server_id,
                scenario_id           = scenario_id,
                unit_name             = udef.unit_name,
                category              = udef.category,
                required_tech         = udef.required_tech,
                population_required   = udef.population_required,
                gold_cost             = udef.gold_cost,
                recruitment_time_days = udef.recruitment_time_days,
                speed_modifier        = udef.speed_modifier,
                battle_points         = udef.battle_points,
            )
            if before is None:
                inserted += 1

        return SeedResult(
            seeded   = inserted,
            total    = len(UNIT_DEFINITIONS),
            scenario = scenario_id,
        )

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_unit(
        self,
        server_id:   str,
        scenario_id: str,
        unit_name:   str,
    ) -> dict | None:
        """Return the full definition row for a unit, or None if not seeded."""
        return self._db.get_troop_definition(server_id, scenario_id, unit_name)

    def get_all_units(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        """Return all unit definitions for this scenario, ordered by category then name."""
        return self._db.get_all_troop_definitions(server_id, scenario_id)

    def get_units_by_category(
        self,
        server_id:   str,
        scenario_id: str,
        category:    str,
    ) -> list[dict]:
        """
        Return all units in the given category (F1, F2, FL1, S1, S2, N1).

        Raises
        ------
        ValueError if category is not a recognised value.
        """
        if category not in UNIT_CATEGORIES:
            raise ValueError(
                f"Unknown category '{category}'. "
                f"Valid: {sorted(UNIT_CATEGORIES)}"
            )
        return self._db.get_troop_definitions_by_category(
            server_id, scenario_id, category
        )

    def get_units_unlocked_by_tech(
        self,
        server_id:   str,
        scenario_id: str,
        tech_id:     str,
    ) -> list[dict]:
        """Return all unit definitions whose required_tech matches tech_id."""
        if tech_id not in MILITARY_TECH_TREE:
            raise ValueError(
                f"Unknown military tech_id '{tech_id}'. "
                f"Valid: {sorted(MILITARY_TECH_TREE)}"
            )
        return self._db.get_troop_definitions_by_tech(server_id, scenario_id, tech_id)

    def get_recruitable_units(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> list[dict]:
        """
        Return all unit definitions that the country can currently recruit
        (i.e. their required tech is unlocked).
        """
        all_units = self._db.get_all_troop_definitions(server_id, scenario_id)
        recruitable = []
        for unit in all_units:
            ok, _ = self._mil_tech.validate_recruitment(
                server_id, scenario_id, country_id, unit["unit_name"]
            )
            if ok:
                recruitable.append(unit)
        return recruitable

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_recruitment(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        unit_name:   str,
    ) -> RecruitmentValidation:
        """
        Full recruitment gate check for a country attempting to recruit
        ``unit_name``.

        Checks (in order)
        -----------------
        1. Unit definitions have been seeded for this scenario.
        2. The unit's required military tech is unlocked by the country.

        Returns
        -------
        RecruitmentValidation with ``allowed=True`` if recruitment is allowed,
        or ``allowed=False`` with a human-readable ``reason``.
        """
        unit_row = self._db.get_troop_definition(server_id, scenario_id, unit_name)
        if unit_row is None:
            return RecruitmentValidation(
                allowed               = False,
                reason                = (
                    f"Unit '{unit_name}' not found in scenario '{scenario_id}'. "
                    f"Call seed_definitions() first."
                ),
                unit_name             = unit_name,
                required_tech         = "",
                gold_cost             = 0.0,
                population_required   = 0,
                recruitment_time_days = 0,
            )

        ok, reason = self._mil_tech.validate_recruitment(
            server_id, scenario_id, country_id, unit_name
        )
        return RecruitmentValidation(
            allowed               = ok,
            reason                = reason if not ok else "Recruitment allowed.",
            unit_name             = unit_name,
            required_tech         = unit_row["required_tech"],
            gold_cost             = float(unit_row["gold_cost"]),
            population_required   = int(unit_row["population_required"]),
            recruitment_time_days = int(unit_row["recruitment_time_days"]),
        )

    # ------------------------------------------------------------------
    # Summary helpers
    # ------------------------------------------------------------------

    def get_category_summary(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> dict[str, list[str]]:
        """
        Return a dict of category → [unit_name, ...] for all seeded units.
        """
        summary: dict[str, list[str]] = {cat: [] for cat in sorted(UNIT_CATEGORIES)}
        for row in self._db.get_all_troop_definitions(server_id, scenario_id):
            summary.setdefault(row["category"], []).append(row["unit_name"])
        return summary
