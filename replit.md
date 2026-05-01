# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Each package manages its own dependencies.

## Discord Strategy Roleplay Bot — Python Backend

Pure Python backend game logic lives in `game_backend/`. No Discord commands, no UI.

### Modules

| File | Purpose |
|---|---|
| `game_backend/db.py` | SQLite layer; `country_state` table; per-server isolation via `server_id` |
| `game_backend/time_system.py` | In-game calendar, tick advancement, speed settings (1x–5x + pause) |
| `game_backend/religion_system.py` | `Religion` enum (Islam/Christianity/Judaism/Hinduism/Atheism); `ReligionSystem` for DB reads/writes |
| `game_backend/diplomacy_system.py` | Bilateral relation points, tiers, dynamic modifiers (religion -2), gifts, persecution |
| `game_backend/economy_system.py` | Treasury and daily income; update per tick days; transfer/deposit/withdraw |
| `game_backend/population_system.py` | Population with monthly compound growth; integrates with tick days |
| `game_backend/war_system.py` | War declaration, occupation, war score, treaty resolution, ceasefires, vassals, reparations |
| `game_backend/demo.py` | Full smoke-test runner for all six systems |

Run the demo: `python3 -m game_backend.demo`

## WW1 Scenario Static Data

Static base data for the WW1 scenario lives in `ww1_economy/seed_ww1.py`. Two
SQLite tables (defined in `ww1_economy/db.py`) hold it:

| Table | Columns |
|---|---|
| `countries` | `server_id, scenario_id, country_id, country_name, total_population` |
| `provinces` | `server_id, scenario_id, province_id, province_name, owner_country, resource_type, population` |

Both tables are keyed by `(server_id, scenario_id)` for full multi-server / multi-scenario isolation.

- `country_id` is lowercase with underscores (e.g. `russian_empire`).
- `province_name` is the original base name + zero-padded 3-digit `province_id` (e.g. `Rhineland001`, `East prussia010`, `Rome102`).
- `population` and `total_population` are stored in absolute people; source values like `5000k` become `5_000_000`.
- `total_population` per country is computed as the **sum of its province populations** (the stated totals in the source dataset were not always exact and are deliberately ignored).
- Province ID `025` is intentionally absent from the dataset and therefore from the table.

Re-seed (idempotent — clears and re-inserts the `ww1` scenario rows):
`python3 -m ww1_economy.seed_ww1`

Override the DB file with `WW1_DB_PATH=/path/to/file.db`. Default is `ww1_scenario.db` in the repo root.

## WW1 Economy Module (`ww1_economy/`)

End-to-end economy backend for the WW1 scenario. All systems are partitioned by
`(server_id, scenario_id)` and uphold two hard invariants: **treasury never goes
negative** and **storage never goes negative**.

| File | Purpose |
|---|---|
| `db.py` | SQLite layer for `buildings`, `country_storage`, `countries`, `provinces`, `global_market`. Migrations are additive only. |
| `resources.py` | `Tier1Resource`, `Tier2Resource`, `BuildingType`, `BUILDING_CONFIGS`, `BUILDING_CONSUMPTION` (Tier 2 monthly inputs), `MARKET_BASE_PRICES`, `NON_STORABLE_PRODUCTS={horses, textiles}`. |
| `storage_system.py` | Add / deduct / set country resource counts. |
| `treasury_system.py` | Atomic deposit / deduct on country gold. |
| `building_system.py` | `start_construction()` accepts optional `TreasurySystem`, `TechnologySystem`, `StorageSystem`; enforces tech-gate check, deducts construction resources (stone/wood) from country storage before starting, and refunds both gold and resources on insertion failure. |
| `consumption_system.py` | `ResourceConsumptionSystem.run_monthly()` aggregates per-country requirements, deducts all-or-nothing from storage, and flips every completed building between `is_active=1/0`. Infra buildings have no monthly consumption. |
| `production_system.py` | Monthly tick. Inactive buildings produce nothing. Horses (Ranch) and textiles (Textile Mill) are income-only — never stored. Precious Mine deposits **+25 gold/month** for gold provinces and **+30 gold/month** for gems provinces directly to the country treasury. |
| `market_system.py` | Global market with base prices, monthly demand-driven repricing tiers (-5 / 0 / +5 / +10%), bounded 70%–200% of base, shortage detection (rolling demand ≥ 500 over 3 months → 3–6 month shortage that blocks buyers). |
| `efficiency_system.py` | Pure `compute_efficiency(opinion, unrest, in_active_war, war_victory_bonus_active)` returning a value clamped to **[0.5, 1.3]**. `apply_income_formula(base, tax, eff)` enforces taxation **before** efficiency: `final = base * tax * eff`. |
| `tech_data.py` | Pure static data: `TECH_TREE` (6 techs), `REFORM_TREE` (8 reforms), `BUILDING_TECH_REQUIREMENTS`, `TECH_GATED_BUILDINGS`, `RESEARCH_SPEED_BONUSES`, `REFORM_ADOPTION_COST=100`, `MAX_ADOPTED_REFORMS=3`. |
| `technology_system.py` | `TechnologySystem`: `start_research()`, `process_completions()`, `compute_research_speed()` (province infra DR brackets), `is_unlocked()`, `is_building_unlocked()`, shared-queue guard across techs + reforms. |
| `reforms_system.py` | `ReformsSystem`: `start_research_reform()`, `process_completions()`, `adopt_reform()` (100g, max 3), `unadopt_reform()`, `compute_effects()`, `is_war_declaration_blocked()`. |
| `tick_system.py` | Top-level orchestrator. `daily_tick()` completes buildings, completes tech research, completes reform research, then credits income. `monthly_tick()` runs: consumption → production → refresh income → market → efficiency. `DailyTickReport` now includes `tech_completions` and `reform_completions`. |
| `economy_demo.py` | End-to-end demo exercising the original 10 economy spec parts. Run with `python3 -m ww1_economy.economy_demo`. |
| `tech_demo.py` | End-to-end demo for all 7+1 Technology System spec parts (tech tree, research speed, econ tech, infra tech, reforms, queue, tick integration, invariants). Run with `python3 -m ww1_economy.tech_demo`. |

