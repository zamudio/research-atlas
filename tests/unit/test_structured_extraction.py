import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from research_atlas.application.extraction import extract_source_document
from research_atlas.application.ports.extraction import StructuredExtractor
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.providers.ollama import OllamaExtractor
from research_atlas.infrastructure.providers.openai_responses import OpenAIResponsesExtractor
from research_atlas.infrastructure.providers.structured_extraction import (
    create_structured_extractor,
)
from tests.persistence.conftest import run
from tests.unit.test_extraction import FakeProvider, MemoryPersistence


@pytest.fixture(autouse=True)
def isolated_extraction_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("PROVIDER", "MODEL", "BASE_URL", "API_KEY", "TIMEOUT_SECONDS"):
        monkeypatch.delenv("RESEARCH_ATLAS_EXTRACTION_" + name, raising=False)


def test_settings_load_for_discovery_without_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PROVIDER", "MODEL", "BASE_URL", "API_KEY", "TIMEOUT_SECONDS"):
        monkeypatch.delenv("RESEARCH_ATLAS_EXTRACTION_" + name, raising=False)
    settings = ProviderSettings()
    assert settings.extraction_provider is None and settings.extraction_model is None
    assert settings.extraction_base_url is None and settings.extraction_api_key is None
    assert settings.extraction_timeout_seconds == 600
    with pytest.raises(ValueError, match="provider must be explicitly configured"):
        create_structured_extractor(settings)


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize("model", [None, "", " \t"])
def test_model_required_only_at_construction(provider: str, model: str | None) -> None:
    settings = ProviderSettings(extraction_provider=provider, extraction_model=model)
    with pytest.raises(ValueError, match="model must be explicitly configured"):
        create_structured_extractor(settings)


@pytest.mark.parametrize("provider", [None, "", " ", "unimplemented"])
def test_factory_rejects_missing_or_unknown_provider(provider: str | None) -> None:
    settings = ProviderSettings(extraction_provider=provider, extraction_model="chosen")
    with pytest.raises(ValueError, match="provider"):
        create_structured_extractor(settings)


def test_explicit_builtins_and_safe_configuration() -> None:
    for provider, adapter, endpoint in (
        ("ollama", OllamaExtractor, "http://localhost:11434"),
        ("openai", OpenAIResponsesExtractor, "https://api.openai.com/v1"),
    ):
        settings = ProviderSettings(
            extraction_provider=provider,
            extraction_model="user-selected-model",
            extraction_api_key=SecretStr("test-only-key"),
        )
        extractor: StructuredExtractor = create_structured_extractor(settings)
        assert isinstance(extractor, adapter)
        assert extractor.configuration["provider"] == provider
        assert extractor.configuration["model"] == "user-selected-model"
        assert extractor.configuration["base_url"] == endpoint
        assert "test-only-key" not in json.dumps(dict(extractor.configuration))
        assert "test-only-key" not in repr(settings)


@pytest.mark.parametrize("key", [None, "", " "])
def test_openai_requires_runtime_credential(key: str | None) -> None:
    settings = ProviderSettings(
        extraction_provider="openai",
        extraction_model="chosen",
        extraction_api_key=SecretStr(key) if key is not None else None,
    )
    with pytest.raises(ValueError, match="API key must be configured"):
        create_structured_extractor(settings)


def test_runtime_selection_and_secrets_use_generic_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_ATLAS_EXTRACTION_PROVIDER", "openai")
    monkeypatch.setenv("RESEARCH_ATLAS_EXTRACTION_MODEL", "chosen-alias")
    monkeypatch.setenv("RESEARCH_ATLAS_EXTRACTION_BASE_URL", "https://reference.test/v1/")
    monkeypatch.setenv("RESEARCH_ATLAS_EXTRACTION_API_KEY", "test-only-key")
    monkeypatch.setenv("RESEARCH_ATLAS_EXTRACTION_TIMEOUT_SECONDS", "30")
    settings = ProviderSettings()
    assert isinstance(settings.extraction_api_key, SecretStr)
    provider = create_structured_extractor(settings)
    assert provider.configuration["model"] == "chosen-alias"
    assert provider.configuration["timeout_seconds"] == 30
    assert provider.configuration["base_url"] == "https://reference.test/v1"
    assert "test-only-key" not in repr(settings) + repr(provider.configuration)


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize(
    "url",
    ["ftp://host", "http://user:secret@host", "http://host?key=secret", "http://host#secret"],
)
def test_unsafe_endpoints_cannot_enter_retained_configuration(provider: str, url: str) -> None:
    settings = ProviderSettings(
        extraction_provider=provider,
        extraction_model="chosen",
        extraction_base_url=url,
        extraction_api_key=SecretStr("test-only-key"),
    )
    with pytest.raises(ValueError) as error:
        create_structured_extractor(settings)
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
                extraction_provider=provider,
                extraction_model="chosen",
                extraction_base_url=url,
                extraction_api_key=SecretStr("test-only-key"),
            )
            with pytest.raises(ValueError, match="requires HTTPS") as error:
                extractor = create_structured_extractor(settings, client)
                await extractor.extract("instructions", "document", {})
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
            extractor = create_structured_extractor(
                ProviderSettings(
                    extraction_provider=provider,
                    extraction_model="chosen",
                    extraction_base_url=base_url,
                    extraction_api_key=SecretStr("test-only-key"),
                ),
                client,
            )
            result = await extractor.extract("instructions", "document", {})
            assert result.raw_output == b"{}"

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
            extractor = create_structured_extractor(
                ProviderSettings(
                    extraction_provider="ollama",
                    extraction_model="chosen",
                    extraction_api_key=SecretStr(key) if key is not None else None,
                ),
                client,
            )
            result = await extractor.extract("instructions", "document", {})
            assert result.raw_output == b"{}"

    run(scenario())
    assert calls == 1


def test_custom_protocol_implementation_works_without_runtime_settings_or_factory() -> None:
    async def scenario() -> None:
        provider: StructuredExtractor = FakeProvider()
        store = MemoryPersistence()
        result = await extract_source_document(
            store,
            provider,
            run_id="run",
            source_id=store.parent.source_id,
            document_id=store.parent.document_id,
        )
        assert result.status == "accepted" and store.published is not None

    run(scenario())
