"""OpenAI adapter (openai)."""

from event_bot.llm.base import ExtractionError, ModelT

DEFAULT_MODEL = "gpt-4.1-mini"


class OpenAIProvider:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        import openai

        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._model = model or DEFAULT_MODEL

    async def extract_json(
        self, *, system: str, user: str, schema: type[ModelT]
    ) -> ModelT:
        try:
            response = await self._client.responses.parse(
                model=self._model,
                instructions=system,
                input=user,
                text_format=schema,
            )
        except Exception as exc:  # noqa: BLE001 — normalize every SDK failure
            raise ExtractionError(f"openai: {exc}") from exc

        parsed = response.output_parsed
        if parsed is None:
            raise ExtractionError(
                f"openai returned no parseable {schema.__name__} "
                f"(status={response.status})"
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
        raise ExtractionError("visão ainda não implementada para openai")
