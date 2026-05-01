"""
WW1 MILITARY TECH + TROOP DEFINITIONS DEMO
--------------------------------------------
End-to-end smoke test for:

  Part 1 — Troop definition seeding and lookup
  Part 2 — Military tech tree: start research, process completions, unlock check
  Part 3 — Research queue guard (only one active research at a time)
  Part 4 — Prerequisite enforcement
  Part 5 — Multi-prerequisite tech (Early Bombers needs 3 unlocks)
  Part 6 — Recruitment validation gate (tech unlock required)
  Part 7 — get_recruitable_units (filtered by unlocked techs)
  Part 8 — Full tree walk: root → naval branch to Light Carriers

Run with:
    python3 -m ww1_economy.military_demo
"""

from __future__ import annotations

import sys

from ww1_economy.db                       import EconomyDB
from ww1_economy.military_tech_system     import MilitaryTechSystem
from ww1_economy.troop_definition_system  import TroopDefinitionSystem
from ww1_economy.military_tech_data       import MILITARY_TECH_TREE
from ww1_economy.unit_data                import UNIT_DEFINITIONS


# ── helpers ───────────────────────────────────────────────────────────────────

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    msg = f"  [{tag}] {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    if not condition:
        _failures.append(label)


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ── setup ─────────────────────────────────────────────────────────────────────

SERVER  = "demo_server"
SCEN    = "ww1"
COUNTRY = "germany"

db      = EconomyDB(":memory:")
db.init()

mil_tech = MilitaryTechSystem(db)
troop_sys = TroopDefinitionSystem(db, mil_tech)

# ── Part 1: Troop definition seeding ─────────────────────────────────────────

section("Part 1 — Troop definition seeding")

result = troop_sys.seed_definitions(SERVER, SCEN)
check("All units seeded",        result.total    == len(UNIT_DEFINITIONS),
      f"{result.total} units")
check("First seed inserts rows", result.seeded   == len(UNIT_DEFINITIONS),
      f"{result.seeded} inserted")

# Idempotent second seed
result2 = troop_sys.seed_definitions(SERVER, SCEN)
check("Second seed inserts 0",   result2.seeded  == 0,
      "idempotent")

all_units = troop_sys.get_all_units(SERVER, SCEN)
check("All units retrievable",   len(all_units)  == len(UNIT_DEFINITIONS),
      f"{len(all_units)} rows")

# Category spot checks
f1_units = troop_sys.get_units_by_category(SERVER, SCEN, "F1")
check("F1 has 4 units",          len(f1_units)   == 4)

n1_units = troop_sys.get_units_by_category(SERVER, SCEN, "N1")
check("N1 has 5 naval units",    len(n1_units)   == 5)

# Single unit lookup
cannon = troop_sys.get_unit(SERVER, SCEN, "Cannons")
check("Cannons definition found",            cannon is not None)
check("Cannons category is S2",              cannon["category"]              == "S2")
check("Cannons required_tech is 'cannons'",  cannon["required_tech"]         == "cannons")
check("Cannons pop_required = 3",            cannon["population_required"]   == 3)
check("Cannons gold_cost = 6",              cannon["gold_cost"]             == 6.0)
check("Cannons recruit_time = 45d",         cannon["recruitment_time_days"] == 45)
check("Cannons speed = 0.8",               cannon["speed_modifier"]        == 0.8)
check("Cannons battle_points = 16",        cannon["battle_points"]         == 16)

# Units unlocked by a tech
units_by_mech = troop_sys.get_units_unlocked_by_tech(SERVER, SCEN, "mechanised_infantry")
names_by_mech = {u["unit_name"] for u in units_by_mech}
check("mechanised_infantry tech unlocks 2 units", len(units_by_mech) == 2)
check("Mechanised Infantry in set",   "Mechanised Infantry"          in names_by_mech)
check("Adv. Mech Infantry in set",    "Advanced Mechanised Infantry" in names_by_mech)

# ── Part 2: Research start + completion ──────────────────────────────────────

section("Part 2 — Research start and completion")

day = 0
r = mil_tech.start_research(SERVER, SCEN, COUNTRY, "pre_industrial_military_doctrine", day)
check("Root tech research starts",    r.allowed, r.reason)
check("Duration = 30d (1 month)",     r.duration_days == 30, f"{r.duration_days}d")
check("End day = 30",                 r.end_day       == 30, f"end_day={r.end_day}")

# Try to start a second while first is active
r2 = mil_tech.start_research(SERVER, SCEN, COUNTRY, "early_infantry", day)
check("Queue blocks second research", not r2.allowed, r2.reason)

# Advance to day 30 and process
events = mil_tech.process_completions(SERVER, SCEN, current_day=30)
check("Root tech completes on day 30", len(events) == 1)
check("Completed tech_id correct",     events[0].tech_id == "pre_industrial_military_doctrine")

