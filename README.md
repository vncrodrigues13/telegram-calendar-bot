# Telegram → Google Calendar Birthday Bot

Forward a birthday invite to your bot on Telegram. It replies with the
person, place, and time it extracted, plus ✅ / ✏️ / ❌ buttons. Tap ✅ and the
event lands in your Google Calendar, with the original message preserved in
the description.

An LLM does one narrow job — pull **Person / Place / Time** out of unstructured
pt-BR text. Everything else (approval, event creation, deduplication) is
deterministic code.

```
Telegram (you forward) → bot/handlers.py
                              ↓
                     llm/ (provider-agnostic)  ← prompt.py builds the pt-BR prompt
                              ↓                   base.py = the swap seam
                     ExtractedEvent (pydantic)
                              ↓
                     approval card + inline buttons
                              ↓ (you tap ✅)
                     gcal/client.py → Google Calendar
                              ↓
                     store.py (sqlite: pending + dedupe)
```

Two things are load-bearing:

- **The AI provider is swappable.** Gemini, Claude, and OpenAI are a config
  change, not a rewrite. `LLM_PROVIDER=claude` and you're done.
- **Nothing lands in the calendar without your approval.** A hallucinated date
  should never silently occupy a Saturday.

---

## Setup

You need four things. Steps 1–3 take about five minutes; step 4 is the fiddly
one.

### 1. Bot token — @BotFather

Open Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`,
pick a name and a username. Copy the token it gives you (looks like
`123456:ABC-DEF...`) → `TELEGRAM_BOT_TOKEN`.

### 2. Your Telegram user ID — @userinfobot

Message [@userinfobot](https://t.me/userinfobot). It replies with your numeric
ID → `OWNER_TELEGRAM_ID`. This locks the bot to you: anyone else who finds it
gets no response at all.

### 3. Gemini API key

[aistudio.google.com](https://aistudio.google.com) → **Get API key** → create
one → `GEMINI_API_KEY`.

(Using Claude or OpenAI instead? Set `LLM_PROVIDER` and the matching
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`. Only the selected provider's SDK and
key are touched at runtime.)

### 4. Google Calendar OAuth

In the [Google Cloud Console](https://console.cloud.google.com):

1. Create a new project (top-left project picker → **New Project**).
2. **APIs & Services → Library** → search "Google Calendar API" → **Enable**.
3. **APIs & Services → OAuth consent screen** → User Type **External** →
   fill in app name and your email → **Save and Continue** through the
   scopes screen → on **Test users**, click **Add Users** and add your own
   Google address. (Without this the app stays in testing mode and refuses
   your login.)
4. **APIs & Services → Credentials** → **Create Credentials** → **OAuth client
   ID** → Application type **Desktop app** → **Create** → **Download JSON**.
5. Save that file as `credentials.json` in the project root.

You never paste anything from this file into `.env`; the bot reads it directly
and writes a `token.json` next to it after your first login. Both are
gitignored.

### 5. Configure

```bash
cp .env.example .env
$EDITOR .env
uv sync
```

---

## Check it works

Run these in order — each one works before the next is needed.

**1. Install**

```bash
uv sync && uv run python -c "import telegram, google.genai, googleapiclient; print('ok')"
```

**2. Extraction alone** — no Telegram, no Calendar. This is the fast loop for
tuning the prompt:

```bash
uv run python -m birthday_bot.tools.try_extract \
  "Galera, sábado tem niver da Ana! 15h na Rua das Flores 200, Pinheiros. Traz bebida 🎂"
```

Expect `person: "Ana"`, `place` with the street, `start` on the *next*
Saturday at 15:00, `is_birthday_invite: true`. Also worth trying:

- `"bom dia pessoal"` → `is_birthday_invite: false`
- `"dia 12/03 às 20h"` → **March 12**, not December 3

**3. Provider swap** — same input, three providers, same shape out:

```bash
MSG="Galera, sábado tem niver da Ana! 15h na Rua das Flores 200"
LLM_PROVIDER=gemini uv run python -m birthday_bot.tools.try_extract "$MSG"
LLM_PROVIDER=claude uv run python -m birthday_bot.tools.try_extract "$MSG"
LLM_PROVIDER=openai uv run python -m birthday_bot.tools.try_extract "$MSG"
```

**4. Google Calendar auth + write** — opens a browser once, writes
`token.json`, then creates and immediately deletes a test event:

```bash
uv run python -m birthday_bot.tools.gcal_check
```

**5. Unit tests** — no network, no API keys:

```bash
uv run pytest
```

**6. End to end**

```bash
uv run python -m birthday_bot.main
```

Forward a real invite from Telegram. Expect the card within a few seconds; tap
✅ and confirm the event appears in Google Calendar with the original message
in the description. Forward the same message again to confirm dedupe fires.

---

## How it behaves

- **Missing time blocks creation.** If the message gives no start time, the ✅
  button is withheld and you're asked to supply the date via ✏️. An event with
  no time is worse than no event.
- **Not an invite?** The bot says so and offers a "criar mesmo assim" button
  for the occasional miss.
- **✏️ corrections** re-run the extraction with your correction applied
  (`"na verdade é da Bia"`, `"é dia 22/03"`) rather than starting over.
- **Duplicates.** Forwarding the same invite twice — easy to do in a busy
  group — surfaces "já criei esse evento" with the link instead of creating a
  second entry. Matching ignores casing and re-wrapping.
- **Reminders** default to 1 day and 2 hours before, configurable via
  `REMINDER_MINUTES`.
- **Errors are reported in-chat**, not swallowed in the terminal.

## Known trade-off

A Telegram bot cannot read your DMs, so capture is manual — you tap forward on
each invite. The `MessageSource` seam in `bot/` keeps a future Telethon
listener (which *can* read everything automatically) an additive change rather
than a rewrite.

## Adding a fourth provider

Write one file implementing `LLMProvider` from `llm/base.py`:

```python
async def extract_json(self, *, system: str, user: str, schema: type[ModelT]) -> ModelT: ...
```

then add it to `_KEY_FIELDS` and the factory chain in `llm/registry.py`. All
Portuguese prompt text, date-resolution rules, and the `ExtractedEvent` schema
live in `llm/prompt.py` and `models.py` — a provider adapter never sees them.

## Layout

```
src/birthday_bot/
    config.py        # pydantic-settings, reads .env
    models.py        # ExtractedEvent
    extract.py       # prompt + provider -> ExtractedEvent
    store.py         # sqlite: pending approvals + dedupe ledger
    main.py          # wiring + PTB startup
    llm/
        base.py      # LLMProvider Protocol  ← the seam
        prompt.py    # pt-BR system prompt + user prompt builders
        gemini.py    # google-genai
        claude.py    # anthropic
        openai.py    # openai
        registry.py  # LLM_PROVIDER env -> provider instance
    gcal/            # not `calendar/` — that shadows the stdlib module
        auth.py      # InstalledAppFlow + token.json refresh
        client.py    # create_event()
    bot/
        handlers.py  # message -> extract -> card; callbacks -> create
        cards.py     # renders the approval message + keyboard
    tools/
        try_extract.py  # CLI: test extraction, no Telegram/Calendar
        gcal_check.py   # CLI: verify OAuth, create+delete a test event
```
