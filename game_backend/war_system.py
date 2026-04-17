"""
WAR SYSTEM
----------
Manages active wars, occupation of provinces, war score accumulation,
and treaty resolution between countries.

Key rules:
  - Wars do NOT end automatically — they require a treaty.
  - War score is a signed integer:
      > 0 → attacker is winning
      < 0 → defender is winning
  - Three treaty types: Surrender, White Peace, Proclaim Victory.
  - Post-war ceasefire = 3 in-game years (stored as a day count).
  - Vassals pay 25% income to their overlord and can eventually rebel.
  - War reparations transfer 35% of the loser's income per tick.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Treaty options
class TreatyType(Enum):
    SURRENDER        = "surrender"         # Loser cedes ~50% of provinces
    WHITE_PEACE      = "white_peace"       # Status quo, no territorial change
    PROCLAIM_VICTORY = "proclaim_victory"  # Winner spends war score on demands


# War outcome recorded after treaty resolution
class WarOutcome(Enum):
    ATTACKER_VICTORY = "attacker_victory"
    DEFENDER_VICTORY = "defender_victory"
    WHITE_PEACE      = "white_peace"


# Ceasefire duration in in-game years (converted to days at resolution time)
CEASEFIRE_YEARS: int       = 3
MONTHS_PER_YEAR: int       = 12
DAYS_PER_MONTH:  int       = 30
CEASEFIRE_DAYS:  int       = CEASEFIRE_YEARS * MONTHS_PER_YEAR * DAYS_PER_MONTH  # 1080

# Reparations income transfer rate (applied each income tick while active)
REPARATIONS_RATE: float = 0.35

# Surrender territory transfer fraction
SURRENDER_PROVINCE_FRACTION: float = 0.50

# Vassal income tribute rate
VASSAL_TRIBUTE_RATE: float = 0.25

# War score threshold to consider one side dominant
WAR_SCORE_DOMINANT_THRESHOLD: int = 50


# ---------------------------------------------------------------------------
# Province
# ---------------------------------------------------------------------------

@dataclass
class Province:
    """
    Represents a single in-game province.
    The cost field drives how much war score is required to claim it
    via Proclaim Victory.
    """
    name:        str
    owner:       str           # Country name that owns this province
    war_score_cost: int = 10   # War score points needed to demand this province

    def to_dict(self) -> dict:
        return {
            "name":           self.name,
            "owner":          self.owner,
            "war_score_cost": self.war_score_cost,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Province":
        return cls(**data)


# ---------------------------------------------------------------------------
# Occupation record
# ---------------------------------------------------------------------------

@dataclass
class Occupation:
    """
    Tracks which provinces are currently occupied and by whom during a war.
    Occupation contributes to war score.
    """
    province_name: str
    occupied_by:   str   # Country name currently holding the province
    original_owner: str  # Province's owner before the war (restored on White Peace)

    def to_dict(self) -> dict:
        return {
            "province_name":  self.province_name,
            "occupied_by":    self.occupied_by,
            "original_owner": self.original_owner,
        }


# ---------------------------------------------------------------------------
# Vassal record
# ---------------------------------------------------------------------------

@dataclass
class VassalRelation:
    """
    Records an overlord–vassal relationship established after a war.
    """
    vassal:   str            # Country that was forced into vassalhood
    overlord: str            # Country that holds suzerainty
    tribute_rate: float = VASSAL_TRIBUTE_RATE
    can_rebel: bool     = True

    def to_dict(self) -> dict:
        return {
            "vassal":        self.vassal,
            "overlord":      self.overlord,
            "tribute_rate":  self.tribute_rate,
            "can_rebel":     self.can_rebel,
        }


# ---------------------------------------------------------------------------
# Ceasefire record
# ---------------------------------------------------------------------------

@dataclass
class Ceasefire:
    """
    Prevents re-declaration of war for a fixed in-game period after a war ends.
    ``expires_on_day`` is the absolute in-game day (from TimeSystem.total_days_elapsed)
    at which the ceasefire expires.
    """
    country_a:       str
    country_b:       str
    expires_on_day:  int   # Absolute in-game day when ceasefire lifts

    def is_active(self, current_day: int) -> bool:
        return current_day < self.expires_on_day

    def to_dict(self) -> dict:
        return {
            "country_a":      self.country_a,
            "country_b":      self.country_b,
            "expires_on_day": self.expires_on_day,
        }


# ---------------------------------------------------------------------------
# Reparations record
# ---------------------------------------------------------------------------

@dataclass
class Reparations:
    """
    Ongoing income transfer from the losing country to the winning country.
    Duration is expressed in in-game days; the economy system (future) should
    call ``is_active`` each income tick to determine whether to apply the transfer.
    """
    payer:           str    # Country paying reparations
    receiver:        str    # Country receiving reparations
    rate:            float  # Fraction of payer's income transferred per tick
    expires_on_day:  int    # Absolute in-game day when reparations end

    def is_active(self, current_day: int) -> bool:
        return current_day < self.expires_on_day

    def to_dict(self) -> dict:
        return {
            "payer":           self.payer,
            "receiver":        self.receiver,
            "rate":            self.rate,
            "expires_on_day":  self.expires_on_day,
        }


# ---------------------------------------------------------------------------
# War — the core data structure
# ---------------------------------------------------------------------------

@dataclass
class War:
    """
    Represents a single active war between two coalitions.

    Attributes
    ----------
    war_id        : Unique identifier (UUID string).
    attackers     : Set of country names on the attacking side.
    defenders     : Set of country names on the defending side.
    war_score     : Signed integer.  > 0 favours attackers, < 0 favours defenders.
    occupations   : Map of province_name → Occupation.
    start_day     : Absolute in-game day when the war began.
    active        : False once a treaty has been signed.
    outcome       : Set after treaty resolution.
    """
    war_id:      str                         = field(default_factory=lambda: str(uuid.uuid4()))
    attackers:   set[str]                    = field(default_factory=set)
    defenders:   set[str]                    = field(default_factory=set)
    war_score:   int                         = 0
    occupations: dict[str, Occupation]       = field(default_factory=dict)
    start_day:   int                         = 0
    active:      bool                        = True
    outcome:     Optional[WarOutcome]        = None

    # ------------------------------------------------------------------
    # Score helpers
    # ------------------------------------------------------------------

    def attacker_leading(self) -> bool:
        return self.war_score > 0

    def defender_leading(self) -> bool:
        return self.war_score < 0

    def is_decisive(self) -> bool:
        """True when one side has a dominant war-score advantage."""
        return abs(self.war_score) >= WAR_SCORE_DOMINANT_THRESHOLD

    # ------------------------------------------------------------------
    # Occupation helpers
    # ------------------------------------------------------------------

    def occupy_province(self, province_name: str, occupied_by: str, original_owner: str) -> None:
        """
        Record a province as occupied by a country.
        Adjusts war score: +score_value if the occupier is an attacker,
        -score_value if the occupier is a defender.
        """
        self.occupations[province_name] = Occupation(
            province_name  = province_name,
            occupied_by    = occupied_by,
            original_owner = original_owner,
        )
        # Occupation contributes a fixed war-score point per province
        if occupied_by in self.attackers:
            self.war_score += 10
        elif occupied_by in self.defenders:
            self.war_score -= 10

    def liberate_province(self, province_name: str) -> None:
        """
        Remove an occupation record (province was recaptured or returned).
        Reverses the war score contribution.
        """
        occ = self.occupations.pop(province_name, None)
        if occ is None:
            return
        if occ.occupied_by in self.attackers:
            self.war_score -= 10
        elif occ.occupied_by in self.defenders:
            self.war_score += 10

    def get_occupied_by(self, country: str) -> list[str]:
        """Return names of all provinces currently occupied by ``country``."""
        return [
            name for name, occ in self.occupations.items()
            if occ.occupied_by == country
        ]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "war_id":      self.war_id,
            "attackers":   list(self.attackers),
            "defenders":   list(self.defenders),
            "war_score":   self.war_score,
            "occupations": {k: v.to_dict() for k, v in self.occupations.items()},
            "start_day":   self.start_day,
            "active":      self.active,
            "outcome":     self.outcome.value if self.outcome else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "War":
        war = cls(
            war_id    = data["war_id"],
            attackers = set(data["attackers"]),
            defenders = set(data["defenders"]),
            war_score = data["war_score"],
            start_day = data["start_day"],
            active    = data["active"],
            outcome   = WarOutcome(data["outcome"]) if data["outcome"] else None,
        )
        war.occupations = {
            k: Occupation(**v) for k, v in data["occupations"].items()
        }
        return war


# ---------------------------------------------------------------------------
# WarSystem — the main engine
# ---------------------------------------------------------------------------

class WarSystem:
    """
    Central controller for all wars, ceasefires, vassals, and reparations.

    Usage example
    -------------
    >>> ws = WarSystem()
    >>> war_id = ws.declare_war("Evoria", "Drakmar", current_day=100)
    >>> ws.occupy_province(war_id, "Border Keep", occupied_by="Evoria",
    ...                    original_owner="Drakmar")
    >>> ws.resolve_treaty(war_id, TreatyType.SURRENDER,
    ...                   provinces={"border_keep": province_obj},
    ...                   current_day=200)
    """

    def __init__(self) -> None:
        self._wars:       dict[str, War]            = {}   # war_id → War
        self._ceasefires: list[Ceasefire]            = []
        self._vassals:    dict[str, VassalRelation]  = {}   # vassal_name → VassalRelation
        self._reparations: list[Reparations]         = []

    # ------------------------------------------------------------------
    # War declaration
    # ------------------------------------------------------------------

    def declare_war(
        self,
        attacker:    str,
        defender:    str,
        current_day: int,
        extra_attackers: list[str] | None = None,
        extra_defenders: list[str] | None = None,
    ) -> str:
        """
        Open a new war between ``attacker`` and ``defender``.

        Extra coalition members can be provided via ``extra_attackers`` /
        ``extra_defenders``.

        Returns the new ``war_id``.

        Raises
        ------
        ValueError  if a ceasefire is currently active between the two countries.
        """
        if self.ceasefire_active(attacker, defender, current_day):
            raise ValueError(
                f"A ceasefire is still active between '{attacker}' and '{defender}'."
            )

        attackers = {attacker} | set(extra_attackers or [])
        defenders = {defender} | set(extra_defenders or [])

        war = War(
            attackers  = attackers,
            defenders  = defenders,
            start_day  = current_day,
        )
        self._wars[war.war_id] = war
        return war.war_id

    # ------------------------------------------------------------------
    # Province occupation
    # ------------------------------------------------------------------

    def occupy_province(
        self,
        war_id:         str,
        province_name:  str,
        occupied_by:    str,
        original_owner: str,
    ) -> None:
        """
        Mark ``province_name`` as occupied by ``occupied_by`` in the given war.
        Updates war score automatically.
        """
        war = self._get_active_war(war_id)
        war.occupy_province(province_name, occupied_by, original_owner)

    def liberate_province(self, war_id: str, province_name: str) -> None:
        """Remove an occupation and revert the war score contribution."""
        war = self._get_active_war(war_id)
        war.liberate_province(province_name)

    def adjust_war_score(self, war_id: str, delta: int) -> int:
        """
        Manually adjust war score by ``delta`` (positive favours attackers).
        Use this for future factors such as battle victories, attrition, events.
        Returns the new war score.
        """
        war = self._get_active_war(war_id)
        war.war_score += delta
        return war.war_score

    # ------------------------------------------------------------------
    # Treaty resolution
    # ------------------------------------------------------------------

    def resolve_treaty(
        self,
        war_id:               str,
        treaty_type:          TreatyType,
        current_day:          int,
        provinces:            dict[str, Province] | None = None,
        reparations_duration_days: int = CEASEFIRE_DAYS,
    ) -> dict:
        """
        End a war via a treaty and apply all consequences.

        Parameters
        ----------
        war_id                    : The war to resolve.
        treaty_type               : One of SURRENDER, WHITE_PEACE, PROCLAIM_VICTORY.
        current_day               : Current absolute in-game day (for ceasefire timing).
        provinces                 : Full province registry {name → Province} — required
                                    for SURRENDER and PROCLAIM_VICTORY.
        reparations_duration_days : How long reparations last (only for PROCLAIM_VICTORY).

        Returns a summary dict describing what changed.
        """
        war = self._get_active_war(war_id)
        summary: dict = {"war_id": war_id, "treaty": treaty_type.value, "changes": []}

        if treaty_type == TreatyType.WHITE_PEACE:
            summary.update(self._resolve_white_peace(war))
        elif treaty_type == TreatyType.SURRENDER:
            summary.update(self._resolve_surrender(war, provinces or {}))
        elif treaty_type == TreatyType.PROCLAIM_VICTORY:
            summary.update(
                self._resolve_proclaim_victory(
                    war, provinces or {}, current_day, reparations_duration_days
                )
            )

        # Close the war
        war.active  = False
        war.outcome = summary.get("_outcome", WarOutcome.WHITE_PEACE)

        # Register ceasefire for every attacker–defender pair
        ceasefire_end = current_day + CEASEFIRE_DAYS
        for a in war.attackers:
            for d in war.defenders:
                self._ceasefires.append(
                    Ceasefire(country_a=a, country_b=d, expires_on_day=ceasefire_end)
                )

        # Remove internal key from summary before returning
        summary.pop("_outcome", None)
        return summary

    # ------------------------------------------------------------------
    # Vassal mechanics
    # ------------------------------------------------------------------

    def create_vassal(self, vassal: str, overlord: str) -> VassalRelation:
        """
        Establish a vassal relationship.  Called during PROCLAIM_VICTORY resolution
        but can also be triggered directly by admin commands.
        """
        if vassal in self._vassals:
            raise ValueError(f"'{vassal}' is already a vassal.")
        rel = VassalRelation(vassal=vassal, overlord=overlord)
        self._vassals[vassal] = rel
        return rel

    def vassal_rebels(self, vassal: str) -> bool:
        """
        Attempt a vassal rebellion. Returns True if successful (removed from vassalage).
        The actual probability / conditions are left for the game layer to decide;
        this method simply removes the record.
        """
        if vassal not in self._vassals:
            return False
        del self._vassals[vassal]
        return True

    def get_vassal_relation(self, vassal: str) -> Optional[VassalRelation]:
        return self._vassals.get(vassal)

    def get_all_vassals(self) -> list[VassalRelation]:
        return list(self._vassals.values())

    # ------------------------------------------------------------------
    # Ceasefire queries
    # ------------------------------------------------------------------

    def ceasefire_active(self, a: str, b: str, current_day: int) -> bool:
        """True if any active ceasefire covers the pair (a, b)."""
        for cf in self._ceasefires:
            if {cf.country_a, cf.country_b} == {a, b}:
                if cf.is_active(current_day):
                    return True
        return False

    def get_ceasefires(self, current_day: int) -> list[Ceasefire]:
        """Return all ceasefires that are still active."""
        return [cf for cf in self._ceasefires if cf.is_active(current_day)]

    # ------------------------------------------------------------------
    # Reparations queries
    # ------------------------------------------------------------------

    def get_active_reparations(self, current_day: int) -> list[Reparations]:
        """Return all reparation agreements that are currently active."""
        return [r for r in self._reparations if r.is_active(current_day)]

    # ------------------------------------------------------------------
    # War queries
    # ------------------------------------------------------------------

    def get_war(self, war_id: str) -> War:
        if war_id not in self._wars:
            raise KeyError(f"No war with id '{war_id}'.")
        return self._wars[war_id]

    def get_active_wars(self) -> list[War]:
        """Return all currently active wars."""
        return [w for w in self._wars.values() if w.active]

    def get_wars_involving(self, country: str) -> list[War]:
        """Return all wars (active or resolved) involving a country."""
        return [
            w for w in self._wars.values()
            if country in w.attackers or country in w.defenders
        ]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "wars":         {wid: w.to_dict() for wid, w in self._wars.items()},
            "ceasefires":   [cf.to_dict() for cf in self._ceasefires],
            "vassals":      {k: v.to_dict() for k, v in self._vassals.items()},
            "reparations":  [r.to_dict() for r in self._reparations],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WarSystem":
        ws = cls()
        ws._wars = {wid: War.from_dict(wd) for wid, wd in data["wars"].items()}
        ws._ceasefires = [
            Ceasefire(**cf) for cf in data["ceasefires"]
        ]
        ws._vassals = {
            k: VassalRelation(**v) for k, v in data["vassals"].items()
        }
        ws._reparations = [
            Reparations(**r) for r in data["reparations"]
        ]
        return ws

    # ------------------------------------------------------------------
    # Internal treaty helpers
    # ------------------------------------------------------------------

    def _resolve_white_peace(self, war: War) -> dict:
        """
        White Peace: restore all occupied provinces to their original owners.
        No territorial changes.
        """
        restored: list[str] = []
        for province_name, occ in list(war.occupations.items()):
            # Revert ownership in external province registry is the caller's job;
            # here we just clear the occupation record.
            restored.append(f"{province_name} → returned to {occ.original_owner}")
        war.occupations.clear()
        war.war_score = 0

        return {
            "_outcome": WarOutcome.WHITE_PEACE,
            "changes":  restored or ["No territorial changes."],
        }

    def _resolve_surrender(self, war: War, provinces: dict[str, Province]) -> dict:
        """
        Surrender: the losing side cedes approximately 50% of their provinces.
        The winner is whichever side has the higher war score.
        """
        # Determine loser / winner
        if war.war_score >= 0:
            # Attackers win
            winner_side = war.attackers
            loser_side  = war.defenders
            outcome     = WarOutcome.ATTACKER_VICTORY
        else:
            winner_side = war.defenders
            loser_side  = war.attackers
            outcome     = WarOutcome.DEFENDER_VICTORY

        # Collect loser-owned provinces
        loser_provinces = [
            p for p in provinces.values()
            if p.owner in loser_side
        ]

        # Transfer ~50%
        transfer_count = max(1, len(loser_provinces) // 2)
        transferred    = loser_provinces[:transfer_count]
        changes        = []

        for prov in transferred:
            # Transfer to the first (or only) winner — extend for multi-country logic
            new_owner      = next(iter(winner_side))
            old_owner      = prov.owner
            prov.owner     = new_owner
            changes.append(f"{prov.name}: {old_owner} → {new_owner}")

        war.occupations.clear()

        return {
            "_outcome": outcome,
            "changes":  changes or ["No provinces transferred (loser had none)."],
        }

    def _resolve_proclaim_victory(
        self,
        war:                      War,
        provinces:                dict[str, Province],
        current_day:              int,
        reparations_duration_days: int,
    ) -> dict:
        """
        Proclaim Victory: the dominant side spends war score on a menu of demands.
        Current implementation auto-applies all supported demands based on score.

        Demands (in priority order):
          1. Take provinces (cost per province)
          2. War reparations (35% income transfer)
          3. Create vassal state

        The caller (game/Discord layer) should expose a selection UI for demand
        choices.  This method applies whatever the war score can support.
        """
        if war.war_score >= 0:
            winner_side = war.attackers
            loser_side  = war.defenders
            outcome     = WarOutcome.ATTACKER_VICTORY
        else:
            winner_side = war.defenders
            loser_side  = war.attackers
            outcome     = WarOutcome.DEFENDER_VICTORY

        remaining_score = abs(war.war_score)
        changes: list[str] = []

        winner = next(iter(winner_side))
        loser  = next(iter(loser_side))

        # 1. Claim occupied provinces (paid for by war score)
        for province_name in list(war.occupations.keys()):
            occ = war.occupations[province_name]
            if occ.occupied_by in winner_side and province_name in provinces:
                prov = provinces[province_name]
                cost = prov.war_score_cost
                if remaining_score >= cost:
                    remaining_score -= cost
                    old_owner   = prov.owner
                    prov.owner  = winner
                    changes.append(
                        f"Province '{province_name}' transferred: {old_owner} → {winner} (cost {cost})"
                    )

        # 2. Reparations (costs 20 war score)
        REPARATIONS_COST = 20
        if remaining_score >= REPARATIONS_COST:
            remaining_score -= REPARATIONS_COST
            expiry = current_day + reparations_duration_days
            rep = Reparations(
                payer          = loser,
                receiver       = winner,
                rate           = REPARATIONS_RATE,
                expires_on_day = expiry,
            )
            self._reparations.append(rep)
            changes.append(
                f"Reparations: {loser} pays {int(REPARATIONS_RATE * 100)}% income "
                f"to {winner} for {reparations_duration_days} in-game days."
            )

        # 3. Vassal (costs 50 war score)
        VASSAL_COST = 50
        if remaining_score >= VASSAL_COST and loser not in self._vassals:
            remaining_score -= VASSAL_COST
            self.create_vassal(vassal=loser, overlord=winner)
            changes.append(
                f"Vassal established: {loser} becomes a vassal of {winner} "
                f"(tribute rate: {int(VASSAL_TRIBUTE_RATE * 100)}%)."
            )

        war.occupations.clear()

        return {
            "_outcome": outcome,
            "changes":  changes or ["Victory declared but no demands could be met."],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_active_war(self, war_id: str) -> War:
        war = self._wars.get(war_id)
        if war is None:
            raise KeyError(f"No war with id '{war_id}'.")
        if not war.active:
            raise ValueError(f"War '{war_id}' has already ended.")
        return war
