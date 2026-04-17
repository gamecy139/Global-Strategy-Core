"""
DIPLOMACY SYSTEM
----------------
Manages bilateral relations between countries using a points-based model.

Relation scale:
  < 0       → Hostile  (war may be declared)
   0 – 10   → Neutral
  10 – 20   → Defense Pact tier (defense pacts can be formed)
  20 – 30   → Alliance tier (full alliances can be formed)

Relations are stored as a symmetric lookup table keyed by a canonical
(country_a, country_b) tuple where country_a < country_b (alphabetical).
This guarantees each pair has exactly one entry regardless of lookup order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RELATION_MIN: int = -10   # Floor — below this a country is considered at war
RELATION_MAX: int = 30    # Ceiling — maximum possible relations

# Tier thresholds
TIER_NEUTRAL_MIN: int    = 0
TIER_DEFENSE_PACT_MIN: int = 10
TIER_ALLIANCE_MIN: int   = 20

# Automatic penalty for religious persecution events
RELIGIOUS_PERSECUTION_PENALTY: int = 10


# ---------------------------------------------------------------------------
# Relation tier classification
# ---------------------------------------------------------------------------

class RelationTier(Enum):
    HOSTILE      = "hostile"       # < 0
    NEUTRAL      = "neutral"       # 0–9
    DEFENSE_PACT = "defense_pact"  # 10–19 (pact can be formed)
    ALLIANCE     = "alliance"      # 20–30 (alliance can be formed)

    @classmethod
    def from_value(cls, value: int) -> "RelationTier":
        if value < TIER_NEUTRAL_MIN:
            return cls.HOSTILE
        if value < TIER_DEFENSE_PACT_MIN:
            return cls.NEUTRAL
        if value < TIER_ALLIANCE_MIN:
            return cls.DEFENSE_PACT
        return cls.ALLIANCE


# ---------------------------------------------------------------------------
# Country registry
# ---------------------------------------------------------------------------

@dataclass
class Country:
    """
    Lightweight country record.
    Extend this dataclass to add economy, technology, culture, religion, etc.
    """
    name:     str
    religion: str = "none"   # Used by religious-persecution auto-modifier

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Country) and self.name == other.name


# ---------------------------------------------------------------------------
# DiplomacySystem
# ---------------------------------------------------------------------------

class DiplomacySystem:
    """
    Manages all diplomatic relations between registered countries.

    Usage
    -----
    >>> ds = DiplomacySystem()
    >>> ds.register_country(Country("Evoria", religion="solarian"))
    >>> ds.register_country(Country("Drakmar", religion="obsidian"))
    >>> ds.improve_relations("Evoria", "Drakmar", amount=5)
    >>> print(ds.get_relation("Evoria", "Drakmar"))
    5
    """

    def __init__(self) -> None:
        # name → Country object
        self._countries: dict[str, Country] = {}

        # canonical pair (a, b) where a < b → relation value
        self._relations: dict[tuple[str, str], int] = {}

    # ------------------------------------------------------------------
    # Country management
    # ------------------------------------------------------------------

    def register_country(self, country: Country) -> None:
        """
        Add a new country to the diplomacy system.
        Automatically initialises neutral (0) relations with all existing countries.
        """
        if country.name in self._countries:
            raise ValueError(f"Country '{country.name}' is already registered.")

        for existing_name in self._countries:
            key = self._make_key(country.name, existing_name)
            self._relations[key] = 0  # Start neutral

        self._countries[country.name] = country

    def get_country(self, name: str) -> Country:
        """Return the Country object for the given name."""
        self._require_country(name)
        return self._countries[name]

    def list_countries(self) -> list[str]:
        """Return a sorted list of all registered country names."""
        return sorted(self._countries.keys())

    # ------------------------------------------------------------------
    # Relation read access
    # ------------------------------------------------------------------

    def get_relation(self, country_a: str, country_b: str) -> int:
        """Return the current relation score between two countries (-10 to 30)."""
        self._require_pair(country_a, country_b)
        return self._relations[self._make_key(country_a, country_b)]

    def get_relation_tier(self, country_a: str, country_b: str) -> RelationTier:
        """Return the diplomatic tier based on current relation score."""
        value = self.get_relation(country_a, country_b)
        return RelationTier.from_value(value)

    def can_declare_war(self, attacker: str, defender: str) -> bool:
        """War may only be declared when relations are strictly negative."""
        return self.get_relation(attacker, defender) < 0

    def can_form_defense_pact(self, country_a: str, country_b: str) -> bool:
        return self.get_relation(country_a, country_b) >= TIER_DEFENSE_PACT_MIN

    def can_form_alliance(self, country_a: str, country_b: str) -> bool:
        return self.get_relation(country_a, country_b) >= TIER_ALLIANCE_MIN

    def all_relations(self) -> list[dict]:
        """
        Return every bilateral relation as a list of dicts.
        Useful for status embeds or database persistence.
        """
        result = []
        for (a, b), value in self._relations.items():
            result.append({
                "country_a": a,
                "country_b": b,
                "value":     value,
                "tier":      RelationTier.from_value(value).value,
            })
        return result

    # ------------------------------------------------------------------
    # Relation modification
    # ------------------------------------------------------------------

    def improve_relations(self, country_a: str, country_b: str, amount: int) -> int:
        """
        Improve relations by ``amount`` points, clamped to RELATION_MAX.
        Returns the new relation value.
        """
        if amount <= 0:
            raise ValueError("Improvement amount must be positive.")
        return self._adjust_relations(country_a, country_b, +amount)

    def damage_relations(self, country_a: str, country_b: str, amount: int) -> int:
        """
        Damage relations by ``amount`` points, clamped to RELATION_MIN.
        Returns the new relation value.
        """
        if amount <= 0:
            raise ValueError("Damage amount must be positive.")
        return self._adjust_relations(country_a, country_b, -amount)

    def send_gift(
        self,
        sender: str,
        receiver: str,
        gift_value: int,
        relation_boost: int,
    ) -> int:
        """
        Simulate a diplomatic gift.

        Parameters
        ----------
        sender        : Name of the country sending the gift.
        receiver      : Name of the country receiving the gift.
        gift_value    : Monetary / resource value (stored externally, passed here
                        for logging / future economy hooks).
        relation_boost: How many relation points the gift grants.

        Returns the new relation score.
        """
        if relation_boost <= 0:
            raise ValueError("A gift must grant at least 1 relation point.")
        return self.improve_relations(sender, receiver, relation_boost)

    def set_relation(self, country_a: str, country_b: str, value: int) -> None:
        """
        Directly set a relation value (admin / scripted events).
        Value is clamped to [RELATION_MIN, RELATION_MAX].
        """
        self._require_pair(country_a, country_b)
        key = self._make_key(country_a, country_b)
        self._relations[key] = max(RELATION_MIN, min(RELATION_MAX, value))

    # ------------------------------------------------------------------
    # Auto-modifiers
    # ------------------------------------------------------------------

    def apply_religious_persecution(self, persecuting_country: str, religion: str) -> list[str]:
        """
        Apply a -10 relation penalty from every country that follows ``religion``
        toward ``persecuting_country``.

        Call this whenever a country triggers a persecution event.

        Returns a list of country names whose relations were affected.
        """
        self._require_country(persecuting_country)
        affected: list[str] = []

        for name, country in self._countries.items():
            if name == persecuting_country:
                continue
            if country.religion.lower() == religion.lower():
                self._adjust_relations(persecuting_country, name, -RELIGIOUS_PERSECUTION_PENALTY)
                affected.append(name)

        return affected

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise the full diplomacy state for persistence."""
        return {
            "countries": [
                {"name": c.name, "religion": c.religion}
                for c in self._countries.values()
            ],
            "relations": [
                {"a": a, "b": b, "value": v}
                for (a, b), v in self._relations.items()
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DiplomacySystem":
        """Restore a DiplomacySystem from a serialised dictionary."""
        ds = cls()
        for c in data["countries"]:
            # Register without triggering auto-init (pair data will be loaded below)
            ds._countries[c["name"]] = Country(name=c["name"], religion=c["religion"])
        for r in data["relations"]:
            key = ds._make_key(r["a"], r["b"])
            ds._relations[key] = r["value"]
        return ds

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(a: str, b: str) -> tuple[str, str]:
        """Return a canonical (smaller, larger) key for a country pair."""
        return (a, b) if a < b else (b, a)

    def _require_country(self, name: str) -> None:
        if name not in self._countries:
            raise KeyError(f"Country '{name}' is not registered.")

    def _require_pair(self, a: str, b: str) -> None:
        if a == b:
            raise ValueError("A country cannot have diplomatic relations with itself.")
        self._require_country(a)
        self._require_country(b)

    def _adjust_relations(self, a: str, b: str, delta: int) -> int:
        """Apply a delta (positive or negative), clamp, and return new value."""
        self._require_pair(a, b)
        key = self._make_key(a, b)
        new_value = self._relations[key] + delta
        new_value = max(RELATION_MIN, min(RELATION_MAX, new_value))
        self._relations[key] = new_value
        return new_value
