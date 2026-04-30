"""
WW1 SCENARIO SEED — STATIC BASE DATA
-------------------------------------
Inserts the canonical WW1 country and province dataset into the
``countries`` and ``provinces`` tables for ``scenario_id = "ww1"``.

Rules followed (per task spec):
  * province_id integers preserved EXACTLY (gaps allowed, e.g. no 025).
  * province_name = original base name + zero-padded 3-digit province_id.
  * resource_type preserved EXACTLY (no spelling fixes).
  * population preserved EXACTLY (stored in absolute people; "5000k" -> 5_000_000).
  * Country total_population = SUM of its provinces (computed, not the listed total).
  * country_id is lowercase with underscores; spaces removed.

Run with:
    python3 -m ww1_economy.seed_ww1
"""

from __future__ import annotations

import os
import random
from typing import NamedTuple

from ww1_economy.db import EconomyDB


SERVER_ID   = "guild_demo"
SCENARIO_ID = "ww1"
DEFAULT_DB  = os.environ.get("WW1_DB_PATH", "ww1_scenario.db")


class ProvinceSeed(NamedTuple):
    province_id:   int
    base_name:     str   # name WITHOUT the 3-digit suffix
    resource_type: str
    population_k:  int   # population expressed in thousands ("k")


class CountrySeed(NamedTuple):
    country_id:   str
    country_name: str
    provinces:    list[ProvinceSeed]


# ---------------------------------------------------------------------------
# Static dataset — exact spellings preserved
# ---------------------------------------------------------------------------

