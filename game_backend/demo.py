"""
DEMO / SMOKE TEST
-----------------
Exercises all six game systems:
  1. Time System
  2. Diplomacy System (including religion modifier)
  3. War System
  4. Database Layer
  5. Religion System
  6. Economy System
  7. Population System
  8. Integrated tick loop

Run with:  python3 -m game_backend.demo
"""

from game_backend.time_system       import TimeSystem, TimeSpeed
from game_backend.diplomacy_system  import DiplomacySystem, Country
from game_backend.war_system        import WarSystem, Province, TreatyType
from game_backend.db                import Database
from game_backend.religion_system   import Religion, ReligionSystem
from game_backend.economy_system    import EconomySystem
from game_backend.population_system import PopulationSystem


def separator(title: str) -> None:
    width = 62
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


SERVER = "guild_demo"   # Simulated Discord server ID


# ===========================================================================
# 0. DATABASE SETUP (shared across all DB-backed systems)
# ===========================================================================
separator("DATABASE SETUP")

db = Database(":memory:")   # In-memory — no file left behind after the demo
db.init()
print("SQLite database initialised (in-memory, per-server isolation by server_id)")

# Instantiate all DB-backed systems against the same database
rel_sys = ReligionSystem(db)
eco_sys = EconomySystem(db)
pop_sys = PopulationSystem(db)


# ===========================================================================
# 1. TIME SYSTEM
# ===========================================================================
separator("TIME SYSTEM")

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
separator("RELIGION SYSTEM")

print("Valid religions:", Religion.values())

# Validate
try:
    Religion.parse("Paganism")
except ValueError as e:
    print(f"Validation (expected error): {e}")

print(f"Religion.parse('Islam') == 'Islam': {Religion.parse('Islam') == 'Islam'}")

# DB operations (creates rows with defaults if absent)
rel_sys.set_religion(SERVER, "Evoria",  "Islam")
rel_sys.set_religion(SERVER, "Drakmar", "Christianity")
rel_sys.set_religion(SERVER, "Veldris", "Islam")

print(f"Evoria  religion: {rel_sys.get_religion(SERVER, 'Evoria')}")
print(f"Drakmar religion: {rel_sys.get_religion(SERVER, 'Drakmar')}")
print(f"Veldris religion: {rel_sys.get_religion(SERVER, 'Veldris')}")

# List by religion
islamic = rel_sys.list_by_religion(SERVER, "Islam")
print(f"Countries following Islam: {islamic}")


# ===========================================================================
# 3. DIPLOMACY SYSTEM — with religion modifier
# ===========================================================================
separator("DIPLOMACY SYSTEM (religion modifier)")

ds = DiplomacySystem()

evoria  = Country("Evoria",  religion="Islam")
drakmar = Country("Drakmar", religion="Christianity")   # different from Evoria
veldris = Country("Veldris", religion="Islam")          # same as Evoria

ds.register_country(evoria)
ds.register_country(drakmar)
ds.register_country(veldris)

# Base relations start at 0
print(f"\nBase relation  Evoria ↔ Drakmar: {ds.get_relation('Evoria', 'Drakmar')}")
print(f"Effective      Evoria ↔ Drakmar: {ds.get_effective_relation('Evoria', 'Drakmar')}"
      f"  (religion modifier applied)")
print(f"Modifiers: {ds.compute_modifiers('Evoria', 'Drakmar')}")

# Same-religion pair — no modifier
print(f"\nBase relation  Evoria ↔ Veldris: {ds.get_relation('Evoria', 'Veldris')}")
print(f"Effective      Evoria ↔ Veldris: {ds.get_effective_relation('Evoria', 'Veldris')}"
      f"  (same religion — no modifier)")

# Can declare war check using effective relation
print(f"\nEvoria can declare war on Drakmar? {ds.can_declare_war('Evoria', 'Drakmar')}"
      f"  (effective = {ds.get_effective_relation('Evoria', 'Drakmar')})")

