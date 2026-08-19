from pathlib import Path

import pytest

from event_bot.config import Settings
from event_bot.llm.base import ModelT
from event_bot.models import ExtractedEvent
from event_bot.store import Store


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        telegram_bot_token="test-token",
        owner_telegram_id=42,
        llm_provider="gemini",
        gemini_api_key="test-key",
        timezone="America/Sao_Paulo",
        db_path=tmp_path / "test.db",
    )


@pytest.fixture
async def store(settings: Settings) -> Store:
    store = Store(settings.db_path)
    await store.init()
    return store


class FakeProvider:
    """Canned extraction — no network, no API keys.

    Records the prompts it was called with so tests can assert on them. The
    image path has its own queue: a correction-after-image test exercises
    `extract_json_from_image` *and* `extract_json` in one run, which a single
    shared queue cannot serve.
    """

    def __init__(self, *events: ExtractedEvent, search_place_result: str | None = None) -> None:
        self.queue = list(events)
        self.image_queue: list[ExtractedEvent] = []
        self.calls: list[tuple[str, str]] = []
        self.image_calls: list[tuple[str, str, bytes, str]] = []
        self.search_place_calls: list[str] = []
        self._search_place_result = search_place_result

    async def extract_json(
        self, *, system: str, user: str, schema: type[ModelT]
    ) -> ModelT:
        self.calls.append((system, user))
        return self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]

    async def extract_json_from_image(
        self,
        *,
        system: str,
        user: str,
        image: bytes,
        mime_type: str,
        schema: type[ModelT],
    ) -> ModelT:
        self.image_calls.append((system, user, image, mime_type))
        return (
            self.image_queue.pop(0)
            if len(self.image_queue) > 1
            else self.image_queue[0]
        )

    async def search_place(self, place: str) -> str | None:
        self.search_place_calls.append(place)
        return self._search_place_result


@pytest.fixture
def invite() -> ExtractedEvent:
    return ExtractedEvent(
        is_event_invite=True,
        title="Aniversário de Ana",
        event_type="aniversário",
        person="Ana",
        place="Rua das Flores 200, Pinheiros",
        start="2026-03-14T15:00:00",
        confidence=0.9,
    )


@pytest.fixture
def all_day_invite() -> ExtractedEvent:
    return ExtractedEvent(
        is_event_invite=True,
        title="Casamento de Ana e João",
        event_type="casamento",
        person="Ana e João",
        place="Fazenda Vista Alegre",
        start="2026-12-20T00:00:00",
        all_day=True,
        confidence=0.9,
    )


@pytest.fixture
def personless_invite() -> ExtractedEvent:
    return ExtractedEvent(
        is_event_invite=True,
        title="Night Run",
        event_type="corrida",
        person=None,
        place=None,
        start="2026-09-28T17:00:00",
        confidence=0.9,
    )
