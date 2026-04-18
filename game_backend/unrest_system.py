"""
UNREST SYSTEM
-------------
Manages country unrest (0–100) — a measure of civil instability.

Monthly unrest sources (all capped to +10 increase per month):
  Non-core provinces       → +2 per province owned
  Religion mismatch        → +3 per province whose religion ≠ country religion
  Religious persecution    → +2 (if persecution_active flag is set)
  Low opinion (< 30)       → +2 (from OpinionSystem)

Instant effects:
  Religious persecution activated → +10 immediately

Monthly unrest reduction (opinion-driven):
  opinion > 50 → -2 per month
  opinion > 70 → -3 per month

Thresholds and events:
  ≥ 50 → Riots        (population decrease, cooldown 60 days / 2 months)
  ≥ 80 → Rebellion    (spawn rebel army,    cooldown 180 days / 6 months)

Stacking cap:
  Monthly increase is hard-capped at +10.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from game_backend.db import Database

if TYPE_CHECKING:
    from game_backend.province_system import ProvinceSystem
    from game_backend.opinion_system  import OpinionSystem
    from game_backend.military_system import MilitarySystem


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UNREST_MIN: float = 0.0
UNREST_MAX: float = 100.0

MAX_MONTHLY_INCREASE: int = 10   # Hard cap on monthly unrest gain

# Source contributions per item (per province)
NON_CORE_UNREST_PER_PROVINCE:     int = 2
RELIGION_MISMATCH_UNREST_PER_PROVINCE: int = 3
PERSECUTION_MONTHLY_UNREST:       int = 2
PERSECUTION_INSTANT_UNREST:       int = 10

# Event thresholds
RIOT_THRESHOLD:      float = 50.0
REBELLION_THRESHOLD: float = 80.0

# Event cooldowns in in-game days
RIOT_COOLDOWN_DAYS:      int = 60    # 2 months
REBELLION_COOLDOWN_DAYS: int = 180   # 6 months

# Riot effect: fraction of current_population lost
RIOT_POPULATION_LOSS_FRACTION: float = 0.02   # 2% population decrease per riot


class UnrestSystem:
    """
    Manages civil unrest for all countries on all servers.

    Parameters
    ----------
    db : Database
        Shared database instance.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_unrest(self, server_id: str, country_id: str) -> float:
        row = self._db.get_or_create_country(server_id, country_id)
        return float(row.get("unrest", 0.0))

    def get_snapshot(self, server_id: str, country_id: str) -> dict:
        row = self._db.get_or_create_country(server_id, country_id)
        return {
            "server_id":           server_id,
            "country_id":          country_id,
            "unrest":              float(row.get("unrest", 0.0)),
            "persecution_active":  bool(row.get("persecution_active", 0)),
        }

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def set_unrest(self, server_id: str, country_id: str, value: float) -> float:
        clamped = max(UNREST_MIN, min(UNREST_MAX, value))
        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(server_id, country_id, unrest=clamped)
        return clamped

    def adjust_unrest(self, server_id: str, country_id: str, delta: float) -> float:
        current = self.get_unrest(server_id, country_id)
        return self.set_unrest(server_id, country_id, current + delta)

    # ------------------------------------------------------------------
    # Persecution events
    # ------------------------------------------------------------------

    def activate_persecution(self, server_id: str, country_id: str) -> dict:
        """
        Mark religious persecution as active and immediately apply +10 unrest.
        Returns the new unrest value and affected info.
        """
        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(server_id, country_id, persecution_active=1)
        new_unrest = self.adjust_unrest(server_id, country_id, PERSECUTION_INSTANT_UNREST)
        return {
            "server_id":   server_id,
            "country_id":  country_id,
            "instant_unrest_added": PERSECUTION_INSTANT_UNREST,
            "new_unrest":  new_unrest,
        }

    def deactivate_persecution(self, server_id: str, country_id: str) -> None:
        """Remove active persecution flag."""
        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(server_id, country_id, persecution_active=0)

    def is_persecution_active(self, server_id: str, country_id: str) -> bool:
        row = self._db.get_or_create_country(server_id, country_id)
        return bool(row.get("persecution_active", 0))

    # ------------------------------------------------------------------
    # Monthly unrest update
    # ------------------------------------------------------------------

    def update_monthly(
        self,
        server_id:        str,
        country_id:       str,
        current_day:      int,
        province_system:  "ProvinceSystem",
        opinion_system:   "OpinionSystem",
        country_religion: str,
    ) -> dict:
        """
        Apply one month's worth of unrest changes.

        1. Compute all monthly increase sources (capped at MAX_MONTHLY_INCREASE).
        2. Apply opinion-based reduction.
        3. Clamp result to [0, 100].
        4. Check event thresholds (riots, rebellion).

        Parameters
        ----------
        province_system  : Used to count non-core and religion-mismatch provinces.
        opinion_system   : Used to check opinion level for increase/reduction.
        country_religion : Official religion of the country (for mismatch check).

        Returns a detailed dict describing what happened.
        """
        row     = self._db.get_or_create_country(server_id, country_id)
        current = float(row.get("unrest", 0.0))
        sources: dict[str, int] = {}

        # --- Monthly increase sources ---
        non_core   = province_system.get_non_core_provinces(server_id, country_id)
        mismatches = province_system.get_religion_mismatch_provinces(
            server_id, country_id, country_religion
        )
        persecution_active = bool(row.get("persecution_active", 0))
        opinion_contrib    = opinion_system.get_unrest_contribution(server_id, country_id)

        sources["non_core_provinces"]      = len(non_core)       * NON_CORE_UNREST_PER_PROVINCE
        sources["religion_mismatch"]       = len(mismatches)     * RELIGION_MISMATCH_UNREST_PER_PROVINCE
        sources["persecution"]             = PERSECUTION_MONTHLY_UNREST if persecution_active else 0
        sources["low_opinion"]             = opinion_contrib

        total_increase = min(
            MAX_MONTHLY_INCREASE,
            sum(sources.values()),
        )

        # --- Monthly reduction (opinion-based) ---
        reduction = opinion_system.get_unrest_reduction(server_id, country_id)

        # --- Net change ---
        net_delta   = total_increase - reduction
        new_unrest  = self.set_unrest(server_id, country_id, current + net_delta)

        # --- Threshold events ---
        events = self._check_thresholds(server_id, country_id, current_day)

        return {
            "server_id":            server_id,
            "country_id":           country_id,
            "old_unrest":           current,
            "sources":              sources,
            "total_increase":       total_increase,
            "reduction":            reduction,
            "net_delta":            net_delta,
            "new_unrest":           new_unrest,
            "non_core_count":       len(non_core),
            "mismatch_count":       len(mismatches),
            "events":               events,
        }

    # ------------------------------------------------------------------
    # Event threshold checks
    # ------------------------------------------------------------------

    def _check_thresholds(
        self,
        server_id:   str,
        country_id:  str,
        current_day: int,
    ) -> list[dict]:
        """
        Evaluate unrest thresholds and return triggered events.
        Events carry cooldown metadata; the caller executes actual consequences.
        """
        row     = self._db.get_or_create_country(server_id, country_id)
        unrest  = float(row.get("unrest", 0.0))
        events: list[dict] = []

        # --- Riots ---
        if unrest >= RIOT_THRESHOLD:
            last_riot = int(row.get("last_riot_day", 0))
            if current_day - last_riot >= RIOT_COOLDOWN_DAYS:
                self._db.update_fields(server_id, country_id, last_riot_day=current_day)
                events.append({
                    "type":                   "riot",
                    "unrest":                 unrest,
                    "population_loss_fraction": RIOT_POPULATION_LOSS_FRACTION,
                    "message": (
                        f"Riots break out in {country_id}! "
                        f"Population decreases by {RIOT_POPULATION_LOSS_FRACTION*100:.0f}%."
                    ),
                })

        # --- Rebellion ---
        if unrest >= REBELLION_THRESHOLD:
            last_rebellion = int(row.get("last_rebellion_day", 0))
            if current_day - last_rebellion >= REBELLION_COOLDOWN_DAYS:
                self._db.update_fields(
                    server_id, country_id, last_rebellion_day=current_day
                )
                events.append({
                    "type":    "rebellion",
                    "unrest":  unrest,
                    "message": (
                        f"A rebellion erupts in {country_id}! "
                        f"Rebel forces have been spawned."
                    ),
                })

        return events

    def apply_riot_consequences(
        self,
        server_id:        str,
        country_id:       str,
        population_system,   # PopulationSystem — avoid circular import
    ) -> int:
        """
        Reduce population by the riot fraction.
        Returns the new population.
        """
        current_pop = population_system.get_current_population(server_id, country_id)
        loss        = max(1, int(current_pop * RIOT_POPULATION_LOSS_FRACTION))
        return population_system.apply_population_change(server_id, country_id, -loss)

    def apply_rebellion_consequences(
        self,
        server_id:        str,
        country_id:       str,
        military_system:  "MilitarySystem",
        rebel_size:       int  = 10_000,
        location:         str  = "capital",
    ) -> str:
        """
        Spawn a rebel army unit.
        Returns the new unit_id.
        """
        unit_id = military_system.create_unit(
            server_id  = server_id,
            country_id = f"rebels_{country_id}",
            unit_type  = "infantry",
            size       = rebel_size,
            location   = location,
        )
        return unit_id
