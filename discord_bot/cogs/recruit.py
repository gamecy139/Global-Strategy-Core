"""
Recruitment cog — rp recruit_army / rp ra

Multi-step interactive army recruitment flow:
  Step 1  Province select  (dropdown)
  Step 2  Unit slot select (multi-select) + qty input via chat
  Step 3  Summary screen
  Step 4  Start / Cancel buttons  →  creates army in DB
"""
from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

from discord_bot import embeds, game_state
from discord_bot.ww1_data import (
    get_country_by_id,
    get_provinces,
    get_recruitable_slots,
    get_recruitment_cap_info,
    execute_army_recruitment,
)

SLOT_ORDER: list[str] = ["F1", "F2", "FL1", "S1", "S2", "N1"]

SLOT_LABELS: dict[str, str] = {
    "F1":  "⚔️  Front Line I",
    "F2":  "🗡️  Front Line II",
    "FL1": "🐎  Flank",
    "S1":  "🔭  Support I",
    "S2":  "💥  Support II",
    "N1":  "⚓  Naval",
}


# ── Step 4: Summary — Start / Cancel ─────────────────────────────────────────

class SummaryView(discord.ui.View):
    def __init__(
        self,
        country:       dict,
        province_id:   str,
        province_name: str,
        selections:    dict,
        total_gold:    float,
        total_pop:     int,
        total_days:    int,
        treasury:      float,
        penalty:       bool,
        guild_id:      str,
        user_id:       str,
        game_day:      int,
        current_month: int,
    ) -> None:
        super().__init__(timeout=180)
        self.country       = country
        self.province_id   = province_id
        self.province_name = province_name
        self.selections    = selections
        self.total_gold    = total_gold
        self.total_pop     = total_pop
        self.total_days    = total_days
        self.treasury      = treasury
        self.penalty       = penalty
        self.guild_id      = guild_id
        self.user_id       = user_id
        self.game_day      = game_day
        self.current_month = current_month

    @discord.ui.button(label="⚔️  Start Recruitment", style=discord.ButtonStyle.success)
    async def start_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "This isn't your recruitment session.", ephemeral=True
            )
            return

        await interaction.response.defer()

        actual = game_state.get_user_country(self.guild_id, str(interaction.user.id))
        if actual != self.country["country_id"]:
            await interaction.edit_original_response(
                embed=embeds.recruit_error_embed("You no longer control this country."),
                view=None,
            )
            return

        result = execute_army_recruitment(
            country_id    = self.country["country_id"],
            province_id   = self.province_id,
            province_name = self.province_name,
            selections    = self.selections,
            game_day      = self.game_day,
            current_month = self.current_month,
        )

        if not result["ok"]:
            await interaction.edit_original_response(
                embed=embeds.recruit_error_embed(result["reason"]),
                view=None,
            )
            return

        await interaction.edit_original_response(
            embed=embeds.recruit_started_embed(
                province_name = self.province_name,
                selections    = self.selections,
                total_gold    = result["total_gold"],
                total_pop     = result["total_pop"],
                total_days    = result["total_days"],
            ),
            view=None,
        )

    @discord.ui.button(label="✖  Cancel", style=discord.ButtonStyle.danger)
    async def cancel_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "This isn't your recruitment session.", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            embed=embeds.select_error_embed("Recruitment cancelled."),
            view=None,
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


# ── Step 2: Unit slot multi-select ────────────────────────────────────────────

