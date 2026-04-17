"""
DEMO / SMOKE TEST
-----------------
Exercises the Time, Diplomacy, and War systems together to verify
all core behaviours described in the spec.

Run with:  python -m game_backend.demo
"""

from game_backend.time_system    import TimeSystem, TimeSpeed
from game_backend.diplomacy_system import DiplomacySystem, Country
from game_backend.war_system     import (
    WarSystem, Province, TreatyType, WarOutcome
)


def separator(title: str) -> None:
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


# ===========================================================================
# 1. TIME SYSTEM
# ===========================================================================
separator("TIME SYSTEM")

ts = TimeSystem()
print(f"Start:              {ts.date_string()}")

# Tick at each speed and show progression
for speed in [TimeSpeed.X1, TimeSpeed.X2, TimeSpeed.X3, TimeSpeed.X4, TimeSpeed.X5]:
    ts.set_speed(speed)
    days = ts.tick()
    print(f"Speed {speed.value}x tick  →  +{days:2d} days  |  {ts.date_string()}")

# Pause test
ts.pause()
days_paused = ts.tick()
print(f"Paused tick        →  +{days_paused} days   |  {ts.date_string()}")
ts.unpause()

# Advance enough to roll over a year
ts.advance_days(300)
print(f"After +300 days    →  {ts.date_string()}")

# Absolute day counter
print(f"Total days elapsed: {ts.total_days_elapsed()}")

# Serialisation round-trip
state_dict = ts.get_state().to_dict()
from game_backend.time_system import TimeState
restored_state = TimeState.from_dict(state_dict)
print(f"Restored state:     Year={restored_state.year}, Month={restored_state.month}, Day={restored_state.day}")


# ===========================================================================
# 2. DIPLOMACY SYSTEM
# ===========================================================================
separator("DIPLOMACY SYSTEM")

ds = DiplomacySystem()

evoria  = Country("Evoria",  religion="solarian")
drakmar = Country("Drakmar", religion="obsidian")
veldris = Country("Veldris", religion="solarian")  # Same religion as Evoria

ds.register_country(evoria)
ds.register_country(drakmar)
ds.register_country(veldris)

print("Initial relations (all neutral at 0):")
for row in ds.all_relations():
    print(f"  {row['country_a']} ↔ {row['country_b']}: {row['value']}  ({row['tier']})")

# Improve
ds.improve_relations("Evoria", "Veldris", amount=15)
print(f"\nEvoria ↔ Veldris after +15:   {ds.get_relation('Evoria','Veldris')}  ({ds.get_relation_tier('Evoria','Veldris').value})")
print(f"  Defense Pact possible?  {ds.can_form_defense_pact('Evoria','Veldris')}")

ds.improve_relations("Evoria", "Veldris", amount=10)
print(f"Evoria ↔ Veldris after +10:   {ds.get_relation('Evoria','Veldris')}  ({ds.get_relation_tier('Evoria','Veldris').value})")
print(f"  Alliance possible?      {ds.can_form_alliance('Evoria','Veldris')}")

# Damage
ds.damage_relations("Evoria", "Drakmar", amount=5)
print(f"\nEvoria ↔ Drakmar after -5:    {ds.get_relation('Evoria','Drakmar')}  ({ds.get_relation_tier('Evoria','Drakmar').value})")
print(f"  Can declare war?        {ds.can_declare_war('Evoria','Drakmar')}")

# Gift
ds.send_gift(sender="Veldris", receiver="Drakmar", gift_value=5000, relation_boost=3)
print(f"\nVeldris → Drakmar gift (+3): {ds.get_relation('Veldris','Drakmar')}")

# Religious persecution auto-modifier
print("\nDrakmar enacts religious persecution of 'solarian' faith...")
affected = ds.apply_religious_persecution("Drakmar", "solarian")
print(f"  Affected countries:     {affected}")
print(f"  Evoria ↔ Drakmar now:   {ds.get_relation('Evoria','Drakmar')}")
print(f"  Veldris ↔ Drakmar now:  {ds.get_relation('Veldris','Drakmar')}")

# War eligibility after persecution
print(f"\n  Evoria can declare war on Drakmar?  {ds.can_declare_war('Evoria','Drakmar')}")

# Serialisation round-trip
ds2 = DiplomacySystem.from_dict(ds.to_dict())
print(f"\nSerialization check — Evoria ↔ Drakmar restored: {ds2.get_relation('Evoria','Drakmar')}")


# ===========================================================================
# 3. WAR SYSTEM
# ===========================================================================
separator("WAR SYSTEM")

ws = WarSystem()

