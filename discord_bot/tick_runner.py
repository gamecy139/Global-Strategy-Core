"""
Background tick loop — advances in-game time and applies economic effects.
Runs every 10 real seconds; advances game days based on each guild's speed setting.
"""
from __future__ import annotations

import logging
import os

from discord.ext import tasks

from discord_bot import game_state
from ww1_economy.db import EconomyDB

log = logging.getLogger("tick")

WW1_DB = os.environ.get("WW1_DB_PATH", "ww1_scenario.db")
SERVER_ID   = "guild_demo"
SCENARIO_ID = "ww1"

_db: EconomyDB | None = None


def _get_db() -> EconomyDB:
    global _db
    if _db is None:
        _db = EconomyDB(WW1_DB)
        _db.init()
    return _db


# ── Tick helpers ──────────────────────────────────────────────────────────────

def _apply_daily_income(country_id: str, days: int) -> None:
    """Credit daily_base_income × days to the country's treasury."""
    db = _get_db()
    row = db.get_country(SERVER_ID, SCENARIO_ID, country_id)
    if row is None:
        return
    income = float(row.get("daily_base_income") or 0.0)
    if income > 0 and days > 0:
        try:
            db.update_country_fields(
                SERVER_ID, SCENARIO_ID, country_id,
                treasury=float(row.get("treasury") or 0.0) + income * days,
            )
        except Exception as e:
            log.warning("Treasury update failed for %s: %s", country_id, e)


def _apply_monthly_growth(country_id: str, months_crossed: int) -> None:
    """Compound monthly population growth."""
    if months_crossed <= 0:
        return
    db = _get_db()
    row = db.get_country(SERVER_ID, SCENARIO_ID, country_id)
    if row is None:
        return
    pop    = int(row.get("total_population") or 0)
    rate   = float(row.get("population_growth_rate") or 0.6)
    factor = (1.0 + rate / 100.0) ** months_crossed
    new_pop = int(pop * factor)
    try:
        db.update_country_fields(
            SERVER_ID, SCENARIO_ID, country_id,
            total_population=new_pop,
        )
        # Also update per-province populations proportionally
        import sqlite3
        con = sqlite3.connect(WW1_DB)
        con.execute(
            "UPDATE provinces SET population = CAST(population * ? AS INTEGER) "
            "WHERE server_id=? AND scenario_id=? AND owner_country=?",
            (factor, SERVER_ID, SCENARIO_ID, country_id),
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("Population update failed for %s: %s", country_id, e)


def _get_all_assigned_countries(guild_id: str) -> list[str]:
    assignments = game_state.get_assignments(guild_id)
    return list(assignments.keys())


# ── Main tick task ────────────────────────────────────────────────────────────

@tasks.loop(seconds=10)
async def tick_task() -> None:
    sessions = game_state.get_all_sessions()
    for session in sessions:
        guild_id  = session["guild_id"]
        game_day_before = session["game_day"]

        days_advanced, new_game_day = game_state.advance_tick(guild_id)
        if days_advanced <= 0:
            continue

        log.debug("Guild %s advanced %d days → day %d (%s)",
                  guild_id, days_advanced, new_game_day,
                  game_state.game_date_str(new_game_day))

        country_ids = _get_all_assigned_countries(guild_id)

        for cid in country_ids:
            # Apply daily income
            _apply_daily_income(cid, days_advanced)

            # Check if any month boundaries were crossed
            month_before = game_day_before // game_state.DAYS_PER_MONTH
            month_after  = new_game_day    // game_state.DAYS_PER_MONTH
            months_crossed = month_after - month_before
            if months_crossed > 0:
                _apply_monthly_growth(cid, months_crossed)


@tick_task.before_loop
async def _before_tick(bot=None) -> None:
    pass  # bot.wait_until_ready() handled in start_tick


async def start_tick(bot) -> None:
    await bot.wait_until_ready()
    if not tick_task.is_running():
        tick_task.start()
        log.info("Tick runner started.")
