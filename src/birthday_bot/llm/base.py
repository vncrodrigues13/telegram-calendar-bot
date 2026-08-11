"""The provider swap seam.

Deliberately tiny and domain-free: it knows about a system prompt, a user
prompt, and a schema. Everything about birthdays, Portuguese, and calendars
lives outside this file. If you find yourself wanting to add a parameter here,
check first whether it belongs in `prompt.py` instead.
"""

from typing import Protocol, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class ExtractionError(RuntimeError):
    """Any provider-side failure, normalized so callers catch one thing."""


class LLMProvider(Protocol):
    async def extract_json(
        self, *, system: str, user: str, schema: type[ModelT]
    ) -> ModelT: ...
