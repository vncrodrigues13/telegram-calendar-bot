"""The try_extract CLI — argument wiring, not model behavior.

The ✏️ correction path used to be reachable only through Telegram. `--fix`
puts it in the fast loop; these tests pin the plumbing (which prompt builder
runs, in what order, with what carried over) so only the model's answer needs
a human.
"""

from types import ModuleType

import pytest

from event_bot import tools
from event_bot.config import Settings
from event_bot.models import ExtractedEvent
from event_bot.tools import try_extract as tool
from tests.conftest import FakeProvider


@pytest.fixture
def corrected(invite: ExtractedEvent) -> ExtractedEvent:
    return invite.model_copy(update={"start": "2026-03-22T20:00:00"})


async def test_plain_run_extracts_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: Settings,
    invite: ExtractedEvent,
) -> None:
    provider = FakeProvider(invite)
    monkeypatch.setattr(tool, "load_settings", lambda: settings)
    monkeypatch.setattr(tool, "build_provider", lambda _: provider)

    rc = await tool.main(["niver", "da", "Ana"])

    assert rc == 0
    assert len(provider.calls) == 1
    # The words are rejoined into one message, not treated as separate args.
    assert "niver da Ana" in provider.calls[0][1]


async def test_fix_reextracts_with_the_correction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: Settings,
    invite: ExtractedEvent,
    corrected: ExtractedEvent,
) -> None:
    provider = FakeProvider(invite, corrected)
    monkeypatch.setattr(tool, "load_settings", lambda: settings)
    monkeypatch.setattr(tool, "build_provider", lambda _: provider)

    rc = await tool.main(["niver da Ana dia 12/03", "--fix", "é dia 22/03"])

    assert rc == 0
    assert len(provider.calls) == 2

    # Second call is the correction prompt: it carries the original message,
    # the first extraction, and the correction.
    second = provider.calls[1][1]
    assert "niver da Ana dia 12/03" in second
    assert "2026-03-14T15:00:00" in second  # what it got wrong
    assert "é dia 22/03" in second

    out = capsys.readouterr().out
    assert "2026-03-14T15:00:00" in out  # before
    assert "2026-03-22T20:00:00" in out  # after
    assert out.index("2026-03-14") < out.index("2026-03-22")


async def test_config_error_is_a_message_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: Settings,
) -> None:
    """A missing API key is user error; it should read like one."""

    def boom(_: Settings) -> None:
        raise ValueError("LLM_PROVIDER=claude exige ANTHROPIC_API_KEY")

    monkeypatch.setattr(tool, "load_settings", lambda: settings)
    monkeypatch.setattr(tool, "build_provider", boom)

    rc = await tool.main(["teste"])

    assert rc == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


async def test_extraction_failure_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: Settings,
) -> None:
    from event_bot.llm.base import ExtractionError

    class Failing:
        async def extract_json(self, **_: object) -> ExtractedEvent:
            raise ExtractionError("gemini: 400")

    monkeypatch.setattr(tool, "load_settings", lambda: settings)
    monkeypatch.setattr(tool, "build_provider", lambda _: Failing())

    rc = await tool.main(["teste"])

    assert rc == 1
    assert "gemini: 400" in capsys.readouterr().err


def test_module_is_importable_without_argv() -> None:
    """Guards against the tool package growing an import-time side effect."""
    assert isinstance(tools, ModuleType)
    assert callable(tool.main)
