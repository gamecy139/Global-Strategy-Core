"""
DEMO / SMOKE TEST — Build 3
----------------------------
Exercises all twelve game systems:
  1.  Database Setup
  2.  Time System
  3.  Religion System
  4.  Diplomacy System (with religion modifier)
  5.  Economy System
  6.  Population System (base + bonus growth, investments)
  7.  Taxation System
  8.  Opinion System
  9.  Province System (registration, conversions)
  10. Unrest System (monthly update, persecution, thresholds)
  11. Military System (create, merge, split, move, process movements)
  12. Recruitment System (dynamic %, mass penalty)
  13. Integrated monthly tick loop

Run with:  python3 -m game_backend.demo
"""

from game_backend.time_system        import TimeSystem, TimeSpeed
from game_backend.diplomacy_system   import DiplomacySystem, Country
from game_backend.war_system         import WarSystem, Province as WarProvince, TreatyType
from game_backend.db                 import Database
from game_backend.religion_system    import Religion, ReligionSystem
from game_backend.economy_system     import EconomySystem
from game_backend.population_system  import PopulationSystem
from game_backend.taxation_system    import TaxationSystem, TaxLevel
from game_backend.opinion_system     import OpinionSystem
from game_backend.province_system    import ProvinceSystem
from game_backend.unrest_system      import UnrestSystem
from game_backend.military_system    import MilitarySystem, RecruitmentSystem


def separator(title: str) -> None:
    width = 66
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


SERVER = "guild_demo"   # Simulated Discord server ID


# ===========================================================================
# 0. DATABASE SETUP
# ===========================================================================
separator("0. DATABASE SETUP")

db = Database(":memory:")
db.init()
print("SQLite in-memory database initialised.")
print("Tables: country_state, army_units, recruitment_tracking, province_state")

rel_sys    = ReligionSystem(db)
eco_sys    = EconomySystem(db)
pop_sys    = PopulationSystem(db)
tax_sys    = TaxationSystem(db)
opin_sys   = OpinionSystem(db)
prov_sys   = ProvinceSystem(db)
unrest_sys = UnrestSystem(db)
mil_sys    = MilitarySystem(db)
rec_sys    = RecruitmentSystem(db, mil_sys)


# ===========================================================================
# 1. TIME SYSTEM
# ===========================================================================
separator("1. TIME SYSTEM")

ts = TimeSystem()
print(f"Start:              {ts.date_string()}")

for speed in [TimeSpeed.X1, TimeSpeed.X2, TimeSpeed.X3, TimeSpeed.X4, TimeSpeed.X5]:
    ts.set_speed(speed)
    days = ts.tick()
    print(f"Speed {speed.value}x tick  →  +{days:2d} days  |  {ts.date_string()}")

ts.pause()
paused = ts.tick()
print(f"Paused tick        →  +{paused} days   |  {ts.date_string()}")
ts.unpause()

ts.advance_days(300)
print(f"After +300 days    →  {ts.date_string()}")
print(f"Total days elapsed: {ts.total_days_elapsed()}")


# ===========================================================================
# 2. RELIGION SYSTEM
# ===========================================================================
separator("2. RELIGION SYSTEM")

print("Valid religions:", Religion.values())
try:
    Religion.parse("Paganism")
except ValueError as e:
    print(f"Validation (expected error): {e}")

rel_sys.set_religion(SERVER, "Evoria",  "Islam")
rel_sys.set_religion(SERVER, "Drakmar", "Christianity")
rel_sys.set_religion(SERVER, "Veldris", "Islam")

print(f"Evoria  → {rel_sys.get_religion(SERVER, 'Evoria')}")
print(f"Drakmar → {rel_sys.get_religion(SERVER, 'Drakmar')}")
print(f"Countries following Islam: {rel_sys.list_by_religion(SERVER, 'Islam')}")


# ===========================================================================
# 3. DIPLOMACY SYSTEM (religion modifier)
# ===========================================================================
separator("3. DIPLOMACY SYSTEM (religion modifier)")

ds = DiplomacySystem()
evoria  = Country("Evoria",  religion="Islam")
drakmar = Country("Drakmar", religion="Christianity")
veldris = Country("Veldris", religion="Islam")
ds.register_country(evoria)
ds.register_country(drakmar)
ds.register_country(veldris)

print(f"Evoria ↔ Drakmar base={ds.get_relation('Evoria','Drakmar')}, "
      f"effective={ds.get_effective_relation('Evoria','Drakmar')} (−2 religion modifier)")
print(f"Evoria ↔ Veldris effective={ds.get_effective_relation('Evoria','Veldris')} "
      f"(same religion, no modifier)")

