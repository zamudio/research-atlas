"""Runtime model configuration validation."""

import httpx
from pydantic import SecretStr

from research_atlas.config import ProviderSettings


def model_name(settings: ProviderSettings) -> str:
    model = settings.model_name
    if model is None or not model.strip():
        raise ValueError("model must be explicitly configured")
    if len(model) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in model):
        raise ValueError("model identity must be bounded printable text")
    return model


def model_base_url(
    settings: ProviderSettings, default: str | None, *, api_key: SecretStr | None = None
) -> str:
    value = settings.model_base_url
    value = value.rstrip("/") if value else default
    if not value:
        raise ValueError("model base URL must be explicitly configured")
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
            "model base URL requires HTTP(S) without credentials/query/fragment"
        ) from None
    if (
        api_key is not None
        and api_key.get_secret_value().strip()
        and url.scheme == "http"
        and url.host not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("authenticated generation requires HTTPS except for loopback endpoints")
    return str(url)


def model_credential(
    key: SecretStr | None, provider: str, *, required: bool = True
) -> SecretStr | None:
    if key is None or not key.get_secret_value().strip():
        if required:
            raise ValueError(f"{provider} API key must be configured")
        return None
    return key
