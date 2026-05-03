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

Military tick (every game-day):
  • Movement arrivals → occupation start → battle trigger
  • Battle ticks (every game-day while active)
  • Occupation progress
  • Supply consumption
  • War score auto-boost (attacker ≥80% defender provinces occupied)
  • Battle start/end channel embeds sent via bot reference
"""
from __future__ import annotations

import logging
import os

from discord.ext import tasks

from discord_bot import embeds, game_state
from ww1_economy.db import EconomyDB

log = logging.getLogger("tick")

WW1_DB      = os.environ.get("WW1_DB_PATH", "ww1_scenario.db")
SERVER_ID   = "guild_demo"
SCENARIO_ID = "ww1"

_tick_system = None
_bot_ref     = None          # set by start_tick(); used for battle channel embeds


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


# ── Military systems cache ─────────────────────────────────────────────────────

_military_systems_cache = None


def _get_military_systems():
    """Return (db, war_sys, army_sys, battle_sys, occ_sys) — lazily cached."""
    global _military_systems_cache
    if _military_systems_cache is None:
        from ww1_economy.db               import EconomyDB
        from ww1_economy.religion_system  import ReligionSystem
        from ww1_economy.diplomacy_system  import DiplomacySystem
        from ww1_economy.war_system        import WarSystem
        from ww1_economy.army_system       import ArmySystem
        from ww1_economy.battle_system     import BattleSystem
        from ww1_economy.occupation_system import OccupationSystem
        db  = EconomyDB(WW1_DB)
        db.init()
        rel = ReligionSystem(db)
        dip = DiplomacySystem(db, rel)
        war = WarSystem(db, dip)
        arm = ArmySystem(db)
        bat = BattleSystem(db, arm, war)
        occ = OccupationSystem(db, war)
        _military_systems_cache = (db, war, arm, bat, occ)
    return _military_systems_cache


def _province_name_lookup(province_id: str) -> str:
    """Quick inline province name lookup."""
    import sqlite3 as _sql
    con = _sql.connect(WW1_DB)
    con.row_factory = _sql.Row
    row = con.execute(
        "SELECT province_name FROM provinces "
        "WHERE server_id=? AND scenario_id=? AND province_id=?",
        (SERVER_ID, SCENARIO_ID, province_id),
    ).fetchone()
    con.close()
    return row["province_name"] if row else province_id


def _build_name_map_inline() -> dict[str, str]:
    """Build country_id → country_name map inline."""
    import sqlite3 as _sql
    con = _sql.connect(WW1_DB)
    con.row_factory = _sql.Row
    rows = con.execute(
        "SELECT country_id, country_name FROM countries "
        "WHERE server_id=? AND scenario_id=?",
        (SERVER_ID, SCENARIO_ID),
    ).fetchall()
    con.close()
    return {r["country_id"]: r["country_name"] for r in rows}


def _process_military_tick(new_game_day: int) -> dict:
    """
    Run every game day:
      1. Finish movement — armies that have arrived move to their destination.
      2. Trigger battles — if enemy armies share a province.
      3. Tick active battles.
      4. Tick province occupations (per active war).
      5. Consume supply (per active war).
      6. War score auto-boost rule.

    Returns a dict with battle events for async channel sends:
      {
        "battle_starts": [{"province_name", "att_country", "def_country",
                           "att_strength", "def_strength"}, …],
        "battle_ends":   [{"province_name", "winner_country", "loser_country",
                           "att_str_after", "def_str_after", "score_delta"}, …],
      }
    """
    db, war_sys, army_sys, bat_sys, occ_sys = _get_military_systems()

    battle_starts:  list[dict]          = []
    battle_ends:    list[dict]          = []
    _occup_events:  list                = []   # discord.Embed objects for occupation feedback

    # 1 — Movement arrivals
    arrivals = army_sys.process_movement(SERVER_ID, SCENARIO_ID, new_game_day)
    for evt in arrivals:
        log.info("Army %s arrived at '%s' (country %s).",
                 evt.army_id[:8], evt.province_id, evt.country_id)

        from discord_bot.ww1_data import get_war_between
        import sqlite3 as _sql
        _con = _sql.connect(WW1_DB)
        _con.row_factory = _sql.Row
        prov_row = _con.execute(
            "SELECT owner_country FROM provinces "
            "WHERE server_id=? AND scenario_id=? AND province_id=?",
            (SERVER_ID, SCENARIO_ID, evt.province_id),
        ).fetchone()
        _con.close()

        if prov_row and prov_row["owner_country"] and prov_row["owner_country"] != evt.country_id:
            owner_id = prov_row["owner_country"]
            w = get_war_between(evt.country_id, owner_id)
            if w:
                occ_sys.start_occupation(
                    SERVER_ID, SCENARIO_ID, evt.province_id,
                    w["war_id"], evt.country_id, new_game_day,
                )
                log.info("Occupation started: %s by %s (war %s).",
                         evt.province_id, evt.country_id, w["war_id"][:8])

                enemy_armies = [
                    a for a in db.get_armies_in_province(SERVER_ID, SCENARIO_ID, evt.province_id)
                    if a["country_id"] != evt.country_id
                    and a["state"] not in ("destroyed", "moving")
                ]
                if enemy_armies:
                    enemy_row = enemy_armies[0]
                    trig = bat_sys.trigger_battle(
                        SERVER_ID, SCENARIO_ID, w["war_id"],
                        evt.army_id, enemy_row["army_id"],
                        evt.province_id, new_game_day,
                    )
                    log.info("Battle trigger: %s", trig.message)
                    if trig.ok and trig.battle_id:
                        # Collect data for channel embed
                        att_row = db.get_army(evt.army_id)
                        def_row = db.get_army(enemy_row["army_id"])
                        battle_starts.append({
                            "province_name": _province_name_lookup(evt.province_id),
                            "att_country":   evt.country_id,
                            "def_country":   enemy_row["country_id"],
                            "att_strength":  float(att_row.get("strength_pct") or 100) if att_row else 100.0,
                            "def_strength":  float(def_row.get("strength_pct") or 100) if def_row else 100.0,
                        })

    # 2 — Tick active battles
    battle_result = bat_sys.process_all_battles(SERVER_ID, SCENARIO_ID, new_game_day)
    for tick in battle_result.events:
        log.info("Battle tick: %s", tick.message)
        if tick.winner_army_id:
            # A battle was resolved this tick — build result event for channel send
            winner_row = db.get_army(tick.winner_army_id)
            loser_id   = (
                tick.army_b_id
                if tick.winner_army_id == tick.army_a_id
                else tick.army_a_id
            )
            loser_row = db.get_army(loser_id)
            winner_country = winner_row["country_id"] if winner_row else "?"
            loser_country  = loser_row["country_id"]  if loser_row  else "?"

            # Determine score delta for this resolved battle (+5 for win)
            score_delta = 5.0
            if tick.a_destroyed or tick.b_destroyed:
                score_delta = 10.0  # army_destroyed bonus

            battle_ends.append({
                "province_name":  _province_name_lookup(tick.province_id),
                "winner_country": winner_country,
                "loser_country":  loser_country,
                "att_str_after":  tick.strength_a_after,
                "def_str_after":  tick.strength_b_after,
                "score_delta":    score_delta,
            })

    # 3 — Tick province occupations for every active war
    active_wars = db.get_active_wars(SERVER_ID, SCENARIO_ID)
    for w in active_wars:
        w = dict(w)
        occ_result = occ_sys.process_occupations(
            SERVER_ID, SCENARIO_ID, w["war_id"], new_game_day
        )
        for oe in occ_result.completed:
            log.info("Province fully occupied: %s by %s%s.",
                     oe.province_id, oe.occupying_country,
                     f" ({oe.war_score_event})" if oe.war_score_event else "")
            try:
                import sqlite3 as _sql
                _con = _sql.connect(WW1_DB)
                _con.row_factory = _sql.Row
                _prow = _con.execute(
                    "SELECT province_name, owner_country FROM provinces "
                    "WHERE server_id=? AND scenario_id=? AND province_id=?",
                    (SERVER_ID, SCENARIO_ID, oe.province_id),
                ).fetchone()
                _con.close()
                if _prow:
                    _pname   = _prow["province_name"]
                    _prev    = _prow["owner_country"] or oe.province_id
                    _nm      = _build_name_map_inline()
                    _occ_em  = embeds.occupation_feedback_embed(
                        _pname, oe.occupying_country, _prev, _nm
                    )
                    _occup_events.append(_occ_em)
            except Exception as _occ_err:
                log.warning("Occupation embed lookup failed: %s", _occ_err)

        # 4 — Supply consumption
        war_start = int(w.get("start_day") or 0)
        supply_results = army_sys.process_all_supply(
            SERVER_ID, SCENARIO_ID, new_game_day, war_start
        )
        for sr in supply_results:
            if not (sr.food_met and sr.ammo_met and sr.medicine_met):
                log.info("Supply shortage — army %s: %s", sr.army_id[:8], sr.message)

        # 5 — War score auto-boost rule:
        #   If attacker occupies ≥80% of defender's provinces
        #   AND defender occupies 0 attacker provinces
        #   → force attacker score ≥ 80
        try:
            attacker = w["attacker"]
            defender = w["defender"]
            def_provs = db.get_provinces_by_country(SERVER_ID, SCENARIO_ID, defender)
            total_def = len(def_provs)
            if total_def > 0:
                occs = db.get_war_occupations(w["war_id"])
                att_occ = sum(
                    1 for o in occs
                    if o.get("occupying_country") == attacker and o.get("is_occupied")
                )
                def_occ = sum(
                    1 for o in occs
                    if o.get("occupying_country") == defender and o.get("is_occupied")
                )
                if att_occ / total_def >= 0.8 and def_occ == 0:
                    att_score = float(w.get("war_score_attacker") or 50)
                    if att_score < 80:
                        db.update_war_fields(
                            w["war_id"],
                            war_score_attacker=80,
                            war_score_defender=20,
                        )
                        log.info(
                            "War score auto-boost: %s → 80 "
                            "(occupied %d/%d defender provinces).",
                            attacker, att_occ, total_def,
                        )
        except Exception as _e:
            log.warning("War score auto-boost error: %s", _e)

    return {
        "battle_starts":  battle_starts,
        "battle_ends":    battle_ends,
        "occup_embeds":   _occup_events,
    }


# ── Main tick task ─────────────────────────────────────────────────────────────

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
            from discord_bot.ww1_data import apply_hospital_opinion
            for bldg in report.building_completions:
                if bldg.get("building_type") == "Hospital":
                    apply_hospital_opinion(bldg["country_id"], province_count=1)
        except Exception as e:
            log.warning("Daily tick error: %s", e)

        # ── Military tech completions ─────────────────────────────────────────
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

        # ── Military tick: movement, battles, occupation, supply, auto-boost ──
        mil_events: dict = {"battle_starts": [], "battle_ends": [], "occup_embeds": []}
        try:
            mil_events = _process_military_tick(new_game_day)
        except Exception as e:
            log.warning("Military tick error: %s", e)

        # ── Battle + Occupation channel notifications ─────────────────────────
        if _bot_ref and (
            mil_events["battle_starts"]
            or mil_events["battle_ends"]
            or mil_events["occup_embeds"]
        ):
            try:
                channel_id_str = session["channel_id"]
                channel = _bot_ref.get_channel(int(channel_id_str))
                if channel:
                    nm = _build_name_map_inline()
                    for bs in mil_events["battle_starts"]:
                        em = embeds.battle_start_embed(
                            bs["province_name"],
                            bs["att_country"],
                            bs["def_country"],
                            bs["att_strength"],
                            bs["def_strength"],
                            nm,
                        )
                        await channel.send(embed=em)
                    for be in mil_events["battle_ends"]:
                        em = embeds.battle_result_embed(
                            be["province_name"],
                            be["winner_country"],
                            be["loser_country"],
                            be["att_str_after"],
                            be["def_str_after"],
                            be["score_delta"],
                            nm,
                        )
                        await channel.send(embed=em)
                    for occ_em in mil_events["occup_embeds"]:
                        await channel.send(embed=occ_em)
            except Exception as e:
                log.warning("Battle channel send error: %s", e)

        # ── Monthly tick: consumption → production → market → efficiency ───────
        month_before   = game_day_before  // game_state.DAYS_PER_MONTH
        month_after    = new_game_day     // game_state.DAYS_PER_MONTH
        months_crossed = month_after - month_before

        if months_crossed > 0:
            try:
                ts.monthly_tick(SERVER_ID, SCENARIO_ID, month_after)
            except Exception as e:
                log.warning("Monthly tick error: %s", e)

            country_ids = _get_all_assigned_countries(guild_id)
            for cid in country_ids:
                _apply_monthly_growth(cid, months_crossed)

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
    global _bot_ref
    _bot_ref = bot
    await bot.wait_until_ready()
    game_state.reset_all_tick_clocks()
    if not tick_task.is_running():
        tick_task.start()
        log.info("Tick runner started (tick clocks reset to now).")
