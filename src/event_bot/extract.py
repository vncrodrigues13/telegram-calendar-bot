"""Prompt + provider -> ExtractedEvent. The one place the two meet."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from event_bot.config import Settings
from event_bot.llm.base import LLMProvider
from event_bot.llm.prompt import (
    build_correction_prompt,
    build_system_prompt,
    build_system_prompt_image,
    build_user_prompt,
    build_user_prompt_image,
)
from event_bot.models import ExtractedEvent

logger = logging.getLogger(__name__)


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


async def extract_event_from_image(
    provider: LLMProvider,
    settings: Settings,
    image: bytes,
    mime_type: str,
    caption: str | None = None,
    now: datetime | None = None,
) -> ExtractedEvent:
    now = now or now_local(settings)
    event = await provider.extract_json_from_image(
        system=build_system_prompt_image(),
        user=build_user_prompt_image(caption, now, settings.timezone),
        image=image,
        mime_type=mime_type,
        schema=ExtractedEvent,
    )

    if not event.place:
        return event

    search_place = getattr(provider, "search_place", None)
    if search_place is None:
        logger.debug("provider has no search_place; skipping place enrichment")
        return event

    try:
        enriched = await search_place(event.place)
    except Exception:  # noqa: BLE001 — enrichment must never break extraction
        logger.warning("place enrichment failed", exc_info=True)
        return event

    return event.model_copy(update={"place": enriched}) if enriched else event


async def reextract_with_correction(
    provider: LLMProvider,
    settings: Settings,
    original_text: str | None,
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
