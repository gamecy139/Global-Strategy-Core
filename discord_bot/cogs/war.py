"""
War cog — rp declare_war, rp war, rp call_allies (rp ca), rp move_unit
"""
from __future__ import annotations

import discord
from discord.ext import commands

from discord_bot import embeds, game_state
from discord_bot.ww1_data import (
    find_country,
    get_country_by_id,
    get_countries,
    get_active_wars_for_country,
    get_ally_country_ids,
    get_country_armies,
    get_all_provinces_list,
    get_war_details,
    war_declare,
    war_request_ceasefire,
    war_accept_ceasefire,
    war_surrender,
    war_proclaim_victory,
    war_add_ally,
    war_move_army,
    SERVER_ID,
    SCENARIO_ID,
)

GUILD_ID = "guild_demo"


def _country_name(country_id: str) -> str:
    c = get_country_by_id(country_id)
    return c["country_name"] if c else country_id


def _build_name_map() -> dict[str, str]:
    return {c["country_id"]: c["country_name"] for c in get_countries()}


# ─────────────────────────────────────────────────────────────────────────────
# Views
# ─────────────────────────────────────────────────────────────────────────────

class WarStatusView(discord.ui.View):
    """Buttons shown with rp war — one war at a time."""

    def __init__(self, war_id: str, country_id: str, guild_id: str) -> None:
        super().__init__(timeout=120)
        self.war_id     = war_id
        self.country_id = country_id
        self.guild_id   = guild_id

    async def _refresh_embed(self, interaction: discord.Interaction) -> None:
        """Edit the original war status message with fresh data.
        Safe to call regardless of whether the interaction response is already sent.
        """
        details = get_war_details(self.war_id)
        if details is None:
            content = "War not found or already ended."
            if interaction.response.is_done():
                await interaction.message.edit(content=content, embed=None, view=None)
            else:
                await interaction.response.edit_message(content=content, embed=None, view=None)
            return
        nm   = _build_name_map()
        date = game_state.get_game_date(self.guild_id)
        em   = embeds.war_status_embed(
            details["war"], details["participants"],
            details["occupations"], date, nm
        )
        if interaction.response.is_done():
            await interaction.message.edit(embed=em, view=self)
        else:
            await interaction.response.edit_message(embed=em, view=self)

    @discord.ui.button(label="🕊️ Request Ceasefire", style=discord.ButtonStyle.secondary, row=0)
    async def btn_ceasefire(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = war_request_ceasefire(self.war_id, self.country_id)
        em  = embeds.war_action_result_embed("Ceasefire Request", res["message"], res["ok"])
        await interaction.response.send_message(embed=em, ephemeral=True)

    @discord.ui.button(label="✅ Accept Ceasefire", style=discord.ButtonStyle.success, row=0)
    async def btn_accept_cf(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = war_accept_ceasefire(self.war_id, self.country_id)
        em  = embeds.war_action_result_embed("Accept Ceasefire", res["message"], res["ok"])
        # Defer so we can both reply ephemerally AND edit the original message
        await interaction.response.defer()
        await interaction.followup.send(embed=em, ephemeral=True)
        if res["ok"]:
            await self._refresh_embed(interaction)

    @discord.ui.button(label="🏳️ Surrender", style=discord.ButtonStyle.danger, row=1)
    async def btn_surrender(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = war_surrender(self.war_id, self.country_id)
        em  = embeds.war_action_result_embed("Surrender", res["message"], res["ok"])
        await interaction.response.send_message(embed=em, ephemeral=True)

    @discord.ui.button(label="👑 Proclaim Victory", style=discord.ButtonStyle.primary, row=1)
    async def btn_victory(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = war_proclaim_victory(self.war_id, self.country_id)
        em  = embeds.war_action_result_embed("Proclaim Victory", res["message"], res["ok"])
        await interaction.response.send_message(embed=em, ephemeral=True)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._refresh_embed(interaction)


# ── Call Allies ───────────────────────────────────────────────────────────────

class AllySelect(discord.ui.Select):
    def __init__(self, allies: list[str], name_map: dict[str, str]) -> None:
        opts = [
            discord.SelectOption(label=name_map.get(a, a), value=a)
            for a in allies[:25]
        ]
        super().__init__(placeholder="Select ally to call…", options=opts, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view: CallAlliesView = self.view
        view.selected_ally = self.values[0]
        view.stage = "war"
        await view._update_message(interaction)


class WarSelectForAlly(discord.ui.Select):
    def __init__(self, wars: list[dict], name_map: dict[str, str]) -> None:
        opts = []
        for w in wars[:25]:
            att = name_map.get(w["attacker"], w["attacker"])
            dfn = name_map.get(w["defender"], w["defender"])
            opts.append(discord.SelectOption(
                label=f"{att} vs {dfn}",
                value=w["war_id"],
                description=w["war_id"][:20],
            ))
        super().__init__(placeholder="Select war to call ally into…", options=opts, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view: CallAlliesView = self.view
        view.selected_war_id = self.values[0]
        view.stage = "confirm"
        await view._update_message(interaction)


class CallAlliesView(discord.ui.View):
    def __init__(self, country_id: str, allies: list[str],
                 wars: list[dict], guild_id: str) -> None:
        super().__init__(timeout=120)
        self.country_id      = country_id
        self.allies          = allies
        self.wars            = wars
        self.guild_id        = guild_id
        self.selected_ally:  str | None = None
        self.selected_war_id: str | None = None
        self.stage           = "ally"
        self._name_map       = _build_name_map()
        self._build_items()

    def _build_items(self):
        self.clear_items()
        if self.stage == "ally":
            self.add_item(AllySelect(self.allies, self._name_map))
        elif self.stage == "war":
            self.add_item(WarSelectForAlly(self.wars, self._name_map))
            self.add_item(self._confirm_btn(disabled=True))
        elif self.stage == "confirm":
            self.add_item(self._confirm_btn(disabled=False))
            self.add_item(self._cancel_btn())

    def _confirm_btn(self, disabled: bool) -> discord.ui.Button:
        btn = discord.ui.Button(
            label="✅ Confirm Call",
            style=discord.ButtonStyle.success,
            disabled=disabled,
            custom_id="call_confirm",
        )
        btn.callback = self._do_confirm
        return btn

    def _cancel_btn(self) -> discord.ui.Button:
        btn = discord.ui.Button(
            label="❌ Cancel",
            style=discord.ButtonStyle.danger,
            custom_id="call_cancel",
        )
        btn.callback = self._do_cancel
        return btn

    async def _do_confirm(self, interaction: discord.Interaction):
        if not self.selected_ally or not self.selected_war_id:
            await interaction.response.send_message("Select an ally and war first.", ephemeral=True)
            return
        details = get_war_details(self.selected_war_id)
        if details is None:
            await interaction.response.send_message("War not found.", ephemeral=True)
            return
        war = details["war"]
        # Determine side of calling country
        sides = {war["attacker"]: "attacker", war["defender"]: "defender"}
        for p in details["participants"]:
            sides[p["country_id"]] = p["side"]
        side = sides.get(self.country_id, "attacker")

        res = war_add_ally(self.selected_war_id, self.selected_ally, side)
        ally_name = self._name_map.get(self.selected_ally, self.selected_ally)
        em = embeds.war_action_result_embed(
            f"Call Ally — {ally_name}", res["message"], res["ok"]
        )
        await interaction.response.edit_message(embed=em, view=None)

    async def _do_cancel(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="Cancelled.", embed=None, view=None
        )

    async def _update_message(self, interaction: discord.Interaction):
        self._build_items()
        nm = self._name_map
        if self.stage == "war":
            desc = (f"Ally selected: **{nm.get(self.selected_ally, self.selected_ally)}**\n"
                    "Now select which war to call them into.")
        elif self.stage == "confirm":
            ally_name = nm.get(self.selected_ally, self.selected_ally)
            details   = get_war_details(self.selected_war_id)
            war_label = "?"
            if details:
                w = details["war"]
                war_label = (f"{nm.get(w['attacker'], w['attacker'])} vs "
                             f"{nm.get(w['defender'], w['defender'])}")
            desc = (f"Calling **{ally_name}** into **{war_label}**.\n"
                    "Press **Confirm** to proceed.")
        else:
            desc = "Select an ally to call into one of your wars."

        em = embeds.call_allies_embed(
            _country_name(self.country_id), self.allies,
            game_state.get_game_date(self.guild_id)
        )
        em.description = desc
        await interaction.response.edit_message(embed=em, view=self)


# ── Move Unit ─────────────────────────────────────────────────────────────────

class ArmySelectMenu(discord.ui.Select):
    def __init__(self, armies: list[dict]) -> None:
        opts = []
        for a in armies[:25]:
            prov  = a.get("province_name") or a.get("province_id") or "?"
            state = a.get("state", "?")
            str_  = float(a.get("strength_pct") or 100)
            opts.append(discord.SelectOption(
                label=f"Army #{a['army_num']} — {prov}",
                value=a["army_id"],
                description=f"State: {state}  Str: {str_:.0f}%",
            ))
        super().__init__(placeholder="Select army to move…", options=opts, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view: MoveUnitView = self.view
        view.selected_army_id = self.values[0]
        # Find army label
        for a in view.armies:
            if a["army_id"] == self.values[0]:
                prov = a.get("province_name") or a.get("province_id") or "?"
                view.selected_army_label = f"Army #{a['army_num']} in {prov}"
                break
        view.stage = "province"
        await view._update_message(interaction)


class ProvinceSelectMenu(discord.ui.Select):
    def __init__(self, provinces: list[dict]) -> None:
        opts = []
        for p in provinces[:25]:
            owner = p.get("owner_country") or "?"
            opts.append(discord.SelectOption(
                label=p["province_name"][:100],
                value=p["province_id"],
                description=f"Owner: {owner}",
            ))
        super().__init__(placeholder="Select destination province…", options=opts, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view: MoveUnitView = self.view
        view.selected_province_id = self.values[0]
        # Find province name
        for p in view.provinces:
            if p["province_id"] == self.values[0]:
                view.selected_province_name = p["province_name"]
                break
        view.stage = "confirm"
        await view._update_message(interaction)


class MoveUnitView(discord.ui.View):
    def __init__(
        self,
        country_id: str,
        armies: list[dict],
        provinces: list[dict],
        guild_id: str,
        enemy_country_ids: list[str],
    ) -> None:
        super().__init__(timeout=120)
        self.country_id              = country_id
        self.armies                  = armies
        self.provinces               = provinces
        self.guild_id                = guild_id
        self.enemy_country_ids       = enemy_country_ids
        self.selected_army_id:       str | None = None
        self.selected_army_label:    str        = "Army"
        self.selected_province_id:   str | None = None
        self.selected_province_name: str        = "?"
        self.stage                              = "army"
        self._build_items()

    def _build_items(self):
        self.clear_items()
        if self.stage == "army":
            self.add_item(ArmySelectMenu(self.armies))
        elif self.stage == "province":
            self.add_item(ProvinceSelectMenu(self.provinces))
        elif self.stage == "confirm":
            confirm_btn = discord.ui.Button(
                label="⚔️ March!", style=discord.ButtonStyle.danger, custom_id="move_confirm"
            )
            confirm_btn.callback = self._do_confirm
            cancel_btn = discord.ui.Button(
                label="❌ Cancel", style=discord.ButtonStyle.secondary, custom_id="move_cancel"
            )
            cancel_btn.callback = self._do_cancel
            self.add_item(confirm_btn)
            self.add_item(cancel_btn)

    def _compute_provinces_to_traverse(self) -> int:
        """Simple estimate: 1 province hop (no adjacency graph in DB)."""
        return 1

    async def _do_confirm(self, interaction: discord.Interaction):
        gd   = game_state.get_game_day(self.guild_id)
        hops = self._compute_provinces_to_traverse()
        res  = war_move_army(
            self.selected_army_id,
            self.selected_province_id,
            hops,
            gd,
        )
        if res["ok"]:
            arrival_date = game_state.game_date_str(res["arrival_day"])
            em = embeds.move_confirm_embed(
                self.selected_army_label,
                self.selected_province_name,
                res["travel_days"],
                arrival_date,
            )
            em.title = "🗺️  March Orders Issued!"
            await interaction.response.edit_message(embed=em, view=None)
        else:
            em = embeds.war_action_result_embed("Move Failed", res["message"], False)
            await interaction.response.edit_message(embed=em, view=None)

    async def _do_cancel(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="March orders cancelled.", embed=None, view=None
        )

    async def _update_message(self, interaction: discord.Interaction):
        self._build_items()
        gd   = game_state.get_game_day(self.guild_id)
        date = game_state.game_date_str(gd)

        if self.stage == "province":
            em = embeds.move_army_embed(
                _country_name(self.country_id), self.armies, date
            )
            em.title       = f"🗺️  {self.selected_army_label} — Choose Destination"
            em.description = "Select the province to march to."
        elif self.stage == "confirm":
            hops = self._compute_provinces_to_traverse()
            from ww1_economy.army_system import TRAVEL_DAYS_PER_PROVINCE
            import math
            travel_days  = max(1, math.ceil(hops * TRAVEL_DAYS_PER_PROVINCE))
            arrival_day  = gd + travel_days
            arrival_date = game_state.game_date_str(arrival_day)
            em = embeds.move_confirm_embed(
                self.selected_army_label,
                self.selected_province_name,
                travel_days,
                arrival_date,
            )
        else:
            em = embeds.move_army_embed(
                _country_name(self.country_id), self.armies, date
            )
        await interaction.response.edit_message(embed=em, view=self)


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class WarCog(commands.Cog, name="War"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _get_country(self, ctx: commands.Context) -> dict | None:
        cid = game_state.get_user_country(str(ctx.guild.id), str(ctx.author.id))
        if cid is None:
            return None
        return get_country_by_id(cid)

    async def _no_country(self, ctx: commands.Context):
        await ctx.send(embed=discord.Embed(
            title="❌  No Country",
            description="You haven't chosen a country yet. Use `rp pick_country` first.",
            colour=0xD84315,
        ))

    # ── declare_war ───────────────────────────────────────────────────────────

    @commands.command(name="declare_war", aliases=["dw"])
    async def declare_war(self, ctx: commands.Context, *, country: str):
        """Declare war on another country."""
        my_country = self._get_country(ctx)
        if my_country is None:
            return await self._no_country(ctx)

        target = find_country(country)
        if target is None:
            return await ctx.send(embed=discord.Embed(
                title="❌  Country Not Found",
                description=f"No country matching `{country}` found.",
                colour=0xD84315,
            ))

        if target["country_id"] == my_country["country_id"]:
            return await ctx.send(embed=discord.Embed(
                title="❌  Invalid Target",
                description="You cannot declare war on yourself.",
                colour=0xD84315,
            ))

        gd  = game_state.get_game_day(str(ctx.guild.id))
        res = war_declare(my_country["country_id"], target["country_id"], gd)

        if not res["ok"]:
            return await ctx.send(embed=discord.Embed(
                title="❌  Cannot Declare War",
                description=res["message"],
                colour=0xD84315,
            ))

        date = game_state.game_date_str(gd)
        em   = embeds.war_declare_embed(
            my_country["country_name"],
            target["country_name"],
            res["war_id"],
            date,
        )
        await ctx.send(embed=em)

    # ── war ──────────────────────────────────────────────────────────────────

    @commands.command(name="war")
    async def war(self, ctx: commands.Context, war_id: str | None = None):
        """Show war status. Optionally pass a war ID for a specific war."""
        my_country = self._get_country(ctx)
        if my_country is None:
            return await self._no_country(ctx)

        cid  = my_country["country_id"]
        gd   = game_state.get_game_day(str(ctx.guild.id))
        date = game_state.game_date_str(gd)

        wars = get_active_wars_for_country(cid)
        if not wars:
            em = embeds.war_list_embed([], my_country["country_name"], date)
            return await ctx.send(embed=em)

        # If a war_id was specified, find that specific war
        target_war_id: str | None = None
        if war_id:
            for w in wars:
                if w["war_id"].startswith(war_id) or w["war_id"] == war_id:
                    target_war_id = w["war_id"]
                    break
            if target_war_id is None:
                em = embeds.war_action_result_embed(
                    "War Not Found",
                    f"No active war with ID starting `{war_id}` found for your country.",
                    False,
                )
                return await ctx.send(embed=em)
        else:
            # Show the first (or only) war directly, list others
            if len(wars) > 1:
                nm = _build_name_map()
                em = embeds.war_list_embed(wars, my_country["country_name"], date)
                em.description += (
                    "\n\n*Use `rp war <war_id_prefix>` to view a specific war's details.*"
                )
                return await ctx.send(embed=em)
            target_war_id = wars[0]["war_id"]

        details = get_war_details(target_war_id)
        if details is None:
            return await ctx.send("War data not found.")

        nm = _build_name_map()
        em = embeds.war_status_embed(
            details["war"], details["participants"],
            details["occupations"], date, nm
        )
        view = WarStatusView(target_war_id, cid, str(ctx.guild.id))
        await ctx.send(embed=em, view=view)

    # ── call_allies ───────────────────────────────────────────────────────────

    @commands.command(name="call_allies", aliases=["ca"])
    async def call_allies(self, ctx: commands.Context):
        """Call an allied country into one of your wars."""
        my_country = self._get_country(ctx)
        if my_country is None:
            return await self._no_country(ctx)

        cid    = my_country["country_id"]
        gd     = game_state.get_game_day(str(ctx.guild.id))
        date   = game_state.game_date_str(gd)
        allies = get_ally_country_ids(cid)
        wars   = get_active_wars_for_country(cid)

        if not allies:
            return await ctx.send(embed=embeds.call_allies_embed(
                my_country["country_name"], [], date
            ))

        if not wars:
            return await ctx.send(embed=embeds.war_action_result_embed(
                "Call Allies",
                "You are not in any active war. Declare war first.",
                False,
            ))

        em   = embeds.call_allies_embed(my_country["country_name"], allies, date)
        view = CallAlliesView(cid, allies, wars, str(ctx.guild.id))
        await ctx.send(embed=em, view=view)

    # ── move_unit ─────────────────────────────────────────────────────────────

    @commands.command(name="move_unit", aliases=["move"])
    async def move_unit(self, ctx: commands.Context):
        """Order an army to march to a province."""
        my_country = self._get_country(ctx)
        if my_country is None:
            return await self._no_country(ctx)

        cid    = my_country["country_id"]
        gd     = game_state.get_game_day(str(ctx.guild.id))
        date   = game_state.game_date_str(gd)
        armies = get_country_armies(cid)

        # Filter to movable armies
        movable = [a for a in armies if a["state"] in ("idle", "retreating")]
        if not movable:
            em = embeds.move_army_embed(my_country["country_name"], [], date)
            em.description = (
                "No armies available to move.\n"
                "Armies must be **idle** (not recruiting, in combat, or destroyed)."
            )
            return await ctx.send(embed=em)

        # Provinces to show: own + at-war enemies
        wars = get_active_wars_for_country(cid)
        enemy_ids: list[str] = []
        for w in wars:
            if w["attacker"] != cid:
                enemy_ids.append(w["attacker"])
            if w["defender"] != cid:
                enemy_ids.append(w["defender"])

        provinces = get_all_provinces_list(
            owner_country=cid,
            enemy_countries=enemy_ids or None,
        )

        em   = embeds.move_army_embed(my_country["country_name"], movable, date)
        view = MoveUnitView(cid, movable, provinces, str(ctx.guild.id), enemy_ids)
        await ctx.send(embed=em, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WarCog(bot))
