"""The extraction schema — the one thing the LLM is asked to produce."""

from datetime import datetime

from pydantic import BaseModel, field_validator


def _normalize_iso(value: str) -> str:
    """Parse a model-supplied timestamp and re-emit it as naive local ISO.

    Models occasionally decorate the timestamp with a `Z` or a `+00:00` offset
    even when told not to. We want a wall-clock time in the user's timezone,
    so any offset is dropped rather than converted.
    """
    text = value.strip()
    if text.endswith(("z", "Z")):
        text = text[:-1]
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat(timespec="seconds")


class ExtractedEvent(BaseModel):
    """What the LLM extracts from one message.

    `start`/`end` are `str`, not `datetime`, on purpose. A `datetime` field
    emits `format: "date-time"` in the JSON schema; OpenAI's strict structured
    output mode rejects `format`, and the three providers disagree on how they
    honor it. A plain string parsed here behaves identically everywhere.
    """

    is_birthday_invite: bool
    person: str | None = None  # quem faz aniversário
    place: str | None = None  # local + endereço, como escrito
    start: str | None = None  # "2026-03-14T15:00:00" — plain ISO, no timezone
    end: str | None = None
    confidence: float = 0.0  # 0..1
    notes: str | None = None  # ambiguidades ("ano não informado")

    @field_validator("start", "end", mode="before")
    @classmethod
    def _validate_iso(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return _normalize_iso(value)
        except ValueError:
            # A malformed timestamp is indistinguishable from "no date given":
            # both mean we cannot create an event, and both route to the ✏️ path.
            return None

    def start_dt(self) -> datetime | None:
        return datetime.fromisoformat(self.start) if self.start else None

    def end_dt(self) -> datetime | None:
        return datetime.fromisoformat(self.end) if self.end else None
