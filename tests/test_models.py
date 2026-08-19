"""ExtractedEvent: the validators, and the schema contract across providers."""

from datetime import datetime

from event_bot.models import ExtractedEvent


def _format_keys(node: object, path: str = "$") -> list[tuple[str, object]]:
    """Find real `format` *keys*, ignoring the word inside description strings."""
    hits: list[tuple[str, object]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "format":
                hits.append((path, value))
            hits += _format_keys(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            hits += _format_keys(value, f"{path}[{index}]")
    return hits


# --- validators -----------------------------------------------------------


def test_naive_iso_passes_through() -> None:
    event = ExtractedEvent(is_event_invite=True, start="2026-03-14T15:00:00")
    assert event.start == "2026-03-14T15:00:00"
    assert event.start_dt() == datetime(2026, 3, 14, 15, 0)


def test_offsets_are_dropped_not_converted() -> None:
    """We want wall-clock time; the timezone is carried by the event body."""
    for decorated in ("2026-03-14T15:00:00Z", "2026-03-14T15:00:00+00:00"):
        event = ExtractedEvent(is_event_invite=True, start=decorated)
        assert event.start == "2026-03-14T15:00:00"


def test_unparseable_or_empty_timestamps_become_none() -> None:
    """Garbage and 'no date given' both mean the same thing: route to ✏️."""
    for bad in ("sábado que vem", "", "   ", "2026-13-45T99:00:00", 12345):
        event = ExtractedEvent(is_event_invite=True, start=bad)  # type: ignore[arg-type]
        assert event.start is None
        assert event.start_dt() is None


def test_all_day_defaults_false() -> None:
    event = ExtractedEvent(is_event_invite=True, start="2026-03-14T15:00:00")
    assert event.all_day is False


def test_date_only_start_normalizes_to_midnight() -> None:
    event = ExtractedEvent(is_event_invite=True, start="2026-12-20", all_day=True)
    assert event.start == "2026-12-20T00:00:00"
    assert event.start_dt() == datetime(2026, 12, 20, 0, 0)


# --- display_title fallback chain ------------------------------------------


def test_display_title_prefers_title() -> None:
    event = ExtractedEvent(is_event_invite=True, title="Corrida da Ponte", person="Ana")
    assert event.display_title() == "Corrida da Ponte"


def test_display_title_falls_back_to_person() -> None:
    event = ExtractedEvent(is_event_invite=True, person="Ana")
    assert event.display_title() == "Evento de Ana"


def test_display_title_falls_back_to_generic() -> None:
    event = ExtractedEvent(is_event_invite=True)
    assert event.display_title() == "Evento"


# --- the schema contract --------------------------------------------------
#
# `start`/`end` are `str`, not `datetime`, so the JSON schema never carries
# `format: "date-time"` — Gemini's structured-output mode is sensitive to it.
# This test fails loudly if someone "cleans up" the model by switching the
# fields to `datetime`.


def test_gemini_schema_maps_start_to_a_nullable_string() -> None:
    from google.genai import _transformers as transformers

    schema = transformers.t_schema(None, ExtractedEvent)
    start = (schema.properties or {})["start"]
    assert start.format is None
    assert start.nullable is True
