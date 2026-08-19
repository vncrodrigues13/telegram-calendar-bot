"""The `raw_text` convention shared by the store, the bot and the calendar.

A text forward stores the message verbatim. An image forward has no text, so
`raw_text` is `[imagem <file_unique_id>]`, optionally followed by the caption
the user typed. `file_unique_id` is what makes an image identity-stable across
re-forwards, so it — and not the caption — is what dedupe keys on.
"""

import re

_IMAGE_MARKER = re.compile(r"^\[imagem [^\]]+\]")


def image_marker(file_unique_id: str) -> str:
    return f"[imagem {file_unique_id}]"


def image_key(raw_text: str) -> str | None:
    """The `[imagem <id>]` marker alone, or None for ordinary text."""
    match = _IMAGE_MARKER.match(raw_text.strip())
    return match.group(0) if match else None


def image_caption(raw_text: str) -> str | None:
    """Whatever the user typed alongside the image, or None."""
    stripped = raw_text.strip()
    match = _IMAGE_MARKER.match(stripped)
    if match is None:
        return None
    return stripped[match.end() :].strip() or None
