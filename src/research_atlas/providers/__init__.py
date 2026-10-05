"""Provider-neutral structured generation for a caller-supplied JSON schema."""

from collections.abc import Mapping
from typing import Protocol


class ModelProviderError(Exception):
    """Safe local failure code without remote bodies, credentials, or input text."""


class StructuredModel(Protocol):
    async def fits_context(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bool:
        """Whether the complete request, including output reserve, fits this model."""
        ...

    async def generate(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bytes: ...
