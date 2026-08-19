from event_bot.models import ExtractedEvent
from event_bot.store import Store


async def test_pending_round_trip(store: Store, invite: ExtractedEvent) -> None:
    pending_id = await store.add_pending(
        chat_id=7, raw_text="texto original", forwarded_from="Grupo X", extraction=invite
    )

    pending = await store.get_pending(pending_id)
    assert pending is not None
    assert pending.chat_id == 7
    assert pending.raw_text == "texto original"
    assert pending.forwarded_from == "Grupo X"
    assert pending.extraction.person == "Ana"
    assert pending.card_message_id is None


async def test_pending_update_and_delete(store: Store, invite: ExtractedEvent) -> None:
    pending_id = await store.add_pending(1, "texto", None, invite)

    corrected = invite.model_copy(update={"person": "Fulana"})
    await store.update_pending(pending_id, extraction=corrected, card_message_id=99)

    pending = await store.get_pending(pending_id)
    assert pending is not None
    assert pending.extraction.person == "Fulana"
    assert pending.card_message_id == 99

    await store.delete_pending(pending_id)
    assert await store.get_pending(pending_id) is None


async def test_stale_schema_row_returns_none_instead_of_raising(store: Store) -> None:
    """A row serialized under the old is_birthday_invite schema is unreadable
    by the current ExtractedEvent — it should degrade to 'no longer pending'
    rather than raise a pydantic.ValidationError up through the handler."""
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO pending "
            "(chat_id, card_message_id, raw_text, forwarded_from, "
            " extraction_json, created_at) "
            "VALUES (?, NULL, ?, ?, ?, ?)",
            (1, "texto antigo", None, '{"is_birthday_invite": true}', "2026-01-01"),
        )
        pending_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    assert await store.get_pending(pending_id) is None
