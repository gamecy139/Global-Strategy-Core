"""
WW1 ECONOMY — DEMO / SMOKE TEST
---------------------------------
Exercises all four subsystems:
  1. Database setup
  2. Resource catalogue
  3. Building system (construction, validation, completion tick)
  4. Storage system (add, deduct, batch, queries)
  5. Production system (monthly tick, Precious Mine gold, preview)
  6. Validation rules (Tier 1 restriction, Tier 2 uniqueness, resource mismatch)
  7. Multi-scenario isolation

Run with:  python3 -m ww1_economy.demo
"""

from ww1_economy.db                import EconomyDB
from ww1_economy.resources         import (
    Tier1Resource, Tier2Resource, BuildingType, BUILDING_CONFIGS,
    RESOURCE_TO_TIER1_BUILDING, TIER1_BUILDING_TYPES, TIER2_BUILDING_TYPES,
)
from ww1_economy.storage_system    import StorageSystem
from ww1_economy.building_system   import BuildingSystem
from ww1_economy.production_system import ProductionSystem


def separator(title: str) -> None:
    width = 66
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


SERVER   = "guild_demo"
SCENARIO = "ww1_classic"


# ===========================================================================
# 0. DATABASE SETUP
# ===========================================================================
separator("0. DATABASE SETUP")

db       = EconomyDB(":memory:")
db.init()
storage  = StorageSystem(db)
builder  = BuildingSystem(db)
producer = ProductionSystem(db, storage)

print("EconomyDB initialised (in-memory).")
print("Tables: buildings, country_storage")
print(f"Server: {SERVER!r}  |  Scenario: {SCENARIO!r}")


# ===========================================================================
# 1. RESOURCE CATALOGUE
# ===========================================================================
separator("1. RESOURCE CATALOGUE")

print("Tier 1 resources:", [r.value for r in Tier1Resource])
print("Tier 2 resources:", [r.value for r in Tier2Resource])
print(f"\n{len(TIER1_BUILDING_TYPES)} Tier 1 building types:")
for bt in sorted(TIER1_BUILDING_TYPES, key=lambda b: b.value):
    cfg = BUILDING_CONFIGS[bt]
    print(f"  {bt.value:<20}  cost={cfg.construction_cost_gold:>6.0f}g  "
          f"time={cfg.construction_months:>2}mo  "
          f"income={cfg.daily_income:.1f}/day  "
          f"prod={cfg.monthly_production} {cfg.production_unit}/mo  "
          f"resources={sorted(cfg.allowed_resources)}")

print(f"\n{len(TIER2_BUILDING_TYPES)} Tier 2 building types:")
for bt in sorted(TIER2_BUILDING_TYPES, key=lambda b: b.value):
    cfg = BUILDING_CONFIGS[bt]
    print(f"  {bt.value:<26}  cost={cfg.construction_cost_gold:>6.0f}g  "
          f"time={cfg.construction_months:>2}mo  "
          f"income={cfg.daily_income:.1f}/day  "
          f"prod={cfg.monthly_production} {cfg.production_resource} ({cfg.production_unit})/mo")

print(f"\nResource → required Tier 1 building:")
for res, bt in sorted(RESOURCE_TO_TIER1_BUILDING.items()):
    print(f"  {res:<10} → {bt.value}")


# ===========================================================================
# 2. BUILDING SYSTEM — construction + tick
# ===========================================================================
separator("2. BUILDING SYSTEM — construction and completion tick")

DAY = 0   # Absolute in-game day counter

# --- Province map (province_id → resource, country_id) -------------------
provinces = {
    "ruhr_valley":  ("coal",    "Germany"),
    "rhineland":    ("iron",    "Germany"),
    "alsace":       ("cotton",  "Germany"),
    "paris_basin":  ("grain",   "France"),
    "normandy":     ("oil",     "France"),
    "south_africa": ("gold",    "Britain"),
    "kimberley":    ("gems",    "Britain"),
    "ardennes":     ("wood",    "Belgium"),
}

# Build Tier 1 buildings
print("\nStarting Tier 1 constructions:")
for prov_id, (resource, country) in provinces.items():
    bt = RESOURCE_TO_TIER1_BUILDING[resource]
    result = builder.start_construction(
        SERVER, SCENARIO, prov_id, country, bt, resource, DAY
    )
    cfg = BUILDING_CONFIGS[BuildingType(bt)]
    status = "OK" if result["allowed"] else f"BLOCKED: {result['reason']}"
    print(f"  [{country:<10}] {prov_id:<15} → {bt.value:<20} "
          f"cost={result.get('cost',0):.0f}g  completes day {result.get('completion_day','?')} | {status}")