# Province registry (shared with game layer)
provinces: dict[str, Province] = {
    "Ironfort":    Province("Ironfort",    owner="Drakmar", war_score_cost=15),
    "Ashwood":     Province("Ashwood",     owner="Drakmar", war_score_cost=10),
    "Goldmere":    Province("Goldmere",    owner="Drakmar", war_score_cost=20),
    "Northpass":   Province("Northpass",   owner="Evoria",  war_score_cost=10),
}

current_day = ts.total_days_elapsed()

# Declare war
war_id = ws.declare_war("Evoria", "Drakmar", current_day=current_day)
print(f"War declared!  ID: {war_id}")

war = ws.get_war(war_id)
print(f"  Attackers: {war.attackers}")
print(f"  Defenders: {war.defenders}")
print(f"  War score: {war.war_score}  (0 = even)")

# Occupy provinces
ws.occupy_province(war_id, "Ironfort",  occupied_by="Evoria", original_owner="Drakmar")
ws.occupy_province(war_id, "Ashwood",   occupied_by="Evoria", original_owner="Drakmar")
print(f"\nEvoria occupies Ironfort and Ashwood.")
print(f"  War score: {ws.get_war(war_id).war_score}  (+10 per province)")

# Manual war-score adjustment (e.g. battle victory)
ws.adjust_war_score(war_id, delta=25)
print(f"  Battle victory +25 → War score: {ws.get_war(war_id).war_score}")

# --- Scenario A: White Peace ---
separator("WAR SYSTEM — White Peace")
# Clone for independent scenario
ws_a = WarSystem()
war_id_a = ws_a.declare_war("Evoria", "Drakmar", current_day=current_day)
ws_a.occupy_province(war_id_a, "Ashwood", occupied_by="Evoria", original_owner="Drakmar")
result_a = ws_a.resolve_treaty(war_id_a, TreatyType.WHITE_PEACE, current_day=current_day,
                                provinces=dict(provinces))
print(f"Treaty: WHITE PEACE")
for change in result_a["changes"]:
    print(f"  {change}")
print(f"  Ceasefire active? {ws_a.ceasefire_active('Evoria','Drakmar', current_day + 1)}")
print(f"  Ceasefire expires in 1080 in-game days")

# --- Scenario B: Surrender ---
separator("WAR SYSTEM — Surrender")
ws_b = WarSystem()
war_id_b = ws_b.declare_war("Evoria", "Drakmar", current_day=current_day)
ws_b.occupy_province(war_id_b, "Ironfort", occupied_by="Evoria", original_owner="Drakmar")
ws_b.occupy_province(war_id_b, "Ashwood",  occupied_by="Evoria", original_owner="Drakmar")
result_b = ws_b.resolve_treaty(war_id_b, TreatyType.SURRENDER, current_day=current_day,
                                provinces=dict(provinces))
print(f"Treaty: SURRENDER (Evoria wins)")
for change in result_b["changes"]:
    print(f"  {change}")

# --- Scenario C: Proclaim Victory ---
separator("WAR SYSTEM — Proclaim Victory")
ws_c = WarSystem()
war_id_c = ws_c.declare_war("Evoria", "Drakmar", current_day=current_day)
ws_c.occupy_province(war_id_c, "Ironfort",  occupied_by="Evoria", original_owner="Drakmar")
ws_c.occupy_province(war_id_c, "Ashwood",   occupied_by="Evoria", original_owner="Drakmar")
ws_c.occupy_province(war_id_c, "Goldmere",  occupied_by="Evoria", original_owner="Drakmar")
ws_c.adjust_war_score(war_id_c, delta=80)   # Decisive advantage for demands

local_provinces = {
    "Ironfort":  Province("Ironfort",  owner="Drakmar", war_score_cost=15),
    "Ashwood":   Province("Ashwood",   owner="Drakmar", war_score_cost=10),
    "Goldmere":  Province("Goldmere",  owner="Drakmar", war_score_cost=20),
}
result_c = ws_c.resolve_treaty(
    war_id_c,
    TreatyType.PROCLAIM_VICTORY,
    current_day=current_day,
    provinces=local_provinces,
    reparations_duration_days=1080,
)
print(f"Treaty: PROCLAIM VICTORY (Evoria wins)")
for change in result_c["changes"]:
    print(f"  {change}")
print(f"\nActive reparations: {len(ws_c.get_active_reparations(current_day + 1))}")
print(f"Drakmar's vassal overlord: "
      f"{ws_c.get_vassal_relation('Drakmar').overlord if ws_c.get_vassal_relation('Drakmar') else 'none'}")

# Vassal rebels
ws_c.vassal_rebels("Drakmar")
print(f"After rebellion — Drakmar vassal relation: {ws_c.get_vassal_relation('Drakmar')}")

# Serialisation round-trip
ws_c2 = WarSystem.from_dict(ws_c.to_dict())
print(f"\nSerialization check — wars restored: {len(ws_c2._wars)}")

separator("ALL SYSTEMS DEMO COMPLETE")
