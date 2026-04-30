"""
WW1 ECONOMY — TREASURY SYSTEM
-------------------------------
Thin wrapper over the ``treasury`` column on ``ww1_economy.countries``.

All operations are isolated by ``(server_id, scenario_id, country_id)``,
and the underlying DB layer guarantees the treasury can never go negative
(deductions that would underflow are atomically rejected).
"""

from __future__ import annotations

from ww1_economy.db import EconomyDB


class TreasurySystem:
    """
    Per-country gold balance.  Used by:
      • BuildingSystem — to deduct construction costs
      • ProductionSystem — to deposit gold from Gold/Gems mines
      • GlobalMarketSystem — to deduct purchase costs
      • TickSystem — to apply daily income (final, after tax + efficiency)

    Parameters
    ----------
    db : EconomyDB
        Shared database instance.
    """

    def __init__(self, db: EconomyDB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, server_id: str, scenario_id: str, country_id: str) -> float:
        row = self._db.get_country(server_id, scenario_id, country_id)
        if row is None:
            raise ValueError(
                f"Country '{country_id}' not found in scenario '{scenario_id}'."
            )
        return float(row.get("treasury") or 0.0)

    def has_enough(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        amount:      float,
    ) -> bool:
        if amount < 0:
            raise ValueError("amount must be non-negative.")
        return self.get(server_id, scenario_id, country_id) >= amount

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def deposit(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        amount:      float,
    ) -> float:
        """Add ``amount`` gold to treasury. Returns the new balance."""
        if amount < 0:
            raise ValueError("Use deduct() to remove gold.")
        # Make sure the country exists; otherwise the UPDATE silently no-ops.
        row = self._db.get_country(server_id, scenario_id, country_id)
        if row is None:
            raise ValueError(
                f"Country '{country_id}' not found in scenario '{scenario_id}'."
            )
        if amount == 0:
            return float(row.get("treasury") or 0.0)
        return self._db.deposit_treasury(
            server_id, scenario_id, country_id, float(amount)
        )

    def deduct(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        amount:      float,
    ) -> tuple[bool, float]:
        """
        Atomically deduct ``amount`` IFF the treasury has enough.

        Returns ``(success, new_balance)``.  When ``success`` is False the
        treasury is unchanged and ``new_balance`` is the current balance.
        Treasury is guaranteed never to go negative.
        """
        if amount < 0:
            raise ValueError("amount must be non-negative.")
        # Make sure the country exists.
        row = self._db.get_country(server_id, scenario_id, country_id)
        if row is None:
            raise ValueError(
                f"Country '{country_id}' not found in scenario '{scenario_id}'."
            )
        if amount == 0:
            return True, float(row.get("treasury") or 0.0)
        return self._db.deduct_treasury(
            server_id, scenario_id, country_id, float(amount)
        )

    def set(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        amount:      float,
    ) -> None:
        """Direct setter for admin / scripted seeding. Cannot go negative."""
        if amount < 0:
            raise ValueError("Treasury cannot be negative.")
        self._db.update_country_fields(
            server_id, scenario_id, country_id, treasury=float(amount)
        )
