from asyncio import run
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from research_atlas.config import ProviderSettings
from research_atlas.providers.factory import (
    create_structured_model,
)


@pytest.fixture(autouse=True)
def isolated_extraction_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("PROVIDER", "NAME", "BASE_URL", "TIMEOUT_SECONDS"):
        monkeypatch.delenv("RESEARCH_ATLAS_MODEL_" + name, raising=False)


def test_settings_load_for_discovery_without_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PROVIDER", "NAME", "BASE_URL", "TIMEOUT_SECONDS"):
        monkeypatch.delenv("RESEARCH_ATLAS_MODEL_" + name, raising=False)
    settings = ProviderSettings()
    assert settings.model_provider is None and settings.model_name is None
    assert settings.model_base_url is None
    assert settings.model_timeout_seconds == 600
    with pytest.raises(ValueError, match="provider must be explicitly configured"):
        create_structured_model(settings)


@pytest.mark.parametrize(
    "provider",
    [
        "ollama",
        "openai",
        "anthropic",
        "gemini",
        "kimi",
        "openrouter",
        "deepseek",
        "openai_compatible",
    ],
)
@pytest.mark.parametrize("model", [None, "", " \t"])
def test_model_required_only_at_construction(provider: str, model: str | None) -> None:
    settings = ProviderSettings(model_provider=provider, model_name=model)
    with pytest.raises(ValueError, match="model must be explicitly configured"):
        create_structured_model(settings)


@pytest.mark.parametrize("provider", [None, "", " ", "unimplemented"])
def test_factory_rejects_missing_or_unknown_provider(provider: str | None) -> None:
    settings = ProviderSettings(model_provider=provider, model_name="chosen")
    with pytest.raises(ValueError, match="provider"):
        create_structured_model(settings)


@pytest.mark.parametrize("key", [None, "", " "])
def test_openai_requires_runtime_credential(key: str | None) -> None:
    settings = ProviderSettings(
        model_provider="openai",
        model_name="chosen",
        openai_api_key=SecretStr(key) if key is not None else None,
    )
    with pytest.raises(ValueError, match="API key must be configured"):
        create_structured_model(settings)


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize(
    "url",
    ["ftp://host", "http://user:secret@host", "http://host?key=secret", "http://host#secret"],
)
def test_unsafe_endpoints_rejected(provider: str, url: str) -> None:
    settings = ProviderSettings(
        model_provider=provider,
        model_name="chosen",
        model_base_url=url,
        openai_api_key=SecretStr("test-only-key") if provider == "openai" else None,
        ollama_api_key=SecretStr("test-only-key") if provider == "ollama" else None,
    )
    with pytest.raises(ValueError) as error:
        create_structured_model(settings)
    assert "secret" not in str(error.value) and "test-only-key" not in str(error.value)


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize("host", ["remote.test", "localhost.remote.test", "192.168.1.2", "[::2]"])
def test_authenticated_remote_http_rejected_before_io(provider: str, host: str) -> None:
    calls = 0
    url = f"http://{host}/private-endpoint"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("unsafe endpoint must not receive a request")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            settings = ProviderSettings(
                model_provider=provider,
                model_name="chosen",
                model_base_url=url,
                openai_api_key=SecretStr("test-only-key") if provider == "openai" else None,
                ollama_api_key=SecretStr("test-only-key") if provider == "ollama" else None,
            )
            with pytest.raises(ValueError, match="requires HTTPS") as error:
                extractor = create_structured_model(settings, client)
                await extractor.generate("instructions", "document", {})
            message = str(error.value)
            assert all(
                value not in message for value in ("test-only-key", url, host, "private-endpoint")
            )

    run(scenario())
    assert calls == 0


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [("openai", None)]
    + [
        (provider, endpoint)
        for provider in ("openai", "ollama")
        for endpoint in (
            "http://localhost:11434",
            "http://127.0.0.1:11434",
            "http://[::1]:11434",
            "https://remote.test/v1",
        )
    ],
)
def test_authenticated_allowed_endpoints_send_credential(
    provider: str, base_url: str | None
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        endpoint = base_url or "https://api.openai.com/v1"
        suffix = "/responses" if provider == "openai" else "/api/chat"
        assert str(request.url) == endpoint + suffix
        assert request.headers["Authorization"] == "Bearer test-only-key"
        if provider == "ollama":
            return httpx.Response(
                200, json={"model": "chosen", "done": True, "message": {"content": "{}"}}
            )
        return httpx.Response(
            200,
            json={
                "model": "chosen",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "{}"}],
                    }
                ],
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            extractor = create_structured_model(
                ProviderSettings(
                    model_provider=provider,
                    model_name="chosen",
                    model_base_url=base_url,
                    openai_api_key=SecretStr("test-only-key") if provider == "openai" else None,
                    ollama_api_key=SecretStr("test-only-key") if provider == "ollama" else None,
                ),
                client,
            )
            result = await extractor.generate("instructions", "document", {})
            assert result == b"{}"

    run(scenario())
    assert calls == 1


@pytest.mark.parametrize("key", [None, "", " \t"])
def test_unauthenticated_ollama_local_http_remains_allowed(key: str | None) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert str(request.url) == "http://localhost:11434/api/chat"
        assert "Authorization" not in request.headers
        return httpx.Response(
            200, json={"model": "chosen", "done": True, "message": {"content": "{}"}}
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            extractor = create_structured_model(
                ProviderSettings(
                    model_provider="ollama",
                    model_name="chosen",
                    ollama_api_key=SecretStr(key) if key is not None else None,
                ),
                client,
            )
            result = await extractor.generate("instructions", "document", {})
            assert result == b"{}"

    run(scenario())
    assert calls == 1
