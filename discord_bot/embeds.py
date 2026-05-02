"""
Central place for all embed builders.
"""
from __future__ import annotations
import discord

COL_GOLD   = 0xC9A84C
COL_RED    = 0x8B1A1A
COL_GREEN  = 0x2E7D32
COL_BLUE   = 0x1565C0
COL_ORANGE = 0xD84315
COL_GREY   = 0x546E7A
COL_PURPLE = 0x4A148C
COL_TEAL   = 0x00695C

THUMB = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/"
    "Iron_Cross_-_black.svg/240px-Iron_Cross_-_black.svg.png"
)

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


def _fmt_pop(n: int | float) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


def _base(title: str, description: str, colour: int) -> discord.Embed:
    e = discord.Embed(title=title, description=description, colour=colour)
    e.set_thumbnail(url=THUMB)
    e.set_footer(text="WW1 Roleplay  •  prefix: rp")
    return e


# ── Help ──────────────────────────────────────────────────────────────────────

def help_embed() -> discord.Embed:
    e = _base(
        "📖  WW1 Roleplay — Command Reference",
        "All commands use the prefix **rp**.",
        COL_GOLD,
    )
    cmds = [
        ("rp help",                       "Show this help message."),
        ("rp start",                      "**Admin** — Choose a scenario and begin."),
        ("rp countries",                  "List all playable nations."),
        ("rp select `<country>`",         "Claim a country."),
        ("rp my_country / rp mc",         "View your country dashboard with sections."),
        ("rp speed",                      "**Admin** — View or change game speed."),
        ("rp invest pg",                  "Invest gold to boost population growth."),
        ("rp storage",                    "View your country's resource storage."),
        ("rp buildings",                  "Browse all constructable buildings."),
        ("rp construct `<building>`",     "Construct a building in one of your provinces."),
        ("rp technology",                 "Browse the technology tree and see research speed."),
        ("rp research `<tech/reform>`",   "Start or resume researching a technology or reform."),
        ("rp switch_research `<name>`",   "Pause current research and start a new one."),
        ("rp reforms",                    "View all reforms and their effects."),
        ("rp adopt `<reform>`",           "Adopt a researched reform (costs 100 gold)."),
        ("rp rr `<reform>`",              "Remove / unadopt an active reform."),
        ("rp taxation",                   "Set your tax policy (affects income & opinion)."),
        ("rp gm",                         "Open the Global Market to buy resources."),
        ("rp recruit_army / rp ra",       "Recruit an army in one of your provinces."),
        ("rp edit_diplomacy / rp ed",     "Manage diplomatic actions (improve, damage, war, alliance, gift, rivalry)."),
        ("rp check_diplomacy / rp cd",    "View your diplomacy overview and inspect per-country relations."),
    ]
    for name, desc in cmds:
        e.add_field(name=f"`{name}`", value=desc, inline=False)
    return e


# ── General error embeds ──────────────────────────────────────────────────────

def no_game_embed() -> discord.Embed:
    return _base(
        "⚠️  No Active Game",
        "No scenario is running in this server.\nAn **administrator** can use **`rp start`** to begin.",
        COL_GREY,
    )


def not_admin_embed(cmd: str) -> discord.Embed:
    return _base(
        "🔒  Administrator Only",
        f"**`{cmd}`** can only be used by members with **Administrator** permission.",
        COL_RED,
    )


def no_country_embed() -> discord.Embed:
    return _base(
        "❓  No Country Selected",
        "You haven't claimed a country yet.\n"
        "Use **`rp countries`** to browse, then **`rp select <name>`** to claim one.",
        COL_ORANGE,
    )


def select_error_embed(message: str) -> discord.Embed:
    return _base("❌  Error", message, COL_ORANGE)


def select_success_embed(user: discord.Member, country: dict) -> discord.Embed:
    emoji = RELIGION_EMOJI.get(country["religion"], "🏛️")
    return _base(
        "🎌  Country Claimed!",
        (
            f"{user.mention} is now playing as **{country['country_name']}**.\n\n"
            f"{emoji} **Religion:** {country['religion']}\n"
            f"👥 **Population:** {_fmt_pop(country['total_population'])}\n\n"
            "Use **`rp my_country`** to see your full dashboard."
        ),
        COL_GREEN,
    )


# ── rp start ─────────────────────────────────────────────────────────────────

def start_setup_embed() -> discord.Embed:
    return _base(
        "⚙️  Scenario Setup",
        "Set up a roleplay scenario before starting the gameplay.\n\n"
        "Use the dropdown below to choose your scenario.",
        COL_RED,
    )


def game_already_started_embed(scenario_label: str) -> discord.Embed:
    return _base(
        "🚫  Game Already Running",
        (
            f"A game of **{scenario_label}** is already in progress.\n\n"
            "• Use **`rp countries`** to see available nations.\n"
            "• Use **`rp select <name>`** to claim yours.\n"
            "• Use **`rp my_country`** if you've already picked one."
        ),
        COL_RED,
    )


def game_started_embed(scenario: str) -> discord.Embed:
    e = _base(
        "🎖️  Game Started!",
        (
            f"**Scenario:** {scenario}\n"
            f"**Starting Date:** 1 January, 1910\n\n"
            "The world stage is set. Empires will rise and fall.\n\n"
            "Use **`rp countries`** to view all available nations, "
            "then **`rp select <country>`** to claim yours."
        ),
        COL_GREEN,
    )
    e.set_image(
        url="https://upload.wikimedia.org/wikipedia/commons/thumb/0/07/"
            "Map_Europe_1914-en.svg/800px-Map_Europe_1914-en.svg.png"
    )
    return e


# ── rp clear ──────────────────────────────────────────────────────────────────

def clear_confirm_embed() -> discord.Embed:
    return _base(
        "⚠️  Reset Entire Game?",
        (
            "This will **permanently delete** the ongoing game for this server:\n\n"
            "• All country assignments will be cleared\n"
            "• All player selections will be reset\n"
            "• All investments will be lost\n"
            "• Game session and tick progress will be wiped\n\n"
            "**Players will need to use `rp start` and `rp select` again.**\n\n"
            "Are you sure?"
        ),
        COL_RED,
    )


