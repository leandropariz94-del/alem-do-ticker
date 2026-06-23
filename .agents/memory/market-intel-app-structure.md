---
name: Market Intel app structure & workflow gotchas
description: How the market-intel Streamlit app is served and how it stores/separates analyses.
---

# Market Intel (Streamlit) — non-obvious facts

## Which workflow serves the app
- **Which workflow serves Streamlit can flip between sessions.** Two workflows both run `cd market-intel && streamlit run app.py --server.port 5000`: the plain **`Start application`** and **`artifacts/mockup-sandbox: Start application`**. Only one can bind port 5000; the other goes **FAILED** with "Port 5000 is not available" — this is expected, not a bug.
- **Do not trust this file's memory of which one is live.** Run `refresh_all_logs` and restart whichever one is currently RUNNING to reload code. Leave the FAILED duplicate alone.
- **No reliable preview-pane screenshot path.** `market-intel` is NOT a registered artifact, so `screenshot(app_preview, artifact_dir_name="market-intel")` errors ("Artifact not found"). The mockup-sandbox artifact's `/` / `/__mockup/` hits the Vite preview server, not Streamlit. Validate via `curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/` (expect 200), syntax check, DB checks, and logs instead.

## Modes (Investidor / DP6) — Fornecedor REMOVED
- **The Fornecedor module was removed entirely.** Only two live modes remain: **Investidor** (public default) and **DP6** (private, env-gated). All Fornecedor code is gone (`LENSES`/`LENS_ICONS`, `compute_opportunity_score`, `render_lens_card`, fornecedor prompt builders, all UI branches). `_count_bullets`/`_extract_tendencia` were KEPT (shared by investor/dp6).
- **Backward-compat leftovers kept on purpose:** the one-time `ALTER TABLE … DEFAULT 'fornecedor'` column add, and one legacy label mapping `"Oportunidades para Fornecedores"` in the markdown-compat path. Legacy `mode='fornecedor'` DB rows are untouched → they become invisible because history/overview filter by current mode. A one-time reclassify/cleanup script is the only way to surface them (out of scope).
- Analyses are tagged with a `mode` column in `market_intel.db`. `init_db()` adds the column and backfills via `_detect_mode(results)`; the parse-failure fallback now defaults to **`investor`** (not the defunct `fornecedor`) so unparseable rows stay visible.
- `_detect_mode` is now binary: `"Oportunidades para a DP6"` present → `dp6`; else → `investor`. Default mode is `investor` everywhere (sidebar, `main()`, page signatures, `analyze_with_claude`).
- Mode-aware helpers centralize branching: `lenses_for_mode(mode)`, `icons_for_mode(mode)`, `_score_for_mode(mode, results)`. Sidebar history + Visão Geral filter by `st.session_state["mode"]` so modes never mix.

## DP6 mode (commercial-intelligence mode for DP6 the consultancy)
- **Feature flag:** env var `DP6_MODE_ENABLED`, default ON. `"0"/"false"/"off"` hide the DP6 radio option; if dp6 was the active session mode when the flag goes off, sidebar falls back to `investor`. When the flag is off the radio shows a single Investidor option (acceptable). Purpose: hide DP6 mode when releasing the app to the market.
- 7 lenses (`DP6_LENSES`): Destaque do Período, Eficiência e Performance, Evolução Digital e IA, Ecossistema de Dados, Dores e Metas Futuras, Direcionamento Estratégico, Oportunidades para a DP6.
- Prompts: `_build_dp6_extraction_prompt` + `_build_dp6_consolidation_prompt` (shared `_DP6_SECTION_FORMAT`: Insight Consolidado / Sinais para a DP6 / Métricas / Citações; the opportunity lens adds Serviços DP6 Recomendados + Abordagem Comercial + Prioridade). Wired via `mode=="dp6"` in `analyze_with_claude`.
- **Output tokens are capped LOW for cost:** `analyze_with_claude` sets `out_max_tokens = 2000` for ALL modes (was 16000 dp6 / 8192 others). **Why:** explicit cost-reduction request — cheaper per call. **Tradeoff:** DP6's 7 verbose sections (esp. the last, Oportunidades, with 3 sub-blocks) WILL truncate at 2000 → blank/partial final cards. This is a known, accepted tradeoff; if DP6 output quality matters again, raise this cap. Each `_call` returns ALL lenses' markdown in one response, so 2000 is shared across all lenses of a call.
- DP6 lens cards (`render_dp6_lens_card`) intentionally render NO trend badge — long PT trend labels ("Em transformação", "Aceleração") broke the narrow badge column. The `**Tendência:**` line is still stripped from the body. `render_trend_badge` is still used by investor cards.

