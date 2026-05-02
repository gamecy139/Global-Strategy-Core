"""
Background tick loop — advances in-game time and applies all economic effects.
Runs every 10 real seconds; advances game days based on each guild's speed setting.

On bot startup, last_tick_real_s is reset to NOW so offline time never
accumulates as phantom game-days.

Monthly tick uses the full TickSystem (consumption → production → market →
efficiency) so that:
  • Tier 2 buildings consume resources and activate/deactivate
  • Storage fills from production (Tier 1 & Tier 2)
  • Gold/Gems mines credit treasury directly
  • daily_base_income is refreshed from actual active buildings
  • Economy efficiency is recomputed from opinion/unrest/war
"""
from __future__ import annotations

import logging
import os

from discord.ext import tasks

from discord_bot import game_state
from ww1_economy.db import EconomyDB

log = logging.getLogger("tick")

WW1_DB      = os.environ.get("WW1_DB_PATH", "ww1_scenario.db")
SERVER_ID   = "guild_demo"
SCENARIO_ID = "ww1"

_tick_system = None


def _get_tick_system():
    global _tick_system
    if _tick_system is None:
        from ww1_economy.tick_system import TickSystem
        db = EconomyDB(WW1_DB)
        db.init()
        _tick_system = TickSystem.assemble(db)
    return _tick_system


def _apply_monthly_growth(country_id: str, months_crossed: int) -> None:
    """Compound monthly population growth (province-level + country total)."""
    if months_crossed <= 0:
        return
    db = EconomyDB(WW1_DB)
    db.init()
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
    return list(game_state.get_assignments(guild_id).keys())


# ── Main tick task ────────────────────────────────────────────────────────────

_military_systems_cache = None


def _get_military_systems():
    """Return (db, war_sys, army_sys, battle_sys, occ_sys) — lazily cached."""
    global _military_systems_cache
    if _military_systems_cache is None:
        from ww1_economy.db               import EconomyDB
        from ww1_economy.diplomacy_system  import DiplomacySystem
        from ww1_economy.war_system        import WarSystem
        from ww1_economy.army_system       import ArmySystem
        from ww1_economy.battle_system     import BattleSystem
        from ww1_economy.occupation_system import OccupationSystem
        db  = EconomyDB(WW1_DB)
        db.init()
        dip = DiplomacySystem(db)
        war = WarSystem(db, dip)
        arm = ArmySystem(db)
        bat = BattleSystem(db, arm, war)
        occ = OccupationSystem(db, war)
        _military_systems_cache = (db, war, arm, bat, occ)
    return _military_systems_cache


def _process_military_tick(new_game_day: int) -> None:
    """
    Run every game day:
      1. Finish movement — armies that have arrived move to their destination.
      2. Trigger battles — if enemy armies share a province.
      3. Tick active battles.
      4. Tick province occupations (per active war).
      5. Consume supply (per active war).
    Battle/occupation/supply events are logged; no channel messages here
    (channel notifications can be wired later via a bot reference).
    """
    db, war_sys, army_sys, bat_sys, occ_sys = _get_military_systems()

    # 1 — Movement arrivals
    arrivals = army_sys.process_movement(SERVER_ID, SCENARIO_ID, new_game_day)
    for evt in arrivals:
        log.info("Army %s arrived at '%s' (country %s).",
                 evt.army_id[:8], evt.province_id, evt.country_id)

        # Check if the province is enemy-owned → start occupation
        from discord_bot.ww1_data import get_war_between
        import sqlite3 as _sql
        _con = _sql.connect(WW1_DB)
        _con.row_factory = _sql.Row
        prov = _con.execute(
            "SELECT owner_country FROM provinces "
            "WHERE server_id=? AND scenario_id=? AND province_id=?",
            (SERVER_ID, SCENARIO_ID, evt.province_id),
        ).fetchone()
        _con.close()

        if prov and prov["owner_country"] and prov["owner_country"] != evt.country_id:
            owner_id = prov["owner_country"]
            w = get_war_between(evt.country_id, owner_id)
            if w:
                occ_evt = occ_sys.start_occupation(
                    SERVER_ID, SCENARIO_ID, evt.province_id,
                    w["war_id"], evt.country_id, new_game_day,
                )
                log.info("Occupation started: %s by %s (war %s).",
                         evt.province_id, evt.country_id, w["war_id"][:8])

                # Check for enemy army in same province → trigger battle
                enemy_armies = [
                    a for a in db.get_armies_in_province(SERVER_ID, SCENARIO_ID, evt.province_id)
                    if a["country_id"] != evt.country_id
                    and a["state"] not in ("destroyed", "moving")
                ]
                if enemy_armies:
                    trig = bat_sys.trigger_battle(
                        SERVER_ID, SCENARIO_ID, w["war_id"],
                        evt.army_id, enemy_armies[0]["army_id"],
                        evt.province_id, new_game_day,
                    )
                    log.info("Battle trigger: %s", trig.message)

    # 2 — Tick active battles
    battle_result = bat_sys.process_all_battles(SERVER_ID, SCENARIO_ID, new_game_day)
    for tick in battle_result.events:
        log.info("Battle tick: %s", tick.message)

    # 3 — Tick province occupations for every active war
    active_wars = db.get_active_wars(SERVER_ID, SCENARIO_ID)
    for w in active_wars:
        occ_result = occ_sys.process_occupations(
            SERVER_ID, SCENARIO_ID, w["war_id"], new_game_day
        )
        for oe in occ_result.completed:
            log.info("Province fully occupied: %s by %s%s.",
                     oe.province_id, oe.occupying_country,
                     f" ({oe.war_score_event})" if oe.war_score_event else "")

        # 4 — Supply consumption (needs war start day)
        war_start = int(w.get("start_day") or 0)
        supply_results = army_sys.process_all_supply(
            SERVER_ID, SCENARIO_ID, new_game_day, war_start
        )
        for sr in supply_results:
            if not (sr.food_met and sr.ammo_met and sr.medicine_met):
                log.info("Supply shortage — army %s: %s", sr.army_id[:8], sr.message)


