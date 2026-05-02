"""
Read/write helpers that bridge the Discord bot with ww1_scenario.db.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

DB_PATH     = os.environ.get("WW1_DB_PATH", "ww1_scenario.db")
SERVER_ID   = "guild_demo"
SCENARIO_ID = "ww1"

RELIGION_EMOJI: dict[str, str] = {
    "Protestant Christian": "✝️",
    "Catholic Christian":   "⛪",
    "Orthodox Christian":   "☦️",
    "Sunni Islam":          "☪️",
    "Atheism":              "🔬",
    "Judaism":              "✡️",
    "Hinduism":             "🕉️",
}

RESOURCE_EMOJI: dict[str, str] = {
    "coal": "🪨", "iron": "⚙️", "gold": "🪙", "grain": "🌾",
    "meat": "🥩", "wood": "🪵", "oil": "🛢️", "cotton": "🧶",
    "rubber": "🧪", "copper": "🔶", "horses": "🐎", "stone": "🪨",
    "gems": "💎",
}

STORABLE_RESOURCES = [
    "iron","coal","copper","stone","wood","rubber","grain","meat",
    "horses","cotton","oil","gems","textiles","chemicals",
    "gunpowder","ammunition","medicines",
]


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def _write_conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# ── Countries ─────────────────────────────────────────────────────────────────

def get_countries() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT country_id, country_name, total_population, "
            "       treasury, daily_base_income, population_growth_rate "
            "FROM countries "
            "WHERE server_id=? AND scenario_id=? ORDER BY country_name",
            (SERVER_ID, SCENARIO_ID),
        ).fetchall()
        result = []
        for r in rows:
            rel = con.execute(
                "SELECT religion FROM country_religions "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (SERVER_ID, SCENARIO_ID, r["country_id"]),
            ).fetchone()
            result.append({
                "country_id":             r["country_id"],
                "country_name":           r["country_name"],
                "total_population":       r["total_population"],
                "treasury":               r["treasury"] or 0.0,
                "daily_base_income":      r["daily_base_income"] or 0.0,
                "population_growth_rate": r["population_growth_rate"]
                                          if r["population_growth_rate"] is not None else 0.6,
                "religion":               rel["religion"] if rel else "Unknown",
            })
    return result


def get_country_by_id(country_id: str) -> dict | None:
    for c in get_countries():
        if c["country_id"] == country_id:
            return c
    return None


def find_country(name_query: str) -> dict | None:
    q = name_query.strip().lower()
    countries = get_countries()
    for c in countries:
        if c["country_name"].lower() == q or c["country_id"].lower() == q:
            return c
    for c in countries:
        if q in c["country_name"].lower() or q in c["country_id"].lower():
            return c
    return None


def update_population_growth_rate(country_id: str, new_rate: float) -> None:
    con = _write_conn()
    con.execute(
        "UPDATE countries SET population_growth_rate=? "
        "WHERE server_id=? AND scenario_id=? AND country_id=?",
        (new_rate, SERVER_ID, SCENARIO_ID, country_id),
    )
    con.commit()
    con.close()


def deduct_treasury(country_id: str, amount: float) -> float:
    """Deduct gold, returns new treasury balance. Raises ValueError if insufficient."""
    with _conn() as con:
        row = con.execute(
            "SELECT treasury FROM countries WHERE server_id=? AND scenario_id=? AND country_id=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchone()
    if row is None:
        raise ValueError("Country not found")
    balance = float(row["treasury"] or 0.0)
    if balance < amount:
        raise ValueError(f"Insufficient treasury: need {amount:.1f}, have {balance:.1f}")
    new_balance = balance - amount
    con2 = _write_conn()
    con2.execute(
        "UPDATE countries SET treasury=? WHERE server_id=? AND scenario_id=? AND country_id=?",
        (new_balance, SERVER_ID, SCENARIO_ID, country_id),
    )
    con2.commit()
    con2.close()
    return new_balance


# ── Provinces ─────────────────────────────────────────────────────────────────

def get_provinces(country_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT province_id, province_name, resource_type, population "
            "FROM provinces "
            "WHERE server_id=? AND scenario_id=? AND owner_country=? "
            "ORDER BY province_name",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Storage ───────────────────────────────────────────────────────────────────

def get_storage(country_id: str) -> dict:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM country_storage "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchone()
    if row:
        d = dict(row)
        d.pop("server_id", None)
        d.pop("scenario_id", None)
        d.pop("country_id", None)
        return d
    return {r: 0 for r in STORABLE_RESOURCES}


def deduct_storage_resources(country_id: str, resources: dict[str, int]) -> None:
    """Deduct multiple resources from storage. Raises ValueError if any insufficient."""
    storage = get_storage(country_id)
    for res, needed in resources.items():
        have = storage.get(res, 0)
        if have < needed:
            raise ValueError(f"Insufficient {res}: need {needed}, have {have}")
    # Apply deductions
    con2 = _write_conn()
    for res, needed in resources.items():
        con2.execute(
            f"UPDATE country_storage SET {res} = {res} - ? "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (needed, SERVER_ID, SCENARIO_ID, country_id),
        )
    con2.commit()
    con2.close()


# ── Buildings ─────────────────────────────────────────────────────────────────

def get_buildings_with_status(country_id: str, current_game_day: int) -> dict[str, list[str]]:
    """
    Returns {province_name: [status_string, …]}
    Status strings include "(Under Construction — X days left)" for incomplete buildings.
    """
    with _conn() as con:
        rows = con.execute(
            "SELECT p.province_name, b.building_type, b.is_completed, "
            "       b.is_active, b.construction_end_time "
            "FROM buildings b "
            "JOIN provinces p "
            "  ON p.province_id = b.province_id "
            "  AND p.server_id  = b.server_id "
            "  AND p.scenario_id= b.scenario_id "
            "WHERE b.server_id=? AND b.scenario_id=? AND b.country_id=? "
            "ORDER BY p.province_name",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()

    result: dict[str, list[str]] = {}
    for r in rows:
        pname = r["province_name"]
        btype = r["building_type"]
        if r["is_completed"]:
            status = "✅" if r["is_active"] else "🔴"
            entry  = f"{status} {btype}"
        else:
            days_left = max(0, (r["construction_end_time"] or 0) - current_game_day)
            entry = f"⏳ {btype} *(Under Construction — {days_left} days left)*"
        result.setdefault(pname, []).append(entry)
    return result


# ── Building construction ─────────────────────────────────────────────────────

def construct_building(
    country_id: str,
    building_type_str: str,
    province_id: str,
    province_resource: str,
    current_game_day: int,
) -> dict:
    """
    Wrapper around BuildingSystem.start_construction.
    Returns the result dict from the backend.
    """
    from ww1_economy.db             import EconomyDB
    from ww1_economy.building_system import BuildingSystem
    from ww1_economy.treasury_system import TreasurySystem
    from ww1_economy.storage_system  import StorageSystem

    db       = EconomyDB(DB_PATH)
    db.init()
    treasury = TreasurySystem(db)
    storage  = StorageSystem(db)
    bs       = BuildingSystem(db)

    return bs.start_construction(
        server_id         = SERVER_ID,
        scenario_id       = SCENARIO_ID,
        province_id       = str(province_id),
        country_id        = country_id,
        building_type     = building_type_str,
        province_resource = province_resource,
        current_day       = current_game_day,
        treasury          = treasury,
        storage           = storage,
    )


# ── Army ─────────────────────────────────────────────────────────────────────

def get_army_summary(country_id: str) -> dict:
    with _conn() as con:
        armies = con.execute(
            "SELECT army_id, province_id, state, strength_pct "
            "FROM armies "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()
        total_units = 0
        army_list   = []
        for a in armies:
            units = con.execute(
                "SELECT unit_name, quantity FROM army_units WHERE army_id=?",
                (a["army_id"],),
            ).fetchall()
            unit_count = sum(u["quantity"] for u in units)
            total_units += unit_count
            army_list.append({
                "army_id":      a["army_id"][:8],
                "province_id":  a["province_id"],
                "state":        a["state"],
                "strength_pct": a["strength_pct"],
                "unit_count":   unit_count,
                "units":        [dict(u) for u in units],
            })
    return {"total_units": total_units, "armies": army_list}


# ── Formatting ────────────────────────────────────────────────────────────────

def fmt_pop(n: int | float) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)