def clear_success_embed() -> discord.Embed:
    return _base(
        "🗑️  Game Reset",
        "The game has been completely reset for this server.\n"
        "Use **`rp start`** to begin a new game.",
        COL_GREEN,
    )


def clear_cancelled_embed() -> discord.Embed:
    return _base("❌  Cancelled", "Game reset cancelled. The game continues.", COL_GREY)


def not_authorised_embed(cmd: str) -> discord.Embed:
    return _base(
        "🚫  Not Authorised",
        f"You are not authorised to use **`{cmd}`**.",
        COL_RED,
    )


# ── rp countries ─────────────────────────────────────────────────────────────

def countries_embed(
    countries: list[dict],
    assignments: dict[str, str],
    page: int,
    total_pages: int,
) -> discord.Embed:
    e = discord.Embed(
        title="🗺️  Playable Nations — WW1 Scenario (1910)",
        description=(
            "Choose a nation with **`rp select <country name>`**.\n"
            "🔒 = already taken by another player.\n"
        ),
        colour=COL_BLUE,
    )
    e.set_thumbnail(url=THUMB)
    for c in countries:
        emoji  = RELIGION_EMOJI.get(c["religion"], "🏛️")
        owner  = assignments.get(c["country_id"])
        status = f"🔒 *{owner}*" if owner else "✅ Available"
        e.add_field(
            name=c["country_name"],
            value=f"{emoji} {c['religion']}\n👥 {_fmt_pop(c['total_population'])}\n{status}",
            inline=True,
        )
    e.set_footer(text=f"WW1 Roleplay  •  prefix: rp  •  Page {page}/{total_pages}")
    return e


# ── rp speed ─────────────────────────────────────────────────────────────────

def speed_embed(current_value: str, options: list[dict]) -> discord.Embed:
    label_map = {o["value"]: o["label"] for o in options}
    current_label = label_map.get(current_value, current_value)
    return _base(
        "⏱️  Game Speed",
        f"Current speed: **{current_label}**\n\nSelect a new speed from the dropdown below.",
        COL_PURPLE,
    )


def speed_changed_embed(new_label: str) -> discord.Embed:
    return _base("✅  Speed Updated", f"Game speed set to **{new_label}**.", COL_GREEN)


# ── rp my_country ─────────────────────────────────────────────────────────────

def _mc_slim_header(country_name: str, owner: str, date: str) -> str:
    return f"**{country_name}**\n**Owner:** {owner}  •  **Date:** {date}"


def _opinion_emoji(opinion: int) -> str:
    if opinion >= 80:
        return "😄"
    if opinion >= 60:
        return "😊"
    if opinion >= 40:
        return "😐"
    if opinion >= 20:
        return "😟"
    return "😠"


def my_country_overview_embed(country: dict, owner: str, date: str) -> discord.Embed:
    rel_emoji = RELIGION_EMOJI.get(country.get("religion", ""), "🏛️")
    opinion   = country.get("population_opinion", 50)
    op_emoji  = _opinion_emoji(opinion)
    e = discord.Embed(title=f"🏛️  {country['country_name']}", colour=COL_GOLD)
    e.set_thumbnail(url=THUMB)
    e.add_field(name="Owner",        value=owner,                                         inline=True)
    e.add_field(name="Date",         value=date,                                          inline=True)
    e.add_field(name="Religion",     value=f"{rel_emoji} {country.get('religion','—')}",  inline=True)
    e.add_field(name="Treasury",     value=f"{country.get('treasury', 0):,.1f} gold",     inline=True)
    e.add_field(name="Daily Income", value=f"{country.get('daily_base_income', 0):+.2f} gold/day", inline=True)
    growth = country.get("population_growth_rate", 0.6)
    e.add_field(name="Pop. Growth",  value=f"{growth:.2f}%/month",                        inline=True)
    e.add_field(name="Pop. Opinion", value=f"{op_emoji} {opinion}/100",                   inline=True)
    e.add_field(
        name="ℹ️  Use the dropdown to explore",
        value="Provinces · Population · Resources · Military · Infrastructure",
        inline=False,
    )
    e.set_footer(text="Overview  •  WW1 Roleplay")
    return e


def my_country_provinces_embed(country: dict, owner: str, date: str,
                                provinces: list[dict]) -> discord.Embed:
    header = _mc_slim_header(country["country_name"], owner, date)
    lines  = [f"• {p['province_name']}" for p in provinces]
    e = discord.Embed(
        title=f"🗺️  Provinces — {country['country_name']}",
        description=header + f"\n\n**{len(provinces)} Provinces**\n" + "\n".join(lines[:40]),
        colour=COL_BLUE,
    )
    e.set_footer(text="Provinces  •  Use dropdown to switch section.")
    return e


def my_country_population_embed(country: dict, owner: str, date: str,
                                  provinces: list[dict]) -> discord.Embed:
    header = _mc_slim_header(country["country_name"], owner, date)
    total  = sum(p["population"] for p in provinces)
    growth = country.get("population_growth_rate", 0.6)
    lines  = [f"• **{p['province_name']}** — {_fmt_pop(p['population'])}" for p in provinces]
    e = discord.Embed(
        title=f"👥  Population — {country['country_name']}",
        description=(
            header
            + f"\n\n**Total Population:** {_fmt_pop(total)}\n"
            + f"**Monthly Growth Rate:** {growth:.2f}%\n\n"
            + "\n".join(lines[:35])
        ),
        colour=COL_GREEN,
    )
    e.set_footer(text="Population  •  Use dropdown to switch section.")
    return e


