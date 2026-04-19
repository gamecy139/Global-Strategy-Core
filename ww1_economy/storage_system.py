"""
WW1 ECONOMY — STORAGE SYSTEM
------------------------------
Manages country resource storage for a single scenario.

Gold is NOT stored here — it goes directly to the country treasury
(handled by the calling game layer or EconomySystem).

All operations are keyed by (server_id, scenario_id, country_id) for
full multi-server and multi-scenario isolation.
"""

from __future__ import annotations

from ww1_economy.db        import EconomyDB
from ww1_economy.resources import STORABLE_RESOURCES, STORABLE_RESOURCE_SET


class StorageSystem:
    """
    Manages country_storage reads and writes.

    Parameters
    ----------
    db : EconomyDB
        Shared database instance (must have been initialised via ``db.init()``).
    """

    def __init__(self, db: EconomyDB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_all(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict:
        """
        Return the full storage snapshot for a country.
        Creates the storage row with zeroes if it does not yet exist.
        """
        row = self._db.get_or_create_storage(server_id, scenario_id, country_id)
        # Return only resource columns (drop meta-columns)
        return {
            k: int(v) for k, v in row.items()
            if k in STORABLE_RESOURCE_SET
        }

    def get_resource(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        resource:    str,
    ) -> int:
        """Return the stored amount of a single resource."""
        self._validate_resource(resource)
        row = self._db.get_or_create_storage(server_id, scenario_id, country_id)
        return int(row.get(resource, 0))

    def get_all_countries(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        """Return storage snapshots for all countries in a scenario."""
        return self._db.get_all_storage(server_id, scenario_id)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        resource:    str,
        amount:      int,
    ) -> int:
        """
        Add ``amount`` of ``resource`` to storage.
        Returns the new total.
        Raises ValueError for negative amounts.
        """
        self._validate_resource(resource)
        if amount < 0:
            raise ValueError(
                f"Use deduct() to remove resources. "
                f"Amount must be non-negative, got {amount}."
            )
        return self._db.add_to_storage(
            server_id, scenario_id, country_id, resource, amount
        )

    def deduct(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        resource:    str,
        amount:      int,
        allow_partial: bool = False,
    ) -> int:
        """
        Deduct ``amount`` from storage.

        Parameters
        ----------
        allow_partial : bool
            If True, deduct as much as available (clamped to 0).
            If False (default), raises ValueError when storage < amount.

        Returns the new total.
        """
        self._validate_resource(resource)
        if amount < 0:
            raise ValueError(f"Deduct amount must be non-negative, got {amount}.")

        current = self.get_resource(server_id, scenario_id, country_id, resource)
        if not allow_partial and current < amount:
            raise ValueError(
                f"Insufficient {resource}. "
                f"Have {current}, need {amount}."
            )
        return self._db.deduct_from_storage(
            server_id, scenario_id, country_id, resource, amount
        )

    def set_resource(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        resource:    str,
        amount:      int,
    ) -> None:
        """Directly set a resource to a specific amount (admin / scripted events)."""
        self._validate_resource(resource)
        if amount < 0:
            raise ValueError(f"Storage amount cannot be negative, got {amount}.")
        self._db.update_storage_resource(
            server_id, scenario_id, country_id, resource, amount
        )

    def add_batch(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        resources:   dict[str, int],
    ) -> dict[str, int]:
        """
        Add multiple resources in one call.
        Returns a dict of resource → new total.
        """
        result: dict[str, int] = {}
        for resource, amount in resources.items():
            result[resource] = self.add(
                server_id, scenario_id, country_id, resource, amount
            )
        return result

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def has_enough(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        resource:    str,
        amount:      int,
    ) -> bool:
        """Return True if the country has at least ``amount`` of ``resource``."""
        return self.get_resource(server_id, scenario_id, country_id, resource) >= amount

    def has_enough_batch(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        requirements: dict[str, int],
    ) -> dict[str, bool]:
        """
        Check multiple resource requirements at once.
        Returns {resource: bool} for each entry.
        """
        return {
            res: self.has_enough(server_id, scenario_id, country_id, res, amt)
            for res, amt in requirements.items()
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_resource(resource: str) -> None:
        if resource not in STORABLE_RESOURCE_SET:
            raise ValueError(
                f"'{resource}' is not a storable resource. "
                f"Valid resources: {', '.join(STORABLE_RESOURCES)}"
            )
