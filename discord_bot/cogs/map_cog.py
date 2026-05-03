from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord.ext import commands

from discord_bot.map_renderer import (
    COUNTRY_COLORS,
    COUNTRY_COLOR_NAMES,
    COUNTRY_DISPLAY_NAMES,
    DEFAULT_COLOR,
)

log = logging.getLogger(__name__)

# Build legend lines: "German Empire — Blue"
# Split into two side-by-side fields so the embed stays compact.
_LEGEND_ENTRIES = [
    f"{COUNTRY_DISPLAY_NAMES[cid]} — {COUNTRY_COLOR_NAMES[cid]}"
    for cid in COUNTRY_COLORS
]
_HALF = (len(_LEGEND_ENTRIES) + 1) // 2
_LEGEND_LEFT  = "\n".join(_LEGEND_ENTRIES[:_HALF])
_LEGEND_RIGHT = "\n".join(_LEGEND_ENTRIES[_HALF:])
_LEGEND_UNOWNED = "Unowned — Grey"


class MapCog(commands.Cog, name="Map"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="map")
    async def map_cmd(self, ctx: commands.Context) -> None:
        """Render the current political map coloured by country ownership."""
        status = await ctx.send("🗺️  Generating map… this may take a few seconds.")

        guild_id = str(ctx.guild.id) if ctx.guild else "guild_demo"

        try:
            from discord_bot.map_renderer import render_map_png
            loop      = asyncio.get_event_loop()
            png_bytes = await loop.run_in_executor(
                None, lambda: render_map_png(server_id=guild_id)
            )
        except Exception as exc:
            log.exception("Map render failed")
            await status.edit(content=f"❌  Map render failed: {exc}")
            return

        file  = discord.File(io.BytesIO(png_bytes), filename="map.png")
        embed = discord.Embed(
            title="⚔️  Political Map — WW1 1914",
            colour=0x2B2D31,
        )
        embed.add_field(name="Map Legend", value=_LEGEND_LEFT,  inline=True)
        embed.add_field(name="\u200b",      value=_LEGEND_RIGHT, inline=True)
        embed.add_field(name="\u200b",      value=_LEGEND_UNOWNED, inline=False)
        embed.set_image(url="attachment://map.png")
        await status.delete()
        await ctx.send(file=file, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MapCog(bot))
