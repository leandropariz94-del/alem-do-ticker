---
name: Anthropic proxy 529 / model availability
description: How the Replit-managed Anthropic proxy behaves under load and which models stay available.
---

# Anthropic proxy 529 overload behavior

The `market-intel` Streamlit app calls Anthropic via `anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])`. The SDK auto-uses `ANTHROPIC_BASE_URL` when set, so this routes through Replit's managed proxy (not a direct user key). Evidence: models outside the proxy's allow-list (e.g. `claude-3-5-sonnet-20241022`) return 404.

**Observed during peak load (June 2026):** `claude-opus-4-8/4-7/4-6/4-5` and `claude-sonnet-4-6/4-5` all return `529 overloaded_error`, while `claude-haiku-4-5` responds instantly. The larger/newer models are the most congested; Haiku almost always retains capacity.

**Rule:** for resilience use a model fallback chain (preferred → Haiku), not just retry-on-529. Pure retry can wait 60s+ and still fail because the proxy stays saturated for minutes. Fallback to Haiku gets the user a result immediately.

**Why:** 529 is server/proxy capacity, not a code bug and not file-size related. Retry mitigates transient blips but cannot fix sustained overload; a different (lighter) model is the only reliable escape during peaks.

**How to apply:** the supported proxy model list lives in the `ai-integrations-anthropic` skill. When falling back to a weaker model, surface it to the user (quality may degrade) — `market-intel` records models used in `st.session_state["_models_used"]` and shows a one-time notice on the detail page when only Haiku produced the result.
