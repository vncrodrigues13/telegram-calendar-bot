# Kick-off — remaining work

Status as of **2026-08-11**. Companion to [`telegram-calendar-bot.md`](telegram-calendar-bot.md), which describes the design; this file tracks only what is left.

The build is complete — every file in the plan exists, with no stubs. `credentials.json` is now in place; what remains is granting OAuth consent once, one untested path, and hygiene.

---

## Blocking — nothing works end to end until this is done

- [ ] **Run `uv run python -m birthday_bot.tools.gcal_check`** (needs you — it opens a browser)
  Grants consent once, writes `token.json`, creates a test event and deletes it. Clears verification step 4. Two failures are possible here and neither is visible in `credentials.json`:
  - `access_denied` → your account is not a **test user** on the OAuth consent screen.
  - 403 "Calendar API has not been used…" → **Google Calendar API** is not enabled on project `fourth-amp-468802-v5`.
- [ ] **End-to-end run** — `uv run python -m birthday_bot.main`, forward a real invite, tap ✅, confirm the event lands in Google Calendar with the original message in the description. Forward the same message again to confirm dedupe fires. Clears verification step 6.

> The bot **boots and runs without `token.json`** — `CalendarClient` builds its Google service lazily. You can start it now and exercise the card, ✏️, ❌ and dedupe paths today; only the ✅ tap fails, and it fails into the in-chat error handler rather than crashing.

---

## Security

- [ ] **Rotate the OpenAI key at `~/.zshrc:53`** — it was printed in full into an assistant transcript on 2026-08-10 and must be considered compromised. Rotate at <https://platform.openai.com/api-keys>.
  It is unrelated to this project and can simply be deleted from `~/.zshrc` if nothing else uses it.

---

## Code

- [ ] **Add a correction mode to `try_extract`** (highest-value remaining change)
  `reextract_with_correction` — the ✏️ path — is reachable *only* through `handlers.py`, so it has never run against a real LLM. `test_prompt.py` asserts on the prompt string, not a round-trip. This is the mechanism you reach for every time Gemini gets a date wrong, and it is the least-exercised code in the project. A `--fix "é dia 22/03"` flag would move it into the fast loop.
- [ ] **Catch `ValueError` in `try_extract`** — a missing API key currently surfaces as a raw traceback. The message is correct and the failure is early; it just prints badly.
- [ ] **Better error when a deferred provider's SDK is missing** — `LLM_PROVIDER=claude` with a key set but `anthropic` uninstalled dies on a bare `ModuleNotFoundError`. `registry.py` could catch it and say "reinstale com `uv add anthropic`". Low priority: the no-key path (the likely mistake) already reports clearly.

---

## Documentation

- [ ] **Update `README.md` — it contradicts the current plan.** It still advertises three live providers:
  - lines 28–29 — "Gemini, Claude, and OpenAI are a config change… `LLM_PROVIDER=claude` and you're done"
  - lines 57–58 — instructions for setting `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
  - lines 114–120 — verification step 3 as a three-provider comparison
  - lines 196–197 — file tree listing `claude.py` / `openai.py` without deferred status

  All four need to match the Gemini-only decision, including that re-enabling a provider now also requires `uv add`.

---

## Repository hygiene

- [ ] **`git init` + first commit** — the project is not a git repository. `.gitignore` is written and correct (`.env`, `credentials.json`, `token.json`, `*.db`) but inert until a repo exists, and real secrets are sitting in the working tree right now: `.env` plus, since 2026-08-11, the OAuth `client_secret` in `credentials.json` — and `token.json` will join them after the step above. Initialize *before* the first commit, not after, and confirm `git status` shows none of the four.

---

## Deferred by decision — not work, recorded so it is not mistaken for an oversight

- **Verification step 3 (provider swap) is unrun.** Only Gemini is configured, so there is nothing to compare against. This is the real test of constraint #1 and stays open until a second provider is funded.
- **`anthropic` and `openai` removed from dependencies** (2026-08-10). The adapters remain in the tree; their SDKs are not installed. The two schema-portability tests in `test_models.py` `importorskip` and reactivate automatically if either SDK returns.

---

## Already verified — do not redo

| Check | Result |
|---|---|
| Install + imports | ✅ |
| Gemini extraction | ✅ 5/5 messages correct (next-Saturday, non-invite, DD/MM ordering, year inference) |
| Unit tests | ✅ 31 passed, 2 skipped (deferred SDKs) |
| Telegram token | ✅ live — bot is **Jarvis** (@viniciusrodrigues_bot) |
| Webhook clear for long polling | ✅ none set, 0 pending |
| Bot boots + connects | ✅ `Application started` |
| SQLite schema | ✅ `pending` + `created`, matches plan |
| `.env.example` vs `config.py` | ✅ all 14 fields, zero drift |
| Gemini default model | ✅ `gemini-3.6-flash` (2.5-flash is closed to new API keys) |
| `credentials.json` present + correct type | ✅ 2026-08-11 — top-level `installed` (Desktop app, the type `run_local_server` requires), all fields present, project `fourth-amp-468802-v5`; `InstalledAppFlow` builds against it with the `calendar.events` scope |
