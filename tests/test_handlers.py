"""Full flow against a FakeProvider. No network, no API keys."""

from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

import pytest

from birthday_bot.bot import cards, handlers
from birthday_bot.config import Settings
from birthday_bot.gcal.client import CreatedCalendarEvent, build_event_body
from birthday_bot.llm.base import ExtractionError
from birthday_bot.models import ExtractedEvent
from birthday_bot.store import Store

from .conftest import FakeProvider


# --- test doubles ---------------------------------------------------------


@dataclass
class FakeMessage:
    text: str | None = None
    caption: str | None = None
    chat_id: int = 7
    message_id: int = 1
    forward_origin: object | None = None
    replies: list["FakeMessage"] = field(default_factory=list)
    edits: list[tuple[str, object]] = field(default_factory=list)

    async def reply_text(self, text: str, **kwargs) -> "FakeMessage":
        reply = FakeMessage(text=text, chat_id=self.chat_id, message_id=self.message_id + 100)
        self.replies.append(reply)
        return reply

    async def edit_text(self, text: str, reply_markup=None, **kwargs) -> None:
        self.edits.append((text, reply_markup))

    @property
    def last_edit(self) -> tuple[str, object]:
        return self.edits[-1]


@dataclass
class FakeQuery:
    data: str
    message: FakeMessage
    answered: bool = False
    edits: list[tuple[str, object]] = field(default_factory=list)

    async def answer(self) -> None:
        self.answered = True

    async def edit_message_text(self, text: str, reply_markup=None, **kwargs) -> None:
        self.edits.append((text, reply_markup))

    @property
    def last_edit(self) -> tuple[str, object]:
        return self.edits[-1]


class FakeCalendar:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.created: list[dict] = []

    async def create_event(
        self, event, raw_text, forwarded_from, captured_at
    ) -> CreatedCalendarEvent:
        if self.fail is not None:
            raise self.fail
        self.created.append(
            {
                "event": event,
                "raw_text": raw_text,
                "forwarded_from": forwarded_from,
                "captured_at": captured_at,
            }
        )
        return CreatedCalendarEvent(
            event_id="evt_1", html_link="https://calendar.example/evt_1"
        )


def make_context(
    settings: Settings, store: Store, provider, calendar
) -> SimpleNamespace:
    return SimpleNamespace(
        application=SimpleNamespace(
            bot_data={
                "settings": settings,
                "store": store,
                "provider": provider,
                "calendar": calendar,
            }
        ),
        user_data={},
        bot=None,
        error=None,
    )


def make_update(message: FakeMessage | None = None, query: FakeQuery | None = None):
    return SimpleNamespace(effective_message=message, callback_query=query)


def callback_data(reply_markup) -> list[str]:
    return [b.callback_data for row in reply_markup.inline_keyboard for b in row]


# --- the happy path -------------------------------------------------------


