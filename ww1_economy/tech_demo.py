"""
WW1 TECHNOLOGY SYSTEM — END-TO-END DEMO
-----------------------------------------
Exercises every component of the Technology System spec:

  Part 1 — Core Technology System (DB table, one-research constraint)
  Part 2 — Research Speed System (base, infra bonuses, DR, modifiers)
  Part 3 — Economic Technology (Industrialization → Chemical Processing,
            tech-gated buildings: Powder Mill / Arms Factory / Pharma)
  Part 4 — Infrastructure Technology (Early Modern Infra → Library → School
            → University; Hospital / Library / School / University buildings
            with resource deduction at construction start)
  Part 5 — Reforms System (unlock, adopt with gold cost, max-3 limit, effects)
  Part 6 — start_research() process (prerequisites, queue exclusivity,
            end_day computed from research speed)
  Part 7 — Daily process (research completion via TickSystem.daily_tick)

Run:
    python3 -m ww1_economy.tech_demo
"""

from __future__ import annotations

import sys

from ww1_economy.db               import EconomyDB
from ww1_economy.storage_system   import StorageSystem
from ww1_economy.treasury_system  import TreasurySystem
from ww1_economy.building_system  import BuildingSystem
from ww1_economy.technology_system import TechnologySystem
from ww1_economy.reforms_system   import ReformsSystem
from ww1_economy.tick_system      import TickSystem
from ww1_economy.tech_data        import (
    TECH_TREE, REFORM_TREE,
    BUILDING_TECH_REQUIREMENTS, TECH_GATED_BUILDINGS,
    REFORM_ADOPTION_COST, MAX_ADOPTED_REFORMS,
)

# ── Constants ──────────────────────────────────────────────────────────────────
SERVER   = "guild_tech_demo"
SCENARIO = "ww1"
GERMANY  = "germany"
FRANCE   = "france"
DAYS_PER_MONTH = 30

SEPARATOR = "=" * 72