def my_country_resources_embed(country: dict, owner: str, date: str,
                                 provinces: list[dict]) -> discord.Embed:
    header = _mc_slim_header(country["country_name"], owner, date)
    by_res: dict[str, list[str]] = {}
    for p in provinces:
        res = (p.get("resource_type") or "none").lower()
        by_res.setdefault(res, []).append(p["province_name"])

    e = discord.Embed(
        title=f"⚙️  Resources — {country['country_name']}",
        description=header,
        colour=COL_ORANGE,
    )
    for res, pnames in sorted(by_res.items()):
        emoji = RESOURCE_EMOJI.get(res, "📦")
        e.add_field(
            name=f"{emoji}  {res.title()} ({len(pnames)})",
            value="\n".join(f"• {n}" for n in pnames),
            inline=True,
        )
    e.set_footer(text="Resources  •  Use dropdown to switch section.")
    return e


def my_country_military_embed(country: dict, owner: str, date: str,
                                army_data: dict) -> discord.Embed:
    header = _mc_slim_header(country["country_name"], owner, date)
    armies = army_data["armies"]
    total  = army_data["total_units"]

    if not armies:
        body = "*No army units currently deployed.\nRecruit troops to build your military force.*"
    else:
        lines = [f"**Total Deployed Units:** {total:,}\n"]
        for a in armies:
            state = a["state"]
            if state == "recruiting":
                rem  = a["days_remaining"]
                m, d = divmod(rem, 30)
                time_str = f"{m}m {d}d" if m else f"{d}d"
                lines.append(
                    f"🔨 **{a['army_label']}** — {a['province_name']} "
                    f"— *recruiting* (**{time_str} remaining**)"
                )
                for u in a["units"]:
                    lines.append(f"  ↳ {u['unit_name']}: {u['quantity']:,}")
            else:
                lines.append(
                    f"⚔️ **{a['army_label']}** — {a['province_name']} "
                    f"({a['strength_pct']:.0f}% strength) — **{a['unit_count']} units**"
                )
                for u in a["units"]:
                    lines.append(f"  ↳ {u['unit_name']}: {u['quantity']:,}")
        body = "\n".join(lines[:40])

    e = discord.Embed(
        title=f"⚔️  Military — {country['country_name']}",
        description=header + "\n\n" + body,
        colour=COL_RED,
    )
    e.set_footer(text="Military  •  Use dropdown to switch section.")
    return e


def my_country_infrastructure_embed(country: dict, owner: str, date: str,
                                      provinces: list[dict],
                                      buildings: dict[str, list[str]]) -> discord.Embed:
    header = _mc_slim_header(country["country_name"], owner, date)
    e = discord.Embed(
        title=f"🏗️  Infrastructure — {country['country_name']}",
        description=header,
        colour=COL_GREY,
    )
    for p in provinces:
        pname = p["province_name"]
        blist = buildings.get(pname, [])
        value = "\n".join(blist) if blist else "*No buildings*"
        e.add_field(name=f"🏗️  {pname}", value=value, inline=True)
    e.set_footer(text="Infrastructure  •  Use dropdown to switch section.")
    return e


# ── rp invest ────────────────────────────────────────────────────────────────

def invest_embed(country_name: str, current_rate: float,
                 next_cost: float, treasury: float, cap: float) -> discord.Embed:
    at_cap = (current_rate >= cap)
    e = _base(
        f"📈  Population Investment — {country_name}",
        (
            f"**Current Growth Rate:** {current_rate:.2f}%/month\n"
            f"**Investment Cap:** {cap:.1f}%/month\n"
            f"**Treasury:** {treasury:,.1f} gold\n\n"
            + (
                f"**Next Investment Cost:** {next_cost:,.0f} gold\n"
                f"**Growth after invest:** {min(current_rate + 0.05, cap):.2f}%/month\n\n"
                "Use **`rp invest pg`** to invest."
                if not at_cap else
                "✅ You have reached the **maximum growth rate**."
            )
        ),
        COL_GREEN,
    )
    return e


def invest_success_embed(country_name: str, gold_spent: float,
                          new_rate: float, next_cost: float) -> discord.Embed:
    return _base(
        "✅  Investment Successful",
        (
            f"**Country:** {country_name}\n"
            f"**Gold Spent:** {gold_spent:,.0f} gold\n"
            f"**New Growth Rate:** {new_rate:.2f}%/month\n"
            f"**Next Investment Cost:** {next_cost:,.0f} gold"
        ),
        COL_GREEN,
    )


# ── rp storage ───────────────────────────────────────────────────────────────

def storage_embed(country_name: str, owner: str, date: str,
                   storage: dict) -> discord.Embed:
    header = _mc_slim_header(country_name, owner, date)
    e = discord.Embed(
        title=f"📦  Storage — {country_name}",
        description=header + "\n\n*Note: Horses & Textiles give daily income only. Gems & Gold go directly to treasury.*",
        colour=COL_TEAL,
    )
    for res, qty in storage.items():
        emoji = RESOURCE_EMOJI.get(res, "📦")
        e.add_field(
            name=f"{emoji}  {res.replace('_',' ').title()}",
            value=f"{qty:,}",
            inline=True,
        )
    e.set_footer(text="Storage  •  WW1 Roleplay")
    return e


# ── rp buildings ─────────────────────────────────────────────────────────────

