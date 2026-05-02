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
    "rubber": "🧪", "copper": "🔶", "horses": "🐎", "stone": "🏔️",
    "gems": "💎", "textiles": "🧵", "chemicals": "⚗️",
    "gunpowder": "💣", "ammunition": "🔫", "medicines": "💊",
}

# Resources that appear in country_storage and should be displayed.
# Horses, Textiles → give daily income only (no storage slot shown).
# Gems, Gold       → credited to treasury directly (no storage slot shown).
DISPLAY_STORAGE_RESOURCES = [
    "iron", "coal", "copper", "stone", "wood", "rubber",
    "grain", "meat", "cotton", "oil",
    "chemicals", "gunpowder", "ammunition", "medicines",
]

# All resources that can actually exist in the storage table (including legacy).
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
            "       treasury, daily_base_income, population_growth_rate, "
            "       population_opinion, economy_efficiency "
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
                "population_opinion":     r["population_opinion"]
                                          if r["population_opinion"] is not None else 50,
                "economy_efficiency":     r["economy_efficiency"]
                                          if r["economy_efficiency"] is not None else 1.0,
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


def credit_treasury(country_id: str, amount: float) -> None:
    con2 = _write_conn()
    con2.execute(
        "UPDATE countries SET treasury = treasury + ? "
        "WHERE server_id=? AND scenario_id=? AND country_id=?",
        (amount, SERVER_ID, SCENARIO_ID, country_id),
    )
    con2.commit()
    con2.close()


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
    """Returns full storage dict (all columns in country_storage)."""
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


def get_display_storage(country_id: str) -> dict:
    """Returns only the resources that should be shown in the storage embed."""
    full = get_storage(country_id)
    return {k: full.get(k, 0) for k in DISPLAY_STORAGE_RESOURCES}


def deduct_storage_resources(country_id: str, resources: dict[str, int]) -> None:
    """Deduct multiple resources from storage. Raises ValueError if any insufficient."""
    storage = get_storage(country_id)
    for res, needed in resources.items():
        have = storage.get(res, 0)
        if have < needed:
            raise ValueError(f"Insufficient {res}: need {needed}, have {have}")
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
    Completed buildings show ✅/🔴.
    Under-construction buildings show ⏳ with time left (or "completing soon" if 0 days left).
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
            days_left = (r["construction_end_time"] or 0) - current_game_day
            if days_left <= 0:
                entry = f"⏳ {btype} *(Completing next tick…)*"
            else:
                entry = f"⏳ {btype} *(Under Construction — {days_left}d left)*"
        result.setdefault(pname, []).append(entry)
    return result


