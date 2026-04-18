"""
Discord Strategy Roleplay Game — Backend Systems
Modular backend package. All systems are imported here for convenience.
"""

from .time_system       import TimeSystem, TimeSpeed
from .diplomacy_system  import DiplomacySystem, RelationTier, Country
from .war_system        import WarSystem, War, TreatyType, WarOutcome
from .db                import Database
from .religion_system   import Religion, ReligionSystem
from .economy_system    import EconomySystem
from .population_system import PopulationSystem
from .taxation_system   import TaxationSystem, TaxLevel
from .opinion_system    import OpinionSystem
from .province_system   import ProvinceSystem
from .unrest_system     import UnrestSystem
from .military_system   import MilitarySystem, RecruitmentSystem

__all__ = [
    # Time
    "TimeSystem",
    "TimeSpeed",
    # Diplomacy
    "DiplomacySystem",
    "RelationTier",
    "Country",
    # War
    "WarSystem",
    "War",
    "TreatyType",
    "WarOutcome",
    # Database
    "Database",
    # Religion
    "Religion",
    "ReligionSystem",
    # Economy
    "EconomySystem",
    # Population
    "PopulationSystem",
    # Taxation
    "TaxationSystem",
    "TaxLevel",
    # Opinion
    "OpinionSystem",
    # Provinces
    "ProvinceSystem",
    # Unrest
    "UnrestSystem",
    # Military & Recruitment
    "MilitarySystem",
    "RecruitmentSystem",
]
