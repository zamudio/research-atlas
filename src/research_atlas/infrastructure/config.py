"""Environment-backed configuration for supported provider adapters."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RESEARCH_ATLAS_", extra="ignore")

    openalex_api_key: str | None = None
    crossref_mailto: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    extraction_model: str = Field(default="qwen3.5:4b", min_length=1, pattern=r"\S")
    extraction_timeout_seconds: float = Field(default=600, gt=0, le=1800)