def get_completed_building_types(country_id: str) -> set[str]:
    """Return a set of building type names that are completed for this country."""
    with _conn() as con:
        rows = con.execute(
            "SELECT building_type FROM buildings "
            "WHERE server_id=? AND scenario_id=? AND country_id=? AND is_completed=1",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()
    return {r["building_type"] for r in rows}


# ── Building construction ─────────────────────────────────────────────────────

def construct_building(
    country_id: str,
    building_type_str: str,
    province_id: str,
    province_resource: str,
    current_game_day: int,
) -> dict:
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


# ── Technology ────────────────────────────────────────────────────────────────

def _get_econ_db():
    from ww1_economy.db import EconomyDB
    db = EconomyDB(DB_PATH)
    db.init()
    return db


def get_tech_status_for_country(country_id: str) -> dict[str, dict]:
    """Returns {tech_id: {is_unlocked, is_researching, research_start_day, research_end_day}}."""
    db = _get_econ_db()
    rows = db.get_technologies_for_country(SERVER_ID, SCENARIO_ID, country_id)
    return {r["tech_id"]: r for r in rows}


def get_reform_status_for_country(country_id: str) -> dict[str, dict]:
    db = _get_econ_db()
    rows = db.get_reforms_for_country(SERVER_ID, SCENARIO_ID, country_id)
    return {r["reform_id"]: r for r in rows}


def get_mil_tech_status_for_country(country_id: str) -> dict[str, dict]:
    db = _get_econ_db()
    rows = db.get_military_technologies_for_country(SERVER_ID, SCENARIO_ID, country_id)
    return {r["tech_id"]: r for r in rows}


def get_active_research_info(country_id: str, game_day: int) -> dict | None:
    """
    Returns info about whatever is currently being researched (tech, reform, or mil tech),
    or None if nothing is being researched.
    """
    db = _get_econ_db()

    row = db.get_active_research(SERVER_ID, SCENARIO_ID, country_id)
    if row:
        remaining = max(0, row["research_end_day"] - game_day)
        total     = max(1, row["research_end_day"] - row["research_start_day"])
        done      = max(0, game_day - row["research_start_day"])
        pct       = min(100, int(done / total * 100))
        return {
            "tech_id":      row["tech_id"],
            "type":         "tech",
            "remaining_days": remaining,
            "pct_done":     pct,
        }

    row = db.get_active_reform_research(SERVER_ID, SCENARIO_ID, country_id)
    if row:
        remaining = max(0, row["research_end_day"] - game_day)
        total     = max(1, row["research_end_day"] - row["research_start_day"])
        done      = max(0, game_day - row["research_start_day"])
        pct       = min(100, int(done / total * 100))
        return {
            "tech_id":      row["reform_id"],
            "type":         "reform",
            "remaining_days": remaining,
            "pct_done":     pct,
        }

    row = db.get_active_military_research(SERVER_ID, SCENARIO_ID, country_id)
    if row:
        remaining = max(0, row["research_end_day"] - game_day)
        total     = max(1, row["research_end_day"] - row["research_start_day"])
        done      = max(0, game_day - row["research_start_day"])
        pct       = min(100, int(done / total * 100))
        return {
            "tech_id":      row["tech_id"],
            "type":         "military",
            "remaining_days": remaining,
            "pct_done":     pct,
        }

    return None


MAX_RESEARCH_SPEED: float = 10.0


def get_research_speed(country_id: str) -> float:
    """
    Returns the final research speed in % per month.
    base 1.0% + Library +0.5%, School +1.0%, University +1.5% per completed building.
    Clamped to [0.5, 10.0]%.
    """
    speed = 1.0
    completed = get_completed_building_types(country_id)
    from ww1_economy.tech_data import RESEARCH_SPEED_BONUSES
    for btype, bonus in RESEARCH_SPEED_BONUSES.items():
        count = sum(1 for b in completed if b == btype)
        speed += bonus * count
    return min(MAX_RESEARCH_SPEED, max(0.5, speed))


def cancel_active_research(country_id: str, game_day: int) -> dict | None:
    """
    Cancel whatever is currently being researched.
    Returns {tech_id, type, remaining_days} or None if nothing was researching.
    """
    info = get_active_research_info(country_id, game_day)
    if info is None:
        return None

    con = _write_conn()
    try:
        rtype = info["type"]
        rid   = info["tech_id"]
        if rtype == "tech":
            con.execute(
                "UPDATE technologies SET is_researching=0 "
                "WHERE server_id=? AND scenario_id=? AND country_id=? AND tech_id=?",
                (SERVER_ID, SCENARIO_ID, country_id, rid),
            )
        elif rtype == "reform":
            con.execute(
                "UPDATE reforms SET is_researching=0 "
                "WHERE server_id=? AND scenario_id=? AND country_id=? AND reform_id=?",
                (SERVER_ID, SCENARIO_ID, country_id, rid),
            )
        elif rtype == "military":
            con.execute(
                "UPDATE military_technologies SET is_researching=0 "
                "WHERE server_id=? AND scenario_id=? AND country_id=? AND tech_id=?",
                (SERVER_ID, SCENARIO_ID, country_id, rid),
            )
        con.commit()
    finally:
        con.close()

    return info


def start_tech_research(country_id: str, tech_id: str, game_day: int,
                         remaining_days: int | None = None) -> dict:
    """
    Start or resume research on a civil technology.
    Returns {"ok": True} or {"ok": False, "reason": str}.
    """
    from ww1_economy.tech_data import TECH_TREE
    tdef = TECH_TREE.get(tech_id)
    if tdef is None:
        return {"ok": False, "reason": "Unknown technology."}

    # Check prerequisites
    db     = _get_econ_db()
    status = get_tech_status_for_country(country_id)
    for prereq in tdef.prerequisites:
        if not status.get(prereq, {}).get("is_unlocked", False):
            from ww1_economy.tech_data import TECH_TREE as TT
            pname = TT[prereq].name if prereq in TT else prereq
            return {"ok": False, "reason": f"Prerequisite not met: **{pname}**"}

    if status.get(tech_id, {}).get("is_unlocked", False):
        return {"ok": False, "reason": "This technology is already unlocked."}

    duration = remaining_days if remaining_days is not None else tdef.duration_days
    end_day  = game_day + duration

    db.upsert_technology(
        server_id          = SERVER_ID,
        scenario_id        = SCENARIO_ID,
        country_id         = country_id,
        tech_id            = tech_id,
        is_unlocked        = False,
        is_researching     = True,
        research_start_day = game_day,
        research_end_day   = end_day,
    )
    return {"ok": True, "duration": duration, "end_day": end_day}


def start_reform_research(country_id: str, reform_id: str, game_day: int,
                           remaining_days: int | None = None) -> dict:
    """Start or resume research on a reform."""
    from ww1_economy.tech_data import REFORM_TREE
    rdef = REFORM_TREE.get(reform_id)
    if rdef is None:
        return {"ok": False, "reason": "Unknown reform."}

    db     = _get_econ_db()
    rstatus = get_reform_status_for_country(country_id)

    # Check prerequisites
    for prereq in rdef.prerequisites:
        if not rstatus.get(prereq, {}).get("is_unlocked", False):
            from ww1_economy.tech_data import REFORM_TREE as RT
            pname = RT[prereq].name if prereq in RT else prereq
            return {"ok": False, "reason": f"Prerequisite not met: **{pname}**"}

    if rstatus.get(reform_id, {}).get("is_unlocked", False):
        return {"ok": False, "reason": "This reform is already researched."}
    if rstatus.get(reform_id, {}).get("is_adopted", False):
        return {"ok": False, "reason": "This reform is already adopted."}

    duration = remaining_days if remaining_days is not None else rdef.duration_days
    end_day  = game_day + duration

    db.upsert_reform(
        server_id          = SERVER_ID,
        scenario_id        = SCENARIO_ID,
        country_id         = country_id,
        reform_id          = reform_id,
        is_unlocked        = False,
        is_adopted         = False,
        is_researching     = True,
        research_start_day = game_day,
        research_end_day   = end_day,
    )
    return {"ok": True, "duration": duration, "end_day": end_day}


def start_mil_tech_research(country_id: str, tech_id: str, game_day: int,
                              remaining_days: int | None = None) -> dict:
    """Start or resume research on a military technology."""
    from ww1_economy.military_tech_data import MILITARY_TECH_TREE
    tdef = MILITARY_TECH_TREE.get(tech_id)
    if tdef is None:
        return {"ok": False, "reason": "Unknown military technology."}

    mstatus = get_mil_tech_status_for_country(country_id)
    for prereq in tdef.prerequisites:
        if not mstatus.get(prereq, {}).get("is_unlocked", False):
            from ww1_economy.military_tech_data import MILITARY_TECH_TREE as MTT
            pname = MTT[prereq].name if prereq in MTT else prereq
            return {"ok": False, "reason": f"Prerequisite not met: **{pname}**"}

    if mstatus.get(tech_id, {}).get("is_unlocked", False):
        return {"ok": False, "reason": "This military technology is already unlocked."}

    duration = remaining_days if remaining_days is not None else tdef.duration_days
    end_day  = game_day + duration

    db = _get_econ_db()
    db.upsert_military_technology(
        server_id              = SERVER_ID,
        scenario_id            = SCENARIO_ID,
        country_id             = country_id,
        tech_id                = tech_id,
        is_unlocked            = False,
        is_researching         = True,
        research_start_day     = game_day,
        research_duration_days = duration,
        research_end_day       = end_day,
    )
    return {"ok": True, "duration": duration, "end_day": end_day}


def adopt_reform(country_id: str, reform_id: str) -> dict:
    """
    Adopt a researched reform. Costs 100 gold. Max 3 adopted at once.
    Returns {"ok": True, "new_treasury": float} or {"ok": False, "reason": str}.
    Also applies the reform's opinion_bonus immediately to the country's opinion.
    """
    from ww1_economy.tech_data import REFORM_TREE, REFORM_ADOPTION_COST, MAX_ADOPTED_REFORMS

    rdef = REFORM_TREE.get(reform_id)
    if rdef is None:
        return {"ok": False, "reason": "Unknown reform."}

    db      = _get_econ_db()
    rstatus = get_reform_status_for_country(country_id)
    row     = rstatus.get(reform_id, {})

    if not row.get("is_unlocked", False):
        return {"ok": False, "reason": "This reform must be fully researched before it can be adopted."}
    if row.get("is_adopted", False):
        return {"ok": False, "reason": "This reform is already adopted."}

    adopted = db.get_adopted_reforms(SERVER_ID, SCENARIO_ID, country_id)
    if len(adopted) >= MAX_ADOPTED_REFORMS:
        return {"ok": False, "reason": f"Maximum of **{MAX_ADOPTED_REFORMS}** reforms can be adopted at once."}

    try:
        new_bal = deduct_treasury(country_id, REFORM_ADOPTION_COST)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}

    db.adopt_reform(SERVER_ID, SCENARIO_ID, country_id, reform_id)

    # Apply opinion bonus immediately
    if rdef.opinion_bonus:
        _apply_opinion_delta(country_id, rdef.opinion_bonus)

    return {"ok": True, "new_treasury": new_bal, "adopted_count": len(adopted) + 1}


