# Telegram → Google Calendar Event Bot

Forward an event invite — birthday, wedding, race, show, whatever — to the
bot on Telegram. It replies with the title, type, person, place and time it
extracted, plus ✅ / ✏️ / ❌ buttons. Tap ✅ and the event lands in your
Google Calendar, original message kept in the description.

An LLM does one narrow job — pull **Title / Type / Person / Place / Time**
out of unstructured pt-BR text. Approval and event creation are
deterministic code. Nothing reaches the calendar without your tap.

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
                     store.py (sqlite: pending approvals)
```

## Requirements

Four things from the outside world, plus a Python toolchain. Budget about
15 minutes end to end — the Google Cloud part is the slow one, everything else
is copy-paste.

| # | What you need | Where it comes from | Lands in |
|---|---|---|---|
| 0 | Python **3.13+** and [uv](https://docs.astral.sh/uv/) | your machine | — |
| 1 | Telegram **bot token** | @BotFather | `.env` → `TELEGRAM_BOT_TOKEN` |
| 2 | Your **Telegram user ID** (a number) | @userinfobot | `.env` → `OWNER_TELEGRAM_ID` |
| 3 | **Gemini API key** | Google AI Studio | `.env` → `GEMINI_API_KEY` |
| 4 | **`credentials.json`** | Google Cloud Console | project root |

What you *don't* need: a server, a domain, a webhook, an always-on machine, or
a Google Calendar API key (there is no such thing here — see step 4). The bot
long-polls Telegram from your laptop; close the terminal and it simply stops.

### 0. Python 3.13+ and uv

[uv](https://docs.astral.sh/uv/) manages both the Python version and the
dependencies, so it's the only thing you install by hand:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
uv sync                                            # installs Python 3.13 + deps
```

Verify with `uv run pytest`. The suite is fully offline — it needs no keys, no
network, and no Google account, so a green run here confirms the toolchain
before you go collect any credentials.

### 1. Telegram bot token

Open [@BotFather](https://t.me/BotFather) in Telegram and send `/newbot`. It
asks for a display name (anything) and a username (must end in `bot`, e.g.
`meu_calendario_bot`). It replies with a token shaped like
`123456789:AAE-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.

Copy the whole thing, colon included, into `TELEGRAM_BOT_TOKEN`. Anyone holding
this token controls the bot, so it stays in `.env` — which is gitignored.

### 2. Your Telegram user ID

Message [@userinfobot](https://t.me/userinfobot) and it answers with your
numeric ID (something like `123456789` — a number, *not* your `@username`).
Put it in `OWNER_TELEGRAM_ID`.

This is the bot's entire access control: messages from any other ID are ignored
without a reply. Get it wrong and the bot will simply never answer you.

### 3. Gemini API key

Go to [aistudio.google.com](https://aistudio.google.com) → **Get API key** →
create one in a new or existing project. Paste it into `GEMINI_API_KEY`.

The free tier is generous and one forwarded invite is a single small request,
so personal use typically costs nothing. Only this key is required by default —
`claude` and `openai` adapters ship in `llm/`, but using one means setting
`LLM_PROVIDER`, its own key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`), and
installing the SDK (`uv add anthropic` / `uv add openai`).

### 4. Google Calendar access (`credentials.json`)

This is **not** an API key. Writing to *your* calendar requires *your* consent,
so Google uses OAuth: you register an app, then grant it access in a browser.