ds.improve_relations("Evoria", "Drakmar", amount=2)
print(f"\nAfter base +2 → effective Evoria↔Drakmar: "
      f"{ds.get_effective_relation('Evoria','Drakmar')}")


# ===========================================================================
# 4. ECONOMY SYSTEM
# ===========================================================================
separator("4. ECONOMY SYSTEM")

eco_sys.ensure_country(SERVER, "Evoria",  treasury=10_000.0, daily_income=100.0)
eco_sys.ensure_country(SERVER, "Drakmar", treasury=8_000.0,  daily_income=80.0)
eco_sys.ensure_country(SERVER, "Veldris", treasury=5_000.0,  daily_income=60.0)

eco_sys.add_income(SERVER, "Evoria", 50)
print(f"Evoria income after +50: {eco_sys.get_daily_income(SERVER, 'Evoria'):.1f}/day")

new_t = eco_sys.update_treasury(SERVER, "Evoria", days_passed=3)
print(f"Evoria treasury after 3 days (150/day): {new_t:.1f}")

result = eco_sys.transfer(SERVER, payer="Drakmar", receiver="Evoria", amount=1_000)
print(f"Transfer 1000g Drakmar→Evoria: {result}")


# ===========================================================================
# 5. POPULATION SYSTEM — base + bonus growth + investments
# ===========================================================================
separator("5. POPULATION SYSTEM (base + bonus growth + investments)")

pop_sys.initialize_country(SERVER, "Evoria",  base_population=5_000_000, base_growth_rate=0.02)
pop_sys.initialize_country(SERVER, "Drakmar", base_population=4_000_000, base_growth_rate=0.015)
pop_sys.initialize_country(SERVER, "Veldris", base_population=2_000_000, base_growth_rate=0.03)

print(f"Evoria snapshot: {pop_sys.get_snapshot(SERVER, 'Evoria')}")

# Standard growth
new_pop = pop_sys.update_population(SERVER, "Evoria", months_passed=1)
print(f"\nEvoria after 1 month (2% base): {new_pop:,}")

# Investment — first investment
DAY_0 = 0
result = pop_sys.invest_in_growth(SERVER, "Evoria", current_day=DAY_0)
print(f"\nInvestment 1: {result}")

result = pop_sys.invest_in_growth(SERVER, "Evoria", current_day=DAY_0 + 1)
print(f"Immediate re-invest (expect blocked): {result}")

result = pop_sys.invest_in_growth(SERVER, "Evoria", current_day=DAY_0 + 91)
print(f"After cooldown (day 91): {result}")

# Now growth uses base + bonus
snap = pop_sys.get_snapshot(SERVER, "Evoria")
print(f"\nEvoria post-investment snapshot: {snap}")
new_pop = pop_sys.update_population(SERVER, "Evoria", months_passed=1)
print(f"Evoria after 1 month (total={snap['total_growth_rate']*100:.1f}% rate): {new_pop:,}")

# Max investment cap
for i in range(10):
    r = pop_sys.invest_in_growth(SERVER, "Evoria", current_day=DAY_0 + 91 * (i + 2))
    if not r["allowed"]:
        print(f"Investment capped after iteration {i}: {r['reason']}")
        break


# ===========================================================================
# 6. TAXATION SYSTEM
# ===========================================================================
separator("6. TAXATION SYSTEM")

print("All tax levels:")
for lvl in TaxLevel:
    cfg = lvl.config
    print(f"  {cfg.name:<26} income ×{cfg.income_multiplier:.2f}  "
          f"opinion {cfg.opinion_modifier:+d}/month")

tax_sys.set_tax_level(SERVER, "Evoria",  "Standard Contribution")
tax_sys.set_tax_level(SERVER, "Drakmar", "War Levy")
tax_sys.set_tax_level(SERVER, "Veldris", "Light Contribution")

for cid in ["Evoria", "Drakmar", "Veldris"]:
    snap = tax_sys.get_snapshot(SERVER, cid)
    print(f"\n{cid}: {snap}")

# Income calculation
raw_income = 100.0
eff = tax_sys.calculate_effective_income(SERVER, "Drakmar", raw_income)
print(f"\nDrakmar War Levy effective income (base=100): {eff:.1f}")

# Invalid level
try:
    tax_sys.set_tax_level(SERVER, "Evoria", "Maximum Extraction")
except ValueError as e:
    print(f"Invalid level (expected error): {e}")


# ===========================================================================
# 7. OPINION SYSTEM
# ===========================================================================
separator("7. OPINION SYSTEM")

