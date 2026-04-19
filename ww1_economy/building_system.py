"""
WW1 ECONOMY — BUILDING SYSTEM
-------------------------------
Manages building construction, completion, and validation for all provinces
within a scenario.

Validation rules enforced here:
  • Only ONE Tier 1 building per province.
  • Tier 1 building must match the province's natural resource.
  • Only ONE of each Tier 2 building type per province.
  • Duplicate construction is prevented (build already exists or in progress).

All data is keyed by (server_id, scenario_id) for full multi-server and
multi-scenario isolation.
"""

from __future__ import annotations

from ww1_economy.db        import EconomyDB
from ww1_economy.resources import (
    BuildingType,
    BuildingTier,
    BUILDING_CONFIGS,
    TIER1_BUILDING_TYPES,
    TIER2_BUILDING_TYPES,
    DAYS_PER_MONTH,
    get_config,
    resolve_tier1_production_resource,
)


class BuildingSystem:
    """
    Manages construction queues and building state for all provinces.

    Parameters
    ----------
    db : EconomyDB
        Shared database instance (must have been initialised via ``db.init()``).
    """

    def __init__(self, db: EconomyDB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def start_construction(
        self,
        server_id:        str,
        scenario_id:      str,
        province_id:      str,
        country_id:       str,
        building_type:    str | BuildingType,
        province_resource: str,
        current_day:      int,
    ) -> dict:
        """
        Begin constructing a building in a province.

        Parameters
        ----------
        building_type     : The building to construct (name or enum).
        province_resource : The natural resource of the province (Tier 1 gate).
        current_day       : Absolute in-game day when construction starts.

        Returns a result dict:
            allowed          : bool
            reason           : str
            building_type    : str (if allowed)
            completion_day   : int (if allowed)
            cost             : float gold (if allowed)

        Raises ValueError for unknown building types.
        Does NOT deduct gold — the caller is responsible for paying the cost.
        """
        cfg = get_config(building_type)
        btype = cfg.building_type

        # ---- Validation -----------------------------------------------

        existing = self._db.get_buildings_in_province(
            server_id, scenario_id, province_id
        )

        if btype.value in TIER1_BUILDING_TYPES or btype in TIER1_BUILDING_TYPES:
            ok, reason = self._validate_tier1(
                btype, province_resource, existing
            )
        else:
            ok, reason = self._validate_tier2(btype, existing)

        if not ok:
            return {"allowed": False, "reason": reason}

        # ---- Resource type stored with the building --------------------

        if cfg.is_tier1:
            resource_type = province_resource
        else:
            resource_type = None

        # ---- Insert ---------------------------------------------------

        completion_day = current_day + cfg.construction_days
        self._db.insert_building(
            server_id               = server_id,
            scenario_id             = scenario_id,
            province_id             = province_id,
            country_id              = country_id,
            building_type           = btype.value,
            resource_type           = resource_type,
            construction_start_time = current_day,
            construction_end_time   = completion_day,
            is_completed            = False,
        )

        return {
            "allowed":        True,
            "reason":         "Construction started.",
            "building_type":  btype.value,
            "province_id":    province_id,
            "country_id":     country_id,
            "resource_type":  resource_type,
            "start_day":      current_day,
            "completion_day": completion_day,
            "cost":           cfg.construction_cost_gold,
        }

    def complete_construction(
        self,
        server_id:    str,
        scenario_id:  str,
        province_id:  str,
        building_type: str,
    ) -> bool:
        """
        Manually mark a building as completed.
        Returns True if the building was found and updated, False otherwise.
        """
        row = self._db.get_building(
            server_id, scenario_id, province_id, building_type
        )
        if row is None:
            return False
        self._db.update_building_fields(
            server_id, scenario_id, province_id, building_type,
            is_completed=1,
        )
        return True

    def cancel_construction(
        self,
        server_id:    str,
        scenario_id:  str,
        province_id:  str,
        building_type: str,
    ) -> bool:
        """
        Cancel an in-progress construction and remove the building record.
        Returns True if cancelled, False if not found or already completed.
        """
        row = self._db.get_building(
            server_id, scenario_id, province_id, building_type
        )
        if row is None or row["is_completed"]:
            return False
        self._db.delete_building(
            server_id, scenario_id, province_id, building_type
        )
        return True

    def demolish(
        self,
        server_id:    str,
        scenario_id:  str,
        province_id:  str,
        building_type: str,
    ) -> bool:
        """
        Demolish a completed building.
        Returns True if demolished, False if not found.
        """
        row = self._db.get_building(
            server_id, scenario_id, province_id, building_type
        )
        if row is None:
            return False
        self._db.delete_building(
            server_id, scenario_id, province_id, building_type
        )
        return True

    # ------------------------------------------------------------------
    # Construction tick — call each game day
    # ------------------------------------------------------------------

    def process_completions(
        self,
        server_id:   str,
        scenario_id: str,
        current_day: int,
    ) -> list[dict]:
        """
        Check all buildings under construction and complete any that have
        reached their ``construction_end_time``.

        Returns a list of completion event dicts for all buildings completed
        in this call.  Call this on every game tick or at minimum every day.
        """
        completed: list[dict] = []
        for row in self._db.get_under_construction(server_id, scenario_id):
            if current_day >= int(row["construction_end_time"]):
                self._db.update_building_fields(
                    row["server_id"],
                    row["scenario_id"],
                    row["province_id"],
                    row["building_type"],
                    is_completed=1,
                )
                completed.append({
                    "province_id":   row["province_id"],
                    "country_id":    row["country_id"],
                    "building_type": row["building_type"],
                    "resource_type": row.get("resource_type"),
                })
        return completed

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_buildings_in_province(
        self,
        server_id:   str,
        scenario_id: str,
        province_id: str,
    ) -> list[dict]:
        return self._db.get_buildings_in_province(server_id, scenario_id, province_id)

    def get_buildings_by_country(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> list[dict]:
        return self._db.get_buildings_by_country(server_id, scenario_id, country_id)

    def get_all_buildings(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        return self._db.get_all_buildings(server_id, scenario_id)

    def get_completed_buildings(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        return self._db.get_completed_buildings(server_id, scenario_id)

    def get_under_construction(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        return self._db.get_under_construction(server_id, scenario_id)

    def get_building(
        self,
        server_id:    str,
        scenario_id:  str,
        province_id:  str,
        building_type: str,
    ) -> dict | None:
        return self._db.get_building(
            server_id, scenario_id, province_id, building_type
        )

    # ------------------------------------------------------------------
    # Validation (public, for pre-checks before attempting construction)
    # ------------------------------------------------------------------

    def can_build(
        self,
        server_id:         str,
        scenario_id:       str,
        province_id:       str,
        building_type:     str | BuildingType,
        province_resource: str,
    ) -> tuple[bool, str]:
        """
        Check whether a building can be placed without actually inserting it.
        Returns (allowed: bool, reason: str).
        """
        cfg      = get_config(building_type)
        btype    = cfg.building_type
        existing = self._db.get_buildings_in_province(
            server_id, scenario_id, province_id
        )
        if btype in TIER1_BUILDING_TYPES:
            return self._validate_tier1(btype, province_resource, existing)
        return self._validate_tier2(btype, existing)

    # ------------------------------------------------------------------
    # Internal validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_tier1(
        btype:             BuildingType,
        province_resource: str,
        existing_buildings: list[dict],
    ) -> tuple[bool, str]:
        cfg = BUILDING_CONFIGS[btype]

        # Rule: Tier 1 must match province resource
        if province_resource not in cfg.allowed_resources:
            return False, (
                f"Cannot build '{btype.value}' here. "
                f"Province resource is '{province_resource}', "
                f"but '{btype.value}' requires one of: "
                f"{sorted(cfg.allowed_resources)}."
            )

        # Rule: only ONE Tier 1 building per province
        for row in existing_buildings:
            existing_cfg = get_config(row["building_type"])
            if existing_cfg.is_tier1:
                return False, (
                    f"Province already has a Tier 1 building "
                    f"('{row['building_type']}'). "
                    f"Only one Tier 1 building is allowed per province."
                )

        return True, "Tier 1 construction allowed."

    @staticmethod
    def _validate_tier2(
        btype:             BuildingType,
        existing_buildings: list[dict],
    ) -> tuple[bool, str]:
        # Rule: only ONE of each Tier 2 building type per province
        for row in existing_buildings:
            if row["building_type"] == btype.value:
                status = "completed" if row["is_completed"] else "under construction"
                return False, (
                    f"Province already has a '{btype.value}' ({status}). "
                    f"Only one of each Tier 2 building type is allowed per province."
                )
        return True, "Tier 2 construction allowed."
