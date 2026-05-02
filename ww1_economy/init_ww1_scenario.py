"""
WW1 SCENARIO INITIALIZER — Phase 2
------------------------------------
Updates existing countries with economic stats and religion,
initialises all-pairs diplomacy relations (50 each),
and grants tier-appropriate technology unlocks.

Run with:
    python3 -m ww1_economy.init_ww1_scenario

Rules followed:
  * Uses server_id="guild_demo", scenario_id="ww1", DB="ww1_scenario.db"
  * Identifies countries by country_id (no name-based lookup).
  * Does NOT create or delete countries or provinces.
  * Relations are only written if they do not already exist.
  * economy_efficiency 100 (%) → stored as 1.0 in DB.
  * daily_income → daily_base_income column.
  * tax_level "Standard Taxation" → tax_multiplier = 1.0.
  * "Hospital", "Powder Mill", "Pharmaceutical Plant" are buildings
    unlocked by tech, not tech IDs — they are not written here.
  * "Banks" maps to reform_id "banking_system".
  * Parent military techs (early_infantry, cavalry, support_units) are
    always unlocked alongside their children.
"""

from __future__ import annotations

import itertools
import os

from ww1_economy.db import EconomyDB

SERVER_ID   = "guild_demo"
SCENARIO_ID = "ww1"
DEFAULT_DB  = os.environ.get("WW1_DB_PATH", "ww1_scenario.db")

# ---------------------------------------------------------------------------
# Country configuration
# ---------------------------------------------------------------------------

COUNTRY_CONFIG: list[dict] = [
    # Tier 1
    dict(country_id="germany",         religion="Protestant Christian",  treasury=600.0, daily_income=8.0, opinion=70, tier=1),
    dict(country_id="united_kingdom",  religion="Protestant Christian",  treasury=500.0, daily_income=7.0, opinion=55, tier=1),
    dict(country_id="france",          religion="Atheism",               treasury=320.0, daily_income=5.0, opinion=60, tier=1),
    # Tier 2
    dict(country_id="russian_empire",  religion="Orthodox Christian",    treasury=400.0, daily_income=4.0, opinion=50, tier=2),
    dict(country_id="austrian_empire", religion="Catholic Christian",    treasury=400.0, daily_income=5.0, opinion=45, tier=2),
    dict(country_id="italy",           religion="Catholic Christian",    treasury=200.0, daily_income=3.0, opinion=60, tier=2),
    # Tier 3
    dict(country_id="ottoman",         religion="Sunni Islam",           treasury=230.0, daily_income=3.0, opinion=45, tier=3),
    dict(country_id="netherlands",     religion="Protestant Christian",  treasury=150.0, daily_income=3.0, opinion=55, tier=3),
    dict(country_id="denmark",         religion="Protestant Christian",  treasury=120.0, daily_income=2.0, opinion=50, tier=3),
    dict(country_id="sweden",          religion="Protestant Christian",  treasury=180.0, daily_income=3.0, opinion=45, tier=3),
    dict(country_id="spain",           religion="Catholic Christian",    treasury=200.0, daily_income=2.0, opinion=60, tier=3),
    dict(country_id="belgium",         religion="Catholic Christian",    treasury=180.0, daily_income=3.0, opinion=60, tier=3),
    dict(country_id="switzerland",     religion="Protestant Christian",  treasury=230.0, daily_income=4.0, opinion=70, tier=3),
    dict(country_id="romania",         religion="Orthodox Christian",    treasury=200.0, daily_income=3.0, opinion=50, tier=3),
    # Tier 4
    dict(country_id="portugal",        religion="Catholic Christian",    treasury=180.0, daily_income=3.0, opinion=50, tier=4),
    dict(country_id="norway",          religion="Protestant Christian",  treasury=120.0, daily_income=1.0, opinion=45, tier=4),
    dict(country_id="albania",         religion="Sunni Islam",           treasury=80.0,  daily_income=1.0, opinion=35, tier=4),
    dict(country_id="bulgaria",        religion="Orthodox Christian",    treasury=120.0, daily_income=2.0, opinion=40, tier=4),
    dict(country_id="serbia",          religion="Orthodox Christian",    treasury=80.0,  daily_income=1.0, opinion=40, tier=4),
    dict(country_id="greece",          religion="Orthodox Christian",    treasury=100.0, daily_income=2.0, opinion=50, tier=4),
]

# ---------------------------------------------------------------------------
# Technology tier definitions
# ---------------------------------------------------------------------------

# Economic / infrastructure technologies (technologies table)
ECON_TECHS: dict[int, list[str]] = {
    1: ["industrialization", "chemical_processing",
        "early_modern_infrastructure", "library", "school"],
    2: ["industrialization",
        "early_modern_infrastructure", "library"],
    3: ["industrialization",
        "early_modern_infrastructure", "library"],
    4: ["industrialization", "chemical_processing",
        "early_modern_infrastructure", "library"],
    # Note: "Hospital" = a building (unlocked by early_modern_infrastructure)
    #       "Powder Mill" / "Pharmaceutical Plant" = buildings (unlocked by
    #       chemical_processing). Not tech IDs — handled by the building system.
}