opin_sys.set_opinion(SERVER, "Evoria",  70)
opin_sys.set_opinion(SERVER, "Drakmar", 25)
opin_sys.set_opinion(SERVER, "Veldris", 85)

for cid in ["Evoria", "Drakmar", "Veldris"]:
    snap = opin_sys.get_snapshot(SERVER, cid)
    print(f"{cid}: {snap}")

# War penalty
new_op = opin_sys.apply_war_penalty(SERVER, "Evoria")
print(f"\nEvoria after war penalty (-15): {new_op}")

# Monthly update (applies tax modifier)
update = opin_sys.update_monthly(SERVER, "Evoria", tax_sys)
print(f"Evoria monthly opinion update: {update}")

# Effects
print(f"\nDrakmar (opinion=25) recruitment cost modifier: "
      f"{opin_sys.get_recruitment_cost_modifier(SERVER, 'Drakmar'):.2f}")
print(f"Veldris (opinion=85) recruitment cost modifier: "
      f"{opin_sys.get_recruitment_cost_modifier(SERVER, 'Veldris'):.2f}")
print(f"Drakmar contributes to unrest? {opin_sys.contributes_to_unrest(SERVER, 'Drakmar')}")


# ===========================================================================
# 8. PROVINCE SYSTEM
# ===========================================================================
separator("8. PROVINCE SYSTEM")

prov_sys.register_province(SERVER, "evoria_capital",  "Evoria",  is_core=True,  religion="Islam")
prov_sys.register_province(SERVER, "border_plains",   "Evoria",  is_core=False, religion="Christianity")
prov_sys.register_province(SERVER, "drakmar_citadel", "Drakmar", is_core=True,  religion="Christianity")
prov_sys.register_province(SERVER, "river_march",     "Evoria",  is_core=False, religion="Islam")

print(f"Evoria provinces: {[p['province_id'] for p in prov_sys.get_provinces_by_country(SERVER,'Evoria')]}")
print(f"Non-core: {[p['province_id'] for p in prov_sys.get_non_core_provinces(SERVER,'Evoria')]}")
print(f"Religion mismatches (Evoria, Islam): "
      f"{[p['province_id'] for p in prov_sys.get_religion_mismatch_provinces(SERVER,'Evoria','Islam')]}")

# Core conversion (4 months = 120 days)
current_day = 100
conv = prov_sys.start_core_conversion(SERVER, "border_plains", "Evoria", current_day)
print(f"\nCore conversion started: {conv}")

completed = prov_sys.process_conversions(SERVER, current_day=current_day + 50)
print(f"After 50 days (incomplete): {completed}")

completed = prov_sys.process_conversions(SERVER, current_day=current_day + 120)
print(f"After 120 days (complete): {completed}")
print(f"border_plains is_core? {prov_sys.get_province(SERVER,'border_plains')['is_core']}")

# Religion conversion (6 months = 180 days)
conv2 = prov_sys.start_religion_conversion(SERVER, "border_plains", "Islam", current_day + 120)
print(f"\nReligion conversion started: {conv2}")
completed2 = prov_sys.process_conversions(SERVER, current_day=current_day + 120 + 180)
print(f"After 180 days (complete): {completed2}")


# ===========================================================================
# 9. UNREST SYSTEM
# ===========================================================================
separator("9. UNREST SYSTEM")

unrest_sys.set_unrest(SERVER, "Evoria", 20.0)

# Persecution instant effect
result = unrest_sys.activate_persecution(SERVER, "Evoria")
print(f"Persecution activated: {result}")
print(f"Persecution active? {unrest_sys.is_persecution_active(SERVER, 'Evoria')}")

# Monthly update
print(f"\nNon-core provinces before monthly: "
      f"{[p['province_id'] for p in prov_sys.get_non_core_provinces(SERVER,'Evoria')]}")
print(f"Religion mismatches: "
      f"{[p['province_id'] for p in prov_sys.get_religion_mismatch_provinces(SERVER,'Evoria','Islam')]}")

# opinion is currently low for Drakmar, so let's do unrest update for Drakmar
unrest_sys.set_unrest(SERVER, "Drakmar", 45.0)
opin_sys.set_opinion(SERVER, "Drakmar", 25)  # low opinion

monthly = unrest_sys.update_monthly(
    server_id        = SERVER,
    country_id       = "Drakmar",
    current_day      = 200,
    province_system  = prov_sys,
    opinion_system   = opin_sys,
    country_religion = "Christianity",
)
print(f"\nDrakmar monthly unrest update: {monthly}")

