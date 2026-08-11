"""LLM_PROVIDER -> provider instance.

Provider SDKs are imported inside the factories, never at module top, so a
missing OPENAI_API_KEY (or a missing `openai` install) can never break a
Gemini run.
"""

from birthday_bot.config import Settings
from birthday_bot.llm.base import LLMProvider

# provider name -> the settings attribute holding its key, and the env var name
# to quote back at the user when it is missing.
_KEY_FIELDS: dict[str, tuple[str, str]] = {
    "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
    "claude": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
}


def build_provider(settings: Settings) -> LLMProvider:
    name = settings.llm_provider
    if name not in _KEY_FIELDS:
        known = ", ".join(sorted(_KEY_FIELDS))
        raise ValueError(f"LLM_PROVIDER={name!r} desconhecido. Use um de: {known}")

    field, env_var = _KEY_FIELDS[name]
    api_key = getattr(settings, field)
    if not api_key:
        raise ValueError(
            f"LLM_PROVIDER={name} exige {env_var}, que não está definido no .env"
        )

    if name == "gemini":
        from birthday_bot.llm.gemini import GeminiProvider

        return GeminiProvider(api_key=api_key, model=settings.llm_model)

    if name == "claude":
        from birthday_bot.llm.claude import ClaudeProvider

        return ClaudeProvider(api_key=api_key, model=settings.llm_model)

    from birthday_bot.llm.openai import OpenAIProvider

    return OpenAIProvider(api_key=api_key, model=settings.llm_model)