def buildings_list_embed(tier_label: str, buildings_data: list[dict],
                          page: int, total_pages: int) -> discord.Embed:
    e = discord.Embed(
        title=f"🏭  Buildings Catalogue — {tier_label}",
        description=f"Page {page}/{total_pages}  •  Use `rp construct <name>` to build.",
        colour=COL_PURPLE,
    )
    for b in buildings_data:
        res_line = ""
        if b.get("allowed_resources"):
            res_list = ", ".join(b["allowed_resources"])
            res_line = f"\n🔒 **Resource required:** {res_list}"
        cons_res  = b.get("construction_cost_resources", {})
        cons_line = ""
        if cons_res:
            parts = [f"{v} {k}" for k, v in cons_res.items()]
            cons_line = f"\n🧱 **Mats on build:** {', '.join(parts)}"
        prod      = b.get("production_resource") or b.get("gold_to_treasury_monthly")
        prod_line = (
            f"\n📤 **Monthly prod:** {b['monthly_production']} {b.get('production_unit','')} "
            f"{('→ ' + prod) if prod else ''}"
            if b["monthly_production"] > 0 else ""
        )
        income_line = f"\n💰 **Daily income:** {b['daily_income']:+.2f} gold/day" if b["daily_income"] > 0 else ""

        # Tech requirement note
        from ww1_economy.tech_data import BUILDING_TECH_REQUIREMENTS, TECH_TREE
        tech_req = BUILDING_TECH_REQUIREMENTS.get(b["name"])
        tech_line = ""
        if tech_req and tech_req in TECH_TREE:
            tech_line = f"\n🔬 **Requires tech:** {TECH_TREE[tech_req].name}"

        e.add_field(
            name=f"**{b['name']}**  ({b['tier']})",
            value=(
                f"💲 **Cost:** {b['cost']:.0f} gold"
                f"\n⏱️ **Build time:** {b['months']} months"
                + income_line
                + prod_line
                + res_line
                + cons_line
                + tech_line
            ),
            inline=False,
        )
    e.set_footer(text="WW1 Roleplay  •  rp buildings")
    return e


# ── rp construct ─────────────────────────────────────────────────────────────

def construct_info_embed(building: dict, country_name: str,
                          compatible_provinces: list[dict]) -> discord.Embed:
    cons_res  = building.get("construction_cost_resources", {})
    cons_line = ""
    if cons_res:
        parts = [f"{v} {k}" for k, v in cons_res.items()]
        cons_line = f"\n🧱 **Mats required:** {', '.join(parts)}"
    prod      = building.get("production_resource")
    prod_line = (
        f"\n📤 **Produces:** {building['monthly_production']} "
        f"{building.get('production_unit','')} {prod or ''}/month"
        if building["monthly_production"] > 0 else ""
    )
    income_line = f"\n💰 **Daily income:** {building['daily_income']:+.2f} gold/day" if building["daily_income"] > 0 else ""
    res_note = ""
    if building.get("allowed_resources"):
        res_list = ", ".join(building["allowed_resources"])
        res_note = f"\n\n⚠️ Tier 1 building — province must have: **{res_list}**"
        if not compatible_provinces:
            res_note += "\n\n❌ **None of your provinces have the required resource!**"
    e = _base(
        f"🏗️  Construct: {building['name']}",
        (
            f"💲 **Cost:** {building['cost']:.0f} gold\n"
            f"⏱️ **Build time:** {building['months']} months"
            + income_line
            + prod_line
            + cons_line
            + res_note
            + "\n\nSelect the province(s) to build in below."
        ),
        COL_PURPLE,
    )
    return e


def construct_tech_locked_embed(building_name: str, required_tech: str) -> discord.Embed:
    return _base(
        "🔒  Technology Required",
        (
            f"**{building_name}** cannot be built yet.\n\n"
            f"You need to research **{required_tech}** first.\n"
            "Use **`rp technology`** to see the tech tree and **`rp research <name>`** to start."
        ),
        COL_RED,
    )


def construct_confirm_embed(building_name: str, provinces: list[str],
                             total_gold: float, cons_resources: dict[str, int],
                             months: int) -> discord.Embed:
    e = _base(
        "🔨  Confirm Construction",
        (
            f"**Building:** {building_name}\n"
            f"**Provinces ({len(provinces)}):** {', '.join(provinces)}\n"
            f"**Construction Time:** {months} months each\n"
            f"💲 **Total Gold Cost:** {total_gold:,.0f} gold"
            + (
                f"\n🧱 **Resources per province:** "
                + ", ".join(f"{v} {k}" for k, v in cons_resources.items())
                if cons_resources else ""
            )
            + "\n\nClick **Construct** to begin, or **Cancel** to go back."
        ),
        COL_ORANGE,
    )
    return e


def construct_success_embed(building_name: str, provinces: list[str],
                              gold_spent: float, completion_days: int) -> discord.Embed:
    return _base(
        "✅  Construction Started!",
        (
            f"**{building_name}** is now under construction in:\n"
            + "\n".join(f"• {p}" for p in provinces)
            + f"\n\n💲 **Gold spent:** {gold_spent:,.0f}\n"
            f"⏱️ **Completes in:** {completion_days} game-days"
        ),
        COL_GREEN,
    )


def construct_error_embed(reason: str) -> discord.Embed:
    return _base("❌  Construction Failed", reason, COL_RED)


# ── rp technology ────────────────────────────────────────────────────────────

def technology_main_embed(
    country_name: str,
    owner: str,
    date: str,
    research_speed: float,
    active_research: dict | None,
) -> discord.Embed:
    if active_research:
        rtype  = active_research["type"].title()
        rid    = active_research["tech_id"]
        pct    = active_research["pct_done"]
        rem    = active_research["remaining_days"]
        months = rem // 30
        days   = rem % 30
        time_str = f"{months}m {days}d" if months else f"{days}d"
        research_line = f"🔬 **{rid.replace('_',' ').title()}** ({rtype}) — {pct}% done, {time_str} left"
    else:
        research_line = "*Nothing being researched.*"

    e = _base(
        f"🔬  Technology — {country_name}",
        (
            f"**Owner:** {owner}  •  **Date:** {date}\n\n"
            f"📊 **Research Speed:** {research_speed:.1f}%/month\n"
            f"🔬 **Currently Researching:** {research_line}\n\n"
            "Select a category below to explore the technology tree."
        ),
        COL_PURPLE,
    )
    return e


