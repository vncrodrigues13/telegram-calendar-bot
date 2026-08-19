"""Full flow against a FakeProvider. No network, no API keys."""

from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, NetworkError

from event_bot.bot import cards, handlers
from event_bot.config import Settings
from event_bot.gcal.client import CreatedCalendarEvent, build_event_body
from event_bot.llm.base import ExtractionError
from event_bot.models import ExtractedEvent
from event_bot.raw_text import image_marker
from event_bot.store import Store

from .conftest import FakeProvider


# --- test doubles ---------------------------------------------------------


@dataclass
class FakeMessage:
    text: str | None = None
    caption: str | None = None
    chat_id: int = 7
    message_id: int = 1
    forward_origin: object | None = None
    photo: tuple = ()
    document: object | None = None
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
class FakeFile:
    data: bytes

    async def download_as_bytearray(self) -> bytearray:
        return bytearray(self.data)


@dataclass
class FakePhotoSize:
    file_unique_id: str
    data: bytes = b"fake-jpeg-bytes"
    errors: list[Exception] = field(default_factory=list)
    get_file_calls: int = 0

    async def get_file(self) -> FakeFile:
        self.get_file_calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return FakeFile(self.data)


@dataclass
class FakeDocument:
    file_unique_id: str
    mime_type: str
    data: bytes = b"fake-doc-bytes"
    errors: list[Exception] = field(default_factory=list)
    get_file_calls: int = 0

    async def get_file(self) -> FakeFile:
        self.get_file_calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return FakeFile(self.data)


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


