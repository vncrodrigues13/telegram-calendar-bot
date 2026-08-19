# CLAUDE.md

## Linear

Linear project reference for this repository: `telegram-bot-43f68fcbee65`
(https://linear.app/vncrodrigues13/project/telegram-bot-43f68fcbee65). Use this
slug when looking up or creating Linear issues, projects, and documents for this
work.

## Running the project

Setup (`.env`, `credentials.json`, `token.json`) is documented in README.md.

```bash
uv sync
uv run python -m event_bot.main
```

Then forward a calendar-invite-style message to the bot on Telegram. It only
responds to the Telegram user ID set as `OWNER_TELEGRAM_ID` in `.env`, and it
long-polls Telegram until killed (Ctrl+C).

Lighter-weight tools for testing parts in isolation:

```bash
# extraction only — no Telegram, no Calendar
uv run python -m event_bot.tools.try_extract "sábado tem niver da Ana! 15h na Rua das Flores 200"

# image extraction only — no Telegram, no Calendar
uv run python -m event_bot.tools.try_extract_image specs/plans/image-extractor/image.png

# Google Calendar OAuth check — opens a browser, creates/deletes a test event
uv run python -m event_bot.tools.gcal_check

# test suite (no network/keys needed)
uv run pytest
```
