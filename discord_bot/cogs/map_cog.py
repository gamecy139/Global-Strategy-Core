from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord.ext import commands

from discord_bot.map_renderer import COUNTRY_COLORS, DEFAULT_COLOR

log = logging.getLogger(__name__)

_LEGEND_NAMES: dict[str, str] = {
    "germany":         "German Empire",
    "united_kingdom":  "United Kingdom",
    "france":          "France",
    "russian_empire":  "Russian Empire",
    "austrian_empire": "Austrian Empire",
    "ottoman":         "Ottoman Empire",
    "italy":           "Italy",
    "spain":           "Spain",
    "netherlands":     "Netherlands",
    "belgium":         "Belgium",
    "sweden":          "Sweden",
    "denmark":         "Denmark",
    "norway":          "Norway",
    "portugal":        "Portugal",
    "switzerland":     "Switzerland",
    "greece":          "Greece",
    "serbia":          "Serbia",
    "bulgaria":        "Bulgaria",
    "romania":         "Romania",
    "albania":         "Albania",
}

_LEGEND_TEXT = "\n".join(
    f"`{color}`  {_LEGEND_NAMES.get(cid, cid)}"
    for cid, color in COUNTRY_COLORS.items()
) + f"\n`{DEFAULT_COLOR}`  (unowned)"


class MapCog(commands.Cog, name="Map"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="map")
    async def map_cmd(self, ctx: commands.Context) -> None:
        """Render the current political map coloured by country ownership."""
        status = await ctx.send("🗺️  Generating map… this may take a few seconds.")
        try:
            from discord_bot.map_renderer import render_map_png
            loop      = asyncio.get_event_loop()
            png_bytes = await loop.run_in_executor(None, render_map_png)
        except Exception as exc:
            log.exception("Map render failed")
            await status.edit(content=f"❌  Map render failed: {exc}")
            return

        file  = discord.File(io.BytesIO(png_bytes), filename="map.png")
        embed = discord.Embed(
            title="⚔️  Political Map — WW1 1914",
            colour=0x2B2D31,
        )
        embed.add_field(name="Legend", value=_LEGEND_TEXT, inline=False)
        embed.set_image(url="attachment://map.png")
        await status.delete()
        await ctx.send(file=file, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MapCog(bot))
