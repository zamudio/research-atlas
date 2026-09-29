"""Environment-backed configuration for supported provider adapters."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RESEARCH_ATLAS_", extra="ignore")

    openalex_api_key: str | None = None
    crossref_mailto: str | None = None
