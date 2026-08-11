"""Google Calendar event creation.

googleapiclient is blocking, so every API call is wrapped in asyncio.to_thread.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from googleapiclient.discovery import build

from birthday_bot.config import Settings
from birthday_bot.gcal.auth import load_credentials
from birthday_bot.models import ExtractedEvent


@dataclass(frozen=True)
class CreatedCalendarEvent:
    event_id: str
    html_link: str | None


def build_description(
    raw_text: str, forwarded_from: str | None, notes: str | None, captured_at: datetime
) -> str:
    """The description carries the full context.

    Months from now the calendar entry should explain itself: the verbatim
    original message, who forwarded it, when we captured it, and any
    ambiguity the extraction flagged.
    """
    lines = [raw_text.strip(), "", "——"]
    lines.append(f"Encaminhado por: {forwarded_from or 'desconhecido'}")
    lines.append(f"Capturado em: {captured_at.strftime('%Y-%m-%d %H:%M')}")
    if notes:
        lines.append(f"Observações: {notes}")
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
        raise ValueError("não dá para criar evento sem horário de início")

    end = event.end_dt() or start + timedelta(hours=settings.default_event_hours)
    if end <= start:
        end = start + timedelta(hours=settings.default_event_hours)

    person = event.person or "aniversariante não identificado"
    return {
        "summary": f"Aniversário de {person}",
        "location": event.place,
        "description": build_description(
            raw_text, forwarded_from, event.notes, captured_at
        ),
        "start": {"dateTime": start.isoformat(), "timeZone": settings.timezone},
        "end": {"dateTime": end.isoformat(), "timeZone": settings.timezone},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": m} for m in settings.reminder_minutes
            ],
        },
    }


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
