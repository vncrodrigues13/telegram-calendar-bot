"""Message -> extraction -> card; callbacks -> event creation."""

import logging

from telegram import (
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from birthday_bot.bot import cards
from birthday_bot.config import Settings
from birthday_bot.extract import (
    extract_event,
    now_local,
    reextract_with_correction,
)
from birthday_bot.gcal.client import CalendarClient
from birthday_bot.llm.base import ExtractionError, LLMProvider
from birthday_bot.store import Store

logger = logging.getLogger(__name__)

EDITING_KEY = "editing"


def describe_origin(message: Message) -> str | None:
    """Human-readable forward origin.

    PTB v20+ replaced the flat `forward_from` fields with a `MessageOrigin`
    union, so each variant carries its sender in a different attribute.
    """
    origin = message.forward_origin
    if origin is None:
        return None
    if isinstance(origin, MessageOriginUser):
        return origin.sender_user.full_name
    if isinstance(origin, MessageOriginHiddenUser):
        return origin.sender_user_name
    if isinstance(origin, MessageOriginChat):
        return origin.sender_chat.title or origin.sender_chat.full_name
    if isinstance(origin, MessageOriginChannel):
        return origin.chat.title
    return None


def _bot_data(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.application.bot_data


def _store(context: ContextTypes.DEFAULT_TYPE) -> Store:
    return _bot_data(context)["store"]


def _provider(context: ContextTypes.DEFAULT_TYPE) -> LLMProvider:
    return _bot_data(context)["provider"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return _bot_data(context)["settings"]


def _calendar(context: ContextTypes.DEFAULT_TYPE) -> CalendarClient:
    return _bot_data(context)["calendar"]


async def _show_card(
    message: Message, pending_id: int, event, forwarded_from: str | None
) -> None:
    """Edit `message` in place into the approval card."""
    if not event.is_birthday_invite:
        text, keyboard = cards.render_not_an_invite(pending_id)
    else:
        text = cards.render_card(event, forwarded_from)
        keyboard = cards.render_keyboard(
            pending_id, can_create=event.start_dt() is not None
        )
    await message.edit_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.HTML
    )


# --- incoming messages ----------------------------------------------------


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    text = message.text or message.caption
    if not text:
        return

    # A pending ✏️ correction takes precedence over treating this as a new invite.
    editing_id = context.user_data.pop(EDITING_KEY, None) if context.user_data else None
    if editing_id is not None:
        await _apply_correction(message, context, int(editing_id), text)
        return

    store = _store(context)

    existing = await store.find_created(text)
    if existing is not None:
        await message.reply_text(
            cards.render_duplicate(existing.html_link), parse_mode=ParseMode.HTML
        )
        return

    status = await message.reply_text("🔎 analisando…")

    try:
        event = await extract_event(_provider(context), _settings(context), text)
    except ExtractionError as exc:
        logger.warning("extraction failed: %s", exc)
        await status.edit_text(f"❌ Não consegui analisar essa mensagem.\n{exc}")
        return

    forwarded_from = describe_origin(message)
    pending_id = await store.add_pending(
        chat_id=message.chat_id,
        raw_text=text,
        forwarded_from=forwarded_from,
        extraction=event,
    )
    await store.update_pending(pending_id, card_message_id=status.message_id)
    await _show_card(status, pending_id, event, forwarded_from)


async def _apply_correction(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    pending_id: int,
    correction: str,
) -> None:
    store = _store(context)
    pending = await store.get_pending(pending_id)
    if pending is None:
        await message.reply_text("Esse convite não está mais pendente.")
        return

    status = await message.reply_text("🔎 reanalisando com a sua correção…")
    try:
        event = await reextract_with_correction(
            _provider(context),
            _settings(context),
            pending.raw_text,
            pending.extraction,
            correction,
        )
    except ExtractionError as exc:
        logger.warning("re-extraction failed: %s", exc)
        await status.edit_text(f"❌ Não consegui aplicar a correção.\n{exc}")
        return

    await store.update_pending(
        pending_id, extraction=event, card_message_id=status.message_id
    )
    await _show_card(status, pending_id, event, pending.forwarded_from)


# --- callbacks ------------------------------------------------------------


def _pending_id(update: Update) -> int:
    data = update.callback_query.data or ""
    return int(data.split(":", 1)[1])


async def on_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    pending_id = _pending_id(update)

    store = _store(context)
    pending = await store.get_pending(pending_id)
    if pending is None:
        await query.edit_message_text("Esse convite não está mais pendente.")
        return

    event = pending.extraction
    if event.start_dt() is None:
        await query.edit_message_text(
            "Ainda falta o horário. Use ✏️ para informar a data.",
            reply_markup=cards.render_keyboard(pending_id, can_create=False),
        )
        return

    settings = _settings(context)
    try:
        created = await _calendar(context).create_event(
            event,
            raw_text=pending.raw_text,
            forwarded_from=pending.forwarded_from,
            captured_at=now_local(settings),
        )
    except Exception as exc:  # noqa: BLE001 — surface the failure in-chat
        logger.exception("calendar insert failed")
        await query.edit_message_text(f"❌ Falhei ao criar o evento.\n{exc}")
        return

    await store.record_created(pending.raw_text, created.event_id, created.html_link)
    await store.delete_pending(pending_id)
    await query.edit_message_text(
        cards.render_created(event, created.html_link), parse_mode=ParseMode.HTML
    )


async def on_force(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """'Criar mesmo assim' after we judged the message not to be an invite."""
    query = update.callback_query
    await query.answer()
    pending_id = _pending_id(update)

    store = _store(context)
    pending = await store.get_pending(pending_id)
    if pending is None:
        await query.edit_message_text("Esse convite não está mais pendente.")
        return

    event = pending.extraction.model_copy(update={"is_birthday_invite": True})
    await store.update_pending(pending_id, extraction=event)
    await _show_card(query.message, pending_id, event, pending.forwarded_from)


async def on_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    pending_id = _pending_id(update)
    if context.user_data is not None:
        context.user_data[EDITING_KEY] = pending_id
    await query.message.reply_text(
        "✏️ O que devo corrigir? Ex.: “é dia 22/03”, “o aniversário é da Bia”, "
        "“o endereço é Rua X, 100”."
    )


async def on_discard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    pending_id = _pending_id(update)
    await _store(context).delete_pending(pending_id)
    if context.user_data is not None:
        context.user_data.pop(EDITING_KEY, None)
    await query.edit_message_text("🗑️ Descartado.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Report failures back in-chat rather than dying silently in the terminal."""
    logger.exception("unhandled error", exc_info=context.error)
    chat_id = None
    if isinstance(update, Update) and update.effective_chat is not None:
        chat_id = update.effective_chat.id
    if chat_id is None:
        return
    try:
        await context.bot.send_message(
            chat_id, f"❌ Deu erro aqui: {context.error}"
        )
    except Exception:  # noqa: BLE001 — nothing useful left to do
        logger.exception("could not report the error to the chat")


def register(application: Application, owner_id: int) -> None:
    """Owner filter first: a stranger who finds the bot gets nothing."""
    owner_only = filters.User(owner_id)
    application.add_handler(
        MessageHandler(owner_only & (filters.TEXT | filters.CAPTION), on_message)
    )
    application.add_handler(
        CallbackQueryHandler(on_confirm, pattern=rf"^{cards.OK_PREFIX}:\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(on_force, pattern=rf"^{cards.FORCE_PREFIX}:\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(on_edit, pattern=rf"^{cards.EDIT_PREFIX}:\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(on_discard, pattern=rf"^{cards.NO_PREFIX}:\d+$")
    )
    application.add_error_handler(on_error)
