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