# Reforms (reforms table, marked is_adopted=True)
# "Banks" in the spec → banking_system reform ID
REFORM_TECHS: dict[int, list[str]] = {
    1: ["foundational_governance", "national_identity_program", "banking_system"],
    2: ["foundational_governance", "war_mobilization_act"],
    3: ["foundational_governance"],
    4: ["foundational_governance"],
}

# Military technologies (military_technologies table)
# Parent techs (early_infantry, cavalry, support_units) are always included
# alongside their children so prerequisite checks always pass.
MILITARY_TECHS: dict[int, list[str]] = {
    1: [
        "pre_industrial_military_doctrine",
        # Infantry line (parent + all children)
        "early_infantry", "line_infantry", "elite_line_infantry",
        "grenadier", "elite_grenadier",
        # Cavalry line
        "cavalry", "heavy_cavalry", "elite_cavalry",
        # Support line
        "support_units", "elite_archers", "recon_rifleman",
        "cannons", "elite_cannons",
        # Naval
        "naval_warfare_doctrine", "gunboats", "early_battleships", "battleships",
        # Modern
        "modern_warfare_doctrine", "rifleman", "early_trench_infantry",
    ],
    2: [
        "pre_industrial_military_doctrine",
        "early_infantry", "line_infantry", "elite_line_infantry",
        "grenadier", "elite_grenadier",
        "cavalry", "heavy_cavalry", "elite_cavalry",
        "support_units", "elite_archers", "recon_rifleman",
        "cannons", "elite_cannons",
        "naval_warfare_doctrine", "gunboats", "early_battleships", "battleships",
        "modern_warfare_doctrine", "rifleman",
    ],
    3: [
        "pre_industrial_military_doctrine",
        "early_infantry", "line_infantry", "elite_line_infantry",
        "cavalry", "heavy_cavalry", "elite_cavalry",
        "support_units", "elite_archers",
        "cannons", "elite_cannons",
        "naval_warfare_doctrine", "gunboats", "early_battleships",
    ],
    4: [
        "pre_industrial_military_doctrine",
        "early_infantry", "line_infantry", "elite_line_infantry", "grenadier",
        "cavalry", "heavy_cavalry",
        "support_units", "elite_archers",
        "cannons",
        "naval_warfare_doctrine", "gunboats",
    ],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(n: int) -> str:
    return f"{n:>5,}"


def _sep(title: str) -> None:
    w = 68
    print(f"\n{'─' * w}")
    print(f"  {title}")
    print(f"{'─' * w}")


# ---------------------------------------------------------------------------
# Main initialisation
# ---------------------------------------------------------------------------

def initialise(db: EconomyDB,
               server_id:   str = SERVER_ID,
               scenario_id: str = SCENARIO_ID) -> None:

    all_ids = [c["country_id"] for c in COUNTRY_CONFIG]

    # ------------------------------------------------------------------
    # 1. Country economic stats + storage
    # ------------------------------------------------------------------
    _sep("1 — Country stats & religion")
    for c in COUNTRY_CONFIG:
        cid = c["country_id"]
        existing = db.get_country(server_id, scenario_id, cid)
        if existing is None:
            print(f"  SKIP (not found): {cid}")
            continue

        db.update_country_fields(
            server_id, scenario_id, cid,
            treasury          = c["treasury"],
            daily_base_income = c["daily_income"],
            economy_efficiency= 1.0,          # 100 % → 1.0 in DB
            population_opinion= c["opinion"],
            tax_multiplier    = 1.0,          # Standard Taxation
            in_active_war     = 0,
            unrest            = 0.0,
        )
        db.upsert_country_religion(server_id, scenario_id, cid, c["religion"])
        db.get_or_create_storage(server_id, scenario_id, cid)
        print(f"  ✓ {cid:<22}  tier={c['tier']}  "
              f"treasury={c['treasury']:>6.0f}  "
              f"religion={c['religion']}")

    # ------------------------------------------------------------------
    # 2. Diplomacy — all pairs at 50 (skip if already set)
    # ------------------------------------------------------------------
    _sep("2 — Diplomacy relations (all pairs → 50)")
    inserted = skipped = 0
    for a, b in itertools.combinations(all_ids, 2):
        existing = db.get_relation(server_id, scenario_id, a, b)
        if existing is None:
            db.upsert_relation(server_id, scenario_id, a, b, base_relation=50.0)
            inserted += 1
        else:
            skipped += 1
    total_pairs = inserted + skipped
    print(f"  Inserted: {inserted:>4}  Skipped (already set): {skipped:>4}"
          f"  Total pairs: {total_pairs:>4}")

    # ------------------------------------------------------------------
    # 3. Technologies
    # ------------------------------------------------------------------
    _sep("3 — Technology unlocks")
    econ_total = reform_total = mil_total = 0

    for c in COUNTRY_CONFIG:
        cid  = c["country_id"]
        tier = c["tier"]

        # Economic / infrastructure
        for tid in ECON_TECHS[tier]:
            db.upsert_technology(
                server_id, scenario_id, cid, tid,
                is_unlocked=True,
            )
            econ_total += 1

        # Reforms (unlocked + adopted)
        for rid in REFORM_TECHS[tier]:
            db.upsert_reform(
                server_id, scenario_id, cid, rid,
                is_unlocked=True,
                is_adopted=True,
            )
            reform_total += 1

        # Military
        for mid in MILITARY_TECHS[tier]:
            db.upsert_military_technology(
                server_id, scenario_id, cid, mid,
                is_unlocked=True,
            )
            mil_total += 1

    print(f"  Economic/infra unlocks : {econ_total:>5}")
    print(f"  Reform unlocks         : {reform_total:>5}")
    print(f"  Military unlocks       : {mil_total:>5}")
    print(f"  Total tech writes      : {econ_total + reform_total + mil_total:>5}")


# ---------------------------------------------------------------------------
# Verification report
# ---------------------------------------------------------------------------

def verify(db: EconomyDB,
           server_id:   str = SERVER_ID,
           scenario_id: str = SCENARIO_ID) -> None:
    _sep("VERIFICATION REPORT")

    all_ids = [c["country_id"] for c in COUNTRY_CONFIG]
    issues: list[str] = []

    print(f"\n  {'country_id':<22} {'tier':>4}  {'treasury':>8}  "
          f"{'eff':>5}  {'opinion':>7}  {'econ':>5}  "
          f"{'reform':>6}  {'mil':>5}  {'rel_rows':>8}")
    print(f"  {'─'*22}  {'─'*4}  {'─'*8}  {'─'*5}  "
          f"{'─'*7}  {'─'*5}  {'─'*6}  {'─'*5}  {'─'*8}")

    for c in COUNTRY_CONFIG:
        cid  = c["country_id"]
        tier = c["tier"]
        row  = db.get_country(server_id, scenario_id, cid)
        if row is None:
            issues.append(f"{cid}: country row missing!")
            continue

        eff       = row.get("economy_efficiency", 0)
        opinion   = row.get("population_opinion", 0)
        treasury  = row.get("treasury", 0)

        econ_rows  = db.get_technologies_for_country(server_id, scenario_id, cid)
        unlocked_e = sum(1 for r in econ_rows if r["is_unlocked"])

        reform_rows = db.get_reforms_for_country(server_id, scenario_id, cid)
        adopted_r   = sum(1 for r in reform_rows if r["is_adopted"])

        mil_rows   = db.get_military_technologies_for_country(server_id, scenario_id, cid)
        unlocked_m = sum(1 for r in mil_rows if r["is_unlocked"])

        # Count relation rows involving this country
        rel_count = sum(
            1 for other in all_ids
            if other != cid and db.get_relation(server_id, scenario_id, cid, other) is not None
        )

        expected_econ   = len(ECON_TECHS[tier])
        expected_reform = len(REFORM_TECHS[tier])
        expected_mil    = len(MILITARY_TECHS[tier])

        if unlocked_e < expected_econ:
            issues.append(f"{cid}: expected {expected_econ} econ techs, got {unlocked_e}")
        if adopted_r < expected_reform:
            issues.append(f"{cid}: expected {expected_reform} reforms adopted, got {adopted_r}")
        if unlocked_m < expected_mil:
            issues.append(f"{cid}: expected {expected_mil} mil techs, got {unlocked_m}")
        if abs(float(eff) - 1.0) > 0.01:
            issues.append(f"{cid}: economy_efficiency={eff} (expected 1.0)")
        if rel_count < len(all_ids) - 1:
            issues.append(f"{cid}: only {rel_count} relation rows (expected {len(all_ids)-1})")

        status = "OK" if not [i for i in issues if i.startswith(cid)] else "!!"
        print(f"  {cid:<22} {tier:>4}  {treasury:>8.0f}  "
              f"{eff:>5.2f}  {opinion:>7}  "
              f"{unlocked_e:>5}  {adopted_r:>6}  {unlocked_m:>5}  {rel_count:>8}  "
              f"[{status}]")

    _sep("RESULT")
    if issues:
        print(f"  {len(issues)} issue(s) found:")
        for issue in issues:
            print(f"    ✗ {issue}")
    else:
        print("  All checks passed — scenario ready.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    db = EconomyDB(DEFAULT_DB)
    db.init()

    print(f"\nDB : {DEFAULT_DB}")
    print(f"SRV: {SERVER_ID}   SCEN: {SCENARIO_ID}")

    # Check that seed data exists first
    countries = db.get_all_countries(SERVER_ID, SCENARIO_ID)
    print(f"\nFound {len(countries)} existing country rows in DB.")
    if not countries:
        print("\nWARNING: No countries found. Run seed_ww1.py first:\n"
              "    python3 -m ww1_economy.seed_ww1\n")

    initialise(db)
    verify(db)


if __name__ == "__main__":
    main()