### Infrastructure Buildings (Tier: INFRA)
`Hospital`, `Library`, `School`, `University` — no monthly consumption, can coexist in any combination within the same province, require a tech unlock, and deduct stone/wood from `country_storage` at construction start.

| Building | Tech Required | Gold | Stone | Wood |
|---|---|---|---|---|
| Hospital | `early_modern_infrastructure` | 60 | 25 | 15 |
| Library | `early_modern_infrastructure` | 40 | 5 | 20 |
| School | `library` | 50 | 15 | 15 |
| University | `school` | 80 | 30 | 10 |

### Research Speed Formula
`final = clamp(base + infra_bonus + opinion_mod + unrest_mod + war_mod, min=0.5%)`
- **base**: 1.0%
- **infra_bonus**: sum of per-province infra building bonuses with diminishing returns (provinces 1–3 → 100%, 4–6 → 50%, 7–10 → 25%, 11+ → 10%). Library=+0.5%, School=+1.0%, University=+2.0%, Hospital=+0.5%.
- **opinion>80** → +0.5%;  **opinion<30** → -1.5%
- **unrest>50** → -2.0%
- **in_active_war AND pre-war speed>3%** → -2.0%
- `end_day = current_day + int(duration_days / (speed_pct / 100.0))`

### Canonical daily tick order (enforced in `TickSystem.daily_tick`)
1. Building construction completions.
2. Technology research completions.
3. Reform research completions.
4. Income crediting (`final_income × days_passed` per country).

### Canonical monthly order (enforced in `TickSystem.monthly_tick`)
1. `ResourceConsumptionSystem.run_monthly` — flips activity flags.
2. `ProductionSystem.run_monthly_production` — only ACTIVE buildings produce; gold/gems → treasury.
3. Refresh `countries.daily_base_income` from production output.
4. `GlobalMarketSystem.update_market_monthly` — re-price every resource.
5. `EconomyEfficiencySystem.recompute_all` — bounded multiplier ready for next month's daily ticks.

### Key Design Decisions
- Time overflows correctly (days → months → years) using flat day-index arithmetic
- Diplomacy: base relation stored in memory; `get_effective_relation()` adds modifiers dynamically without touching stored value
- Religion modifier: -2 effective penalty when two countries follow different religions; computed at query time only
- All DB operations isolated by `(server_id, country_id)` — multiple Discord guilds share one SQLite file safely
- Economy: `update_treasury(days)` called each tick; income sources (factories, trade, etc.) added via `add_income()`
- Population: compound growth formula `P × (1 + r)^n` per complete in-game month (30 days)
- War score is signed: positive = attacker winning, negative = defender winning
- Ceasefire = 1080 in-game days (3 years × 12 months × 30 days)

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)

## Key Commands

- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `pnpm --filter @workspace/api-server run dev` — run API server locally

See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details.
