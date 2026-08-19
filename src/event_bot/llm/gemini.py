"""Gemini adapter (google-genai)."""

import logging

from event_bot.llm.base import ExtractionError, ModelT

logger = logging.getLogger(__name__)

# The spec named gemini-2.5-flash, but Google has closed it to new API keys
# ("no longer available to new users"), so it 404s on a fresh project.
DEFAULT_MODEL = "gemini-3.6-flash"

_MAX_PLACE_LENGTH = 200
_NO_RESULT = "SEM_RESULTADO"
_PLACE_PROMPT = (
    "Pesquise o endereço completo deste local, no Brasil: \"{place}\". "
    "Responda em uma única linha, apenas com o nome do local seguido do "
    "endereço completo (rua, número se houver, bairro, cidade, estado). "
    "Não escreva mais nada, sem explicações. Se não encontrar um endereço "
    f"confiável, responda exatamente: {_NO_RESULT}."
)


def _one_line_place(text: str | None) -> str | None:
    """Hold the model to the one-line answer it was asked for.

    A grounded answer sometimes arrives with a preamble or a trailing citation
    line, and this string lands in the calendar's `location` field — a
    paragraph there is worse than no enrichment at all. The sentinel is
    checked as a substring because models emit `SEM_RESULTADO.` about as often
    as the bare token.
    """
    stripped = (text or "").strip()
    if not stripped:
        return None
    line = stripped.splitlines()[0].strip()
    if not line or _NO_RESULT in line:
        return None
    return line[:_MAX_PLACE_LENGTH]


class GeminiProvider:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model or DEFAULT_MODEL
        # Maps grounding may be Vertex-only; latch it off after the first
        # rejection so an unsupported tool costs one wasted call per process
        # rather than one per image.
        self._maps_grounding = True

    async def extract_json(
        self, *, system: str, user: str, schema: type[ModelT]
    ) -> ModelT:
        from google.genai import types

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        except Exception as exc:  # noqa: BLE001 — normalize every SDK failure
            raise ExtractionError(f"gemini: {exc}") from exc

        parsed = response.parsed
        if not isinstance(parsed, schema):
            raise ExtractionError(
                f"gemini returned no parseable {schema.__name__}: {response.text!r}"
            )
        return parsed

    async def extract_json_from_image(
        self,
        *,
        system: str,
        user: str,
        image: bytes,
        mime_type: str,
        schema: type[ModelT],
    ) -> ModelT:
        from google.genai import types

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[
                    types.Part.from_bytes(data=image, mime_type=mime_type),
                    user,
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        except Exception as exc:  # noqa: BLE001 — normalize every SDK failure
            raise ExtractionError(f"gemini: {exc}") from exc

        parsed = response.parsed
        if not isinstance(parsed, schema):
            raise ExtractionError(
                f"gemini returned no parseable {schema.__name__}: {response.text!r}"
            )
        return parsed

    async def search_place(self, place: str) -> str | None:
        """Best-effort: the venue as written on the invite -> a fuller address.

        Never raises. Callers treat "no enrichment" and "search failed"
        identically, and a failed lookup must never cost the user an
        extraction that succeeded.
        """
        from google.genai import types

        tools = []
        if self._maps_grounding:
            tools.append(("maps", types.Tool(google_maps=types.GoogleMaps())))
        tools.append(("search", types.Tool(google_search=types.GoogleSearch())))

        for name, tool in tools:
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=_PLACE_PROMPT.format(place=place),
                    config=types.GenerateContentConfig(tools=[tool]),
                )
            except Exception as exc:  # noqa: BLE001 — best-effort, never fatal
                logger.info("place search via %s failed: %s", name, exc)
                if name == "maps":
                    self._maps_grounding = False
                continue
            return _one_line_place(response.text)
        return None
