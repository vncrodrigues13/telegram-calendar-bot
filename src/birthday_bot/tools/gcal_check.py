"""CLI: verify Google OAuth end to end by creating and deleting a test event.

    uv run python -m birthday_bot.tools.gcal_check

Opens a browser once, writes token.json, then proves we can write to the
calendar without leaving anything behind.
"""

import asyncio
from datetime import timedelta

from birthday_bot.config import load_settings
from birthday_bot.extract import now_local
from birthday_bot.gcal.client import CalendarClient
from birthday_bot.models import ExtractedEvent


async def main() -> int:
    settings = load_settings()
    client = CalendarClient(settings)
    now = now_local(settings)
    start = (now + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)

    probe = ExtractedEvent(
        is_birthday_invite=True,
        person="Teste do bot",
        place="Nenhum lugar",
        start=start.isoformat(timespec="seconds"),
        confidence=1.0,
        notes="evento de teste, será apagado automaticamente",
    )

    print(f"calendário : {settings.calendar_id} ({settings.timezone})")
    print("criando evento de teste…")
    created = await client.create_event(
        probe,
        raw_text="Evento de teste criado por birthday_bot.tools.gcal_check",
        forwarded_from=None,
        captured_at=now,
    )
    print(f"  criado: {created.event_id}")
    if created.html_link:
        print(f"  link  : {created.html_link}")

    print("apagando evento de teste…")
    await client.delete_event(created.event_id)
    print("  apagado. OAuth e escrita no calendário estão funcionando.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
