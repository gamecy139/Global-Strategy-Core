"""
Central place for all embed builders — keeps cog code clean.
"""
from __future__ import annotations

import discord

# Palette
COL_GOLD   = 0xC9A84C
COL_RED    = 0x8B1A1A
COL_GREEN  = 0x2E7D32
COL_BLUE   = 0x1565C0
COL_ORANGE = 0xD84315
COL_GREY   = 0x546E7A
COL_PURPLE = 0x4A148C

THUMB = "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Iron_Cross_-_black.svg/240px-Iron_Cross_-_black.svg.png"

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

GAME_START_YEAR = 1910


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
        ("rp help",                "Show this help message."),
        ("rp start",               "**Admin only** — Choose a scenario and begin the game."),
        ("rp countries",           "List all playable countries with religion & population."),
        ("rp select `<country>`",  "Claim a country and start playing as it."),
        ("rp my_country",          "View your country's full dashboard.  Alias: **rp mc**"),
        ("rp speed",               "**Admin only** — View or change the game speed."),
    ]
    for name, desc in cmds:
        e.add_field(name=f"`{name}`", value=desc, inline=False)
    return e


# ── Start ─────────────────────────────────────────────────────────────────────

def start_setup_embed() -> discord.Embed:
    return _base(
        "⚙️  Scenario Setup",
        (
            "Set up a roleplay scenario before starting the gameplay.\n\n"
            "Use the dropdown below to choose your scenario."
        ),
        COL_RED,
    )


def game_already_started_embed(scenario_label: str) -> discord.Embed:
    return _base(
        "🚫  Game Already Running",
        (
            f"A game of **{scenario_label}** (1910) is already in progress.\n\n"
            "• Use **`rp countries`** to see available nations.\n"
            "• Use **`rp select <name>`** to claim yours.\n"
            "• Use **`rp my_country`** if you've already picked one."
        ),
        COL_RED,
    )


def not_admin_embed(cmd: str) -> discord.Embed:
    return _base(
        "🔒  Administrator Only",
        f"**`{cmd}`** can only be used by members with **Administrator** permission.",
        COL_RED,
    )


