---
name: Além do Ticker (market-intel) app structure & gotchas
description: How the market-intel "Além do Ticker" Streamlit app is served and how it stores analyses.
---

# Além do Ticker (market-intel, Streamlit) — non-obvious facts

The app was reworked from a multi-mode "Market Intel" tool into a **single-purpose
investor (pessoa física) app called "Além do Ticker"**. Proposition: analyze Brazilian
companies in depth *beyond the stock price* — números realizados, projetos, perspectivas
e objetivos da gestão em documentos de RI.

## Which workflow serves the app
- **Which workflow serves Streamlit can flip between sessions.** Two workflows both run `cd market-intel && streamlit run app.py --server.port 5000`: the plain **`Start application`** and **`artifacts/mockup-sandbox: Start application`**. Only one can bind port 5000; the other goes **FAILED** with "Port 5000 is not available" — expected, not a bug.
- **Do not trust this file's memory of which one is live.** Run `refresh_all_logs` and restart whichever is currently RUNNING to reload code. Leave the FAILED duplicate alone.
- **No reliable preview-pane screenshot path.** `market-intel` is NOT a registered artifact, so `screenshot(app_preview, artifact_dir_name="market-intel")` errors. Validate via `curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/` (expect 200), AST/import checks, and logs instead.

## Single purpose — DP6 and Fornecedor fully REMOVED
- **No modes anymore.** DP6 (commercial-intelligence) and the older Fornecedor module are entirely gone — constants, prompts, renderers, the sidebar mode toggle, and `dp6_enabled()`. Do not reintroduce mode branching.
- **The `mode` column in `market_intel.db` is kept for backward compat only.** `_detect_mode()` now always returns `"investor"`; new saves are tagged `investor`. Legacy `mode='dp6'`/`'fornecedor'` rows stay invisible because history/overview query `list_analyses("investor")`. (The one-time `ALTER TABLE … DEFAULT 'fornecedor'` migration default is a harmless pre-existing leftover; new rows always set an explicit mode.)
- Vestigial `mode` params/helpers (`lenses_for_mode`, `icons_for_mode`, `_score_for_mode`, `mode=` args) remain but are functionally inert (investor-only). Harmless dead complexity.

## Sections the AI generates = 6 lenses + 3 scores
- `INVESTOR_LENSES` = 6 analytical lenses (Fundamentos Financeiros, Alocação de Capital, Vantagem Competitiva/Moat, Gestão e Governança, Riscos Declarados, Guidance e Perspectivas).
- `SCORE_METHODOLOGIES` = `["Score Buffett", "Score Barsi", "Score Graham"]`, each with `SCORE_META` (icon / investor name / subtitle / criteria list).
- `INVESTOR_SECTIONS = INVESTOR_LENSES + SCORE_METHODOLOGIES` — this is what the prompt asks for AND what the parser (`active_lenses` in `analyze_with_claude`) must recognize. If you change either list, the parser must use the combined list or score sections silently drop.

## 3-methodology score panel (replaces the single Score Buffett)
- Each analysis produces 3 notas (1–10), each with a 2–3 line **Justificativa** and a **Por critério** block, generated per methodology (Buffett = qualidade do negócio, Barsi = dividendos/renda, Graham = margem de segurança).
- `render_score_panel(results)` draws them as a **3-column evaluation panel at the TOP** of `page_analysis`, before the 6 detailed lens cards.
- Parsing helpers: `_extract_nota` (clamps 1–10), `_extract_justificativa` (stops at next `**Header:**`), `_extract_criteria_block`. Safe because parsing is per-section markdown.
- **Score scale:** stored 0–100, displayed `/10`. `compute_investor_score` = mean of the 3 notas × 10, with a composite fallback over `INVESTOR_LENSES` when notas are missing. `score_color` thresholds 70/45.

## One upload → one analysis
- "Nova análise" extracts PDF text once, runs `analyze_with_claude` (investor only), saves one DB row. Per-iteration try/except (continue-on-error) is retained from the old multi-module loop but now there's a single module.

## Cost / model controls
- **Model is Haiku.** `MODEL_CHAIN = ["claude-haiku-4-5-20251001", "claude-haiku-4-5"]` — dated Haiku primary, alias Haiku as 529 fallback. The `fallback_notice_for` notice only fires when the alias string is in the used-models set (a real 529→alias fallback); it stays silent in normal runs.
- **`out_max_tokens = 8000`** (single value, no mode branch). **Why:** quality-first per explicit user instruction "não quero que perca qualidade nem fique nada em branco" — the 9-section output (6 lenses + 3 scores w/ justificativa+criteria) must not truncate. Each `_call` returns ALL sections in one response, so this budget is shared across them.
- **Per-PDF input cap:** `extract_text_from_pdf` → `_trim_to_strategic_window(text, 50_000)`. **GOTCHA — two truncation points:** the prompt builder embeds `{pdf_text}`; verify both `extract_text_from_pdf` AND the builder when tuning input length.

## Streamlit gotchas (see streamlit-markdown-gotchas.md)
- `st.markdown` treats `$...$` as LaTeX → all rendered model text passes through `_md_escape_dollars` (R$/US$ heavy PT text).

## Validation
- `cd market-intel && python3 -c "import ast; ast.parse(open('app.py').read())"`, then `ANTHROPIC_API_KEY=x python3 -c "import app"` (ignore the Streamlit ScriptRunContext warning).
