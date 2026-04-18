"""
POPULATION SYSTEM (Extended)
-----------------------------
Manages per-country population with base + bonus monthly growth, persisted
to SQLite.

Each country has:
  base_population          — starting / reference population
  current_population       — live head count (changes monthly)
  base_growth_rate         — inherent monthly growth (set at country creation)
  bonus_growth_rate        — additional growth from player investments (max 2%)
  total_growth_rate        — base + bonus (used for actual monthly calculation)
  growth_investment_count  — how many investments have been made
  last_growth_investment_time — in-game day of the most recent investment

Growth formula (compound):
  new_population = current_population × (1 + total_growth_rate)^months

Investment system:
  - Each investment adds +0.5% (0.005) to bonus_growth_rate
  - bonus_growth_rate is capped at max_bonus (default 0.02 = 2%)
  - Cooldown between investments (default 90 days = 3 in-game months)
  - Cost grows progressively: base_cost × (count + 1)
"""

from __future__ import annotations

import math

from game_backend.db import Database

DAYS_PER_MONTH: int = 30

# Investment defaults (all configurable via method parameters)
DEFAULT_MAX_BONUS:          float = 0.02    # 2% max bonus growth
DEFAULT_INVESTMENT_BOOST:   float = 0.005   # +0.5% per investment
DEFAULT_INVESTMENT_COOLDOWN: int  = 90      # days (3 months)
DEFAULT_BASE_INVESTMENT_COST: float = 500.0  # gold; actual cost = base × (count+1)


