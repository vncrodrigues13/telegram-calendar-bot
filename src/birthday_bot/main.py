"""Wiring + PTB application startup."""

import logging

from telegram.ext import Application

from birthday_bot.bot import handlers
from birthday_bot.config import load_settings
from birthday_bot.gcal.client import CalendarClient
from birthday_bot.llm.registry import build_provider
from birthday_bot.store import Store

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = load_settings()
    store = Store(settings.db_path)

    async def _post_init(app: Application) -> None:
        await store.init()

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .build()
    )
    application.bot_data.update(
        settings=settings,
        store=store,
        provider=build_provider(settings),
        calendar=CalendarClient(settings),
    )

    handlers.register(application, settings.owner_telegram_id)

    logger.info(
        "provider=%s timezone=%s calendar=%s — encaminhe um convite para o bot",
        settings.llm_provider,
        settings.timezone,
        settings.calendar_id,
    )
    # run_polling owns the event loop; nothing else needs an asyncio.run.
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