# Improve base relation enough to overcome the modifier
ds.improve_relations("Evoria", "Drakmar", amount=2)
print(f"\nAfter base +2 — effective Evoria ↔ Drakmar: "
      f"{ds.get_effective_relation('Evoria', 'Drakmar')}  "
      f"(base={ds.get_relation('Evoria','Drakmar')}, modifier=-2)")

# Test update_country_religion sync
ds.update_country_religion("Drakmar", "Islam")   # Now same religion
print(f"\nAfter converting Drakmar to Islam:")
print(f"  Modifiers Evoria ↔ Drakmar: {ds.compute_modifiers('Evoria', 'Drakmar')}")
print(f"  Effective: {ds.get_effective_relation('Evoria', 'Drakmar')}")

# ReligionSystem.set_religion with diplomacy sync
rel_sys.set_religion(SERVER, "Drakmar", "Christianity", diplomacy=ds)
print(f"\nReverted Drakmar → Christianity via ReligionSystem (with diplomacy sync)")
print(f"  In-memory religion: {ds.get_country('Drakmar').religion}")
print(f"  Effective:          {ds.get_effective_relation('Evoria', 'Drakmar')}")

# all_relations() now shows base + effective
print("\nAll relations (base / effective / modifiers):")
for row in ds.all_relations():
    print(f"  {row['country_a']} ↔ {row['country_b']}: "
          f"base={row['base_value']}, effective={row['effective_value']}, "
          f"tier={row['tier']}, modifiers={[m['reason'] for m in row['modifiers']]}")


# ===========================================================================
# 4. ECONOMY SYSTEM
# ===========================================================================
separator("ECONOMY SYSTEM")

eco_sys.ensure_country(SERVER, "Evoria",  treasury=10_000.0, daily_income=100.0)
eco_sys.ensure_country(SERVER, "Drakmar", treasury=8_000.0,  daily_income=80.0)
eco_sys.ensure_country(SERVER, "Veldris", treasury=5_000.0,  daily_income=60.0)

print(f"Initial Evoria  treasury: {eco_sys.get_treasury(SERVER, 'Evoria'):.1f}")
print(f"Initial Drakmar treasury: {eco_sys.get_treasury(SERVER, 'Drakmar'):.1f}")

# Income modification
eco_sys.add_income(SERVER, "Evoria", 50)
eco_sys.reduce_income(SERVER, "Drakmar", 20)
print(f"\nEvoria  daily income after +50: {eco_sys.get_daily_income(SERVER, 'Evoria'):.1f}")
print(f"Drakmar daily income after -20: {eco_sys.get_daily_income(SERVER, 'Drakmar'):.1f}")

# Treasury update (simulating 3 in-game days passing)
new_treasury = eco_sys.update_treasury(SERVER, "Evoria", days_passed=3)
print(f"\nEvoria treasury after 3 days (income=150/day): {new_treasury:.1f}")

# One-off deposit / withdraw
eco_sys.deposit(SERVER, "Veldris", 2_000)
eco_sys.withdraw(SERVER, "Veldris", 500)
print(f"Veldris treasury after +2000 / -500: "
      f"{eco_sys.get_treasury(SERVER, 'Veldris'):.1f}")

# Gold transfer (reparations simulation)
result = eco_sys.transfer(SERVER, payer="Drakmar", receiver="Evoria", amount=1_000)
print(f"\nReparation transfer (1000 gold): {result}")

# Bulk update — all countries get 10-day income
print("\nBulk update (10 days income for all countries):")
bulk = eco_sys.update_all_treasuries(SERVER, days_passed=10)
for cid, new_t in bulk.items():
    print(f"  {cid}: {new_t:.1f}")

# Snapshot
snap = eco_sys.get_snapshot(SERVER, "Evoria")
print(f"\nEvoria economy snapshot: {snap}")


# ===========================================================================
# 5. POPULATION SYSTEM
# ===========================================================================
separator("POPULATION SYSTEM")

