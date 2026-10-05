"""Environment-backed configuration for supported provider adapters."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RESEARCH_ATLAS_", extra="ignore")

    openalex_api_key: SecretStr | None = None
    model_provider: str | None = None
    model_name: str | None = None
    model_base_url: str | None = None
    model_context_tokens: int | None = Field(default=None, gt=0, strict=True)
    embedding_provider: str | None = None
    embedding_model_name: str = "nomic-embed-text"
    embedding_base_url: str | None = None
    ollama_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    kimi_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None
    openai_compatible_api_key: SecretStr | None = None
    model_timeout_seconds: float = Field(default=300, gt=0, le=1800)
    model_max_output_tokens: int = Field(default=8192, gt=0, le=131072)

    @field_validator("model_context_tokens", mode="before")
    @classmethod
    def parse_model_context_tokens(cls, value: object) -> object:
        if value == "":
            return None
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                raise ValueError("model context tokens must be a positive integer") from None
        return value
