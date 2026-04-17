"""
ECONOMY SYSTEM
--------------
Manages per-country treasury and income, persisted to SQLite.

Each country tracked here has:
  treasury      — current gold reserves
  daily_income  — gold earned per in-game day

Treasury is updated by calling ``update_treasury(country_id, days_passed)``.
Income can be adjusted through ``add_income`` / ``reduce_income`` to hook in
future sources (taxation, trade, war reparations, vassal tribute, etc.).

All operations are isolated by ``server_id`` so multiple Discord servers
share one database without interfering with each other.

Integration with TimeSystem
---------------------------
The game loop should call ``update_treasury`` on every tick, passing the
number of in-game days returned by ``TimeSystem.tick()``.

Example
-------
    db  = Database("game.db"); db.init()
    eco = EconomySystem(db)

    eco.ensure_country("guild_1", "Evoria")
    eco.add_income("guild_1", "Evoria", 50)          # +50 gold/day
    eco.update_treasury("guild_1", "Evoria", days=3)  # 3 in-game days pass
    print(eco.get_treasury("guild_1", "Evoria"))      # 150.0
"""

from __future__ import annotations

from game_backend.db import Database


class EconomySystem:
    """
    Handles treasury and income for all countries on all servers.

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
        server_id:    str,
        country_id:   str,
        treasury:     float = 0.0,
        daily_income: float = 0.0,
    ) -> None:
        """
        Guarantee a country row exists in the database.
        If the row is already present it is not overwritten.
        If it is absent, it is created with the supplied starting values.
        """
        existing = self._db.get_country(server_id, country_id)
        if existing is None:
            self._db.upsert_country(
                server_id    = server_id,
                country_id   = country_id,
                treasury     = treasury,
                daily_income = daily_income,
            )

    # ------------------------------------------------------------------
    # Treasury read
    # ------------------------------------------------------------------

    def get_treasury(self, server_id: str, country_id: str) -> float:
        """Return the current treasury balance for a country."""
        row = self._db.get_or_create_country(server_id, country_id)
        return float(row["treasury"])

    def get_daily_income(self, server_id: str, country_id: str) -> float:
        """Return the current daily income for a country."""
        row = self._db.get_or_create_country(server_id, country_id)
        return float(row["daily_income"])

    def get_snapshot(self, server_id: str, country_id: str) -> dict:
        """
        Return a full economy snapshot dict.

        Keys: server_id, country_id, treasury, daily_income
        """
        row = self._db.get_or_create_country(server_id, country_id)
        return {
            "server_id":    server_id,
            "country_id":   country_id,
            "treasury":     float(row["treasury"]),
            "daily_income": float(row["daily_income"]),
        }

    # ------------------------------------------------------------------
    # Income modification
    # ------------------------------------------------------------------

    def add_income(self, server_id: str, country_id: str, amount: float) -> float:
        """
        Increase a country's daily income by ``amount``.

        This is the hook for future income sources: attach factories, trade
        routes, vassal tribute, etc. by calling this with the relevant amount.

        Returns the new daily_income.
        """
        if amount < 0:
            raise ValueError("Use reduce_income() to decrease income.")
        row = self._db.get_or_create_country(server_id, country_id)
        new_income = float(row["daily_income"]) + amount
        self._db.update_fields(server_id, country_id, daily_income=new_income)
        return new_income

    def reduce_income(self, server_id: str, country_id: str, amount: float) -> float:
        """
        Decrease a country's daily income by ``amount``.
        Income is clamped to 0 (a country cannot have negative daily income).

        Returns the new daily_income.
        """
        if amount < 0:
            raise ValueError("Use add_income() to increase income.")
        row = self._db.get_or_create_country(server_id, country_id)
        new_income = max(0.0, float(row["daily_income"]) - amount)
        self._db.update_fields(server_id, country_id, daily_income=new_income)
        return new_income

    def set_income(self, server_id: str, country_id: str, amount: float) -> None:
        """Directly set daily income (admin / scripted use)."""
        if amount < 0:
            raise ValueError("Daily income cannot be negative.")
        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(server_id, country_id, daily_income=amount)

    # ------------------------------------------------------------------
    # Treasury update — called each time tick
    # ------------------------------------------------------------------

    def update_treasury(
        self,
        server_id:   str,
        country_id:  str,
        days_passed: int,
    ) -> float:
        """
        Add ``daily_income * days_passed`` to the treasury.

        Should be called on every TimeSystem tick, passing the return value
        of ``TimeSystem.tick()`` as ``days_passed``.

        Returns the new treasury balance.
        """
        if days_passed < 0:
            raise ValueError("days_passed must be non-negative.")
        if days_passed == 0:
            return self.get_treasury(server_id, country_id)

        row        = self._db.get_or_create_country(server_id, country_id)
        income     = float(row["daily_income"])
        old_treasury = float(row["treasury"])
        new_treasury = old_treasury + income * days_passed

        self._db.update_fields(server_id, country_id, treasury=new_treasury)
        return new_treasury

    # ------------------------------------------------------------------
    # Direct treasury manipulation (admin / event hooks)
    # ------------------------------------------------------------------

    def deposit(self, server_id: str, country_id: str, amount: float) -> float:
        """Add a one-off amount to the treasury (gifts, looting, events, etc.)."""
        if amount < 0:
            raise ValueError("Use withdraw() to remove gold.")
        row          = self._db.get_or_create_country(server_id, country_id)
        new_treasury = float(row["treasury"]) + amount
        self._db.update_fields(server_id, country_id, treasury=new_treasury)
        return new_treasury

    def withdraw(self, server_id: str, country_id: str, amount: float) -> float:
        """
        Remove a one-off amount from the treasury.
        Treasury is clamped to 0 — a country cannot go into debt via this method.

        Returns the new treasury balance.
        """
        if amount < 0:
            raise ValueError("Use deposit() to add gold.")
        row          = self._db.get_or_create_country(server_id, country_id)
        new_treasury = max(0.0, float(row["treasury"]) - amount)
        self._db.update_fields(server_id, country_id, treasury=new_treasury)
        return new_treasury

    def transfer(
        self,
        server_id: str,
        payer:     str,
        receiver:  str,
        amount:    float,
    ) -> dict:
        """
        Move ``amount`` gold from ``payer`` to ``receiver`` on the same server.
        Useful for war reparations, tribute, and trade.
        Payer treasury is clamped at 0.

        Returns a dict with new balances: {payer: float, receiver: float}.
        """
        if amount <= 0:
            raise ValueError("Transfer amount must be positive.")
        new_payer    = self.withdraw(server_id, payer, amount)
        new_receiver = self.deposit(server_id, receiver, amount)
        return {"payer": new_payer, "receiver": new_receiver}

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def update_all_treasuries(self, server_id: str, days_passed: int) -> dict[str, float]:
        """
        Apply income to every country registered on a server for a given
        number of in-game days.  Returns a mapping of country_id → new_treasury.
        """
        result = {}
        for row in self._db.get_all_countries(server_id):
            new_treasury = self.update_treasury(server_id, row["country_id"], days_passed)
            result[row["country_id"]] = new_treasury
        return result