## One upload → all modules
- The "Nova análise" button extracts PDF text ONCE, then loops `analyze_with_claude` over every enabled mode (dp6 only if `dp6_enabled()`, then investor) on the same `files_and_texts`, saving one DB row per mode via `save_analysis(..., mode=m)`. After all modes finish it opens the detail page for the currently-active sidebar mode (`saved_ids.get(mode)` or the first saved). **Why:** users wanted one upload to populate all modules instead of uploading multiple times. Cost: ~70s per mode → a single click can take a few minutes.
- `save_analysis` takes an optional explicit `mode` (falls back to `_detect_mode`). The fallback-model notice is tracked per mode (`models_by_mode`) and only fires for the landing module — don't revert to the shared `_models_used` aggregate or the notice misfires across modes.
- **Error handling is continue-on-error (per-iteration try/except), NOT abort-on-first-failure.** **Why:** the old outer try/except aborted the whole loop on the first module error, silently dropping later modules — the investor module (last in the loop) "didn't analyze" whenever an earlier module errored. Now each module runs independently; failures append to `failed_modes` and `continue`; successful modules still save. If ALL fail → consolidated error + return; if SOME fail → navigate to a saved module and set `st.session_state["partial_failure_notice"]` (a warning rendered once on the matching detail page). Don't reintroduce an outer abort.

## Cost controls (input/model/output)
- **Model is Haiku, not Sonnet/Opus.** `MODEL_CHAIN = ["claude-haiku-4-5-20251001", "claude-haiku-4-5"]` — dated Haiku primary (cheap, fine for structured extraction), alias Haiku as 529 fallback. **Why:** explicit cost-reduction. The legacy "fall back to faster/less-deep Haiku" notice (`fallback_notice_for`) only fires if the SET contains exactly `"claude-haiku-4-5"` (the alias), which the dated primary string does NOT match — so it stays silent in normal runs and only (mildly inaccurately) fires on a real 529→alias fallback.
- **Per-PDF input cap:** `extract_text_from_pdf` runs every PDF through `_trim_to_strategic_window(text, PDF_CHAR_LIMIT=50_000)` — keeps ~70% from the start + a middle slice, drops the end (repetitive tables/footnotes). **Why:** releases concentrate strategy at start/middle; trimming the tail cuts input tokens.
- **GOTCHA — two truncation points.** The extraction prompt builders (`_build_investor_extraction_prompt`, `_build_dp6_extraction_prompt`) embed `{pdf_text}`; they USED to hard-slice `{pdf_text[:8000]}`, which silently overrode any upstream window. That slice was removed so the trimmed 50k reaches the API. **Lesson:** the actual input size sent to Claude is governed by the prompt builders, not only by `extract_text_from_pdf` — change/verify both when tuning input length.

## Score scales
- Stored 0–100 for all modes. Displayed: investor `/10` (Buffett nota×10 stored, shown as 0–10 because users think 0–10); dp6 `/100`. `score_color` thresholds 70/45.
- `compute_dp6_score` ("temperatura comercial"): per-lens "Sinais para a DP6" bullets capped at 3 (×2.5), opportunity "Serviços DP6 Recomendados" capped at 5 (×1.5), Prioridade Alta +10 / Média +5, trend ±1.5, normalized by /80 then clamped 0–100. **Why:** caps + denominator-above-max keep discrimination at the top (typical ~40-50, strong ~80-90) instead of saturating at 100.

## Validation
- `cd market-intel && python3 -c "import ast; ast.parse(open('app.py').read())"`, then exercise funcs via `python3 -c` after `os.environ.setdefault("ANTHROPIC_API_KEY","x"); import app` (ignore the Streamlit ScriptRunContext warning).
