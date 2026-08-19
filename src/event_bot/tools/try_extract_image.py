"""CLI: test image extraction with no Telegram and no Calendar.

    uv run python -m event_bot.tools.try_extract_image specs/plans/image-extractor/image.png

Add --caption to pass a Telegram-style caption alongside the image, and --fix
to also exercise the ✏️ correction path:

    uv run python -m event_bot.tools.try_extract_image image.png \\
        --caption "bora?" --fix "é dia 22/08"

Swap providers with the env var (only gemini has vision today; claude/openai
raise a clear error):

    LLM_PROVIDER=claude uv run python -m event_bot.tools.try_extract_image image.png
"""

import argparse
import asyncio
import mimetypes
import sys
from pathlib import Path

from event_bot.config import load_settings
from event_bot.extract import (
    extract_event_from_image,
    now_local,
    reextract_with_correction,
)
from event_bot.llm.base import ExtractionError
from event_bot.llm.registry import build_provider


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m event_bot.tools.try_extract_image",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", help="caminho para o arquivo de imagem")
    parser.add_argument("--caption", help="legenda opcional, como no Telegram")
    parser.add_argument(
        "--fix",
        metavar="CORREÇÃO",
        help="re-extrai aplicando esta correção, como o botão ✏️ faz",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    image_path = Path(args.image)

    try:
        settings = load_settings()
        provider = build_provider(settings)
    except ValueError as exc:
        print(f"configuração: {exc}", file=sys.stderr)
        return 2

    image_bytes = image_path.read_bytes()
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    now = now_local(settings)

    print(f"provider : {settings.llm_provider}")
    print(f"agora    : {now.isoformat(timespec='seconds')} ({settings.timezone})")
    print(f"imagem   : {image_path} ({mime_type})")
    if args.caption:
        print(f"legenda  : {args.caption}")
    print()

    try:
        event = await extract_event_from_image(
            provider, settings, image_bytes, mime_type, args.caption, now=now
        )
        print(event.model_dump_json(indent=2))

        if args.fix:
            print(f"\ncorreção : {args.fix}\n")
            # `None` matches what handlers pass for a captionless image: the
            # source-free correction prompt.
            event = await reextract_with_correction(
                provider, settings, args.caption, event, args.fix, now=now
            )
            print(event.model_dump_json(indent=2))
    except ExtractionError as exc:
        print(f"falhou: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
