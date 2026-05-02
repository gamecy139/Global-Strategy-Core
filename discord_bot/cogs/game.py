"""
Main game cog — implements rp help / start / countries / select.
"""
from __future__ import annotations

import discord
from discord.ext import commands

from discord_bot import embeds, game_state
from discord_bot.ww1_data import find_country, get_countries

COUNTRIES_PER_PAGE = 9   # 3 × 3 grid of inline fields looks clean


# ── Scenario selector UI ─────────────────────────────────────────────────────

class ScenarioSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="WW1 — World War 1",
                value="ww1",
                description="Europe, 1914. The Great War begins.",
                emoji="⚔️",
            ),
        ]
        super().__init__(
            placeholder="☐  Choose a scenario…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        guild_id   = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        scenario   = self.values[0]

        game_state.start_game(guild_id, channel_id, scenario)

        label_map = {"ww1": "World War 1 (1914)"}
        label = label_map.get(scenario, scenario.upper())

        self.view.stop()
        self.disabled = True
        await interaction.response.edit_message(
            embed=embeds.game_started_embed(label),
            view=None,
        )


class ScenarioView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(ScenarioSelect())

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Country list pagination ───────────────────────────────────────────────────

class CountriesView(discord.ui.View):
    def __init__(self, countries: list[dict], assignments: dict[str, str]):
        super().__init__(timeout=90)
        self.countries   = countries
        self.assignments = assignments
        self.page        = 1
        self.total_pages = max(1, -(-len(countries) // COUNTRIES_PER_PAGE))
        self._update_buttons()

    def _page_countries(self) -> list[dict]:
        start = (self.page - 1) * COUNTRIES_PER_PAGE
        return self.countries[start: start + COUNTRIES_PER_PAGE]

    def _update_buttons(self):
        self.prev_btn.disabled = self.page <= 1
        self.next_btn.disabled = self.page >= self.total_pages

    def _current_embed(self) -> discord.Embed:
        return embeds.countries_embed(
            self._page_countries(),
            self.assignments,
            self.page,
            self.total_pages,
        )

    @discord.ui.button(label="◀  Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._current_embed(), view=self)

    @discord.ui.button(label="Next  ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._current_embed(), view=self)


# ── Cog ──────────────────────────────────────────────────────────────────────

class GameCog(commands.Cog, name="Game"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── rp help ──────────────────────────────────────────────────────────────

    @commands.command(name="help")
    async def help_cmd(self, ctx: commands.Context):
        """Show all available commands."""
        await ctx.send(embed=embeds.help_embed())

    # ── rp start ─────────────────────────────────────────────────────────────

    @commands.command(name="start")
    async def start_cmd(self, ctx: commands.Context):
        """Choose a scenario and begin the game."""
        view = ScenarioView()
        await ctx.send(embed=embeds.start_setup_embed(), view=view)

    # ── rp countries ─────────────────────────────────────────────────────────

    @commands.command(name="countries")
    async def countries_cmd(self, ctx: commands.Context):
        """List all nations with religion and population."""
        guild_id = str(ctx.guild.id)
        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        countries   = get_countries()
        assignments = game_state.get_assignments(guild_id)
        view        = CountriesView(countries, assignments)

        await ctx.send(
            embed=embeds.countries_embed(
                countries[:COUNTRIES_PER_PAGE],
                assignments,
                page=1,
                total_pages=max(1, -(-len(countries) // COUNTRIES_PER_PAGE)),
            ),
            view=view,
        )

    # ── rp select <country> ───────────────────────────────────────────────────

    @commands.command(name="select")
    async def select_cmd(self, ctx: commands.Context, *, country_name: str = ""):
        """Claim a country to play as."""
        guild_id = str(ctx.guild.id)

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        if not country_name:
            await ctx.send(embed=embeds.select_error_embed(
                "Please provide a country name.\n"
                "Example: **`rp select Germany`**"
            ))
            return

        country = find_country(country_name)
        if country is None:
            await ctx.send(embed=embeds.select_error_embed(
                f"No country found matching **\"{country_name}\"**.\n"
                "Use **`rp countries`** to see the full list."
            ))
            return

        error = game_state.assign_country(
            guild_id,
            country["country_id"],
            str(ctx.author.id),
            ctx.author.display_name,
        )
        if error:
            await ctx.send(embed=embeds.select_error_embed(error))
            return

        await ctx.send(embed=embeds.select_success_embed(ctx.author, country))


async def setup(bot: commands.Bot):
    await bot.add_cog(GameCog(bot))