def tech_tree_embed(
    country_name: str,
    category: str,
    items: list[dict],
    page: int,
    total_pages: int,
    tech_status: dict,
    paused_ids: set,
) -> discord.Embed:
    """
    items: list of {tech_id, name, duration_months, prerequisites, description}
    tech_status: {tech_id: row_dict}  — from DB
    paused_ids: set of tech_ids that are paused
    """
    CAT_EMOJI = {
        "Economic":       "📊",
        "Infrastructure": "🏗️",
        "Reforms":        "📜",
        "Military":       "⚔️",
    }
    emoji = CAT_EMOJI.get(category, "🔬")
    e = discord.Embed(
        title=f"{emoji}  {category} — {country_name}",
        description=f"Page {page}/{total_pages}  •  Use `rp research <name>` to start.",
        colour=COL_PURPLE,
    )

    LEGEND = "✅ Unlocked  •  🔬 Researching  •  ⏸ Paused  •  📜 Available  •  🔒 Locked"
    e.set_footer(text=LEGEND)

    for item in items:
        tid    = item["tech_id"]
        name   = item["name"]
        dur_m  = item.get("duration_months", 0)
        prereqs = item.get("prerequisites", ())
        descr  = item.get("description", "")
        row    = tech_status.get(tid, {})

        is_unlocked    = bool(row.get("is_unlocked", False))
        # Guard: if unlocked, never show as researching even if DB flag is stale
        is_researching = bool(row.get("is_researching", False)) and not is_unlocked
        is_paused      = tid in paused_ids and not is_unlocked

        if is_unlocked:
            icon = "✅"
        elif is_researching:
            icon = "🔬"
        elif is_paused:
            icon = "⏸"
        elif prereqs:
            icon = "🔒"
        else:
            icon = "📜"

        extra = ""
        if is_researching and row:
            extra = " — *researching*"
        elif is_paused:
            extra = f" — *paused*"

        prereq_str = ""
        if prereqs and not is_unlocked:
            prereq_str = f"\n  ↳ Requires: {', '.join(p.replace('_',' ').title() for p in prereqs)}"

        desc_line = f"\n  {descr}" if descr else ""

        e.add_field(
            name=f"{icon}  {name}",
            value=f"⏱️ {dur_m} months{extra}{desc_line}{prereq_str}",
            inline=False,
        )

    return e


# ── rp research ──────────────────────────────────────────────────────────────

def research_started_embed(
    tech_name: str,
    duration_days: int,
    speed_pct: float,
    is_resume: bool = False,
) -> discord.Embed:
    months = duration_days // 30
    days   = duration_days % 30
    time_str = f"{months} months" if not days else f"{months}m {days}d"
    action = "Resumed" if is_resume else "Started"
    return _base(
        f"🔬  Research {action}!",
        (
            f"**Technology:** {tech_name}\n"
            f"**Time Remaining:** {time_str}\n"
            f"**Research Speed:** {speed_pct:.1f}%/month\n\n"
            "Use **`rp technology`** to track progress."
        ),
        COL_GREEN,
    )


def research_error_embed(reason: str) -> discord.Embed:
    return _base("❌  Research Failed", reason, COL_RED)


def switch_research_embed(
    old_name: str,
    old_remaining_days: int,
    new_name: str,
    new_duration_days: int,
    speed_pct: float,
) -> discord.Embed:
    old_m = old_remaining_days // 30
    old_d = old_remaining_days % 30
    new_m = new_duration_days  // 30
    new_d = new_duration_days  % 30
    old_str = f"{old_m}m {old_d}d" if old_m else f"{old_d}d"
    new_str = f"{new_m} months" if not new_d else f"{new_m}m {new_d}d"
    return _base(
        "🔄  Research Switched",
        (
            f"⏸ **Paused:** {old_name} *(had {old_str} remaining — saved)*\n\n"
            f"🔬 **Now Researching:** {new_name}\n"
            f"⏱️ **Duration:** {new_str}\n"
            f"📊 **Speed:** {speed_pct:.1f}%/month\n\n"
            f"Resume **{old_name}** later with `rp research {old_name.lower().replace(' ', '_')}`."
        ),
        COL_PURPLE,
    )


# ── rp reforms ───────────────────────────────────────────────────────────────

def reforms_embed(
    country_name: str,
    owner: str,
    date: str,
    reforms: list[dict],
    adopted_ids: set[str],
    adopted_count: int,
) -> discord.Embed:
    from ww1_economy.tech_data import MAX_ADOPTED_REFORMS, REFORM_ADOPTION_COST
    e = discord.Embed(
        title=f"📜  Reforms — {country_name}",
        description=(
            f"**Owner:** {owner}  •  **Date:** {date}\n"
            f"**Adopted:** {adopted_count}/{MAX_ADOPTED_REFORMS}  "
            f"•  **Adoption Cost:** {REFORM_ADOPTION_COST:.0f} gold\n\n"
            "✅ Adopted  •  📜 Researched (can adopt)  •  🔬 Researching  •  🔒 Not yet researched"
        ),
        colour=COL_TEAL,
    )

    for r in reforms:
        rid       = r["reform_id"]
        name      = r["name"]
        dur_m     = r["duration_months"]
        is_adopted = rid in adopted_ids
        row_status = r.get("_status", {})
        is_unlocked    = bool(row_status.get("is_unlocked", False))
        is_researching = bool(row_status.get("is_researching", False))
        prereqs        = r.get("prerequisites", ())

        if is_adopted:
            icon = "✅"
        elif is_unlocked:
            icon = "📜"
        elif is_researching:
            icon = "🔬"
        elif prereqs:
            icon = "🔒"
        else:
            icon = "📝"

        effects = []
        if r.get("opinion_bonus"):
            effects.append(f"Opinion +{r['opinion_bonus']}")
        if r.get("economy_efficiency_pct"):
            effects.append(f"Efficiency {r['economy_efficiency_pct']:+.0f}%")
        if r.get("recruitment_cost_pct"):
            effects.append(f"Recruit cost {r['recruitment_cost_pct']:+.0f}%")
        if r.get("population_growth_pct"):
            effects.append(f"Pop growth {r['population_growth_pct']:+.0f}%")
        if r.get("non_core_conversion_cost_pct"):
            effects.append(f"Core cost {r['non_core_conversion_cost_pct']:+.0f}%")
        if r.get("blocks_war_declaration"):
            effects.append("Cannot declare war")

        effects_str = ", ".join(effects) if effects else "Governance bonus"
        prereq_str  = f"\n  ↳ Requires: {', '.join(prereqs)}" if prereqs and not is_unlocked else ""

        e.add_field(
            name=f"{icon}  {name}",
            value=f"⏱️ {dur_m} months  •  🎯 {effects_str}{prereq_str}",
            inline=False,
        )

    e.set_footer(text="WW1 Roleplay  •  rp adopt <reform> to adopt")
    return e


