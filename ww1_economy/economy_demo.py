"""
WW1 ECONOMY — END-TO-END DEMO
------------------------------
Exercises the full updated economy spec (all 7 parts):

  1. Bounded economy efficiency multiplier (0.5 – 1.3).
  2. Income formula applies TAXATION before EFFICIENCY.
  3. Building construction deducts gold from the treasury (or rejects).
  4. Monthly shared-pool resource consumption (all-or-nothing per country).
  5. Production fixes — horses & textiles never stored, gold/gems → treasury.
  6. Global market with shortage detection and dynamic prices.
  7. Daily + monthly tick orchestration wires everything together.

Run with:  python3 -m ww1_economy.economy_demo
"""

from __future__ import annotations

import os

from ww1_economy import (
    EconomyDB,
    StorageSystem, TreasurySystem, BuildingSystem,
    ResourceConsumptionSystem, ProductionSystem,
    GlobalMarketSystem, EconomyEfficiencySystem, TickSystem,
    BuildingType, MARKET_BASE_PRICES,
    apply_income_formula, compute_efficiency,
    EFFICIENCY_MIN, EFFICIENCY_MAX,
)


SERVER   = "guild_demo"
SCENARIO = "ww1"
DB_PATH  = "ww1_demo.db"


def banner(title: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n  {title}\n{line}")


def sub(title: str) -> None:
    print(f"\n--- {title} ---")


# ===========================================================================
# 0. FRESH DATABASE
# ===========================================================================
banner("0. DATABASE SETUP — fresh ww1 scenario")

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

db = EconomyDB(DB_PATH)
db.init()
print(f"Database opened: {DB_PATH}")

# Seed two countries.  upsert_country writes only the identity columns —
# economy fields are added by the migration with sensible defaults, then
# tuned via update_country_fields below.
db.upsert_country(SERVER, SCENARIO, "germany", "German Empire",  60_000_000)
db.upsert_country(SERVER, SCENARIO, "france",  "French Republic", 40_000_000)

db.update_country_fields(SERVER, SCENARIO, "germany",
    treasury=1000.0, daily_base_income=0.0, tax_multiplier=1.0,
    economy_efficiency=1.0, population_opinion=70, unrest=5,
)
db.update_country_fields(SERVER, SCENARIO, "france",
    treasury=30.0,   daily_base_income=0.0, tax_multiplier=1.0,
    economy_efficiency=1.0, population_opinion=60, unrest=10,
)

# Provinces (province_id is INT in the schema)
PROVS = {
    "ger_ruhr":     (101, "germany", "Ruhr",     "iron",   100_000),
    "ger_silesia":  (102, "germany", "Silesia",  "coal",    80_000),
    "ger_bavaria":  (103, "germany", "Bavaria",  "horses",  60_000),
    "ger_saxony":   (104, "germany", "Saxony",   "cotton",  70_000),
    "ger_harz":     (105, "germany", "Harz",     "gold",    40_000),
    "ger_hesse":    (106, "germany", "Hesse",    "gems",    30_000),
    "fra_lorraine": (201, "france",  "Lorraine", "iron",    90_000),
}
for slug, (pid, owner, name, res, pop) in PROVS.items():
    db.upsert_province(SERVER, SCENARIO, pid, name, owner, res, pop)
# Map slug → id for use later in the demo
PID = {slug: pid for slug, (pid, *_) in PROVS.items()}

print("Seeded 2 countries (germany, france) and 7 provinces.")

# ===========================================================================
# 1. WIRE EVERY SUBSYSTEM
# ===========================================================================
banner("1. SYSTEM WIRING")

tick = TickSystem.assemble(db)
storage   = tick._storage
treasury  = tick._treasury
buildings = tick._buildings
market    = tick._market
print("All 8 subsystems assembled via TickSystem.assemble().")

# Initialize the global market with base prices
market.initialise_market(SERVER, SCENARIO)
print(f"Global market seeded with {len(MARKET_BASE_PRICES)} resources.")


# ===========================================================================
# 2. BOUNDED EFFICIENCY (PART 1)
# ===========================================================================
banner("2. ECONOMY EFFICIENCY — BOUNDED (0.5 – 1.3)")

scenarios = [
    ("ideal",          dict(opinion=100, unrest=0,  in_active_war=False, war_victory_bonus_active=False)),
    ("typical",        dict(opinion=60,  unrest=20, in_active_war=False, war_victory_bonus_active=False)),
    ("revolt + war",   dict(opinion=10,  unrest=90, in_active_war=True,  war_victory_bonus_active=False)),
    ("post-victory",   dict(opinion=80,  unrest=10, in_active_war=False, war_victory_bonus_active=True)),
]
for label, kw in scenarios:
    res = compute_efficiency(**kw)
    assert EFFICIENCY_MIN <= res.value <= EFFICIENCY_MAX, "BOUND VIOLATION"
    mods_str = ", ".join(f"{n}{v:+.2f}" for n, v in res.modifiers) or "—"
    print(f"  {label:14s} eff={res.value:.3f}  raw={res.raw:.3f}  clamped={res.clamped}  [{mods_str}]")


# ===========================================================================
# 3. TAXATION BEFORE EFFICIENCY (PART 2)
# ===========================================================================
banner("3. INCOME FORMULA — taxation BEFORE efficiency")

f = apply_income_formula(base_income=1000.0, tax_multiplier=1.20, economy_efficiency=0.90)
print(f"  base=1000, tax=1.20, eff=0.90")
print(f"    taxed_income  = base * tax           = {f['taxed_income']:.2f}   (expect 1200)")
print(f"    final_income  = taxed * efficiency   = {f['final_income']:.2f}   (expect 1080)")
assert f["taxed_income"] == 1200.0
assert f["final_income"] == 1080.0
print("  Formula order verified.")


# ===========================================================================
# 4. BUILDING CONSTRUCTION DEDUCTS GOLD (PART 3)
# ===========================================================================
banner("4. CONSTRUCTION COST DEDUCTION")

current_day = 0

# Germany builds an iron mine, can afford it
res = buildings.start_construction(
    SERVER, SCENARIO, PID["ger_ruhr"], "germany",
    BuildingType.MINE, "iron", current_day, treasury=treasury,
)
print(f"  germany builds Mine on Ruhr (iron):")
print(f"    allowed={res['allowed']}  cost={res['cost']:.0f}  treasury_after={res['treasury_after']:.0f}")
assert res["allowed"] and res["paid"]

# France tries to build something it cannot afford (Arms Factory is Tier 2)
res2 = buildings.start_construction(
    SERVER, SCENARIO, PID["fra_lorraine"], "france",
    BuildingType.ARMS_FACTORY, "iron", current_day, treasury=treasury,
)
print(f"  france tries to build Arms Factory (cost {res2['cost']:.0f}):")
print(f"    allowed={res2['allowed']}  reason='{res2['reason']}'")
assert not res2["allowed"]
assert treasury.get(SERVER, SCENARIO, "france") == 30.0  # untouched

# Germany builds the rest of its industrial base
plan = [
    ("ger_silesia", BuildingType.MINE,           "coal"),
    ("ger_bavaria", BuildingType.RANCH,          "horses"),
    ("ger_saxony",  BuildingType.PLANTATION,     "cotton"),
    ("ger_harz",    BuildingType.PRECIOUS_MINE,  "gold"),
    ("ger_hesse",   BuildingType.PRECIOUS_MINE,  "gems"),
]
for prov_slug, btype, prov_res in plan:
    r = buildings.start_construction(
        SERVER, SCENARIO, PID[prov_slug], "germany", btype, prov_res, current_day,
        treasury=treasury,
    )
    flag = "OK" if r["allowed"] else "REJECTED"
    print(f"  germany {btype.value:14s} on {prov_slug:12s}: {flag} cost={r['cost']:>5.0f} treas={r.get('treasury_after', '-')}")

# Tier 2 — Textile Mill (no resource gate)
r = buildings.start_construction(
    SERVER, SCENARIO, PID["ger_saxony"], "germany",
    BuildingType.TEXTILE_MILL, "cotton", current_day, treasury=treasury,
)
print(f"  germany Textile Mill on Saxony: allowed={r['allowed']} treas={r.get('treasury_after', '-')}")


# ===========================================================================
# 5. FAST-FORWARD CONSTRUCTION
# ===========================================================================
banner("5. FAST-FORWARD CONSTRUCTION")

completed = buildings.process_completions(SERVER, SCENARIO, current_day=10_000)
print(f"  Completed {len(completed)} buildings via process_completions(day=10000).")
for ev in completed:
    print(f"    {ev['country_id']:8s} {ev['building_type']:14s} on {ev['province_id']}")


# ===========================================================================
# 6. SHARED-POOL CONSUMPTION (PART 4)
# ===========================================================================
banner("6. MONTHLY CONSUMPTION — shared pool, all-or-nothing")

# Germany has a Textile Mill, which consumes 5 cotton/month.
# Give it cotton first — then deplete and watch deactivation.
storage.add(SERVER, SCENARIO, "germany", "cotton", 4)  # not enough, mill will go INACTIVE

cons = tick._consumption.run_monthly(SERVER, SCENARIO)
print("  Consumption summary:")
for cid, cc in cons.by_country.items():
    state = "ACTIVE" if cc.activated else "INACTIVE (shortfall)"
    print(f"    {cid:8s}: {state}  required={cc.required}  "
          f"deducted={cc.deducted}  shortfalls={cc.shortfalls}")

# Verify the textile mill is now inactive on germany
ger_buildings = db.get_buildings_by_country(SERVER, SCENARIO, "germany")
inactive = [b for b in ger_buildings if not b.get("is_active", 1)]
print(f"  germany inactive buildings: {len(inactive)} (expect ≥1 from cotton shortfall)")


# ===========================================================================
# 7. PRODUCTION — horses/textiles income-only, gold+gems → treasury (PART 5)
# ===========================================================================
banner("7. MONTHLY PRODUCTION")

# Top up cotton so the textile mill comes back online next month
storage.add(SERVER, SCENARIO, "germany", "cotton", 100)

# Re-run consumption so is_active is now true again
tick._consumption.run_monthly(SERVER, SCENARIO)

treas_before = treasury.get(SERVER, SCENARIO, "germany")
prod = tick._production.run_monthly_production(SERVER, SCENARIO)
treas_after  = treasury.get(SERVER, SCENARIO, "germany")

ger = prod.by_country["germany"]
print(f"  germany production:")
print(f"    resources_added (storage) : {ger.resources_added}")
print(f"    income_only (no storage)  : {ger.income_only}   (expect horses & textiles)")
print(f"    gold_to_treasury          : {ger.gold_to_treasury:.0f}  (gold mine 25 + gems mine 30 = 55)")
print(f"    daily_income_total        : {ger.daily_income_total:.2f}")
print(f"    treasury delta            : +{treas_after - treas_before:.0f}")
assert "horses"   in ger.income_only,    "horses must be income-only"
assert "textiles" in ger.income_only,    "textiles must be income-only"
assert "horses"   not in ger.resources_added
assert "textiles" not in ger.resources_added
assert "gold"     not in ger.resources_added
assert "gems"     not in ger.resources_added
assert ger.gold_to_treasury == 55.0


# ===========================================================================
# 8. GLOBAL MARKET — buy with shortage protection (PART 6)
# ===========================================================================
banner("8. GLOBAL MARKET — buy / shortage / dynamic prices")

# Show base prices for a few resources
sub("Initial market state")
for r in ["iron", "coal", "oil", "gunpowder", "rubber"]:
    row = db.get_market_resource(SERVER, SCENARIO, r)
    print(f"  {r:10s} price={row['current_price']:.2f}  base={row['base_price']:.2f}  shortage={bool(row['shortage'])}")

# Top France's treasury up so it can play on the market
treasury.deposit(SERVER, SCENARIO, "france", 1000.0)

# France attempts to buy 50 coal — should succeed, debits treasury, adds storage
sub("France buys 50 coal")
buy = market.buy_resource(SERVER, SCENARIO, "france", "coal", 50)
print(f"  success={buy.success}  spent={buy.total_cost:.2f}  unit={buy.unit_price:.2f}  reason={buy.reason}")
assert buy.success
print(f"  france treasury after: {treasury.get(SERVER, SCENARIO, 'france'):.2f}")
print(f"  france coal storage:   {storage.get_resource(SERVER, SCENARIO, 'france', 'coal')}")

# Drive coal demand high enough to trigger a shortage, then try to buy
# during a confirmed-shortage month.
sub("Stress-test: drive coal demand into shortage")
shortage_month = None
for month in range(1, 12):
    db.increment_market_demand(SERVER, SCENARIO, "coal", 600)
    upd = market.update_market_monthly(SERVER, SCENARIO, current_month=month)
    coal = upd.updates["coal"]
    print(f"  month {month}: coal price={coal.new_price:.2f}  "
          f"rolling={coal.rolling_demand}  shortage={coal.shortage}")
    if coal.shortage and shortage_month is None:
        shortage_month = month
        break

assert shortage_month is not None, "Shortage failed to trigger."

# Try to buy WHILE shortage is in effect — must be REJECTED
sub(f"Attempt to buy coal during the active shortage (month {shortage_month})")
blocked = market.buy_resource(SERVER, SCENARIO, "france", "coal", 5)
print(f"  success={blocked.success}  reason={blocked.reason}")
assert not blocked.success, "Shortage should block purchases."


# ===========================================================================
# 9. ORCHESTRATOR — daily + monthly ticks (PART 7)
# ===========================================================================
banner("9. TICK ORCHESTRATOR — daily + monthly")

sub("Reset war/opinion state for a clean efficiency calc")
db.update_country_fields(SERVER, SCENARIO, "germany",
    population_opinion=70, unrest=10, in_active_war=False, war_victory_end_month=0,
    tax_multiplier=1.10,
)

# Run a monthly tick to refresh daily_base_income & efficiency
sub("Monthly tick (current_month = 9)")
mt = tick.monthly_tick(SERVER, SCENARIO, current_month=9)
ger_eff = mt.efficiency["germany"]
mods_str = ", ".join(f"{n}{v:+.2f}" for n, v in ger_eff.modifiers) or "—"
print(f"  germany efficiency: {ger_eff.value:.3f}  raw={ger_eff.raw:.3f}  [{mods_str}]")
ger_row = db.get_country(SERVER, SCENARIO, "germany")
print(f"  germany daily_base_income now: {ger_row['daily_base_income']:.2f}")

# Now run 30 daily ticks and watch the treasury accrue
sub("30 daily ticks")
treas_start = treasury.get(SERVER, SCENARIO, "germany")
report = tick.daily_tick(SERVER, SCENARIO, current_day=current_day + 60, days_passed=30)
treas_end = treasury.get(SERVER, SCENARIO, "germany")

ger_d = report.countries["germany"]
print(f"  base={ger_d.base_income:.2f}  tax={ger_d.tax_multiplier:.2f}  eff={ger_d.economy_efficiency:.3f}")
print(f"  taxed={ger_d.taxed_income:.2f}  final/day={ger_d.final_income:.2f}")
print(f"  treasury delta over 30 days: +{treas_end - treas_start:.2f}")


# ===========================================================================
# 10. INVARIANT CHECKS
# ===========================================================================
banner("10. GLOBAL INVARIANT CHECKS")

ok = True
for c in db.get_all_countries(SERVER, SCENARIO):
    if c["treasury"] < 0:
        print(f"  FAIL: {c['country_id']} treasury negative: {c['treasury']}")
        ok = False
    snapshot = storage.get_all(SERVER, SCENARIO, c["country_id"])
    for res, amt in snapshot.items():
        if amt < 0:
            print(f"  FAIL: {c['country_id']} {res} negative: {amt}")
            ok = False
    eff = c.get("economy_efficiency", 1.0) or 1.0
    if not (EFFICIENCY_MIN <= eff <= EFFICIENCY_MAX):
        print(f"  FAIL: {c['country_id']} efficiency out of bounds: {eff}")
        ok = False

if ok:
    print("  All invariants hold: treasury ≥ 0, storage ≥ 0, efficiency in [0.5, 1.3].")

print("\nDemo complete.")
