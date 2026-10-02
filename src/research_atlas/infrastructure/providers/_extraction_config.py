"""Runtime extraction validation; shared settings can load without an extractor."""

import httpx
from pydantic import SecretStr

from research_atlas.infrastructure.config import ProviderSettings


def extraction_model(settings: ProviderSettings) -> str:
    model = settings.extraction_model
    if model is None or not model.strip():
        raise ValueError("extraction model must be explicitly configured")
    if len(model) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in model):
        raise ValueError("extraction model identity must be bounded printable text")
    return model


def extraction_base_url(
    settings: ProviderSettings, default: str | None, *, api_key: SecretStr | None = None
) -> str:
    value = settings.extraction_base_url
    value = value.rstrip("/") if value else default
    if not value:
        raise ValueError("extraction base URL must be explicitly configured")
    try:
        url = httpx.URL(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise ValueError
    except httpx.InvalidURL, ValueError:
        raise ValueError(
            "extraction base URL requires HTTP(S) without credentials/query/fragment"
        ) from None
    key = api_key if api_key is not None else settings.extraction_api_key
    if (
        key is not None
        and key.get_secret_value().strip()
        and url.scheme == "http"
        and url.host not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("authenticated extraction requires HTTPS except for loopback endpoints")
    return str(url)


def extraction_credential(
    key: SecretStr | None, provider: str, *, required: bool = True
) -> SecretStr | None:
    if key is None or not key.get_secret_value().strip():
        if required:
            raise ValueError(f"{provider} extraction API key must be configured")
        return None
    return key


def preferred_credential(primary: SecretStr | None, legacy: SecretStr | None) -> SecretStr | None:
    """Blank provider-specific variables in .env.example must not hide a legacy key."""
    return primary if primary is not None and primary.get_secret_value().strip() else legacy
