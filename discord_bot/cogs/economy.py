"""
Economy cog — rp invest / rp storage / rp buildings / rp construct
"""
from __future__ import annotations

import discord
from discord.ext import commands

from discord_bot import embeds, game_state
from discord_bot.ww1_data import (
    find_country, get_country_by_id, get_provinces,
    get_storage, deduct_treasury, deduct_storage_resources,
    update_population_growth_rate, construct_building,
)


# ── Building catalogue (used by rp buildings + rp construct) ──────────────────

def _get_building_catalogue() -> list[dict]:
    from ww1_economy.resources import BUILDING_CONFIGS, BuildingTier
    result = []
    for bt, cfg in BUILDING_CONFIGS.items():
        tier_label = {
            BuildingTier.TIER1: "Tier 1 — Extraction",
            BuildingTier.TIER2: "Tier 2 — Industry",
            BuildingTier.INFRA: "Infrastructure",
        }.get(cfg.tier, str(cfg.tier))
        result.append({
            "name":                       bt.value,
            "tier":                       tier_label,
            "tier_enum":                  cfg.tier,
            "cost":                       cfg.construction_cost_gold,
            "months":                     cfg.construction_months,
            "daily_income":               cfg.daily_income,
            "monthly_production":         cfg.monthly_production,
            "production_resource":        cfg.production_resource,
            "production_unit":            cfg.production_unit,
            "gold_to_treasury_monthly":   cfg.gold_to_treasury_monthly,
            "allowed_resources":          sorted(cfg.allowed_resources),
            "construction_cost_resources": cfg.construction_resources_dict,
        })
    return result


def _find_building(query: str) -> dict | None:
    q = query.strip().lower().replace("-", " ").replace("_", " ")
    for b in _get_building_catalogue():
        if b["name"].lower() == q:
            return b
    for b in _get_building_catalogue():
        if q in b["name"].lower():
            return b
    return None


# ── Pages: buildings list splits into 3 pages ─────────────────────────────────

BUILDINGS_PAGES = [
    ("🏗️ Tier 1 — Resource Extraction", lambda b: b["tier"].startswith("Tier 1")),
    ("🏭 Tier 2 — Industry",             lambda b: b["tier"].startswith("Tier 2")),
    ("🏛️ Infrastructure",               lambda b: b["tier"].startswith("Infra")),
]


class BuildingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.page = 0
        self._update_buttons()

    def _current_embed(self) -> discord.Embed:
        label, filt = BUILDINGS_PAGES[self.page]
        data = [b for b in _get_building_catalogue() if filt(b)]
        return embeds.buildings_list_embed(label, data, self.page + 1, len(BUILDINGS_PAGES))

    def _update_buttons(self):
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= len(BUILDINGS_PAGES) - 1

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

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Construct: province select ────────────────────────────────────────────────

