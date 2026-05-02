"""
Economy cog — rp invest / rp storage / rp buildings / rp construct
             / rp technology / rp research / rp switch_research / rp reforms / rp adopt
"""
from __future__ import annotations

import discord
from discord.ext import commands

from discord_bot import embeds, game_state
from discord_bot.ww1_data import (
    find_country, get_country_by_id, get_provinces,
    get_storage, get_display_storage,
    deduct_treasury, deduct_storage_resources,
    update_population_growth_rate, construct_building,
    get_tech_status_for_country, get_reform_status_for_country,
    get_mil_tech_status_for_country, get_active_research_info,
    get_research_speed, cancel_active_research,
    start_tech_research, start_reform_research, start_mil_tech_research,
    adopt_reform, find_research_target, remove_reform,
    get_market_snapshot, buy_from_market,
    get_current_tax_level, set_country_tax_level,
)

# Items shown per tech-tree page
TECH_PAGE_SIZE = 5


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
            pid   = str(p["province_id"])
            res   = (p.get("resource_type") or "none").lower()
            compat = (not is_tier1) or (res in allowed_res)
            if not compat:
                continue
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
            building  = building,
            provinces = selected_ps,
            guild_id  = str(interaction.guild_id),
            user_id   = str(interaction.user.id),
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
            await interaction.edit_original_response(embed=embeds.no_country_embed(), view=None)
            return

        building     = self.building
        game_day     = game_state.get_game_day(guild_id)
        total_gold   = building["cost"] * len(self.provinces)
        cons_res_per = building.get("construction_cost_resources", {})

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

        if cons_res_per:
            total_cons = {k: v * len(self.provinces) for k, v in cons_res_per.items()}
            storage = get_storage(country_id)
            for res, needed in total_cons.items():
                if storage.get(res, 0) < needed:
                    await interaction.edit_original_response(
                        embed=embeds.construct_error_embed(
                            f"Insufficient **{res}**: need {needed}, have {storage.get(res, 0)}."
                        ),
                        view=None,
                    )
                    return

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

        actual_gold = building["cost"] * len(pnames)
        days_left   = comp_day - game_day
        success_embed = embeds.construct_success_embed(
            building_name   = building["name"],
            provinces       = pnames,
            gold_spent      = actual_gold,
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


# ── Technology tree view ──────────────────────────────────────────────────────

TECH_CATEGORIES: dict[str, list[str]] = {
    "Economic":       ["industrialization", "chemical_processing"],
    "Infrastructure": ["early_modern_infrastructure", "library", "school", "university"],
}


def _build_tech_items(category: str, country_id: str) -> list[dict]:
    """Build the list of item dicts for the given category."""
    from ww1_economy.tech_data          import TECH_TREE, REFORM_TREE
    from ww1_economy.military_tech_data import MILITARY_TECH_TREE

    items = []
    if category in TECH_CATEGORIES:
        for tid in TECH_CATEGORIES[category]:
            if tid in TECH_TREE:
                tdef = TECH_TREE[tid]
                unlocks = ", ".join(tdef.unlocks_buildings) if tdef.unlocks_buildings else ""
                items.append({
                    "tech_id":         tid,
                    "name":            tdef.name,
                    "duration_months": tdef.duration_months,
                    "prerequisites":   tdef.prerequisites,
                    "description":     f"Unlocks: {unlocks}" if unlocks else "",
                })
    elif category == "Reforms":
        for rid, rdef in REFORM_TREE.items():
            effects = []
            if rdef.opinion_bonus:
                effects.append(f"Opinion +{rdef.opinion_bonus}")
            if rdef.economy_efficiency_pct:
                effects.append(f"Efficiency {rdef.economy_efficiency_pct:+.0f}%")
            if rdef.recruitment_cost_pct:
                effects.append(f"Recruit cost {rdef.recruitment_cost_pct:+.0f}%")
            if rdef.blocks_war_declaration:
                effects.append("No war declaration")
            items.append({
                "tech_id":         rid,
                "name":            rdef.name,
                "duration_months": rdef.duration_months,
                "prerequisites":   rdef.prerequisites,
                "description":     ", ".join(effects) if effects else "Governance",
            })
    elif category == "Military":
        for tid, tdef in MILITARY_TECH_TREE.items():
            units = ", ".join(tdef.unlocks_units) if tdef.unlocks_units else ""
            items.append({
                "tech_id":         tid,
                "name":            tdef.name,
                "duration_months": tdef.duration_months,
                "prerequisites":   tdef.prerequisites,
                "description":     f"Units: {units}" if units else "",
            })
    return items


def _get_tech_status_combined(country_id: str) -> dict[str, dict]:
    """Returns merged status from all three tech tables, keyed by tech_id."""
    status = {}
    status.update(get_tech_status_for_country(country_id))
    status.update({k: v for k, v in get_reform_status_for_country(country_id).items()})
    status.update(get_mil_tech_status_for_country(country_id))
    return status


class TechCategorySelect(discord.ui.Select):
    def __init__(self, country_id: str, guild_id: str, country_name: str):
        self.country_id   = country_id
        self.guild_id     = guild_id
        self.country_name = country_name
        options = [
            discord.SelectOption(label="📊 Economic",       value="Economic",       description="Industrialization, Chemical Processing"),
            discord.SelectOption(label="🏗️ Infrastructure", value="Infrastructure", description="Infrastructure, Library, School, University"),
            discord.SelectOption(label="📜 Reforms",        value="Reforms",        description="Social & economic reforms"),
            discord.SelectOption(label="⚔️ Military",       value="Military",       description="Military technology tree"),
        ]
        super().__init__(placeholder="Select a technology category…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        category  = self.values[0]
        items     = _build_tech_items(category, self.country_id)
        page_view = TechTreeView(
            country_id   = self.country_id,
            guild_id     = self.guild_id,
            country_name = self.country_name,
            category     = category,
            items        = items,
        )
        await interaction.edit_original_response(
            embed=page_view._current_embed(),
            view=page_view,
        )


class TechMainView(discord.ui.View):
    def __init__(self, country_id: str, guild_id: str, country_name: str):
        super().__init__(timeout=180)
        self.add_item(TechCategorySelect(country_id, guild_id, country_name))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class TechTreeView(discord.ui.View):
    def __init__(self, country_id: str, guild_id: str, country_name: str,
                 category: str, items: list[dict]):
        super().__init__(timeout=180)
        self.country_id   = country_id
        self.guild_id     = guild_id
        self.country_name = country_name
        self.category     = category
        self.items        = items
        self.page         = 0
        self.total_pages  = max(1, -(-len(items) // TECH_PAGE_SIZE))
        self._add_components()

    def _add_components(self):
        self.clear_items()
        # Category selector (re-added so user can switch)
        cat_select = TechCategorySelect(self.country_id, self.guild_id, self.country_name)
        self.add_item(cat_select)
        # Pagination
        prev = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary,
                                  disabled=self.page <= 0, custom_id="prev")
        next_ = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary,
                                   disabled=self.page >= self.total_pages - 1, custom_id="next_")
        prev.callback  = self._prev_callback
        next_.callback = self._next_callback
        self.add_item(prev)
        self.add_item(next_)

    async def _prev_callback(self, interaction: discord.Interaction):
        self.page -= 1
        self._add_components()
        await interaction.response.edit_message(embed=self._current_embed(), view=self)

    async def _next_callback(self, interaction: discord.Interaction):
        self.page += 1
        self._add_components()
        await interaction.response.edit_message(embed=self._current_embed(), view=self)

    def _current_embed(self) -> discord.Embed:
        start    = self.page * TECH_PAGE_SIZE
        page_items = self.items[start: start + TECH_PAGE_SIZE]

        tech_status = _get_tech_status_combined(self.country_id)

        # Build paused_ids from bot_state.db (for this country)
        paused_ids: set[str] = set()
        try:
            import sqlite3
            con = sqlite3.connect("bot_state.db")
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT research_id FROM paused_research "
                "WHERE guild_id=? AND country_id=?",
                (self.guild_id, self.country_id),
            ).fetchall()
            con.close()
            paused_ids = {r["research_id"] for r in rows}
        except Exception:
            pass

        return embeds.tech_tree_embed(
            country_name = self.country_name,
            category     = self.category,
            items        = page_items,
            page         = self.page + 1,
            total_pages  = self.total_pages,
            tech_status  = tech_status,
            paused_ids   = paused_ids,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Taxation — dropdown & view ───────────────────────────────────────────────

_TAX_EMOJI: dict[str, str] = {
    "tax_exemption":      "⚪",
    "light_contribution": "🟢",
    "standard":           "🔵",
    "elevated":           "🟠",
    "war_levy":           "🔴",
}


class TaxSelect(discord.ui.Select):
    def __init__(
        self,
        current_tax_key: str,
        country_id:      str,
        guild_id:        str,
        current_month:   int,
    ):
        self.country_id    = country_id
        self.guild_id      = guild_id
        self.current_month = current_month

        from ww1_economy.efficiency_system import WW1_TAX_TIERS, WW1_TAX_MAP
        self._tax_map = WW1_TAX_MAP

        options = []
        for tier in WW1_TAX_TIERS:
            key    = tier["key"]
            emoji  = _TAX_EMOJI.get(key, "⚫")
            op     = tier["opinion"]
            op_str = f"+{op}" if op > 0 else str(op)
            options.append(discord.SelectOption(
                label       = tier["label"],
                value       = key,
                description = f"Opinion {op_str}",
                emoji       = emoji,
                default     = (key == current_tax_key),
            ))

        super().__init__(
            placeholder = "Select tax policy…",
            min_values  = 1,
            max_values  = 1,
            options     = options,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        user_id    = str(interaction.user.id)
        guild_id   = self.guild_id
        country_id = self.country_id

        actual = game_state.get_user_country(guild_id, user_id)
        if actual != country_id:
            await interaction.followup.send(
                embed=embeds.select_error_embed("You don't control this country."),
                ephemeral=True,
            )
            return

        tax_key  = self.values[0]
        new_tier = self._tax_map[tax_key]

        result = set_country_tax_level(country_id, tax_key, current_month=self.current_month)
        if not result["ok"]:
            await interaction.followup.send(
                embed=embeds.select_error_embed(result["reason"]),
                ephemeral=True,
            )
            return

        new_view = TaxationView(tax_key, country_id, guild_id, self.current_month)
        await interaction.edit_original_response(
            embed=embeds.taxation_changed_embed(
                tier       = new_tier,
                opinion    = result["opinion"],
                efficiency = result["efficiency"],
            ),
            view=new_view,
        )


class TaxationView(discord.ui.View):
    def __init__(
        self,
        current_tax_key: str,
        country_id:      str,
        guild_id:        str,
        current_month:   int,
    ):
        super().__init__(timeout=120)
        self.add_item(TaxSelect(current_tax_key, country_id, guild_id, current_month))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Global Market — resource select ──────────────────────────────────────────

class ResourceSelect(discord.ui.Select):
    def __init__(self, market_rows: list[dict], country_id: str, guild_id: str):
        self.country_id  = country_id
        self.guild_id    = guild_id
        self.row_map     = {r["resource_name"]: r for r in market_rows}

        from ww1_economy.resources import MARKET_BASE_PRICES, MARKET_RESOURCE_SET
        ORDERED = [
            "iron", "coal", "copper", "stone", "wood", "rubber",
            "grain", "meat", "cotton", "oil",
            "chemicals", "gunpowder", "ammunition", "medicines",
        ]
        options = []
        for res in ORDERED:
            row      = self.row_map.get(res)
            price    = float(row["current_price"]) if row else MARKET_BASE_PRICES.get(res, 0.0)
            shortage = bool(int(row.get("shortage") or 0)) if row else False
            emoji    = embeds.RESOURCE_EMOJI.get(res, "📦")
            label    = res.title()
            desc     = f"{price:.1f} gold/unit"
            if shortage:
                desc += "  [SHORTAGE]"
            options.append(discord.SelectOption(
                label       = label,
                value       = res,
                description = desc,
                emoji       = emoji,
            ))

        super().__init__(
            placeholder = "☐  Select a resource to buy…",
            min_values  = 1,
            max_values  = 1,
            options     = options,
        )

    async def callback(self, interaction: discord.Interaction):
        resource = self.values[0]
        row      = self.row_map.get(resource, {})
        shortage = bool(int(row.get("shortage") or 0)) if row else False

        if shortage:
            await interaction.response.send_message(
                embed=embeds.market_buy_error_embed(
                    f"**{resource.title()}** is currently in shortage — market closed for buyers."
                ),
                ephemeral=True,
            )
            return

        modal = QuantityModal(
            resource   = resource,
            market_row = row,
            country_id = self.country_id,
            guild_id   = self.guild_id,
        )
        await interaction.response.send_modal(modal)


class GlobalMarketView(discord.ui.View):
    def __init__(self, market_rows: list[dict], country_id: str, guild_id: str):
        super().__init__(timeout=120)
        self.add_item(ResourceSelect(market_rows, country_id, guild_id))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Global Market — quantity modal ────────────────────────────────────────────

class QuantityModal(discord.ui.Modal, title="Enter Quantity"):
    quantity: discord.ui.TextInput = discord.ui.TextInput(
        label       = "How many units do you want to buy?",
        placeholder = "e.g. 50",
        min_length  = 1,
        max_length  = 7,
        required    = True,
    )

    def __init__(self, resource: str, market_row: dict,
                 country_id: str, guild_id: str):
        super().__init__()
        self.resource   = resource
        self.market_row = market_row
        self.country_id = country_id
        self.guild_id   = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.quantity.value.strip().replace(",", "")
        try:
            qty = int(raw)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.market_buy_error_embed("Please enter a valid whole number."),
                ephemeral=True,
            )
            return

        if qty <= 0:
            await interaction.response.send_message(
                embed=embeds.market_buy_error_embed("Quantity must be at least 1."),
                ephemeral=True,
            )
            return

        from ww1_economy.resources import MARKET_BASE_PRICES
        unit_price = float(self.market_row.get("current_price") or MARKET_BASE_PRICES.get(self.resource, 0.0))
        total_cost = unit_price * qty
        country    = get_country_by_id(self.country_id)
        treasury   = country["treasury"] if country else 0.0

        confirm_view = MarketConfirmView(
            resource   = self.resource,
            quantity   = qty,
            unit_price = unit_price,
            total_cost = total_cost,
            country_id = self.country_id,
            guild_id   = self.guild_id,
        )
        await interaction.response.send_message(
            embed=embeds.market_buy_confirm_embed(
                resource   = self.resource,
                quantity   = qty,
                unit_price = unit_price,
                total_cost = total_cost,
                treasury   = treasury,
            ),
            view=confirm_view,
        )


# ── Global Market — confirm / cancel ─────────────────────────────────────────

class MarketConfirmView(discord.ui.View):
    def __init__(self, resource: str, quantity: int,
                 unit_price: float, total_cost: float,
                 country_id: str, guild_id: str):
        super().__init__(timeout=90)
        self.resource   = resource
        self.quantity   = quantity
        self.unit_price = unit_price
        self.total_cost = total_cost
        self.country_id = country_id
        self.guild_id   = guild_id

    @discord.ui.button(label="✅  Buy", style=discord.ButtonStyle.success)
    async def buy_btn(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        await interaction.response.defer()

        result = buy_from_market(self.country_id, self.resource, self.quantity)

        if not result["success"]:
            await interaction.edit_original_response(
                embed=embeds.market_buy_error_embed(result["reason"]),
                view=None,
            )
            return

        await interaction.edit_original_response(
            embed=embeds.market_buy_success_embed(
                resource     = self.resource,
                quantity     = result["quantity"],
                total_cost   = result["total_cost"],
                new_treasury = result["new_treasury"],
                new_storage  = result["new_storage"],
            ),
            view=None,
        )

    @discord.ui.button(label="❌  Cancel", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=embeds.select_error_embed("Purchase cancelled."),
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
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        VALID_TYPES = {"pg", "population", "population_growth", "population_growth_rate"}
        if not invest_type or invest_type.strip().lower().replace(" ", "_") not in VALID_TYPES:
            await ctx.send(embed=embeds.select_error_embed(
                "Usage: **`rp invest pg`**\n\nCurrently available investment: **Population Growth Rate**"
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

        inv          = game_state.get_investment(guild_id, country_id)
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

        try:
            deduct_treasury(country_id, next_cost)
        except ValueError as e:
            await ctx.send(embed=embeds.select_error_embed(str(e)))
            return

        new_bonus = growth_bonus + game_state.GROWTH_STEP
        new_rate  = min(game_state.BASE_GROWTH_RATE + new_bonus, cap)
        new_cost  = next_cost * 2.0

        game_state.save_investment(guild_id, country_id, new_bonus, new_cost)
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
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return

        country      = get_country_by_id(country_id)
        display_stor = get_display_storage(country_id)
        date         = game_state.get_game_date(guild_id)

        await ctx.send(embed=embeds.storage_embed(
            country_name = country["country_name"],
            owner        = ctx.author.display_name,
            date         = date,
            storage      = display_stor,
        ))

    # ── rp buildings ─────────────────────────────────────────────────────────

    @commands.command(name="buildings")
    async def buildings_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return
        view = BuildingsView()
        await ctx.send(embed=view._current_embed(), view=view)

    # ── rp construct <building> ───────────────────────────────────────────────

    @commands.command(name="construct")
    async def construct_cmd(self, ctx: commands.Context, *, building_name: str = ""):
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

        # ── Tech gate check ──────────────────────────────────────────────────
        from ww1_economy.tech_data import BUILDING_TECH_REQUIREMENTS, TECH_TREE
        tech_req = BUILDING_TECH_REQUIREMENTS.get(building["name"])
        if tech_req:
            tech_status = get_tech_status_for_country(country_id)
            if not tech_status.get(tech_req, {}).get("is_unlocked", False):
                req_name = TECH_TREE[tech_req].name if tech_req in TECH_TREE else tech_req
                await ctx.send(embed=embeds.construct_tech_locked_embed(
                    building["name"], req_name
                ))
                return

        provinces = get_provinces(country_id)
        if not provinces:
            await ctx.send(embed=embeds.select_error_embed("Your country has no provinces!"))
            return

        allowed_res = set(building.get("allowed_resources", []))
        if allowed_res:
            compatible = [p for p in provinces
                          if (p.get("resource_type") or "").lower() in allowed_res]
        else:
            compatible = provinces

        country    = get_country_by_id(country_id)
        if country is None:
            await ctx.send(embed=embeds.select_error_embed("Country data not found."))
            return

        info_embed = embeds.construct_info_embed(building, country["country_name"], compatible)
        view       = ConstructSelectView(building, compatible if compatible else provinces)
        await ctx.send(embed=info_embed, view=view)

    # ── rp technology ─────────────────────────────────────────────────────────

    @commands.command(name="technology", aliases=["tech"])
    async def technology_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return

        country  = get_country_by_id(country_id)
        game_day = game_state.get_game_day(guild_id)
        date     = game_state.get_game_date(guild_id)
        speed    = get_research_speed(country_id)
        active   = get_active_research_info(country_id, game_day)

        view = TechMainView(country_id, guild_id, country["country_name"])
        await ctx.send(
            embed=embeds.technology_main_embed(
                country_name    = country["country_name"],
                owner           = ctx.author.display_name,
                date            = date,
                research_speed  = speed,
                active_research = active,
            ),
            view=view,
        )

    # ── rp research <name> ────────────────────────────────────────────────────

    @commands.command(name="research")
    async def research_cmd(self, ctx: commands.Context, *, tech_name: str = ""):
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        if not tech_name:
            await ctx.send(embed=embeds.research_error_embed(
                "Please specify what to research.\nExample: **`rp research industrialization`**\n"
                "Use **`rp technology`** to see the tech tree."
            ))
            return

        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return

        # Find the target
        target = find_research_target(tech_name)
        if target is None:
            await ctx.send(embed=embeds.research_error_embed(
                f"No technology or reform found matching **\"{tech_name}\"**.\n"
                "Use **`rp technology`** to see all available options."
            ))
            return

        # Check if something is already being researched
        game_day = game_state.get_game_day(guild_id)
        active   = get_active_research_info(country_id, game_day)
        if active:
            from ww1_economy.tech_data          import TECH_TREE, REFORM_TREE
            from ww1_economy.military_tech_data import MILITARY_TECH_TREE
            all_trees = {**TECH_TREE, **REFORM_TREE, **MILITARY_TECH_TREE}
            active_def = all_trees.get(active["tech_id"])
            active_name = active_def.name if active_def else active["tech_id"].replace("_", " ").title()
            await ctx.send(embed=embeds.research_error_embed(
                f"Already researching **{active_name}**.\n"
                "Use **`rp switch_research {tech_name}`** to switch, or wait until it completes."
            ))
            return

        # Check for paused research on this tech
        paused = game_state.get_paused_research(guild_id, country_id, target["tech_id"])
        remaining_days = paused["remaining_days"] if paused else None
        is_resume      = paused is not None and remaining_days and remaining_days > 0

        speed = get_research_speed(country_id)
        ttype = target["type"]

        if ttype == "tech":
            result = start_tech_research(country_id, target["tech_id"], game_day, remaining_days)
        elif ttype == "reform":
            result = start_reform_research(country_id, target["tech_id"], game_day, remaining_days)
        else:
            result = start_mil_tech_research(country_id, target["tech_id"], game_day, remaining_days)

        if not result["ok"]:
            await ctx.send(embed=embeds.research_error_embed(result["reason"]))
            return

        # Clear paused entry if we resumed
        if is_resume:
            game_state.clear_paused_research(guild_id, country_id, target["tech_id"])

        await ctx.send(embed=embeds.research_started_embed(
            tech_name     = target["name"],
            duration_days = result["duration"],
            speed_pct     = speed,
            is_resume     = bool(is_resume),
        ))

    # ── rp switch_research / rp sr ────────────────────────────────────────────

    @commands.command(name="switch_research", aliases=["sr"])
    async def switch_research_cmd(self, ctx: commands.Context, *, tech_name: str = ""):
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        if not tech_name:
            await ctx.send(embed=embeds.research_error_embed(
                "Please specify what to research next.\n"
                "Example: **`rp switch_research chemical processing`**"
            ))
            return

        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return

        game_day = game_state.get_game_day(guild_id)

        # Must have active research to switch from
        active = get_active_research_info(country_id, game_day)
        if not active:
            await ctx.send(embed=embeds.research_error_embed(
                "You are not currently researching anything.\n"
                "Use **`rp research <name>`** to start research."
            ))
            return

        # Find new target
        target = find_research_target(tech_name)
        if target is None:
            await ctx.send(embed=embeds.research_error_embed(
                f"No technology or reform found matching **\"{tech_name}\"**.\n"
                "Use **`rp technology`** to see all available options."
            ))
            return

        if target["tech_id"] == active["tech_id"]:
            await ctx.send(embed=embeds.research_error_embed(
                "You are already researching that!"
            ))
            return

        # Get name of currently active research
        from ww1_economy.tech_data          import TECH_TREE, REFORM_TREE
        from ww1_economy.military_tech_data import MILITARY_TECH_TREE
        all_trees   = {**TECH_TREE, **REFORM_TREE, **MILITARY_TECH_TREE}
        active_def  = all_trees.get(active["tech_id"])
        old_name    = active_def.name if active_def else active["tech_id"].replace("_", " ").title()
        old_remain  = active["remaining_days"]

        # Cancel current research and save progress
        cancel_active_research(country_id, game_day)
        game_state.save_paused_research(
            guild_id       = guild_id,
            country_id     = country_id,
            research_id    = active["tech_id"],
            research_type  = active["type"],
            remaining_days = old_remain,
        )

        # Check if new target has paused progress
        paused     = game_state.get_paused_research(guild_id, country_id, target["tech_id"])
        rem_days   = paused["remaining_days"] if paused else None

        speed = get_research_speed(country_id)
        ttype = target["type"]

        if ttype == "tech":
            result = start_tech_research(country_id, target["tech_id"], game_day, rem_days)
        elif ttype == "reform":
            result = start_reform_research(country_id, target["tech_id"], game_day, rem_days)
        else:
            result = start_mil_tech_research(country_id, target["tech_id"], game_day, rem_days)

        if not result["ok"]:
            # Restore old research
            if active["type"] == "tech":
                start_tech_research(country_id, active["tech_id"], game_day, old_remain)
            elif active["type"] == "reform":
                start_reform_research(country_id, active["tech_id"], game_day, old_remain)
            else:
                start_mil_tech_research(country_id, active["tech_id"], game_day, old_remain)
            game_state.clear_paused_research(guild_id, country_id, active["tech_id"])
            await ctx.send(embed=embeds.research_error_embed(result["reason"]))
            return

        # Clear paused entry for new target if resumed
        if rem_days:
            game_state.clear_paused_research(guild_id, country_id, target["tech_id"])

        await ctx.send(embed=embeds.switch_research_embed(
            old_name           = old_name,
            old_remaining_days = old_remain,
            new_name           = target["name"],
            new_duration_days  = result["duration"],
            speed_pct          = speed,
        ))

    # ── rp reforms ───────────────────────────────────────────────────────────

    @commands.command(name="reforms")
    async def reforms_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return

        country  = get_country_by_id(country_id)
        date     = game_state.get_game_date(guild_id)
        rstatus  = get_reform_status_for_country(country_id)

        from ww1_economy.tech_data import REFORM_TREE
        reforms_data = []
        adopted_ids  = set()
        for rid, rdef in REFORM_TREE.items():
            row = rstatus.get(rid, {})
            if row.get("is_adopted"):
                adopted_ids.add(rid)
            item = {
                "reform_id":                  rid,
                "name":                       rdef.name,
                "duration_months":            rdef.duration_months,
                "prerequisites":              rdef.prerequisites,
                "opinion_bonus":              rdef.opinion_bonus,
                "economy_efficiency_pct":     rdef.economy_efficiency_pct,
                "recruitment_cost_pct":       rdef.recruitment_cost_pct,
                "population_growth_pct":      rdef.population_growth_pct,
                "non_core_conversion_cost_pct": rdef.non_core_conversion_cost_pct,
                "blocks_war_declaration":     rdef.blocks_war_declaration,
                "_status":                    row,
            }
            reforms_data.append(item)

        await ctx.send(embed=embeds.reforms_embed(
            country_name  = country["country_name"],
            owner         = ctx.author.display_name,
            date          = date,
            reforms       = reforms_data,
            adopted_ids   = adopted_ids,
            adopted_count = len(adopted_ids),
        ))

    # ── rp remove reforms / rp rr <name> ─────────────────────────────────────

    @commands.command(name="remove_reforms", aliases=["rr"])
    async def remove_reforms_cmd(self, ctx: commands.Context, *, reform_name: str = ""):
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        if not reform_name:
            await ctx.send(embed=embeds.remove_reform_error_embed(
                "Please specify a reform to remove.\nExample: **`rp rr banking system`**\n"
                "Use **`rp reforms`** to see your currently adopted reforms."
            ))
            return

        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return

        # Fuzzy-find the reform
        from ww1_economy.tech_data import REFORM_TREE
        q = reform_name.strip().lower().replace("-", " ").replace("_", " ")
        matched_rid = None
        for rid, rdef in REFORM_TREE.items():
            norm = rdef.name.lower().replace("-", " ")
            if norm == q or rid.replace("_", " ") == q:
                matched_rid = rid
                break
        if matched_rid is None:
            for rid, rdef in REFORM_TREE.items():
                norm = rdef.name.lower().replace("-", " ")
                if q in norm or q in rid.replace("_", " "):
                    matched_rid = rid
                    break

        if matched_rid is None:
            await ctx.send(embed=embeds.remove_reform_error_embed(
                f"No reform found matching **\"{reform_name}\"**.\n"
                "Use **`rp reforms`** to see all reforms."
            ))
            return

        rdef   = REFORM_TREE[matched_rid]
        result = remove_reform(country_id, matched_rid)

        if not result["ok"]:
            await ctx.send(embed=embeds.remove_reform_error_embed(result["reason"]))
            return

        await ctx.send(embed=embeds.remove_reform_success_embed(
            reform_name   = rdef.name,
            adopted_count = result["adopted_count"],
        ))

    # ── rp adopt <reform> ────────────────────────────────────────────────────

    @commands.command(name="adopt")
    async def adopt_cmd(self, ctx: commands.Context, *, reform_name: str = ""):
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        if not reform_name:
            await ctx.send(embed=embeds.adopt_error_embed(
                "Please specify a reform to adopt.\nExample: **`rp adopt banking system`**\n"
                "Use **`rp reforms`** to see all reforms."
            ))
            return

        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return

        # Find the reform
        from ww1_economy.tech_data import REFORM_TREE, REFORM_ADOPTION_COST
        q = reform_name.strip().lower().replace("-", " ").replace("_", " ")
        matched_rid = None
        for rid, rdef in REFORM_TREE.items():
            norm = rdef.name.lower().replace("-", " ")
            if norm == q or rid.replace("_", " ") == q:
                matched_rid = rid
                break
        if matched_rid is None:
            for rid, rdef in REFORM_TREE.items():
                norm = rdef.name.lower().replace("-", " ")
                if q in norm or q in rid.replace("_", " "):
                    matched_rid = rid
                    break

        if matched_rid is None:
            await ctx.send(embed=embeds.adopt_error_embed(
                f"No reform found matching **\"{reform_name}\"**.\n"
                "Use **`rp reforms`** to see all available reforms."
            ))
            return

        rdef   = REFORM_TREE[matched_rid]
        result = adopt_reform(country_id, matched_rid)

        if not result["ok"]:
            await ctx.send(embed=embeds.adopt_error_embed(result["reason"]))
            return

        await ctx.send(embed=embeds.adopt_success_embed(
            reform_name   = rdef.name,
            gold_spent    = REFORM_ADOPTION_COST,
            new_treasury  = result["new_treasury"],
            adopted_count = result["adopted_count"],
        ))


    # ── rp taxation ───────────────────────────────────────────────────────────

    @commands.command(name="taxation", aliases=["tax"])
    async def taxation_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return

        from ww1_economy.efficiency_system import WW1_TAX_TIERS

        country       = get_country_by_id(country_id)
        game_day      = game_state.get_game_day(guild_id)
        current_month = game_day // 30

        current_tax_key = get_current_tax_level(country_id)
        opinion         = int(country.get("population_opinion", 50))
        efficiency      = float(country.get("economy_efficiency", 1.0))

        await ctx.send(
            embed=embeds.taxation_embed(
                country_name       = country["country_name"],
                tiers              = WW1_TAX_TIERS,
                current_tax_key    = current_tax_key,
                current_opinion    = opinion,
                current_efficiency = efficiency,
            ),
            view=TaxationView(current_tax_key, country_id, guild_id, current_month),
        )

    # ── rp gm / rp global_market ──────────────────────────────────────────────

    @commands.command(name="global_market", aliases=["gm"])
    async def global_market_cmd(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        user_id  = str(ctx.author.id)

        if not game_state.is_game_running(guild_id):
            await ctx.send(embed=embeds.no_game_embed())
            return

        country_id = game_state.get_user_country(guild_id, user_id)
        if country_id is None:
            await ctx.send(embed=embeds.no_country_embed())
            return

        market_rows = get_market_snapshot()
        view        = GlobalMarketView(market_rows, country_id, guild_id)
        await ctx.send(
            embed=embeds.global_market_embed(market_rows),
            view=view,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCog(bot))