pop_sys.ensure_country(SERVER, "Evoria",  population=5_000_000, growth_rate=0.02)
pop_sys.ensure_country(SERVER, "Drakmar", population=4_000_000, growth_rate=0.015)
pop_sys.ensure_country(SERVER, "Veldris", population=2_000_000, growth_rate=0.03)

print(f"Initial Evoria  population: {pop_sys.get_population(SERVER, 'Evoria'):,}")
print(f"Initial Drakmar population: {pop_sys.get_population(SERVER, 'Drakmar'):,}")

# 1 month of growth
new_pop = pop_sys.update_population(SERVER, "Evoria", months_passed=1)
print(f"\nEvoria after 1 month (2% growth): {new_pop:,}")

# 12 months of growth (1 in-game year)
new_pop = pop_sys.update_population(SERVER, "Drakmar", months_passed=12)
print(f"Drakmar after 12 months (1.5% growth): {new_pop:,}")

# From-days convenience wrapper
days_to_test = 90   # 3 in-game months
new_pop, months_applied = pop_sys.update_population_from_days(SERVER, "Veldris", days_to_test)
print(f"Veldris after {days_to_test} days ({months_applied} months, 3% growth): {new_pop:,}")

# Growth rate change
pop_sys.set_growth_rate(SERVER, "Evoria", 0.05)
print(f"\nEvoria growth rate set to 5%: {pop_sys.get_growth_rate(SERVER, 'Evoria')}")

# Negative growth (plague / war attrition)
pop_sys.set_growth_rate(SERVER, "Drakmar", -0.01)
pop_for_drakmar = pop_sys.update_population(SERVER, "Drakmar", months_passed=6)
print(f"Drakmar after 6 months at -1% growth: {pop_for_drakmar:,}")

# Direct population change (event)
pop_sys.apply_population_change(SERVER, "Evoria", -500_000)
print(f"Evoria after plague (-500k): {pop_sys.get_population(SERVER, 'Evoria'):,}")

# Bulk
print("\nBulk update (60 days for all countries):")
bulk_pop = pop_sys.update_all_populations(SERVER, days_passed=60)
for cid, new_p in bulk_pop.items():
    print(f"  {cid}: {new_p:,}")


# ===========================================================================
# 6. INTEGRATED TICK LOOP
# ===========================================================================
separator("INTEGRATED TICK LOOP (3 simulated ticks)")

ts_loop = TimeSystem()
ts_loop.set_speed(TimeSpeed.X2)    # 12 in-game days per tick

# Reset economy to clean state
eco_loop = EconomySystem(db)
eco_loop.ensure_country(SERVER, "Evoria")
eco_loop.set_income(SERVER, "Evoria", 200.0)

pop_loop = PopulationSystem(db)
pop_loop.ensure_country(SERVER, "Evoria")
pop_loop.set_growth_rate(SERVER, "Evoria", 0.02)

for tick_n in range(1, 4):
    days_passed = ts_loop.tick()

    # Economy: update every day
    new_t = eco_loop.update_treasury(SERVER, "Evoria", days_passed)

    # Population: update by complete months
    new_p, months = pop_loop.update_population_from_days(SERVER, "Evoria", days_passed)

    print(f"Tick {tick_n} | {ts_loop.date_string()} | "
          f"+{days_passed}d | treasury={new_t:.1f} | "
          f"pop={new_p:,} ({months} months)")


# ===========================================================================
# 7. SERVER ISOLATION CHECK
# ===========================================================================
separator("SERVER ISOLATION")

other_server = "guild_other"
rel_sys.set_religion(other_server, "Evoria", "Hinduism")

print(f"guild_demo  / Evoria religion: {rel_sys.get_religion(SERVER,       'Evoria')}")
print(f"guild_other / Evoria religion: {rel_sys.get_religion(other_server, 'Evoria')}")
print("→ Different servers are fully isolated")


separator("ALL SYSTEMS DEMO COMPLETE")