# Build Tier 2 buildings in mixed provinces
print("\nStarting Tier 2 constructions:")
tier2_builds = [
    ("ruhr_valley",  "Germany", "Textile Mill"),
    ("ruhr_valley",  "Germany", "Arms Factory"),
    ("rhineland",    "Germany", "Chemical Plant"),
    ("paris_basin",  "France",  "Pharmaceutical Plant"),
    ("paris_basin",  "France",  "Powder Mill"),
    ("ardennes",     "Belgium", "Textile Mill"),
]
for prov_id, country, bt_name in tier2_builds:
    resource = provinces[prov_id][0]
    result = builder.start_construction(
        SERVER, SCENARIO, prov_id, country, bt_name, resource, DAY
    )
    status = "OK" if result["allowed"] else f"BLOCKED: {result['reason']}"
    print(f"  [{country:<10}] {prov_id:<15} → {bt_name:<26} "
          f"cost={result.get('cost',0):.0f}g  completes day {result.get('completion_day','?')} | {status}")


# ===========================================================================
# 3. VALIDATION RULES
# ===========================================================================
separator("3. VALIDATION RULES")

# Rule A: only 1 Tier 1 per province
print("Rule A — second Tier 1 in same province:")
res = builder.start_construction(
    SERVER, SCENARIO, "ruhr_valley", "Germany", "Mine", "coal", DAY
)
print(f"  Mine in ruhr_valley (already has Mine): {res['reason']}")

# Rule B: Tier 1 resource mismatch
print("\nRule B — Tier 1 resource mismatch:")
res = builder.start_construction(
    SERVER, SCENARIO, "alsace", "Germany", "Mine", "cotton", DAY
)
print(f"  Mine in alsace (resource=cotton): {res['reason']}")

# Rule C: duplicate Tier 2 in same province
print("\nRule C — duplicate Tier 2 in same province:")
res = builder.start_construction(
    SERVER, SCENARIO, "ruhr_valley", "Germany", "Textile Mill", "coal", DAY
)
print(f"  Second Textile Mill in ruhr_valley: {res['reason']}")

# Rule D: Oil Rig on wrong resource
print("\nRule D — Oil Rig on non-oil province:")
res = builder.start_construction(
    SERVER, SCENARIO, "rhineland", "Germany", "Oil Rig", "iron", DAY
)
print(f"  Oil Rig in rhineland (resource=iron): {res['reason']}")

# can_build() pre-check
ok, reason = builder.can_build(
    SERVER, SCENARIO, "south_africa", "Pharmaceutical Plant", "gold"
)
print(f"\ncan_build Pharma Plant in south_africa (no Tier 2 yet): {ok} — {reason}")


# ===========================================================================
# 4. CONSTRUCTION TICK — complete buildings
# ===========================================================================
separator("4. CONSTRUCTION TICK — complete buildings")

# Advance to day 540 (18 months) — all buildings should be done
COMPLETE_DAY = 540
completed = builder.process_completions(SERVER, SCENARIO, COMPLETE_DAY)
print(f"Buildings completed on day {COMPLETE_DAY}: {len(completed)}")
for ev in completed[:5]:
    print(f"  [{ev['country_id']:<10}] {ev['province_id']:<15} "
          f"→ {ev['building_type']} (resource={ev.get('resource_type','—')})")
if len(completed) > 5:
    print(f"  ... and {len(completed)-5} more")

all_buildings = builder.get_all_buildings(SERVER, SCENARIO)
done  = sum(1 for b in all_buildings if b["is_completed"])
total = len(all_buildings)
print(f"\nTotal buildings: {total}  |  Completed: {done}  |  Under construction: {total-done}")


# ===========================================================================
# 5. STORAGE SYSTEM
# ===========================================================================
separator("5. STORAGE SYSTEM")

# Seed some resources manually
storage.add(SERVER, SCENARIO, "Germany", "iron",      500)
storage.add(SERVER, SCENARIO, "Germany", "coal",      750)
storage.add(SERVER, SCENARIO, "Germany", "ammunition", 200)
storage.add(SERVER, SCENARIO, "France",  "grain",     300)
storage.add(SERVER, SCENARIO, "France",  "oil",       120)

print("Germany storage (selected):")
for res in ("iron", "coal", "ammunition", "textiles"):
    print(f"  {res}: {storage.get_resource(SERVER, SCENARIO, 'Germany', res)}")

# Batch add
batch_result = storage.add_batch(
    SERVER, SCENARIO, "Britain",
    {"gems": 10, "textiles": 50, "medicines": 100}
)
print(f"\nBritain batch add: {batch_result}")

# Deduct
new_val = storage.deduct(SERVER, SCENARIO, "Germany", "iron", 100)
print(f"\nGermany iron after deduct 100: {new_val}")