# Verify unlocked
check("Root tech is now unlocked",
      mil_tech.is_tech_unlocked(SERVER, SCEN, COUNTRY, "pre_industrial_military_doctrine"))

# ── Part 3: Queue guard after completion ─────────────────────────────────────

section("Part 3 — Queue guard: one research at a time")

day = 30
r = mil_tech.start_research(SERVER, SCEN, COUNTRY, "early_infantry", day)
check("early_infantry starts after root", r.allowed, r.reason)

r_block = mil_tech.start_research(SERVER, SCEN, COUNTRY, "grenadier", day)
check("grenadier blocked while early_infantry active", not r_block.allowed, r_block.reason)

events = mil_tech.process_completions(SERVER, SCEN, current_day=30 + 60)  # 2 months later
check("early_infantry completes",
      any(e.tech_id == "early_infantry" for e in events))
check("early_infantry: Line Infantry unlocked via event",
      "Line Infantry" in events[0].unlocked_units if events else False)

# ── Part 4: Prerequisite enforcement ─────────────────────────────────────────

section("Part 4 — Prerequisite enforcement")

# elite_line_infantry requires line_infantry which is NOT yet unlocked
r = mil_tech.start_research(SERVER, SCEN, COUNTRY, "elite_line_infantry", current_day=90)
check("elite_line_infantry blocked (prereq line_infantry missing)",
      not r.allowed, r.reason)

# line_infantry (3 months) then elite_line_infantry
r = mil_tech.start_research(SERVER, SCEN, COUNTRY, "line_infantry", current_day=90)
check("line_infantry starts", r.allowed, r.reason)
mil_tech.process_completions(SERVER, SCEN, current_day=90 + 90)  # 3 months
check("line_infantry unlocked",
      mil_tech.is_tech_unlocked(SERVER, SCEN, COUNTRY, "line_infantry"))

r = mil_tech.start_research(SERVER, SCEN, COUNTRY, "elite_line_infantry", current_day=180)
check("elite_line_infantry starts after line_infantry unlocked", r.allowed, r.reason)
mil_tech.process_completions(SERVER, SCEN, current_day=180 + 180)  # 6 months
check("elite_line_infantry unlocked",
      mil_tech.is_tech_unlocked(SERVER, SCEN, COUNTRY, "elite_line_infantry"))

# ── Part 5: Multi-prerequisite (Early Bombers) ────────────────────────────────

section("Part 5 — Multi-prerequisite: Early Bombers (early_aviation + observation_balloons + artillery)")

COUNTRY2 = "france"

# early_bombers needs: early_aviation, observation_balloons, artillery
# artillery needs: mechanised_army → modern_warfare_doctrine → pre_industrial_military_doctrine

def fast_unlock(country: str, tech_id: str, start_day: int) -> int:
    """Unlock tech immediately (simulate 0-duration by injecting directly)."""
    tdef = MILITARY_TECH_TREE[tech_id]
    db.upsert_military_technology(
        server_id              = SERVER,
        scenario_id            = SCEN,
        country_id             = country,
        tech_id                = tech_id,
        is_unlocked            = True,
        is_researching         = False,
        research_start_day     = start_day,
        research_duration_days = tdef.duration_days,
        research_end_day       = start_day + tdef.duration_days,
    )
    return start_day + tdef.duration_days

# Give france the required prerequisites
for tid in [
    "pre_industrial_military_doctrine",
    "aerial_warfare",
    "early_aviation",
    "observation_balloons",
    "modern_warfare_doctrine",
    "mechanised_army",
    "artillery",
]:
    fast_unlock(COUNTRY2, tid, 0)

# Now early_bombers should be researchable
r = mil_tech.start_research(SERVER, SCEN, COUNTRY2, "early_bombers", current_day=0)
check("Early Bombers starts when all 3 prereqs met", r.allowed, r.reason)
mil_tech.process_completions(SERVER, SCEN, current_day=r.end_day)
check("Early Bombers unlocked",
      mil_tech.is_tech_unlocked(SERVER, SCEN, COUNTRY2, "early_bombers"))

# Verify a third country missing one prereq is blocked
COUNTRY3 = "austria"
for tid in [
    "pre_industrial_military_doctrine",
    "aerial_warfare",
    "early_aviation",
    # observation_balloons MISSING
    "modern_warfare_doctrine",
    "mechanised_army",
    "artillery",
]:
    fast_unlock(COUNTRY3, tid, 0)

r = mil_tech.start_research(SERVER, SCEN, COUNTRY3, "early_bombers", current_day=0)
check("Early Bombers blocked when observation_balloons missing",
      not r.allowed, r.reason)

# ── Part 6: Recruitment validation gate ──────────────────────────────────────

section("Part 6 — Recruitment validation gate")