# Trigger riot threshold
unrest_sys.set_unrest(SERVER, "Veldris", 55.0)
monthly_v = unrest_sys.update_monthly(
    SERVER, "Veldris", 200, prov_sys, opin_sys, "Islam"
)
print(f"\nVeldris monthly unrest (≥50 threshold): events={monthly_v['events']}")

# Riot consequence
if any(e["type"] == "riot" for e in monthly_v["events"]):
    new_p = unrest_sys.apply_riot_consequences(SERVER, "Veldris", pop_sys)
    print(f"Riot! Veldris population reduced to: {new_p:,}")

# Deactivate persecution
unrest_sys.deactivate_persecution(SERVER, "Evoria")
print(f"Evoria persecution deactivated: {unrest_sys.is_persecution_active(SERVER,'Evoria')}")


# ===========================================================================
# 10. MILITARY SYSTEM
# ===========================================================================
separator("10. MILITARY SYSTEM")

# Create units
u1 = mil_sys.create_unit(SERVER, "Evoria", "infantry", 5_000, "evoria_capital")
u2 = mil_sys.create_unit(SERVER, "Evoria", "infantry", 3_000, "evoria_capital")
u3 = mil_sys.create_unit(SERVER, "Evoria", "cavalry",  1_000, "evoria_capital")
u4 = mil_sys.create_unit(SERVER, "Drakmar", "ranged",  2_000, "drakmar_citadel")

print(f"Evoria units: {[u['unit_id'][:8] for u in mil_sys.get_country_units(SERVER,'Evoria')]}")
print(f"Evoria total army: {mil_sys.get_total_army_size(SERVER,'Evoria'):,}")

# Merge two infantry units
merged_id = mil_sys.merge_units(SERVER, u1, u2)
print(f"\nMerged infantry → size: {mil_sys.get_unit(SERVER, merged_id)['size']:,}")

# Split the merged unit
orig_id, new_id = mil_sys.split_unit(SERVER, merged_id, 4_000)
print(f"Split: original={mil_sys.get_unit(SERVER,orig_id)['size']:,}, "
      f"new={mil_sys.get_unit(SERVER,new_id)['size']:,}")

# Move a unit
DAY_NOW = 300
ARRIVAL_DAY = DAY_NOW + 10
mil_sys.move_unit(SERVER, new_id, "border_plains", ARRIVAL_DAY)
print(f"\nUnit {new_id[:8]} dispatched to border_plains (arrives day {ARRIVAL_DAY})")

# Process movements — before arrival
arrived_early = mil_sys.process_movements(SERVER, current_day=DAY_NOW + 5)
print(f"Day {DAY_NOW+5}: arrivals = {arrived_early}")

# Process movements — after arrival
arrived = mil_sys.process_movements(SERVER, current_day=ARRIVAL_DAY)
print(f"Day {ARRIVAL_DAY}: arrivals = [{{'unit': {arrived[0]['unit_id'][:8] if arrived else '?'}, "
      f"'at': {arrived[0]['arrived_at'] if arrived else '?'}}}]")

# Disband
disbanded_size = mil_sys.disband_unit(SERVER, u3)
print(f"\nDisbanded cavalry unit (size={disbanded_size:,}). "
      f"Evoria total army: {mil_sys.get_total_army_size(SERVER,'Evoria'):,}")


# ===========================================================================
# 11. RECRUITMENT SYSTEM
# ===========================================================================
separator("11. RECRUITMENT SYSTEM")

# Set up a fresh country for clean recruitment demo
pop_sys.initialize_country(SERVER, "Veldris", base_population=2_000_000, base_growth_rate=0.01)
eco_sys.ensure_country(SERVER, "Veldris", treasury=50_000.0, daily_income=60.0)

allowed_pct = rec_sys.get_allowed_percentage(SERVER, "Veldris", at_war=False)
max_rec     = rec_sys.calculate_max_recruitable(SERVER, "Veldris")
print(f"Veldris allowed recruitment: {allowed_pct*100:.1f}%  ({max_rec:,} soldiers)")

war_pct  = rec_sys.get_allowed_percentage(SERVER, "Veldris", at_war=True)
war_max  = rec_sys.calculate_max_recruitable(SERVER, "Veldris", at_war=True)
print(f"During war: {war_pct*100:.1f}%  ({war_max:,} soldiers)")

# First recruitment
cost = rec_sys.get_recruitment_cost(SERVER, "Veldris", 100_000,
                                    base_cost_per_unit=1.0, current_day=0)
print(f"\nCost to recruit 100,000 (no penalty): {cost:,.1f} gold")

