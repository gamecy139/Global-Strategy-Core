"""
War cog — rp declare_war, rp war, rp call_allies (rp ca), rp move_unit,
          rp non_core_province (rp nc), rp diff_religion (rp dr)
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
    get_opponent_country,
    get_occupied_provinces_by_winner,
    get_non_core_provinces,
    get_country_religion,
    get_different_religion_provinces,
    start_core_conversion,
    start_religion_conversion,
    war_spend_take_province,
    war_spend_puppet,
    war_spend_reparations,
    war_spend_insult,
    war_end,
    SERVER_ID,
    SCENARIO_ID,
)

GUILD_ID = "guild_demo"

# War score costs — midpoints of spec ranges
PROVINCE_COST    = 15   # 10-20
PUPPET_COST      = 90   # 80-100
INSULT_COST      = 25   # 20-30
REPARATIONS_COST = 35   # 30-40
CORE_CONV_DAYS   = 90
REL_CONV_DAYS    = 120


def _country_name(country_id: str) -> str:
    c = get_country_by_id(country_id)
    return c["country_name"] if c else country_id


def _build_name_map() -> dict[str, str]:
    return {c["country_id"]: c["country_name"] for c in get_countries()}


# =============================================================================
# WarStatusView
# =============================================================================

class WarStatusView(discord.ui.View):
    """Buttons shown with rp war — one war at a time."""

    def __init__(self, war_id: str, country_id: str, guild_id: str) -> None:
        super().__init__(timeout=120)
        self.war_id     = war_id
        self.country_id = country_id
        self.guild_id   = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user_cid = game_state.get_user_country(
            str(interaction.guild.id), str(interaction.user.id)
        )
        if user_cid != self.country_id:
            await interaction.response.send_message(
                "Only the country's leader can use these war controls.", ephemeral=True
            )
            return False
        return True

    async def _refresh_embed(self, interaction: discord.Interaction) -> None:
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
        await interaction.response.defer()
        await interaction.followup.send(embed=em, ephemeral=True)
        if res["ok"]:
            await self._refresh_embed(interaction)

    @discord.ui.button(label="🏳️ Surrender", style=discord.ButtonStyle.danger, row=1)
    async def btn_surrender(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = war_surrender(self.war_id, self.country_id)
        em  = embeds.war_action_result_embed("Surrender", res["message"], res["ok"])
        await interaction.response.send_message(embed=em, ephemeral=True)

        if res["ok"]:
            # Notify the winner with the Victory Decision embed
            winner_cid  = get_opponent_country(self.war_id, self.country_id)
            if winner_cid is None:
                return
            winner_score = float(res.get("victory_score") or 100)
            winner_name  = _country_name(winner_cid)
            loser_name   = _country_name(self.country_id)

            # Find the winner's Discord user to ping
            winner_uid = game_state.get_country_owner_id(self.guild_id, winner_cid)
            mention    = f"<@{winner_uid}>" if winner_uid else f"**{winner_name}**"

            view = VictoryDecisionView(
                war_id       = self.war_id,
                winner_cid   = winner_cid,
                loser_cid    = self.country_id,
                guild_id     = self.guild_id,
                score        = winner_score,
                winner_name  = winner_name,
                loser_name   = loser_name,
            )
            vem = embeds.victory_decision_embed(
                winner_name, loser_name, winner_score, set(), []
            )
            vem.description = (
                f"{mention} — **{loser_name}** has surrendered!\n"
                f"You hold **{winner_score:.0f}** war score to spend on your demands."
            )
            await interaction.channel.send(embed=vem, view=view)

    @discord.ui.button(label="👑 Proclaim Victory", style=discord.ButtonStyle.primary, row=1)
    async def btn_victory(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = war_proclaim_victory(self.war_id, self.country_id)
        if not res["ok"]:
            em = embeds.war_action_result_embed("Proclaim Victory", res["message"], False)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        score       = float(res["victory_score"])
        winner_name = _country_name(self.country_id)
        loser_cid   = get_opponent_country(self.war_id, self.country_id)
        loser_name  = _country_name(loser_cid) if loser_cid else "?"

        view = VictoryDecisionView(
            war_id      = self.war_id,
            winner_cid  = self.country_id,
            loser_cid   = loser_cid or "",
            guild_id    = self.guild_id,
            score       = score,
            winner_name = winner_name,
            loser_name  = loser_name,
        )
        em = embeds.victory_decision_embed(winner_name, loser_name, score, set(), [])
        await interaction.response.send_message(embed=em, view=view, ephemeral=False)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._refresh_embed(interaction)


# =============================================================================
# Victory Decision Flow
# =============================================================================

class OptionsSelect(discord.ui.Select):
    """Multi-select dropdown for choosing victory demands."""

    def __init__(self, current: set[str]) -> None:
        opts = [
            discord.SelectOption(
                label="⚔️  Occupy Provinces",
                value="occupy",
                description=f"{PROVINCE_COST} war score per province",
                default="occupy" in current,
            ),
            discord.SelectOption(
                label="🤝  Puppet State",
                value="puppet",
                description=f"{PUPPET_COST} war score",
                default="puppet" in current,
            ),
            discord.SelectOption(
                label="😤  Insult",
                value="insult",
                description=f"{INSULT_COST} war score",
                default="insult" in current,
            ),
            discord.SelectOption(
                label="💰  War Reparations",
                value="reparations",
                description=f"{REPARATIONS_COST} war score (2-year economic penalty)",
                default="reparations" in current,
            ),
        ]
        super().__init__(
            placeholder="Select victory demands…",
            options=opts,
            min_values=0,
            max_values=4,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view: VictoryDecisionView = self.view
        view.selected_opts = set(self.values)
        if "occupy" not in view.selected_opts:
            view.selected_provinces.clear()
        view._rebuild_items()
        em = embeds.victory_decision_embed(
            view.winner_name, view.loser_name, view.score_remaining,
            view.selected_opts, view.selected_provinces, view._province_names,
        )
        await interaction.response.edit_message(embed=em, view=view)


class VictoryDecisionView(discord.ui.View):
    """Step 1: choose which demands to impose."""

    def __init__(
        self,
        war_id:      str,
        winner_cid:  str,
        loser_cid:   str,
        guild_id:    str,
        score:       float,
        winner_name: str,
        loser_name:  str,
    ) -> None:
        super().__init__(timeout=300)
        self.war_id           = war_id
        self.winner_cid       = winner_cid
        self.loser_cid        = loser_cid
        self.guild_id         = guild_id
        self.score_remaining  = score
        self.winner_name      = winner_name
        self.loser_name       = loser_name
        self.selected_opts:       set[str]       = set()
        self.selected_provinces:  list[str]      = []
        self._province_names:     dict[str, str] = {}
        self._rebuild_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user_cid = game_state.get_user_country(
            str(interaction.guild.id), str(interaction.user.id)
        )
        if user_cid != self.winner_cid:
            await interaction.response.send_message(
                "Only the winning nation's leader can use these controls.", ephemeral=True
            )
            return False
        return True

    def _total_cost(self) -> float:
        cost = PROVINCE_COST * len(self.selected_provinces)
        if "puppet"      in self.selected_opts: cost += PUPPET_COST
        if "insult"      in self.selected_opts: cost += INSULT_COST
        if "reparations" in self.selected_opts: cost += REPARATIONS_COST
        return cost

    def _ready(self) -> bool:
        if not self.selected_opts:
            return False
        if "occupy" in self.selected_opts and not self.selected_provinces:
            return False
        return self._total_cost() <= self.score_remaining

    def _rebuild_items(self) -> None:
        self.clear_items()
        self.add_item(OptionsSelect(self.selected_opts))

        if "occupy" in self.selected_opts:
            n   = len(self.selected_provinces)
            lbl = f"🏛️ Select Provinces ({n} chosen)" if n else "🏛️ Select Provinces"
            sel_btn = discord.ui.Button(
                label=lbl, style=discord.ButtonStyle.primary,
                custom_id="vd_sel_provinces", row=1,
            )
            sel_btn.callback = self._go_select_provinces
            self.add_item(sel_btn)

        cont_btn = discord.ui.Button(
            label="➡️ Continue",
            style=discord.ButtonStyle.success,
            disabled=not self._ready(),
            custom_id="vd_continue",
            row=2,
        )
        cont_btn.callback = self._go_confirm

        cancel_btn = discord.ui.Button(
            label="❌ Cancel",
            style=discord.ButtonStyle.secondary,
            custom_id="vd_cancel",
            row=2,
        )
        cancel_btn.callback = self._do_cancel

        self.add_item(cont_btn)
        self.add_item(cancel_btn)

    async def _go_select_provinces(self, interaction: discord.Interaction) -> None:
        provinces = get_occupied_provinces_by_winner(self.war_id, self.winner_cid)
        if not provinces:
            return await interaction.response.send_message(
                "No fully-occupied provinces are available to annex yet.", ephemeral=True
            )
        view = ProvinceSelectView(self, provinces)
        em   = embeds.province_select_embed(
            self.loser_name, provinces, self.score_remaining, self.selected_provinces
        )
        await interaction.response.edit_message(embed=em, view=view)

    async def _go_confirm(self, interaction: discord.Interaction) -> None:
        if not self._ready():
            return await interaction.response.send_message(
                "Select at least one demand and ensure you have enough war score.", ephemeral=True
            )
        view = ConfirmDemandsView(self)
        em   = embeds.confirm_demands_embed(
            self.winner_name, self.loser_name,
            self.selected_opts, self.selected_provinces, self._province_names,
            self._total_cost(), self.score_remaining,
        )
        await interaction.response.edit_message(embed=em, view=view)

    async def _do_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            content="Victory demands cancelled.", embed=None, view=None
        )


class ProvinceMultiSelect(discord.ui.Select):
    """Multi-select for picking provinces to annex."""

    def __init__(self, provinces: list[dict], already: list[str]) -> None:
        opts = []
        for p in provinces[:25]:
            opts.append(discord.SelectOption(
                label=p["province_name"][:100],
                value=p["province_id"],
                description=f"Cost: {PROVINCE_COST} war score",
                default=p["province_id"] in already,
            ))
        super().__init__(
            placeholder="Select provinces to annex…",
            options=opts,
            min_values=0,
            max_values=len(opts),
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view: ProvinceSelectView = self.view
        view.pending_selection   = list(self.values)
        await interaction.response.defer()


class ProvinceSelectView(discord.ui.View):
    """Step 2 (if Occupy chosen): pick specific provinces."""

    def __init__(self, parent: VictoryDecisionView, provinces: list[dict]) -> None:
        super().__init__(timeout=300)
        self.parent            = parent
        self.provinces         = provinces
        self.pending_selection = list(parent.selected_provinces)
        self.add_item(ProvinceMultiSelect(provinces, self.pending_selection))

        confirm = discord.ui.Button(
            label="✅ Confirm Selection",
            style=discord.ButtonStyle.success,
            custom_id="ps_confirm",
            row=1,
        )
        confirm.callback = self._do_confirm

        back = discord.ui.Button(
            label="🔙 Go Back",
            style=discord.ButtonStyle.secondary,
            custom_id="ps_back",
            row=1,
        )
        back.callback = self._do_back

        self.add_item(confirm)
        self.add_item(back)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.parent.interaction_check(interaction)

    async def _do_confirm(self, interaction: discord.Interaction) -> None:
        p = self.parent
        p.selected_provinces = list(self.pending_selection)
        # Build name map
        for prov in self.provinces:
            p._province_names[prov["province_id"]] = prov["province_name"]
        p._rebuild_items()
        em = embeds.victory_decision_embed(
            p.winner_name, p.loser_name, p.score_remaining,
            p.selected_opts, p.selected_provinces, p._province_names,
        )
        await interaction.response.edit_message(embed=em, view=p)

    async def _do_back(self, interaction: discord.Interaction) -> None:
        p = self.parent
        p._rebuild_items()
        em = embeds.victory_decision_embed(
            p.winner_name, p.loser_name, p.score_remaining,
            p.selected_opts, p.selected_provinces, p._province_names,
        )
        await interaction.response.edit_message(embed=em, view=p)


class ConfirmDemandsView(discord.ui.View):
    """Step 3: final confirmation before enforcing demands."""

    def __init__(self, parent: VictoryDecisionView) -> None:
        super().__init__(timeout=300)
        self.parent = parent

        enforce = discord.ui.Button(
            label="✅ Enforce Demands",
            style=discord.ButtonStyle.success,
            custom_id="cd_enforce",
        )
        enforce.callback = self._do_enforce

        back = discord.ui.Button(
            label="🔙 Go Back",
            style=discord.ButtonStyle.danger,
            custom_id="cd_back",
        )
        back.callback = self._do_back

        self.add_item(enforce)
        self.add_item(back)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.parent.interaction_check(interaction)

    async def _do_enforce(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        p   = self.parent
        gd  = game_state.get_game_day(p.guild_id)
        effects: list[str] = []
        errors:  list[str] = []

        # Occupy provinces
        for pid in p.selected_provinces:
            res = war_spend_take_province(p.war_id, p.winner_cid, pid, PROVINCE_COST, gd)
            pname = p._province_names.get(pid, pid)
            if res["ok"]:
                effects.append(f"✅ Annexed **{pname}** (non-core, conversion started)")
            else:
                errors.append(f"❌ Annex **{pname}**: {res['message']}")

        # Puppet state
        if "puppet" in p.selected_opts:
            res = war_spend_puppet(p.war_id, p.winner_cid, p.loser_cid, PUPPET_COST, gd)
            if res["ok"]:
                effects.append(f"✅ **{p.loser_name}** is now your puppet state")
            else:
                errors.append(f"❌ Puppet: {res['message']}")

        # Insult
        if "insult" in p.selected_opts:
            res = war_spend_insult(p.war_id, p.winner_cid, p.loser_cid, INSULT_COST)
            if res["ok"]:
                effects.append(f"✅ Insulted **{p.loser_name}** (+5 opinion, −10 relations)")
            else:
                errors.append(f"❌ Insult: {res['message']}")

        # Reparations
        if "reparations" in p.selected_opts:
            res = war_spend_reparations(p.war_id, p.winner_cid, p.loser_cid, REPARATIONS_COST, gd)
            if res["ok"]:
                effects.append(
                    f"✅ War reparations imposed on **{p.loser_name}** "
                    f"(−20% efficiency for 2 years, +1.5/day income)"
                )
            else:
                errors.append(f"❌ Reparations: {res['message']}")

        # End the war
        war_end(p.war_id, "attacker_victory")

        lines  = effects + errors
        colour = 0x4CAF50 if not errors else 0xFF9800
        em = discord.Embed(
            title="⚔️  Victory Terms Enforced",
            description="\n".join(lines) if lines else "No demands enforced.",
            colour=colour,
        )
        em.add_field(
            name="🕊️ War Ended",
            value=f"The war between **{p.winner_name}** and **{p.loser_name}** is over.",
            inline=False,
        )
        em.set_footer(text="WW1 Roleplay  •  prefix: rp")
        await interaction.followup.edit_message(interaction.message.id, embed=em, view=None)

    async def _do_back(self, interaction: discord.Interaction) -> None:
        p = self.parent
        p._rebuild_items()
        em = embeds.victory_decision_embed(
            p.winner_name, p.loser_name, p.score_remaining,
            p.selected_opts, p.selected_provinces, p._province_names,
        )
        await interaction.response.edit_message(embed=em, view=p)


# =============================================================================
# Non-Core Province Views
# =============================================================================

class NonCoreSelect(discord.ui.Select):
    def __init__(self, provinces: list[dict], already: list[str]) -> None:
        opts = []
        for p in provinces[:25]:
            pop = f"{p.get('population', 0):,}"
            opts.append(discord.SelectOption(
                label=p["province_name"][:100],
                value=p["province_id"],
                description=f"Pop {pop} | Conversion: {CORE_CONV_DAYS} days",
                default=p["province_id"] in already,
            ))
        super().__init__(
            placeholder="Select non-core provinces to convert…",
            options=opts,
            min_values=0,
            max_values=len(opts),
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view: NonCoreView = self.view
        view.selected = list(self.values)
        view._rebuild_items()
        em = embeds.non_core_province_embed(
            view.country_name, view.provinces,
            game_state.get_game_date(view.guild_id),
            selected=view.selected,
            conv_days=CORE_CONV_DAYS,
        )
        await interaction.response.edit_message(embed=em, view=view)


class NonCoreView(discord.ui.View):
    def __init__(
        self, country_id: str, country_name: str,
        provinces: list[dict], guild_id: str,
    ) -> None:
        super().__init__(timeout=120)
        self.country_id   = country_id
        self.country_name = country_name
        self.provinces    = provinces
        self.guild_id     = guild_id
        self.selected:    list[str] = []
        self._rebuild_items()

    def _rebuild_items(self) -> None:
        self.clear_items()
        self.add_item(NonCoreSelect(self.provinces, self.selected))

        confirm = discord.ui.Button(
            label=(
                f"✅ Confirm ({len(self.selected)} province(s), {CORE_CONV_DAYS} days each)"
                if self.selected else "✅ Confirm"
            ),
            style=discord.ButtonStyle.success,
            disabled=not self.selected,
            custom_id="nc_confirm",
            row=1,
        )
        confirm.callback = self._do_confirm

        cancel = discord.ui.Button(
            label="❌ Cancel",
            style=discord.ButtonStyle.secondary,
            custom_id="nc_cancel",
            row=1,
        )
        cancel.callback = self._do_cancel
        self.add_item(confirm)
        self.add_item(cancel)

    async def _do_confirm(self, interaction: discord.Interaction) -> None:
        gd    = game_state.get_game_day(self.guild_id)
        names = {p["province_id"]: p["province_name"] for p in self.provinces}
        lines = []
        for pid in self.selected:
            end_day = gd + CORE_CONV_DAYS
            start_core_conversion(pid, self.country_id, gd, end_day)
            lines.append(
                f"• **{names.get(pid, pid)}** — completes "
                f"**{game_state.game_date_str(end_day)}**"
            )
        em = discord.Embed(
            title="🏛️  Core Conversion Started",
            description=(
                f"{len(lines)} province(s) queued for core conversion:\n"
                + "\n".join(lines)
                + f"\n\n*Conversion time: {CORE_CONV_DAYS} days each.*"
            ),
            colour=0x2E7D32,
        )
        em.set_footer(text="WW1 Roleplay  •  prefix: rp")
        await interaction.response.edit_message(embed=em, view=None)

    async def _do_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            content="Cancelled.", embed=None, view=None
        )


# =============================================================================
# Religion Conversion Views
# =============================================================================

class ReligionSelect(discord.ui.Select):
    def __init__(self, provinces: list[dict], already: list[str]) -> None:
        opts = []
        for p in provinces[:25]:
            prel = p.get("province_religion", "Unknown")
            opts.append(discord.SelectOption(
                label=p["province_name"][:100],
                value=p["province_id"],
                description=f"{prel} → convert | {REL_CONV_DAYS} days",
                default=p["province_id"] in already,
            ))
        super().__init__(
            placeholder="Select provinces to convert…",
            options=opts,
            min_values=0,
            max_values=len(opts),
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view: ReligionView = self.view
        view.selected = list(self.values)
        view._rebuild_items()
        em = embeds.religion_province_embed(
            view.country_name, view.country_religion, view.provinces,
            game_state.get_game_date(view.guild_id),
            selected=view.selected,
            conv_days=REL_CONV_DAYS,
        )
        await interaction.response.edit_message(embed=em, view=view)


class ReligionView(discord.ui.View):
    def __init__(
        self, country_id: str, country_name: str, country_religion: str,
        provinces: list[dict], guild_id: str,
    ) -> None:
        super().__init__(timeout=120)
        self.country_id       = country_id
        self.country_name     = country_name
        self.country_religion = country_religion
        self.provinces        = provinces
        self.guild_id         = guild_id
        self.selected:        list[str] = []
        self._rebuild_items()

    def _rebuild_items(self) -> None:
        self.clear_items()
        self.add_item(ReligionSelect(self.provinces, self.selected))

        confirm = discord.ui.Button(
            label=(
                f"✅ Confirm ({len(self.selected)} province(s), {REL_CONV_DAYS} days each)"
                if self.selected else "✅ Confirm"
            ),
            style=discord.ButtonStyle.success,
            disabled=not self.selected,
            custom_id="rel_confirm",
            row=1,
        )
        confirm.callback = self._do_confirm

        cancel = discord.ui.Button(
            label="❌ Cancel",
            style=discord.ButtonStyle.secondary,
            custom_id="rel_cancel",
            row=1,
        )
        cancel.callback = self._do_cancel
        self.add_item(confirm)
        self.add_item(cancel)

    async def _do_confirm(self, interaction: discord.Interaction) -> None:
        gd    = game_state.get_game_day(self.guild_id)
        names = {p["province_id"]: p["province_name"] for p in self.provinces}
        prels = {p["province_id"]: p.get("province_religion", "Unknown") for p in self.provinces}
        lines = []
        for pid in self.selected:
            end_day = gd + REL_CONV_DAYS
            start_religion_conversion(
                pid,
                prels.get(pid, "Unknown"),
                self.country_religion,
                gd, end_day,
            )
            lines.append(
                f"• **{names.get(pid, pid)}** "
                f"({prels.get(pid, '?')} → {self.country_religion}) — "
                f"completes **{game_state.game_date_str(end_day)}**"
            )
        em = discord.Embed(
            title="⛪  Religion Conversion Started",
            description=(
                f"{len(lines)} province(s) queued for religion conversion:\n"
                + "\n".join(lines)
                + f"\n\n*Conversion time: {REL_CONV_DAYS} days each.*"
            ),
            colour=0x4A148C,
        )
        em.set_footer(text="WW1 Roleplay  •  prefix: rp")
        await interaction.response.edit_message(embed=em, view=None)

    async def _do_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            content="Cancelled.", embed=None, view=None
        )


# =============================================================================
# Call Allies Views
# =============================================================================

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


# =============================================================================
# Move Unit Views
# =============================================================================

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

    def _compute_hops(self) -> int:
        return 1

    async def _do_confirm(self, interaction: discord.Interaction):
        gd   = game_state.get_game_day(self.guild_id)
        hops = self._compute_hops()
        res  = war_move_army(
            self.selected_army_id,
            self.selected_province_id,
            hops, gd,
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
            hops = self._compute_hops()
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


# =============================================================================
# Cog
# =============================================================================

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
        """Show war status. Optionally pass a war ID prefix."""
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

        target_war_id: str | None = None
        if war_id:
            for w in wars:
                if w["war_id"].startswith(war_id) or w["war_id"] == war_id:
                    target_war_id = w["war_id"]
                    break
            if target_war_id is None:
                return await ctx.send(embed=embeds.war_action_result_embed(
                    "War Not Found",
                    f"No active war with ID starting `{war_id}` found for your country.",
                    False,
                ))
        else:
            if len(wars) > 1:
                em = embeds.war_list_embed(wars, my_country["country_name"], date)
                em.description += "\n\n*Use `rp war <war_id_prefix>` to view a specific war.*"
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
                "No Active Wars",
                "You have no active wars to call allies into.",
                False,
            ))

        view = CallAlliesView(cid, allies, wars, str(ctx.guild.id))
        em   = embeds.call_allies_embed(my_country["country_name"], allies, date)
        await ctx.send(embed=em, view=view)

    # ── move_unit ─────────────────────────────────────────────────────────────

    @commands.command(name="move_unit", aliases=["move"])
    async def move_unit(self, ctx: commands.Context):
        """Order an army to march to a new province."""
        my_country = self._get_country(ctx)
        if my_country is None:
            return await self._no_country(ctx)

        cid    = my_country["country_id"]
        gd     = game_state.get_game_day(str(ctx.guild.id))
        date   = game_state.game_date_str(gd)
        armies = [
            a for a in get_country_armies(cid)
            if a.get("state") not in ("destroyed", "moving", "in_combat", "recruiting")
        ]

        if not armies:
            return await ctx.send(embed=discord.Embed(
                title="⚠️  No Available Armies",
                description="All your armies are in combat, moving, or destroyed.",
                colour=0xD84315,
            ))

        wars            = get_active_wars_for_country(cid)
        enemy_cids: list[str] = []
        for w in wars:
            opp = get_opponent_country(w["war_id"], cid)
            if opp:
                enemy_cids.append(opp)

        provinces = get_all_provinces_list(cid, enemy_cids)
        view = MoveUnitView(cid, armies, provinces, str(ctx.guild.id), enemy_cids)
        em   = embeds.move_army_embed(_country_name(cid), armies, date)
        await ctx.send(embed=em, view=view)

    # ── non_core_province ─────────────────────────────────────────────────────

    @commands.command(name="non_core_province", aliases=["nc_province", "nc"])
    async def non_core_province(self, ctx: commands.Context):
        """List and begin core conversion for non-core provinces."""
        my_country = self._get_country(ctx)
        if my_country is None:
            return await self._no_country(ctx)

        cid      = my_country["country_id"]
        cname    = my_country["country_name"]
        gd       = game_state.get_game_day(str(ctx.guild.id))
        date     = game_state.game_date_str(gd)
        provinces = get_non_core_provinces(cid)

        em = embeds.non_core_province_embed(cname, provinces, date, conv_days=CORE_CONV_DAYS)
        if not provinces:
            return await ctx.send(embed=em)

        view = NonCoreView(cid, cname, provinces, str(ctx.guild.id))
        await ctx.send(embed=em, view=view)

    # ── diff_religion ─────────────────────────────────────────────────────────

    @commands.command(name="diff_religion", aliases=["dr_province", "dr"])
    async def diff_religion(self, ctx: commands.Context):
        """List and begin religion conversion for mismatched provinces."""
        my_country = self._get_country(ctx)
        if my_country is None:
            return await self._no_country(ctx)

        cid      = my_country["country_id"]
        cname    = my_country["country_name"]
        crel     = get_country_religion(cid)
        gd       = game_state.get_game_day(str(ctx.guild.id))
        date     = game_state.game_date_str(gd)

        if crel is None:
            return await ctx.send(embed=discord.Embed(
                title="❌  No State Religion",
                description=(
                    f"**{cname}** has no state religion configured. "
                    "Religion conversion is not available."
                ),
                colour=0xD84315,
            ))

        provinces = get_different_religion_provinces(cid)
        em = embeds.religion_province_embed(cname, crel, provinces, date, conv_days=REL_CONV_DAYS)

        if not provinces:
            return await ctx.send(embed=em)

        view = ReligionView(cid, cname, crel, provinces, str(ctx.guild.id))
        await ctx.send(embed=em, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WarCog(bot))
