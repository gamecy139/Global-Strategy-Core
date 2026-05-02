"""
Discord bot entry point — single-instance enforced via PID lock file.
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import os
import signal
import sys
import time

import discord
from discord.ext import commands

from discord_bot import game_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")

TOKEN    = os.environ.get("DISCORD_TOKEN", "")
PID_FILE = "/tmp/ww1_discord_bot.pid"


# ── Single-instance lock ──────────────────────────────────────────────────────

def _enforce_single_instance() -> None:
    """
    Kill any pre-existing bot process found in the PID file, then write
    the current PID so future restarts can clean up after us.
    """
    current_pid = os.getpid()

    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            if old_pid != current_pid:
                log.info("Killing previous bot instance (PID %d)…", old_pid)
                os.kill(old_pid, signal.SIGTERM)
                # Give the old process a moment to exit cleanly
                for _ in range(20):          # up to 2 seconds
                    time.sleep(0.1)
                    try:
                        os.kill(old_pid, 0)  # check still alive
                    except ProcessLookupError:
                        break                # gone — good
                else:
                    # Still alive after 2 s — force kill
                    try:
                        os.kill(old_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        except (ValueError, ProcessLookupError, OSError):
            pass  # stale / unreadable PID file is fine

    with open(PID_FILE, "w") as f:
        f.write(str(current_pid))

    atexit.register(_remove_pid_file)


def _remove_pid_file() -> None:
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


# ── Bot ───────────────────────────────────────────────────────────────────────

INTENTS = discord.Intents.default()
INTENTS.message_content = True


class RoleplayBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="rp ",
            intents=INTENTS,
            help_command=None,
            case_insensitive=True,
        )
        self._tick_started = False   # guard: start_tick only once per process

    async def setup_hook(self):
        game_state.init()

        # Seed troop definitions so validate_recruitment always finds every unit
        try:
            from discord_bot.ww1_data import _ensure_troop_definitions_seeded
            _ensure_troop_definitions_seeded()
            log.info("Troop definitions seeded.")
        except Exception as exc:
            log.warning("Troop-definition seeding failed (non-fatal): %s", exc)

        await self.load_extension("discord_bot.cogs.game")
        await self.load_extension("discord_bot.cogs.economy")
        await self.load_extension("discord_bot.cogs.recruit")
        log.info("Cogs loaded.")

    async def on_ready(self):
        # on_ready fires again on every Discord reconnect — guard everything
        await self.change_presence(
            activity=discord.Game(name="rp help | WW1 Roleplay 1910")
        )
        log.info("Logged in as %s  (id=%s)", self.user, self.user.id)
        log.info("Serving %d guild(s).", len(self.guilds))

        if not self._tick_started:
            from discord_bot.tick_runner import start_tick
            await start_tick(self)
            self._tick_started = True

    async def on_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandNotFound):
            return
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


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    if not TOKEN:
        log.error("DISCORD_TOKEN is not set. Add it to Replit Secrets.")
        return

    bot = RoleplayBot()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    _enforce_single_instance()
    asyncio.run(main())