class RecruitUnitSelect(discord.ui.Select):
    def __init__(self, slot_units: dict, parent_view: "RecruitView") -> None:
        self.slot_units  = slot_units
        self.parent_view = parent_view

        available = [s for s in SLOT_ORDER if s in slot_units]
        options = [
            discord.SelectOption(
                label       = SLOT_LABELS.get(slot, slot),
                value       = slot,
                description = slot_units[slot]["unit_name"][:100],
            )
            for slot in available
        ]
        super().__init__(
            placeholder = "Select unit categories to recruit…",
            min_values  = 1,
            max_values  = len(options),
            options     = options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.parent_view

        if str(interaction.user.id) != view.user_id:
            await interaction.response.send_message(
                "This isn't your recruitment session.", ephemeral=True
            )
            return

        await interaction.response.defer()

        selected_slots    = set(self.values)
        already_confirmed = set(view.quantities.keys())

        # Ask qty for selected slots that don't already have a confirmed quantity.
        # Previously confirmed slots are NEVER cleared — each interaction only adds.
        for slot in [s for s in SLOT_ORDER if s in selected_slots and s not in already_confirmed]:
            unit = self.slot_units[slot]
            prompt_msg = await interaction.channel.send(
                f"<@{interaction.user.id}> **How many {unit['unit_name']} (`{slot}`) to recruit?**"
                f"  *(reply with a whole number — 60 s timeout)*"
            )

            def _check(m: discord.Message, _uid=interaction.user.id, _cid=interaction.channel_id):
                return m.author.id == _uid and m.channel.id == _cid

            try:
                reply = await interaction.client.wait_for(
                    "message", check=_check, timeout=60.0
                )
                raw = reply.content.strip()
                try:
                    qty = int(raw)
                except ValueError:
                    qty = 0

                try:
                    await prompt_msg.delete()
                    await reply.delete()
                except Exception:
                    pass

                if qty <= 0:
                    await interaction.channel.send(
                        f"⚠️ Invalid quantity for `{slot}` — must be a positive whole number."
                        " Slot skipped.",
                        delete_after=10,
                    )
                    continue

                view.quantities[slot] = qty

            except asyncio.TimeoutError:
                try:
                    await prompt_msg.delete()
                except Exception:
                    pass
                await interaction.channel.send(
                    f"⏱️ Timed out waiting for `{slot}` quantity — slot skipped.",
                    delete_after=10,
                )

        # Refresh the main embed
        await interaction.edit_original_response(
            embed=embeds.recruit_units_embed(
                country_name  = view.country_name,
                province_name = view.province_name,
                slot_units    = self.slot_units,
                quantities    = view.quantities,
            ),
            view=view,
        )


# ── Step 2: Recruitment view (select + continue button) ───────────────────────

class RecruitView(discord.ui.View):
    def __init__(
        self,
        slot_units:    dict,
        province_id:   str,
        province_name: str,
        country_id:    str,
        country_name:  str,
        guild_id:      str,
        user_id:       str,
        game_day:      int,
        current_month: int,
    ) -> None:
        super().__init__(timeout=300)
        self.slot_units    = slot_units
        self.province_id   = province_id
        self.province_name = province_name
        self.country_id    = country_id
        self.country_name  = country_name
        self.guild_id      = guild_id
        self.user_id       = user_id
        self.game_day      = game_day
        self.current_month = current_month
        self.quantities: dict[str, int] = {}

        self.add_item(RecruitUnitSelect(slot_units, self))

    @discord.ui.button(label="✅  Continue", style=discord.ButtonStyle.primary, row=1)
    async def continue_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "This isn't your recruitment session.", ephemeral=True
            )
            return

        if not self.quantities:
            await interaction.response.send_message(
                "Select at least one unit category and enter a quantity first.",
                ephemeral=True,
            )
            return

        # Build selections dict (slot → {unit_name, qty, unit})
        selections: dict = {}
        for slot, qty in self.quantities.items():
            unit = self.slot_units[slot]
            selections[slot] = {"unit_name": unit["unit_name"], "qty": qty, "unit": unit}

        # Compute preview totals (same logic as execute, for display only)
        cap_info   = get_recruitment_cap_info(self.country_id, self.current_month)
        penalty    = cap_info["penalty"]
        total_gold = 0.0
        total_pop  = 0
        total_time = 0
        for sel in selections.values():
            qty  = sel["qty"]
            unit = sel["unit"]
            g    = float(unit["gold_cost"]) * qty * (3 if penalty else 1)
            p    = int(unit["population_required"]) * qty
            t    = int(unit["recruitment_time_days"]) * qty
            if penalty:
                t = int(t * 1.5)
            total_gold += g
            total_pop  += p
            total_time  = max(total_time, t)

        country  = get_country_by_id(self.country_id) or {}
        treasury = float(country.get("treasury", 0.0))

        summary_view = SummaryView(
            country       = country if country else {"country_id": self.country_id},
            province_id   = self.province_id,
            province_name = self.province_name,
            selections    = selections,
            total_gold    = total_gold,
            total_pop     = total_pop,
            total_days    = total_time,
            treasury      = treasury,
            penalty       = penalty,
            guild_id      = self.guild_id,
            user_id       = self.user_id,
            game_day      = self.game_day,
            current_month = self.current_month,
        )

        await interaction.response.edit_message(
            embed=embeds.recruit_summary_embed(
                country_name  = self.country_name,
                province_name = self.province_name,
                selections    = selections,
                total_gold    = total_gold,
                total_pop     = total_pop,
                total_days    = total_time,
                treasury      = treasury,
                penalty       = penalty,
            ),
            view=summary_view,
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


# ── Step 1: Province select ───────────────────────────────────────────────────

class ProvinceSelect(discord.ui.Select):
    def __init__(
        self,
        provinces:     list[dict],
        country_id:    str,
        country_name:  str,
        guild_id:      str,
        user_id:       str,
        game_day:      int,
        current_month: int,
    ) -> None:
        self.country_id    = country_id
        self.country_name  = country_name
        self.guild_id      = guild_id
        self.user_id       = user_id
        self.game_day      = game_day
        self.current_month = current_month
        self._province_map = {str(p["province_id"]): p for p in provinces}

        options = [
            discord.SelectOption(
                label       = p["province_name"][:100],
                value       = str(p["province_id"]),
                description = (
                    f"Pop: {p['population']:,}  |  {p['resource_type']}"
                )[:100],
            )
            for p in provinces[:25]
        ]
        super().__init__(
            placeholder = "Choose a province…",
            min_values  = 1,
            max_values  = 1,
            options     = options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "This isn't your recruitment session.", ephemeral=True
            )
            return

        await interaction.response.defer()

        province      = self._province_map[self.values[0]]
        province_id   = str(province["province_id"])
        province_name = province["province_name"]

        slot_units = get_recruitable_slots(self.country_id)
        if not slot_units:
            await interaction.edit_original_response(
                embed=embeds.recruit_no_units_embed(self.country_name),
                view=None,
            )
            return

        view = RecruitView(
            slot_units    = slot_units,
            province_id   = province_id,
            province_name = province_name,
            country_id    = self.country_id,
            country_name  = self.country_name,
            guild_id      = self.guild_id,
            user_id       = self.user_id,
            game_day      = self.game_day,
            current_month = self.current_month,
        )
        await interaction.edit_original_response(
            embed=embeds.recruit_units_embed(
                country_name  = self.country_name,
                province_name = province_name,
                slot_units    = slot_units,
                quantities    = {},
            ),
            view=view,
        )


class ProvinceView(discord.ui.View):
    def __init__(
        self,
        provinces:     list[dict],
        country_id:    str,
        country_name:  str,
        guild_id:      str,
        user_id:       str,
        game_day:      int,
        current_month: int,
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(ProvinceSelect(
            provinces, country_id, country_name,
            guild_id, user_id, game_day, current_month,
        ))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


# ── Cog ───────────────────────────────────────────────────────────────────────

class RecruitCog(commands.Cog, name="Recruit"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="recruit_army", aliases=["ra"])
    async def recruit_army_cmd(self, ctx: commands.Context) -> None:
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
                "Could not load country data. Please contact an admin."
            ))
            return

        provinces = get_provinces(country_id)
        if not provinces:
            await ctx.send(embed=embeds.select_error_embed(
                "You have no provinces to recruit in."
            ))
            return

        country_name  = country["country_name"]
        game_day      = game_state.get_game_day(guild_id)
        current_month = game_day // 30

        view = ProvinceView(
            provinces     = provinces,
            country_id    = country_id,
            country_name  = country_name,
            guild_id      = guild_id,
            user_id       = user_id,
            game_day      = game_day,
            current_month = current_month,
        )
        await ctx.send(
            embed=embeds.recruit_province_embed(country_name, len(provinces)),
            view=view,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RecruitCog(bot))
