"""
WW1 ECONOMY — RESOURCE & BUILDING DEFINITIONS
----------------------------------------------
All Tier 1 and Tier 2 resources for the WW1 scenario, plus complete
building configuration data-classes.

This module is pure data — no I/O, no database access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

class Tier1Resource(str, Enum):
    """Raw / natural resources extracted by Tier 1 buildings."""
    IRON   = "iron"
    COAL   = "coal"
    COPPER = "copper"
    STONE  = "stone"
    WOOD   = "wood"
    RUBBER = "rubber"
    GRAIN  = "grain"
    MEAT   = "meat"
    HORSES = "horses"
    COTTON = "cotton"
    OIL    = "oil"
    GOLD   = "gold"   # special: goes directly to treasury
    GEMS   = "gems"


class Tier2Resource(str, Enum):
    """Manufactured / processed resources produced by Tier 2 buildings."""
    TEXTILES    = "textiles"
    CHEMICALS   = "chemicals"
    GUNPOWDER   = "gunpowder"
    AMMUNITION  = "ammunition"
    MEDICINES   = "medicines"


# All resources that can be stored in country_storage.
#
# NOTE: gold, gems, horses and textiles are intentionally NOT stored:
#   * gold  → goes directly to treasury
#   * gems  → goes directly to treasury (Gems Mine = +30 gold/month)
#   * horses    → Ranch only contributes daily income; no inventory accrues
#   * textiles  → Textile Mill only contributes daily income; no inventory accrues
#
# We keep the legacy column names in country_storage so we don't break old DB
# files, but production never writes to them anymore.
STORABLE_RESOURCES: tuple[str, ...] = (
    "iron", "coal", "copper", "stone",
    "wood", "rubber",
    "grain", "meat",
    "horses",        # legacy column — no longer written by production
    "cotton",
    "oil",
    "gems",          # legacy column — no longer written by production
    "textiles",      # legacy column — no longer written by production
    "chemicals", "gunpowder", "ammunition", "medicines",
)

# Convenience set for fast membership checks
STORABLE_RESOURCE_SET: frozenset[str] = frozenset(STORABLE_RESOURCES)

# Resources that are produced by buildings but NEVER stored — they only feed
# the country's daily income (or, for gold/gems, treasury directly).
NON_STORABLE_PRODUCTS: frozenset[str] = frozenset({"horses", "textiles"})

ALL_RESOURCE_NAMES: frozenset[str] = frozenset(
    r.value for r in Tier1Resource
) | frozenset(r.value for r in Tier2Resource)


# ---------------------------------------------------------------------------
# Building tiers
# ---------------------------------------------------------------------------

class BuildingTier(str, Enum):
    TIER1 = "tier1"
    TIER2 = "tier2"
    INFRA = "infra"   # infrastructure: Hospital, Library, School, University


class BuildingType(str, Enum):
    """All building types for the WW1 scenario."""
    # Tier 1 — resource-dependent
    MINE              = "Mine"
    LOGGING_CAMP      = "Logging Camp"
    FARM              = "Farm"
    RANCH             = "Ranch"
    PLANTATION        = "Plantation"
    OIL_RIG           = "Oil Rig"
    PRECIOUS_MINE     = "Precious Mine"

    # Tier 2 — industrial, province-independent
    TEXTILE_MILL         = "Textile Mill"
    CHEMICAL_PLANT       = "Chemical Plant"
    POWDER_MILL          = "Powder Mill"
    ARMS_FACTORY         = "Arms Factory"
    PHARMACEUTICAL_PLANT = "Pharmaceutical Plant"

    # Infrastructure — requires tech unlock; no monthly consumption; coexist in province
    HOSPITAL   = "Hospital"
    LIBRARY    = "Library"
    SCHOOL     = "School"
    UNIVERSITY = "University"


# ---------------------------------------------------------------------------
# Building configuration
# ---------------------------------------------------------------------------

DAYS_PER_MONTH: int = 30


@dataclass(frozen=True)
class BuildingConfig:
    """
    Immutable specification for one building type.

    Parameters
    ----------
    building_type            : BuildingType
    tier                     : BuildingTier
    allowed_resources        : frozenset[str] — Tier 1 resources this building can extract.
                               Empty for Tier 2 buildings.
    construction_months      : int — construction duration in in-game months.
    construction_cost_gold   : float — one-time gold cost to start construction.
    daily_income             : float — gold added to treasury each in-game day once built.
    monthly_production       : int — units produced each in-game month.
    production_resource      : str | None — resource produced. None if production
                               depends on the province resource (Precious Mine gold).
    production_unit          : str — descriptive unit label (tons, barrels, horses…).
    gold_to_treasury_monthly : float — gold deposited to treasury monthly (Precious Mine gold).
    """
    building_type:           BuildingType
    tier:                    BuildingTier
    allowed_resources:       frozenset[str]
    construction_months:     int
    construction_cost_gold:  float
    daily_income:            float
    monthly_production:      int
    production_resource:     str | None     # None for gold branch of Precious Mine
    production_unit:         str
    gold_to_treasury_monthly: float = 0.0  # Only Precious Mine (gold resource) uses this
    # Resources consumed at construction start (deducted from country_storage).
    # Stored as tuple-of-pairs to preserve hashability of the frozen dataclass.
    # Example: (("stone", 25), ("wood", 15))
    construction_cost_resources: tuple[tuple[str, int], ...] = ()

    @property
    def construction_resources_dict(self) -> dict[str, int]:
        """Return construction_cost_resources as a plain dict for convenience."""
        return dict(self.construction_cost_resources)

    @property
    def construction_days(self) -> int:
        """Construction duration in in-game days."""
        return self.construction_months * DAYS_PER_MONTH

    @property
    def is_tier1(self) -> bool:
        return self.tier == BuildingTier.TIER1

    @property
    def is_tier2(self) -> bool:
        return self.tier == BuildingTier.TIER2

    @property
    def is_infra(self) -> bool:
        return self.tier == BuildingTier.INFRA

    def can_be_built_on(self, province_resource: str) -> bool:
        """
        Return True if this building may be constructed in a province
        whose natural resource is ``province_resource``.
        Tier 2 buildings always return True (province resource is irrelevant).
        """
        if self.is_tier2:
            return True
        return province_resource in self.allowed_resources


# ---------------------------------------------------------------------------
# Building catalogue
# ---------------------------------------------------------------------------

BUILDING_CONFIGS: dict[BuildingType, BuildingConfig] = {

    # ------------------------------------------------------------------ Tier 1
    BuildingType.MINE: BuildingConfig(
        building_type          = BuildingType.MINE,
        tier                   = BuildingTier.TIER1,
        allowed_resources      = frozenset({"iron", "coal", "copper", "stone"}),
        construction_months    = 3,
        construction_cost_gold = 60.0,
        daily_income           = 0.5,
        monthly_production     = 10,
        production_resource    = None,   # resolved from province resource at build time
        production_unit        = "tons",
    ),

    BuildingType.LOGGING_CAMP: BuildingConfig(
        building_type          = BuildingType.LOGGING_CAMP,
        tier                   = BuildingTier.TIER1,
        allowed_resources      = frozenset({"wood", "rubber"}),
        construction_months    = 4,
        construction_cost_gold = 80.0,
        daily_income           = 0.3,
        monthly_production     = 5,
        production_resource    = None,
        production_unit        = "logs",
    ),

    BuildingType.FARM: BuildingConfig(
        building_type          = BuildingType.FARM,
        tier                   = BuildingTier.TIER1,
        allowed_resources      = frozenset({"grain", "meat"}),
        construction_months    = 3,
        construction_cost_gold = 45.0,
        daily_income           = 0.3,
        monthly_production     = 30,
        production_resource    = None,
        production_unit        = "tons",
    ),

    BuildingType.RANCH: BuildingConfig(
        building_type          = BuildingType.RANCH,
        tier                   = BuildingTier.TIER1,
        allowed_resources      = frozenset({"horses"}),
        construction_months    = 8,
        construction_cost_gold = 70.0,
        daily_income           = 0.5,
        monthly_production     = 300,
        production_resource    = "horses",
        production_unit        = "horses",
    ),

    BuildingType.PLANTATION: BuildingConfig(
        building_type          = BuildingType.PLANTATION,
        tier                   = BuildingTier.TIER1,
        allowed_resources      = frozenset({"cotton"}),
        construction_months    = 12,
        construction_cost_gold = 75.0,
        daily_income           = 0.5,
        monthly_production     = 20,
        production_resource    = "cotton",
        production_unit        = "tons",
    ),

    BuildingType.OIL_RIG: BuildingConfig(
        building_type          = BuildingType.OIL_RIG,
        tier                   = BuildingTier.TIER1,
        allowed_resources      = frozenset({"oil"}),
        construction_months    = 18,
        construction_cost_gold = 150.0,
        daily_income           = 1.5,
        monthly_production     = 30,
        production_resource    = "oil",
        production_unit        = "barrels",
    ),

    BuildingType.PRECIOUS_MINE: BuildingConfig(
        building_type            = BuildingType.PRECIOUS_MINE,
        tier                     = BuildingTier.TIER1,
        allowed_resources        = frozenset({"gold", "gems"}),
        construction_months      = 18,
        construction_cost_gold   = 100.0,
        daily_income             = 2.5,
        monthly_production       = 10,  # gems branch; gold branch uses gold_to_treasury_monthly
        production_resource      = "gems",  # default; gold branch is handled separately
        production_unit          = "gems",
        gold_to_treasury_monthly = 25.0,  # only used when province_resource == "gold"
    ),

    # ------------------------------------------------------------------ Tier 2
    BuildingType.TEXTILE_MILL: BuildingConfig(
        building_type          = BuildingType.TEXTILE_MILL,
        tier                   = BuildingTier.TIER2,
        allowed_resources      = frozenset(),
        construction_months    = 6,
        construction_cost_gold = 50.0,
        daily_income           = 1.0,
        monthly_production     = 5,
        production_resource    = "textiles",
        production_unit        = "tons",
    ),

    BuildingType.CHEMICAL_PLANT: BuildingConfig(
        building_type          = BuildingType.CHEMICAL_PLANT,
        tier                   = BuildingTier.TIER2,
        allowed_resources      = frozenset(),
        construction_months    = 18,
        construction_cost_gold = 150.0,
        daily_income           = 0.5,
        monthly_production     = 5,
        production_resource    = "chemicals",
        production_unit        = "tons",
    ),

    BuildingType.POWDER_MILL: BuildingConfig(
        building_type          = BuildingType.POWDER_MILL,
        tier                   = BuildingTier.TIER2,
        allowed_resources      = frozenset(),
        construction_months    = 8,
        construction_cost_gold = 100.0,
        daily_income           = 0.3,
        monthly_production     = 15,
        production_resource    = "gunpowder",
        production_unit        = "tons",
    ),

    BuildingType.ARMS_FACTORY: BuildingConfig(
        building_type          = BuildingType.ARMS_FACTORY,
        tier                   = BuildingTier.TIER2,
        allowed_resources      = frozenset(),
        construction_months    = 6,
        construction_cost_gold = 60.0,
        daily_income           = 0.2,
        monthly_production     = 50,
        production_resource    = "ammunition",
        production_unit        = "stacks",
    ),

    BuildingType.PHARMACEUTICAL_PLANT: BuildingConfig(
        building_type          = BuildingType.PHARMACEUTICAL_PLANT,
        tier                   = BuildingTier.TIER2,
        allowed_resources      = frozenset(),
        construction_months    = 3,
        construction_cost_gold = 45.0,
        daily_income           = 0.2,
        monthly_production     = 50,
        production_resource    = "medicines",
        production_unit        = "stacks",
    ),

    # ------------------------------------------------------------ Infrastructure
    # Tech requirements are enforced by TechnologySystem via BUILDING_TECH_REQUIREMENTS.
    # These buildings have no monthly resource consumption and can coexist in a province.

    BuildingType.HOSPITAL: BuildingConfig(
        building_type               = BuildingType.HOSPITAL,
        tier                        = BuildingTier.INFRA,
        allowed_resources           = frozenset(),
        construction_months         = 4,
        construction_cost_gold      = 60.0,
        daily_income                = 0.0,
        monthly_production          = 0,
        production_resource         = None,
        production_unit             = "",
        construction_cost_resources = (("stone", 25), ("wood", 15)),
    ),

    BuildingType.LIBRARY: BuildingConfig(
        building_type               = BuildingType.LIBRARY,
        tier                        = BuildingTier.INFRA,
        allowed_resources           = frozenset(),
        construction_months         = 4,
        construction_cost_gold      = 40.0,
        daily_income                = 0.0,
        monthly_production          = 0,
        production_resource         = None,
        production_unit             = "",
        construction_cost_resources = (("wood", 20), ("stone", 5)),
    ),

    BuildingType.SCHOOL: BuildingConfig(
        building_type               = BuildingType.SCHOOL,
        tier                        = BuildingTier.INFRA,
        allowed_resources           = frozenset(),
        construction_months         = 6,
        construction_cost_gold      = 60.0,
        daily_income                = 0.0,
        monthly_production          = 0,
        production_resource         = None,
        production_unit             = "",
        construction_cost_resources = (("stone", 15), ("wood", 15)),
    ),

    BuildingType.UNIVERSITY: BuildingConfig(
        building_type               = BuildingType.UNIVERSITY,
        tier                        = BuildingTier.INFRA,
        allowed_resources           = frozenset(),
        construction_months         = 9,
        construction_cost_gold      = 90.0,
        daily_income                = 0.0,
        monthly_production          = 0,
        production_resource         = None,
        production_unit             = "",
        construction_cost_resources = (("wood", 30), ("stone", 20)),
    ),
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

# Which BuildingType is required for each Tier 1 resource?
RESOURCE_TO_TIER1_BUILDING: dict[str, BuildingType] = {}
for _btype, _cfg in BUILDING_CONFIGS.items():
    for _res in _cfg.allowed_resources:
        RESOURCE_TO_TIER1_BUILDING[_res] = _btype

# Tier 1, Tier 2, and infrastructure building type sets
TIER1_BUILDING_TYPES: frozenset[BuildingType] = frozenset(
    bt for bt, cfg in BUILDING_CONFIGS.items() if cfg.is_tier1
)
TIER2_BUILDING_TYPES: frozenset[BuildingType] = frozenset(
    bt for bt, cfg in BUILDING_CONFIGS.items() if cfg.is_tier2
)
INFRA_BUILDING_TYPES: frozenset[BuildingType] = frozenset(
    bt for bt, cfg in BUILDING_CONFIGS.items() if cfg.tier == BuildingTier.INFRA
)


def get_config(building_type: str | BuildingType) -> BuildingConfig:
    """
    Return the BuildingConfig for a given building type name or enum member.
    Raises ValueError for unrecognised names.
    """
    if isinstance(building_type, str):
        try:
            building_type = BuildingType(building_type)
        except ValueError:
            valid = ", ".join(f"'{b.value}'" for b in BuildingType)
            raise ValueError(
                f"Unknown building type '{building_type}'. Valid: {valid}"
            )
    return BUILDING_CONFIGS[building_type]


# ---------------------------------------------------------------------------
# Tier 2 monthly resource consumption (shared-pool model)
# ---------------------------------------------------------------------------
#
# The consumption system aggregates these requirements across every completed
# Tier 2 building of a country.  If the country's storage covers the TOTAL,
# every Tier 2 building activates for the month.  Otherwise NONE of them do.
#
# Tier 1 buildings consume nothing (they extract from raw province resources).

BUILDING_CONSUMPTION: dict[BuildingType, dict[str, int]] = {
    BuildingType.TEXTILE_MILL:        {"cotton": 5},
    BuildingType.CHEMICAL_PLANT:      {"oil": 3, "copper": 2},
    BuildingType.POWDER_MILL:         {"coal": 6, "oil": 2},
    BuildingType.ARMS_FACTORY:        {"iron": 10, "gunpowder": 5},
    BuildingType.PHARMACEUTICAL_PLANT: {"chemicals": 2, "rubber": 2},
}


def consumption_for(building_type: str | BuildingType) -> dict[str, int]:
    """Return the per-month resource requirement dict for a building.
    Returns ``{}`` for any building type with no consumption (all Tier 1)."""
    if isinstance(building_type, str):
        try:
            building_type = BuildingType(building_type)
        except ValueError:
            return {}
    return dict(BUILDING_CONSUMPTION.get(building_type, {}))


# ---------------------------------------------------------------------------
# Global market base prices
# ---------------------------------------------------------------------------
#
# Used by ww1_economy.market_system.GlobalMarketSystem.  All prices are
# expressed as gold-per-unit.  The market mutates a per-resource current_price
# but always remembers this base value for resets and bound checks.

MARKET_BASE_PRICES: dict[str, float] = {
    # Tier 1 commodities
    "iron":   6.0,
    "coal":   5.0,
    "copper": 7.0,
    "stone":  3.0,
    "wood":   4.0,
    "rubber": 6.0,
    "grain":  3.0,
    "meat":   5.0,
    "cotton": 5.0,
    "oil":    9.0,
    # Tier 2 finished goods
    "chemicals":  12.0,
    "gunpowder":  14.0,
    "ammunition": 18.0,
    "medicines":  16.0,
}

MARKET_RESOURCES: tuple[str, ...] = tuple(MARKET_BASE_PRICES.keys())
MARKET_RESOURCE_SET: frozenset[str] = frozenset(MARKET_RESOURCES)


def resolve_tier1_production_resource(
    building_type: BuildingType,
    province_resource: str,
) -> str | None:
    """
    Determine the storage resource produced by a Tier 1 building given the
    province's natural resource.

    Returns None for the gold branch of Precious Mine (output goes to treasury).
    Raises ValueError if the resource is incompatible with the building.
    """
    cfg = get_config(building_type)
    if province_resource not in cfg.allowed_resources:
        raise ValueError(
            f"Province resource '{province_resource}' is not compatible "
            f"with building '{building_type.value}'. "
            f"Allowed: {sorted(cfg.allowed_resources)}"
        )
    if building_type == BuildingType.PRECIOUS_MINE:
        # Gold → treasury only (no storage entry); gems → storage
        return None if province_resource == "gold" else "gems"
    # For all other Tier 1 buildings, the produced resource = province resource
    return province_resource
