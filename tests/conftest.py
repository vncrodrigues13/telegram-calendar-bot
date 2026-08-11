from pathlib import Path

import pytest

from birthday_bot.config import Settings
from birthday_bot.llm.base import ModelT
from birthday_bot.models import ExtractedEvent
from birthday_bot.store import Store


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

    Records the prompts it was called with so tests can assert on them.
    """

    def __init__(self, *events: ExtractedEvent) -> None:
        self.queue = list(events)
        self.calls: list[tuple[str, str]] = []

    async def extract_json(
        self, *, system: str, user: str, schema: type[ModelT]
    ) -> ModelT:
        self.calls.append((system, user))
        return self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]


@pytest.fixture
def invite() -> ExtractedEvent:
    return ExtractedEvent(
        is_birthday_invite=True,
        person="Ana",
        place="Rua das Flores 200, Pinheiros",
        start="2026-03-14T15:00:00",
        confidence=0.9,
    )
