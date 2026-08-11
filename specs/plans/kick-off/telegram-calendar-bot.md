# Telegram → Google Calendar Birthday Bot

## Context

Birthday invitations arrive through Telegram as free-form messages — no fixed template, mixed phrasing, relative dates ("sábado às 15h"), addresses buried in prose. Transcribing each one into Google Calendar by hand is tedious and easy to forget.

This project builds a locally-run Python bot that turns a forwarded Telegram message into a Google Calendar event. An LLM does one narrow job: **extract Person / Place / Time** from unstructured Portuguese text. Everything else — approval, event creation, deduplication — is deterministic code.

Two constraints drive the design:

1. **The AI provider must be swappable.** Gemini is the only provider in use right now — Claude and OpenAI are deferred, not designed out. Their adapters stay in the tree and the seam stays load-bearing, so turning either on is `uv add anthropic` (or `openai`), a key in `.env`, and `LLM_PROVIDER=` — never a rewrite. This means the LLM layer is a narrow interface (`system + user + schema → validated object`) with the prompt and domain logic living outside it.
2. **Nothing lands in the calendar without approval.** The bot replies with the parsed Person/Place/Time and inline ✅ / ✏️ / ❌ buttons. A hallucinated date should never silently occupy a Saturday.

**Decisions already made:** BotFather bot with long polling (no server, no public IP — you forward invites to the bot); approval via inline buttons; pt-BR prompt with DD/MM date ordering; timed events with a 3-hour default duration and reminders 1 day + 2 hours before.

**Known trade-off:** a Telegram bot cannot read your DMs, so capture is manual — you tap forward on each invite. The `MessageSource` seam in `bot/` keeps a future Telethon listener (which *can* read everything automatically) an additive change rather than a rewrite.

---

## Architecture

```
Telegram (you forward) → bot/handlers.py
                              ↓
                     llm/ (provider-agnostic)  ← prompt.py builds pt-BR prompt
                              ↓                   base.py = the swap seam
                     ExtractedEvent (pydantic)
                              ↓
                     approval card + inline buttons
                              ↓ (you tap ✅)
                     gcal/client.py → Google Calendar
                              ↓
                     store.py (sqlite: pending + dedupe)
```

**The swap seam.** `LLMProvider` is deliberately tiny — it knows nothing about birthdays:

```python
class LLMProvider(Protocol):
    async def extract_json(
        self, *, system: str, user: str, schema: type[ModelT]
    ) -> ModelT: ...
```

All Portuguese prompt text, date-resolution rules, and the `ExtractedEvent` schema live in `llm/prompt.py` and `models.py`. Adding a fourth provider means one ~40-line file plus a registry entry.

---

## File layout

```
pyproject.toml            # uv-managed, requires-python = ">=3.13"
.env.example              # every knob, documented
.gitignore                # .env, token.json, credentials.json, *.db
README.md                 # setup: BotFather → Gemini key → Google OAuth
specs/plans/kick-off/     # this document
src/birthday_bot/
    config.py             # pydantic-settings, reads .env
    models.py             # ExtractedEvent
    store.py              # sqlite: pending approvals + dedupe ledger
    main.py               # wiring + PTB application startup
    llm/
        base.py           # LLMProvider Protocol  ← the seam
        prompt.py         # pt-BR system prompt + user prompt builder
        gemini.py         # google-genai  ← the only provider in use
        claude.py         # anthropic — deferred, SDK not installed
        openai.py         # openai — deferred, SDK not installed
        registry.py       # LLM_PROVIDER env → provider instance
    gcal/
        auth.py           # InstalledAppFlow + token.json refresh
        client.py         # create_event()
    bot/
        handlers.py       # message → extract → card; callbacks → create
        cards.py          # renders the approval message + keyboard
    tools/
        try_extract.py    # CLI: test extraction with no Telegram/Calendar
        gcal_check.py     # CLI: verify OAuth, create+delete a test event
tests/
    test_prompt.py        # relative-date resolution, DD/MM ordering
    test_store.py         # dedupe fingerprinting
    test_handlers.py      # full flow against a FakeProvider
```

Note the package is `gcal/`, not `calendar/` — the latter shadows the stdlib module and causes confusing import errors.

---

## Implementation

### 1. `config.py` — pydantic-settings

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    telegram_bot_token: str
    owner_telegram_id: int          # only you may talk to the bot

    llm_provider: Literal["gemini", "claude", "openai"] = "gemini"
    llm_model: str | None = None    # None → per-provider default
    gemini_api_key: str | None = None       # the only one set today
    anthropic_api_key: str | None = None    # deferred — leave unset
    openai_api_key: str | None = None       # deferred — leave unset

    timezone: str = "America/Sao_Paulo"
    calendar_id: str = "primary"
    default_event_hours: int = 3
    reminder_minutes: list[int] = [1440, 120]
    db_path: Path = Path("bot.db")
