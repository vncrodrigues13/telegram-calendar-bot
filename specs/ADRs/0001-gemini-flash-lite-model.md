# ADR 0001: Use `gemini-2.5-flash-lite` as the extraction model

## Status

Rejected — superseded by [0002-gemini-3.5-flash-lite.md](0002-gemini-3.5-flash-lite.md).

## Context

The bot's only LLM job is narrow: pull Person / Place / Time out of a
forwarded Portuguese invite (text or image) into a fixed schema
(`extract_json` / `extract_json_from_image` in `llm/gemini.py`). This is
short-context, low-reasoning extraction, not open-ended generation.

The current default, set in `llm/gemini.py`, is `gemini-3.6-flash` — the
general "Flash" workhorse tier. It was picked as a fallback after the
originally spec'd `gemini-2.5-flash` returned 404s on fresh API keys
(Google closed 2.5 Flash to new projects). Flash was never chosen for this
project on capability grounds; it's just the default tier one step up from
Flash-Lite.

Google's current Gemini lineup has three tiers: Pro (reasoning), Flash
(everyday), and Flash-Lite (cheapest/fastest, aimed at high-volume, low-
latency jobs like extraction and classification). Flash-Lite is roughly an
order of magnitude cheaper per token than Flash, which matters here because
every forwarded message and every image costs a call, and the task itself
doesn't need Flash-tier reasoning.

## Decision

Switch the default extraction model from `gemini-3.6-flash` to
`gemini-2.5-flash-lite`, set via `LLM_MODEL=gemini-2.5-flash-lite` in
`.env` (already supported as an override in `config.py` / `registry.py` —
no code change required to trial it).

2.5 Flash-Lite (not 3.5/3.1 Flash-Lite) was picked for the first trial
because it's the cheapest tier available (~$0.05 / $0.20 per 1M
input/output tokens) and the older, more-established generation of the
lite tier.

## Outcome

Live-tested via `try_extract_image` once a valid API key was in place, and
it failed immediately:

```
gemini: 404 NOT_FOUND. {'error': {'code': 404, 'message': 'This model
models/gemini-2.5-flash-lite is no longer available to new users. Please
update your code to use models/gemini-3.5-flash-lite for the latest
features and improvements.', 'status': 'NOT_FOUND'}}
```

This is the same failure mode that already killed `gemini-2.5-flash` (see
Context): Google has closed the 2.5 generation to new API keys/projects,
regardless of tier.

**Lesson learned (applies beyond this decision):** don't assume a model ID
from docs, blog posts, or pricing pages is actually callable — any Gemini
2.5-era model name should be treated as likely dead for new API keys.
Any model swap needs one live call before it's trusted. Future attempts
should start from the 3.x generation.

## Follow-up

See [0002-gemini-3.5-flash-lite.md](0002-gemini-3.5-flash-lite.md), which
tries the replacement model Google's own error message named.

API key trouble encountered while testing this ADR, for reference: two
values pasted directly into `.env` (prefixed `AQ.`, not the standard
AI-Studio `AIzaSy...` format) both returned `API_KEY_INVALID`. A
shell-exported `GEMINI_API_KEY` (`AIzaSyDW1...`, correct format) was found
to silently take priority over the `.env` value — pydantic-settings/dotenv
treats real environment variables as higher priority than `.env` file
contents. If `.env` edits to `GEMINI_API_KEY` ever appear to have no
effect, check `env | grep GEMINI_API_KEY` for a shadowing export first.
