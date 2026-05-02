"""
Main game cog — rp help / start / countries / select / speed / my_country / mc / clear
"""
from __future__ import annotations

import discord
from discord.ext import commands

from discord_bot import embeds, game_state
from discord_bot.ww1_data import (
    find_country, get_countries, get_country_by_id,
    get_provinces, get_buildings_with_status, get_army_summary,
)

COUNTRIES_PER_PAGE = 9
AUTHORISED_USER    = "xter_gamer"


def _is_admin(ctx: commands.Context) -> bool:
    return ctx.author.guild_permissions.administrator


def _is_authorised(ctx: commands.Context) -> bool:
    """Returns True if the user is xter_gamer (by display name or username)."""
    return (
        ctx.author.display_name.lower() == AUTHORISED_USER.lower()
        or ctx.author.name.lower()         == AUTHORISED_USER.lower()
    )


# ── Scenario selector ─────────────────────────────────────────────────────────

class ScenarioSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="WW1 — World War 1",
                value="ww1",
                description="Europe, 1910. The Great War looms.",
                emoji="⚔️",
            ),
        ]
        super().__init__(
            placeholder="☐  Choose a scenario…",
            min_values=1, max_values=1, options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        guild_id   = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        scenario   = self.values[0]
        game_state.start_game(guild_id, channel_id, scenario)
        label_map  = {"ww1": "World War 1 (1910)"}
        label      = label_map.get(scenario, scenario.upper())
        self.view.stop()
        self.disabled = True
        await interaction.response.edit_message(
            embed=embeds.game_started_embed(label), view=None,
        )


class ScenarioView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(ScenarioSelect())

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Countries pagination ──────────────────────────────────────────────────────

class CountriesView(discord.ui.View):
    def __init__(self, countries: list[dict], assignments: dict[str, str]):
        super().__init__(timeout=90)
        self.countries   = countries
        self.assignments = assignments
        self.page        = 1
        self.total_pages = max(1, -(-len(countries) // COUNTRIES_PER_PAGE))
        self._update_buttons()

    def _page_countries(self):
        start = (self.page - 1) * COUNTRIES_PER_PAGE
        return self.countries[start: start + COUNTRIES_PER_PAGE]

    def _update_buttons(self):
        self.prev_btn.disabled = self.page <= 1
        self.next_btn.disabled = self.page >= self.total_pages

    def _current_embed(self):
        return embeds.countries_embed(
            self._page_countries(), self.assignments,
            self.page, self.total_pages,
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


# ── Speed selector ────────────────────────────────────────────────────────────

class SpeedSelect(discord.ui.Select):
    def __init__(self, current_value: str):
        options = [
            discord.SelectOption(
                label=opt["label"], value=opt["value"],
                description=opt["desc"],
                default=(opt["value"] == current_value),
            )
            for opt in game_state.SPEED_OPTIONS
        ]
        super().__init__(
            placeholder="Select game speed…",
            min_values=1, max_values=1, options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        guild_id  = str(interaction.guild_id)
        new_value = self.values[0]
        game_state.set_speed(guild_id, new_value)
        label_map = {o["value"]: o["label"] for o in game_state.SPEED_OPTIONS}
        new_label = label_map.get(new_value, new_value)
        self.view.stop()
        await interaction.response.edit_message(
            embed=embeds.speed_changed_embed(new_label), view=None,
        )


class SpeedView(discord.ui.View):
    def __init__(self, current_value: str):
        super().__init__(timeout=90)
        self.add_item(SpeedSelect(current_value))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Clear game: confirmation view ─────────────────────────────────────────────

class ClearConfirmView(discord.ui.View):
    def __init__(self, guild_id: str):
        super().__init__(timeout=60)
        self.guild_id = guild_id

    @discord.ui.button(label="✅  Yes, Reset", style=discord.ButtonStyle.danger)
    async def yes_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        game_state.reset_guild_game(self.guild_id)
        self.stop()
        await interaction.response.edit_message(
            embed=embeds.clear_success_embed(), view=None,
        )

    @discord.ui.button(label="❌  No, Cancel", style=discord.ButtonStyle.secondary)
    async def no_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            embed=embeds.clear_cancelled_embed(), view=None,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── My Country — section select ───────────────────────────────────────────────

SECTIONS = [
    ("overview",        "🏛️  Overview",       "Treasury, income, basic info."),
    ("provinces",       "🗺️  Provinces",       "List of all provinces."),
    ("population",      "👥  Population",      "Total pop, growth rate, per-province."),
    ("resources",       "⚙️  Resources",       "Province resources breakdown."),
    ("military",        "⚔️  Military",        "Army units and armies."),
    ("infrastructure",  "🏗️  Infrastructure",  "Buildings per province."),
]


class CountrySelect(discord.ui.Select):
    def __init__(self, country: dict, owner_name: str, guild_id: str):
        self.country    = country
        self.owner_name = owner_name
        self.guild_id   = guild_id
        options = [
            discord.SelectOption(label=label, value=value, description=desc)
            for value, label, desc in SECTIONS
        ]
        super().__init__(
            placeholder="☐  Explore your country…",
            min_values=1, max_values=1, options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        section  = self.values[0]
        country  = self.country
        cid      = country["country_id"]
        owner    = self.owner_name
        guild_id = self.guild_id
        date     = game_state.get_game_date(guild_id)

        if section == "overview":
            embed = embeds.my_country_overview_embed(country, owner, date)

        elif section == "provinces":
            provs = get_provinces(cid)
            embed = embeds.my_country_provinces_embed(country, owner, date, provs)

        elif section == "population":
            provs = get_provinces(cid)
            embed = embeds.my_country_population_embed(country, owner, date, provs)

        elif section == "resources":
            provs = get_provinces(cid)
            embed = embeds.my_country_resources_embed(country, owner, date, provs)

        elif section == "military":
            army_data = get_army_summary(cid)
            embed = embeds.my_country_military_embed(country, owner, date, army_data)

        elif section == "infrastructure":
            provs    = get_provinces(cid)
            game_day = game_state.get_game_day(guild_id)
            bldgs    = get_buildings_with_status(cid, game_day)
            embed    = embeds.my_country_infrastructure_embed(country, owner, date, provs, bldgs)

        else:
            embed = embeds.my_country_overview_embed(country, owner, date)

        await interaction.edit_original_response(embed=embed, view=self.view)


class CountryView(discord.ui.View):
    def __init__(self, country: dict, owner_name: str, guild_id: str):
        super().__init__(timeout=180)
        self.add_item(CountrySelect(country, owner_name, guild_id))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Cog ───────────────────────────────────────────────────────────────────────

class GameCog(commands.Cog, name="Game"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_cmd(self, ctx: commands.Context):
        await ctx.send(embed=embeds.help_embed())

    @commands.command(name="start")
    async def start_cmd(self, ctx: commands.Context):
        if not _is_admin(ctx):
            await ctx.send(embed=embeds.not_admin_embed("rp start"))
            return
        guild_id = str(ctx.guild.id)
        if game_state.is_game_running(guild_id):
            session   = game_state.get_session(guild_id)
            label_map = {"ww1": "World War 1 (1910)"}
            label     = label_map.get(session["scenario_id"], session["scenario_id"].upper())
            await ctx.send(embed=embeds.game_already_started_embed(label))
            return
        view = ScenarioView()
        await ctx.send(embed=embeds.start_setup_embed(), view=view)

    @commands.command(name="countries")
    async def countries_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return
        countries   = get_countries()
        assignments = game_state.get_assignments(guild_id)
        view        = CountriesView(countries, assignments)
        await ctx.send(
            embed=embeds.countries_embed(
                countries[:COUNTRIES_PER_PAGE], assignments,
                page=1,
                total_pages=max(1, -(-len(countries) // COUNTRIES_PER_PAGE)),
            ),
            view=view,
        )

    @commands.command(name="select")
    async def select_cmd(self, ctx: commands.Context, *, country_name: str = ""):
        guild_id = str(ctx.guild.id)
        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return
        if not country_name:
            await ctx.send(embed=embeds.select_error_embed(
                "Please provide a country name.\nExample: **`rp select German Empire`**"
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
            guild_id, country["country_id"],
            str(ctx.author.id), ctx.author.display_name,
        )
        if error:
            await ctx.send(embed=embeds.select_error_embed(error))
            return
        await ctx.send(embed=embeds.select_success_embed(ctx.author, country))

    @commands.command(name="speed")
    async def speed_cmd(self, ctx: commands.Context):
        if not _is_admin(ctx):
            await ctx.send(embed=embeds.not_admin_embed("rp speed"))
            return
        guild_id = str(ctx.guild.id)
        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return
        current = game_state.get_speed(guild_id)
        view    = SpeedView(current)
        await ctx.send(embed=embeds.speed_embed(current, game_state.SPEED_OPTIONS), view=view)

    @commands.command(name="my_country", aliases=["mc"])
    async def my_country_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)
        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return
        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return
        country = get_country_by_id(country_id)
        if country is None:
            await ctx.send(embed=embeds.select_error_embed(
                f"Could not load data for `{country_id}`. Please contact an admin."
            ))
            return
        date = game_state.get_game_date(guild_id)
        view = CountryView(country, ctx.author.display_name, guild_id)
        await ctx.send(
            embed=embeds.my_country_overview_embed(country, ctx.author.display_name, date),
            view=view,
        )

    @commands.command(name="clear")
    async def clear_cmd(self, ctx: commands.Context):
        """Reset the entire game for this server. Only xter_gamer can use this."""
        if not _is_authorised(ctx):
            await ctx.send(embed=embeds.not_authorised_embed("rp clear"))
            return
        guild_id = str(ctx.guild.id)
        view     = ClearConfirmView(guild_id)
        await ctx.send(embed=embeds.clear_confirm_embed(), view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(GameCog(bot))