def _apply_opinion_delta(country_id: str, delta: int) -> None:
    """Add delta to population_opinion, clamped to [0, 100]."""
    con = _write_conn()
    try:
        con.execute(
            "UPDATE countries "
            "SET population_opinion = MAX(0, MIN(100, population_opinion + ?)) "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (delta, SERVER_ID, SCENARIO_ID, country_id),
        )
        con.commit()
    finally:
        con.close()


def apply_hospital_opinion(country_id: str, province_count: int = 1) -> None:
    """Apply +1.5 opinion per completed Hospital province. Called on building completion."""
    if province_count <= 0:
        return
    delta = int(round(1.5 * province_count))
    _apply_opinion_delta(country_id, delta)


def remove_reform(country_id: str, reform_id: str) -> dict:
    """
    Unadopt an adopted reform.
    Reverses the opinion_bonus that was applied on adoption.
    Returns {"ok": True} or {"ok": False, "reason": str}.
    """
    from ww1_economy.tech_data import REFORM_TREE

    rdef = REFORM_TREE.get(reform_id)
    if rdef is None:
        return {"ok": False, "reason": "Unknown reform."}

    db      = _get_econ_db()
    rstatus = get_reform_status_for_country(country_id)
    row     = rstatus.get(reform_id, {})

    if not row.get("is_adopted", False):
        return {"ok": False, "reason": "This reform is not currently adopted."}

    db.unadopt_reform(SERVER_ID, SCENARIO_ID, country_id, reform_id)

    # Reverse the opinion bonus
    if rdef.opinion_bonus:
        _apply_opinion_delta(country_id, -rdef.opinion_bonus)

    adopted = db.get_adopted_reforms(SERVER_ID, SCENARIO_ID, country_id)
    return {"ok": True, "adopted_count": len(adopted)}


