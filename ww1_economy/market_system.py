"""
WW1 ECONOMY — GLOBAL MARKET SYSTEM
------------------------------------
A scenario-wide marketplace where countries can buy any of the 14 tradable
resources (Tier 1 commodities + Tier 2 finished goods).

Behaviour summary
-----------------
buy_resource(...):
    1. Reject if the resource is in shortage.
    2. cost = current_price × quantity
    3. Reject if treasury < cost.
    4. Atomically deduct gold (treasury can never go negative).
    5. Add the resource to storage (storage is bounded ≥ 0 by construction).
    6. current_month_demand += quantity.

update_market_monthly(current_month):
    For every market resource on the scenario:
      • Adjust price based on current_month_demand (-5%, 0%, +5%, +10%).
      • Clamp current_price to [70%, 200%] of base_price.
      • If rolling_demand (current + previous) ≥ 500, declare a shortage:
            shortage = True
            shortage_end_month = current_month + RANDOM(3..6)
      • If current_month >= shortage_end_month, recover:
            shortage = False
            current_price = base_price
      • Roll demand counters:
            previous_month_demand = current_month_demand
            current_month_demand  = 0

All data is keyed by ``(server_id, scenario_id, resource_name)``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ww1_economy.db              import EconomyDB
from ww1_economy.storage_system  import StorageSystem
from ww1_economy.treasury_system import TreasurySystem
from ww1_economy.resources       import (
    MARKET_BASE_PRICES,
    MARKET_RESOURCE_SET,
)


# ---------------------------------------------------------------------------
# Tunables (kept module-level so tests can monkeypatch them deterministically)
# ---------------------------------------------------------------------------

PRICE_FLOOR_FACTOR:   float = 0.70   # min current_price as fraction of base
PRICE_CEILING_FACTOR: float = 2.00   # max current_price as fraction of base

SHORTAGE_THRESHOLD:   int = 500      # rolling_demand ≥ this → shortage
SHORTAGE_DURATION_MIN: int = 3
SHORTAGE_DURATION_MAX: int = 6


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class BuyResult:
    success:        bool
    reason:         str
    resource:       str
    quantity:       int
    unit_price:     float = 0.0
    total_cost:     float = 0.0
    new_treasury:   float = 0.0
    new_storage:    int   = 0
    new_demand:     int   = 0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class MarketResourceUpdate:
    resource:              str
    old_price:             float
    new_price:             float
    base_price:            float
    rolling_demand:        int
    current_month_demand:  int
    previous_month_demand: int
    shortage:              bool
    shortage_end_month:    int
    shortage_started:      bool = False
    shortage_recovered:    bool = False
    notes:                 list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class MarketUpdateReport:
    server_id:     str
    scenario_id:   str
    current_month: int
    updates:       dict[str, MarketResourceUpdate] = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "server_id":     self.server_id,
            "scenario_id":   self.scenario_id,
            "current_month": self.current_month,
            "resources": {k: v.to_dict() for k, v in self.updates.items()},
        }


# ---------------------------------------------------------------------------
# GlobalMarketSystem
# ---------------------------------------------------------------------------

class GlobalMarketSystem:
    """
    Scenario-wide marketplace.

    Parameters
    ----------
    db       : EconomyDB
    storage  : StorageSystem
    treasury : TreasurySystem
    rng      : random.Random | None
        Optional injected RNG for deterministic shortage-duration tests.
    """

    def __init__(
        self,
        db:       EconomyDB,
        storage:  StorageSystem,
        treasury: TreasurySystem,
        rng:      random.Random | None = None,
    ) -> None:
        self._db       = db
        self._storage  = storage
        self._treasury = treasury
        self._rng      = rng or random.Random()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def initialise_market(
        self,
        server_id:   str,
        scenario_id: str,
        prices:      dict[str, float] | None = None,
    ) -> None:
        """
        Insert the per-resource market rows using base prices.  Idempotent —
        existing rows are left untouched, so call it on every server start.
        """
        self._db.init_market_prices(server_id, scenario_id, prices)

    # ------------------------------------------------------------------
    # Buy
    # ------------------------------------------------------------------

    def buy_resource(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        resource:    str,
        quantity:    int,
    ) -> BuyResult:
        """
        Buy ``quantity`` units of ``resource`` from the global market.
        Returns a ``BuyResult``; never raises for the normal failure modes.
        """
        if quantity <= 0:
            return BuyResult(False, "quantity must be positive.", resource, quantity)

        if resource not in MARKET_RESOURCE_SET:
            return BuyResult(
                False,
                f"'{resource}' is not traded on the global market.",
                resource, quantity,
            )

        # Bought goods always go to storage — make sure storage exists.
        try:
            self._storage._validate_resource(resource)  # type: ignore[attr-defined]
        except ValueError as ex:
            return BuyResult(False, str(ex), resource, quantity)

        market = self._db.get_market_resource(server_id, scenario_id, resource)
        if market is None:
            # Lazy-init this single market row at base price.
            base = MARKET_BASE_PRICES.get(resource)
            if base is None:
                return BuyResult(
                    False,
                    f"'{resource}' has no base price configured.",
                    resource, quantity,
                )
            self._db.init_market_prices(
                server_id, scenario_id, {resource: base}
            )
            market = self._db.get_market_resource(server_id, scenario_id, resource)
            assert market is not None

        if int(market.get("shortage") or 0):
            return BuyResult(
                False,
                f"'{resource}' is in shortage; market closed for buyers.",
                resource, quantity,
                unit_price=float(market["current_price"]),
            )

        unit_price = float(market["current_price"])
        total_cost = unit_price * quantity

        # Try to deduct gold — atomic check, never goes negative.
        ok, balance = self._treasury.deduct(
            server_id, scenario_id, country_id, total_cost
        )
        if not ok:
            return BuyResult(
                False,
                f"Insufficient treasury: need {total_cost:.2f} gold, "
                f"have {balance:.2f}.",
                resource, quantity,
                unit_price=unit_price,
                total_cost=total_cost,
                new_treasury=balance,
            )

        # Add to storage.
        new_storage = self._storage.add(
            server_id, scenario_id, country_id, resource, quantity
        )

        # Record demand.
        new_demand = self._db.increment_market_demand(
            server_id, scenario_id, resource, quantity
        )

        return BuyResult(
            success      = True,
            reason       = "Purchase successful.",
            resource     = resource,
            quantity     = quantity,
            unit_price   = unit_price,
            total_cost   = total_cost,
            new_treasury = balance,
            new_storage  = new_storage,
            new_demand   = new_demand,
        )

    # ------------------------------------------------------------------
    # Monthly market tick
    # ------------------------------------------------------------------

    def update_market_monthly(
        self,
        server_id:     str,
        scenario_id:   str,
        current_month: int,
    ) -> MarketUpdateReport:
        """
        Run the full monthly market update for every resource in the
        scenario (lazy-initialising any missing rows from base prices).
        """
        # Make sure every base resource exists.
        self._db.init_market_prices(server_id, scenario_id)

        report = MarketUpdateReport(
            server_id=server_id, scenario_id=scenario_id, current_month=current_month
        )

        for row in self._db.get_all_market(server_id, scenario_id):
            resource    = row["resource_name"]
            base        = float(row["base_price"])
            old_price   = float(row["current_price"])
            cur_demand  = int(row["current_month_demand"])
            prev_demand = int(row["previous_month_demand"])
            shortage    = bool(row["shortage"])
            end_month   = int(row["shortage_end_month"])

            update = MarketResourceUpdate(
                resource              = resource,
                old_price             = old_price,
                new_price             = old_price,
                base_price            = base,
                rolling_demand        = cur_demand + prev_demand,
                current_month_demand  = cur_demand,
                previous_month_demand = prev_demand,
                shortage              = shortage,
                shortage_end_month    = end_month,
            )

            # ---- Price change based on this month's demand --------------
            #   0–29 → -5%, 30–50 → 0%, 51–150 → +5%, 151+ → +10%
            if cur_demand <= 29:
                pct = -0.05
            elif cur_demand <= 50:
                pct =  0.00
            elif cur_demand <= 150:
                pct = +0.05
            else:
                pct = +0.10
            update.notes.append(f"price_pct={pct:+.0%} (demand={cur_demand})")

            new_price = old_price * (1.0 + pct)

            # Bound to [70%, 200%] of base
            min_price = base * PRICE_FLOOR_FACTOR
            max_price = base * PRICE_CEILING_FACTOR
            if new_price < min_price:
                new_price = min_price
                update.notes.append(f"clamped_to_floor={min_price:.2f}")
            elif new_price > max_price:
                new_price = max_price
                update.notes.append(f"clamped_to_ceiling={max_price:.2f}")
            update.new_price = round(new_price, 4)

            # ---- Shortage start / recovery ------------------------------
            rolling = cur_demand + prev_demand
            if not shortage and rolling >= SHORTAGE_THRESHOLD:
                duration = self._rng.randint(
                    SHORTAGE_DURATION_MIN, SHORTAGE_DURATION_MAX
                )
                shortage  = True
                end_month = current_month + duration
                update.shortage_started = True
                update.notes.append(
                    f"shortage_started: rolling_demand={rolling} "
                    f"≥ {SHORTAGE_THRESHOLD}, ends={end_month}"
                )

            recovered = False
            if shortage and current_month >= end_month:
                shortage  = False
                update.shortage_recovered = True
                # Spec: "price reset to base_price"
                new_price = base
                update.new_price = base
                update.notes.append("shortage_recovered: price reset to base")
                recovered = True

            update.shortage           = shortage
            update.shortage_end_month = end_month if shortage else 0

            # ---- Demand shift ------------------------------------------
            new_prev_demand = cur_demand
            new_cur_demand  = 0

            # ---- Persist ------------------------------------------------
            self._db.update_market_fields(
                server_id, scenario_id, resource,
                current_price         = float(update.new_price),
                current_month_demand  = new_cur_demand,
                previous_month_demand = new_prev_demand,
                shortage              = int(shortage),
                shortage_end_month    = end_month if shortage else 0,
            )

            report.updates[resource] = update

        return report

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_price(
        self, server_id: str, scenario_id: str, resource: str
    ) -> float:
        row = self._db.get_market_resource(server_id, scenario_id, resource)
        if row is None:
            base = MARKET_BASE_PRICES.get(resource)
            if base is None:
                raise ValueError(
                    f"'{resource}' is not a market resource."
                )
            return float(base)
        return float(row["current_price"])

    def get_snapshot(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        return self._db.get_all_market(server_id, scenario_id)

    def is_in_shortage(
        self, server_id: str, scenario_id: str, resource: str
    ) -> bool:
        row = self._db.get_market_resource(server_id, scenario_id, resource)
        return bool(row and int(row.get("shortage") or 0))