async def test_confirm_creates_the_event_and_clears_pending(
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

    assert await store.get_pending(pending_id) is None


async def test_all_day_pending_confirms_and_reaches_create_event(
    settings: Settings, store: Store, all_day_invite: ExtractedEvent
) -> None:
    calendar = FakeCalendar()
    context = make_context(settings, store, FakeProvider(all_day_invite), calendar)
    pending_id = await store.add_pending(7, "texto", None, all_day_invite)

    query = FakeQuery(data=f"ok:{pending_id}", message=FakeMessage())
    await handlers.on_confirm(make_update(query=query), context)

    assert len(calendar.created) == 1
    assert calendar.created[0]["event"].all_day is True

    text, _ = query.last_edit
    assert "Evento criado" in text


# --- guard rails ----------------------------------------------------------


async def test_missing_start_withholds_the_create_button(
    settings: Settings, store: Store
) -> None:
    """An event with no time is worse than no event."""
    no_time = ExtractedEvent(
        is_event_invite=True,
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
    no_time = ExtractedEvent(is_event_invite=True, person="Ana", start=None)
    calendar = FakeCalendar()
    context = make_context(settings, store, FakeProvider(no_time), calendar)
    pending_id = await store.add_pending(7, "texto", None, no_time)

    query = FakeQuery(data=f"ok:{pending_id}", message=FakeMessage())
    await handlers.on_confirm(make_update(query=query), context)

    assert calendar.created == []
    assert "falta a data" in query.last_edit[0]


async def test_non_invite_offers_the_escape_hatch(
    settings: Settings, store: Store
) -> None:
    not_invite = ExtractedEvent(is_event_invite=False)
    context = make_context(settings, store, FakeProvider(not_invite), FakeCalendar())
    message = FakeMessage(text="bom dia pessoal")

    await handlers.on_message(make_update(message=message), context)

    card_text, keyboard = message.replies[0].last_edit
    assert "não parece um evento" in card_text
    assert callback_data(keyboard) == ["force:1", "no:1"]


async def test_force_turns_a_non_invite_into_a_normal_card(
    settings: Settings, store: Store
) -> None:
    not_invite = ExtractedEvent(
        is_event_invite=False, person="Ana", start="2026-03-14T15:00:00"
    )
    context = make_context(settings, store, FakeProvider(not_invite), FakeCalendar())
    pending_id = await store.add_pending(7, "texto", None, not_invite)

    card_message = FakeMessage()
    query = FakeQuery(data=f"force:{pending_id}", message=card_message)
    await handlers.on_force(make_update(query=query), context)

    _, keyboard = card_message.last_edit
    assert callback_data(keyboard) == [f"ok:{pending_id}", f"edit:{pending_id}", f"no:{pending_id}"]
    pending = await store.get_pending(pending_id)
    assert pending is not None and pending.extraction.is_event_invite


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
        is_event_invite=True,
        person="<b>Ana</b> & cia",
        start="2026-03-14T15:00:00",
    )
    card = cards.render_card(hostile, forwarded_from=None)
    assert "&lt;b&gt;Ana&lt;/b&gt; &amp; cia" in card


def test_personless_card_omits_quem_but_still_shows_local(
    personless_invite: ExtractedEvent,
) -> None:
    """No person at all (not just an unnamed one) — the "Quem" line
    disappears entirely, while "Local" still renders its null placeholder.
    The two null fields are handled by different rules."""
    card = cards.render_card(personless_invite, forwarded_from=None)
    assert "Quem" not in card
    assert "<b>Local:</b> <i>não informado</i>" in card


# --- image handling ---------------------------------------------------------


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The retry backoff otherwise costs real seconds in the test run."""
    calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr(handlers.asyncio, "sleep", _fake_sleep)
    return calls


async def test_photo_becomes_a_card_and_a_pending_row(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    provider = FakeProvider()
    provider.image_queue.append(invite)
    context = make_context(settings, store, provider, FakeCalendar())
    photo = FakePhotoSize(file_unique_id="photo123")
    message = FakeMessage(photo=(photo,))

    await handlers.on_message(make_update(message=message), context)

    status = message.replies[0]
    assert status.text == "🔎 analisando a imagem…"
    card_text, keyboard = status.last_edit
    assert "Ana" in card_text

    pending = await store.get_pending(1)
    assert pending is not None
    assert pending.raw_text == "[imagem photo123]"
    assert len(provider.image_calls) == 1
    assert provider.image_calls[0][3] == "image/jpeg"


async def test_image_document_becomes_a_card_with_its_own_mime_type(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    provider = FakeProvider()
    provider.image_queue.append(invite)
    context = make_context(settings, store, provider, FakeCalendar())
    document = FakeDocument(file_unique_id="doc123", mime_type="image/png")
    message = FakeMessage(document=document)

    await handlers.on_message(make_update(message=message), context)

    pending = await store.get_pending(1)
    assert pending is not None
    assert pending.raw_text == "[imagem doc123]"
    assert provider.image_calls[0][3] == "image/png"


async def test_captioned_non_image_document_still_goes_down_the_text_path(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    """A captioned PDF must not be routed into the image path — regression
    guard for a dispatcher that branches on `message.document` truthiness
    instead of its mime type."""
    provider = FakeProvider(invite)
    context = make_context(settings, store, provider, FakeCalendar())
    document = FakeDocument(file_unique_id="pdf123", mime_type="application/pdf")
    message = FakeMessage(caption="olha esse convite", document=document)

    await handlers.on_message(make_update(message=message), context)

    assert provider.image_calls == []
    assert len(provider.calls) == 1
    assert "olha esse convite" in provider.calls[0][1]
    assert document.get_file_calls == 0


async def test_unsupported_image_mime_is_rejected_without_downloading(
    settings: Settings, store: Store
) -> None:
    provider = FakeProvider()
    context = make_context(settings, store, provider, FakeCalendar())
    document = FakeDocument(file_unique_id="svg123", mime_type="image/svg+xml")
    message = FakeMessage(document=document)

    await handlers.on_message(make_update(message=message), context)

    assert "Não consigo ler esse formato" in message.replies[0].text
    assert document.get_file_calls == 0
    assert provider.image_calls == []


async def test_caption_appears_in_raw_text_and_prompt(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    provider = FakeProvider()
    provider.image_queue.append(invite)
    context = make_context(settings, store, provider, FakeCalendar())
    photo = FakePhotoSize(file_unique_id="photo123")
    message = FakeMessage(photo=(photo,), caption="bora nessa?")

    await handlers.on_message(make_update(message=message), context)

    pending = await store.get_pending(1)
    assert pending is not None
    assert pending.raw_text == "[imagem photo123] bora nessa?"
    assert "bora nessa?" in provider.image_calls[0][1]


async def test_download_exhausts_retries_and_reports_failure(
    settings: Settings, store: Store, no_sleep: list[float]
) -> None:
    provider = FakeProvider()
    context = make_context(settings, store, provider, FakeCalendar())
    photo = FakePhotoSize(
        file_unique_id="photo123",
        errors=[NetworkError("blip"), NetworkError("blip"), NetworkError("blip")],
    )
    message = FakeMessage(photo=(photo,))

    await handlers.on_message(make_update(message=message), context)

    text, _ = message.replies[0].last_edit
    assert "Não foi possível baixar sua imagem" in text
    assert photo.get_file_calls == 3
    assert provider.image_calls == []


async def test_download_recovers_after_transient_failures(
    settings: Settings, store: Store, invite: ExtractedEvent, no_sleep: list[float]
) -> None:
    provider = FakeProvider()
    provider.image_queue.append(invite)
    context = make_context(settings, store, provider, FakeCalendar())
    photo = FakePhotoSize(
        file_unique_id="photo123", errors=[NetworkError("blip"), NetworkError("blip")]
    )
    message = FakeMessage(photo=(photo,))

    await handlers.on_message(make_update(message=message), context)

    assert photo.get_file_calls == 3
    assert len(provider.image_calls) == 1
    assert len(no_sleep) == 2  # backed off twice, then succeeded


async def test_bad_request_fails_immediately_without_retrying(
    settings: Settings, store: Store, no_sleep: list[float]
) -> None:
    provider = FakeProvider()
    context = make_context(settings, store, provider, FakeCalendar())
    photo = FakePhotoSize(file_unique_id="photo123", errors=[BadRequest("file too big")])
    message = FakeMessage(photo=(photo,))

    await handlers.on_message(make_update(message=message), context)

    text, _ = message.replies[0].last_edit
    assert "Não foi possível baixar sua imagem" in text
    assert photo.get_file_calls == 1
    assert no_sleep == []


async def test_extraction_failure_after_download_is_reported(
    settings: Settings, store: Store
) -> None:
    class Boom(FakeProvider):
        async def extract_json_from_image(self, **kwargs):
            raise ExtractionError("gemini: quota exceeded")

    provider = Boom()
    context = make_context(settings, store, provider, FakeCalendar())
    photo = FakePhotoSize(file_unique_id="photo123")
    message = FakeMessage(photo=(photo,))

    await handlers.on_message(make_update(message=message), context)

    text, _ = message.replies[0].last_edit
    assert "Não consegui analisar essa imagem" in text


async def test_edit_then_captionless_photo_keeps_editing_state(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    provider = FakeProvider(invite)
    context = make_context(settings, store, provider, FakeCalendar())
    pending_id = await store.add_pending(7, "niver da Ana", None, invite)

    query = FakeQuery(data=f"edit:{pending_id}", message=FakeMessage())
    await handlers.on_edit(make_update(query=query), context)
    assert context.user_data[handlers.EDITING_KEY] == pending_id

    photo = FakePhotoSize(file_unique_id="photo123")
    message = FakeMessage(photo=(photo,))
    await handlers.on_message(make_update(message=message), context)

    assert "correção em texto" in message.replies[0].text
    assert context.user_data[handlers.EDITING_KEY] == pending_id
    assert provider.image_calls == []


async def test_edit_then_captioned_photo_applies_the_caption_as_correction(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    corrected = invite.model_copy(update={"person": "Bia"})
    provider = FakeProvider(corrected)
    context = make_context(settings, store, provider, FakeCalendar())
    pending_id = await store.add_pending(7, "niver da Ana", None, invite)

    query = FakeQuery(data=f"edit:{pending_id}", message=FakeMessage())
    await handlers.on_edit(make_update(query=query), context)

    photo = FakePhotoSize(file_unique_id="photo123")
    message = FakeMessage(photo=(photo,), caption="na verdade é da Bia")
    await handlers.on_message(make_update(message=message), context)

    card_text, _ = message.replies[0].last_edit
    assert "Bia" in card_text
    assert handlers.EDITING_KEY not in context.user_data
    assert "na verdade é da Bia" in provider.calls[-1][1]
    assert provider.image_calls == []  # the photo itself is never re-extracted


async def test_edit_on_image_derived_pending_uses_source_free_correction(
    settings: Settings, store: Store, invite: ExtractedEvent
) -> None:
    corrected = invite.model_copy(update={"start": "2026-08-23T00:00:00"})
    provider = FakeProvider(corrected)
    context = make_context(settings, store, provider, FakeCalendar())
    raw = image_marker("photo123") + " bora?"
    pending_id = await store.add_pending(7, raw, None, invite)

    query = FakeQuery(data=f"edit:{pending_id}", message=FakeMessage())
    await handlers.on_edit(make_update(query=query), context)

    correction = FakeMessage(text="na verdade é dia 23/08")
    await handlers.on_message(make_update(message=correction), context)

    assert len(provider.calls) == 1
    rendered_prompt = provider.calls[0][1]
    assert "[imagem" not in rendered_prompt
    assert "na verdade é dia 23/08" in rendered_prompt
