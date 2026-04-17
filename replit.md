# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Each package manages its own dependencies.

## Discord Strategy Roleplay Bot — Python Backend

Pure Python backend game logic lives in `game_backend/`. No Discord commands, no UI.

### Modules

| File | Purpose |
|---|---|
| `game_backend/time_system.py` | In-game calendar, tick advancement, speed settings (1x–5x + pause) |
| `game_backend/diplomacy_system.py` | Bilateral relation points, tiers, gifts, religious persecution |
| `game_backend/war_system.py` | War declaration, occupation, war score, treaty resolution, ceasefires, vassals, reparations |
| `game_backend/demo.py` | Smoke-test runner for all three systems |

Run the demo: `python3 -m game_backend.demo`

### Key Design Decisions
- Time overflows correctly (days → months → years) using flat day-index arithmetic
- Diplomacy uses a canonical-key lookup `(min(a,b), max(a,b))` so each pair has one entry
- War score is signed: positive = attacker winning, negative = defender winning
- All three systems serialise/deserialise cleanly via `.to_dict()` / `.from_dict()`
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
