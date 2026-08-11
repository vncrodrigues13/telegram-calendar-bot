"""Claude adapter (anthropic)."""

from birthday_bot.llm.base import ExtractionError, ModelT

DEFAULT_MODEL = "claude-haiku-4-5"


class ClaudeProvider:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model or DEFAULT_MODEL

    async def extract_json(
        self, *, system: str, user: str, schema: type[ModelT]
    ) -> ModelT:
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except Exception as exc:  # noqa: BLE001 — normalize every SDK failure
            raise ExtractionError(f"claude: {exc}") from exc

        parsed = response.parsed_output
        if parsed is None:
            raise ExtractionError(
                f"claude returned no parseable {schema.__name__} "
                f"(stop_reason={response.stop_reason})"
            )
        return parsed
