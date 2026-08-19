"""All the pt-BR domain logic. The provider adapters know none of this.

The prompt text itself lives in `event_bot/prompts/*.md` — this module loads
and fills those templates.
"""

from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from string import Template

WEEKDAYS_PT = [
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
]


@lru_cache
def _template(name: str) -> Template:
    return Template(
        files("event_bot.prompts").joinpath(name).read_text(encoding="utf-8")
    )


def build_system_prompt() -> str:
    return f"{_template('system.md').template}\n{_template('_rules.md').template}"


def build_system_prompt_image() -> str:
    return (
        f"{_template('system_image.md').template}\n{_template('_rules.md').template}"
    )


def _now_line(now: datetime, timezone: str) -> str:
    weekday = WEEKDAYS_PT[now.weekday()]
    return (
        f"Agora: {now.strftime('%Y-%m-%dT%H:%M:%S')} ({weekday}), "
        f"fuso horário {timezone}."
    )


def build_user_prompt(text: str, now: datetime, timezone: str) -> str:
    return _template("user.md").substitute(
        now_line=_now_line(now, timezone),
        text=text,
    )


def build_user_prompt_image(caption: str | None, now: datetime, timezone: str) -> str:
    caption_block = f"\n\n<<<LEGENDA\n{caption}\nLEGENDA>>>" if caption else ""
    return _template("user_image.md").substitute(
        now_line=_now_line(now, timezone),
        caption_block=caption_block,
    )


def build_correction_prompt(
    original_text: str | None,
    previous: object,
    correction: str,
    now: datetime,
    timezone: str,
) -> str:
    """Re-extract with the user's correction applied (the ✏️ path).

    `previous` is the earlier ExtractedEvent, passed as JSON so the model can
    see exactly what it got wrong instead of starting from scratch.
    `original_text` is `None` for an image-derived pending — the image is not
    re-sent, so a source-free template is used instead of quoting a file id
    as "the original message".
    """
    previous_json = (
        previous.model_dump_json(indent=2)  # type: ignore[attr-defined]
        if hasattr(previous, "model_dump_json")
        else str(previous)
    )
    if original_text is None:
        return _template("correction_no_source.md").substitute(
            now_line=_now_line(now, timezone),
            previous_json=previous_json,
            correction=correction,
        )
    return _template("correction.md").substitute(
        now_line=_now_line(now, timezone),
        original_text=original_text,
        previous_json=previous_json,
        correction=correction,
    )
