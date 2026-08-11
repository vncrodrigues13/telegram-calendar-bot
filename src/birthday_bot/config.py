"""Runtime configuration, read from .env (see .env.example)."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    owner_telegram_id: int  # only you may talk to the bot

    llm_provider: Literal["gemini", "claude", "openai"] = "gemini"
    llm_model: str | None = None  # None -> per-provider default
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    timezone: str = "America/Sao_Paulo"
    calendar_id: str = "primary"
    default_event_hours: int = 3
    # pydantic-settings parses list env vars as JSON: REMINDER_MINUTES=[1440,120]
    reminder_minutes: list[int] = Field(default_factory=lambda: [1440, 120])

    db_path: Path = Path("bot.db")
    credentials_path: Path = Path("credentials.json")
    token_path: Path = Path("token.json")


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from .env