def hdr(n: int, title: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {n}. {title}")
    print(SEPARATOR)


def sub(title: str) -> None:
    print(f"\n--- {title} ---")


def chk(condition: bool, msg: str) -> None:
    if not condition:
        print(f"  FAIL: {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"  OK  : {msg}")


# ── Setup ──────────────────────────────────────────────────────────────────────

db = EconomyDB(":memory:")
db.init()

storage   = StorageSystem(db)
treasury  = TreasurySystem(db)
buildings = BuildingSystem(db)
tech      = TechnologySystem(db)
reforms   = ReformsSystem(db, treasury)
tick      = TickSystem.assemble(db)

# Seed countries
for cid, name, gold in [
    (GERMANY, "Germany",  1000.0),
    (FRANCE,  "France",   1000.0),
]:
    db.upsert_country(SERVER, SCENARIO, cid, name, 5_000_000)
    treasury.set(SERVER, SCENARIO, cid, gold)
    db.update_country_fields(
        SERVER, SCENARIO, cid,
        population_opinion=65,
        unrest=10.0,
        in_active_war=0,
    )

# Seed provinces (province_id as int per DB schema)
for pid, pname, owner, res, pop in [
    (1, "Berlin",     GERMANY, "iron",  500_000),
    (2, "Munich",     GERMANY, "coal",  400_000),
    (3, "Hamburg",    GERMANY, "wood",  350_000),
    (4, "Frankfurt",  GERMANY, "stone", 300_000),
    (5, "Stuttgart",  GERMANY, "grain", 280_000),
    (6, "Paris",      FRANCE,  "iron",  600_000),
    (7, "Lyon",       FRANCE,  "coal",  300_000),
]:
    db.upsert_province(SERVER, SCENARIO, pid, pname, owner, res, pop)

# Seed storage — Germany needs wood + stone for infra buildings
storage.set_resource(SERVER, SCENARIO, GERMANY, "wood",  500)
storage.set_resource(SERVER, SCENARIO, GERMANY, "stone", 500)
storage.set_resource(SERVER, SCENARIO, GERMANY, "iron",  200)
storage.set_resource(SERVER, SCENARIO, GERMANY, "coal",  200)

# France needs fewer resources
storage.set_resource(SERVER, SCENARIO, FRANCE, "wood",   50)
storage.set_resource(SERVER, SCENARIO, FRANCE, "stone",  50)


# ==============================================================================
#  SECTION 1 — TECH TREE STRUCTURE + DB TABLE
# ==============================================================================

hdr(1, "TECH TREE STRUCTURE AND DATABASE TABLE")

sub("Tech tree contents (static data)")
for tid, tdef in TECH_TREE.items():
    print(f"  {tid:<35} {tdef.duration_months:>3}mo  "
          f"prereqs={list(tdef.prerequisites)}")

chk(len(TECH_TREE) == 6, "Tech tree has exactly 6 nodes")
chk("industrialization" in TECH_TREE, "'industrialization' present")
chk("chemical_processing" in TECH_TREE, "'chemical_processing' present")
chk("early_modern_infrastructure" in TECH_TREE,
    "'early_modern_infrastructure' present")
chk("library" in TECH_TREE, "'library' tech present")
chk("school"  in TECH_TREE, "'school' tech present")
chk("university" in TECH_TREE, "'university' tech present")

sub("Tech-gated buildings")
for bname, tid in sorted(BUILDING_TECH_REQUIREMENTS.items()):
    print(f"  '{bname}' → requires '{tid}'")

chk("Powder Mill"          in TECH_GATED_BUILDINGS, "Powder Mill gated")
chk("Arms Factory"         in TECH_GATED_BUILDINGS, "Arms Factory gated")
chk("Pharmaceutical Plant" in TECH_GATED_BUILDINGS, "Pharmaceutical Plant gated")
chk("Hospital"             in TECH_GATED_BUILDINGS, "Hospital gated")
chk("Library"              in TECH_GATED_BUILDINGS, "Library building gated")
chk("School"               in TECH_GATED_BUILDINGS, "School building gated")
chk("University"           in TECH_GATED_BUILDINGS, "University building gated")
chk("Mine" not in TECH_GATED_BUILDINGS,             "Mine NOT gated (Tier 1)")
chk("Farm" not in TECH_GATED_BUILDINGS,             "Farm NOT gated (Tier 1)")
chk("Chemical Plant" not in TECH_GATED_BUILDINGS,   "Chemical Plant NOT gated (per spec)")

sub("DB tables created (technologies + reforms)")
tables = {
    r[0] for r in
    db._mem_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
}
chk("technologies" in tables, "technologies table exists")
chk("reforms"      in tables, "reforms table exists")


# ==============================================================================
#  SECTION 2 — RESEARCH SPEED (base, modifiers, diminishing returns)
# ==============================================================================

hdr(2, "RESEARCH SPEED SYSTEM")

sub("Base speed (no buildings, normal opinion/unrest)")
spd = tech.compute_research_speed(SERVER, SCENARIO, GERMANY)
print(f"  base={spd.base}%  infra_bonus={spd.infra_bonus}%  "
      f"opinion={spd.opinion_modifier}%  unrest={spd.unrest_modifier}%")
print(f"  raw={spd.raw_speed:.4f}%  final={spd.final_speed:.4f}%")
chk(spd.base == 1.0,     "base speed = 1.0%")
chk(spd.infra_bonus == 0.0, "no infra bonus yet")
chk(spd.final_speed >= 0.5, "speed ≥ minimum 0.5%")

sub("Opinion > 80 → +0.5% bonus")
db.update_country_fields(SERVER, SCENARIO, GERMANY, population_opinion=85)
spd_high = tech.compute_research_speed(SERVER, SCENARIO, GERMANY)
print(f"  opinion modifier: {spd_high.opinion_modifier:+.2f}%  "
      f"final={spd_high.final_speed:.4f}%")
chk(spd_high.opinion_modifier == 0.5, "opinion>80 → +0.5%")

sub("Opinion < 30 → -1.5% penalty")
db.update_country_fields(SERVER, SCENARIO, GERMANY, population_opinion=20)
spd_low = tech.compute_research_speed(SERVER, SCENARIO, GERMANY)
chk(spd_low.opinion_modifier == -1.5, "opinion<30 → -1.5%")

sub("Unrest > 50 → -2% penalty")
db.update_country_fields(
    SERVER, SCENARIO, GERMANY, population_opinion=65, unrest=60.0
)
spd_unrest = tech.compute_research_speed(SERVER, SCENARIO, GERMANY)
chk(spd_unrest.unrest_modifier == -2.0, "unrest>50 → -2%")

sub("Minimum clamp at 0.5%")
db.update_country_fields(
    SERVER, SCENARIO, GERMANY, population_opinion=20, unrest=60.0
)
spd_min = tech.compute_research_speed(SERVER, SCENARIO, GERMANY)
print(f"  raw={spd_min.raw_speed:.4f}%  clamped to {spd_min.final_speed:.4f}%")
chk(spd_min.final_speed >= 0.5, "speed clamped to 0.5% minimum")

# Reset to normal
db.update_country_fields(
    SERVER, SCENARIO, GERMANY, population_opinion=65, unrest=10.0
)


# ==============================================================================
#  SECTION 3 — ECONOMIC TECHNOLOGY (Industrialization → Chemical Processing)
# ==============================================================================

hdr(3, "ECONOMIC TECHNOLOGY")

sub("Part 6 — start_research (queue, prerequisites, end_day)")
current_day = 1

# Start Industrialization
r = tech.start_research(SERVER, SCENARIO, GERMANY, "industrialization", current_day)
print(f"  Start industrialization: allowed={r.allowed}  end_day={r.end_day}  "
      f"speed={r.speed_used:.2f}%")
chk(r.allowed, "industrialization research started")
spd_now = tech.compute_research_speed(SERVER, SCENARIO, GERMANY).final_speed
expected_end = current_day + int(TECH_TREE["industrialization"].duration_days
                                 / (spd_now / 100.0))
chk(r.end_day == expected_end,
    f"end_day={r.end_day} matches formula ({expected_end})")

# Queue exclusivity
r2 = tech.start_research(SERVER, SCENARIO, GERMANY, "chemical_processing", current_day)
chk(not r2.allowed, "cannot start second research while first is active")
print(f"  Blocked (expected): {r2.reason}")

# Prerequisite not met for france
r_prereq = tech.start_research(SERVER, SCENARIO, FRANCE, "chemical_processing", 1)
chk(not r_prereq.allowed, "chemical_processing blocked by missing prerequisite")
print(f"  Prerequisite check (expected): {r_prereq.reason}")

sub("Part 7 — Daily process: research completion")
# Fast-forward to end_day for Germany
dt = tick.daily_tick(SERVER, SCENARIO, r.end_day, days_passed=0)
chk(len(dt.tech_completions) == 1, "industrialization completes on end_day")
completed_event = dt.tech_completions[0]
print(f"  Completed: {completed_event.name} for {completed_event.country_id}")
print(f"  Unlocked techs: {completed_event.unlocked_techs}")
chk(completed_event.tech_id == "industrialization", "correct tech completed")
chk("chemical_processing" in completed_event.unlocked_techs,
    "chemical_processing now researchable")
chk(tech.is_unlocked(SERVER, SCENARIO, GERMANY, "industrialization"),
    "industrialization is_unlocked=True in DB")

sub("Now research Chemical Processing (prerequisite satisfied)")
r_chem = tech.start_research(
    SERVER, SCENARIO, GERMANY, "chemical_processing", r.end_day
)
print(f"  Start chemical_processing: allowed={r_chem.allowed}  end_day={r_chem.end_day}")
chk(r_chem.allowed, "chemical_processing research started")

# Fast-forward
dt2 = tick.daily_tick(SERVER, SCENARIO, r_chem.end_day, days_passed=0)
chk(len(dt2.tech_completions) == 1, "chemical_processing completes")
chk(dt2.tech_completions[0].tech_id == "chemical_processing",
    "correct tech completed")
chk(tech.is_unlocked(SERVER, SCENARIO, GERMANY, "chemical_processing"),
    "chemical_processing is_unlocked=True in DB")

sub("Tech-gated construction: Powder Mill / Arms Factory / Pharma")
# Germany now has chemical_processing → can build Powder Mill
result_pm = buildings.start_construction(
    server_id        = SERVER,
    scenario_id      = SCENARIO,
    province_id      = "1",   # Berlin
    country_id       = GERMANY,
    building_type    = "Powder Mill",
    province_resource = "iron",
    current_day      = r_chem.end_day + 1,
    treasury         = treasury,
    technology       = tech,
    storage          = storage,
)
print(f"  Germany build Powder Mill: allowed={result_pm['allowed']}")
chk(result_pm["allowed"], "Germany can build Powder Mill (chemical_processing unlocked)")

# France lacks chemical_processing → blocked
result_pm_fr = buildings.start_construction(
    server_id        = SERVER,
    scenario_id      = SCENARIO,
    province_id      = "6",   # Paris
    country_id       = FRANCE,
    building_type    = "Arms Factory",
    province_resource = "iron",
    current_day      = r_chem.end_day + 1,
    treasury         = treasury,
    technology       = tech,
    storage          = storage,
)
print(f"  France build Arms Factory: allowed={result_pm_fr['allowed']}  "
      f"reason={result_pm_fr['reason']}")
chk(not result_pm_fr["allowed"],
    "France cannot build Arms Factory (chemical_processing not unlocked)")


# ==============================================================================
#  SECTION 4 — INFRASTRUCTURE TECHNOLOGY + BUILDINGS
# ==============================================================================

hdr(4, "INFRASTRUCTURE TECHNOLOGY")

sub("Research Early Modern Infrastructure (1 month)")
day_infra = r_chem.end_day + 5
r_emi = tech.start_research(
    SERVER, SCENARIO, GERMANY, "early_modern_infrastructure", day_infra
)
print(f"  Start early_modern_infrastructure: allowed={r_emi.allowed}  "
      f"end_day={r_emi.end_day}")
chk(r_emi.allowed, "early_modern_infrastructure research started")

# Complete it
dt_emi = tick.daily_tick(SERVER, SCENARIO, r_emi.end_day, days_passed=0)
chk(len(dt_emi.tech_completions) == 1, "early_modern_infrastructure completes")
chk(tech.is_unlocked(
    SERVER, SCENARIO, GERMANY, "early_modern_infrastructure"
), "early_modern_infrastructure unlocked in DB")
print(f"  Unlocked buildings: {dt_emi.tech_completions[0].unlocked_buildings}")

sub("Build Hospital (requires early_modern_infra, uses stone+wood)")
wood_before  = storage.get_resource(SERVER, SCENARIO, GERMANY, "wood")
stone_before = storage.get_resource(SERVER, SCENARIO, GERMANY, "stone")
gold_before  = treasury.get(SERVER, SCENARIO, GERMANY)

result_hosp = buildings.start_construction(
    server_id         = SERVER,
    scenario_id       = SCENARIO,
    province_id       = "1",  # Berlin
    country_id        = GERMANY,
    building_type     = "Hospital",
    province_resource = "iron",
    current_day       = r_emi.end_day + 1,
    treasury          = treasury,
    technology        = tech,
    storage           = storage,
)
print(f"  Build Hospital: allowed={result_hosp['allowed']}  "
      f"resources_deducted={result_hosp.get('resources_deducted')}  "
      f"gold_cost={result_hosp['cost']:.0f}")
chk(result_hosp["allowed"], "Hospital construction started")
chk(result_hosp["paid"],    "Gold was deducted for Hospital")

wood_after  = storage.get_resource(SERVER, SCENARIO, GERMANY, "wood")
stone_after = storage.get_resource(SERVER, SCENARIO, GERMANY, "stone")
gold_after  = treasury.get(SERVER, SCENARIO, GERMANY)

chk(wood_before  - wood_after  == 15, "15 wood deducted for Hospital")
chk(stone_before - stone_after == 25, "25 stone deducted for Hospital")
chk(gold_before  - gold_after  == 60, "60 gold deducted for Hospital")

sub("Build Library (requires early_modern_infra; same province as Hospital)")
wood_before2  = storage.get_resource(SERVER, SCENARIO, GERMANY, "wood")
stone_before2 = storage.get_resource(SERVER, SCENARIO, GERMANY, "stone")

result_lib = buildings.start_construction(
    server_id         = SERVER,
    scenario_id       = SCENARIO,
    province_id       = "1",  # Berlin — both Hospital and Library in same province
    country_id        = GERMANY,
    building_type     = "Library",
    province_resource = "iron",
    current_day       = r_emi.end_day + 1,
    treasury          = treasury,
    technology        = tech,
    storage           = storage,
)
print(f"  Build Library (same province as Hospital): allowed={result_lib['allowed']}  "
      f"resources_deducted={result_lib.get('resources_deducted')}")
chk(result_lib["allowed"], "Library can coexist with Hospital in same province")
chk(result_lib.get("resources_deducted", {}).get("wood",  0) == 20,
    "20 wood deducted for Library")
chk(result_lib.get("resources_deducted", {}).get("stone", 0) == 5,
    "5 stone deducted for Library")

sub("Attempt to build Library again in same province → blocked")
result_lib2 = buildings.start_construction(
    server_id         = SERVER,
    scenario_id       = SCENARIO,
    province_id       = "1",
    country_id        = GERMANY,
    building_type     = "Library",
    province_resource = "iron",
    current_day       = r_emi.end_day + 1,
    treasury          = treasury,
    technology        = tech,
    storage           = storage,
)
chk(not result_lib2["allowed"], "Cannot build second Library in same province")
print(f"  Blocked (expected): {result_lib2['reason']}")

sub("Attempt Hospital before tech unlock (France)")
result_hosp_fr = buildings.start_construction(
    server_id         = SERVER,
    scenario_id       = SCENARIO,
    province_id       = "6",  # Paris
    country_id        = FRANCE,
    building_type     = "Hospital",
    province_resource = "iron",
    current_day       = r_emi.end_day + 1,
    treasury          = treasury,
    technology        = tech,
    storage           = storage,
)
chk(not result_hosp_fr["allowed"],
    "France cannot build Hospital without early_modern_infrastructure")
print(f"  Blocked (expected): {result_hosp_fr['reason']}")

sub("Insufficient resources → building blocked (France Hospital via fake unlock)")
# Give France the tech manually to test resource gating in isolation
db.upsert_technology(
    SERVER, SCENARIO, FRANCE, "early_modern_infrastructure",
    is_unlocked=True,
)
storage.set_resource(SERVER, SCENARIO, FRANCE, "wood",  1)   # need 15 → fail
storage.set_resource(SERVER, SCENARIO, FRANCE, "stone", 5)   # need 25 → fail

result_hosp_no_res = buildings.start_construction(
    server_id         = SERVER,
    scenario_id       = SCENARIO,
    province_id       = "6",
    country_id        = FRANCE,
    building_type     = "Hospital",
    province_resource = "iron",
    current_day       = r_emi.end_day + 1,
    treasury          = treasury,
    technology        = tech,
    storage           = storage,
)
print(f"  France Hospital (no resources): allowed={result_hosp_no_res['allowed']}  "
      f"shortfalls={result_hosp_no_res.get('shortfalls')}")
chk(not result_hosp_no_res["allowed"],
    "Hospital blocked when resources insufficient")
gold_fr_unchanged = treasury.get(SERVER, SCENARIO, FRANCE)
chk(gold_fr_unchanged == 1000.0,
    "France treasury NOT debited when resources blocked construction")

# Reset the manual tech unlock used for the resource-gating test so France
# can go through the real research flow in Section 7.
db.upsert_technology(
    SERVER, SCENARIO, FRANCE, "early_modern_infrastructure",
    is_unlocked=False, is_researching=False,
)

sub("Research chain: Library tech → School tech → University tech")
# Fast-forward Germany through the library tech chain
day_lib_start = r_emi.end_day + 50

r_lib_tech = tech.start_research(
    SERVER, SCENARIO, GERMANY, "library", day_lib_start
)
chk(r_lib_tech.allowed, "library tech research starts (prereq met)")
print(f"  Library tech: end_day={r_lib_tech.end_day}")
tick.daily_tick(SERVER, SCENARIO, r_lib_tech.end_day, days_passed=0)
chk(tech.is_unlocked(SERVER, SCENARIO, GERMANY, "library"), "library tech unlocked")

r_sch_tech = tech.start_research(
    SERVER, SCENARIO, GERMANY, "school", r_lib_tech.end_day
)
chk(r_sch_tech.allowed, "school tech research starts")
tick.daily_tick(SERVER, SCENARIO, r_sch_tech.end_day, days_passed=0)
chk(tech.is_unlocked(SERVER, SCENARIO, GERMANY, "school"), "school tech unlocked")

# School building now unlocked → build it
sub("Build School (requires 'school' tech; 15 stone + 15 wood)")
result_school = buildings.start_construction(
    server_id         = SERVER,
    scenario_id       = SCENARIO,
    province_id       = "2",  # Munich
    country_id        = GERMANY,
    building_type     = "School",
    province_resource = "coal",
    current_day       = r_sch_tech.end_day + 1,
    treasury          = treasury,
    technology        = tech,
    storage           = storage,
)
print(f"  Build School: allowed={result_school['allowed']}  "
      f"resources_deducted={result_school.get('resources_deducted')}")
chk(result_school["allowed"], "School building starts (school tech unlocked)")
chk(result_school.get("resources_deducted", {}).get("stone", 0) == 15,
    "15 stone deducted for School")
chk(result_school.get("resources_deducted", {}).get("wood", 0) == 15,
    "15 wood deducted for School")


# ==============================================================================
#  SECTION 5 — RESEARCH SPEED WITH INFRA BUILDINGS (diminishing returns)
# ==============================================================================

hdr(5, "RESEARCH SPEED WITH INFRA BUILDINGS + DIMINISHING RETURNS")

# Complete the Library building (province 1, current_day trick)
lib_building = db.get_building(SERVER, SCENARIO, "1", "Library")
if lib_building:
    db.update_building_fields(SERVER, SCENARIO, "1", "Library", is_completed=1)

# Complete the School building (province 2)
sch_building = db.get_building(SERVER, SCENARIO, "2", "School")
if sch_building:
    db.update_building_fields(SERVER, SCENARIO, "2", "School", is_completed=1)

sub("Speed with Library (+0.5%) and School (+1%) — both in first 3 provinces")
spd_infra = tech.compute_research_speed(SERVER, SCENARIO, GERMANY)
print(f"  infra_bonus={spd_infra.infra_bonus:.4f}%  "
      f"final={spd_infra.final_speed:.4f}%")
print(f"  modifiers: {spd_infra.modifiers}")
# Library in prov 1 → 0.5% × 100% = 0.5%
# School in prov 2  → 1.0% × 100% = 1.0%
# Province 1 and 2 both in bracket 1 (rank ≤ 3 → 100%)
chk(abs(spd_infra.infra_bonus - 1.5) < 0.0001,
    "infra bonus = 1.5% (0.5 Library + 1.0 School, both 100% DR)")

sub("Add Library to prov 4 (rank 2 if prov 3 is empty → 50% DR)")
# Province 3 (Hamburg) has no infra building
# Province 4 (Frankfurt) will be rank 3 if 1+2 filled — let's add Library there
db.insert_building(
    server_id               = SERVER,
    scenario_id             = SCENARIO,
    province_id             = "3",
    country_id              = GERMANY,
    building_type           = "Library",
    resource_type           = None,
    construction_start_time = 1,
    construction_end_time   = 1,
    is_completed            = True,
)
# Now prov 1 = Library(rank1=100%), prov 2 = School(rank2=100%),
#      prov 3 = Library(rank3=100%)
spd_3prov = tech.compute_research_speed(SERVER, SCENARIO, GERMANY)
print(f"  3 provinces with infra: bonus={spd_3prov.infra_bonus:.4f}%")
# Library(0.5)×100% + School(1.0)×100% + Library(0.5)×100% = 2.0%
chk(abs(spd_3prov.infra_bonus - 2.0) < 0.0001,
    "infra bonus = 2.0% (first 3 provinces at 100% DR)")

# Add a 4th province with infra → bracket 2 (50% DR)
db.insert_building(
    server_id               = SERVER,
    scenario_id             = SCENARIO,
    province_id             = "4",
    country_id              = GERMANY,
    building_type           = "Library",
    resource_type           = None,
    construction_start_time = 1,
    construction_end_time   = 1,
    is_completed            = True,
)
spd_4prov = tech.compute_research_speed(SERVER, SCENARIO, GERMANY)
print(f"  4 provinces with infra: bonus={spd_4prov.infra_bonus:.4f}%")
# Library(0.5)×100% + School(1.0)×100% + Library(0.5)×100% + Library(0.5)×50%
# = 0.5 + 1.0 + 0.5 + 0.25 = 2.25%
chk(abs(spd_4prov.infra_bonus - 2.25) < 0.0001,
    "infra bonus = 2.25% (4th province at 50% DR)")

sub("War penalty: speed>3% AND in_active_war → -2%")
db.update_country_fields(SERVER, SCENARIO, GERMANY, in_active_war=1)
spd_war = tech.compute_research_speed(SERVER, SCENARIO, GERMANY)
print(f"  with war: pre-war={spd_war.base + spd_war.infra_bonus:.2f}%  "
      f"war_mod={spd_war.war_modifier:+.2f}%  final={spd_war.final_speed:.4f}%")
# base(1%) + infra(2.25%) = 3.25% > 3% → war penalty applies
chk(spd_war.war_modifier == -2.0, "war penalty -2% applied (speed was >3%)")
db.update_country_fields(SERVER, SCENARIO, GERMANY, in_active_war=0)


# ==============================================================================
#  SECTION 6 — REFORMS SYSTEM
# ==============================================================================

hdr(6, "REFORMS SYSTEM")

sub("Reform tree structure")
for rid, rdef in REFORM_TREE.items():
    print(f"  {rid:<35} {rdef.duration_months:>3}mo  "
          f"opinion={rdef.opinion_bonus:+d}  "
          f"eff={rdef.economy_efficiency_pct:+.0f}%")
chk(len(REFORM_TREE) == 8, "Reform tree has 8 reforms")

sub("Research and unlock Foundational Governance")
day_ref = r_sch_tech.end_day + 100
# Get current speed
current_speed = tech.compute_research_speed(SERVER, SCENARIO, GERMANY).final_speed

r_fg = reforms.start_research_reform(
    SERVER, SCENARIO, GERMANY, "foundational_governance",
    day_ref, research_speed_pct=current_speed
)
print(f"  Start foundational_governance: allowed={r_fg.allowed}  "
      f"end_day={r_fg.end_day}  speed={r_fg.speed_used:.2f}%")
chk(r_fg.allowed, "foundational_governance research starts")

# Tech research queue exclusivity while reform is being researched
r_univ = tech.start_research(
    SERVER, SCENARIO, GERMANY, "university", day_ref
)
chk(not r_univ.allowed, "cannot research tech while reform is in queue")
print(f"  Tech blocked by reform queue: {r_univ.reason}")

# Complete the reform
dt_ref = tick.daily_tick(SERVER, SCENARIO, r_fg.end_day, days_passed=0)
chk(len(dt_ref.reform_completions) == 1, "foundational_governance completes")
print(f"  Reform completed: {dt_ref.reform_completions[0].name}")

sub("Adopt foundational_governance — costs 100 gold")
gold_before_adopt = treasury.get(SERVER, SCENARIO, GERMANY)
adopt_r = reforms.adopt_reform(SERVER, SCENARIO, GERMANY, "foundational_governance")
print(f"  Adopt: allowed={adopt_r.allowed}  gold_spent={adopt_r.gold_spent:.0f}  "
      f"treasury_after={adopt_r.treasury_after:.2f}  adopted_count={adopt_r.adopted_count}")
chk(adopt_r.allowed, "foundational_governance adopted")
chk(adopt_r.gold_spent == REFORM_ADOPTION_COST, "100 gold spent on adoption")
chk(abs((gold_before_adopt - REFORM_ADOPTION_COST) - adopt_r.treasury_after) < 0.01,
    "treasury correctly decremented by adoption cost")

sub("Unlock + adopt National Identity Program (+2 opinion, -10% non-core cost)")
r_nip = reforms.start_research_reform(
    SERVER, SCENARIO, GERMANY, "national_identity_program",
    r_fg.end_day, research_speed_pct=current_speed
)
chk(r_nip.allowed, "national_identity_program research starts")
tick.daily_tick(SERVER, SCENARIO, r_nip.end_day, days_passed=0)
adopt_nip = reforms.adopt_reform(
    SERVER, SCENARIO, GERMANY, "national_identity_program"
)
chk(adopt_nip.allowed, "national_identity_program adopted")

sub("Unlock + adopt Women Rights (+5 opinion, -2% population growth)")
r_wr = reforms.start_research_reform(
    SERVER, SCENARIO, GERMANY, "women_rights",
    r_nip.end_day, research_speed_pct=current_speed
)
chk(r_wr.allowed, "women_rights research starts")
tick.daily_tick(SERVER, SCENARIO, r_wr.end_day, days_passed=0)
adopt_wr = reforms.adopt_reform(SERVER, SCENARIO, GERMANY, "women_rights")
chk(adopt_wr.allowed, "women_rights adopted (3rd slot)")

sub("Max 3 adopted reforms — 4th adoption blocked")
# Unlock War Mobilization Act
r_wma = reforms.start_research_reform(
    SERVER, SCENARIO, GERMANY, "war_mobilization_act",
    r_wr.end_day, research_speed_pct=current_speed
)
chk(r_wma.allowed, "war_mobilization_act research starts")
tick.daily_tick(SERVER, SCENARIO, r_wma.end_day, days_passed=0)

adopt_wma = reforms.adopt_reform(SERVER, SCENARIO, GERMANY, "war_mobilization_act")
print(f"  4th adoption attempt: allowed={adopt_wma.allowed}  reason={adopt_wma.reason}")
chk(not adopt_wma.allowed,
    f"4th adoption blocked (max {MAX_ADOPTED_REFORMS})")

sub("compute_effects — aggregate active reform bonuses")
effects = reforms.compute_effects(SERVER, SCENARIO, GERMANY)
print(f"  adopted reforms: {effects.adopted_reform_ids}")
print(f"  opinion_bonus: {effects.opinion_bonus}")
print(f"  economy_efficiency_pct: {effects.economy_efficiency_pct:+.0f}%")
print(f"  recruitment_cost_pct: {effects.recruitment_cost_pct:+.0f}%")
print(f"  population_growth_pct: {effects.population_growth_pct:+.2f}%")
print(f"  non_core_conversion_cost_pct: {effects.non_core_conversion_cost_pct:+.0f}%")
# Foundational Governance: 0 opinion bonus
# National Identity Program: +2 opinion, -10% non-core
# Women Rights: +5 opinion, -2% pop growth
chk(effects.opinion_bonus == 7, "total opinion bonus = 7 (0 + 2 + 5)")
chk(effects.population_growth_pct == -2.0, "pop growth -2% from Women Rights")
chk(effects.non_core_conversion_cost_pct == -10.0,
    "non-core conversion -10% from NIP")

sub("No Offence Policy cannot be adopted during war")
r_nop = reforms.start_research_reform(
    SERVER, SCENARIO, GERMANY, "no_offence_policy",
    r_wma.end_day, research_speed_pct=current_speed
)
chk(r_nop.allowed, "no_offence_policy research starts")
tick.daily_tick(SERVER, SCENARIO, r_nop.end_day, days_passed=0)

# Set Germany at war
db.update_country_fields(SERVER, SCENARIO, GERMANY, in_active_war=1)
# First unadopt one reform to free a slot
reforms.unadopt_reform(SERVER, SCENARIO, GERMANY, "foundational_governance")

adopt_nop_war = reforms.adopt_reform(SERVER, SCENARIO, GERMANY, "no_offence_policy")
print(f"  Adopt No Offence Policy during war: allowed={adopt_nop_war.allowed}  "
      f"reason={adopt_nop_war.reason}")
chk(not adopt_nop_war.allowed,
    "No Offence Policy cannot be adopted during war")
db.update_country_fields(SERVER, SCENARIO, GERMANY, in_active_war=0)

sub("No Offence Policy blocks war declaration when adopted")
adopt_nop = reforms.adopt_reform(SERVER, SCENARIO, GERMANY, "no_offence_policy")
chk(adopt_nop.allowed, "No Offence Policy adopted (peacetime)")
chk(reforms.is_war_declaration_blocked(SERVER, SCENARIO, GERMANY),
    "war declaration blocked by No Offence Policy")

sub("Central Banking System prerequisite: banking_system required")
r_cbs_direct = reforms.start_research_reform(
    SERVER, SCENARIO, FRANCE, "central_banking_system",
    1, research_speed_pct=1.0
)
print(f"  France central_banking_system (no prereq): "
      f"allowed={r_cbs_direct.allowed}  reason={r_cbs_direct.reason}")
chk(not r_cbs_direct.allowed,
    "central_banking_system blocked by missing banking_system prerequisite")


# ==============================================================================
#  SECTION 7 — TICK INTEGRATION (daily research completions)
# ==============================================================================

hdr(7, "TICK INTEGRATION — DAILY RESEARCH COMPLETIONS")

sub("Start research for France (University tech chain not yet unlocked → blocked)")
r_univ_fr = tech.start_research(SERVER, SCENARIO, FRANCE, "university", 1)
chk(not r_univ_fr.allowed,
    "university blocked for France (prerequisite chain not met)")
print(f"  Blocked: {r_univ_fr.reason}")

sub("France researches Early Modern Infrastructure then Library tech")
day_fr = 1
r_emi_fr = tech.start_research(
    SERVER, SCENARIO, FRANCE, "early_modern_infrastructure", day_fr
)
chk(r_emi_fr.allowed, "France starts early_modern_infrastructure")
dt_fr = tick.daily_tick(SERVER, SCENARIO, r_emi_fr.end_day, days_passed=0)
chk(len(dt_fr.tech_completions) >= 1, "France completes early_modern_infrastructure")
chk(tech.is_unlocked(
    SERVER, SCENARIO, FRANCE, "early_modern_infrastructure"
), "France has early_modern_infrastructure")

r_lib_fr = tech.start_research(
    SERVER, SCENARIO, FRANCE, "library", r_emi_fr.end_day
)
chk(r_lib_fr.allowed, "France starts library tech (prereq met)")
dt_lib_fr = tick.daily_tick(SERVER, SCENARIO, r_lib_fr.end_day, days_passed=0)
chk(len(dt_lib_fr.tech_completions) >= 1, "France completes library tech")

sub("DailyTickReport includes both tech and reform completions")
print(f"  tech_completions in last tick:   {len(dt_lib_fr.tech_completions)}")
print(f"  reform_completions in last tick: {len(dt_lib_fr.reform_completions)}")
print("  summary keys:", list(dt_lib_fr.summary().keys()))
chk("tech_completions" in dt_lib_fr.summary(), "summary includes tech_completions")
chk("reform_completions" in dt_lib_fr.summary(),
    "summary includes reform_completions")


# ==============================================================================
#  SECTION 8 — GLOBAL INVARIANT CHECKS
# ==============================================================================

hdr(8, "GLOBAL INVARIANT CHECKS")

for cid in [GERMANY, FRANCE]:
    t = treasury.get(SERVER, SCENARIO, cid)
    chk(t >= 0, f"{cid} treasury ≥ 0 (is {t:.2f})")

    stor = storage.get_all(SERVER, SCENARIO, cid)
    for res, amt in stor.items():
        chk(amt >= 0, f"{cid}.{res} storage ≥ 0 (is {amt})")

# All techs that are unlocked are properly flagged in DB
for cid in [GERMANY, FRANCE]:
    for tid in tech.get_unlocked_techs(SERVER, SCENARIO, cid):
        row = db.get_technology(SERVER, SCENARIO, cid, tid)
        chk(row is not None and bool(int(row["is_unlocked"])),
            f"{cid}.{tid} DB row is_unlocked=1")

# No country has more than one active research at a time
for cid in [GERMANY, FRANCE]:
    active_tech   = db.get_active_research(SERVER, SCENARIO, cid)
    active_reform = db.get_active_reform_research(SERVER, SCENARIO, cid)
    chk(
        not (active_tech and active_reform),
        f"{cid}: not simultaneously researching tech AND reform"
    )

# All adopted reforms ≤ MAX_ADOPTED_REFORMS
for cid in [GERMANY, FRANCE]:
    adopted = db.get_adopted_reforms(SERVER, SCENARIO, cid)
    chk(
        len(adopted) <= MAX_ADOPTED_REFORMS,
        f"{cid}: adopted reforms ({len(adopted)}) ≤ {MAX_ADOPTED_REFORMS}"
    )

print(f"\n{SEPARATOR}")
print("  Technology System demo COMPLETE — all assertions passed.")
print(SEPARATOR)
