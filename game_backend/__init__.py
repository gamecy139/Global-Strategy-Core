"""
Discord Strategy Roleplay Game - Backend Systems
Modular backend package containing Time, Diplomacy, and War systems.
"""

from .time_system import TimeSystem, TimeSpeed
from .diplomacy_system import DiplomacySystem, RelationTier
from .war_system import WarSystem, War, TreatyType, WarOutcome

__all__ = [
    "TimeSystem",
    "TimeSpeed",
    "DiplomacySystem",
    "RelationTier",
    "WarSystem",
    "War",
    "TreatyType",
    "WarOutcome",
]
