"""Message -> extraction -> card; callbacks -> event creation."""

import asyncio
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
from telegram.error import BadRequest, NetworkError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from event_bot.bot import cards
from event_bot.config import Settings
from event_bot.extract import (
    extract_event,
    extract_event_from_image,
    now_local,
    reextract_with_correction,
)
from event_bot.gcal.client import CalendarClient
from event_bot.llm.base import ExtractionError, LLMProvider
from event_bot.raw_text import image_caption, image_key, image_marker
from event_bot.store import Store

logger = logging.getLogger(__name__)

EDITING_KEY = "editing"

_MAX_DOWNLOAD_ATTEMPTS = 3
_DOWNLOAD_BACKOFF_SECONDS = (1, 2)  # after attempts 1 and 2; attempt 3 is the last

# What Gemini can actually read. `filters.Document.IMAGE` is a bare `image/`
# prefix match, so it also lets through svg/gif/bmp/tiff — and PTB's own
# docstring notes the *sender* controls `mime_type`.
_SUPPORTED_IMAGE_MIMES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}
)


class ImageDownloadError(RuntimeError):
    """Telegram would not give us the file — distinct from a failed extraction."""


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
    if not event.is_event_invite:
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


def _image_media(message: Message) -> tuple[object, str] | None:
    """The PhotoSize/Document to download and its mime type, or None."""
    if message.photo:
        # Telegram always transcodes `photo` to JPEG; [-1] is the largest size.
        return message.photo[-1], "image/jpeg"
    document = message.document
    if document is not None and (document.mime_type or "").startswith("image/"):
        return document, document.mime_type
    return None


async def _download_bytes(media) -> bytes:
    """`media` is a PhotoSize or a Document — both expose `get_file()`.

    Only transient failures are retried. `BadRequest` is permanent (the Bot
    API refuses files over 20 MB — exactly the "send as file to keep the fine
    print legible" case) and, counter-intuitively, PTB makes it a *subclass*
    of `NetworkError`, so it has to be excluded before the retry clause rather
    than after.

    The retry budget is deliberately small: PTB's default
    `max_concurrent_updates` is 1 and `main.py` does not override it, so every
    second spent sleeping here is a second the bot ignores every other message
    and every ✅/✏️/❌ button press.
    """
    for attempt in range(_MAX_DOWNLOAD_ATTEMPTS):
        try:
            file = await media.get_file()
            return bytes(await file.download_as_bytearray())
        except BadRequest as exc:  # permanent: too big, bad file id
            raise ImageDownloadError(str(exc)) from exc
        except NetworkError as exc:  # transient: blip, timeout
            if attempt == _MAX_DOWNLOAD_ATTEMPTS - 1:
                raise ImageDownloadError(str(exc)) from exc
            await asyncio.sleep(_DOWNLOAD_BACKOFF_SECONDS[attempt])
        except Exception as exc:  # noqa: BLE001
            raise ImageDownloadError(str(exc)) from exc
    raise AssertionError("unreachable")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    media = _image_media(message)
    if media is not None:
        await _handle_image(message, context, *media)
        return

    text = message.text or message.caption
    if not text:
        return
    await _handle_text(message, context, text)


async def _handle_text(
    message: Message, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    # A pending ✏️ correction takes precedence over treating this as a new invite.
    editing_id = context.user_data.pop(EDITING_KEY, None) if context.user_data else None
    if editing_id is not None:
        await _apply_correction(message, context, int(editing_id), text)
        return

    status = await message.reply_text("🔎 analisando…")

    try:
        event = await extract_event(_provider(context), _settings(context), text)
    except ExtractionError as exc:
        logger.warning("extraction failed: %s", exc)
        await status.edit_text(f"❌ Não consegui analisar essa mensagem.\n{exc}")
        return

    await _finish_pending(message, status, context, text, event)


async def _handle_image(
    message: Message, context: ContextTypes.DEFAULT_TYPE, media, mime_type: str
) -> None:
    if mime_type not in _SUPPORTED_IMAGE_MIMES:
        await message.reply_text(
            f"❌ Não consigo ler esse formato de imagem ({mime_type}). "
            "Mande como JPEG, PNG ou WEBP."
        )
        return

    caption = message.caption
    raw_text = image_marker(media.file_unique_id) + (f" {caption}" if caption else "")

    # An image on its own is never a ✏️ correction — the correction has to be
    # text. With a caption, the caption *is* the correction; without one, keep
    # the edit state so the next text message still lands as one.
    if context.user_data and EDITING_KEY in context.user_data:
        if caption:
            pending_id = context.user_data.pop(EDITING_KEY)
            await _apply_correction(message, context, int(pending_id), caption)
        else:
            await message.reply_text(
                "✏️ Ainda estou esperando a correção em texto. Mande o que "
                "devo corrigir, ou use ❌ para descartar."
            )
        return

    status = await message.reply_text("🔎 analisando a imagem…")

    try:
        image_bytes = await _download_bytes(media)
    except ImageDownloadError as exc:
        logger.warning("image download failed: %s", exc)
        await status.edit_text("❌ Não foi possível baixar sua imagem.")
        return

    try:
        event = await extract_event_from_image(
            _provider(context), _settings(context), image_bytes, mime_type, caption
        )
    except ExtractionError as exc:
        logger.warning("image extraction failed: %s", exc)
        await status.edit_text(f"❌ Não consegui analisar essa imagem.\n{exc}")
        return

    await _finish_pending(message, status, context, raw_text, event)


async def _finish_pending(
    message: Message,
    status: Message,
    context: ContextTypes.DEFAULT_TYPE,
    raw_text: str,
    event,
) -> None:
    store = _store(context)
    forwarded_from = describe_origin(message)
    pending_id = await store.add_pending(
        chat_id=message.chat_id,
        raw_text=raw_text,
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

    # The image itself is gone; only the caption, if any, is real text.
    original_text = pending.raw_text
    if image_key(original_text) is not None:
        original_text = image_caption(pending.raw_text)

    status = await message.reply_text("🔎 reanalisando com a sua correção…")
    try:
        event = await reextract_with_correction(
            _provider(context),
            _settings(context),
            original_text,
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
            "Ainda falta a data. Use ✏️ para informar a data.",
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

    event = pending.extraction.model_copy(update={"is_event_invite": True})
    await store.update_pending(pending_id, extraction=event)
    await _show_card(query.message, pending_id, event, pending.forwarded_from)


async def on_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    pending_id = _pending_id(update)
    if context.user_data is not None:
        context.user_data[EDITING_KEY] = pending_id
    await query.message.reply_text(
        "✏️ O que devo corrigir? Ex.: “é dia 22/03”, “é o casamento da Bia”, "
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
        MessageHandler(
            owner_only
            & (filters.TEXT | filters.CAPTION | filters.PHOTO | filters.Document.IMAGE),
            on_message,
        )
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