def adopt_success_embed(reform_name: str, gold_spent: float,
                         new_treasury: float, adopted_count: int) -> discord.Embed:
    from ww1_economy.tech_data import MAX_ADOPTED_REFORMS
    return _base(
        "✅  Reform Adopted!",
        (
            f"**Reform:** {reform_name}\n"
            f"💲 **Gold Spent:** {gold_spent:.0f}\n"
            f"💰 **Treasury:** {new_treasury:,.1f} gold\n"
            f"📜 **Adopted:** {adopted_count}/{MAX_ADOPTED_REFORMS}"
        ),
        COL_GREEN,
    )


def adopt_error_embed(reason: str) -> discord.Embed:
    return _base("❌  Adoption Failed", reason, COL_RED)


# ── rp remove reforms ────────────────────────────────────────────────────────

def remove_reform_success_embed(reform_name: str, adopted_count: int) -> discord.Embed:
    from ww1_economy.tech_data import MAX_ADOPTED_REFORMS
    return _base(
        "🗑️  Reform Removed",
        (
            f"**{reform_name}** has been unadopted.\n\n"
            f"The reform's opinion bonus has been reversed.\n"
            f"📜 **Adopted reforms:** {adopted_count}/{MAX_ADOPTED_REFORMS}\n\n"
            "You can re-adopt it later with **`rp adopt <reform>`**."
        ),
        COL_ORANGE,
    )


def remove_reform_error_embed(reason: str) -> discord.Embed:
    return _base("❌  Remove Reform Failed", reason, COL_RED)


# ── rp gm — Global Market ────────────────────────────────────────────────────

def global_market_embed(market_rows: list[dict]) -> discord.Embed:
    e = discord.Embed(
        title="🌐  Global Market",
        description=(
            "Buy resources from the international market.\n"
            "Prices shift with demand — high demand raises prices, low demand lowers them.\n"
            "⚠️ Resources in **shortage** cannot be purchased.\n\n"
            "Select a resource below to begin a purchase."
        ),
        colour=COL_TEAL,
    )
    e.set_thumbnail(url=THUMB)

    row_map = {r["resource_name"]: r for r in market_rows}

    TIER1 = ["iron", "coal", "copper", "stone", "wood", "rubber",
             "grain", "meat", "cotton", "oil"]
    TIER2 = ["chemicals", "gunpowder", "ammunition", "medicines"]

    def _res_line(res: str) -> str:
        row = row_map.get(res)
        if row is None:
            from ww1_economy.resources import MARKET_BASE_PRICES
            price = MARKET_BASE_PRICES.get(res, 0.0)
            shortage = False
        else:
            price    = float(row["current_price"])
            shortage = bool(int(row.get("shortage") or 0))
        emoji  = RESOURCE_EMOJI.get(res, "📦")
        status = "  🚫 *Shortage*" if shortage else ""
        return f"{emoji} **{res.title()}** — {price:.1f} gold/unit{status}"

    t1_lines = "\n".join(_res_line(r) for r in TIER1)
    t2_lines = "\n".join(_res_line(r) for r in TIER2)

    e.add_field(name="⛏️  Tier 1 — Raw Resources", value=t1_lines, inline=False)
    e.add_field(name="🏭  Tier 2 — Finished Goods",  value=t2_lines, inline=False)
    e.set_footer(text="Prices update monthly based on demand  •  WW1 Roleplay")
    return e


def market_buy_confirm_embed(
    resource: str,
    quantity: int,
    unit_price: float,
    total_cost: float,
    treasury: float,
) -> discord.Embed:
    emoji   = RESOURCE_EMOJI.get(resource, "📦")
    afford  = treasury >= total_cost
    status  = f"✅ You can afford this." if afford else f"❌ **Insufficient gold** (need {total_cost:,.1f}, have {treasury:,.1f})."
    return _base(
        "🛒  Confirm Purchase",
        (
            f"{emoji} **Resource:** {resource.title()}\n"
            f"📦 **Quantity:** {quantity:,} units\n"
            f"💲 **Unit Price:** {unit_price:.1f} gold\n"
            f"💰 **Total Cost:** {total_cost:,.1f} gold\n"
            f"🏦 **Your Treasury:** {treasury:,.1f} gold\n\n"
            f"{status}\n\n"
            "Click **Buy** to confirm or **Cancel** to abort."
        ),
        COL_GREEN if afford else COL_RED,
    )


def market_buy_success_embed(
    resource: str,
    quantity: int,
    total_cost: float,
    new_treasury: float,
    new_storage: int,
) -> discord.Embed:
    emoji = RESOURCE_EMOJI.get(resource, "📦")
    return _base(
        "✅  Purchase Complete!",
        (
            f"{emoji} **{quantity:,}× {resource.title()}** purchased.\n\n"
            f"💲 **Gold Spent:** {total_cost:,.1f}\n"
            f"💰 **Treasury Remaining:** {new_treasury:,.1f} gold\n"
            f"📦 **{resource.title()} in Storage:** {new_storage:,} units"
        ),
        COL_GREEN,
    )


def market_buy_error_embed(reason: str) -> discord.Embed:
    return _base("❌  Purchase Failed", reason, COL_RED)


# ── Taxation ──────────────────────────────────────────────────────────────────

_TAX_EMOJI: dict[str, str] = {
    "tax_exemption":      "⚪",
    "light_contribution": "🟢",
    "standard":           "🔵",
    "elevated":           "🟠",
    "war_levy":           "🔴",
}