In the [Cloud Console](https://console.cloud.google.com):

1. Create a project (or reuse one) — top-left project picker → **New project**.
2. **APIs & Services → Library** → search *Google Calendar API* → **Enable**.
3. **OAuth consent screen** → User type **External** → fill in app name and
   your email → under **Test users**, add your own Google address.
   ↳ Skipping this is the #1 cause of *"Access blocked: app has not completed
   verification"* later.
4. **Credentials → Create credentials → OAuth client ID** → Application type
   **Desktop app** → Create → **Download JSON**.
5. Rename the downloaded file to `credentials.json` and drop it in the project
   root, next to `pyproject.toml`.

The first time the bot needs the calendar it opens your browser once, you
approve, and it saves the result to `token.json` — refreshed automatically from
then on, so you never see that screen again. Both files are gitignored and stay
on your machine.

Check it end to end before running the bot:

```bash
uv run python -m event_bot.tools.gcal_check   # creates and deletes a test event
```

The bot only ever asks for `calendar.events` — permission to create events,
not to read your existing calendar.

### Putting it together

```bash
cp .env.example .env && $EDITOR .env   # paste steps 1-3 here
uv sync
uv run python -m event_bot.tools.gcal_check   # step 4, one-time browser login
```

`.env.example` documents every optional setting too — timezone, calendar ID,
reminder offsets, default event length.

## Run

```bash
uv run python -m event_bot.main
```

Then forward an invite to the bot.

Smaller CLIs exercise one piece at a time — useful for tuning the prompt, or
for narrowing down which part broke:

```bash
# extraction only — no Telegram, no Calendar (fast loop for prompt tuning)
uv run python -m event_bot.tools.try_extract "sábado tem niver da Ana! 15h na Rua das Flores 200"
uv run python -m event_bot.tools.try_extract "niver da Ana dia 12/03, 20h" --fix "é dia 22/03"

# image extraction only — no Telegram, no Calendar
uv run python -m event_bot.tools.try_extract_image specs/plans/image-extractor/image.png

# OAuth check — opens a browser once, creates and deletes a test event
uv run python -m event_bot.tools.gcal_check

uv run pytest   # no network, no keys
```

## Behavior

- **No date → no ✅.** The button is withheld and you're asked to supply the
  date via ✏️. A date-only message still creates an all-day event; an event
  with the wrong time is worse than no event.
- **Not an invite?** The bot says so and offers a "criar mesmo assim" button.
- **✏️ corrections** re-run the extraction with your note applied
  (`"é dia 22/03"`), rather than starting over.
- **Reminders** default to 1 day and 2 hours before (`REMINDER_MINUTES`).
- **Errors are reported in-chat**, not swallowed in the terminal.

## Integration points

| Seam | Where | Swap cost |
|---|---|---|
| LLM provider | `llm/base.py` Protocol, `llm/registry.py` factory | Gemini is installed; `claude.py` / `openai.py` ship as adapters — `uv add anthropic` + `LLM_PROVIDER=claude` |
| Calendar | `gcal/auth.py` (OAuth) + `gcal/client.py` (`create_event`) | user OAuth, scope `calendar.events` |
| Telegram | `bot/handlers.py`, long polling via PTB | owner-only filter at `register()` |
| State | `store.py`, sqlite (`pending`) | file path via `DB_PATH` |

All Portuguese prompt text lives in `prompts/*.md`, date-resolution rules and
the `ExtractedEvent` schema live in `llm/prompt.py` and `models.py` — a
provider adapter never sees them.

## Known trade-off

A Telegram bot cannot read your DMs, so capture is manual: you tap forward on
each invite. The seam in `bot/` keeps a future Telethon listener (which *can*
read everything) an additive change rather than a rewrite.

## Layout

```
src/event_bot/
    config.py    # pydantic-settings, reads .env
    models.py    # ExtractedEvent
    extract.py   # prompt + provider -> ExtractedEvent
    store.py     # sqlite: pending approvals
    main.py      # wiring + PTB startup
    llm/         # base.py (the seam), prompt.py, gemini|claude|openai, registry.py
    prompts/     # system.md, user.md, correction.md — the actual prompt text
    gcal/        # not `calendar/` — that shadows the stdlib module
    bot/         # handlers.py, cards.py
    tools/       # try_extract.py, try_extract_image.py, gcal_check.py
```
