"""ExtractedEvent: the validators, and the schema contract across providers."""

from datetime import datetime

import pytest

from birthday_bot.models import ExtractedEvent


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
    event = ExtractedEvent(is_birthday_invite=True, start="2026-03-14T15:00:00")
    assert event.start == "2026-03-14T15:00:00"
    assert event.start_dt() == datetime(2026, 3, 14, 15, 0)


def test_offsets_are_dropped_not_converted() -> None:
    """We want wall-clock time; the timezone is carried by the event body."""
    for decorated in ("2026-03-14T15:00:00Z", "2026-03-14T15:00:00+00:00"):
        event = ExtractedEvent(is_birthday_invite=True, start=decorated)
        assert event.start == "2026-03-14T15:00:00"


def test_unparseable_or_empty_timestamps_become_none() -> None:
    """Garbage and 'no date given' both mean the same thing: route to ✏️."""
    for bad in ("sábado que vem", "", "   ", "2026-13-45T99:00:00", 12345):
        event = ExtractedEvent(is_birthday_invite=True, start=bad)  # type: ignore[arg-type]
        assert event.start is None
        assert event.start_dt() is None


# --- the schema contract --------------------------------------------------
#
# `start`/`end` are `str`, not `datetime`, so the JSON schema never carries
# `format: "date-time"` — OpenAI's strict mode rejects `format`, and the three
# providers disagree on how they honor it. These tests fail loudly if someone
# "cleans up" the model by switching the fields to `datetime`.
#
# They reach into each SDK's private schema-conversion internals on purpose:
# it's the only way to check this offline, with no API key and no network. If
# one breaks after an SDK upgrade, the import path moved — find the new one
# rather than deleting the test. The behaviour it guards is real.


def test_openai_strict_schema_has_no_format_key() -> None:
    # openai is no longer a project dependency (provider deferred). The guard
    # stays so it reactivates by itself if the SDK is ever reinstalled.
    to_strict_json_schema = pytest.importorskip(
        "openai.lib._pydantic", reason="openai not installed — provider deferred"
    ).to_strict_json_schema

    schema = to_strict_json_schema(ExtractedEvent)
    assert _format_keys(schema) == []
    assert schema["additionalProperties"] is False
    assert schema["properties"]["start"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]


def test_anthropic_schema_has_no_format_key() -> None:
    # See the note above: anthropic is deferred, so this skips until reinstalled.
    transform_schema = pytest.importorskip(
        "anthropic.lib._parse._transform",
        reason="anthropic not installed — provider deferred",
    ).transform_schema
    from pydantic import TypeAdapter

    schema = transform_schema(TypeAdapter(ExtractedEvent).json_schema())
    assert _format_keys(schema) == []


def test_gemini_schema_maps_start_to_a_nullable_string() -> None:
    from google.genai import _transformers as transformers

    schema = transformers.t_schema(None, ExtractedEvent)
    start = (schema.properties or {})["start"]
    assert start.format is None
    assert start.nullable is True