r1 = rec_sys.recruit(
    SERVER, "Veldris", 100_000, "infantry", "veldris_coast",
    current_day=0, base_cost_per_unit=1.0, opinion_system=opin_sys
)
print(f"Recruitment 1: allowed={r1['allowed']}, unit={r1.get('unit_id','')[:8]}, "
      f"cost={r1.get('cost',0):,.1f}, pop_after={r1.get('new_population',0):,}, "
      f"penalty_triggered={r1.get('penalty_triggered')}")

# Second recruitment quickly — triggers mass penalty (>30% base_pop across 2 recruitments)
r2 = rec_sys.recruit(
    SERVER, "Veldris", 500_000, "infantry", "veldris_coast",
    current_day=30, base_cost_per_unit=1.0, opinion_system=opin_sys
)
print(f"Recruitment 2: allowed={r2['allowed']}, "
      f"penalty_triggered={r2.get('penalty_triggered')}, "
      f"reason={r2.get('reason','')}")

# Cost with penalty active
penalised_cost = rec_sys.get_recruitment_cost(
    SERVER, "Veldris", 10_000, base_cost_per_unit=1.0, current_day=60
)
print(f"Cost with mass penalty ×3 (10,000 recruits): {penalised_cost:,.1f}")

# Tracking
tracking = rec_sys.get_tracking(SERVER, "Veldris")
print(f"Tracking: penalty_active={bool(tracking['penalty_active'])}, "
      f"penalty_end_day={tracking['penalty_end_time']}")


# ===========================================================================
# 12. INTEGRATED MONTHLY TICK LOOP
# ===========================================================================
separator("12. INTEGRATED MONTHLY TICK LOOP (3 months)")

ts_loop = TimeSystem()
ts_loop.set_speed(TimeSpeed.X1)   # 7 days per tick

# Use Evoria as the country — reset to clean state
eco_sys.ensure_country(SERVER, "Evoria", treasury=20_000.0, daily_income=200.0)
pop_sys.initialize_country(SERVER, "Evoria", base_population=5_000_000, base_growth_rate=0.02)
opin_sys.set_opinion(SERVER, "Evoria", 60)
unrest_sys.set_unrest(SERVER, "Evoria", 10.0)
tax_sys.set_tax_level(SERVER, "Evoria", "Standard Contribution")

# Make sure Evoria has the province registered already (border_plains is core now)
prov_sys.register_province(SERVER, "evoria_capital", "Evoria", is_core=True, religion="Islam")
prov_sys.register_province(SERVER, "foreign_hold",   "Evoria", is_core=False, religion="Christianity")

accumulated_days = 0
for tick_n in range(1, 13):   # 12 ticks × 7 days ≈ 3 in-game months
    days = ts_loop.tick()
    accumulated_days += days

    new_t = eco_sys.update_treasury(SERVER, "Evoria", days)
    new_p, months = pop_sys.update_population_from_days(SERVER, "Evoria", days)
    opinion_update = opin_sys.update_monthly(SERVER, "Evoria", tax_sys) if months > 0 else None
    unrest_update  = (
        unrest_sys.update_monthly(
            SERVER, "Evoria", accumulated_days, prov_sys, opin_sys, "Islam"
        ) if months > 0 else None
    )

    conv_completed = prov_sys.process_conversions(SERVER, accumulated_days)

    print(
        f"Tick {tick_n:2d} | Day {accumulated_days:4d} | "
        f"treasury={new_t:,.0f} | pop={new_p:,} | "
        f"opinion={opin_sys.get_opinion(SERVER,'Evoria'):3d} | "
        f"unrest={unrest_sys.get_unrest(SERVER,'Evoria'):5.1f}"
        + (f" | conv={conv_completed}" if conv_completed else "")
    )


# ===========================================================================
# 13. SERVER ISOLATION CHECK
# ===========================================================================
separator("13. SERVER ISOLATION")

other = "guild_other"
rel_sys.set_religion(other, "Evoria", "Hinduism")
tax_sys.set_tax_level(other, "Evoria", "War Levy")
print(f"guild_demo  Evoria religion: {rel_sys.get_religion(SERVER, 'Evoria')}")
print(f"guild_other Evoria religion: {rel_sys.get_religion(other,  'Evoria')}")
print(f"guild_demo  Evoria tax:      {tax_sys.get_tax_label(SERVER, 'Evoria')}")
print(f"guild_other Evoria tax:      {tax_sys.get_tax_label(other,  'Evoria')}")
print("→ All data is fully isolated between servers")


separator("ALL SYSTEMS DEMO COMPLETE")
