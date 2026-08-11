from birthday_bot.models import ExtractedEvent
from birthday_bot.store import Store, fingerprint


def test_fingerprint_ignores_casing_and_rewrapping() -> None:
    original = "Galera, sábado tem niver da Ana! 15h na Rua das Flores 200"
    rewrapped = "  galera, sábado tem niver da ana!\n15h  na Rua das Flores 200 "
    assert fingerprint(original) == fingerprint(rewrapped)


def test_fingerprint_distinguishes_different_invites() -> None:
    assert fingerprint("niver da Ana, 15h") != fingerprint("niver da Bia, 15h")


async def test_created_ledger_round_trip(store: Store) -> None:
    text = "Sábado tem niver da Ana, 15h"
    assert await store.find_created(text) is None

    await store.record_created(text, "evt_123", "https://calendar.example/evt_123")

    found = await store.find_created(text)
    assert found is not None
    assert found.event_id == "evt_123"
    assert found.html_link == "https://calendar.example/evt_123"


async def test_dedupe_matches_a_reforward_with_different_whitespace(
    store: Store,
) -> None:
    await store.record_created("niver da Ana\n15h", "evt_1", None)
    assert await store.find_created("  Niver da Ana   15h  ") is not None


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

    corrected = invite.model_copy(update={"person": "Bia"})
    await store.update_pending(pending_id, extraction=corrected, card_message_id=99)

    pending = await store.get_pending(pending_id)
    assert pending is not None
    assert pending.extraction.person == "Bia"
    assert pending.card_message_id == 99

    await store.delete_pending(pending_id)
    assert await store.get_pending(pending_id) is None