def taxation_embed(
    country_name:       str,
    tiers:              list[dict],
    current_tax_key:    str,
    current_opinion:    int,
    current_efficiency: float,
) -> discord.Embed:
    e = _base(
        "🪙  Taxation Policy",
        f"**{country_name}** — Select your tax level from the dropdown below.\n"
        "Only one tier can be active at a time.",
        COL_GOLD,
    )

    lines = []
    for tier in tiers:
        key    = tier["key"]
        emoji  = _TAX_EMOJI.get(key, "⚫")
        op     = tier["opinion"]
        op_str = f"+{op}" if op > 0 else str(op)
        marker = "  ◄ **Active**" if key == current_tax_key else ""
        lines.append(f"{emoji} **{tier['label']}** — Opinion `{op_str}`{marker}")

    e.add_field(name="Tax Tiers", value="\n".join(lines), inline=False)
    e.add_field(
        name="📊 Current Opinion",
        value=f"`{current_opinion}/100`",
        inline=True,
    )
    e.add_field(
        name="⚙️ Economy Efficiency",
        value=f"`{current_efficiency * 100:.1f}%`",
        inline=True,
    )
    e.set_footer(text="Use the dropdown to change tax policy  •  WW1 Roleplay")
    return e


def taxation_changed_embed(
    tier:       dict,
    opinion:    int,
    efficiency: float,
) -> discord.Embed:
    key    = tier["key"]
    emoji  = _TAX_EMOJI.get(key, "⚫")
    op     = tier["opinion"]
    op_str = f"+{op}" if op > 0 else str(op)

    lines = [
        f"{emoji} Tax policy set to **{tier['label']}**",
        "",
        f"👥 **Opinion change:** `{op_str}`",
        f"📊 **New opinion:** `{opinion}/100`",
        f"⚙️ **Economy Efficiency:** `{efficiency * 100:.1f}%`",
        "",
        f"💰 **Income modifier:** `×{tier['multiplier']:.2f}`",
    ]
    return _base("✅  Tax Policy Updated", "\n".join(lines), COL_GREEN)


# ── rp recruit_army ───────────────────────────────────────────────────────────

_SLOT_SECTION_HEADERS: dict[str, str | None] = {
    "F1":  "**Front Line**",
    "F2":  None,
    "FL1": "**Flank Line**",
    "S1":  "**Support Line**",
    "S2":  None,
    "N1":  "**Naval Line**",
}
_SLOT_ORDER = ["F1", "F2", "FL1", "S1", "S2", "N1"]


def recruit_province_embed(country_name: str, province_count: int) -> discord.Embed:
    return _base(
        "🏰  Select Province — Army Recruitment",
        (
            f"**{country_name}** — choose a province to station your new army.\n\n"
            f"You control **{province_count}** province(s).\n\n"
            "Select one from the dropdown below."
        ),
        COL_RED,
    )


def recruit_units_embed(
    country_name:  str,
    province_name: str,
    slot_units:    dict,
    quantities:    dict,
) -> discord.Embed:
    lines: list[str] = [f"**Province:** {province_name}\n"]
    last_section: str | None = None

    for slot in _SLOT_ORDER:
        header = _SLOT_SECTION_HEADERS.get(slot)
        if header and header != last_section:
            lines.append(header)
            last_section = header

        if slot not in slot_units:
            lines.append(f"`{slot}` — *Not unlocked*")
            continue

        unit = slot_units[slot]
        name = unit["unit_name"]
        g    = float(unit["gold_cost"])
        p    = int(unit["population_required"])
        d    = int(unit["recruitment_time_days"])
        qty  = quantities.get(slot)

        if qty:
            lines.append(
                f"`{slot}` ✅ **{name}** × {qty}"
                f"  —  {g * qty:,.0f} 💰 / {p * qty:,} 👥 / {d * qty}d ⏱️"
            )
        else:
            lines.append(
                f"`{slot}` **{name}**"
                f"  —  {g:,.0f} 💰 / {p} 👥 / {d}d ⏱️  *per unit*"
            )

    lines.append("")
    if quantities:
        lines.append("*Select more categories or click **Continue** when ready.*")
    else:
        lines.append("*Select unit categories below, then enter quantities in chat.*")

    return _base("⚔️  Army Recruitment — Unit Selection", "\n".join(lines), COL_RED)


def recruit_summary_embed(
    country_name:  str,
    province_name: str,
    selections:    dict,
    total_gold:    float,
    total_pop:     int,
    total_days:    int,
    treasury:      float,
    penalty:       bool,
) -> discord.Embed:
    unit_lines: list[str] = []
    for slot in _SLOT_ORDER:
        if slot not in selections:
            continue
        sel = selections[slot]
        unit_lines.append(f"`{slot}` **{sel['unit_name']}** × {sel['qty']}")

    penalty_note = (
        "\n\n⚠️ **Over-recruitment penalty active** (>25% cap used)\n"
        "Cost ×3 and time ×1.5 have been applied."
    ) if penalty else ""

    return _base(
        "📋  Recruitment Summary",
        (
            f"**Country:** {country_name}\n"
            f"**Province:** {province_name}\n\n"
            "**Units to recruit:**\n"
            + "\n".join(unit_lines)
            + f"\n\n💰 **Gold Cost:** {total_gold:,.0f}  *(Treasury: {treasury:,.0f})*\n"
            f"👥 **Population drafted:** {total_pop:,}\n"
            f"⏱️ **Recruitment Time:** {total_days} days"
            + penalty_note
            + "\n\nClick **Start Recruitment** to confirm, or **Cancel** to abort."
        ),
        COL_ORANGE,
    )


def recruit_started_embed(
    province_name: str,
    selections:    dict,
    total_gold:    float,
    total_pop:     int,
    total_days:    int,
) -> discord.Embed:
    unit_lines: list[str] = []
    for slot in _SLOT_ORDER:
        if slot not in selections:
            continue
        sel = selections[slot]
        unit_lines.append(f"`{slot}` {sel['unit_name']} × {sel['qty']}")

    return _base(
        "✅  Army Recruitment Started!",
        (
            f"**Province:** {province_name}\n\n"
            "**Recruiting:**\n"
            + "\n".join(unit_lines)
            + f"\n\n💰 **Gold spent:** {total_gold:,.0f}\n"
            f"👥 **Population drafted:** {total_pop:,}\n"
            f"⏱️ **Completes in:** {total_days} game-days\n\n"
            "*Army status: **recruiting**. It will be ready once the timer expires.*"
        ),
        COL_GREEN,
    )


