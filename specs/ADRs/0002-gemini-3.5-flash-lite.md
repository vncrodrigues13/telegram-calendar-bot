# ADR 0002: Use `gemini-3.5-flash-lite` as the extraction model

## Status

Proposed — live verification pending (see Follow-up).

## Context

[0001-gemini-flash-lite-model.md](0001-gemini-flash-lite-model.md) tried
`gemini-2.5-flash-lite` as a cheaper alternative to the current default
(`gemini-3.6-flash`) for this bot's narrow Person/Place/Time extraction
task. That attempt was rejected: the model 404s for new API keys/projects,
same as `gemini-2.5-flash` before it. Google's own error message named the
replacement:

```
This model models/gemini-2.5-flash-lite is no longer available to new
users. Please update your code to use models/gemini-3.5-flash-lite for the
latest features and improvements.
```

The reasoning for wanting a Flash-Lite tier at all is unchanged from ADR
0001: extraction is short-context and low-reasoning, Flash-Lite is roughly
an order of magnitude cheaper per token than Flash, and every forwarded
message/image costs a call.

## Decision

Switch the default extraction model from `gemini-3.6-flash` to
`gemini-3.5-flash-lite`, set via `LLM_MODEL=gemini-3.5-flash-lite` in
`.env` (already supported as an override in `config.py` / `registry.py` —
no code change required to trial it; already applied).

## Consequences

- Lower per-call cost for both text and image extraction, and for the
  best-effort `search_place` grounding calls, versus the `gemini-3.6-flash`
  baseline.
- Possible accuracy regression on messy, free-form pt-BR invites (relative
  dates, addresses buried in prose) — Flash-Lite trades capability for
  cost/speed, and this hasn't been measured against Flash on this project's
  actual prompts yet.
- Being on the 3.x generation (rather than 2.5, see ADR 0001) makes this
  less likely to be closed off to this project's API key, but that isn't
  guaranteed — verify with a live call before relying on it, per the
  lesson in ADR 0001.
- If Flash-Lite's extraction quality is unacceptable, reverting is a
  one-line `.env` change back to the previous default (or unset
  `LLM_MODEL` to fall back to `gemini-3.6-flash` in code).

## Follow-up

Live testing (via `uv run python -m event_bot.tools.try_extract` and
`try_extract_image`) is still needed against real invites (text and image)
to confirm the model is reachable and to compare output quality against
the `gemini-3.6-flash` baseline before this ADR can move to Accepted.

Blocked in this session on API key auth: the shell-exported
`GEMINI_API_KEY` (see ADR 0001's follow-up for why the shell env wins over
`.env`) returned `API_KEY_INVALID` when re-tried for this model, despite
having worked minutes earlier for the `gemini-2.5-flash-lite` test in ADR
0001 (that test got as far as a 404, which only happens after auth
succeeds). The key may have expired, been rotated, or the failure may be
session/environment-specific. Get a confirmed-working key from
https://aistudio.google.com/apikey and re-run the trial before accepting
this ADR.