# germany has: pre_industrial, early_infantry, line_infantry, elite_line_infantry
COUNTRY4 = "russia"
fast_unlock(COUNTRY4, "pre_industrial_military_doctrine", 0)
fast_unlock(COUNTRY4, "support_units", 0)

v = troop_sys.validate_recruitment(SERVER, SCEN, COUNTRY4, "Elite Archers")
check("Elite Archers recruitable (support_units unlocked)", v.allowed, v.reason)
check("Elite Archers gold_cost = 4",   v.gold_cost             == 4.0)
check("Elite Archers pop_required = 1", v.population_required  == 1)
check("Elite Archers recruit_time 30d", v.recruitment_time_days == 30)

v2 = troop_sys.validate_recruitment(SERVER, SCEN, COUNTRY4, "Cannons")
check("Cannons blocked (cannons tech not unlocked)", not v2.allowed, v2.reason)

v3 = troop_sys.validate_recruitment(SERVER, SCEN, COUNTRY4, "NonExistentUnit")
check("Unknown unit returns not allowed", not v3.allowed, v3.reason)

# ── Part 7: get_recruitable_units ────────────────────────────────────────────

section("Part 7 — get_recruitable_units")

COUNTRY5 = "ottoman"
fast_unlock(COUNTRY5, "pre_industrial_military_doctrine", 0)
fast_unlock(COUNTRY5, "naval_warfare_doctrine", 0)
fast_unlock(COUNTRY5, "gunboats", 0)
fast_unlock(COUNTRY5, "early_battleships", 0)

recruitable = troop_sys.get_recruitable_units(SERVER, SCEN, COUNTRY5)
names_recruitable = {u["unit_name"] for u in recruitable}

check("Gunboats recruitable",         "Gunboats"         in names_recruitable)
check("Early Battleships recruitable","Early Battleships" in names_recruitable)
check("Battleships NOT recruitable",  "Battleships"       not in names_recruitable)
check("Rifleman NOT recruitable",     "Rifleman"          not in names_recruitable)

# ── Part 8: Full naval branch walk ───────────────────────────────────────────

section("Part 8 — Full naval branch walk: root → Light Carriers")

COUNTRY6 = "britain"
naval_path = [
    "pre_industrial_military_doctrine",
    "naval_warfare_doctrine",
    "light_carriers",   # 18 months, direct child of naval_warfare_doctrine
]

fast_unlock(COUNTRY6, "pre_industrial_military_doctrine", 0)
fast_unlock(COUNTRY6, "naval_warfare_doctrine", 0)

r = mil_tech.start_research(SERVER, SCEN, COUNTRY6, "light_carriers", current_day=0)
check("Light Carriers research starts after naval_warfare_doctrine", r.allowed, r.reason)
check("Light Carriers duration = 18 months (540d)", r.duration_days == 540,
      f"{r.duration_days}d")

events = mil_tech.process_completions(SERVER, SCEN, current_day=540)
check("Light Carriers completes on day 540", len(events) == 1)
lc_unit = troop_sys.get_unit(SERVER, SCEN, "Light Carriers")
check("Light Carriers unit: pop=15",         lc_unit["population_required"] == 15)
check("Light Carriers unit: gold=35",        lc_unit["gold_cost"]           == 35.0)
check("Light Carriers unit: battle_pts=95",  lc_unit["battle_points"]       == 95)

v = troop_sys.validate_recruitment(SERVER, SCEN, COUNTRY6, "Light Carriers")
check("Light Carriers recruitable after tech unlock", v.allowed, v.reason)

# ── Status helpers ────────────────────────────────────────────────────────────

section("Status summary for Germany")

status = mil_tech.get_status(SERVER, SCEN, COUNTRY)
unlocked_ids = [tid for tid, s in status.items() if s.is_unlocked]
print(f"  Germany unlocked techs ({len(unlocked_ids)}): {sorted(unlocked_ids)}")
check("Germany has at least 4 unlocked techs", len(unlocked_ids) >= 4)

researchable = mil_tech.get_researchable_techs(SERVER, SCEN, COUNTRY)
print(f"  Germany researchable techs: {researchable}")
check("Researchable list is non-empty", len(researchable) > 0)

category_summary = troop_sys.get_category_summary(SERVER, SCEN)
print(f"  Category summary:")
for cat, names in sorted(category_summary.items()):
    print(f"    {cat}: {', '.join(sorted(names))}")

# ── Final report ──────────────────────────────────────────────────────────────

section("Final report")

if _failures:
    print(f"\n  {FAIL}: {len(_failures)} check(s) failed:")
    for f in _failures:
        print(f"    - {f}")
    sys.exit(1)
else:
    total = sum(1 for line in open(__file__) if "check(" in line)
    print(f"\n  {PASS}: All checks passed.")
    sys.exit(0)
