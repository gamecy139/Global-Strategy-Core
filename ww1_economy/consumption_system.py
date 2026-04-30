"""
WW1 ECONOMY — RESOURCE CONSUMPTION SYSTEM (SHARED POOL)
--------------------------------------------------------
Runs once per in-game month, BEFORE production.

Behaviour (per country, per scenario):

    1. Sum the per-month resource requirement of every COMPLETED Tier 2
       building owned by the country.  (Tier 1 buildings consume nothing.)
    2. If the country's storage covers the FULL aggregate requirement:
         • Deduct every required resource from storage.
         • Mark every COMPLETED building of that country as ACTIVE
           (both Tier 1 and Tier 2).  Tier 1 buildings have no consumption
           cost so they always activate trivially.
    3. Otherwise (any single resource short):
         • Deduct NOTHING (no partial consumption).
         • Mark every COMPLETED building of that country as INACTIVE,
           causing ProductionSystem to skip them this month.

Storage is guaranteed never to go negative — we always check before deducting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ww1_economy.db             import EconomyDB
from ww1_economy.storage_system import StorageSystem
from ww1_economy.resources      import (
    BUILDING_CONSUMPTION,
    BuildingType,
    consumption_for,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CountryConsumption:
    country_id:      str
    required:        dict[str, int] = field(default_factory=dict)
    available:       dict[str, int] = field(default_factory=dict)
    shortfalls:      dict[str, int] = field(default_factory=dict)
    deducted:        dict[str, int] = field(default_factory=dict)
    activated:       bool           = False
    buildings_total: int            = 0
    tier2_total:     int            = 0

    def to_dict(self) -> dict:
        return {
            "country_id":      self.country_id,
            "required":        self.required,
            "available":       self.available,
            "shortfalls":      self.shortfalls,
            "deducted":        self.deducted,
            "activated":       self.activated,
            "buildings_total": self.buildings_total,
            "tier2_total":     self.tier2_total,
        }


@dataclass
class ConsumptionReport:
    server_id:   str
    scenario_id: str
    by_country:  dict[str, CountryConsumption] = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "server_id":   self.server_id,
            "scenario_id": self.scenario_id,
            "countries":   {k: v.to_dict() for k, v in self.by_country.items()},
        }


# ---------------------------------------------------------------------------
# ResourceConsumptionSystem
# ---------------------------------------------------------------------------

class ResourceConsumptionSystem:
    """
    Monthly shared-pool consumption.  Always isolates by
    ``(server_id, scenario_id)``.

    Parameters
    ----------
    db      : EconomyDB     — shared database instance.
    storage : StorageSystem — used to read and deduct from country storage.
    """

    def __init__(self, db: EconomyDB, storage: StorageSystem) -> None:
        self._db      = db
        self._storage = storage

    # ------------------------------------------------------------------
    # Main monthly call
    # ------------------------------------------------------------------

    def run_monthly(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> ConsumptionReport:
        """
        Aggregate consumption for every country in the scenario, deduct
        atomically per country (all-or-nothing), and flip each country's
        completed buildings between ACTIVE / INACTIVE accordingly.
        """
        report = ConsumptionReport(server_id=server_id, scenario_id=scenario_id)

        # Group COMPLETED buildings by country
        completed = self._db.get_completed_buildings(server_id, scenario_id)
        by_country: dict[str, list[dict]] = {}
        for b in completed:
            by_country.setdefault(b["country_id"], []).append(b)

        for country_id, buildings in by_country.items():
            cc = CountryConsumption(country_id=country_id)
            cc.buildings_total = len(buildings)

            # ------ Aggregate required resources ----------------------
            required: dict[str, int] = {}
            for b in buildings:
                req = consumption_for(b["building_type"])
                if req:
                    cc.tier2_total += 1
                    for res, qty in req.items():
                        required[res] = required.get(res, 0) + qty
            cc.required = required

            # ------ Compare against storage ---------------------------
            available: dict[str, int] = {}
            shortfalls: dict[str, int] = {}
            for res, need in required.items():
                have = self._storage.get_resource(
                    server_id, scenario_id, country_id, res
                )
                available[res] = have
                if have < need:
                    shortfalls[res] = need - have
            cc.available  = available
            cc.shortfalls = shortfalls

            # ------ All-or-nothing decision ---------------------------
            if shortfalls:
                # Not enough → INACTIVE for ALL completed buildings
                self._db.set_buildings_active_for_country(
                    server_id, scenario_id, country_id, is_active=False
                )
                cc.activated = False
            else:
                # Enough → deduct everything atomically, then activate all
                deducted: dict[str, int] = {}
                for res, need in required.items():
                    if need > 0:
                        self._storage.deduct(
                            server_id, scenario_id, country_id, res, need
                        )
                        deducted[res] = need
                cc.deducted = deducted

                self._db.set_buildings_active_for_country(
                    server_id, scenario_id, country_id, is_active=True
                )
                cc.activated = True

            report.by_country[country_id] = cc

        return report

    # ------------------------------------------------------------------
    # Read-only previews (no DB writes)
    # ------------------------------------------------------------------

    def preview_for_country(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> CountryConsumption:
        """Compute what would happen on the next monthly tick — no writes."""
        cc = CountryConsumption(country_id=country_id)
        buildings = [
            b for b in self._db.get_buildings_by_country(
                server_id, scenario_id, country_id
            ) if b["is_completed"]
        ]
        cc.buildings_total = len(buildings)

        required: dict[str, int] = {}
        for b in buildings:
            req = consumption_for(b["building_type"])
            if req:
                cc.tier2_total += 1
                for res, qty in req.items():
                    required[res] = required.get(res, 0) + qty

        available  = {}
        shortfalls = {}
        for res, need in required.items():
            have = self._storage.get_resource(
                server_id, scenario_id, country_id, res
            )
            available[res] = have
            if have < need:
                shortfalls[res] = need - have

        cc.required   = required
        cc.available  = available
        cc.shortfalls = shortfalls
        cc.activated  = not shortfalls
        return cc