SCENARIO_DATA: list[CountrySeed] = [
    CountrySeed("germany", "Germany", [
        ProvinceSeed(  1, "Rhineland",            "coal",   5000),
        ProvinceSeed(  2, "Ruhr",                 "iron",   6000),
        ProvinceSeed(  3, "Saarland",             "coal",   1200),
        ProvinceSeed(  4, "Silesia",              "iron",   4000),
        ProvinceSeed(  5, "Saxony",               "cotton", 3500),
        ProvinceSeed(  6, "Berlin",               "gold",   3000),
        ProvinceSeed(  7, "Bavaria",              "grain",  5000),
        ProvinceSeed(  8, "Wurtemmberg",          "meat",   2500),
        ProvinceSeed(  9, "Baden",                "grain",  2200),
        ProvinceSeed( 10, "East prussia",         "grain",  2000),
        ProvinceSeed( 11, "Hanover",              "wood",   3000),
        ProvinceSeed( 12, "Pomerania",            "wood",   1800),
        ProvinceSeed( 13, "Thuringa",             "copper", 2500),
        ProvinceSeed( 14, "Hesse",                "iron",   2800),
        ProvinceSeed( 15, "Mecklenburg",          "horses", 1000),
        ProvinceSeed( 16, "Schleswien holstein",  "cotton", 1500),
    ]),

    CountrySeed("russian_empire", "Russian Empire", [
        ProvinceSeed( 17, "Ukraine",          "grain",  12000),
        ProvinceSeed( 18, "Keiv",             "grain",   8000),
        ProvinceSeed( 19, "Don region",       "meat",    6000),
        ProvinceSeed( 20, "Belarus",          "grain",   5000),
        ProvinceSeed( 21, "Baltic region",    "grain",   4000),
        ProvinceSeed( 22, "Northern russia",  "wood",    3000),
        ProvinceSeed( 23, "Caucasus",         "oil",     5000),
        ProvinceSeed( 24, "Baku",             "oil",     2000),
        # NOTE: id 025 intentionally absent in source dataset
        ProvinceSeed( 26, "Western siberia",  "wood",    3000),
        ProvinceSeed( 27, "Central steppe",   "horses",  4000),
        ProvinceSeed( 28, "St Petersburg",    "iron",    3000),
        ProvinceSeed( 29, "Moscow",           "stone",   6000),
        ProvinceSeed( 30, "Perm",             "coal",    2000),
        ProvinceSeed( 31, "Ural mountains",   "iron",    2500),
        ProvinceSeed( 32, "Karelia",          "wood",    1500),
        ProvinceSeed( 33, "Arkhangelsk",      "gems",    1000),
        ProvinceSeed( 34, "Donbass",          "coal",    5000),
        ProvinceSeed( 35, "Volga",            "grain",   7000),
        ProvinceSeed( 36, "Lapland",          "stone",    500),
        ProvinceSeed( 37, "Kazan",            "stone",   3000),
        ProvinceSeed( 38, "Kursk",            "horses",  2500),
        ProvinceSeed( 39, "Kaluga",           "rubber",  2000),
        ProvinceSeed( 40, "Komi",             "copper",  1000),
    ]),

    CountrySeed("united_kingdom", "United Kingdom", [
        ProvinceSeed( 41, "wales",                "coal",   2500),
        ProvinceSeed( 42, "ireland",              "wood",   4000),
        ProvinceSeed( 43, "Yorkshire",            "coal",   3500),
        ProvinceSeed( 44, "Lancashire",           "cotton", 4000),
        ProvinceSeed( 45, "Midlands",             "iron",   5000),
        ProvinceSeed( 46, "South West England",   "meat",   2500),
        ProvinceSeed( 47, "Scottish highlands",   "meat",   1000),
        ProvinceSeed( 48, "Scottish lowlands",    "iron",   2000),
        ProvinceSeed( 49, "Central england",      "horses", 6000),
        ProvinceSeed( 50, "Portsmouth",           "oil",    1500),
        ProvinceSeed( 51, "London",               "wood",   7000),
        ProvinceSeed( 52, "East angila",          "grain",  2000),
    ]),

    CountrySeed("ottoman", "Ottoman", [
        ProvinceSeed( 53, "Istanbul",             "stone",  1500),
        ProvinceSeed( 54, "Istanbul",             "wood",   1500),
        ProvinceSeed( 55, "Western anatolia",     "meat",   2000),
        ProvinceSeed( 56, "Anatolian highlands",  "coal",   1800),
        ProvinceSeed( 57, "Central anatolia",     "grain",  2000),
        ProvinceSeed( 58, "Eastern anatolia",     "wood",   1200),
        ProvinceSeed( 59, "Mesopotamia",          "oil",    1500),
        ProvinceSeed( 60, "Palestine",            "cotton",  800),
        ProvinceSeed( 61, "Syria",                "grain",  1200),
        ProvinceSeed( 62, "Cyprus",               "copper",  300),
        ProvinceSeed( 63, "Hejaz",                "oil",     500),
        ProvinceSeed( 64, "Izmir",                "cotton", 1000),
        ProvinceSeed( 65, "Macadonia",            "grain",  1200),
        ProvinceSeed( 66, "Black sea coast",      "coal",   1500),
        ProvinceSeed( 67, "Thrace",               "iron",   1500),
    ]),

    CountrySeed("austrian_empire", "Austrian Empire", [
        ProvinceSeed( 68, "Vienna",          "coal",   2500),
        ProvinceSeed( 69, "Hungary",         "grain",  8000),
        ProvinceSeed( 70, "Translyvania",    "grain",  4000),
        ProvinceSeed( 71, "Galicia",         "grain",  5000),
        ProvinceSeed( 72, "Croatia",         "meat",   2000),
        ProvinceSeed( 73, "Slovenia",        "grain",  1500),
        ProvinceSeed( 74, "Bohemia",         "rubber", 6000),
        ProvinceSeed( 75, "Slovakia",        "horses", 3000),
        ProvinceSeed( 76, "Upperaustria",    "coal",   2500),
        ProvinceSeed( 77, "Lower austria",   "iron",   3000),
        ProvinceSeed( 78, "Moravia",         "iron",   3500),
        ProvinceSeed( 79, "Bosnia",          "wood",   1500),
        ProvinceSeed( 80, "Banat",           "iron",   2500),
        ProvinceSeed( 81, "Tyrol",           "gems",   1000),
    ]),

    CountrySeed("france", "France", [
        ProvinceSeed( 82, "Brittany",            "meat",   2000),
        ProvinceSeed( 83, "Normandy",            "grain",  2500),
        ProvinceSeed( 84, "Aquitaine",           "grain",  3000),
        ProvinceSeed( 85, "Burgundy",            "meat",   2000),
        ProvinceSeed( 86, "Paris",               "copper", 5000),
        ProvinceSeed( 87, "Nord pas de calais",  "coal",   3000),
        ProvinceSeed( 88, "Lorraine",            "iron",   2000),
        ProvinceSeed( 89, "Alsace",              "iron",   2000),
        ProvinceSeed( 90, "Rhone alps",          "coal",   3500),
        ProvinceSeed( 91, "Central france",      "wood",   2500),
        ProvinceSeed( 92, "Pyrenees",            "stone",  1500),
        ProvinceSeed( 93, "Occitania",           "grain",  3000),
        ProvinceSeed( 94, "Pays de la loire",    "grain",  2500),
        ProvinceSeed( 95, "Poitou charentes",    "rubber", 2000),
        ProvinceSeed( 96, "Corsica",             "wood",    500),
    ]),

    CountrySeed("italy", "Italy", [
        ProvinceSeed( 97, "Lombardy",        "iron",   3500),
        ProvinceSeed( 98, "Piedmont",        "iron",   2500),
        ProvinceSeed( 99, "Veneto",          "cotton", 2500),
        ProvinceSeed(100, "Emilia romagna",  "grain",  3000),
        ProvinceSeed(101, "Tuscany",         "rubber", 2500),
        ProvinceSeed(102, "Rome",            "stone",  2000),
        ProvinceSeed(103, "Umbria",          "stone",  1000),
        ProvinceSeed(104, "Campania",        "meat",   3000),
        ProvinceSeed(105, "Apulia",          "grain",  2000),
        ProvinceSeed(106, "Calabria",        "wood",   1500),
        ProvinceSeed(107, "Silcisy",         "cotton", 2500),
        ProvinceSeed(108, "Sardinia",        "stone",  1000),
        ProvinceSeed(109, "Northern alps",   "horses",  800),
        ProvinceSeed(110, "Abruzzo",         "grain",  1200),
        ProvinceSeed(111, "Basilicata",      "oil",     800),
    ]),

    CountrySeed("greece", "Greece", [
        ProvinceSeed(112, "Crete",           "cotton",  800),
        ProvinceSeed(113, "Peloponnese",     "meat",   1500),
        ProvinceSeed(114, "Thessaly",        "grain",  1500),
        ProvinceSeed(115, "Central greece",  "grain",  2000),
        ProvinceSeed(116, "Athens",          "stone",  2200),
    ]),

    CountrySeed("serbia", "Serbia", [
        ProvinceSeed(117, "Belgrade",         "grain",  1500),
        ProvinceSeed(118, "Southern serbia",  "horses", 2000),
        ProvinceSeed(119, "Montenegaro",      "stone",  1000),
    ]),

    CountrySeed("bulgaria", "Bulgaria", [
        ProvinceSeed(120, "Sofia",             "grain",  2000),
        ProvinceSeed(121, "Plovdiv",           "meat",   1500),
        ProvinceSeed(122, "Western bulgaria",  "iron",    800),
        ProvinceSeed(123, "Varna",             "cotton",  700),
    ]),

    CountrySeed("romania", "Romania", [
        ProvinceSeed(124, "BTranslyvania",     "wood",   2000),
        ProvinceSeed(125, "Moldavia",          "grain",  2000),
        ProvinceSeed(126, "Wallachia",         "meat",   2000),
        ProvinceSeed(127, "Bucharest",         "gold",   1500),
        ProvinceSeed(128, "Ploiești Region",   "oil",    1000),
    ]),

    CountrySeed("albania", "Albania", [
        ProvinceSeed(129, "Tirana",            "grain",   800),
        ProvinceSeed(130, "Northern Albania",  "wood",    700),
    ]),

    CountrySeed("belgium", "Belgium", [
        ProvinceSeed(131, "Brussels",    "wood",    2000),
        ProvinceSeed(132, "Flanders",    "meat",    3000),
        ProvinceSeed(133, "Wallonia",    "coal",    2000),
        ProvinceSeed(134, "Luxembourg",  "copper",   500),
    ]),

    CountrySeed("netherlands", "Netherlands", [
        ProvinceSeed(135, "Amsterdam",            "gold",   2000),
        ProvinceSeed(136, "Rotterdam",            "rubber", 2000),
        ProvinceSeed(137, "Northern Netherlands", "grain",  2000),
    ]),

    CountrySeed("denmark", "Denmark", [
        ProvinceSeed(138, "Copenhagen",  "copper", 1500),
        ProvinceSeed(139, "Jutland",     "grain",  1000),
        ProvinceSeed(140, "Funen",       "meat",    500),
    ]),

    CountrySeed("sweden", "Sweden", [
        ProvinceSeed(141, "Stockholm",   "gold",   1500),
        ProvinceSeed(142, "Gotaland",    "grain",  1500),
        ProvinceSeed(143, "Svealand",    "iron",   1200),
        ProvinceSeed(144, "Scania",      "meat",   1000),
        ProvinceSeed(145, "Bergslagen",  "coal",    800),
        ProvinceSeed(146, "Norrland",    "wood",    500),
    ]),

    CountrySeed("norway", "Norway", [
        ProvinceSeed(147, "Oslo",             "gems",  800),
        ProvinceSeed(148, "Southern Norway",  "wood",  700),
        ProvinceSeed(149, "Western Norway",   "meat",  600),
        ProvinceSeed(150, "Northern Norway",  "coal",  400),
    ]),

    CountrySeed("spain", "Spain", [
        ProvinceSeed(151, "Andalusia",      "grain",  4000),
        ProvinceSeed(152, "Catalonia",      "rubber", 3000),
        ProvinceSeed(153, "Galicia",        "wood",   2500),
        ProvinceSeed(154, "Basque Region",  "iron",   2000),
        ProvinceSeed(155, "Valencia",       "cotton", 2500),
        ProvinceSeed(156, "Madrid",         "copper", 3000),
    ]),

    CountrySeed("portugal", "Portugal", [
        ProvinceSeed(157, "Algarve",            "meat",   1000),
        ProvinceSeed(158, "Alentejo",           "grain",  1500),
        ProvinceSeed(159, "Lisbon",             "iron",   2500),
        ProvinceSeed(160, "Northern Portugal",  "cotton", 1000),
    ]),

    CountrySeed("switzerland", "Switzerland", [
        ProvinceSeed(161, "Zurich", "gold", 3500),
    ]),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_province_name(base_name: str, province_id: int) -> str:
    """Append the zero-padded 3-digit province_id to the base name."""
    return f"{base_name}{province_id:03d}"


def country_total_population(country: CountrySeed) -> int:
    """Sum of all province populations for the country (in absolute people)."""
    return sum(p.population_k for p in country.provinces) * 1_000


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def seed(db: EconomyDB, server_id: str = SERVER_ID,
         scenario_id: str = SCENARIO_ID) -> dict:
    """
    Insert all countries (with computed total_population), then all provinces.
    Uses upserts so re-running is idempotent.
    Returns a small summary dict for the caller to print.
    """
    # 1. Countries first
    for country in SCENARIO_DATA:
        total = country_total_population(country)
        db.upsert_country(
            server_id        = server_id,
            scenario_id      = scenario_id,
            country_id       = country.country_id,
            country_name     = country.country_name,
            total_population = total,
        )

    # 2. Provinces second
    province_count = 0
    for country in SCENARIO_DATA:
        for prov in country.provinces:
            db.upsert_province(
                server_id     = server_id,
                scenario_id   = scenario_id,
                province_id   = prov.province_id,
                province_name = format_province_name(prov.base_name, prov.province_id),
                owner_country = country.country_id,
                resource_type = prov.resource_type,
                population    = prov.population_k * 1_000,
            )
            province_count += 1

    return {
        "countries_inserted": len(SCENARIO_DATA),
        "provinces_inserted": province_count,
    }


# ---------------------------------------------------------------------------
# CLI / report
# ---------------------------------------------------------------------------

def _separator(title: str) -> None:
    width = 72
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def _format_pop(n: int) -> str:
    return f"{n:>14,}"


def main() -> None:
    db = EconomyDB(DEFAULT_DB)
    db.init()

    # Reset scenario tables so the seed is clean and reproducible.
    db.delete_scenario_provinces(SERVER_ID, SCENARIO_ID)
    db.delete_scenario_countries(SERVER_ID, SCENARIO_ID)

    _separator(f"SEEDING SCENARIO  server_id={SERVER_ID!r}  "
               f"scenario_id={SCENARIO_ID!r}")
    print(f"Database file: {DEFAULT_DB}")

    summary = seed(db)
    print(f"\nInserted {summary['countries_inserted']} countries "
          f"and {summary['provinces_inserted']} provinces.")

    # ------------------------------------------------------------------
    # 7a. All countries with total_population
    # ------------------------------------------------------------------
    _separator("ALL COUNTRIES (total_population = sum of provinces)")
    countries = db.get_all_countries(SERVER_ID, SCENARIO_ID)

    print(f"{'country_id':<20} {'country_name':<22} {'total_population':>16}  "
          f"{'#provs':>7}")
    print("-" * 72)
    grand_total = 0
    for c in countries:
        provs = db.get_provinces_by_country(SERVER_ID, SCENARIO_ID, c["country_id"])
        grand_total += c["total_population"]
        print(
            f"{c['country_id']:<20} "
            f"{c['country_name']:<22} "
            f"{_format_pop(c['total_population'])}  "
            f"{len(provs):>7}"
        )
    print("-" * 72)
    print(f"{'TOTAL':<20} {'':<22} {_format_pop(grand_total)}")

    # ------------------------------------------------------------------
    # 7b. Total province count
    # ------------------------------------------------------------------
    all_provs = db.get_all_provinces(SERVER_ID, SCENARIO_ID)
    _separator("PROVINCE COUNT")
    print(f"Total provinces inserted: {len(all_provs)}")

    # ------------------------------------------------------------------
    # 7c. 10 random provinces as a sample
    # ------------------------------------------------------------------
    _separator("SAMPLE — 10 RANDOM PROVINCES")
    random.seed(42)  # reproducible sample
    sample = random.sample(all_provs, k=min(10, len(all_provs)))
    print(f"{'id':>5}  {'province_name':<26} {'owner_country':<18} "
          f"{'resource':<10} {'population':>14}")
    print("-" * 80)
    for p in sample:
        print(
            f"{p['province_id']:>5}  "
            f"{p['province_name']:<26} "
            f"{p['owner_country']:<18} "
            f"{p['resource_type']:<10} "
            f"{p['population']:>14,}"
        )

    _separator("SEED COMPLETE")


if __name__ == "__main__":
    main()
