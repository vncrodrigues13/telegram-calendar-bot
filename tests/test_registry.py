"""LLM_PROVIDER -> provider, and the three ways it can go wrong.

Every failure here is a config mistake made minutes before the bot is meant to
run, so each one has to say what to change. The messages are the contract.
"""

import importlib.util
import sys
from types import ModuleType

import pytest

from event_bot.config import Settings
from event_bot.llm.registry import build_provider

_HAS_ANTHROPIC = importlib.util.find_spec("anthropic") is not None


def test_missing_key_names_the_env_var(settings: Settings) -> None:
    claude = settings.model_copy(update={"llm_provider": "claude"})
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_provider(claude)


@pytest.mark.skipif(_HAS_ANTHROPIC, reason="anthropic is installed")
def test_missing_sdk_says_how_to_install_it(settings: Settings) -> None:
    """The deferred providers need `uv add`, not just a key — say so."""
    claude = settings.model_copy(
        update={"llm_provider": "claude", "anthropic_api_key": "sk-test"}
    )
    with pytest.raises(ValueError, match="uv add anthropic"):
        build_provider(claude)


def test_an_unrelated_missing_module_keeps_its_traceback(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """A broken install is a bug, not a config mistake — don't dress it up."""
    broken = ModuleType("event_bot.llm.gemini")

    def __getattr__(name: str) -> object:
        raise ModuleNotFoundError("No module named 'httpx'", name="httpx")

    broken.__getattr__ = __getattr__  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "event_bot.llm.gemini", broken)

    with pytest.raises(ModuleNotFoundError, match="httpx"):
        build_provider(settings)
