"""Rendering the approval card. Pure functions — no network, no state.

Cards are HTML, not Markdown: forwarded invites routinely contain `_` and `*`,
and Telegram rejects the whole message if they don't happen to balance. Every
value that came from a message goes through `html.escape`.
"""

from datetime import datetime
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from birthday_bot.llm.prompt import WEEKDAYS_PT
from birthday_bot.models import ExtractedEvent

# Telegram caps callback_data at 64 bytes, so we send IDs, never payloads.
OK_PREFIX = "ok"
EDIT_PREFIX = "edit"
NO_PREFIX = "no"
FORCE_PREFIX = "force"


def format_when(start: datetime | None, end: datetime | None) -> str:
    if start is None:
        return "não informado"
    weekday = WEEKDAYS_PT[start.weekday()]
    text = f"{start.strftime('%d/%m/%Y')} ({weekday}) às {start.strftime('%H:%M')}"
    if end is not None:
        text += f" – {end.strftime('%H:%M')}"
    return text


def _field(label: str, value: str | None) -> str:
    shown = escape(value) if value else "<i>não informado</i>"
    return f"<b>{label}:</b> {shown}"


def render_card(event: ExtractedEvent, forwarded_from: str | None) -> str:
    lines = ["🎂 <b>Convite de aniversário</b>", ""]
    lines.append(_field("Pessoa", event.person))
    lines.append(_field("Local", event.place))
    lines.append(
        f"<b>Quando:</b> {escape(format_when(event.start_dt(), event.end_dt()))}"
    )
    if forwarded_from:
        lines.append(_field("De", forwarded_from))
    lines.append(f"<b>Confiança:</b> {event.confidence:.0%}")
    if event.notes:
        lines.append(f"⚠️ {escape(event.notes)}")
    if event.start_dt() is None:
        lines.append("")
        lines.append(
            "Sem horário não dá para criar o evento. Use ✏️ para informar a data."
        )
    return "\n".join(lines)


def render_keyboard(pending_id: int, *, can_create: bool) -> InlineKeyboardMarkup:
    """✅ is withheld when there is no start time.

    An event with no time is worse than no event, so the only way forward is
    to supply the date via ✏️.
    """
    row = []
    if can_create:
        row.append(
            InlineKeyboardButton("✅ Criar", callback_data=f"{OK_PREFIX}:{pending_id}")
        )
    row.append(
        InlineKeyboardButton("✏️ Corrigir", callback_data=f"{EDIT_PREFIX}:{pending_id}")
    )
    row.append(
        InlineKeyboardButton("❌ Descartar", callback_data=f"{NO_PREFIX}:{pending_id}")
    )
    return InlineKeyboardMarkup([row])


def render_not_an_invite(pending_id: int) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "🤔 Isso não parece um convite de aniversário, então não extraí nada.\n\n"
        "Se eu errei, dá para criar mesmo assim."
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎂 Criar mesmo assim",
                    callback_data=f"{FORCE_PREFIX}:{pending_id}",
                ),
                InlineKeyboardButton(
                    "❌ Descartar", callback_data=f"{NO_PREFIX}:{pending_id}"
                ),
            ]
        ]
    )
    return text, keyboard


def render_created(event: ExtractedEvent, html_link: str | None) -> str:
    person = escape(event.person or "aniversariante")
    lines = [f"✅ Evento criado: <b>Aniversário de {person}</b>"]
    lines.append(escape(format_when(event.start_dt(), event.end_dt())))
    if html_link:
        lines.append(escape(html_link))
    return "\n".join(lines)


def render_duplicate(html_link: str | None) -> str:
    text = "♻️ Já criei esse evento antes."
    if html_link:
        text += f"\n{escape(html_link)}"
    return text
