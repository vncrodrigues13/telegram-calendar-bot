"""CLI: test extraction with no Telegram and no Calendar.

    uv run python -m birthday_bot.tools.try_extract "sábado tem niver da Ana, 15h"

This is the fast loop for tuning the prompt. Swap providers with the env var:

    LLM_PROVIDER=claude uv run python -m birthday_bot.tools.try_extract "$MSG"
"""

import asyncio
import sys

from birthday_bot.config import load_settings
from birthday_bot.extract import extract_event, now_local
from birthday_bot.llm.base import ExtractionError
from birthday_bot.llm.registry import build_provider


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    text = " ".join(sys.argv[1:])
    settings = load_settings()
    provider = build_provider(settings)
    now = now_local(settings)

    print(f"provider : {settings.llm_provider}")
    print(f"agora    : {now.isoformat(timespec='seconds')} ({settings.timezone})")
    print(f"mensagem : {text}\n")

    try:
        event = await extract_event(provider, settings, text, now=now)
    except ExtractionError as exc:
        print(f"falhou: {exc}", file=sys.stderr)
        return 1

    print(event.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