def get_current_tax_level(country_id: str) -> str:
    """Return the current tax_level key for the country (default 'standard')."""
    with _conn() as con:
        row = con.execute(
            "SELECT tax_level FROM countries "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchone()
    if row and row["tax_level"]:
        return row["tax_level"]
    return "standard"


def set_country_tax_level(
    country_id:    str,
    tax_key:       str,
    current_month: int = 0,
) -> dict:
    """
    Set the country's tax policy.

    1. Reverses the old tier's opinion contribution and applies the new one.
    2. Writes tax_level + tax_multiplier to the DB.
    3. Recomputes economy_efficiency immediately.

    Returns {"ok": True, "opinion": int, "efficiency": float}
         or {"ok": False, "reason": str}.
    """
    from ww1_economy.efficiency_system import WW1_TAX_MAP, EconomyEfficiencySystem
    from ww1_economy.db import EconomyDB

    new_tier = WW1_TAX_MAP.get(tax_key)
    if new_tier is None:
        return {"ok": False, "reason": f"Unknown tax level: '{tax_key}'"}

    old_key  = get_current_tax_level(country_id)
    old_tier = WW1_TAX_MAP.get(old_key, WW1_TAX_MAP["standard"])

    opinion_delta = new_tier["opinion"] - old_tier["opinion"]
    if opinion_delta:
        _apply_opinion_delta(country_id, opinion_delta)

    con = _write_conn()
    try:
        con.execute(
            "UPDATE countries SET tax_level=?, tax_multiplier=? "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (tax_key, new_tier["multiplier"], SERVER_ID, SCENARIO_ID, country_id),
        )
        con.commit()
    finally:
        con.close()

    db  = EconomyDB(DB_PATH)
    db.init()
    eff_sys = EconomyEfficiencySystem(db)
    eff_sys.recompute(SERVER_ID, SCENARIO_ID, country_id, current_month)

    with _conn() as c:
        row = c.execute(
            "SELECT population_opinion, economy_efficiency FROM countries "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchone()

    opinion    = int(row["population_opinion"])  if row else 50
    efficiency = float(row["economy_efficiency"]) if row else 1.0
    return {"ok": True, "opinion": opinion, "efficiency": efficiency}


def get_market_snapshot() -> list[dict]:
    """
    Return current market state for all resources (initialising rows if needed).
    Each row has: resource_name, base_price, current_price, shortage, shortage_end_month.
    """
    from ww1_economy.db import EconomyDB
    db = EconomyDB(DB_PATH)
    db.init()
    db.init_market_prices(SERVER_ID, SCENARIO_ID)
    return db.get_all_market(SERVER_ID, SCENARIO_ID)


def buy_from_market(country_id: str, resource: str, quantity: int) -> dict:
    """
    Purchase *quantity* units of *resource* from the global market.
    Deducts gold from treasury and adds resources to storage.
    Returns BuyResult.to_dict().
    """
    from ww1_economy.db              import EconomyDB
    from ww1_economy.market_system   import GlobalMarketSystem
    from ww1_economy.storage_system  import StorageSystem
    from ww1_economy.treasury_system import TreasurySystem

    db       = EconomyDB(DB_PATH)
    db.init()
    storage  = StorageSystem(db)
    treasury = TreasurySystem(db)
    market   = GlobalMarketSystem(db, storage, treasury)

    result = market.buy_resource(SERVER_ID, SCENARIO_ID, country_id, resource, quantity)
    return result.to_dict()


# ── Fuzzy research name lookup ────────────────────────────────────────────────

def find_research_target(query: str) -> dict | None:
    """
    Returns {tech_id, name, type, def} or None.
    Searches TECH_TREE, REFORM_TREE, MILITARY_TECH_TREE.
    """
    from ww1_economy.tech_data          import TECH_TREE, REFORM_TREE
    from ww1_economy.military_tech_data import MILITARY_TECH_TREE

    q = query.strip().lower().replace("-", " ").replace("_", " ")

    all_targets = []
    for tid, tdef in TECH_TREE.items():
        all_targets.append({"tech_id": tid, "name": tdef.name, "type": "tech", "def": tdef})
    for rid, rdef in REFORM_TREE.items():
        all_targets.append({"tech_id": rid, "name": rdef.name, "type": "reform", "def": rdef})
    for tid, tdef in MILITARY_TECH_TREE.items():
        all_targets.append({"tech_id": tid, "name": tdef.name, "type": "military", "def": tdef})

    # Exact match first
    for t in all_targets:
        norm = t["name"].lower().replace("-", " ").replace("_", " ")
        if norm == q or t["tech_id"].replace("_", " ") == q:
            return t
    # Partial match
    for t in all_targets:
        norm = t["name"].lower().replace("-", " ").replace("_", " ")
        if q in norm or q in t["tech_id"].replace("_", " "):
            return t
    return None


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
