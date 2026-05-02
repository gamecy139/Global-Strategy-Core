"""
Read-only helpers that pull WW1 country data from ww1_scenario.db.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

DB_PATH    = os.environ.get("WW1_DB_PATH", "ww1_scenario.db")
SERVER_ID  = "guild_demo"
SCENARIO_ID = "ww1"

# Religion → emoji mapping
RELIGION_EMOJI: dict[str, str] = {
    "Protestant Christian": "✝️",
    "Catholic Christian":   "⛪",
    "Orthodox Christian":   "☦️",
    "Sunni Islam":          "☪️",
    "Atheism":              "🔬",
    "Judaism":              "✡️",
    "Hinduism":             "🕉️",
}


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def get_countries() -> list[dict]:
    """
    Return all countries for the WW1 scenario, enriched with religion.
    Each dict has: country_id, country_name, total_population, religion.
    """
    with _conn() as con:
        rows = con.execute(
            "SELECT country_id, country_name, total_population "
            "FROM countries "
            "WHERE server_id=? AND scenario_id=? "
            "ORDER BY country_name",
            (SERVER_ID, SCENARIO_ID),
        ).fetchall()

        result = []
        for r in rows:
            rel_row = con.execute(
                "SELECT religion FROM country_religions "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (SERVER_ID, SCENARIO_ID, r["country_id"]),
            ).fetchone()
            religion = rel_row["religion"] if rel_row else "Unknown"
            result.append({
                "country_id":       r["country_id"],
                "country_name":     r["country_name"],
                "total_population": r["total_population"],
                "religion":         religion,
            })
    return result


def find_country(name_query: str) -> dict | None:
    """
    Case-insensitive search by country_name or country_id.
    Returns the country dict or None.
    """
    q = name_query.strip().lower()
    for c in get_countries():
        if c["country_name"].lower() == q or c["country_id"].lower() == q:
            return c
    # Partial match fallback
    for c in get_countries():
        if q in c["country_name"].lower() or q in c["country_id"].lower():
            return c
    return None


def fmt_population(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)
