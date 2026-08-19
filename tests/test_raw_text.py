from event_bot.raw_text import image_caption, image_key, image_marker


def test_marker_key_and_caption_round_trip() -> None:
    marker = image_marker("AgACAgQAAxkBAAI")
    assert marker == "[imagem AgACAgQAAxkBAAI]"
    assert image_key(marker) == marker
    assert image_caption(marker) is None


def test_marker_with_caption_round_trips() -> None:
    raw_text = image_marker("abc123") + " bora?"
    assert image_key(raw_text) == "[imagem abc123]"
    assert image_caption(raw_text) == "bora?"


def test_image_key_is_none_for_ordinary_text() -> None:
    assert image_key("sábado tem niver da Ana") is None


def test_image_key_is_none_when_marker_is_not_at_the_start() -> None:
    assert image_key("olha essa imagem: [imagem abc123]") is None


def test_image_caption_is_none_for_ordinary_text() -> None:
    assert image_caption("sábado tem niver da Ana") is None