def recruit_error_embed(reason: str) -> discord.Embed:
    return _base("❌  Recruitment Failed", reason, COL_RED)


def recruit_no_units_embed(country_name: str) -> discord.Embed:
    return _base(
        "🔒  No Units Available",
        (
            f"**{country_name}** has no unlocked military units to recruit.\n\n"
            "Research military technologies to unlock units.\n"
            "Use **`rp technology`** and browse the **Military** category."
        ),
        COL_GREY,
    )


# ── Diplomacy embeds ──────────────────────────────────────────────────────────

_DIPLO_ACTIONS = {
    "improve":   ("📈", "Improve Relations",  "+5 relations per month with the selected country"),
    "damage":    ("📉", "Damage Relations",   "−5 relations per month with the selected country"),
    "rivalry":   ("🗡️",  "Declare Rivalry",    "−10 relations instantly; blocks improvement on both sides"),
    "alliance":  ("🤝", "Propose Alliance",   "Form an alliance (requires 80+ relations)"),
    "war":       ("⚔️",  "Declare War",        "Declare war on a country (requires < 20 relations)"),
    "gift":      ("🎁", "Send Gift",          "−40 gold → target treasury, +5 relations instantly"),
}


def diplo_main_embed(country_name: str) -> discord.Embed:
    e = _base(
        f"⚖️  Diplomacy — {country_name}",
        "Select a diplomatic action from the dropdown below.",
        COL_BLUE,
    )
    for key, (emoji, label, desc) in _DIPLO_ACTIONS.items():
        e.add_field(name=f"{emoji} {label}", value=desc, inline=False)
    return e


def diplo_country_select_embed(action_key: str, country_name: str) -> discord.Embed:
    emoji, label, desc = _DIPLO_ACTIONS[action_key]
    return _base(
        f"{emoji} {label} — Select Country",
        f"**{country_name}** is performing: _{desc}_\n\nChoose a target country below.",
        COL_BLUE,
    )


def diplo_result_embed(ok: bool, title: str, body: str) -> discord.Embed:
    colour = COL_GREEN if ok else COL_RED
    icon   = "✅" if ok else "❌"
    return _base(f"{icon}  {title}", body, colour)


def check_diplomacy_embed(
    country_name: str,
    country_id:   str,
    friendly:     dict[str, float],
    unfriendly:   dict[str, float],
    our_rivals:   list[str],
    rivaled_by:   list[str],
    allies:       list[str],
    wars:         list[dict],
    name_map:     dict[str, str],
) -> discord.Embed:
    e = _base(
        f"🌍  Diplomacy Overview — {country_name}",
        "A summary of your current diplomatic standing.",
        COL_TEAL,
    )

    def _names(ids: list[str] | dict) -> str:
        if isinstance(ids, dict):
            parts = [f"**{name_map.get(cid, cid)}** `{v:.0f}`" for cid, v in ids.items()]
        else:
            parts = [f"**{name_map.get(cid, cid)}**" for cid in ids]
        return ", ".join(parts) if parts else "_None_"

    e.add_field(name="🟢 Friendly (>60)", value=_names(friendly),   inline=False)
    e.add_field(name="🔴 Unfriendly (<30)", value=_names(unfriendly), inline=False)
    e.add_field(name="🗡️ Rivals You Declared", value=_names(our_rivals),  inline=True)
    e.add_field(name="🗡️ Rivaled By",          value=_names(rivaled_by),  inline=True)
    e.add_field(name="🤝 Alliances", value=_names(allies), inline=False)

    if wars:
        war_lines = []
        for w in wars:
            atk = name_map.get(w["attacker"], w["attacker"])
            dfn = name_map.get(w["defender"], w["defender"])
            war_lines.append(f"⚔️ **{atk}** vs **{dfn}**")
        e.add_field(name="⚔️ Ongoing Wars", value="\n".join(war_lines), inline=False)
    else:
        e.add_field(name="⚔️ Ongoing Wars", value="_None_", inline=False)

    e.set_footer(text="WW1 Roleplay  •  Select a country below to view full details")
    return e


def diplo_country_detail_embed(
    my_country_name:     str,
    target_country_name: str,
    relation:            float,
    is_rival_us:         bool,
    is_rival_them:       bool,
    is_allied:           bool,
    at_war:              bool,
    improve_active:      bool,
    damage_active:       bool,
) -> discord.Embed:
    if at_war:
        colour = COL_RED
    elif relation >= 70:
        colour = COL_GREEN
    elif relation < 30:
        colour = COL_ORANGE
    else:
        colour = COL_GOLD

    # Relation bar (10 blocks)
    filled = round(relation / 10)
    bar    = "█" * filled + "░" * (10 - filled)

    lines = [
        f"Relations: **{relation:.0f} / 100**",
        f"`[{bar}]`",
        "",
    ]
    statuses = []
    if at_war:
        statuses.append("⚔️ **AT WAR**")
    if is_allied:
        statuses.append("🤝 **Allied**")
    if is_rival_us:
        statuses.append("🗡️ You declared rivalry")
    if is_rival_them:
        statuses.append("🗡️ They declared rivalry against you")
    if improve_active:
        statuses.append("📈 Improving relations (+5/month)")
    if damage_active:
        statuses.append("📉 Damaging relations (−5/month)")
    if not statuses:
        statuses.append("😐 No special status")

    lines += statuses

    return _base(
        f"🔍 {my_country_name} ↔ {target_country_name}",
        "\n".join(lines),
        colour,
    )


def diplo_help_entries() -> list[tuple[str, str]]:
    return [
        ("rp edit_diplomacy / rp ed", "Manage diplomatic actions (improve, damage, war, alliance, gift, rivalry)."),
        ("rp check_diplomacy / rp cd", "View your diplomatic overview and inspect relations with specific countries."),
    ]
