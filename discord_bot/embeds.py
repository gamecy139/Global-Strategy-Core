"""
Central place for all embed builders — keeps cog code clean.
"""
from __future__ import annotations

import discord

# Palette
COL_GOLD   = 0xC9A84C   # warm gold — header / help
COL_RED    = 0x8B1A1A   # dark red  — WW1 theme / start
COL_GREEN  = 0x2E7D32   # success
COL_BLUE   = 0x1565C0   # info
COL_ORANGE = 0xD84315   # warning / select
COL_GREY   = 0x546E7A   # neutral

THUMB = "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Iron_Cross_-_black.svg/240px-Iron_Cross_-_black.svg.png"


def _base(title: str, description: str, colour: int) -> discord.Embed:
    e = discord.Embed(title=title, description=description, colour=colour)
    e.set_thumbnail(url=THUMB)
    e.set_footer(text="WW1 Roleplay  •  prefix: rp")
    return e


# ── Help ─────────────────────────────────────────────────────────────────────

def help_embed() -> discord.Embed:
    e = _base(
        "📖  WW1 Roleplay — Command Reference",
        "All commands use the prefix **rp**.",
        COL_GOLD,
    )
    commands = [
        ("rp help",                "Show this help message."),
        ("rp start",               "Choose a scenario and begin the game."),
        ("rp countries",           "List all playable countries with religion & population."),
        ("rp select `<country>`",  "Claim a country and start playing as it."),
    ]
    for name, desc in commands:
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


def game_started_embed(scenario: str) -> discord.Embed:
    e = _base(
        "🎖️  Game Started!",
        (
            f"**Scenario:** {scenario}\n\n"
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
    from discord_bot.ww1_data import RELIGION_EMOJI, fmt_population

    e = discord.Embed(
        title="🗺️  Playable Nations — WW1 Scenario",
        description=(
            "Choose a nation with **`rp select <country name>`**.\n"
            "🔒 = already taken by another player.\n"
        ),
        colour=COL_BLUE,
    )
    e.set_thumbnail(url=THUMB)

    for c in countries:
        emoji   = RELIGION_EMOJI.get(c["religion"], "🏛️")
        pop     = fmt_population(c["total_population"])
        owner   = assignments.get(c["country_id"])
        status  = f"🔒 *{owner}*" if owner else "✅ Available"
        e.add_field(
            name=f"{c['country_name']}",
            value=(
                f"{emoji} {c['religion']}\n"
                f"👥 {pop}\n"
                f"{status}"
            ),
            inline=True,
        )

    e.set_footer(
        text=f"WW1 Roleplay  •  prefix: rp  •  Page {page}/{total_pages}"
    )
    return e


# ── Select ────────────────────────────────────────────────────────────────────

def select_success_embed(
    user: discord.Member,
    country: dict,
) -> discord.Embed:
    from discord_bot.ww1_data import RELIGION_EMOJI, fmt_population
    emoji = RELIGION_EMOJI.get(country["religion"], "🏛️")
    e = _base(
        "🎌  Country Claimed!",
        (
            f"{user.mention} is now playing as **{country['country_name']}**.\n\n"
            f"{emoji} **Religion:** {country['religion']}\n"
            f"👥 **Population:** {fmt_population(country['total_population'])}"
        ),
        COL_GREEN,
    )
    return e


def select_error_embed(message: str) -> discord.Embed:
    return _base("❌  Cannot Assign Country", message, COL_ORANGE)


def no_game_embed() -> discord.Embed:
    return _base(
        "⚠️  No Active Game",
        "No scenario is running in this server.\nUse **`rp start`** to begin.",
        COL_GREY,
    )
