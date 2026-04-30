"""
WW1 ECONOMY — TICK SYSTEM (FINAL ORCHESTRATOR)
-----------------------------------------------
Wires the entire WW1 economy into one coherent loop.

DAILY TICK (run every in-game day)
----------------------------------
For every country in the scenario:
    1. Compute final_income using the canonical formula
           taxed   = daily_base_income * tax_multiplier
           final   = taxed             * economy_efficiency
    2. treasury += final_income
       (Treasury can never go negative — daily income only adds.)

MONTHLY TICK (run on each in-game month boundary)
-------------------------------------------------
The order below is mandatory.  Every step is keyed by
(server_id, scenario_id) and never crosses scenarios.

    1. ResourceConsumptionSystem.run_monthly()
         — shared-pool deduction; flips buildings to ACTIVE / INACTIVE.
    2. (Buildings table now reflects activation state from step 1.)
    3. ProductionSystem.run_monthly_production()
         — only ACTIVE buildings produce; horses / textiles never stored;
           gold + gems mines deposit gold to treasury directly.
    4. (Gold from gold/gems mines was already credited inside step 3 when
       a TreasurySystem is wired in — no extra step needed.)
    5. GlobalMarketSystem.update_market_monthly(current_month)
         — re-prices every resource and starts/ends shortages.
    6. EconomyEfficiencySystem.recompute_all(current_month)
         — recomputes the multiplier from opinion / unrest / war state,
           bounded to [0.5, 1.3], ready for next month's daily ticks.
    7. (Unrest updates and population growth are simple setters on the
       countries table — the spec lists them as separate gameplay hooks
       that game logic outside this module is free to call before / after
       this orchestrator.  No new gameplay system is invented here.)

GLOBAL RULES (enforced everywhere this orchestrator touches):
    • Treasury never goes negative.
    • Storage never goes negative.
    • All operations partitioned by (server_id, scenario_id).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ww1_economy.db                  import EconomyDB
from ww1_economy.storage_system      import StorageSystem
from ww1_economy.treasury_system     import TreasurySystem
from ww1_economy.building_system     import BuildingSystem
from ww1_economy.consumption_system  import (
    ResourceConsumptionSystem, ConsumptionReport,
)
from ww1_economy.production_system   import ProductionSystem, ProductionReport
from ww1_economy.market_system       import GlobalMarketSystem, MarketUpdateReport
from ww1_economy.efficiency_system   import (
    EconomyEfficiencySystem, EfficiencyResult, apply_income_formula,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CountryDailyResult:
    country_id:         str
    base_income:        float
    tax_multiplier:     float
    economy_efficiency: float
    taxed_income:       float
    final_income:       float
    days_passed:        int
    income_added:       float
    treasury_after:     float


@dataclass
class DailyTickReport:
    server_id:    str
    scenario_id:  str
    days_passed:  int
    countries:    dict[str, CountryDailyResult] = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "server_id":   self.server_id,
            "scenario_id": self.scenario_id,
            "days_passed": self.days_passed,
            "countries": {
                cid: r.__dict__ for cid, r in self.countries.items()
            },
        }


@dataclass
class MonthlyTickReport:
    server_id:    str
    scenario_id:  str
    current_month: int
    consumption:  ConsumptionReport
    production:   ProductionReport
    market:       MarketUpdateReport
    efficiency:   dict[str, EfficiencyResult]

    def summary(self) -> dict:
        return {
            "server_id":     self.server_id,
            "scenario_id":   self.scenario_id,
            "current_month": self.current_month,
            "consumption":   self.consumption.summary(),
            "production":    self.production.summary(),
            "market":        self.market.summary(),
            "efficiency":    {k: v.to_dict() for k, v in self.efficiency.items()},
        }


# ---------------------------------------------------------------------------
# TickSystem
# ---------------------------------------------------------------------------

class TickSystem:
    """
    Top-level orchestrator that wires every subsystem together.  The caller
    is responsible for passing the absolute ``current_day`` (for completion
    of in-progress construction) and ``current_month`` (for market &
    efficiency state).

    Parameters
    ----------
    db          : EconomyDB
    storage     : StorageSystem
    treasury    : TreasurySystem
    buildings   : BuildingSystem
    consumption : ResourceConsumptionSystem
    production  : ProductionSystem
    market      : GlobalMarketSystem
    efficiency  : EconomyEfficiencySystem
    """

    def __init__(
        self,
        db:          EconomyDB,
        storage:     StorageSystem,
        treasury:    TreasurySystem,
        buildings:   BuildingSystem,
        consumption: ResourceConsumptionSystem,
        production:  ProductionSystem,
        market:      GlobalMarketSystem,
        efficiency:  EconomyEfficiencySystem,
    ) -> None:
        self._db          = db
        self._storage     = storage
        self._treasury    = treasury
        self._buildings   = buildings
        self._consumption = consumption
        self._production  = production
        self._market      = market
        self._efficiency  = efficiency

    # ------------------------------------------------------------------
    # Convenience constructor — wires every subsystem from one db handle.
    # ------------------------------------------------------------------

    @classmethod
    def assemble(cls, db: EconomyDB) -> "TickSystem":
        storage     = StorageSystem(db)
        treasury    = TreasurySystem(db)
        buildings   = BuildingSystem(db)
        consumption = ResourceConsumptionSystem(db, storage)
        production  = ProductionSystem(db, storage, treasury)
        market      = GlobalMarketSystem(db, storage, treasury)
        efficiency  = EconomyEfficiencySystem(db)
        return cls(
            db=db, storage=storage, treasury=treasury,
            buildings=buildings, consumption=consumption,
            production=production, market=market, efficiency=efficiency,
        )

    # ==================================================================
    # DAILY TICK
    # ==================================================================

    def daily_tick(
        self,
        server_id:   str,
        scenario_id: str,
        current_day: int,
        days_passed: int = 1,
    ) -> DailyTickReport:
        """
        Run a daily tick:
          1. Complete any constructions whose end day has been reached.
          2. For every country, calculate final_income and add
             ``final_income * days_passed`` to the treasury.
        """
        if days_passed < 0:
            raise ValueError("days_passed must be non-negative.")

        # 1. Process construction completions through ``current_day``.
        self._buildings.process_completions(server_id, scenario_id, current_day)

        report = DailyTickReport(
            server_id=server_id, scenario_id=scenario_id, days_passed=days_passed
        )
        if days_passed == 0:
            return report

        # 2. Walk every country and apply income.
        for crow in self._db.get_all_countries(server_id, scenario_id):
            cid    = crow["country_id"]
            base   = float(crow.get("daily_base_income") or 0.0)
            tax    = float(crow.get("tax_multiplier")    or 1.0)
            eff    = float(crow.get("economy_efficiency") or 1.0)

            f      = apply_income_formula(base, tax, eff)
            income = f["final_income"] * days_passed

            new_balance = self._treasury.deposit(
                server_id, scenario_id, cid, income
            ) if income > 0 else self._treasury.get(server_id, scenario_id, cid)

            report.countries[cid] = CountryDailyResult(
                country_id         = cid,
                base_income        = f["base_income"],
                tax_multiplier     = f["tax_multiplier"],
                economy_efficiency = f["economy_efficiency"],
                taxed_income       = f["taxed_income"],
                final_income       = f["final_income"],
                days_passed        = days_passed,
                income_added       = income,
                treasury_after     = new_balance,
            )

        return report

    # ==================================================================
    # MONTHLY TICK
    # ==================================================================

    def monthly_tick(
        self,
        server_id:    str,
        scenario_id:  str,
        current_month: int,
    ) -> MonthlyTickReport:
        """
        Run a full monthly tick in the canonical order:
            1. Resource consumption (shared pool) → activates / deactivates.
            2. Production (only ACTIVE buildings; horses/textiles never
               stored; gold/gems → treasury).
            3. Refresh ``daily_base_income`` on each country from the
               freshly-computed monthly building income.
            4. Update the global market.
            5. Recompute economy efficiency for every country.
        """
        # 1. Consumption
        consumption = self._consumption.run_monthly(server_id, scenario_id)

        # 2. Production (treasury credited inline for gold/gems mines)
        production = self._production.run_monthly_production(server_id, scenario_id)

        # 3. Refresh daily_base_income from production results
        for cid, cp in production.by_country.items():
            self._db.update_country_fields(
                server_id, scenario_id, cid,
                daily_base_income=float(cp.daily_income_total),
            )
        # Countries with zero active buildings: zero out
        for crow in self._db.get_all_countries(server_id, scenario_id):
            cid = crow["country_id"]
            if cid not in production.by_country:
                self._db.update_country_fields(
                    server_id, scenario_id, cid, daily_base_income=0.0
                )
            elif production.by_country[cid].buildings_processed == 0:
                self._db.update_country_fields(
                    server_id, scenario_id, cid, daily_base_income=0.0
                )

        # 4. Market
        market = self._market.update_market_monthly(
            server_id, scenario_id, current_month
        )

        # 5. Efficiency
        efficiency = self._efficiency.recompute_all(
            server_id, scenario_id, current_month
        )

        return MonthlyTickReport(
            server_id     = server_id,
            scenario_id   = scenario_id,
            current_month = current_month,
            consumption   = consumption,
            production    = production,
            market        = market,
            efficiency    = efficiency,
        )
