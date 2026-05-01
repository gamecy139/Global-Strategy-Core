"""
WW1 Economy System — Backend Package
--------------------------------------
Modular economy backend for the WW1 grand strategy scenario.

Systems
-------
  StorageSystem               — country resource storage
  TreasurySystem              — country gold balance (never negative)
  BuildingSystem              — construction (treasury + tech + resource aware)
  ResourceConsumptionSystem   — monthly shared-pool consumption
  ProductionSystem            — monthly production (active-only, gold→treasury)
  GlobalMarketSystem          — buy/sell with shortage + dynamic prices
  EconomyEfficiencySystem     — bounded efficiency multiplier (0.5–1.3)
  TechnologySystem            — research progression, speed, unlock checks
  ReformsSystem               — reform research, unlock, adoption, effects
  TickSystem                  — daily + monthly orchestrator (wires all above)

Resources
---------
  Tier1Resource, Tier2Resource, BuildingType, BUILDING_CONFIGS,
  BUILDING_CONSUMPTION, MARKET_BASE_PRICES, NON_STORABLE_PRODUCTS

Technology
----------
  TechDef, ReformDef, TECH_TREE, REFORM_TREE,
  BUILDING_TECH_REQUIREMENTS, TECH_GATED_BUILDINGS,
  RESEARCH_SPEED_BONUSES, REFORM_ADOPTION_COST, MAX_ADOPTED_REFORMS

Database
--------
  EconomyDB — SQLite layer for buildings, country_storage, countries,
  provinces, global_market, technologies, reforms.
"""

from .db                  import EconomyDB
from .resources           import (
    Tier1Resource,
    Tier2Resource,
    BuildingType,
    BuildingTier,
    BuildingConfig,
    BUILDING_CONFIGS,
    BUILDING_CONSUMPTION,
    STORABLE_RESOURCES,
    NON_STORABLE_PRODUCTS,
    MARKET_BASE_PRICES,
    MARKET_RESOURCES,
    RESOURCE_TO_TIER1_BUILDING,
    TIER1_BUILDING_TYPES,
    TIER2_BUILDING_TYPES,
    INFRA_BUILDING_TYPES,
    consumption_for,
    get_config,
)
from .tech_data           import (
    TechDef,
    ReformDef,
    TECH_TREE,
    REFORM_TREE,
    BUILDING_TECH_REQUIREMENTS,
    TECH_GATED_BUILDINGS,
    RESEARCH_SPEED_BONUSES,
    REFORM_ADOPTION_COST,
    MAX_ADOPTED_REFORMS,
)
from .storage_system      import StorageSystem
from .treasury_system     import TreasurySystem
from .building_system     import BuildingSystem
from .consumption_system  import (
    ResourceConsumptionSystem, ConsumptionReport, CountryConsumption,
)
from .production_system   import (
    ProductionSystem, ProductionReport, CountryProduction, GEMS_GOLD_PER_MONTH,
)
from .market_system       import (
    GlobalMarketSystem, BuyResult, MarketUpdateReport, MarketResourceUpdate,
)
from .efficiency_system   import (
    EconomyEfficiencySystem, EfficiencyResult,
    compute_efficiency, apply_income_formula,
    EFFICIENCY_MIN, EFFICIENCY_MAX,
)
from .technology_system   import (
    TechnologySystem, ResearchSpeedResult,
    StartResearchResult, ResearchCompletionEvent,
)
from .reforms_system      import (
    ReformsSystem, ReformEffects,
    StartReformResearchResult, AdoptReformResult, ReformCompletionEvent,
)
from .tick_system         import (
    TickSystem, DailyTickReport, MonthlyTickReport, CountryDailyResult,
)

__all__ = [
    # Database
    "EconomyDB",
    # Resource data
    "Tier1Resource",
    "Tier2Resource",
    "BuildingType",
    "BuildingTier",
    "BuildingConfig",
    "BUILDING_CONFIGS",
    "BUILDING_CONSUMPTION",
    "STORABLE_RESOURCES",
    "NON_STORABLE_PRODUCTS",
    "MARKET_BASE_PRICES",
    "MARKET_RESOURCES",
    "RESOURCE_TO_TIER1_BUILDING",
    "TIER1_BUILDING_TYPES",
    "TIER2_BUILDING_TYPES",
    "INFRA_BUILDING_TYPES",
    "consumption_for",
    "get_config",
    # Technology tree data
    "TechDef",
    "ReformDef",
    "TECH_TREE",
    "REFORM_TREE",
    "BUILDING_TECH_REQUIREMENTS",
    "TECH_GATED_BUILDINGS",
    "RESEARCH_SPEED_BONUSES",
    "REFORM_ADOPTION_COST",
    "MAX_ADOPTED_REFORMS",
    # Systems
    "StorageSystem",
    "TreasurySystem",
    "BuildingSystem",
    "ResourceConsumptionSystem",
    "ProductionSystem",
    "GlobalMarketSystem",
    "EconomyEfficiencySystem",
    "TechnologySystem",
    "ReformsSystem",
    "TickSystem",
    # Reports / result types
    "ConsumptionReport",
    "CountryConsumption",
    "ProductionReport",
    "CountryProduction",
    "GEMS_GOLD_PER_MONTH",
    "BuyResult",
    "MarketUpdateReport",
    "MarketResourceUpdate",
    "EfficiencyResult",
    "ResearchSpeedResult",
    "StartResearchResult",
    "ResearchCompletionEvent",
    "ReformEffects",
    "StartReformResearchResult",
    "AdoptReformResult",
    "ReformCompletionEvent",
    "DailyTickReport",
    "MonthlyTickReport",
    "CountryDailyResult",
    # Pure helpers
    "compute_efficiency",
    "apply_income_formula",
    "EFFICIENCY_MIN",
    "EFFICIENCY_MAX",
]
