"""build_event_body: timed vs all-day calendar bodies."""

from datetime import datetime

from event_bot.config import Settings
from event_bot.gcal.client import build_description, build_event_body
from event_bot.models import ExtractedEvent
from event_bot.raw_text import image_marker

CAPTURED_AT = datetime(2026, 1, 1, 10, 0)


def test_timed_event_uses_datetime_and_default_duration(settings: Settings) -> None:
    event = ExtractedEvent(
        is_event_invite=True,
        title="Corrida da Ponte",
        start="2026-03-14T15:00:00",
    )
    body = build_event_body(
        event, settings, raw_text="x", forwarded_from=None, captured_at=CAPTURED_AT
    )
    assert body["start"] == {
        "dateTime": "2026-03-14T15:00:00",
        "timeZone": "America/Sao_Paulo",
    }
    assert body["end"] == {
        "dateTime": "2026-03-14T18:00:00",
        "timeZone": "America/Sao_Paulo",
    }


def test_all_day_single_day(settings: Settings) -> None:
    event = ExtractedEvent(
        is_event_invite=True,
        title="Casamento de Ana e João",
        start="2026-12-20T00:00:00",
        all_day=True,
    )
    body = build_event_body(
        event, settings, raw_text="x", forwarded_from=None, captured_at=CAPTURED_AT
    )
    assert body["start"] == {"date": "2026-12-20"}
    # Google's all-day end date is exclusive.
    assert body["end"] == {"date": "2026-12-21"}


def test_all_day_range(settings: Settings) -> None:
    event = ExtractedEvent(
        is_event_invite=True,
        title="Viagem pra Bahia",
        start="2026-01-10T00:00:00",
        end="2026-01-15T00:00:00",
        all_day=True,
    )
    body = build_event_body(
        event, settings, raw_text="x", forwarded_from=None, captured_at=CAPTURED_AT
    )
    assert body["start"] == {"date": "2026-01-10"}
    assert body["end"] == {"date": "2026-01-16"}


def test_summary_comes_from_title(settings: Settings) -> None:
    event = ExtractedEvent(
        is_event_invite=True, title="Night Run", start="2026-09-28T17:00:00"
    )
    body = build_event_body(
        event, settings, raw_text="x", forwarded_from=None, captured_at=CAPTURED_AT
    )
    assert body["summary"] == "Night Run"


def test_display_title_fallback_when_no_title(settings: Settings) -> None:
    event = ExtractedEvent(
        is_event_invite=True, person="Ana", start="2026-09-28T17:00:00"
    )
    body = build_event_body(
        event, settings, raw_text="x", forwarded_from=None, captured_at=CAPTURED_AT
    )
    assert body["summary"] == "Evento de Ana"


def test_personless_invite_builds_with_null_location(
    settings: Settings, personless_invite: ExtractedEvent
) -> None:
    body = build_event_body(
        personless_invite,
        settings,
        raw_text="x",
        forwarded_from=None,
        captured_at=CAPTURED_AT,
    )
    assert body["location"] is None
    assert body["summary"] == "Night Run"


# --- build_description: text vs image source -------------------------------


def test_text_description_quotes_raw_text_verbatim(invite: ExtractedEvent) -> None:
    raw = "Galera, sábado tem niver da Ana! 15h na Rua das Flores 200"
    description = build_description(invite, raw, "Turma do Prédio", CAPTURED_AT)
    assert raw in description
    assert "Encaminhado por: Turma do Prédio" in description
    assert "Capturado em: 2026-01-01 10:00" in description


def test_image_description_is_rebuilt_from_the_extraction(
    invite: ExtractedEvent,
) -> None:
    raw = image_marker("abc123") + " bora?"
    description = build_description(invite, raw, "Tia Lu", CAPTURED_AT)

    assert "[imagem]" in description
    assert "Aniversário de Ana" in description
    assert "Legenda: bora?" in description
    assert "Local: Rua das Flores 200, Pinheiros" in description
    assert "Quando: 14/03/2026 15:00" in description
    assert "Encaminhado por: Tia Lu" in description
    assert "abc123" not in description


def test_image_description_omits_legenda_line_without_a_caption(
    invite: ExtractedEvent,
) -> None:
    raw = image_marker("abc123")
    description = build_description(invite, raw, None, CAPTURED_AT)
    assert "Legenda:" not in description


def test_image_description_all_day_omits_time(
    settings: Settings, all_day_invite: ExtractedEvent
) -> None:
    raw = image_marker("abc123")
    description = build_description(all_day_invite, raw, None, CAPTURED_AT)
    assert "Quando: 20/12/2026" in description
    assert "Quando: 20/12/2026 00:00" not in description
