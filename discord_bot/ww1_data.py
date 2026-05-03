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
        # If end_day has passed and tick hasn't cleared it yet, skip — it's done
        if remaining == 0 and game_day >= row["research_end_day"]:
            db.upsert_technology(
                SERVER_ID, SCENARIO_ID, country_id, row["tech_id"],
                is_unlocked=True, is_researching=False,
            )
        else:
            total = max(1, row["research_end_day"] - row["research_start_day"])
            done  = max(0, game_day - row["research_start_day"])
            pct   = min(100, int(done / total * 100))
            return {
                "tech_id":        row["tech_id"],
                "type":           "tech",
                "remaining_days": remaining,
                "pct_done":       pct,
            }

    row = db.get_active_reform_research(SERVER_ID, SCENARIO_ID, country_id)
    if row:
        remaining = max(0, row["research_end_day"] - game_day)
        if remaining == 0 and game_day >= row["research_end_day"]:
            db.upsert_reform(
                SERVER_ID, SCENARIO_ID, country_id, row["reform_id"],
                is_unlocked=True, is_researching=False,
            )
        else:
            total = max(1, row["research_end_day"] - row["research_start_day"])
            done  = max(0, game_day - row["research_start_day"])
            pct   = min(100, int(done / total * 100))
            return {
                "tech_id":        row["reform_id"],
                "type":           "reform",
                "remaining_days": remaining,
                "pct_done":       pct,
            }

    row = db.get_active_military_research(SERVER_ID, SCENARIO_ID, country_id)
    if row:
        remaining = max(0, row["research_end_day"] - game_day)
        if remaining == 0 and game_day >= row["research_end_day"]:
            db.complete_military_technology(SERVER_ID, SCENARIO_ID, country_id, row["tech_id"])
        else:
            total = max(1, row["research_end_day"] - row["research_start_day"])
            done  = max(0, game_day - row["research_start_day"])
            pct   = min(100, int(done / total * 100))
            return {
                "tech_id":        row["tech_id"],
                "type":           "military",
                "remaining_days": remaining,
                "pct_done":       pct,
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

def get_army_summary(country_id: str, game_day: int = 0) -> dict:
    country = get_country_by_id(country_id)
    country_slug = (
        country["country_name"].replace(" ", "_") if country else country_id
    )
    with _conn() as con:
        armies = con.execute(
            "SELECT army_id, province_id, state, strength_pct, recruitment_end_day "
            "FROM armies "
            "WHERE server_id=? AND scenario_id=? AND country_id=? "
            "ORDER BY rowid",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()
        total_units = 0
        army_list   = []
        for idx, a in enumerate(armies, start=1):
            units = con.execute(
                "SELECT unit_name, quantity FROM army_units WHERE army_id=?",
                (a["army_id"],),
            ).fetchall()
            unit_count = sum(u["quantity"] for u in units)
            state      = a["state"]
            end_day    = int(a["recruitment_end_day"] or 0)
            remaining  = max(0, end_day - game_day) if state == "recruiting" else 0

            # Resolve province name (fall back to province_id if not found)
            prov_row = con.execute(
                "SELECT province_name FROM provinces "
                "WHERE server_id=? AND scenario_id=? AND province_id=?",
                (SERVER_ID, SCENARIO_ID, a["province_id"]),
            ).fetchone()
            province_name = prov_row["province_name"] if prov_row else str(a["province_id"])

            # Only count fully-ready units toward total
            if state != "recruiting":
                total_units += unit_count

            army_list.append({
                "army_label":        f"{country_slug}_army_{idx}",
                "province_name":     province_name,
                "state":             state,
                "strength_pct":      a["strength_pct"],
                "unit_count":        unit_count,
                "units":             [dict(u) for u in units],
                "recruitment_end_day": end_day,
                "days_remaining":    remaining,
            })
    return {"total_units": total_units, "armies": army_list}


# ── Army Recruitment ──────────────────────────────────────────────────────────

SLOT_ORDER = ["F1", "F2", "FL1", "S1", "S2", "N1"]


def _ensure_troop_definitions_seeded() -> None:
    """
    Idempotently seed troop_definitions for the scenario.
    Safe to call on every request — INSERT OR IGNORE makes it a no-op after first run.
    """
    from ww1_economy.troop_definition_system import TroopDefinitionSystem
    from ww1_economy.military_tech_system    import MilitaryTechSystem
    db = _get_econ_db()
    TroopDefinitionSystem(db, MilitaryTechSystem(db)).seed_definitions(SERVER_ID, SCENARIO_ID)


def _ensure_mil_tech_bootstrapped(country_id: str) -> None:
    """
    If a country has zero rows in military_technologies, grant the root doctrine
    so it can at least start researching.  This is a safety net for countries
    that were never run through init_ww1_scenario.
    """
    db   = _get_econ_db()
    rows = db.get_military_technologies_for_country(SERVER_ID, SCENARIO_ID, country_id)
    if not rows:
        import logging
        logging.getLogger("bot").warning(
            "Country %s has no military_technologies rows — "
            "auto-granting pre_industrial_military_doctrine.", country_id
        )
        db.upsert_military_technology(
            SERVER_ID, SCENARIO_ID, country_id,
            "pre_industrial_military_doctrine",
            is_unlocked=True,
        )


def get_recruitable_slots(country_id: str) -> dict[str, dict]:
    """
    Return {slot: best_unit_dict} for every slot where the country has at
    least one unlocked unit.  'Best' = highest battle_points.

    Works entirely from static UNIT_DEFINITIONS + MILITARY_TECH_TREE data;
    does NOT depend on the troop_definitions DB table being seeded.
    """
    import logging
    from ww1_economy.unit_data            import UNIT_DEFINITIONS
    from ww1_economy.military_tech_data   import UNIT_TECH_REQUIREMENTS
    from ww1_economy.military_tech_system import MilitaryTechSystem

    log = logging.getLogger("bot")

    db      = _get_econ_db()
    mil_sys = MilitaryTechSystem(db)

    # Safety net: if the country has never been through init_ww1_scenario,
    # grant the root doctrine so they at least have something.
    _ensure_mil_tech_bootstrapped(country_id)

    # Snapshot of every unlocked military tech for this country
    unlocked_techs: set[str] = set(
        mil_sys.get_unlocked_techs(SERVER_ID, SCENARIO_ID, country_id)
    )
    log.debug("Country %s — unlocked mil-techs: %s", country_id, sorted(unlocked_techs))

    by_slot: dict[str, list] = {}
    for udef in UNIT_DEFINITIONS.values():
        required_tech = UNIT_TECH_REQUIREMENTS.get(udef.unit_name)
        if required_tech is None:
            # Unit has no tech gate — always available
            available = True
        else:
            available = required_tech in unlocked_techs

        if available:
            unit_dict = {
                "unit_name":             udef.unit_name,
                "category":              udef.category,
                "required_tech":         required_tech or "",
                "population_required":   udef.population_required,
                "gold_cost":             float(udef.gold_cost),
                "recruitment_time_days": udef.recruitment_time_days,
                "speed_modifier":        float(udef.speed_modifier),
                "battle_points":         udef.battle_points,
            }
            by_slot.setdefault(udef.category, []).append(unit_dict)

    available_units = [u["unit_name"] for units in by_slot.values() for u in units]
    log.debug("Country %s — available units: %s", country_id, sorted(available_units))

    return {
        slot: max(units, key=lambda u: u["battle_points"])
        for slot, units in by_slot.items()
    }


def get_recruitment_cap_info(country_id: str, current_month: int) -> dict:
    """
    Returns recruitment cap data.  Auto-resets used % every 3 months.
    Keys: total_pop, used_pct, remaining_pct, penalty (bool).
    """
    with _conn() as con:
        row = con.execute(
            "SELECT total_population, recruitment_used_percent, "
            "       recruitment_last_reset_month "
            "FROM countries "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchone()

    if row is None:
        return {"total_pop": 0, "used_pct": 0.0, "remaining_pct": 30.0, "penalty": False}

    total_pop  = int(row["total_population"])
    used_pct   = float(row["recruitment_used_percent"] or 0.0)
    last_reset = int(row["recruitment_last_reset_month"] or 0)

    if current_month - last_reset >= 3:
        used_pct = 0.0
        con2 = _write_conn()
        try:
            con2.execute(
                "UPDATE countries "
                "SET recruitment_used_percent=0.0, recruitment_last_reset_month=? "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (current_month, SERVER_ID, SCENARIO_ID, country_id),
            )
            con2.commit()
        finally:
            con2.close()

    remaining_pct = max(0.0, 30.0 - used_pct)
    penalty       = used_pct > 25.0

    return {
        "total_pop":     total_pop,
        "used_pct":      used_pct,
        "remaining_pct": remaining_pct,
        "penalty":       penalty,
    }


def execute_army_recruitment(
    country_id:    str,
    province_id:   str,
    province_name: str,
    selections:    dict,
    game_day:      int,
    current_month: int,
) -> dict:
    """
    Full gate-check + execution of one army recruitment order.

    ``selections`` must be {slot: {"unit_name": str, "qty": int, "unit": row_dict}}.
    A key "_province_id" is ignored if present.

    Returns {"ok": True, "army_id", "total_gold", "total_pop", "total_days", "penalty"}
    or      {"ok": False, "reason": str}.
    """
    import uuid
    from ww1_economy.military_tech_system import MilitaryTechSystem

    db      = _get_econ_db()
    mil_sys = MilitaryTechSystem(db)

    unit_slots = {k: v for k, v in selections.items() if k != "_province_id"}

    # ── 1. Tech gate (bypass troop_definitions — check is_tech_unlocked directly) ──
    from ww1_economy.military_tech_data import UNIT_TECH_REQUIREMENTS
    unlocked_techs: set[str] = set(
        mil_sys.get_unlocked_techs(SERVER_ID, SCENARIO_ID, country_id)
    )
    for slot, sel in unit_slots.items():
        uname         = sel["unit_name"]
        required_tech = UNIT_TECH_REQUIREMENTS.get(uname)
        if required_tech and required_tech not in unlocked_techs:
            return {
                "ok":     False,
                "reason": (
                    f"**{uname}** requires military tech "
                    f"**{required_tech}** which is not yet unlocked."
                ),
            }

    # ── 2. Cap info ───────────────────────────────────────────────────────────
    cap      = get_recruitment_cap_info(country_id, current_month)
    total_pop_country = cap["total_pop"]
    penalty           = cap["penalty"]
    remaining_pct     = cap["remaining_pct"]

    if remaining_pct < 5.0:
        return {
            "ok": False,
            "reason": (
                f"Recruitment cap exhausted — only **{remaining_pct:.1f}%** remaining "
                f"(minimum 5% required).\nThe cap resets every 3 months."
            ),
        }

    # ── 3. Totals (with penalty if applicable) ────────────────────────────────
    total_gold = 0.0
    total_pop  = 0
    total_time = 0

    for slot, sel in unit_slots.items():
        qty  = sel["qty"]
        unit = sel["unit"]
        g    = float(unit["gold_cost"]) * qty * (3 if penalty else 1)
        p    = int(unit["population_required"]) * qty
        t    = int(unit["recruitment_time_days"])
        if penalty:
            t = int(t * 1.5)
        total_gold += g
        total_pop  += p
        total_time  = max(total_time, t)

    # ── 4. Gold check ─────────────────────────────────────────────────────────
    with _conn() as con:
        crow = con.execute(
            "SELECT treasury FROM countries "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchone()
    treasury = float(crow["treasury"] or 0.0) if crow else 0.0

    if treasury < total_gold:
        return {
            "ok": False,
            "reason": (
                f"Not enough gold.\n"
                f"Required: **{total_gold:,.0f}** gold  •  "
                f"Treasury: **{treasury:,.0f}** gold."
            ),
        }

    # ── 5. Population cap check ───────────────────────────────────────────────
    recruitable_pop = int(total_pop_country * remaining_pct / 100.0)
    if total_pop > recruitable_pop:
        return {
            "ok": False,
            "reason": (
                f"Not enough recruitable population.\n"
                f"Required: **{total_pop:,}**  •  "
                f"Available: **{recruitable_pop:,}** "
                f"({remaining_pct:.1f}% of {total_pop_country:,} total)."
            ),
        }

    # ── 6. Execute ────────────────────────────────────────────────────────────
    used_pct_added = (total_pop / total_pop_country * 100.0) if total_pop_country > 0 else 0.0

    deduct_treasury(country_id, total_gold)

    con2 = _write_conn()
    try:
        con2.execute(
            "UPDATE countries "
            "SET total_population           = total_population - ?, "
            "    recruitment_used_percent   = recruitment_used_percent + ? "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (total_pop, used_pct_added, SERVER_ID, SCENARIO_ID, country_id),
        )
        con2.commit()
    finally:
        con2.close()

    army_id = str(uuid.uuid4())
    db.insert_army(
        army_id          = army_id,
        server_id        = SERVER_ID,
        scenario_id      = SCENARIO_ID,
        country_id       = country_id,
        province_id      = str(province_id),
        base_province_id = str(province_id),
        last_supply_day  = game_day,
    )
    db.update_army_fields(
        army_id,
        state                = "recruiting",
        recruitment_end_day  = game_day + total_time,
    )

    for slot, sel in unit_slots.items():
        db.upsert_army_unit(
            army_unit_id = str(uuid.uuid4()),
            army_id      = army_id,
            unit_name    = sel["unit_name"],
            quantity     = sel["qty"],
            server_id    = SERVER_ID,
            scenario_id  = SCENARIO_ID,
        )

    return {
        "ok":         True,
        "army_id":    army_id,
        "total_gold": total_gold,
        "total_pop":  total_pop,
        "total_days": total_time,
        "penalty":    penalty,
    }


# ── Diplomacy ─────────────────────────────────────────────────────────────────

def get_all_relations_for_country(country_id: str) -> dict[str, float]:
    """Returns {other_country_id: base_relation} for every country that has a row."""
    db = _get_econ_db()
    rows = db.get_all_relations(SERVER_ID, SCENARIO_ID)
    result: dict[str, float] = {}
    for r in rows:
        if r["country_a"] == country_id:
            result[r["country_b"]] = float(r["base_relation"])
        elif r["country_b"] == country_id:
            result[r["country_a"]] = float(r["base_relation"])
    return result


def get_relation_value(country_a: str, country_b: str) -> float:
    """Return base_relation between two countries (default 50 if no row)."""
    db = _get_econ_db()
    row = db.get_relation(SERVER_ID, SCENARIO_ID, country_a, country_b)
    return float(row["base_relation"]) if row else 50.0


def is_rival(country_a: str, country_b: str) -> bool:
    """True if either country has declared rivalry against the other."""
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM rivals "
            "WHERE server_id=? AND scenario_id=? "
            "AND ((initiator=? AND target=?) OR (initiator=? AND target=?))",
            (SERVER_ID, SCENARIO_ID, country_a, country_b, country_b, country_a),
        ).fetchone()
    return row is not None


def is_at_war(country_a: str, country_b: str) -> bool:
    """True if the two countries are in an active war."""
    with _conn() as con:
        row = con.execute("""
            SELECT 1 FROM wars
            WHERE server_id=? AND scenario_id=? AND status='active'
            AND ((attacker=? AND defender=?) OR (attacker=? AND defender=?))
        """, (SERVER_ID, SCENARIO_ID, country_a, country_b, country_b, country_a)
        ).fetchone()
    return row is not None


def are_allied(country_a: str, country_b: str) -> bool:
    """True if the two countries share an alliance."""
    with _conn() as con:
        row = con.execute("""
            SELECT 1 FROM alliance_members m1
            JOIN alliance_members m2 ON m1.alliance_id = m2.alliance_id
            WHERE m1.country_id=? AND m2.country_id=?
            AND m1.server_id=? AND m1.scenario_id=?
        """, (country_a, country_b, SERVER_ID, SCENARIO_ID)).fetchone()
    return row is not None


def _upsert_diplomacy_action(actor: str, target: str, action_type: str) -> None:
    con = _write_conn()
    con.execute("""
        INSERT INTO diplomacy_actions (server_id, scenario_id, actor, target, action_type)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(server_id, scenario_id, actor, target)
        DO UPDATE SET action_type=excluded.action_type
    """, (SERVER_ID, SCENARIO_ID, actor, target, action_type))
    con.commit()
    con.close()


def _remove_diplomacy_action(actor: str, target: str) -> None:
    con = _write_conn()
    con.execute(
        "DELETE FROM diplomacy_actions "
        "WHERE server_id=? AND scenario_id=? AND actor=? AND target=?",
        (SERVER_ID, SCENARIO_ID, actor, target),
    )
    con.commit()
    con.close()


def get_active_diplomacy_actions(server_id: str, scenario_id: str) -> list[dict]:
    """All active improve/damage actions for tick processing."""
    with _conn() as con:
        rows = con.execute(
            "SELECT actor, target, action_type FROM diplomacy_actions "
            "WHERE server_id=? AND scenario_id=?",
            (server_id, scenario_id),
        ).fetchall()
    return [dict(r) for r in rows]


def diplo_improve_relations(actor: str, target: str) -> dict:
    """Queue +5/month improve-relations action. Blocked by rivalry/war."""
    if is_rival(actor, target):
        return {"ok": False, "reason": "⚔️ A rivalry exists — improvement is blocked on both sides."}
    if is_at_war(actor, target):
        return {"ok": False, "reason": "⚔️ You are at war — improvement is blocked."}
    _upsert_diplomacy_action(actor, target, "improve")
    return {"ok": True}


def diplo_damage_relations(actor: str, target: str) -> dict:
    """Queue -5/month damage-relations action."""
    if is_at_war(actor, target):
        return {"ok": False, "reason": "⚔️ You are already at war."}
    _upsert_diplomacy_action(actor, target, "damage")
    return {"ok": True}


def diplo_rivalry(actor: str, target: str) -> dict:
    """Declare rivalry: -10 relation instantly, blocks improvement both ways."""
    if is_rival(actor, target):
        return {"ok": False, "reason": "A rivalry already exists between these countries."}
    if is_at_war(actor, target):
        return {"ok": False, "reason": "⚔️ You are already at war — rivalry is redundant."}
    db = _get_econ_db()
    new_rel = db.adjust_base_relation(SERVER_ID, SCENARIO_ID, actor, target, -10.0)
    # Cancel any improve actions in either direction
    _remove_diplomacy_action(actor, target)
    _remove_diplomacy_action(target, actor)
    # Record rivalry (directional — so check_diplomacy can show who initiated)
    con = _write_conn()
    con.execute(
        "INSERT OR IGNORE INTO rivals (server_id, scenario_id, initiator, target) VALUES (?,?,?,?)",
        (SERVER_ID, SCENARIO_ID, actor, target),
    )
    con.commit()
    con.close()
    return {"ok": True, "new_relation": new_rel}


def diplo_alliance(actor: str, target: str) -> dict:
    """Propose alliance (immediate if relation >= 80)."""
    if is_rival(actor, target):
        return {"ok": False, "reason": "⚔️ Cannot ally with a rival."}
    if is_at_war(actor, target):
        return {"ok": False, "reason": "⚔️ Cannot ally with a country you're at war with."}
    if are_allied(actor, target):
        return {"ok": False, "reason": "These countries are already allied."}
    rel = get_relation_value(actor, target)
    if rel < 80:
        return {
            "ok": False,
            "reason": f"Relations must be at least **80** to propose an alliance.\nCurrent: **{rel:.0f}**",
        }
    import uuid as _uuid
    alliance_id = str(_uuid.uuid4())
    db = _get_econ_db()
    db.insert_alliance(alliance_id, SERVER_ID, SCENARIO_ID, f"{actor}-{target} Alliance")
    db.add_alliance_member(alliance_id, actor, SERVER_ID, SCENARIO_ID)
    db.add_alliance_member(alliance_id, target, SERVER_ID, SCENARIO_ID)
    return {"ok": True, "alliance_id": alliance_id}


def diplo_declare_war(actor: str, target: str, game_day: int) -> dict:
    """Declare war. Requires relation < 20."""
    if actor == target:
        return {"ok": False, "reason": "You cannot declare war on yourself."}
    if is_at_war(actor, target):
        return {"ok": False, "reason": "You are already at war with this country."}
    rel = get_relation_value(actor, target)
    if rel >= 20:
        return {
            "ok": False,
            "reason": f"Relations must be below **20** to declare war.\nCurrent: **{rel:.0f}**",
        }
    import uuid as _uuid
    war_id = str(_uuid.uuid4())
    db = _get_econ_db()
    db.insert_war(war_id, SERVER_ID, SCENARIO_ID, actor, target, game_day)
    db.insert_war_participant(war_id, actor, "attacker", is_leader=True)
    db.insert_war_participant(war_id, target, "defender", is_leader=True)
    db.upsert_relation(SERVER_ID, SCENARIO_ID, actor, target, 0.0)
    # Cancel any diplomacy actions between them
    _remove_diplomacy_action(actor, target)
    _remove_diplomacy_action(target, actor)
    return {"ok": True, "war_id": war_id}


def diplo_send_gift(actor: str, target: str) -> dict:
    """Send 40 gold gift: deducted from actor, +40 to target treasury, +5 relation."""
    GIFT_GOLD = 40.0
    GIFT_REL  = 5.0
    if is_at_war(actor, target):
        return {"ok": False, "reason": "⚔️ Cannot send gifts to a country you're at war with."}
    try:
        deduct_treasury(actor, GIFT_GOLD)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    credit_treasury(target, GIFT_GOLD)
    db = _get_econ_db()
    new_rel = db.adjust_base_relation(SERVER_ID, SCENARIO_ID, actor, target, GIFT_REL)
    return {"ok": True, "new_relation": new_rel}


def get_rivals_of(country_id: str) -> tuple[list[str], list[str]]:
    """Returns (countries_we_rivaled, countries_who_rivaled_us)."""
    with _conn() as con:
        our   = [r[0] for r in con.execute(
            "SELECT target FROM rivals WHERE server_id=? AND scenario_id=? AND initiator=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()]
        their = [r[0] for r in con.execute(
            "SELECT initiator FROM rivals WHERE server_id=? AND scenario_id=? AND target=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()]
    return our, their


def get_ally_country_ids(country_id: str) -> list[str]:
    """Returns list of country_ids allied with country_id."""
    with _conn() as con:
        # Find alliance_ids this country belongs to
        alliances = [r[0] for r in con.execute(
            "SELECT alliance_id FROM alliance_members "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()]
        if not alliances:
            return []
        placeholders = ",".join("?" * len(alliances))
        allies = [r[0] for r in con.execute(
            f"SELECT country_id FROM alliance_members "
            f"WHERE alliance_id IN ({placeholders}) AND country_id != ?",
            (*alliances, country_id),
        ).fetchall()]
    return list(dict.fromkeys(allies))  # deduplicate, preserve order


def get_active_wars_for_country(country_id: str) -> list[dict]:
    """All active wars involving country_id."""
    with _conn() as con:
        rows = con.execute("""
            SELECT w.war_id, w.attacker, w.defender, w.start_day
            FROM wars w
            LEFT JOIN war_participants wp ON w.war_id = wp.war_id
            WHERE w.server_id=? AND w.scenario_id=? AND w.status='active'
            AND (w.attacker=? OR w.defender=? OR wp.country_id=?)
        """, (SERVER_ID, SCENARIO_ID, country_id, country_id, country_id)
        ).fetchall()
    return [dict(r) for r in rows]


def get_diplomacy_overview(country_id: str) -> dict:
    """Full diplomatic picture for rp check_diplomacy."""
    all_rels  = get_all_relations_for_country(country_id)
    friendly  = {cid: v for cid, v in all_rels.items() if v > 60}
    unfriendly = {cid: v for cid, v in all_rels.items() if v < 30}
    our_rivals, rivaled_by = get_rivals_of(country_id)
    allies = get_ally_country_ids(country_id)
    wars   = get_active_wars_for_country(country_id)
    return {
        "friendly":    friendly,
        "unfriendly":  unfriendly,
        "our_rivals":  our_rivals,
        "rivaled_by":  rivaled_by,
        "allies":      allies,
        "wars":        wars,
        "all_rels":    all_rels,
    }


# ── Formatting ────────────────────────────────────────────────────────────────

def fmt_pop(n: int | float) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


# ── War / Army / Battle / Occupation System helpers ───────────────────────────

_shared_war_db:     object = None
_war_system_cache:  object = None
_army_system_cache: object = None
_battle_sys_cache:  object = None
_occ_sys_cache:     object = None


def _get_shared_war_db():
    global _shared_war_db
    if _shared_war_db is None:
        from ww1_economy.db import EconomyDB
        _shared_war_db = EconomyDB(DB_PATH)
        _shared_war_db.init()
    return _shared_war_db


def _get_war_system():
    global _war_system_cache
    if _war_system_cache is None:
        from ww1_economy.religion_system  import ReligionSystem
        from ww1_economy.diplomacy_system import DiplomacySystem
        from ww1_economy.war_system import WarSystem
        db  = _get_shared_war_db()
        rel = ReligionSystem(db)
        _war_system_cache = WarSystem(db, DiplomacySystem(db, rel))
    return _war_system_cache


def _get_army_system():
    global _army_system_cache
    if _army_system_cache is None:
        from ww1_economy.army_system import ArmySystem
        _army_system_cache = ArmySystem(_get_shared_war_db())
    return _army_system_cache


def _get_battle_system():
    global _battle_sys_cache
    if _battle_sys_cache is None:
        from ww1_economy.battle_system import BattleSystem
        _battle_sys_cache = BattleSystem(
            _get_shared_war_db(), _get_army_system(), _get_war_system()
        )
    return _battle_sys_cache


def _get_occupation_system():
    global _occ_sys_cache
    if _occ_sys_cache is None:
        from ww1_economy.occupation_system import OccupationSystem
        _occ_sys_cache = OccupationSystem(_get_shared_war_db(), _get_war_system())
    return _occ_sys_cache


def war_declare(attacker: str, defender: str, game_day: int) -> dict:
    """Declare war. Returns {ok, war_id, message}."""
    res = _get_war_system().declare_war(SERVER_ID, SCENARIO_ID, attacker, defender, game_day)
    if res.ok:
        db = _get_shared_war_db()
        for cid in (attacker, defender):
            row = db.get_country(SERVER_ID, SCENARIO_ID, cid)
            if row:
                new_opinion = max(0, int(row.get("population_opinion") or 50) - 5)
                new_eff     = max(0.5, float(row.get("economy_efficiency") or 1.0) - 0.10)
                db.update_country_fields(
                    SERVER_ID, SCENARIO_ID, cid,
                    population_opinion=new_opinion,
                    economy_efficiency=new_eff,
                    in_active_war=1,
                    war_start_month=game_day // 30,
                )
    return {"ok": res.ok, "war_id": res.war_id, "message": res.message}


def war_request_ceasefire(war_id: str, country_id: str) -> dict:
    res = _get_war_system().request_ceasefire(war_id, country_id)
    return {"ok": res.ok, "message": res.message}


def war_accept_ceasefire(war_id: str, country_id: str) -> dict:
    res = _get_war_system().accept_ceasefire(war_id, country_id)
    return {"ok": res.ok, "message": res.message}


def war_surrender(war_id: str, country_id: str) -> dict:
    res = _get_war_system().surrender(war_id, country_id)
    return {"ok": res.ok, "victory_score": res.victory_score, "message": res.message}


def war_proclaim_victory(war_id: str, country_id: str) -> dict:
    res = _get_war_system().proclaim_victory(war_id, country_id)
    return {"ok": res.ok, "victory_score": res.victory_score, "message": res.message}


def war_add_ally(war_id: str, country_id: str, side: str) -> dict:
    msg = _get_war_system().add_ally_to_war(war_id, SERVER_ID, SCENARIO_ID, country_id, side)
    ok  = "not found" not in msg.lower() and "is not active" not in msg.lower()
    return {"ok": ok, "message": msg}


def war_move_army(army_id: str, dest_province_id: str,
                  provinces_to_traverse: int, game_day: int) -> dict:
    """Order an army to move. Returns {ok, travel_days, arrival_day, message}."""
    res = _get_army_system().move_army(
        army_id, dest_province_id, provinces_to_traverse,
        game_day, SERVER_ID, SCENARIO_ID,
    )
    return {
        "ok":          res.ok,
        "travel_days": res.travel_days,
        "arrival_day": res.arrival_day,
        "message":     res.message,
    }


def get_war_details(war_id: str) -> dict | None:
    """Full war record with participants and occupations."""
    db  = _get_shared_war_db()
    war = db.get_war(war_id)
    if war is None:
        return None
    participants = db.get_war_participants(war_id)
    occupations  = db.get_war_occupations(war_id)
    return {
        "war":          dict(war),
        "participants": [dict(p) for p in participants],
        "occupations":  [dict(o) for o in occupations],
    }


def get_country_armies(country_id: str) -> list[dict]:
    """Return all non-destroyed armies for a country with province name and army number."""
    with _conn() as con:
        rows = con.execute(
            "SELECT a.army_id, a.province_id, a.state, a.strength_pct, a.rowid, "
            "       p.province_name "
            "FROM armies a "
            "LEFT JOIN provinces p "
            "  ON p.province_id=a.province_id "
            "  AND p.server_id=a.server_id AND p.scenario_id=a.scenario_id "
            "WHERE a.server_id=? AND a.scenario_id=? AND a.country_id=? "
            "  AND a.state NOT IN ('destroyed') "
            "ORDER BY a.rowid",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()
    result = []
    for i, r in enumerate(rows, start=1):
        d = dict(r)
        d["army_num"] = i
        result.append(d)
    return result


def get_all_provinces_list(owner_country: str | None = None,
                            enemy_countries: list[str] | None = None) -> list[dict]:
    """Return provinces for a movement UI — own first, then enemy, capped at 25."""
    with _conn() as con:
        rows = con.execute(
            "SELECT province_id, province_name, owner_country "
            "FROM provinces "
            "WHERE server_id=? AND scenario_id=? "
            "ORDER BY province_name",
            (SERVER_ID, SCENARIO_ID),
        ).fetchall()
    all_provs = [dict(r) for r in rows]

    own     = [p for p in all_provs if owner_country and p["owner_country"] == owner_country]
    enemies = [p for p in all_provs
               if enemy_countries and p["owner_country"] in enemy_countries
               and p not in own]
    others  = [p for p in all_provs if p not in own and p not in enemies]
    return (own + enemies + others)[:25]


def get_war_between(country_a: str, country_b: str) -> dict | None:
    """Return the first active war that has both countries on opposing sides."""
    with _conn() as con:
        wars = con.execute(
            "SELECT * FROM wars WHERE server_id=? AND scenario_id=? AND status='active'",
            (SERVER_ID, SCENARIO_ID),
        ).fetchall()
        for w in wars:
            w = dict(w)
            parts = con.execute(
                "SELECT country_id, side FROM war_participants WHERE war_id=?",
                (w["war_id"],),
            ).fetchall()
            sides: dict[str, str] = {
                w["attacker"]: "attacker",
                w["defender"]: "defender",
            }
            for p in parts:
                sides[p["country_id"]] = p["side"]
            if (country_a in sides and country_b in sides
                    and sides[country_a] != sides[country_b]):
                return w
    return None


def get_active_wars_all() -> list[dict]:
    """All active wars in the scenario."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM wars WHERE server_id=? AND scenario_id=? AND status='active'",
            (SERVER_ID, SCENARIO_ID),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Victory / Province helpers ─────────────────────────────────────────────────

def get_occupied_provinces_by_winner(war_id: str, winner_id: str) -> list[dict]:
    """Provinces fully occupied by winner in this war (available to annex)."""
    db   = _get_shared_war_db()
    occs = db.get_war_occupations(war_id)
    result: list[dict] = []
    with _conn() as con:
        for occ in occs:
            if occ.get("occupying_country") == winner_id and occ.get("is_occupied"):
                row = con.execute(
                    "SELECT * FROM provinces "
                    "WHERE server_id=? AND scenario_id=? AND province_id=?",
                    (SERVER_ID, SCENARIO_ID, occ["province_id"]),
                ).fetchone()
                if row:
                    result.append(dict(row))
    return result


def get_non_core_provinces(country_id: str) -> list[dict]:
    """Provinces owned by country_id that are non-core (is_core=0)."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.province_id, p.province_name, p.resource_type, p.population,
                   pc.conversion_end_day
            FROM provinces p
            JOIN province_cores pc
              ON pc.province_id  = p.province_id
             AND pc.server_id   = p.server_id
             AND pc.scenario_id = p.scenario_id
             AND pc.country_id  = ?
            WHERE p.server_id=? AND p.scenario_id=? AND p.owner_country=?
              AND pc.is_core = 0
            ORDER BY p.province_name
            """,
            (country_id, SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_country_religion(country_id: str) -> str | None:
    """Return the country's state religion, or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT religion FROM country_religions "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchone()
    return row["religion"] if row else None


def get_different_religion_provinces(country_id: str) -> list[dict]:
    """Provinces owned by country_id whose religion differs from the country's religion."""
    crel = get_country_religion(country_id)
    if crel is None:
        return []
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.province_id, p.province_name, p.resource_type, p.population,
                   COALESCE(pr.religion, 'Unknown') AS province_religion
            FROM provinces p
            LEFT JOIN province_religions pr
              ON pr.province_id  = p.province_id
             AND pr.server_id   = p.server_id
             AND pr.scenario_id = p.scenario_id
            WHERE p.server_id=? AND p.scenario_id=? AND p.owner_country=?
              AND (pr.religion IS NULL OR pr.religion != ?)
            ORDER BY p.province_name
            """,
            (SERVER_ID, SCENARIO_ID, country_id, crel),
        ).fetchall()
    return [dict(r) for r in rows]


def start_core_conversion(
    province_id: str, country_id: str, start_day: int, end_day: int
) -> None:
    """Begin a non-core → core conversion for a province."""
    db = _get_shared_war_db()
    db.upsert_province_core(
        SERVER_ID, SCENARIO_ID, province_id, country_id,
        is_core=0, conversion_start_day=start_day, conversion_end_day=end_day,
    )


def start_religion_conversion(
    province_id: str, from_religion: str, to_religion: str,
    start_day: int, end_day: int,
) -> None:
    """Begin a religion conversion for a province."""
    db = _get_shared_war_db()
    db.upsert_province_religion_conversion(
        SERVER_ID, SCENARIO_ID, province_id,
        from_religion, to_religion, start_day, end_day,
    )


def get_opponent_country(war_id: str, country_id: str) -> str | None:
    """Return the main opposing country (attacker vs defender) in a war."""
    db  = _get_shared_war_db()
    war = db.get_war(war_id)
    if war is None:
        return None
    war = dict(war)
    if war["attacker"] == country_id:
        return war["defender"]
    if war["defender"] == country_id:
        return war["attacker"]
    return None


def war_spend_take_province(
    war_id: str, winner: str, province_id: str,
    cost: float, current_day: int,
) -> dict:
    res = _get_war_system().spend_take_province(war_id, winner, province_id, cost, current_day)
    return {"ok": res.ok, "message": res.message,
            "effects": res.effects, "score_after": res.score_after}


def war_spend_puppet(
    war_id: str, winner: str, loser: str, cost: float, current_day: int,
) -> dict:
    res = _get_war_system().spend_puppet_state(war_id, winner, loser, cost, current_day)
    return {"ok": res.ok, "message": res.message,
            "effects": res.effects, "score_after": res.score_after}


def war_spend_reparations(
    war_id: str, winner: str, loser: str, cost: float, current_day: int,
) -> dict:
    res = _get_war_system().spend_reparations(war_id, winner, loser, cost, current_day)
    return {"ok": res.ok, "message": res.message,
            "effects": res.effects, "score_after": res.score_after}


def war_spend_insult(
    war_id: str, winner: str, loser: str, cost: float,
) -> dict:
    res = _get_war_system().spend_insult(war_id, winner, loser, cost)
    return {"ok": res.ok, "message": res.message,
            "effects": res.effects, "score_after": res.score_after}


def war_end(war_id: str, status: str = "attacker_victory") -> dict:
    db  = _get_shared_war_db()
    war = db.get_war(war_id)
    if war:
        participants  = db.get_war_participants(war_id)
        all_countries = {p["country_id"] for p in participants}
        all_countries.add(war["attacker"])
        all_countries.add(war["defender"])
        for cid in all_countries:
            row = db.get_country(SERVER_ID, SCENARIO_ID, cid)
            if row:
                eff = float(row.get("economy_efficiency") or 1.0)
                op  = int(row.get("population_opinion")   or 50)
                db.update_country_fields(
                    SERVER_ID, SCENARIO_ID, cid,
                    economy_efficiency=min(1.0, eff + 0.10),
                    population_opinion=min(100, op + 5),
                )
    msg = _get_war_system().end_war(war_id, status)
    return {"ok": True, "message": msg}


def initialize_province_religions() -> None:
    """Seed province_religions from country_religions for provinces missing an entry."""
    import sqlite3 as _sqlite3
    con = _write_conn()
    con.row_factory = _sqlite3.Row
    provinces = con.execute(
        "SELECT province_id, owner_country FROM provinces "
        "WHERE server_id=? AND scenario_id=?",
        (SERVER_ID, SCENARIO_ID),
    ).fetchall()
    for prov in provinces:
        pid   = prov["province_id"]
        owner = prov["owner_country"]
        if not owner:
            continue
        existing = con.execute(
            "SELECT 1 FROM province_religions "
            "WHERE server_id=? AND scenario_id=? AND province_id=?",
            (SERVER_ID, SCENARIO_ID, pid),
        ).fetchone()
        if existing:
            continue
        rel_row = con.execute(
            "SELECT religion FROM country_religions "
            "WHERE server_id=? AND scenario_id=? AND country_id=?",
            (SERVER_ID, SCENARIO_ID, owner),
        ).fetchone()
        if rel_row and rel_row["religion"]:
            con.execute(
                "INSERT OR IGNORE INTO province_religions "
                "(server_id, scenario_id, province_id, religion) VALUES (?,?,?,?)",
                (SERVER_ID, SCENARIO_ID, pid, rel_row["religion"]),
            )
    con.commit()
    con.close()


def get_detailed_armies(country_id: str) -> list[dict]:
    """Return all non-destroyed armies with movement and destination details."""
    import sqlite3 as _sqlite3
    with _conn() as con:
        con.row_factory = _sqlite3.Row
        rows = con.execute(
            """
            SELECT a.army_id, a.province_id, a.state, a.strength_pct,
                   a.destination_province_id, a.movement_end_day,
                   a.rowid,
                   p.province_name,
                   pd.province_name AS dest_name
            FROM armies a
            LEFT JOIN provinces p
              ON p.province_id  = a.province_id
             AND p.server_id    = a.server_id AND p.scenario_id = a.scenario_id
            LEFT JOIN provinces pd
              ON pd.province_id  = a.destination_province_id
             AND pd.server_id   = a.server_id AND pd.scenario_id = a.scenario_id
            WHERE a.server_id=? AND a.scenario_id=? AND a.country_id=?
              AND a.state NOT IN ('destroyed')
            ORDER BY a.rowid
            """,
            (SERVER_ID, SCENARIO_ID, country_id),
        ).fetchall()
    result = []
    for i, r in enumerate(rows, start=1):
        d = dict(r)
        d["army_num"] = i
        result.append(d)
    return result
