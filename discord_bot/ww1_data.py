"""
Read-only helpers that pull WW1 data from ww1_scenario.db.
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
    "coal":    "🪨", "iron":    "⚙️", "gold":    "🪙",
    "grain":   "🌾", "meat":    "🥩", "wood":    "🪵",
    "oil":     "🛢️", "cotton":  "🧶", "rubber":  "🧪",
    "copper":  "🔶", "horses":  "🐎", "stone":   "🪨",
    "gems":    "💎",
}


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


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
                "country_id":            r["country_id"],
                "country_name":          r["country_name"],
                "total_population":      r["total_population"],
                "treasury":              r["treasury"] or 0.0,
                "daily_base_income":     r["daily_base_income"] or 0.0,
                "population_growth_rate": r["population_growth_rate"] if r["population_growth_rate"] is not None else 0.6,
                "religion":              rel["religion"] if rel else "Unknown",
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
    # Exact match first
    for c in countries:
        if c["country_name"].lower() == q or c["country_id"].lower() == q:
            return c
    # Partial match
    for c in countries:
        if q in c["country_name"].lower() or q in c["country_id"].lower():
            return c
    return None


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


# ── Buildings ────────────────────────────────────────────────────────────────

def get_buildings(country_id: str) -> dict[str, list[str]]:
    """Returns {province_name: [building_type, …]}"""
    with _conn() as con:
        rows = con.execute(
            "SELECT p.province_name, b.building_type, b.is_completed, b.is_active "
            "FROM buildings b "
            "JOIN provinces p ON p.province_id = b.province_id "
            "  AND p.server_id=b.server_id AND p.scenario_id=b.scenario_id "
            "WHERE b.server_id=? AND b.scenario_id=? AND b.country_id=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()
    result: dict[str, list[str]] = {}
    for r in rows:
        pname = r["province_name"]
        status = "✅" if r["is_completed"] and r["is_active"] else (
                 "🔨" if r["is_completed"] and not r["is_active"] else "⏳")
        entry = f"{status} {r['building_type']}"
        result.setdefault(pname, []).append(entry)
    return result


# ── Armies ────────────────────────────────────────────────────────────────────

def get_army_summary(country_id: str) -> dict:
    """Returns total unit count and a list of army summaries."""
    with _conn() as con:
        armies = con.execute(
            "SELECT army_id, province_id, state, strength_pct "
            "FROM armies "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()

        total_units = 0
        army_list = []
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


# ── Formatting helpers ────────────────────────────────────────────────────────

def fmt_population(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def fmt_treasury(t: float) -> str:
    return f"**{t:,.1f}** gold"


def fmt_income(i: float) -> str:
    return f"**{i:+.2f}** gold/day"
