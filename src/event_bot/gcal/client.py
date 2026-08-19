"""Google Calendar event creation.

googleapiclient is blocking, so every API call is wrapped in asyncio.to_thread.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from googleapiclient.discovery import build

from event_bot.config import Settings
from event_bot.gcal.auth import load_credentials
from event_bot.models import ExtractedEvent
from event_bot.raw_text import image_caption, image_key


@dataclass(frozen=True)
class CreatedCalendarEvent:
    event_id: str
    html_link: str | None


def _source_block(event: ExtractedEvent, raw_text: str) -> str:
    """What the invite itself said.

    A text forward is quoted verbatim. An image forward has no text to quote,
    so this is rebuilt from what was extracted — which is all we have, and is
    read *after* any ✏️ correction, so it reflects the final values rather
    than a first guess.
    """
    if image_key(raw_text) is None:
        return raw_text.strip()

    headline = " — ".join(p for p in (event.title, event.event_type) if p)
    lines = [f"[imagem] {headline}" if headline else "[imagem]"]

    caption = image_caption(raw_text)
    if caption:
        lines.append(f"Legenda: {caption}")
    if event.place:
        lines.append(f"Local: {event.place}")
    start = event.start_dt()
    if start is not None:
        when = start.strftime("%d/%m/%Y")
        if not event.all_day:
            when += start.strftime(" %H:%M")
        lines.append(f"Quando: {when}")
    return "\n".join(lines)


def build_description(
    event: ExtractedEvent,
    raw_text: str,
    forwarded_from: str | None,
    captured_at: datetime,
) -> str:
    """The description carries the full context.

    Months from now the calendar entry should explain itself: what the
    invite said, who forwarded it, when we captured it, and any ambiguity the
    extraction flagged.
    """
    lines = [_source_block(event, raw_text), "", "——"]
    lines.append(f"Encaminhado por: {forwarded_from or 'desconhecido'}")
    lines.append(f"Capturado em: {captured_at.strftime('%Y-%m-%d %H:%M')}")
    if event.notes:
        lines.append(f"Observações: {event.notes}")
    return "\n".join(lines)


def build_event_body(
    event: ExtractedEvent,
    settings: Settings,
    raw_text: str,
    forwarded_from: str | None,
    captured_at: datetime,
) -> dict:
    start = event.start_dt()
    if start is None:
        raise ValueError("não dá para criar evento sem data")

    body = {
        "summary": event.display_title(),
        "location": event.place,
        "description": build_description(
            event, raw_text, forwarded_from, captured_at
        ),
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": m} for m in settings.reminder_minutes
            ],
        },
    }

    if event.all_day:
        start_date = start.date()
        end_dt = event.end_dt()
        end_date = end_dt.date() if end_dt else start_date
        if end_date < start_date:
            end_date = start_date
        # Google's all-day `end.date` is exclusive.
        body["start"] = {"date": start_date.isoformat()}
        body["end"] = {"date": (end_date + timedelta(days=1)).isoformat()}
    else:
        end = event.end_dt() or start + timedelta(hours=settings.default_event_hours)
        if end <= start:
            end = start + timedelta(hours=settings.default_event_hours)
        body["start"] = {"dateTime": start.isoformat(), "timeZone": settings.timezone}
        body["end"] = {"dateTime": end.isoformat(), "timeZone": settings.timezone}

    return body


class CalendarClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = None

    def _get_service(self):
        if self._service is None:
            creds = load_credentials(
                self._settings.credentials_path, self._settings.token_path
            )
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def _insert_sync(self, body: dict) -> CreatedCalendarEvent:
        created = (
            self._get_service()
            .events()
            .insert(calendarId=self._settings.calendar_id, body=body)
            .execute()
        )
        return CreatedCalendarEvent(
            event_id=created["id"], html_link=created.get("htmlLink")
        )

    async def create_event(
        self,
        event: ExtractedEvent,
        raw_text: str,
        forwarded_from: str | None,
        captured_at: datetime,
    ) -> CreatedCalendarEvent:
        body = build_event_body(
            event, self._settings, raw_text, forwarded_from, captured_at
        )
        return await asyncio.to_thread(self._insert_sync, body)

    def _delete_sync(self, event_id: str) -> None:
        self._get_service().events().delete(
            calendarId=self._settings.calendar_id, eventId=event_id
        ).execute()

    async def delete_event(self, event_id: str) -> None:
        await asyncio.to_thread(self._delete_sync, event_id)
