---
name: Market Intel app structure & workflow gotchas
description: How the market-intel Streamlit app is served and how it stores/separates analyses.
---

# Market Intel (Streamlit) — non-obvious facts

## Which workflow serves the app
- The live app is served by the workflow **`artifacts/mockup-sandbox: Start application`** (`cd market-intel && streamlit run app.py --server.port 5000`). Restart THAT one to reload code.
- The plain **`Start application`** workflow stays **FAILED** (port conflict) — this is expected, not a bug.
- The `mockup-sandbox` artifact dir hosts TWO services: the Streamlit app AND a Vite "Component Preview Server". A screenshot of `/` (or `/__mockup/`) hits the preview server, NOT Streamlit. There is no reliable preview-pane screenshot path for this Streamlit app; validate via syntax check + DB checks + logs instead.

## Mode separation (Fornecedor vs Investidor)
- Analyses are tagged with a `mode` column (`'fornecedor'` | `'investor'`) in `market_intel.db`. `init_db()` adds the column and backfills existing rows via `_detect_mode(results)`.
- `_detect_mode` returns `'investor'` iff results contain investor lenses (key "Fundamentos Financeiros"), else `'fornecedor'`.
- DB query helpers (`list_analyses`, `list_periods`, `analyses_for_period`) take an optional `mode` filter. The sidebar history and Visão Geral both filter by `st.session_state["mode"]` so the two modes never mix.

## Score scales
- Fornecedor score is 0–100 (opportunity score). Investor score is stored as Buffett nota×10 (0–100) but DISPLAYED as `/10` in detail + ranking/sidebar. **Why:** users think of the Buffett score as 0–10; only the internal/heatmap math uses the 0–100 form.

## Validation
- No good preview screenshot. Validate: `cd market-intel && python3 -c "import ast; ast.parse(open('app.py').read())"`, then exercise DB helpers via `python3 -c "import app; app.init_db(); ..."`.
