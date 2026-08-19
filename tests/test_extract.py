"""extract_event_from_image: the vision call + best-effort place enrichment."""

from datetime import datetime

import pytest

from event_bot.config import Settings
from event_bot.extract import extract_event_from_image
from event_bot.llm.gemini import GeminiProvider
from event_bot.models import ExtractedEvent

from .conftest import FakeProvider

NOW = datetime(2026, 8, 17, 9, 0, 0)


def test_gemini_provider_has_search_place() -> None:
    """The `getattr(provider, "search_place", None)` lookup in extract.py
    fails silently on a rename — this is the only test that would catch it."""
    assert hasattr(GeminiProvider, "search_place")


async def test_vision_call_gets_the_right_args(settings: Settings) -> None:
    event = ExtractedEvent(is_event_invite=True, title="Mari 39 anos", place=None)
    provider = FakeProvider()
    provider.image_queue.append(event)

    result = await extract_event_from_image(
        provider, settings, b"fake-bytes", "image/png", "bora?", now=NOW
    )

    assert result == event
    assert len(provider.image_calls) == 1
    system, user, image, mime_type = provider.image_calls[0]
    assert image == b"fake-bytes"
    assert mime_type == "image/png"
    assert "bora?" in user


async def test_truthy_place_triggers_search_and_overwrites(settings: Settings) -> None:
    event = ExtractedEvent(is_event_invite=True, place="Fazenda Churrascada")
    provider = FakeProvider(search_place_result="Fazenda Churrascada, Recife - PE")
    provider.image_queue.append(event)

    result = await extract_event_from_image(
        provider, settings, b"x", "image/png", None, now=NOW
    )

    assert provider.search_place_calls == ["Fazenda Churrascada"]
    assert result.place == "Fazenda Churrascada, Recife - PE"


async def test_search_place_returning_none_keeps_original_place(
    settings: Settings,
) -> None:
    event = ExtractedEvent(is_event_invite=True, place="Fazenda Churrascada")
    provider = FakeProvider(search_place_result=None)
    provider.image_queue.append(event)

    result = await extract_event_from_image(
        provider, settings, b"x", "image/png", None, now=NOW
    )

    assert result.place == "Fazenda Churrascada"


async def test_search_place_raising_keeps_original_place(settings: Settings) -> None:
    event = ExtractedEvent(is_event_invite=True, place="Fazenda Churrascada")

    class FlakyProvider(FakeProvider):
        async def search_place(self, place: str) -> str | None:
            raise RuntimeError("timeout")

    provider = FlakyProvider()
    provider.image_queue.append(event)

    result = await extract_event_from_image(
        provider, settings, b"x", "image/png", None, now=NOW
    )

    assert result.place == "Fazenda Churrascada"


async def test_provider_without_search_place_skips_enrichment(
    settings: Settings,
) -> None:
    event = ExtractedEvent(is_event_invite=True, place="Fazenda Churrascada")

    class NoSearchProvider:
        def __init__(self) -> None:
            self.image_calls = []

        async def extract_json_from_image(self, **kwargs) -> ExtractedEvent:
            return event

    provider = NoSearchProvider()
    result = await extract_event_from_image(
        provider, settings, b"x", "image/png", None, now=NOW
    )

    assert result.place == "Fazenda Churrascada"


async def test_null_place_skips_search_entirely(settings: Settings) -> None:
    event = ExtractedEvent(is_event_invite=True, place=None)
    provider = FakeProvider(search_place_result="should never be used")
    provider.image_queue.append(event)

    result = await extract_event_from_image(
        provider, settings, b"x", "image/png", None, now=NOW
    )

    assert result.place is None
    assert provider.search_place_calls == []