async def test_message_becomes_a_card_and_a_pending_row(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    provider = FakeProvider(invite)
    context = make_context(settings, store, provider, FakeCalendar())
    message = FakeMessage(text="Sábado tem niver da Ana, 15h na Rua das Flores 200")

    await handlers.on_message(make_update(message=message), context)

    status = message.replies[0]
    assert status.text == "🔎 analisando…"
    card_text, keyboard = status.last_edit
    assert "Ana" in card_text
    assert "Rua das Flores 200" in card_text
    assert callback_data(keyboard) == ["ok:1", "edit:1", "no:1"]

    pending = await store.get_pending(1)
    assert pending is not None
    assert pending.extraction.person == "Ana"


async def test_confirm_creates_the_event_and_records_the_fingerprint(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    calendar = FakeCalendar()
    context = make_context(settings, store, FakeProvider(invite), calendar)
    raw = "Sábado tem niver da Ana, 15h"
    pending_id = await store.add_pending(7, raw, "Grupo X", invite)

    query = FakeQuery(data=f"ok:{pending_id}", message=FakeMessage())
    await handlers.on_confirm(make_update(query=query), context)

    assert query.answered
    assert len(calendar.created) == 1
    assert calendar.created[0]["raw_text"] == raw
    assert calendar.created[0]["forwarded_from"] == "Grupo X"

    text, _ = query.last_edit
    assert "Evento criado" in text
    assert "https://calendar.example/evt_1" in text

    # The pending row is gone and the dedupe ledger now knows this invite.
    assert await store.get_pending(pending_id) is None
    created = await store.find_created(raw)
    assert created is not None and created.event_id == "evt_1"


async def test_reforwarding_the_same_invite_short_circuits(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    raw = "Sábado tem niver da Ana, 15h"
    await store.record_created(raw, "evt_1", "https://calendar.example/evt_1")

    provider = FakeProvider(invite)
    context = make_context(settings, store, provider, FakeCalendar())
    message = FakeMessage(text=f"  {raw.upper()}  ")  # re-forward, different casing

    await handlers.on_message(make_update(message=message), context)

    assert "Já criei esse evento" in message.replies[0].text
    assert provider.calls == []  # the LLM was never called


# --- guard rails ----------------------------------------------------------


async def test_missing_start_withholds_the_create_button(
    settings: Settings, store: Store
) -> None:
    """An event with no time is worse than no event."""
    no_time = ExtractedEvent(
        is_birthday_invite=True,
        person="Ana",
        place="Casa da Ana",
        start=None,
        notes="horário não informado",
    )
    context = make_context(settings, store, FakeProvider(no_time), FakeCalendar())
    message = FakeMessage(text="Niver da Ana lá em casa, apareçam!")

    await handlers.on_message(make_update(message=message), context)

    card_text, keyboard = message.replies[0].last_edit
    assert callback_data(keyboard) == ["edit:1", "no:1"]  # no ✅
    assert "Use ✏️" in card_text


async def test_confirm_refuses_when_start_is_still_missing(
    settings: Settings, store: Store
) -> None:
    no_time = ExtractedEvent(is_birthday_invite=True, person="Ana", start=None)
    calendar = FakeCalendar()
    context = make_context(settings, store, FakeProvider(no_time), calendar)
    pending_id = await store.add_pending(7, "texto", None, no_time)

    query = FakeQuery(data=f"ok:{pending_id}", message=FakeMessage())
    await handlers.on_confirm(make_update(query=query), context)

    assert calendar.created == []
    assert "falta o horário" in query.last_edit[0]


async def test_non_invite_offers_the_escape_hatch(
    settings: Settings, store: Store
) -> None:
    not_invite = ExtractedEvent(is_birthday_invite=False)
    context = make_context(settings, store, FakeProvider(not_invite), FakeCalendar())
    message = FakeMessage(text="bom dia pessoal")

    await handlers.on_message(make_update(message=message), context)

    card_text, keyboard = message.replies[0].last_edit
    assert "não parece um convite" in card_text
    assert callback_data(keyboard) == ["force:1", "no:1"]


async def test_force_turns_a_non_invite_into_a_normal_card(
    settings: Settings, store: Store
) -> None:
    not_invite = ExtractedEvent(
        is_birthday_invite=False, person="Ana", start="2026-03-14T15:00:00"
    )
    context = make_context(settings, store, FakeProvider(not_invite), FakeCalendar())
    pending_id = await store.add_pending(7, "texto", None, not_invite)

    card_message = FakeMessage()
    query = FakeQuery(data=f"force:{pending_id}", message=card_message)
    await handlers.on_force(make_update(query=query), context)

    _, keyboard = card_message.last_edit
    assert callback_data(keyboard) == [f"ok:{pending_id}", f"edit:{pending_id}", f"no:{pending_id}"]
    pending = await store.get_pending(pending_id)
    assert pending is not None and pending.extraction.is_birthday_invite


async def test_extraction_failure_is_reported_in_chat(
    settings: Settings, store: Store
) -> None:
    class Boom:
        async def extract_json(self, **kwargs):
            raise ExtractionError("gemini: quota exceeded")

    context = make_context(settings, store, Boom(), FakeCalendar())
    message = FakeMessage(text="niver da Ana")

    await handlers.on_message(make_update(message=message), context)

    text, _ = message.replies[0].last_edit
    assert "Não consegui analisar" in text
    assert "quota exceeded" in text


async def test_calendar_failure_is_reported_in_chat(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    calendar = FakeCalendar(fail=RuntimeError("403 insufficient scope"))
    context = make_context(settings, store, FakeProvider(invite), calendar)
    pending_id = await store.add_pending(7, "texto", None, invite)

    query = FakeQuery(data=f"ok:{pending_id}", message=FakeMessage())
    await handlers.on_confirm(make_update(query=query), context)

    text, _ = query.last_edit
    assert "Falhei ao criar o evento" in text
    assert "insufficient scope" in text
    # Nothing was recorded, so a retry is still possible.
    assert await store.get_pending(pending_id) is not None


# --- the ✏️ correction path -----------------------------------------------


async def test_edit_then_correction_reextracts_and_rerenders(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    # The pending row is seeded directly, so the only extraction call in this
    # test is the re-extraction triggered by the correction.
    corrected = invite.model_copy(update={"person": "Bia"})
    provider = FakeProvider(corrected)
    context = make_context(settings, store, provider, FakeCalendar())
    pending_id = await store.add_pending(7, "niver da Ana", None, invite)

    # ✏️ arms the correction state...
    query = FakeQuery(data=f"edit:{pending_id}", message=FakeMessage())
    await handlers.on_edit(make_update(query=query), context)
    assert context.user_data[handlers.EDITING_KEY] == pending_id

    # ...and the next message is routed to the correction prompt, not treated
    # as a brand-new invite.
    correction = FakeMessage(text="na verdade é da Bia")
    await handlers.on_message(make_update(message=correction), context)

    card_text, _ = correction.replies[0].last_edit
    assert "Bia" in card_text
    assert handlers.EDITING_KEY not in context.user_data
    assert "na verdade é da Bia" in provider.calls[-1][1]

    pending = await store.get_pending(pending_id)
    assert pending is not None and pending.extraction.person == "Bia"
    # Only one pending row exists — the correction did not create a second.
    assert await store.get_pending(pending_id + 1) is None


async def test_discard_removes_the_pending_row(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    context = make_context(settings, store, FakeProvider(invite), FakeCalendar())
    pending_id = await store.add_pending(7, "texto", None, invite)

    query = FakeQuery(data=f"no:{pending_id}", message=FakeMessage())
    await handlers.on_discard(make_update(query=query), context)

    assert "Descartado" in query.last_edit[0]
    assert await store.get_pending(pending_id) is None


# --- forward origin -------------------------------------------------------


def test_describe_origin_handles_each_message_origin_variant() -> None:
    from telegram import (
        MessageOriginChannel,
        MessageOriginChat,
        MessageOriginHiddenUser,
        MessageOriginUser,
    )

    now = datetime(2026, 8, 8, 12, 0)
    user = SimpleNamespace(full_name="Ana Silva")
    chat = SimpleNamespace(title="Turma do Prédio", full_name=None)

    cases = [
        (MessageOriginUser(date=now, sender_user=user), "Ana Silva"),
        (
            MessageOriginHiddenUser(date=now, sender_user_name="Alguém"),
            "Alguém",
        ),
        (MessageOriginChat(date=now, sender_chat=chat), "Turma do Prédio"),
        (
            MessageOriginChannel(date=now, chat=chat, message_id=5),
            "Turma do Prédio",
        ),
        (None, None),
    ]
    for origin, expected in cases:
        assert handlers.describe_origin(FakeMessage(forward_origin=origin)) == expected


# --- the calendar event body ---------------------------------------------


def test_event_body_carries_the_full_context(
    settings: Settings, invite: ExtractedEvent
) -> None:
    raw = "Galera, sábado tem niver da Ana! 15h na Rua das Flores 200"
    body = build_event_body(
        invite.model_copy(update={"notes": "ano não informado, assumido 2026"}),
        settings,
        raw_text=raw,
        forwarded_from="Turma do Prédio",
        captured_at=datetime(2026, 8, 8, 14, 32),
    )

    assert body["summary"] == "Aniversário de Ana"
    assert body["location"] == "Rua das Flores 200, Pinheiros"
    assert body["start"] == {
        "dateTime": "2026-03-14T15:00:00",
        "timeZone": "America/Sao_Paulo",
    }
    # No end given -> start + DEFAULT_EVENT_HOURS.
    assert body["end"]["dateTime"] == "2026-03-14T18:00:00"
    assert body["reminders"] == {
        "useDefault": False,
        "overrides": [
            {"method": "popup", "minutes": 1440},
            {"method": "popup", "minutes": 120},
        ],
    }

    description = body["description"]
    assert raw in description  # verbatim original message
    assert "Encaminhado por: Turma do Prédio" in description
    assert "Capturado em: 2026-08-08 14:32" in description
    assert "Observações: ano não informado, assumido 2026" in description


def test_event_body_refuses_to_build_without_a_start(
    settings: Settings, invite: ExtractedEvent
) -> None:
    with pytest.raises(ValueError):
        build_event_body(
            invite.model_copy(update={"start": None}),
            settings,
            raw_text="x",
            forwarded_from=None,
            captured_at=datetime(2026, 8, 8, 14, 32),
        )


# --- card rendering -------------------------------------------------------


def test_card_escapes_html_from_the_forwarded_message() -> None:
    hostile = ExtractedEvent(
        is_birthday_invite=True,
        person="<b>Ana</b> & cia",
        start="2026-03-14T15:00:00",
    )
    card = cards.render_card(hostile, forwarded_from=None)
    assert "&lt;b&gt;Ana&lt;/b&gt; &amp; cia" in card