```

### 2. `models.py` — the extraction schema

```python
class ExtractedEvent(BaseModel):
    is_birthday_invite: bool
    person: str | None        # quem faz aniversário
    place: str | None         # local + endereço, como escrito
    start: str | None         # "2026-03-14T15:00:00" — plain ISO, no tz
    end: str | None
    confidence: float         # 0..1
    notes: str | None         # ambiguidades ("ano não informado")
```

**`start`/`end` are `str`, not `datetime`, on purpose.** A `datetime` field emits `format: "date-time"` in the JSON schema; OpenAI's strict structured-output mode rejects `format`, and the three providers disagree on how they honor it. Emitting a plain string and parsing it ourselves with `datetime.fromisoformat` (validated in a `field_validator`) behaves identically everywhere.

### 3. `llm/prompt.py` — where all the pt-BR logic lives

System prompt establishes the extraction task in Portuguese and pins down the ambiguities that actually bite:

- **Date ordering:** `12/03` is 12 de março, never December 3.
- **Relative dates:** resolve "sábado", "amanhã", "dia 20" against the `now` passed in. If the resolved date is in the past, take the next occurrence.
- **Year inference:** when the year is absent, choose the year that puts the date in the future.
- **Time:** `15h`, `15hs`, `3 da tarde`, `19:30` all normalize to 24-hour.
- **Person:** the *aniversariante*, not the sender — "vem no niver da Ana" → `Ana`. Distinguish from the host when they differ.
- **Not an invite:** if the text isn't a birthday invitation, set `is_birthday_invite: false` and leave the rest null rather than guessing.
- **Never invent:** absent info is `null`; note the gap in `notes`.

The user prompt carries `now` (ISO + weekday name in Portuguese), the timezone, and the raw message text delimited so instructions inside a forwarded message can't be read as commands.

`build_correction_prompt(original_text, previous, correction)` handles the ✏️ path — re-extracts with the user's correction applied.

### 4. `llm/` — the adapters

Each is thin. Defaults chosen for a cheap, low-reasoning extraction task; all overridable via `LLM_MODEL`.

| Provider | Status | Default model | Structured-output mechanism |
|---|---|---|---|
| `gemini` | **in use** | `gemini-3.6-flash` | `config={"response_mime_type": "application/json", "response_schema": Model}` → `resp.parsed` |
| `claude` | deferred | `claude-haiku-4-5` | `client.messages.parse(..., output_format=Model)` → `resp.parsed_output` |
| `openai` | deferred | `gpt-4.1-mini` | `client.responses.parse(..., text_format=Model)` → `resp.output_parsed` |

The Gemini default is `gemini-3.6-flash`, not the `gemini-2.5-flash` this plan originally named: Google has closed 2.5-flash to new API keys, so it fails on a freshly created project.

All three use the async client and are constructed lazily — the `import` sits inside `__init__`, so only the selected provider's SDK is touched at runtime. That laziness is what lets the two deferred adapters stay in the tree with their SDKs uninstalled: `anthropic` and `openai` are **not** project dependencies, and a Gemini run never notices. `registry.py` maps the env value to a constructor and raises a clear error if the matching API key is unset.

Because the key check runs before the import, the common deferred-provider mistake (`LLM_PROVIDER=claude`, no key) still produces the clear Portuguese error. Setting a key *without* reinstalling the SDK is the one path that falls through to a bare `ModuleNotFoundError`.

Each adapter wraps SDK exceptions in a shared `ExtractionError` so `handlers.py` has one thing to catch.

### 5. `store.py` — sqlite, stdlib `sqlite3`

```sql
CREATE TABLE pending (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER, card_message_id INTEGER,
    raw_text TEXT, forwarded_from TEXT,
    extraction_json TEXT, created_at TEXT
);
CREATE TABLE created (
    fingerprint TEXT PRIMARY KEY,   -- sha256 of normalized raw_text
    event_id TEXT, html_link TEXT, created_at TEXT
);
```

The `created` table means forwarding the same invite twice (easy to do in a busy group) surfaces "já criei esse evento" with a link, instead of a duplicate. All DB calls go through `asyncio.to_thread` — `sqlite3` is blocking.

### 6. `gcal/` — OAuth + event creation

`auth.py`: load `token.json` if present, refresh when expired, otherwise run `InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES).run_local_server(port=0)` which opens a browser once. Scope is `.../auth/calendar.events` — narrower than full calendar access.

`client.py` builds the event body:

```python
{
  "summary": f"Aniversário de {person}",
  "location": place,
  "description": description,     # see below
  "start": {"dateTime": start_iso, "timeZone": settings.timezone},
  "end":   {"dateTime": end_iso,   "timeZone": settings.timezone},
  "reminders": {"useDefault": False, "overrides": [
      {"method": "popup", "minutes": m} for m in settings.reminder_minutes
  ]},
}
```

**The description carries the full context** — the verbatim original message, who forwarded it, and any extraction `notes`:

```
<original message text, unmodified>

