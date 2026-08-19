"""_one_line_place: pure function, no client, no API key needed."""

from event_bot.llm.gemini import _MAX_PLACE_LENGTH, _one_line_place


def test_keeps_only_the_first_line() -> None:
    text = "Fazenda Churrascada, Recife - PE\nFonte: Google Maps"
    assert _one_line_place(text) == "Fazenda Churrascada, Recife - PE"


def test_sem_resultado_bare_returns_none() -> None:
    assert _one_line_place("SEM_RESULTADO") is None


def test_sem_resultado_with_period_returns_none() -> None:
    assert _one_line_place("SEM_RESULTADO.") is None


def test_empty_returns_none() -> None:
    assert _one_line_place("") is None
    assert _one_line_place("   ") is None


def test_none_returns_none() -> None:
    assert _one_line_place(None) is None


def test_overlong_input_is_truncated() -> None:
    long_line = "A" * (_MAX_PLACE_LENGTH + 50)
    result = _one_line_place(long_line)
    assert result is not None
    assert len(result) == _MAX_PLACE_LENGTH
