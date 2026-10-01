import json
from collections.abc import Mapping

import httpx
import pytest

from research_atlas.application.ports.extraction import ExtractionProviderError
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.providers.ollama import OllamaExtractor
from research_atlas.schemas.extraction_proposal import ExtractionProposal
from tests.persistence.conftest import run


def test_ollama_request_contract_configured_endpoint_and_exact_content() -> None:
    schema = ExtractionProposal.model_json_schema()
    raw = ' \n{ "studies": [] }\n '
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert (
            request.method == "POST" and str(request.url) == "http://reference.test:11435/api/chat"
        )
        payload = json.loads(request.content)
        assert payload == {
            "model": "qwen-next:4b",
            "stream": False,
            "think": False,
            "format": schema,
            "messages": [
                {"role": "system", "content": "instructions"},
                {"role": "user", "content": "exact document"},
            ],
            "options": {"temperature": 0},
        }
        assert request.extensions["timeout"] == {
            "connect": 600,
            "read": 600,
            "write": 600,
            "pool": 600,
        }
        return httpx.Response(
            200,
            json={
                "model": "qwen-next:4b",
                "done": True,
                "done_reason": "stop",
                "message": {"content": raw, "thinking": "hidden reasoning"},
                "other_metadata": "discard",
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaExtractor(
                ProviderSettings(
                    ollama_base_url="http://reference.test:11435/",
                    extraction_model="qwen-next:4b",
                ),
                client,
            )
            result = await provider.extract("instructions", "exact document", schema)
            assert result.raw_output == raw.encode("utf-8")
            assert result.model_version == "qwen-next:4b"
            assert result.tool_name == "atlas-ollama-chat"
            assert provider.configuration["think"] is False
            assert "thinking" not in repr(result) and "other_metadata" not in repr(result)

    run(scenario())
    assert calls == 1


@pytest.mark.parametrize(
    "fault",
    [
        "transport",
        "timeout",
        "status",
        "redirect",
        "json",
        "list",
        "message",
        "content",
        "empty",
        "model",
    ],
)
def test_ollama_safe_failures_have_no_body_secrets_or_generation_retries(fault: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if fault == "transport":
            raise httpx.ConnectError("secret provider details", request=request)
        if fault == "timeout":
            raise httpx.ReadTimeout("secret provider details", request=request)
        if fault in {"status", "redirect"}:
            return httpx.Response(500 if fault == "status" else 302, text="secret provider details")
        if fault == "json":
            return httpx.Response(200, text="secret provider details")
        bodies: Mapping[str, object] = {
            "list": [],
            "message": {"message": None},
            "content": {"message": {"content": 42}},
            "empty": {"done": True, "message": {"content": " "}},
            "model": {"done": True, "message": {"content": "{}"}, "model": "unexpected"},
        }
        return httpx.Response(200, json=bodies[fault])

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ExtractionProviderError) as error:
                await OllamaExtractor(ProviderSettings(), client).extract("prompt", "doc", {})
            assert "secret" not in str(error.value)
            assert error.value.__cause__ is None
            expected_raw = b"{}" if fault == "model" else b" " if fault == "empty" else None
            assert error.value.raw_output == expected_raw

    run(scenario())
    assert calls == 1


@pytest.mark.parametrize(
    "completion,successful",
    [
        ({"done": True, "done_reason": "stop"}, True),
        ({"done": True}, True),
        ({"done": False, "done_reason": "stop"}, False),
        ({"done": False}, False),
        ({"done": True, "done_reason": "length"}, False),
        ({"done": True, "done_reason": "error"}, False),
        ({"done": True, "done_reason": ""}, False),
        ({"done": True, "done_reason": None}, False),
        ({"done": True, "done_reason": 1}, False),
        ({"done": 1, "done_reason": "stop"}, False),
        ({"done": "true", "done_reason": "stop"}, False),
        ({"done": None}, False),
        ({}, False),
    ],
)
def test_ollama_requires_normal_completion_and_preserves_returned_bytes(
    completion: dict[str, object],
    successful: bool,
) -> None:
    raw = ' \n{ "studies": [], "note": "caf\u00e9" }\n '
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "model": "qwen3.5:4b",
                "message": {"content": raw, "thinking": "hidden reasoning"},
                **completion,
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaExtractor(ProviderSettings(extraction_model="qwen3.5:4b"), client)
            if successful:
                assert (await provider.extract("prompt", "doc", {})).raw_output == raw.encode()
            else:
                with pytest.raises(
                    ExtractionProviderError, match="ollama_incomplete_completion"
                ) as error:
                    await provider.extract("prompt", "doc", {})
                assert error.value.raw_output == raw.encode("utf-8")
                assert "thinking" not in repr(error.value)

    run(scenario())
    assert calls == 1


def test_ollama_environment_configuration_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_ATLAS_EXTRACTION_MODEL", "qwen-next:8b")
    monkeypatch.setenv("RESEARCH_ATLAS_OLLAMA_BASE_URL", "http://localhost:12434")
    provider = OllamaExtractor()
    assert provider.configuration["model"] == "qwen-next:8b"
    assert provider.configuration["base_url"] == "http://localhost:12434"
    for url in ("ftp://localhost", "http://user:secret@localhost", "http://localhost?token=secret"):
        with pytest.raises(ValueError):
            OllamaExtractor(ProviderSettings(ollama_base_url=url))
    with pytest.raises(ValueError):
        ProviderSettings(extraction_timeout_seconds=1801)
