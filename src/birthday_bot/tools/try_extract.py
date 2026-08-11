"""CLI: test extraction with no Telegram and no Calendar.

    uv run python -m birthday_bot.tools.try_extract "sábado tem niver da Ana, 15h"

This is the fast loop for tuning the prompt. Add --fix to also exercise the
✏️ correction path, which is otherwise reachable only through Telegram:

    uv run python -m birthday_bot.tools.try_extract "niver da Ana dia 12/03" \\
        --fix "na verdade é dia 22/03"

Swap providers with the env var:

    LLM_PROVIDER=claude uv run python -m birthday_bot.tools.try_extract "$MSG"
"""

import argparse
import asyncio
import sys

from birthday_bot.config import load_settings
from birthday_bot.extract import extract_event, now_local, reextract_with_correction
from birthday_bot.llm.base import ExtractionError
from birthday_bot.llm.registry import build_provider


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m birthday_bot.tools.try_extract",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "text",
        nargs="+",
        help="a mensagem a extrair (várias palavras viram uma só mensagem)",
    )
    parser.add_argument(
        "--fix",
        metavar="CORREÇÃO",
        help=(
            "re-extrai aplicando esta correção, como o botão ✏️ faz "
            '(ex.: "é dia 22/03")'
        ),
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    text = " ".join(args.text)

    # A missing or unknown provider key raises ValueError with a message that is
    # already user-facing; a traceback would only bury it.
    try:
        settings = load_settings()
        provider = build_provider(settings)
    except ValueError as exc:
        print(f"configuração: {exc}", file=sys.stderr)
        return 2

    now = now_local(settings)

    print(f"provider : {settings.llm_provider}")
    print(f"agora    : {now.isoformat(timespec='seconds')} ({settings.timezone})")
    print(f"mensagem : {text}\n")

    try:
        event = await extract_event(provider, settings, text, now=now)
        print(event.model_dump_json(indent=2))

        if args.fix:
            print(f"\ncorreção : {args.fix}\n")
            event = await reextract_with_correction(
                provider, settings, text, event, args.fix, now=now
            )
            print(event.model_dump_json(indent=2))
    except ExtractionError as exc:
        print(f"falhou: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