@tasks.loop(seconds=10)
async def tick_task() -> None:
    ts = _get_tick_system()

    sessions = game_state.get_all_sessions()
    for session in sessions:
        guild_id        = session["guild_id"]
        game_day_before = session["game_day"]

        days_advanced, new_game_day = game_state.advance_tick(guild_id)
        if days_advanced <= 0:
            continue

        log.debug("Guild %s: +%d days → day %d (%s)",
                  guild_id, days_advanced, new_game_day,
                  game_state.game_date_str(new_game_day))

        # ── Daily tick: building completions, tech/reform completions, income ──
        try:
            report = ts.daily_tick(SERVER_ID, SCENARIO_ID, new_game_day, days_advanced)
            # Apply Hospital opinion bonuses for newly completed hospitals
            from discord_bot.ww1_data import apply_hospital_opinion
            for bldg in report.building_completions:
                if bldg.get("building_type") == "Hospital":
                    apply_hospital_opinion(bldg["country_id"], province_count=1)
        except Exception as e:
            log.warning("Daily tick error: %s", e)

        # ── Military tech completions (separate from economic tick system) ──
        try:
            from ww1_economy.military_tech_system import MilitaryTechSystem
            _mil_db = EconomyDB(WW1_DB)
            _mil_db.init()
            mil_events = MilitaryTechSystem(_mil_db).process_completions(
                SERVER_ID, SCENARIO_ID, new_game_day
            )
            for evt in mil_events:
                log.info(
                    "Military tech completed: %s → %s (unlocks: %s)",
                    evt.country_id, evt.name, evt.unlocked_units,
                )
        except Exception as e:
            log.warning("Military tech completion error: %s", e)

        # ── Recruiting army graduation ────────────────────────────────────────
        try:
            import sqlite3 as _sqlite3
            _con = _sqlite3.connect(WW1_DB)
            _con.row_factory = _sqlite3.Row
            due = _con.execute(
                "SELECT army_id FROM armies "
                "WHERE server_id=? AND scenario_id=? "
                "AND state='recruiting' AND recruitment_end_day <= ?",
                (SERVER_ID, SCENARIO_ID, new_game_day),
            ).fetchall()
            for row in due:
                _con.execute(
                    "UPDATE armies SET state='idle' WHERE army_id=?",
                    (row["army_id"],),
                )
                log.info("Army %s finished recruiting — state → idle.", row["army_id"][:8])
            if due:
                _con.commit()
            _con.close()
        except Exception as e:
            log.warning("Army graduation error: %s", e)

        # ── Military tick: movement, battles, occupation, supply ──────────────
        try:
            _process_military_tick(new_game_day)
        except Exception as e:
            log.warning("Military tick error: %s", e)

        # ── Monthly tick: consumption → production → market → efficiency ───────
        month_before   = game_day_before  // game_state.DAYS_PER_MONTH
        month_after    = new_game_day     // game_state.DAYS_PER_MONTH
        months_crossed = month_after - month_before

        if months_crossed > 0:
            try:
                ts.monthly_tick(SERVER_ID, SCENARIO_ID, month_after)
            except Exception as e:
                log.warning("Monthly tick error: %s", e)

            # Population growth — applied per assigned country
            country_ids = _get_all_assigned_countries(guild_id)
            for cid in country_ids:
                _apply_monthly_growth(cid, months_crossed)

            # Diplomacy monthly drifts (+5 improve / -5 damage per action)
            try:
                from discord_bot.ww1_data import get_active_diplomacy_actions, is_rival
                from ww1_economy.db import EconomyDB as _EconDB
                _dip_db = _EconDB(WW1_DB)
                _dip_db.init()
                actions = get_active_diplomacy_actions(SERVER_ID, SCENARIO_ID)
                for act in actions:
                    actor  = act["actor"]
                    target = act["target"]
                    atype  = act["action_type"]
                    if atype == "improve":
                        if not is_rival(actor, target):
                            _dip_db.adjust_base_relation(
                                SERVER_ID, SCENARIO_ID, actor, target, +5.0
                            )
                    elif atype == "damage":
                        _dip_db.adjust_base_relation(
                            SERVER_ID, SCENARIO_ID, actor, target, -5.0
                        )
                if actions:
                    log.info("Applied monthly diplomacy drifts for %d actions.", len(actions))
            except Exception as e:
                log.warning("Diplomacy drift error: %s", e)


@tick_task.before_loop
async def _before_tick(bot=None) -> None:
    pass


async def start_tick(bot) -> None:
    await bot.wait_until_ready()
    # Reset all tick clocks — time should NOT advance while bot is offline
    game_state.reset_all_tick_clocks()
    if not tick_task.is_running():
        tick_task.start()
        log.info("Tick runner started (tick clocks reset to now).")
