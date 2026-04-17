"""
POPULATION SYSTEM
-----------------
Manages per-country population with monthly percentage growth, persisted
to SQLite.

Each country tracked here has:
  population    — current head count (integer)
  growth_rate   — monthly growth as a decimal fraction  (e.g. 0.02 = 2%/month)

Population updates are triggered by in-game months.  Since 30 in-game days
equal one month, the game loop should convert days → months before calling
``update_population``.

Integration with TimeSystem
---------------------------
On each tick the TimeSystem returns the number of in-game days that passed.
Divide that by 30 (DAYS_PER_MONTH) to get the number of complete months and
pass that to ``update_population``.

Example
-------
    db  = Database("game.db"); db.init()
    pop = PopulationSystem(db)

    pop.ensure_country("guild_1", "Evoria", population=5_000_000, growth_rate=0.02)
    pop.update_population("guild_1", "Evoria", months_passed=1)
    print(pop.get_population("guild_1", "Evoria"))   # 5_100_000
"""

from __future__ import annotations

import math

from game_backend.db import Database

# One in-game month is exactly 30 days
DAYS_PER_MONTH: int = 30


class PopulationSystem:
    """
    Handles population growth for all countries on all servers.

    Parameters
    ----------
    db : Database
        Shared database instance (must have been initialised via ``db.init()``).
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Country initialisation
    # ------------------------------------------------------------------

    def ensure_country(
        self,
        server_id:   str,
        country_id:  str,
        population:  int   = 1_000_000,
        growth_rate: float = 0.01,
    ) -> None:
        """
        Guarantee a country row exists.
        If the row is already present it is not overwritten.
        """
        existing = self._db.get_country(server_id, country_id)
        if existing is None:
            self._db.upsert_country(
                server_id   = server_id,
                country_id  = country_id,
                population  = population,
                growth_rate = growth_rate,
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_population(self, server_id: str, country_id: str) -> int:
        """Return the current population for a country."""
        row = self._db.get_or_create_country(server_id, country_id)
        return int(row["population"])

    def get_growth_rate(self, server_id: str, country_id: str) -> float:
        """Return the monthly growth rate (e.g. 0.02 for 2%/month)."""
        row = self._db.get_or_create_country(server_id, country_id)
        return float(row["growth_rate"])

    def get_snapshot(self, server_id: str, country_id: str) -> dict:
        """
        Return a full population snapshot dict.

        Keys: server_id, country_id, population, growth_rate
        """
        row = self._db.get_or_create_country(server_id, country_id)
        return {
            "server_id":   server_id,
            "country_id":  country_id,
            "population":  int(row["population"]),
            "growth_rate": float(row["growth_rate"]),
        }

    # ------------------------------------------------------------------
    # Growth rate configuration
    # ------------------------------------------------------------------

    def set_growth_rate(self, server_id: str, country_id: str, rate: float) -> None:
        """
        Set the monthly population growth rate.

        Parameters
        ----------
        rate : float
            Decimal fraction of monthly growth.
            - 0.01  =  1%/month
            - 0.05  =  5%/month
            - 0.0   =  no growth (stable population)
            - Negative values represent population decline (war, plague, famine).
        """
        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(server_id, country_id, growth_rate=rate)

    # ------------------------------------------------------------------
    # Population update — called each month (or fractionally)
    # ------------------------------------------------------------------

    def update_population(
        self,
        server_id:     str,
        country_id:    str,
        months_passed: int,
    ) -> int:
        """
        Apply compound monthly growth for ``months_passed`` in-game months.

        Formula: new_population = population × (1 + growth_rate) ^ months_passed

        The result is rounded to the nearest integer.  Fractional months are
        not supported — call this with the integer result of ``days // 30``.

        Returns the new population.
        """
        if months_passed < 0:
            raise ValueError("months_passed must be non-negative.")
        if months_passed == 0:
            return self.get_population(server_id, country_id)

        row         = self._db.get_or_create_country(server_id, country_id)
        population  = int(row["population"])
        growth_rate = float(row["growth_rate"])

        # Compound growth: P × (1 + r)^n
        new_population = math.floor(population * (1 + growth_rate) ** months_passed)

        # Population cannot drop below 1 (edge case: extreme negative growth rate)
        new_population = max(1, new_population)

        self._db.update_fields(server_id, country_id, population=new_population)
        return new_population

    def update_population_from_days(
        self,
        server_id:   str,
        country_id:  str,
        days_passed: int,
    ) -> tuple[int, int]:
        """
        Convenience wrapper: convert ``days_passed`` to complete months and
        apply growth.  Partial days (< 30) are ignored.

        Returns (new_population, complete_months_applied).
        """
        months = days_passed // DAYS_PER_MONTH
        new_pop = self.update_population(server_id, country_id, months)
        return new_pop, months

    # ------------------------------------------------------------------
    # Direct population manipulation (admin / events)
    # ------------------------------------------------------------------

    def set_population(self, server_id: str, country_id: str, amount: int) -> None:
        """
        Directly override a country's population (plague events, admin, etc.).
        """
        if amount < 1:
            raise ValueError("Population must be at least 1.")
        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(server_id, country_id, population=amount)

    def apply_population_change(
        self,
        server_id:   str,
        country_id:  str,
        delta:       int,
    ) -> int:
        """
        Add (or subtract) a fixed number of people from the population.
        Population is clamped to a minimum of 1.

        Returns the new population.
        """
        row     = self._db.get_or_create_country(server_id, country_id)
        new_pop = max(1, int(row["population"]) + delta)
        self._db.update_fields(server_id, country_id, population=new_pop)
        return new_pop

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def update_all_populations(
        self,
        server_id:   str,
        days_passed: int,
    ) -> dict[str, int]:
        """
        Apply growth to every country on a server for the given number of
        in-game days.  Returns a mapping of country_id → new_population.
        Only countries that complete at least one month are updated.
        """
        months = days_passed // DAYS_PER_MONTH
        result = {}
        for row in self._db.get_all_countries(server_id):
            new_pop = self.update_population(server_id, row["country_id"], months)
            result[row["country_id"]] = new_pop
        return result
