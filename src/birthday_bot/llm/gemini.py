"""Gemini adapter (google-genai)."""

from birthday_bot.llm.base import ExtractionError, ModelT

# The spec named gemini-2.5-flash, but Google has closed it to new API keys
# ("no longer available to new users"), so it 404s on a fresh project.
DEFAULT_MODEL = "gemini-3.6-flash"


class GeminiProvider:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model or DEFAULT_MODEL

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
