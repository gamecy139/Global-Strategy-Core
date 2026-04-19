"""
WW1 Economy System — Backend Package
--------------------------------------
Modular economy backend for the WW1 grand strategy scenario.

Systems
-------
  StorageSystem     — country resource storage (all storable resources)
  BuildingSystem    — construction management and validation
  ProductionSystem  — monthly production tick

Resources
---------
  Tier1Resource, Tier2Resource, BuildingType, BUILDING_CONFIGS

Database
--------
  EconomyDB         — SQLite layer for buildings + country_storage
"""

from .db                import EconomyDB
from .resources         import (
    Tier1Resource,
    Tier2Resource,
    BuildingType,
    BuildingTier,
    BuildingConfig,
    BUILDING_CONFIGS,
    STORABLE_RESOURCES,
    RESOURCE_TO_TIER1_BUILDING,
    TIER1_BUILDING_TYPES,
    TIER2_BUILDING_TYPES,
    get_config,
)
from .storage_system    import StorageSystem
from .building_system   import BuildingSystem
from .production_system import ProductionSystem, ProductionReport, CountryProduction

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
    "STORABLE_RESOURCES",
    "RESOURCE_TO_TIER1_BUILDING",
    "TIER1_BUILDING_TYPES",
    "TIER2_BUILDING_TYPES",
    "get_config",
    # Systems
    "StorageSystem",
    "BuildingSystem",
    "ProductionSystem",
    # Report types
    "ProductionReport",
    "CountryProduction",
]
