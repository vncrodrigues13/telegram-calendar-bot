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

# provider name -> (module the adapter imports, package that provides it).
# Only gemini's is installed by default; claude and openai were dropped from
# the dependencies, so selecting one is a two-step change (key + install) and
# the error has to say both.
_PACKAGES: dict[str, tuple[str, str]] = {
    "gemini": ("google.genai", "google-genai"),
    "claude": ("anthropic", "anthropic"),
    "openai": ("openai", "openai"),
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

    try:
        if name == "gemini":
            from birthday_bot.llm.gemini import GeminiProvider

            return GeminiProvider(api_key=api_key, model=settings.llm_model)

        if name == "claude":
            from birthday_bot.llm.claude import ClaudeProvider

            return ClaudeProvider(api_key=api_key, model=settings.llm_model)

        from birthday_bot.llm.openai import OpenAIProvider

        return OpenAIProvider(api_key=api_key, model=settings.llm_model)
    except ModuleNotFoundError as exc:
        module, package = _PACKAGES[name]
        # Only the provider's own SDK gets the friendly message. Any other
        # missing module is a real bug and must keep its traceback.
        if exc.name is None or not module.startswith(exc.name):
            raise
        raise ValueError(
            f"LLM_PROVIDER={name} exige o SDK '{package}', que não está "
            f"instalado. Instale com `uv add {package}`."
        ) from exc
