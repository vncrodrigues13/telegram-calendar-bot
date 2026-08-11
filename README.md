# Telegram → Google Calendar Birthday Bot

Forward a birthday invite to the bot on Telegram. It replies with the person,
place and time it extracted, plus ✅ / ✏️ / ❌ buttons. Tap ✅ and the event
lands in your Google Calendar, original message kept in the description.

An LLM does one narrow job — pull **Person / Place / Time** out of
unstructured pt-BR text. Approval, event creation and dedupe are deterministic
code. Nothing reaches the calendar without your tap.

```
Telegram (you forward) → bot/handlers.py
                              ↓
                          llm/  (Gemini today, provider-agnostic)
                              ↓
                     ExtractedEvent (pydantic)
                              ↓
                     approval card + inline buttons
                              ↓ (you tap ✅)
                     gcal/client.py → Google Calendar
                              ↓
                     store.py (sqlite: pending + dedupe)
```

## Setup

1. **Bot token** — [@BotFather](https://t.me/BotFather) → `/newbot` →
   `TELEGRAM_BOT_TOKEN`.
2. **Your user ID** — [@userinfobot](https://t.me/userinfobot) →
   `OWNER_TELEGRAM_ID`. The bot ignores everyone else.
3. **Gemini key** — [aistudio.google.com](https://aistudio.google.com) →
   `GEMINI_API_KEY`.
4. **Google Calendar OAuth** — in the
   [Cloud Console](https://console.cloud.google.com): new project → enable the
   **Google Calendar API** → OAuth consent screen (External, add your own
   address under **Test users**) → Credentials → OAuth client ID → **Desktop
   app** → download the JSON as `credentials.json` in the project root. The bot
   reads it directly and writes `token.json` on first login; both are
   gitignored.

```bash
cp .env.example .env && $EDITOR .env
uv sync
```

## Run

```bash
uv run python -m birthday_bot.main
```

Then forward an invite to the bot.

Two CLIs help before that, in order:

```bash
# extraction only — no Telegram, no Calendar (fast loop for prompt tuning)
uv run python -m birthday_bot.tools.try_extract "sábado tem niver da Ana! 15h na Rua das Flores 200"
uv run python -m birthday_bot.tools.try_extract "niver da Ana dia 12/03, 20h" --fix "é dia 22/03"

# OAuth check — opens a browser once, creates and deletes a test event
uv run python -m birthday_bot.tools.gcal_check

uv run pytest   # no network, no keys
```

## Behavior

- **No start time → no ✅.** The button is withheld and you're asked to supply
  the date via ✏️. An event with the wrong time is worse than no event.
- **Not an invite?** The bot says so and offers a "criar mesmo assim" button.
- **✏️ corrections** re-run the extraction with your note applied
  (`"é dia 22/03"`), rather than starting over.
- **Duplicates** surface "já criei esse evento" with the link. Matching ignores
  casing and re-wrapping.
- **Reminders** default to 1 day and 2 hours before (`REMINDER_MINUTES`).
- **Errors are reported in-chat**, not swallowed in the terminal.

## Integration points

| Seam | Where | Swap cost |
|---|---|---|
| LLM provider | `llm/base.py` Protocol, `llm/registry.py` factory | Gemini is installed; `claude.py` / `openai.py` ship as adapters — `uv add anthropic` + `LLM_PROVIDER=claude` |
| Calendar | `gcal/auth.py` (OAuth) + `gcal/client.py` (`create_event`) | user OAuth, scope `calendar.events` |
| Telegram | `bot/handlers.py`, long polling via PTB | owner-only filter at `register()` |
| State | `store.py`, sqlite (`pending` + `created`) | file path via `DB_PATH` |

All Portuguese prompt text, date-resolution rules and the `ExtractedEvent`
schema live in `llm/prompt.py` and `models.py` — a provider adapter never sees
them.

## Known trade-off

A Telegram bot cannot read your DMs, so capture is manual: you tap forward on
each invite. The seam in `bot/` keeps a future Telethon listener (which *can*
read everything) an additive change rather than a rewrite.

## Layout

```
src/birthday_bot/
    config.py    # pydantic-settings, reads .env
    models.py    # ExtractedEvent
    extract.py   # prompt + provider -> ExtractedEvent
    store.py     # sqlite: pending approvals + dedupe ledger
    main.py      # wiring + PTB startup
    llm/         # base.py (the seam), prompt.py, gemini|claude|openai, registry.py
    gcal/        # not `calendar/` — that shadows the stdlib module
    bot/         # handlers.py, cards.py
    tools/       # try_extract.py, gcal_check.py
```
