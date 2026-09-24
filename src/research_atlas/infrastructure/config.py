"""Environment-backed configuration for provider adapters."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RESEARCH_ATLAS_", extra="ignore")

    openalex_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    zotero_library_id: str | None = None
    zotero_library_type: str = "user"
    zotero_api_key: str | None = None
