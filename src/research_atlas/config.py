"""Environment-backed configuration for supported provider adapters."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RESEARCH_ATLAS_", extra="ignore")

    openalex_api_key: SecretStr | None = None
    model_provider: str | None = None
    model_name: str | None = None
    model_base_url: str | None = None
    ollama_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    kimi_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None
    openai_compatible_api_key: SecretStr | None = None
    model_timeout_seconds: float = Field(default=600, gt=0, le=1800)
    model_max_output_tokens: int = Field(default=8192, gt=0, le=131072)
