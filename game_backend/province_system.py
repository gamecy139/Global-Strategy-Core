"""
PROVINCE SYSTEM
---------------
Manages per-province state: ownership, core status, and religion.
Supports time-gated core and religion conversion processes.

Each province has:
  owner_country               — which country currently controls it
  is_core                     — 1 if it is a core province for the owner, 0 if not
  religion                    — province religion (one of the Religion enum values)
  core_conversion_target      — country currently converting this province to core
  core_conversion_start_day   — when core conversion began (absolute in-game day)
  religion_conversion_target  — religion being converted to
  religion_conversion_start_day — when religion conversion began

Conversion durations:
  Core conversion:     4 months = 120 in-game days
  Religion conversion: 6 months = 180 in-game days
"""

from __future__ import annotations

from game_backend.db import Database

DAYS_PER_MONTH: int = 30

CORE_CONVERSION_DAYS:     int = 4 * DAYS_PER_MONTH   # 120 days
RELIGION_CONVERSION_DAYS: int = 6 * DAYS_PER_MONTH   # 180 days


class ProvinceSystem:
    """
    Manages province state and conversion queues.

    Parameters
    ----------
    db : Database
        Shared database instance.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Province registration
    # ------------------------------------------------------------------

    def register_province(
        self,
        server_id:     str,
        province_id:   str,
        owner_country: str,
        is_core:       bool = True,
        religion:      str  = "Atheism",
    ) -> None:
        """
        Register a province.  Safe to call multiple times (upsert).
        """
        self._db.upsert_province(
            server_id     = server_id,
            province_id   = province_id,
            owner_country = owner_country,
            is_core       = is_core,
            religion      = religion,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_province(self, server_id: str, province_id: str) -> dict | None:
        """Return the province state dict, or None if not registered."""
        return self._db.get_province(server_id, province_id)

    def get_provinces_by_country(
        self, server_id: str, country_id: str
    ) -> list[dict]:
        """Return all provinces owned by a country."""
        return self._db.get_provinces_by_owner(server_id, country_id)

    def get_non_core_provinces(
        self, server_id: str, country_id: str
    ) -> list[dict]:
        """
        Return provinces owned by ``country_id`` that are NOT cores
        (i.e. recently conquered or transferred).
        """
        return [
            p for p in self._db.get_provinces_by_owner(server_id, country_id)
            if not p["is_core"]
        ]

    def get_religion_mismatch_provinces(
        self,
        server_id:        str,
        country_id:       str,
        country_religion: str,
    ) -> list[dict]:
        """
        Return provinces owned by ``country_id`` whose religion differs
        from the country's official religion.  Used by the Unrest system.
        """
        return [
            p for p in self._db.get_provinces_by_owner(server_id, country_id)
            if p["religion"].lower() != country_religion.lower()
        ]

    def get_all_provinces(self, server_id: str) -> list[dict]:
        return self._db.get_all_provinces(server_id)

    # ------------------------------------------------------------------
    # Ownership
    # ------------------------------------------------------------------

    def transfer_province(
        self,
        server_id:     str,
        province_id:   str,
        new_owner:     str,
        make_core:     bool = False,
    ) -> None:
        """
        Transfer a province to a new owner.
        By default the province is NOT a core for the new owner (conquered).
        Pass ``make_core=True`` for legitimate cession or homeland assignment.
        """
        prov = self._require_province(server_id, province_id)

        # Cancel any in-progress conversions from the old owner
        self._db.update_province_fields(
            server_id, province_id,
            owner_country               = new_owner,
            is_core                     = int(make_core),
            core_conversion_target      = None,
            core_conversion_start_day   = 0,
            religion_conversion_target  = None,
            religion_conversion_start_day = 0,
        )

    def set_core(
        self,
        server_id:   str,
        province_id: str,
        is_core:     bool,
    ) -> None:
        """Directly set the is_core flag (admin / scripted events)."""
        self._require_province(server_id, province_id)
        self._db.update_province_fields(
            server_id, province_id, is_core=int(is_core)
        )

    # ------------------------------------------------------------------
    # Core conversion
    # ------------------------------------------------------------------

    def start_core_conversion(
        self,
        server_id:      str,
        province_id:    str,
        target_country: str,
        current_day:    int,
    ) -> dict:
        """
        Begin converting a province to a core for ``target_country``.
        Duration: 4 in-game months (120 days).

        Raises ValueError if:
          • Province not found.
          • Province is already a core for the target.
          • Conversion already in progress.

        Returns a dict with completion_day.
        """
        prov = self._require_province(server_id, province_id)

        if prov["is_core"] and prov["owner_country"] == target_country:
            raise ValueError(
                f"Province '{province_id}' is already a core for '{target_country}'."
            )
        if prov.get("core_conversion_target"):
            raise ValueError(
                f"Core conversion already in progress for '{province_id}'."
            )

        self._db.update_province_fields(
            server_id, province_id,
            core_conversion_target    = target_country,
            core_conversion_start_day = current_day,
        )
        return {
            "province_id":    province_id,
            "target_country": target_country,
            "start_day":      current_day,
            "completion_day": current_day + CORE_CONVERSION_DAYS,
        }

    def cancel_core_conversion(self, server_id: str, province_id: str) -> None:
        """Cancel an ongoing core conversion."""
        self._db.update_province_fields(
            server_id, province_id,
            core_conversion_target    = None,
            core_conversion_start_day = 0,
        )

    # ------------------------------------------------------------------
    # Religion conversion
    # ------------------------------------------------------------------

    def start_religion_conversion(
        self,
        server_id:       str,
        province_id:     str,
        target_religion: str,
        current_day:     int,
    ) -> dict:
        """
        Begin converting the province's religion.
        Duration: 6 in-game months (180 days).

        Raises ValueError if:
          • Province already follows the target religion.
          • Religion conversion already in progress.

        Returns a dict with completion_day.
        """
        from game_backend.religion_system import Religion
        Religion.parse(target_religion)   # Validate religion name

        prov = self._require_province(server_id, province_id)

        if prov["religion"].lower() == target_religion.lower():
            raise ValueError(
                f"Province '{province_id}' already follows '{target_religion}'."
            )
        if prov.get("religion_conversion_target"):
            raise ValueError(
                f"Religion conversion already in progress for '{province_id}'."
            )

        self._db.update_province_fields(
            server_id, province_id,
            religion_conversion_target    = target_religion,
            religion_conversion_start_day = current_day,
        )
        return {
            "province_id":    province_id,
            "target_religion": target_religion,
            "start_day":      current_day,
            "completion_day": current_day + RELIGION_CONVERSION_DAYS,
        }

    def cancel_religion_conversion(self, server_id: str, province_id: str) -> None:
        self._db.update_province_fields(
            server_id, province_id,
            religion_conversion_target    = None,
            religion_conversion_start_day = 0,
        )

    # ------------------------------------------------------------------
    # Conversion tick — call this each game tick
    # ------------------------------------------------------------------

    def process_conversions(
        self,
        server_id:   str,
        current_day: int,
    ) -> list[dict]:
        """
        Check all in-progress conversions and complete any that have elapsed.

        Returns a list of completion events, each describing what changed.
        Call this on every game tick or at least once per in-game day.
        """
        completed: list[dict] = []

        for prov in self._db.get_provinces_with_active_conversion(server_id):
            pid = prov["province_id"]
            event: dict = {"province_id": pid}

            # Core conversion
            if (prov.get("core_conversion_target") and
                    (current_day - int(prov.get("core_conversion_start_day", 0)))
                    >= CORE_CONVERSION_DAYS):
                target = prov["core_conversion_target"]
                self._db.update_province_fields(
                    server_id, pid,
                    is_core                   = 1,
                    core_conversion_target    = None,
                    core_conversion_start_day = 0,
                )
                event["core_converted_for"] = target
                event["type"] = "core_conversion"
                completed.append(event)

            # Religion conversion
            if (prov.get("religion_conversion_target") and
                    (current_day - int(prov.get("religion_conversion_start_day", 0)))
                    >= RELIGION_CONVERSION_DAYS):
                target_religion = prov["religion_conversion_target"]
                self._db.update_province_fields(
                    server_id, pid,
                    religion                      = target_religion,
                    religion_conversion_target    = None,
                    religion_conversion_start_day = 0,
                )
                event["religion_converted_to"] = target_religion
                event["type"] = event.get("type", "religion_conversion")
                if event not in completed:
                    completed.append(event)

        return completed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_province(self, server_id: str, province_id: str) -> dict:
        prov = self._db.get_province(server_id, province_id)
        if prov is None:
            raise KeyError(
                f"Province '{province_id}' not found on server '{server_id}'. "
                f"Register it first with register_province()."
            )
        return prov
