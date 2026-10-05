"""Only OpenAlex credentials and a per-request HTTP deadline are configurable."""

import os

from pydantic import BaseModel, Field, SecretStr, field_validator


class Settings(BaseModel):
    openalex_api_key: SecretStr = Field(repr=False)
    http_timeout_seconds: float = Field(default=20.0, gt=0, le=120, allow_inf_nan=False)

    @field_validator("openalex_api_key")
    @classmethod
    def nonblank_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if not key or not key.isascii() or not key.isprintable() or any(c.isspace() for c in key):
            raise ValueError("set a nonblank RESEARCH_ATLAS_OPENALEX_API_KEY")
        return SecretStr(key)

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            openalex_api_key=SecretStr(os.environ.get("RESEARCH_ATLAS_OPENALEX_API_KEY", "")),
            http_timeout_seconds=float(os.environ.get("RESEARCH_ATLAS_HTTP_TIMEOUT_SECONDS", "20")),
        )