# has_enough checks
print(f"Germany has 200 coal?   {storage.has_enough(SERVER, SCENARIO, 'Germany', 'coal', 200)}")
print(f"Germany has 5000 coal?  {storage.has_enough(SERVER, SCENARIO, 'Germany', 'coal', 5000)}")

# batch check
reqs = {"ammunition": 50, "gunpowder": 1000}
check = storage.has_enough_batch(SERVER, SCENARIO, "Germany", reqs)
print(f"Germany batch requirements {reqs}: {check}")

# Deduct with allow_partial
result = storage.deduct(SERVER, SCENARIO, "France", "oil", 999, allow_partial=True)
print(f"\nFrance oil partial deduct (999 from 120): {result}")

# Invalid resource
try:
    storage.add(SERVER, SCENARIO, "Germany", "gold", 100)
except ValueError as e:
    print(f"Gold in storage (expected error): {e}")


# ===========================================================================
# 6. PRODUCTION SYSTEM — monthly tick
# ===========================================================================
separator("6. PRODUCTION SYSTEM — monthly tick")

print("Previews BEFORE production:")
for cid in ("Germany", "France", "Britain"):
    prev = producer.get_monthly_production_preview(SERVER, SCENARIO, cid)
    print(f"  {cid}: resources={prev['monthly_resources']}, "
          f"gold_treasury={prev['gold_to_treasury']}, "
          f"daily_income={prev['daily_income_total']}")

print("\nRunning monthly production tick...")
report = producer.run_monthly_production(SERVER, SCENARIO)

print(f"\nProduction report summary:")
summary = report.summary()
for cid, data in summary["countries"].items():
    print(f"\n  [{cid}]")
    print(f"    resources_added:    {data['resources_added']}")
    print(f"    gold_to_treasury:   {data['gold_to_treasury']}")
    print(f"    daily_income_total: {data['daily_income_total']}")
    print(f"    buildings done:     {data['buildings_processed']}")

if summary["skipped"]:
    print(f"\nSkipped: {summary['skipped']}")

print("\nGermany storage AFTER 1 production tick:")
snap = storage.get_all(SERVER, SCENARIO, "Germany")
for res, amt in snap.items():
    if amt > 0:
        print(f"  {res}: {amt}")

# Precious Mine gold note
print("\nBritain gold from Precious Mine (goes to treasury, NOT storage):")
brit_gold = summary["countries"]["Britain"]["gold_to_treasury"]
print(f"  +{brit_gold} gold this month → caller deposits to treasury")
brit_gems = storage.get_resource(SERVER, SCENARIO, "Britain", "gems")
print(f"  Britain gems in storage (from Kimberley Precious Mine): {brit_gems}")

# Run a second tick and verify accumulation
report2 = producer.run_monthly_production(SERVER, SCENARIO)
print(f"\nAfter 2nd tick — Germany iron: "
      f"{storage.get_resource(SERVER, SCENARIO, 'Germany', 'iron')}")
print(f"After 2nd tick — France grain: "
      f"{storage.get_resource(SERVER, SCENARIO, 'France', 'grain')}")


# ===========================================================================
# 7. MULTI-SCENARIO ISOLATION
# ===========================================================================
separator("7. MULTI-SCENARIO ISOLATION")

SCENARIO_B = "ww1_variant"
builder.start_construction(
    SERVER, SCENARIO_B, "ruhr_valley", "Prussia", "Mine", "coal", 0
)
builder.process_completions(SERVER, SCENARIO_B, 90)

storage.add(SERVER, SCENARIO_B, "Prussia", "coal", 9999)

print(f"Scenario '{SCENARIO}'  Germany iron: "
      f"{storage.get_resource(SERVER, SCENARIO,   'Germany', 'iron')}")
print(f"Scenario '{SCENARIO_B}' Prussia coal: "
      f"{storage.get_resource(SERVER, SCENARIO_B, 'Prussia', 'coal')}")

buildings_a = builder.get_all_buildings(SERVER, SCENARIO)
buildings_b = builder.get_all_buildings(SERVER, SCENARIO_B)
print(f"\nBuildings in '{SCENARIO}':   {len(buildings_a)}")
print(f"Buildings in '{SCENARIO_B}': {len(buildings_b)}")
print("→ Scenarios are fully isolated")


# ===========================================================================
# 8. BUILDING INCOME HELPER
# ===========================================================================
separator("8. DAILY INCOME FROM BUILDINGS")

for cid in ("Germany", "France", "Britain"):
    income = producer.get_country_income_from_buildings(SERVER, SCENARIO, cid)
    print(f"  {cid} total daily building income: {income:.2f} gold/day")


separator("WW1 ECONOMY DEMO COMPLETE")