——
Encaminhado por: <forward origin>
Capturado em: 2026-08-08 14:32
Observações: ano não informado, assumido 2026
```

End time is `start + DEFAULT_EVENT_HOURS` when the message gives no end. Google API calls are blocking → wrapped in `asyncio.to_thread`.

### 7. `bot/handlers.py` — the flow

- `MessageHandler(filters.User(OWNER_ID) & (filters.TEXT | filters.CAPTION), on_message)`. The owner filter means a stranger who finds your bot gets nothing.
- Pull text from `msg.text or msg.caption`; read forward metadata from `msg.forward_origin` (PTB v20+ replaced the old `forward_from` fields with a `MessageOrigin` union — handle `MessageOriginUser`, `MessageOriginHiddenUser`, and `MessageOriginChat`).
- Check the dedupe fingerprint first — short-circuit with the existing event link if seen.
- Send "🔎 analisando…", call the provider, edit that message into the card.
- `is_birthday_invite: false` → reply saying so, with a "criar mesmo assim" button for the occasional miss.
- Card + `InlineKeyboardMarkup` with callback data `ok:<pending_id>` / `edit:<pending_id>` / `no:<pending_id>` (IDs, not payloads — Telegram caps callback_data at 64 bytes).
- `CallbackQueryHandler` per prefix. ✅ creates the event and edits the card to show the link; ❌ deletes the pending row and edits to "descartado"; ✏️ sets `context.user_data["editing"] = pending_id` and asks for a correction — the next message routes to the correction prompt and re-renders.
- `error_handler` reports failures back to you in-chat rather than dying silently in the terminal.

Missing `start` blocks creation — the ✅ button is replaced with a prompt to supply the date via ✏️. An event with no time is worse than no event.

### 8. `main.py`

Build settings → provider → store → `Application.builder().token(...).build()` → register handlers → `run_polling(allowed_updates=["message", "callback_query"])`. PTB's `run_polling` owns the event loop; nothing else needs an `asyncio.run`.

---

## Verification

Run these in order — each one works before the next is needed.

**1. Install**
```bash
uv sync && uv run python -c "import telegram, google.genai, googleapiclient; print('ok')"
```

**2. Extraction alone — no Telegram, no Calendar.** This is the fast loop for tuning the prompt:
```bash
uv run python -m birthday_bot.tools.try_extract \
  "Galera, sábado tem niver da Ana! 15h na Rua das Flores 200, Pinheiros. Traz bebida 🎂"
```
Expect `person: "Ana"`, `place` with the street, `start` on the *next* Saturday at 15:00, `is_birthday_invite: true`. Also try a non-invite ("bom dia pessoal") → `is_birthday_invite: false`, and a numeric date ("dia 12/03 às 20h") → March 12, not December 3.

**3. Provider swap — deferred.** Only Gemini is configured, so there is nothing to compare against yet:
```bash
LLM_PROVIDER=gemini uv run python -m birthday_bot.tools.try_extract "$MSG"
```
What *is* verifiable today is that the seam refuses early when a key is missing, in `registry.py` rather than deep inside an SDK:
```bash
LLM_PROVIDER=claude uv run python -m birthday_bot.tools.try_extract "$MSG"
# → ValueError: LLM_PROVIDER=claude exige ANTHROPIC_API_KEY, que não está definido no .env
```
This currently surfaces as an uncaught traceback. The message is right and the failure is early, but `try_extract` could catch `ValueError` and print it plainly — a rough edge, not a defect.

When a second provider is eventually funded, add its key to `.env` and re-run the same command with `LLM_PROVIDER=` switched: same input, same output shape. That comparison is the real test of constraint #1 and remains **unrun**.

Note this step relies on environment variables overriding `.env` — pydantic-settings gives the OS environment precedence, which is what makes the one-line swap work.

**4. Google Calendar auth + write.** Opens a browser once, writes `token.json`, then creates and immediately deletes a test event:
```bash
uv run python -m birthday_bot.tools.gcal_check
```

**5. Unit tests** — `uv run pytest`. Covers relative-date resolution and DD/MM ordering (frozen `now`), dedupe fingerprinting, and the full handler flow against a `FakeProvider` returning a canned `ExtractedEvent` (no network, no API keys).

**6. End to end.** `uv run python -m birthday_bot.main`, then forward a real invite from Telegram. Expect the card within a few seconds, tap ✅, confirm the event appears in Google Calendar with the original message in the description. Forward the same message again to confirm dedupe fires.

---

## Setup you'll need to do (I can't do these)

1. **Bot token** — @BotFather → `/newbot` → copy the token.
2. **Your Telegram user ID** — message @userinfobot; this locks the bot to you.
3. **Gemini key** — [aistudio.google.com](https://aistudio.google.com) → Get API key.
4. **Google Calendar OAuth** — Cloud Console → new project → enable Calendar API → OAuth consent screen (External, add yourself as a test user) → Credentials → OAuth client ID → **Desktop app** → download as `credentials.json` in the project root.

I'll write `.env.example` and a README walking through each of these with the exact clicks.
