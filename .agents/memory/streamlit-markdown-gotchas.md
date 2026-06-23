---
name: Streamlit markdown gotchas
description: Non-obvious rendering/truncation traps when displaying LLM output in Streamlit.
---

# Streamlit markdown gotchas (market-intel)

## `$...$` renders as LaTeX math
`st.markdown()` interprets `$...$` and `$$...$$` as LaTeX. Brazilian financial text uses `R$` and `US$` constantly, so two dollar signs on the same line pair up and the text between them renders as an italic/monospace formula (e.g. "R\$ 1,11 ... vs. R\$ 1,00" mangles "1,11 ... vs. R").

**Fix:** escape every `$` to `\$` before passing user/LLM text to `st.markdown`. In `market-intel` this is `_md_escape_dollars()`, applied at all lens-card render sites.

**Why:** it's a rendering trap, not bad model output — the model returns correct text; Streamlit mangles it. Easy to misdiagnose as an LLM formatting bug.

## Low max_tokens silently truncates multi-section output
When one LLM call must emit many sections (9 supplier lenses / 7 investor lenses as `## headers`), a small `max_tokens` cuts the response mid-sentence. Sections after the cut never appear, so the section parser yields empty strings for them — looks like "the model skipped those lenses" but it's truncation.

**Fix:** use 8192 max_tokens for these multi-section calls (the `ai-integrations-anthropic` skill mandates 8192 minimum). Symptoms of too-low limit: a trailing half-sentence in one section + several fully empty later sections.
