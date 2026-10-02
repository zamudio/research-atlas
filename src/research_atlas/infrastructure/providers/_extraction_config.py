"""Runtime extraction validation; shared settings can load without an extractor."""

import httpx

from research_atlas.infrastructure.config import ProviderSettings


def extraction_model(settings: ProviderSettings) -> str:
    model = settings.extraction_model
    if model is None or not model.strip():
        raise ValueError("extraction model must be explicitly configured")
    return model


def extraction_base_url(settings: ProviderSettings, default: str) -> str:
    value = settings.extraction_base_url
    value = value.rstrip("/") if value else default
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
    key = settings.extraction_api_key
    if (
        key is not None
        and key.get_secret_value().strip()
        and url.scheme == "http"
        and url.host not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("authenticated extraction requires HTTPS except for loopback endpoints")
    return str(url)
