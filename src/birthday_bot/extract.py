"""Prompt + provider -> ExtractedEvent. The one place the two meet."""

from datetime import datetime
from zoneinfo import ZoneInfo

from birthday_bot.config import Settings
from birthday_bot.llm.base import LLMProvider
from birthday_bot.llm.prompt import (
    build_correction_prompt,
    build_system_prompt,
    build_user_prompt,
)
from birthday_bot.models import ExtractedEvent


def now_local(settings: Settings) -> datetime:
    """Wall-clock 'now' in the configured timezone, naive.

    Naive because every timestamp in this system is local wall-clock; Google
    Calendar is told the timezone separately via the event body.
    """
    return datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None)


async def extract_event(
    provider: LLMProvider,
    settings: Settings,
    text: str,
    now: datetime | None = None,
) -> ExtractedEvent:
    return await provider.extract_json(
        system=build_system_prompt(),
        user=build_user_prompt(
            text, now or now_local(settings), settings.timezone
        ),
        schema=ExtractedEvent,
    )


async def reextract_with_correction(
    provider: LLMProvider,
    settings: Settings,
    original_text: str,
    previous: ExtractedEvent,
    correction: str,
    now: datetime | None = None,
) -> ExtractedEvent:
    return await provider.extract_json(
        system=build_system_prompt(),
        user=build_correction_prompt(
            original_text,
            previous,
            correction,
            now or now_local(settings),
            settings.timezone,
        ),
        schema=ExtractedEvent,
    )