class PopulationSystem:
    """
    Handles population growth and growth investments for all countries.

    Parameters
    ----------
    db : Database
        Shared database instance (initialised via ``db.init()``).
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Country initialisation
    # ------------------------------------------------------------------

    def ensure_country(
        self,
        server_id:        str,
        country_id:       str,
        base_population:  int   = 1_000_000,
        base_growth_rate: float = 0.01,
        bonus_growth_rate: float = 0.0,
    ) -> None:
        """
        Guarantee a country row exists.
        If absent, creates it with the supplied values.
        If already present, does NOT overwrite.
        """
        if self._db.get_country(server_id, country_id) is None:
            self._db.get_or_create_country(server_id, country_id)
            self._db.update_fields(
                server_id, country_id,
                base_population   = base_population,
                current_population = base_population,
                population         = base_population,      # legacy alias
                base_growth_rate  = base_growth_rate,
                growth_rate       = base_growth_rate,      # legacy alias
                bonus_growth_rate = bonus_growth_rate,
            )

    def initialize_country(
        self,
        server_id:        str,
        country_id:       str,
        base_population:  int   = 1_000_000,
        base_growth_rate: float = 0.01,
        bonus_growth_rate: float = 0.0,
    ) -> None:
        """
        Force-set population data (overwrites existing values).
        Use this for admin resets or game setup.
        """
        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(
            server_id, country_id,
            base_population    = base_population,
            current_population = base_population,
            population         = base_population,
            base_growth_rate   = base_growth_rate,
            growth_rate        = base_growth_rate,
            bonus_growth_rate  = bonus_growth_rate,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_base_population(self, server_id: str, country_id: str) -> int:
        row = self._db.get_or_create_country(server_id, country_id)
        return int(row.get("base_population") or row.get("population", 1_000_000))

    def get_current_population(self, server_id: str, country_id: str) -> int:
        row = self._db.get_or_create_country(server_id, country_id)
        return int(row.get("current_population") or row.get("population", 1_000_000))

    def get_population(self, server_id: str, country_id: str) -> int:
        """Alias for get_current_population (backward compatibility)."""
        return self.get_current_population(server_id, country_id)

    def get_base_growth_rate(self, server_id: str, country_id: str) -> float:
        row = self._db.get_or_create_country(server_id, country_id)
        return float(row.get("base_growth_rate") or row.get("growth_rate", 0.01))

    def get_bonus_growth_rate(self, server_id: str, country_id: str) -> float:
        row = self._db.get_or_create_country(server_id, country_id)
        return float(row.get("bonus_growth_rate", 0.0))

    def get_total_growth_rate(self, server_id: str, country_id: str) -> float:
        """Effective monthly growth rate = base + bonus."""
        return self.get_base_growth_rate(server_id, country_id) + \
               self.get_bonus_growth_rate(server_id, country_id)

    def get_growth_rate(self, server_id: str, country_id: str) -> float:
        """Alias for get_base_growth_rate (backward compatibility)."""
        return self.get_base_growth_rate(server_id, country_id)

    def get_snapshot(self, server_id: str, country_id: str) -> dict:
        row = self._db.get_or_create_country(server_id, country_id)
        return {
            "server_id":              server_id,
            "country_id":             country_id,
            "base_population":        int(row.get("base_population") or row.get("population", 1_000_000)),
            "current_population":     int(row.get("current_population") or row.get("population", 1_000_000)),
            "base_growth_rate":       float(row.get("base_growth_rate") or row.get("growth_rate", 0.01)),
            "bonus_growth_rate":      float(row.get("bonus_growth_rate", 0.0)),
            "total_growth_rate":      self.get_total_growth_rate(server_id, country_id),
            "growth_investment_count": int(row.get("growth_investment_count", 0)),
        }

    # ------------------------------------------------------------------
    # Growth rate configuration
    # ------------------------------------------------------------------

    def set_growth_rate(self, server_id: str, country_id: str, rate: float) -> None:
        """Set the base monthly growth rate (admin / game setup)."""
        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(
            server_id, country_id,
            base_growth_rate = rate,
            growth_rate      = rate,
        )

    # ------------------------------------------------------------------
    # Monthly population update
    # ------------------------------------------------------------------

    def update_population(
        self,
        server_id:     str,
        country_id:    str,
        months_passed: int,
    ) -> int:
        """
        Apply compound growth using total_growth_rate (base + bonus).
        Returns the new current_population.
        """
        if months_passed < 0:
            raise ValueError("months_passed must be non-negative.")
        if months_passed == 0:
            return self.get_current_population(server_id, country_id)

        row         = self._db.get_or_create_country(server_id, country_id)
        population  = int(row.get("current_population") or row.get("population", 1_000_000))
        total_rate  = (
            float(row.get("base_growth_rate") or row.get("growth_rate", 0.01))
            + float(row.get("bonus_growth_rate", 0.0))
        )

        new_population = max(1, math.floor(population * (1 + total_rate) ** months_passed))

        self._db.update_fields(
            server_id, country_id,
            current_population = new_population,
            population         = new_population,
        )
        return new_population

    def update_population_from_days(
        self,
        server_id:   str,
        country_id:  str,
        days_passed: int,
    ) -> tuple[int, int]:
        """
        Convert days to complete months and apply growth.
        Returns (new_population, months_applied).
        """
        months  = days_passed // DAYS_PER_MONTH
        new_pop = self.update_population(server_id, country_id, months)
        return new_pop, months

    # ------------------------------------------------------------------
    # Growth investment system
    # ------------------------------------------------------------------

    def get_investment_cost(
        self,
        server_id:   str,
        country_id:  str,
        base_cost:   float = DEFAULT_BASE_INVESTMENT_COST,
    ) -> float:
        """
        Calculate the gold cost of the next investment.
        Formula: base_cost × (investment_count + 1)
        """
        row   = self._db.get_or_create_country(server_id, country_id)
        count = int(row.get("growth_investment_count", 0))
        return base_cost * (count + 1)

    def can_invest(
        self,
        server_id:      str,
        country_id:     str,
        current_day:    int,
        cooldown_days:  int   = DEFAULT_INVESTMENT_COOLDOWN,
        max_bonus:      float = DEFAULT_MAX_BONUS,
    ) -> tuple[bool, str]:
        """
        Check whether a growth investment is allowed right now.

        Returns (allowed: bool, reason: str).
        """
        row        = self._db.get_or_create_country(server_id, country_id)
        bonus_rate = float(row.get("bonus_growth_rate", 0.0))
        count      = int(row.get("growth_investment_count", 0))
        last_day   = int(row.get("last_growth_investment_time", 0))

        if bonus_rate >= max_bonus:
            return False, (
                f"Bonus growth rate is already at the maximum "
                f"({max_bonus * 100:.1f}%)."
            )

        days_since = current_day - last_day
        if count > 0 and days_since < cooldown_days:
            remaining = cooldown_days - days_since
            return False, (
                f"Investment on cooldown. {remaining} in-game days remaining."
            )

        return True, "Investment available."

    def invest_in_growth(
        self,
        server_id:     str,
        country_id:    str,
        current_day:   int,
        max_bonus:     float = DEFAULT_MAX_BONUS,
        cooldown_days: int   = DEFAULT_INVESTMENT_COOLDOWN,
        base_cost:     float = DEFAULT_BASE_INVESTMENT_COST,
        boost:         float = DEFAULT_INVESTMENT_BOOST,
    ) -> dict:
        """
        Apply one growth investment if allowed.

        Returns a result dict:
            allowed         : bool
            reason          : str
            cost            : float (gold cost if allowed)
            new_bonus_rate  : float
            total_rate      : float
            investment_count: int

        The caller is responsible for deducting the ``cost`` from the
        treasury (via EconomySystem.withdraw).
        """
        allowed, reason = self.can_invest(
            server_id, country_id, current_day, cooldown_days, max_bonus
        )
        if not allowed:
            return {
                "allowed": False,
                "reason":  reason,
                "cost":    0.0,
            }

        row        = self._db.get_or_create_country(server_id, country_id)
        old_bonus  = float(row.get("bonus_growth_rate", 0.0))
        old_count  = int(row.get("growth_investment_count", 0))
        cost       = base_cost * (old_count + 1)

        new_bonus  = min(max_bonus, old_bonus + boost)
        new_count  = old_count + 1

        self._db.update_fields(
            server_id, country_id,
            bonus_growth_rate           = new_bonus,
            growth_investment_count     = new_count,
            last_growth_investment_time = current_day,
        )

        base_rate = float(row.get("base_growth_rate") or row.get("growth_rate", 0.01))
        return {
            "allowed":          True,
            "reason":           "Investment applied.",
            "cost":             cost,
            "new_bonus_rate":   new_bonus,
            "total_rate":       base_rate + new_bonus,
            "investment_count": new_count,
        }

    # ------------------------------------------------------------------
    # Direct population manipulation (admin / events)
    # ------------------------------------------------------------------

    def set_population(self, server_id: str, country_id: str, amount: int) -> None:
        """Override current_population directly (plague, admin, etc.)."""
        if amount < 1:
            raise ValueError("Population must be at least 1.")
        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(
            server_id, country_id,
            current_population = amount,
            population         = amount,
        )

    def apply_population_change(
        self,
        server_id:  str,
        country_id: str,
        delta:      int,
    ) -> int:
        """Add or subtract a fixed count. Population clamped to 1."""
        row     = self._db.get_or_create_country(server_id, country_id)
        new_pop = max(1, int(row.get("current_population") or row.get("population", 1_000_000)) + delta)
        self._db.update_fields(
            server_id, country_id,
            current_population = new_pop,
            population         = new_pop,
        )
        return new_pop

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def update_all_populations(
        self,
        server_id:   str,
        days_passed: int,
    ) -> dict[str, int]:
        """Apply growth to every country on a server."""
        months = days_passed // DAYS_PER_MONTH
        result = {}
        for row in self._db.get_all_countries(server_id):
            new_pop = self.update_population(server_id, row["country_id"], months)
            result[row["country_id"]] = new_pop
        return result
