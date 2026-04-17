"""
Discord Strategy Roleplay Game - Backend Systems
Modular backend package containing all game systems.
"""

from .time_system       import TimeSystem, TimeSpeed
from .diplomacy_system  import DiplomacySystem, RelationTier, Country
from .war_system        import WarSystem, War, TreatyType, WarOutcome
from .db                import Database
from .religion_system   import Religion, ReligionSystem
from .economy_system    import EconomySystem
from .population_system import PopulationSystem

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
]