def game_started_embed(scenario: str) -> discord.Embed:
    e = _base(
        "🎖️  Game Started!",
        (
            f"**Scenario:** {scenario}\n"
            f"**Year:** {GAME_START_YEAR}\n\n"
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


# ── Countries ─────────────────────────────────────────────────────────────────

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
        pop    = _fmt_pop(c["total_population"])
        owner  = assignments.get(c["country_id"])
        status = f"🔒 *{owner}*" if owner else "✅ Available"
        e.add_field(
            name=c["country_name"],
            value=f"{emoji} {c['religion']}\n👥 {pop}\n{status}",
            inline=True,
        )

    e.set_footer(text=f"WW1 Roleplay  •  prefix: rp  •  Page {page}/{total_pages}")
    return e


# ── Select ────────────────────────────────────────────────────────────────────

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


def select_error_embed(message: str) -> discord.Embed:
    return _base("❌  Cannot Assign Country", message, COL_ORANGE)


def no_game_embed() -> discord.Embed:
    return _base(
        "⚠️  No Active Game",
        "No scenario is running in this server.\nAn **administrator** can use **`rp start`** to begin.",
        COL_GREY,
    )


# ── Speed ─────────────────────────────────────────────────────────────────────

def speed_embed(current_value: str, options: list[dict]) -> discord.Embed:
    label_map = {o["value"]: o["label"] for o in options}
    current_label = label_map.get(current_value, current_value)
    e = _base(
        "⏱️  Game Speed",
        f"Current speed: **{current_label}**\n\nSelect a new speed from the dropdown below.",
        COL_PURPLE,
    )
    return e


def speed_changed_embed(new_label: str) -> discord.Embed:
    return _base("✅  Speed Updated", f"Game speed set to **{new_label}**.", COL_GREEN)


# ── My Country — per-section embeds ──────────────────────────────────────────

def _country_base_embed(country: dict, owner_name: str, year: int,
                         section: str, colour: int) -> discord.Embed:
    rel_emoji = RELIGION_EMOJI.get(country.get("religion", ""), "🏛️")
    e = discord.Embed(
        title=f"🏛️  **{country['country_name']}**",
        colour=colour,
    )
    e.add_field(name="Owner",        value=owner_name, inline=True)
    e.add_field(name="Year",         value=str(year),  inline=True)
    e.add_field(name="Religion",     value=f"{rel_emoji} {country.get('religion','—')}", inline=True)
    e.add_field(name="Treasury",     value=f"{country.get('treasury', 0):,.1f} gold", inline=True)
    e.add_field(name="Daily Income", value=f"{country.get('daily_base_income', 0):+.2f} gold/day", inline=True)
    e.add_field(name="​", value="​", inline=True)   # spacer
    e.add_field(
        name="ℹ️  Use the dropdown to explore",
        value="Provinces · Population · Resources · Military · Infrastructure",
        inline=False,
    )
    e.set_footer(text=f"Section: {section}  •  WW1 Roleplay  •  1910")
    e.set_thumbnail(url=THUMB)
    return e


def my_country_overview_embed(country: dict, owner_name: str, year: int) -> discord.Embed:
    return _country_base_embed(country, owner_name, year, "Overview", COL_GOLD)


def my_country_provinces_embed(country: dict, owner_name: str, year: int,
                                provinces: list[dict]) -> discord.Embed:
    e = _country_base_embed(country, owner_name, year, "Provinces", COL_BLUE)
    e.add_field(
        name=f"🗺️  Provinces ({len(provinces)})",
        value="\n".join(f"• {p['province_name']}" for p in provinces) or "*None*",
        inline=False,
    )
    return e


def my_country_population_embed(country: dict, owner_name: str, year: int,
                                  provinces: list[dict]) -> discord.Embed:
    e = _country_base_embed(country, owner_name, year, "Population", COL_GREEN)
    total  = sum(p["population"] for p in provinces)
    growth = country.get("population_growth_rate", 0.6)
    lines  = [f"**{p['province_name']}** — {_fmt_pop(p['population'])}" for p in provinces]
    e.add_field(name="👥  Total Population", value=_fmt_pop(total),       inline=True)
    e.add_field(name="📈  Monthly Growth",   value=f"{growth:.1%}",       inline=True)
    e.add_field(name="​", value="​", inline=True)
    e.add_field(
        name="Per Province",
        value="\n".join(lines[:25]) or "*No provinces*",
        inline=False,
    )
    return e


def my_country_resources_embed(country: dict, owner_name: str, year: int,
                                 provinces: list[dict]) -> discord.Embed:
    e = _country_base_embed(country, owner_name, year, "Resources", COL_ORANGE)
    by_res: dict[str, list[str]] = {}
    for p in provinces:
        res = (p.get("resource_type") or "none").lower()
        by_res.setdefault(res, []).append(p["province_name"])
    for res, pnames in sorted(by_res.items()):
        emoji = RESOURCE_EMOJI.get(res, "📦")
        e.add_field(
            name=f"{emoji}  {res.title()} ({len(pnames)})",
            value="\n".join(f"• {n}" for n in pnames),
            inline=True,
        )
    return e


def my_country_military_embed(country: dict, owner_name: str, year: int,
                                army_data: dict) -> discord.Embed:
    e = _country_base_embed(country, owner_name, year, "Military", COL_RED)
    armies     = army_data["armies"]
    total_units = army_data["total_units"]

    e.add_field(name="⚔️  Army Units", value=str(total_units) if total_units else "0", inline=True)
    e.add_field(name="🪖  Armies",     value=str(len(armies))  if armies     else "0", inline=True)
    e.add_field(name="​", value="​", inline=True)

    if not armies:
        e.add_field(
            name=f"🏳️  {country['country_name']} Army",
            value="*No army units are currently deployed.\nRecruit troops to build your military force.*",
            inline=False,
        )
    else:
        lines = []
        for a in armies:
            lines.append(
                f"**Army `{a['army_id']}`** — Province {a['province_id']} "
                f"({a['strength_pct']:.0f}% strength) — **{a['unit_count']} units**"
            )
            for u in a["units"]:
                lines.append(f"  ↳ {u['unit_name']}: {u['quantity']:,}")
        e.add_field(
            name=f"🪖  {country['country_name']} Army",
            value="\n".join(lines[:30]),
            inline=False,
        )
    return e


def my_country_infrastructure_embed(country: dict, owner_name: str, year: int,
                                      provinces: list[dict],
                                      buildings: dict[str, list[str]]) -> discord.Embed:
    e = _country_base_embed(country, owner_name, year, "Infrastructure", COL_GREY)
    for p in provinces:
        pname = p["province_name"]
        blist = buildings.get(pname, [])
        value = "\n".join(blist) if blist else "*No buildings*"
        e.add_field(name=f"🏗️  {pname}", value=value, inline=True)
    return e
