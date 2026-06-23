---
name: Market Intel app structure & workflow gotchas
description: How the market-intel Streamlit app is served and how it stores/separates analyses.
---

# Market Intel (Streamlit) — non-obvious facts

## Which workflow serves the app
- **Which workflow serves Streamlit can flip between sessions.** Two workflows both run `cd market-intel && streamlit run app.py --server.port 5000`: the plain **`Start application`** and **`artifacts/mockup-sandbox: Start application`**. Only one can bind port 5000; the other goes **FAILED** with "Port 5000 is not available" — this is expected, not a bug.
- **Do not trust this file's memory of which one is live.** Run `refresh_all_logs` and restart whichever one is currently RUNNING to reload code. Leave the FAILED duplicate alone.
- **No reliable preview-pane screenshot path.** `market-intel` is NOT a registered artifact, so `screenshot(app_preview, artifact_dir_name="market-intel")` errors ("Artifact not found"). The mockup-sandbox artifact's `/` / `/__mockup/` hits the Vite preview server, not Streamlit. Validate via `curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/` (expect 200), syntax check, DB checks, and logs instead.

## Modes (Fornecedor / Investidor / DP6)
- Analyses are tagged with a `mode` column (`'fornecedor'` | `'investor'` | `'dp6'`) in `market_intel.db`. `init_db()` adds the column and backfills via `_detect_mode(results)`.
- `_detect_mode` precedence: investor sentinels first (`"Fundamentos Financeiros"` or `"Score Buffett"`) → `investor`; then `"Oportunidades para a DP6"` → `dp6`; else `fornecedor`. **Why:** investor takes precedence so a malformed payload carrying both key families is never misclassified as DP6. Lens key sets are otherwise disjoint.
- Mode-aware helpers centralize branching: `lenses_for_mode(mode)`, `icons_for_mode(mode)`, `_score_for_mode(mode, results)`. Sidebar history + Visão Geral filter by `st.session_state["mode"]` so modes never mix.

## DP6 mode (commercial-intelligence mode for DP6 the consultancy)
- **Feature flag:** env var `DP6_MODE_ENABLED`, default ON. `"0"/"false"/"off"` hide the DP6 radio option; if dp6 was the active session mode when the flag goes off, sidebar falls back to `fornecedor`. Purpose: hide DP6 mode when releasing the app to the market.
- 7 lenses (`DP6_LENSES`): Destaque do Período, Eficiência e Performance, Evolução Digital e IA, Ecossistema de Dados, Dores e Metas Futuras, Direcionamento Estratégico, Oportunidades para a DP6.
- Prompts: `_build_dp6_extraction_prompt` + `_build_dp6_consolidation_prompt` (shared `_DP6_SECTION_FORMAT`: Insight Consolidado / Sinais para a DP6 / Métricas / Citações; the opportunity lens adds Serviços DP6 Recomendados + Abordagem Comercial + Prioridade). Wired via `mode=="dp6"` in `analyze_with_claude`.
- **DP6 needs more output tokens:** `analyze_with_claude` sets `out_max_tokens = 16000 if mode=="dp6" else 8192`. **Why:** DP6's 7 verbose sections (the last, Oportunidades, has 3 sub-blocks) truncated at 8192 — the final lens card rendered blank because stored content was literally `**Tendência:** Qu`. Any new verbose mode/section needs the same headroom check.
- DP6 lens cards (`render_dp6_lens_card`) intentionally render NO trend badge — long PT trend labels ("Em transformação", "Aceleração") broke the narrow badge column. The `**Tendência:**` line is still stripped from the body. `render_trend_badge` is still used by fornecedor/investor cards.

## One upload → all modules
- The "Nova análise" button extracts PDF text ONCE, then loops `analyze_with_claude` over every enabled mode (dp6 only if `dp6_enabled()`, then fornecedor, then investor) on the same `files_and_texts`, saving one DB row per mode via `save_analysis(..., mode=m)`. After all modes finish it opens the detail page for the currently-active sidebar mode (`saved_ids.get(mode)`). **Why:** users wanted one upload to populate all three modules instead of uploading 3×. Cost: ~70s per mode → a single click can take a few minutes.
- `save_analysis` takes an optional explicit `mode` (falls back to `_detect_mode`). The fallback-model notice is tracked per mode (`models_by_mode`) and only fires for the landing module — don't revert to the shared `_models_used` aggregate or the notice misfires across modes.
- Error handling aborts on the first mode that hard-fails (after the model fallback chain), leaving earlier modes already saved; retrying re-runs all modes and can create duplicate rows. Acceptable for now.

## Score scales
- Stored 0–100 for all modes. Displayed: investor `/10` (Buffett nota×10 stored, shown as 0–10 because users think 0–10); fornecedor & dp6 `/100`. `score_color` thresholds 70/45.
- `compute_dp6_score` ("temperatura comercial"): per-lens "Sinais para a DP6" bullets capped at 3 (×2.5), opportunity "Serviços DP6 Recomendados" capped at 5 (×1.5), Prioridade Alta +10 / Média +5, trend ±1.5, normalized by /80 then clamped 0–100. **Why:** caps + denominator-above-max keep discrimination at the top (typical ~40-50, strong ~80-90) instead of saturating at 100.

## Validation
- `cd market-intel && python3 -c "import ast; ast.parse(open('app.py').read())"`, then exercise funcs via `python3 -c` after `os.environ.setdefault("ANTHROPIC_API_KEY","x"); import app` (ignore the Streamlit ScriptRunContext warning).
