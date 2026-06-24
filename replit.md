# [Project name]

_Replace the heading above with the project's name, and this line with one sentence describing what this app does for users._

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)

## Where things live

_Populate as you build — short repo map plus pointers to the source-of-truth file for DB schema, API contracts, theme files, etc._

## Architecture decisions

_Populate as you build — non-obvious choices a reader couldn't infer from the code (3-5 bullets)._

## Product

- **Além do Ticker** (`market-intel/app.py`, Streamlit, Portuguese/BR) — a single-purpose app for the individual investor (investidor pessoa física). Upload company RI/release PDFs and get an in-depth analysis *beyond the stock price*: números realizados, projetos, perspectivas e objetivos da gestão.
- Each analysis produces 6 detailed lenses (fundamentos, alocação de capital, moat, gestão, riscos, guidance) plus a **3-methodology score panel** shown at the top — Score Buffett, Score Barsi, Score Graham — each rated 1–10 with a short justificativa.
- Uses Claude (Haiku) via the Anthropic Replit proxy (`ANTHROPIC_API_KEY`). Analyses are stored in `market-intel/market_intel.db` (SQLite). Runs on port 5000 via a Streamlit workflow (not a registered artifact).
- See `.agents/memory/market-intel-app-structure.md` for non-obvious structure and gotchas.

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

_Populate as you build — sharp edges, "always run X before Y" rules._

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
