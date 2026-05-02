"""
Diplomacy cog — rp edit_diplomacy (rp ed) / rp check_diplomacy (rp cd)
"""
from __future__ import annotations

import discord
from discord.ext import commands

from discord_bot import embeds, game_state
from discord_bot.ww1_data import (
    get_countries,
    get_country_by_id,
    diplo_improve_relations,
    diplo_damage_relations,
    diplo_rivalry,
    diplo_alliance,
    diplo_declare_war,
    diplo_send_gift,
    get_diplomacy_overview,
    get_all_relations_for_country,
    get_relation_value,
    is_rival,
    is_at_war,
    are_allied,
    get_active_diplomacy_actions,
    SERVER_ID,
    SCENARIO_ID,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _name_map(countries: list[dict]) -> dict[str, str]:
    return {c["country_id"]: c["country_name"] for c in countries}


def _country_options(countries: list[dict], exclude_id: str) -> list[discord.SelectOption]:
    opts = []
    for c in countries:
        if c["country_id"] == exclude_id:
            continue
        opts.append(discord.SelectOption(
            label=c["country_name"],
            value=c["country_id"],
            emoji="🏳️",
        ))
    return opts[:25]  # Discord hard limit


# ── edit_diplomacy views ───────────────────────────────────────────────────────

class ActionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Improve Relations",  value="improve",  emoji="📈",
                                 description="+5 relations / month"),
            discord.SelectOption(label="Damage Relations",   value="damage",   emoji="📉",
                                 description="−5 relations / month"),
            discord.SelectOption(label="Declare Rivalry",    value="rivalry",  emoji="🗡️",
                                 description="−10 instant; blocks improvement both ways"),
            discord.SelectOption(label="Propose Alliance",   value="alliance", emoji="🤝",
                                 description="Requires 80+ relations"),
            discord.SelectOption(label="Declare War",        value="war",      emoji="⚔️",
                                 description="Requires < 20 relations"),
            discord.SelectOption(label="Send Gift",          value="gift",     emoji="🎁",
                                 description="−40 gold → target, +5 relations instantly"),
        ]
        super().__init__(
            placeholder="Choose a diplomatic action…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        view: EditDiplomacyView = self.view
        view.chosen_action = self.values[0]
        # Swap to country picker
        view.clear_items()
        view.add_item(CountrySelect(view.countries, view.my_country_id))
        embed = embeds.diplo_country_select_embed(view.chosen_action, view.my_country_name)
        await interaction.response.edit_message(embed=embed, view=view)


class CountrySelect(discord.ui.Select):
    def __init__(self, countries: list[dict], exclude_id: str):
        opts = _country_options(countries, exclude_id)
        super().__init__(
            placeholder="Select target country…",
            min_values=1,
            max_values=1,
            options=opts,
        )

    async def callback(self, interaction: discord.Interaction):
        view: EditDiplomacyView = self.view
        target_id   = self.values[0]
        action      = view.chosen_action
        my_id       = view.my_country_id
        my_name     = view.my_country_name
        name_map    = _name_map(view.countries)
        target_name = name_map.get(target_id, target_id)
        game_day    = game_state.get_game_day(view.guild_id)

        # ── Execute action ─────────────────────────────────────────────────────
        result = None

        if action == "improve":
            result = diplo_improve_relations(my_id, target_id)
            if result["ok"]:
                title = "Improve Relations Queued"
                body  = (
                    f"**{my_name}** will improve relations with **{target_name}** "
                    f"by **+5** each month until cancelled."
                )
            else:
                title = "Cannot Improve Relations"
                body  = result["reason"]

        elif action == "damage":
            result = diplo_damage_relations(my_id, target_id)
            if result["ok"]:
                title = "Damage Relations Queued"
                body  = (
                    f"**{my_name}** will damage relations with **{target_name}** "
                    f"by **−5** each month until cancelled."
                )
            else:
                title = "Cannot Damage Relations"
                body  = result["reason"]

        elif action == "rivalry":
            result = diplo_rivalry(my_id, target_id)
            if result["ok"]:
                title = "Rivalry Declared"
                body  = (
                    f"**{my_name}** has declared **rivalry** with **{target_name}**.\n"
                    f"Relations dropped by −10 (now **{result['new_relation']:.0f}**).\n"
                    f"Neither side can improve relations while the rivalry stands."
                )
            else:
                title = "Cannot Declare Rivalry"
                body  = result["reason"]

        elif action == "alliance":
            result = diplo_alliance(my_id, target_id)
            if result["ok"]:
                title = "Alliance Formed"
                body  = (
                    f"**{my_name}** and **{target_name}** are now **allied**! 🤝\n"
                    f"The alliance will appear in both countries' diplomacy overview."
                )
            else:
                title = "Alliance Failed"
                body  = result["reason"]

        elif action == "war":
            result = diplo_declare_war(my_id, target_id, game_day)
            if result["ok"]:
                title = "War Declared ⚔️"
                body  = (
                    f"**{my_name}** has declared **war** on **{target_name}**!\n"
                    f"Relations have been set to **0**."
                )
            else:
                title = "Cannot Declare War"
                body  = result["reason"]

        elif action == "gift":
            result = diplo_send_gift(my_id, target_id)
            if result["ok"]:
                title = "Gift Sent"
                body  = (
                    f"**{my_name}** sent **40 gold** to **{target_name}**.\n"
                    f"Relations improved to **{result['new_relation']:.0f}**."
                )
            else:
                title = "Gift Failed"
                body  = result["reason"]

        else:
            title = "Unknown Action"
            body  = "Something went wrong — unknown action."
            if result is None:
                result = {"ok": False}

        ok = result["ok"] if result else False
        view.clear_items()
        view.stop()
        await interaction.response.edit_message(
            embed=embeds.diplo_result_embed(ok, title, body),
            view=None,
        )


class EditDiplomacyView(discord.ui.View):
    def __init__(
        self,
        guild_id:        str,
        my_country_id:   str,
        my_country_name: str,
        countries:       list[dict],
    ):
        super().__init__(timeout=120)
        self.guild_id        = guild_id
        self.my_country_id   = my_country_id
        self.my_country_name = my_country_name
        self.countries       = countries
        self.chosen_action: str | None = None
        self.add_item(ActionSelect())

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── check_diplomacy views ──────────────────────────────────────────────────────

class CheckCountrySelect(discord.ui.Select):
    def __init__(self, countries: list[dict], my_id: str):
        opts = _country_options(countries, my_id)
        super().__init__(
            placeholder="Select a country to inspect relations…",
            min_values=1,
            max_values=1,
            options=opts,
        )

    async def callback(self, interaction: discord.Interaction):
        view: CheckDiplomacyView = self.view
        target_id   = self.values[0]
        my_id       = view.my_country_id
        name_map    = _name_map(view.countries)
        target_name = name_map.get(target_id, target_id)
        my_name     = view.my_country_name

        relation   = get_relation_value(my_id, target_id)
        rival_us   = is_rival(my_id, target_id)  # we or they declared rivalry
        # directional check — did WE initiate?
        from discord_bot.ww1_data import _conn, SERVER_ID, SCENARIO_ID
        with _conn() as con:
            we_rivaled  = con.execute(
                "SELECT 1 FROM rivals WHERE server_id=? AND scenario_id=? AND initiator=? AND target=?",
                (SERVER_ID, SCENARIO_ID, my_id, target_id)
            ).fetchone() is not None
            they_rivaled = con.execute(
                "SELECT 1 FROM rivals WHERE server_id=? AND scenario_id=? AND initiator=? AND target=?",
                (SERVER_ID, SCENARIO_ID, target_id, my_id)
            ).fetchone() is not None
            # Check active diplomacy actions
            my_action = con.execute(
                "SELECT action_type FROM diplomacy_actions "
                "WHERE server_id=? AND scenario_id=? AND actor=? AND target=?",
                (SERVER_ID, SCENARIO_ID, my_id, target_id)
            ).fetchone()
            improve_active = my_action and my_action[0] == "improve"
            damage_active  = my_action and my_action[0] == "damage"

        allied = are_allied(my_id, target_id)
        at_war = is_at_war(my_id, target_id)

        detail_embed = embeds.diplo_country_detail_embed(
            my_country_name=my_name,
            target_country_name=target_name,
            relation=relation,
            is_rival_us=we_rivaled,
            is_rival_them=they_rivaled,
            is_allied=allied,
            at_war=at_war,
            improve_active=improve_active,
            damage_active=damage_active,
        )
        # Keep the dropdown so the user can look up more countries
        await interaction.response.edit_message(embed=detail_embed, view=view)


class CheckDiplomacyView(discord.ui.View):
    def __init__(
        self,
        my_country_id:   str,
        my_country_name: str,
        countries:       list[dict],
    ):
        super().__init__(timeout=180)
        self.my_country_id   = my_country_id
        self.my_country_name = my_country_name
        self.countries       = countries
        self.add_item(CheckCountrySelect(countries, my_country_id))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Cog ───────────────────────────────────────────────────────────────────────

class DiplomacyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── rp edit_diplomacy / rp ed ─────────────────────────────────────────────

    @commands.command(name="edit_diplomacy", aliases=["ed"])
    async def edit_diplomacy_cmd(self, ctx: commands.Context):
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
                f"Could not load data for `{country_id}`."
            ))
            return

        countries = get_countries()
        view      = EditDiplomacyView(guild_id, country_id, country["country_name"], countries)
        await ctx.send(
            embed=embeds.diplo_main_embed(country["country_name"]),
            view=view,
        )

    # ── rp check_diplomacy / rp cd ────────────────────────────────────────────

    @commands.command(name="check_diplomacy", aliases=["cd"])
    async def check_diplomacy_cmd(self, ctx: commands.Context):
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
                f"Could not load data for `{country_id}`."
            ))
            return

        countries = get_countries()
        nm        = _name_map(countries)
        overview  = get_diplomacy_overview(country_id)

        embed = embeds.check_diplomacy_embed(
            country_name=country["country_name"],
            country_id=country_id,
            friendly=overview["friendly"],
            unfriendly=overview["unfriendly"],
            our_rivals=overview["our_rivals"],
            rivaled_by=overview["rivaled_by"],
            allies=overview["allies"],
            wars=overview["wars"],
            name_map=nm,
        )
        view = CheckDiplomacyView(country_id, country["country_name"], countries)
        await ctx.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(DiplomacyCog(bot))
