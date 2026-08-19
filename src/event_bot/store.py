"""sqlite: pending approvals awaiting a ✅/✏️/❌ tap.

sqlite3 is blocking and PTB's loop is not, so every call goes through
asyncio.to_thread.
"""

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from event_bot.models import ExtractedEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER, card_message_id INTEGER,
    raw_text TEXT, forwarded_from TEXT,
    extraction_json TEXT, created_at TEXT
);
"""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Pending:
    id: int
    chat_id: int
    card_message_id: int | None
    raw_text: str
    forwarded_from: str | None
    extraction: ExtractedEvent


class Store:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- schema -----------------------------------------------------------

    def _init_sync(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    # --- pending ----------------------------------------------------------

    def _add_pending_sync(
        self,
        chat_id: int,
        raw_text: str,
        forwarded_from: str | None,
        extraction: ExtractedEvent,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO pending "
                "(chat_id, card_message_id, raw_text, forwarded_from, "
                " extraction_json, created_at) "
                "VALUES (?, NULL, ?, ?, ?, ?)",
                (
                    chat_id,
                    raw_text,
                    forwarded_from,
                    extraction.model_dump_json(),
                    _utc_now(),
                ),
            )
            return int(cursor.lastrowid or 0)

    async def add_pending(
        self,
        chat_id: int,
        raw_text: str,
        forwarded_from: str | None,
        extraction: ExtractedEvent,
    ) -> int:
        return await asyncio.to_thread(
            self._add_pending_sync, chat_id, raw_text, forwarded_from, extraction
        )

    def _get_pending_sync(self, pending_id: int) -> Pending | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pending WHERE id = ?", (pending_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            extraction = ExtractedEvent.model_validate_json(row["extraction_json"])
        except ValidationError:
            # A row serialized under an older schema (e.g. the pre-rename
            # is_birthday_invite field) is indistinguishable from a pending
            # approval that's no longer valid — treat it as gone.
            return None
        return Pending(
            id=row["id"],
            chat_id=row["chat_id"],
            card_message_id=row["card_message_id"],
            raw_text=row["raw_text"],
            forwarded_from=row["forwarded_from"],
            extraction=extraction,
        )

    async def get_pending(self, pending_id: int) -> Pending | None:
        return await asyncio.to_thread(self._get_pending_sync, pending_id)

    def _update_pending_sync(
        self,
        pending_id: int,
        extraction: ExtractedEvent | None,
        card_message_id: int | None,
    ) -> None:
        with self._connect() as conn:
            if extraction is not None:
                conn.execute(
                    "UPDATE pending SET extraction_json = ? WHERE id = ?",
                    (extraction.model_dump_json(), pending_id),
                )
            if card_message_id is not None:
                conn.execute(
                    "UPDATE pending SET card_message_id = ? WHERE id = ?",
                    (card_message_id, pending_id),
                )

    async def update_pending(
        self,
        pending_id: int,
        *,
        extraction: ExtractedEvent | None = None,
        card_message_id: int | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._update_pending_sync, pending_id, extraction, card_message_id
        )

    def _delete_pending_sync(self, pending_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pending WHERE id = ?", (pending_id,))

    async def delete_pending(self, pending_id: int) -> None:
        await asyncio.to_thread(self._delete_pending_sync, pending_id)
