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
