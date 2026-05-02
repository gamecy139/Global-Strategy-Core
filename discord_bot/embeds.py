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
    "rubber": "🧪", "copper": "🔶", "horses": "🐎", "stone": "🪨",
    "gems": "💎",
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
        ("rp help",                     "Show this help message."),
        ("rp start",                    "**Admin** — Choose a scenario and begin."),
        ("rp countries",                "List all playable nations."),
        ("rp select `<country>`",       "Claim a country."),
        ("rp my_country / rp mc",       "View your country dashboard with sections."),
        ("rp speed",                    "**Admin** — View or change game speed."),
        ("rp invest pg",                "Invest gold to boost population growth."),
        ("rp storage",                  "View your country's resource storage."),
        ("rp buildings",                "Browse all constructable buildings."),
        ("rp construct `<building>`",   "Construct a building in one of your provinces."),
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
    """Short header for non-overview sections."""
    return f"**{country_name}**\n**Owner:** {owner}  •  **Date:** {date}"


def my_country_overview_embed(country: dict, owner: str, date: str) -> discord.Embed:
    rel_emoji = RELIGION_EMOJI.get(country.get("religion", ""), "🏛️")
    e = discord.Embed(title=f"🏛️  {country['country_name']}", colour=COL_GOLD)
    e.set_thumbnail(url=THUMB)
    e.add_field(name="Owner",        value=owner,                                         inline=True)
    e.add_field(name="Date",         value=date,                                          inline=True)
    e.add_field(name="Religion",     value=f"{rel_emoji} {country.get('religion','—')}",  inline=True)
    e.add_field(name="Treasury",     value=f"{country.get('treasury', 0):,.1f} gold",     inline=True)
    e.add_field(name="Daily Income", value=f"{country.get('daily_base_income', 0):+.2f} gold/day", inline=True)
    growth = country.get("population_growth_rate", 0.6)
    e.add_field(name="Pop. Growth",  value=f"{growth:.2f}%/month",                        inline=True)
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
        lines = [f"**Total Units:** {total:,}\n"]
        for a in armies:
            lines.append(
                f"**Army `{a['army_id']}`** — Province {a['province_id']} "
                f"({a['strength_pct']:.0f}% strength) — **{a['unit_count']} units**"
            )
            for u in a["units"]:
                lines.append(f"  ↳ {u['unit_name']}: {u['quantity']:,}")
        body = "\n".join(lines[:30])

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
    RESOURCE_EMOJI_LOCAL = {
        "coal": "🪨", "iron": "⚙️", "gold": "🪙", "grain": "🌾",
        "meat": "🥩", "wood": "🪵", "oil": "🛢️", "cotton": "🧶",
        "rubber": "🧪", "copper": "🔶", "horses": "🐎", "stone": "🪨",
        "gems": "💎", "textiles": "🧵", "chemicals": "⚗️",
        "gunpowder": "💣", "ammunition": "🔫", "medicines": "💊",
    }
    header = _mc_slim_header(country_name, owner, date)
    e = discord.Embed(
        title=f"📦  Storage — {country_name}",
        description=header,
        colour=COL_TEAL,
    )
    for res, qty in storage.items():
        emoji = RESOURCE_EMOJI_LOCAL.get(res, "📦")
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
        cons_res = b.get("construction_cost_resources", {})
        cons_line = ""
        if cons_res:
            parts = [f"{v} {k}" for k, v in cons_res.items()]
            cons_line = f"\n🧱 **Mats on build:** {', '.join(parts)}"
        prod = b.get("production_resource") or b.get("gold_to_treasury_monthly")
        prod_line = f"\n📤 **Monthly prod:** {b['monthly_production']} {b.get('production_unit','')} {('→ ' + prod) if prod else ''}" if b["monthly_production"] > 0 else ""
        income_line = f"\n💰 **Daily income:** {b['daily_income']:+.2f} gold/day" if b["daily_income"] > 0 else ""
        e.add_field(
            name=f"**{b['name']}**  ({b['tier']})",
            value=(
                f"💲 **Cost:** {b['cost']:.0f} gold"
                f"\n⏱️ **Build time:** {b['months']} months"
                + income_line
                + prod_line
                + res_line
                + cons_line
            ),
            inline=False,
        )
    e.set_footer(text="WW1 Roleplay  •  rp buildings")
    return e


# ── rp construct ─────────────────────────────────────────────────────────────

def construct_info_embed(building: dict, country_name: str,
                          compatible_provinces: list[dict]) -> discord.Embed:
    cons_res = building.get("construction_cost_resources", {})
    cons_line = ""
    if cons_res:
        parts = [f"{v} {k}" for k, v in cons_res.items()]
        cons_line = f"\n🧱 **Mats required:** {', '.join(parts)}"
    prod = building.get("production_resource")
    prod_line = f"\n📤 **Produces:** {building['monthly_production']} {building.get('production_unit','')} {prod or ''}/month" if building["monthly_production"] > 0 else ""
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


def construct_confirm_embed(building_name: str, provinces: list[str],
                             total_gold: float, cons_resources: dict[str, int],
                             months: int) -> discord.Embed:
    res_line = ""
    if cons_resources:
        parts = [f"{v} {k}" for k, v in cons_resources.items() for _ in [None]]
        res_line = f"\n🧱 **Resources per province:** {', '.join(f'{v} {k}' for k,v in cons_resources.items())}"
    e = _base(
        "🔨  Confirm Construction",
        (
            f"**Building:** {building_name}\n"
            f"**Provinces ({len(provinces)}):** {', '.join(provinces)}\n"
            f"**Construction Time:** {months} months each\n"
            f"💲 **Total Gold Cost:** {total_gold:,.0f} gold"
            + res_line
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