class ProvinceSelect(discord.ui.Select):
    def __init__(self, building: dict, provinces: list[dict]):
        self.building  = building
        self.provinces = {str(p["province_id"]): p for p in provinces}

        is_tier1    = bool(building.get("allowed_resources"))
        allowed_res = set(building.get("allowed_resources", []))

        options = []
        for p in provinces:
            pid  = str(p["province_id"])
            res  = (p.get("resource_type") or "none").lower()
            compat = (not is_tier1) or (res in allowed_res)
            if not compat:
                continue   # don't show incompatible provinces for Tier 1
            emoji = embeds.RESOURCE_EMOJI.get(res, "🏔️")
            options.append(discord.SelectOption(
                label=p["province_name"],
                value=pid,
                description=f"Resource: {res}",
                emoji=emoji,
            ))

        if not options:
            options = [discord.SelectOption(label="No compatible provinces", value="none")]

        super().__init__(
            placeholder="Select province(s) to build in…",
            min_values=1,
            max_values=min(len(options), 10),
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        selected_ids = self.values
        if "none" in selected_ids:
            await interaction.response.send_message(
                embed=embeds.construct_error_embed("No compatible provinces available."),
                ephemeral=True,
            )
            return

        building    = self.building
        selected_ps = [self.provinces[pid] for pid in selected_ids if pid in self.provinces]
        pnames      = [p["province_name"] for p in selected_ps]
        n           = len(selected_ps)
        total_gold  = building["cost"] * n
        cons_res    = building.get("construction_cost_resources", {})

        confirm_embed = embeds.construct_confirm_embed(
            building_name  = building["name"],
            provinces      = pnames,
            total_gold     = total_gold,
            cons_resources = cons_res,
            months         = building["months"],
        )

        confirm_view = ConstructConfirmView(
            building    = building,
            provinces   = selected_ps,
            guild_id    = str(interaction.guild_id),
            user_id     = str(interaction.user.id),
        )
        await interaction.response.edit_message(embed=confirm_embed, view=confirm_view)


class ConstructSelectView(discord.ui.View):
    def __init__(self, building: dict, provinces: list[dict]):
        super().__init__(timeout=120)
        self.add_item(ProvinceSelect(building, provinces))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Construct: confirmation buttons ───────────────────────────────────────────

class ConstructConfirmView(discord.ui.View):
    def __init__(self, building: dict, provinces: list[dict],
                 guild_id: str, user_id: str):
        super().__init__(timeout=120)
        self.building  = building
        self.provinces = provinces
        self.guild_id  = guild_id
        self.user_id   = user_id

    @discord.ui.button(label="✅  Construct", style=discord.ButtonStyle.success)
    async def construct_btn(self, interaction: discord.Interaction,
                             button: discord.ui.Button):
        await interaction.response.defer()

        guild_id   = self.guild_id
        country_id = game_state.get_user_country(guild_id, self.user_id)
        if country_id is None:
            await interaction.edit_original_response(
                embed=embeds.no_country_embed(), view=None
            )
            return

        building     = self.building
        game_day     = game_state.get_game_day(guild_id)
        total_gold   = building["cost"] * len(self.provinces)
        cons_res_per = building.get("construction_cost_resources", {})

        # Check treasury once
        country = get_country_by_id(country_id)
        if country is None:
            await interaction.edit_original_response(
                embed=embeds.construct_error_embed("Country data not found."), view=None
            )
            return

        if country["treasury"] < total_gold:
            await interaction.edit_original_response(
                embed=embeds.construct_error_embed(
                    f"Insufficient gold: need **{total_gold:,.0f}**, "
                    f"have **{country['treasury']:,.1f}**."
                ),
                view=None,
            )
            return

        # Check storage for construction resources (multiplied by number of provinces)
        if cons_res_per:
            total_cons = {k: v * len(self.provinces) for k, v in cons_res_per.items()}
            storage = get_storage(country_id)
            for res, needed in total_cons.items():
                if storage.get(res, 0) < needed:
                    await interaction.edit_original_response(
                        embed=embeds.construct_error_embed(
                            f"Insufficient **{res}**: need {needed}, "
                            f"have {storage.get(res, 0)}."
                        ),
                        view=None,
                    )
                    return

        # Apply construction per province
        pnames   = []
        comp_day = game_day
        errors   = []
        for p in self.provinces:
            result = construct_building(
                country_id        = country_id,
                building_type_str = building["name"],
                province_id       = str(p["province_id"]),
                province_resource = (p.get("resource_type") or "none").lower(),
                current_game_day  = game_day,
            )
            if result.get("allowed"):
                pnames.append(p["province_name"])
                comp_day = result.get("completion_day", game_day)
            else:
                errors.append(f"{p['province_name']}: {result.get('reason','unknown error')}")

        if not pnames:
            await interaction.edit_original_response(
                embed=embeds.construct_error_embed("\n".join(errors) or "Construction failed."),
                view=None,
            )
            return

        # Calculate actual gold spent (backend deducted per province)
        actual_gold = building["cost"] * len(pnames)
        days_left   = comp_day - game_day

        success_embed = embeds.construct_success_embed(
            building_name  = building["name"],
            provinces      = pnames,
            gold_spent     = actual_gold,
            completion_days = days_left,
        )
        if errors:
            success_embed.add_field(
                name="⚠️  Some provinces failed",
                value="\n".join(errors),
                inline=False,
            )

        await interaction.edit_original_response(embed=success_embed, view=None)

    @discord.ui.button(label="❌  Cancel", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=embeds.select_error_embed("Construction cancelled."),
            view=None,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Cog ───────────────────────────────────────────────────────────────────────

class EconomyCog(commands.Cog, name="Economy"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── rp invest <type> ─────────────────────────────────────────────────────

    @commands.command(name="invest")
    async def invest_cmd(self, ctx: commands.Context, *, invest_type: str = ""):
        """Invest gold to boost population growth rate."""
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        VALID_TYPES = {"pg", "population", "population_growth", "population_growth_rate"}

        if not invest_type or invest_type.strip().lower().replace(" ", "_") not in VALID_TYPES:
            await ctx.send(embed=embeds.select_error_embed(
                "Usage: **`rp invest pg`** (or `rp invest population` / `rp invest population_growth`)\n\n"
                "Currently available investment: **Population Growth Rate**"
            ))
            return

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return

        country = get_country_by_id(country_id)
        if country is None:
            await ctx.send(embed=embeds.select_error_embed("Country data not found."))
            return

        inv         = game_state.get_investment(guild_id, country_id)
        growth_bonus = inv["growth_bonus"]
        next_cost    = inv["next_invest_cost"]
        current_rate = game_state.BASE_GROWTH_RATE + growth_bonus
        cap          = game_state.MAX_GROWTH_RATE
        treasury     = country["treasury"]

        if current_rate >= cap:
            await ctx.send(embed=embeds.invest_embed(
                country["country_name"], current_rate, next_cost, treasury, cap
            ))
            return

        if treasury < next_cost:
            await ctx.send(embed=embeds.select_error_embed(
                f"Not enough gold!\n"
                f"**Investment cost:** {next_cost:,.0f} gold\n"
                f"**Your treasury:** {treasury:,.1f} gold"
            ))
            return

        # Apply investment
        try:
            deduct_treasury(country_id, next_cost)
        except ValueError as e:
            await ctx.send(embed=embeds.select_error_embed(str(e)))
            return

        new_bonus    = growth_bonus + game_state.GROWTH_STEP
        new_rate     = game_state.BASE_GROWTH_RATE + new_bonus
        new_rate     = min(new_rate, cap)
        new_cost     = next_cost * 2.0

        # Save updated investment state
        game_state.save_investment(guild_id, country_id, new_bonus, new_cost)

        # Persist new growth rate into ww1_scenario.db
        update_population_growth_rate(country_id, new_rate)

        await ctx.send(embed=embeds.invest_success_embed(
            country_name = country["country_name"],
            gold_spent   = next_cost,
            new_rate     = new_rate,
            next_cost    = new_cost,
        ))

    # ── rp storage ───────────────────────────────────────────────────────────

    @commands.command(name="storage")
    async def storage_cmd(self, ctx: commands.Context):
        """View your country's resource storage."""
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
        storage = get_storage(country_id)
        date    = game_state.get_game_date(guild_id)

        await ctx.send(embed=embeds.storage_embed(
            country_name = country["country_name"],
            owner        = ctx.author.display_name,
            date         = date,
            storage      = storage,
        ))

    # ── rp buildings ─────────────────────────────────────────────────────────

    @commands.command(name="buildings")
    async def buildings_cmd(self, ctx: commands.Context):
        """Browse the full building catalogue."""
        guild_id = str(ctx.guild.id)
        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        view = BuildingsView()
        await ctx.send(embed=view._current_embed(), view=view)

    # ── rp construct <building> ───────────────────────────────────────────────

    @commands.command(name="construct")
    async def construct_cmd(self, ctx: commands.Context, *, building_name: str = ""):
        """Start constructing a building in your provinces."""
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        if not building_name:
            await ctx.send(embed=embeds.select_error_embed(
                "Please provide a building name.\nExample: **`rp construct mine`**\n"
                "Use **`rp buildings`** to see all available buildings."
            ))
            return

        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return

        building = _find_building(building_name)
        if building is None:
            await ctx.send(embed=embeds.select_error_embed(
                f"Building **\"{building_name}\"** not found.\n"
                "Use **`rp buildings`** to see all available buildings."
            ))
            return

        provinces = get_provinces(country_id)
        if not provinces:
            await ctx.send(embed=embeds.select_error_embed("Your country has no provinces!"))
            return

        # Filter compatible provinces for Tier 1 buildings
        allowed_res = set(building.get("allowed_resources", []))
        if allowed_res:
            compatible = [p for p in provinces
                          if (p.get("resource_type") or "").lower() in allowed_res]
        else:
            compatible = provinces

        country = get_country_by_id(country_id)
        if country is None:
            await ctx.send(embed=embeds.select_error_embed("Country data not found."))
            return

        info_embed = embeds.construct_info_embed(building, country["country_name"], compatible)
        view       = ConstructSelectView(building, compatible if compatible else provinces)
        await ctx.send(embed=info_embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCog(bot))
