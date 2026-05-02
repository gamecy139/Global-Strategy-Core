"""
Discord bot entry point.
"""
from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands

from discord_bot import game_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")

TOKEN = os.environ.get("DISCORD_TOKEN", "")

INTENTS = discord.Intents.default()
INTENTS.message_content = True


class RoleplayBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="rp ",
            intents=INTENTS,
            help_command=None,        # we provide our own rp help
            case_insensitive=True,
        )

    async def setup_hook(self):
        game_state.init()
        await self.load_extension("discord_bot.cogs.game")
        log.info("Cogs loaded.")

    async def on_ready(self):
        await self.change_presence(
            activity=discord.Game(name="rp help | WW1 Roleplay")
        )
        log.info("Logged in as %s  (id=%s)", self.user, self.user.id)
        log.info("Serving %d guild(s).", len(self.guilds))

    async def on_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandNotFound):
            return          # silently ignore unknown rp sub-commands
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                embed=discord.Embed(
                    title="⚠️  Missing argument",
                    description=str(error),
                    colour=0xD84315,
                )
            )
            return
        log.error("Unhandled error in %s: %s", ctx.command, error, exc_info=error)


async def main():
    if not TOKEN:
        log.error("DISCORD_TOKEN is not set. Add it to Replit Secrets.")
        return

    bot = RoleplayBot()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
