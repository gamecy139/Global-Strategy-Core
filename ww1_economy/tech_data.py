"""
WW1 TECHNOLOGY — STATIC TREE DEFINITIONS
------------------------------------------
Pure data module.  No I/O, no database access.

Defines the technology tree, reform tree, and the mapping from technology
unlocks → buildable buildings.  All durations are expressed in in-game months;
use TechDef.duration_days / ReformDef.duration_days for day-based arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass

DAYS_PER_MONTH: int = 30


# ---------------------------------------------------------------------------
# Technology definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TechDef:
    """Immutable definition of one technology node."""

    tech_id:          str
    name:             str
    duration_months:  int
    prerequisites:    tuple[str, ...]   # tech_ids that must be unlocked first
    unlocks_buildings: tuple[str, ...]  # BuildingType.value strings unlocked on completion
    unlocks_techs:    tuple[str, ...]   # tech_ids that become researchable on completion

    @property
    def duration_days(self) -> int:
        return self.duration_months * DAYS_PER_MONTH


# ---------------------------------------------------------------------------
# Reform definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReformDef:
    """Immutable definition of one reform."""

    reform_id:       str
    name:            str
    duration_months: int
    prerequisites:   tuple[str, ...]   # reform_ids that must be unlocked first

    # Numeric effects applied while adopted (0 = no effect)
    opinion_bonus:                  int   = 0
    economy_efficiency_pct:         float = 0.0  # e.g. +5.0 → +5%
    recruitment_cost_pct:           float = 0.0  # e.g. -10.0 → -10%
    population_growth_pct:          float = 0.0  # e.g. -2.0 → -2%
    non_core_conversion_cost_pct:   float = 0.0  # e.g. -10.0 → -10%

    # Constraint flags (applied while adopted)
    blocks_war_declaration:   bool = False  # country cannot declare war
    cannot_adopt_during_war:  bool = False  # adoption blocked while in_active_war

    @property
    def duration_days(self) -> int:
        return self.duration_months * DAYS_PER_MONTH


# ---------------------------------------------------------------------------
# Technology tree
# ---------------------------------------------------------------------------

TECH_TREE: dict[str, TechDef] = {

    # ── Economic branch ──────────────────────────────────────────────────────

    "industrialization": TechDef(
        tech_id          = "industrialization",
        name             = "Industrialization",
        duration_months  = 3,
        prerequisites    = (),
        unlocks_buildings = (),
        unlocks_techs    = ("chemical_processing",),
    ),

    "chemical_processing": TechDef(
        tech_id          = "chemical_processing",
        name             = "Chemical Processing",
        duration_months  = 6,
        prerequisites    = ("industrialization",),
        unlocks_buildings = (
            "Powder Mill",
            "Arms Factory",
            "Pharmaceutical Plant",
        ),
        unlocks_techs    = (),
    ),

    # ── Infrastructure branch ─────────────────────────────────────────────────

    "early_modern_infrastructure": TechDef(
        tech_id          = "early_modern_infrastructure",
        name             = "Early Modern Infrastructure",
        duration_months  = 1,
        prerequisites    = (),
        unlocks_buildings = ("Hospital", "Library"),
        unlocks_techs    = ("library",),
    ),

    "library": TechDef(
        tech_id          = "library",
        name             = "Library",
        duration_months  = 6,
        prerequisites    = ("early_modern_infrastructure",),
        unlocks_buildings = ("School",),
        unlocks_techs    = ("school",),
    ),

    "school": TechDef(
        tech_id          = "school",
        name             = "School",
        duration_months  = 6,
        prerequisites    = ("library",),
        unlocks_buildings = ("University",),
        unlocks_techs    = ("university",),
    ),

    "university": TechDef(
        tech_id          = "university",
        name             = "University",
        duration_months  = 12,
        prerequisites    = ("school",),
        unlocks_buildings = (),
        unlocks_techs    = (),
    ),
}


# ---------------------------------------------------------------------------
# Reform tree
# ---------------------------------------------------------------------------

REFORM_TREE: dict[str, ReformDef] = {

    "foundational_governance": ReformDef(
        reform_id        = "foundational_governance",
        name             = "Foundational Governance",
        duration_months  = 3,
        prerequisites    = (),
    ),

    "national_identity_program": ReformDef(
        reform_id                    = "national_identity_program",
        name                         = "National Identity Program",
        duration_months              = 6,
        prerequisites                = (),
        opinion_bonus                = 2,
        non_core_conversion_cost_pct = -10.0,
    ),

    "women_rights": ReformDef(
        reform_id           = "women_rights",
        name                = "Women Rights",
        duration_months     = 6,
        prerequisites       = (),
        opinion_bonus       = 5,
        population_growth_pct = -2.0,
    ),

    "war_mobilization_act": ReformDef(
        reform_id             = "war_mobilization_act",
        name                  = "War Mobilization Act",
        duration_months       = 12,
        prerequisites         = (),
        recruitment_cost_pct  = -10.0,
    ),

    "banking_system": ReformDef(
        reform_id       = "banking_system",
        name            = "Banking System",
        duration_months = 6,
        prerequisites   = (),
        opinion_bonus   = 2,
    ),

    "central_banking_system": ReformDef(
        reform_id               = "central_banking_system",
        name                    = "Central Banking System",
        duration_months         = 24,
        prerequisites           = ("banking_system",),
        opinion_bonus           = 3,
        economy_efficiency_pct  = 5.0,
    ),

    "civil_rights_framework": ReformDef(
        reform_id              = "civil_rights_framework",
        name                   = "Civil Rights Framework",
        duration_months        = 6,
        prerequisites          = (),
        opinion_bonus          = 2,
        economy_efficiency_pct = -3.0,
    ),

    "no_offence_policy": ReformDef(
        reform_id              = "no_offence_policy",
        name                   = "No Offence Policy",
        duration_months        = 12,
        prerequisites          = (),
        opinion_bonus          = 10,
        recruitment_cost_pct   = 5.0,
        blocks_war_declaration = True,
        cannot_adopt_during_war = True,
    ),
}


# ---------------------------------------------------------------------------
# Derived lookups
# ---------------------------------------------------------------------------

# Maps building_type_name → tech_id required before that building can be built.
# Built from TECH_TREE.unlocks_buildings; buildings NOT listed here need no tech.
BUILDING_TECH_REQUIREMENTS: dict[str, str] = {}
for _tid, _tdef in TECH_TREE.items():
    for _bname in _tdef.unlocks_buildings:
        BUILDING_TECH_REQUIREMENTS[_bname] = _tid

# Quick frozenset for O(1) membership checks
TECH_GATED_BUILDINGS: frozenset[str] = frozenset(BUILDING_TECH_REQUIREMENTS)

# Research-speed bonus contributed per completed infra building type (in %)
RESEARCH_SPEED_BONUSES: dict[str, float] = {
    "Library":    0.5,
    "School":     1.0,
    "University": 1.5,
}

# Adoption cost for every reform (gold)
REFORM_ADOPTION_COST: float = 100.0

# Maximum simultaneously adopted reforms per country
MAX_ADOPTED_REFORMS: int = 3
