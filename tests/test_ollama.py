import asyncio
import json
from asyncio import run
from collections.abc import Mapping

import httpx
import pytest

from research_atlas.config import ProviderSettings
from research_atlas.extraction import EXTRACTION_INSTRUCTIONS, ExtractionProposal
from research_atlas.passages import build_passage_index
from research_atlas.providers import ModelProviderError
from research_atlas.providers.ollama import OllamaModel

MODEL_INFO = {
    "model_info": {"general.architecture": "reference", "reference.context_length": 32768}
}


def test_ollama_request_contract_configured_endpoint_and_exact_content() -> None:
    schema = ExtractionProposal.model_json_schema()
    indexed_text = build_passage_index(b"Results\n\nNo change.\n").model_text
    raw = ' \n{ "evidence": [] }\n '
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 600
        )
        if request.url.path == "/api/show":
            assert request.method == "POST"
            assert str(request.url) == "http://reference.test:11435/api/show"
            assert json.loads(request.content) == {"model": "reference:4b"}
            assert "Authorization" not in request.headers
            return httpx.Response(200, json=MODEL_INFO)
        assert (
            request.method == "POST" and str(request.url) == "http://reference.test:11435/api/chat"
        )
        payload = json.loads(request.content)
        assert payload == {
            "model": "reference:4b",
            "stream": False,
            "think": False,
            "format": schema,
            "messages": [
                {"role": "system", "content": EXTRACTION_INSTRUCTIONS},
                {"role": "user", "content": indexed_text},
            ],
            "options": {"temperature": 0, "num_ctx": 32768},
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
                "model": "reference:4b",
                "done": True,
                "done_reason": "stop",
                "message": {"content": raw, "thinking": "hidden reasoning"},
                "other_metadata": "discard",
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaModel(
                ProviderSettings(
                    model_base_url="http://reference.test:11435/",
                    model_name="reference:4b",
                ),
                client,
            )
            result = await provider.generate(EXTRACTION_INSTRUCTIONS, indexed_text, schema)
            assert result == raw.encode("utf-8")
            assert "thinking" not in repr(result) and "other_metadata" not in repr(result)

    run(scenario())
    assert calls == 2


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
        if request.url.path == "/api/show":
            return httpx.Response(200, json=MODEL_INFO)
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
            with pytest.raises(ModelProviderError) as error:
                await OllamaModel(ProviderSettings(model_name="reference:4b"), client).generate(
                    "prompt", "doc", {}
                )
            assert "secret" not in str(error.value)
            assert error.value.__cause__ is None

    run(scenario())
    assert calls == 2


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
    raw = ' \n{ "evidence": [], "note": "caf\u00e9" }\n '
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/api/show":
            return httpx.Response(200, json=MODEL_INFO)
        return httpx.Response(
            200,
            json={
                "model": "reference:4b",
                "message": {"content": raw, "thinking": "hidden reasoning"},
                **completion,
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaModel(ProviderSettings(model_name="reference:4b"), client)
            if successful:
                assert (await provider.generate("prompt", "doc", {})) == raw.encode()
            else:
                with pytest.raises(
                    ModelProviderError, match="ollama_incomplete_completion"
                ) as error:
                    await provider.generate("prompt", "doc", {})
                assert "thinking" not in repr(error.value)

    run(scenario())
    assert calls == 2


def test_ollama_environment_configuration_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_ATLAS_MODEL_NAME", "reference:8b")
    monkeypatch.setenv("RESEARCH_ATLAS_MODEL_BASE_URL", "http://localhost:12434")
    assert isinstance(OllamaModel(), OllamaModel)
    for url in (
        "ftp://localhost",
        "http://user:secret@localhost",
        "http://localhost?token=secret",
        "http://localhost#secret",
        "http://localhost:invalid",
    ):
        with pytest.raises(ValueError):
            OllamaModel(ProviderSettings(model_base_url=url, model_name="reference"))
    with pytest.raises(ValueError):
        ProviderSettings(model_timeout_seconds=1801)


@pytest.mark.parametrize("architecture,maximum", [("llama", 8192), ("qwen35", 262144)])
@pytest.mark.parametrize("override", [None, 4096, "maximum"])
def test_ollama_context_default_override_and_metadata_cache(
    architecture: str, maximum: int, override: int | str | None
) -> None:
    configured = maximum if override == "maximum" else override
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/show":
            assert json.loads(request.content) == {"model": "reference:4b"}
            return httpx.Response(
                200,
                json={
                    "model_info": {
                        "general.architecture": architecture,
                        architecture + ".context_length": maximum,
                        architecture + ".embedding_length": 384,
                    },
                    "parameters": "num_ctx 2048",
                    "template": "private model template",
                },
            )
        assert request.url.path == "/api/chat"
        assert json.loads(request.content)["options"] == {
            "temperature": 0,
            "num_ctx": maximum if configured is None else configured,
        }
        return httpx.Response(
            200, json={"model": "reference:4b", "done": True, "message": {"content": "{}"}}
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaModel(
                ProviderSettings.model_validate(
                    {"model_name": "reference:4b", "model_context_tokens": configured}
                ),
                client,
            )
            for _ in range(2):
                assert (
                    await provider.generate("private instructions", "private document", {}) == b"{}"
                )
            state = repr(vars(provider))
            for private in ("private model template", "private instructions", "private document"):
                assert private not in state

    run(scenario())
    assert calls == ["/api/show", "/api/chat", "/api/chat"]


def test_ollama_context_override_above_maximum_fails_before_chat() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=MODEL_INFO)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaModel(
                ProviderSettings(model_name="reference:4b", model_context_tokens=32769), client
            )
            with pytest.raises(
                ModelProviderError, match=r"^ollama_context_override_exceeds_maximum$"
            ):
                await provider.generate("private prompt", "private document", {})

    run(scenario())
    assert calls == ["/api/show"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"model_info": None},
        {"model_info": []},
        {"model_info": "private model information"},
        {"model_info": {}},
        {"model_info": {"reference.embedding_length": 384}},
        {"model_info": {"context_length": 32768}},
        {"model_info": {".context_length": 32768}},
        {"model_info": {"reference.context_length": "32768"}},
        {"model_info": {"reference.context_length": 32768.0}},
        {"model_info": {"reference.context_length": None}},
        {"model_info": {"reference.context_length": True}},
        {"model_info": {"reference.context_length": 0}},
        {"model_info": {"reference.context_length": -1}},
        {"model_info": {"reference.context_length": {"private": 32768}}},
        {"model_info": {"reference.context_length": 32768, "other.context_length": 8192}},
        {"model_info": {"reference.context_length": 32768, "other.context_length": 32768}},
        {"model_info": {"reference.context_length": 32768, "other.context_length": "private"}},
        {"parameters": "num_ctx 32768", "modelfile": "PARAMETER num_ctx 32768"},
    ],
)
@pytest.mark.parametrize("override", [None, 1024])
def test_ollama_invalid_context_metadata_fails_safely_without_fallback(
    body: dict[str, object], override: int | None
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=body)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaModel(
                ProviderSettings(model_name="reference:4b", model_context_tokens=override), client
            )
            with pytest.raises(ModelProviderError) as error:
                await provider.generate("private prompt", "private document", {})
            assert str(error.value) == "ollama_invalid_context_metadata"
            assert error.value.__cause__ is None

    run(scenario())
    assert calls == ["/api/show"]


@pytest.mark.parametrize(
    "fault",
    ["transport", "timeout", "deadline", "400", "401", "429", "500", "redirect", "json", "list"],
)
def test_ollama_metadata_request_failures_are_safe_and_not_retried(fault: str) -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if fault == "transport":
            raise httpx.ConnectError("private diagnostics", request=request)
        if fault == "timeout":
            raise httpx.ReadTimeout("private diagnostics", request=request)
        if fault == "deadline":
            await asyncio.sleep(0.05)
        if fault == "redirect":
            return httpx.Response(
                302, headers={"Location": "https://other.test"}, text="private diagnostics"
            )
        if fault.isdigit():
            return httpx.Response(int(fault), text="private diagnostics")
        if fault == "json":
            return httpx.Response(200, text="private diagnostics")
        return httpx.Response(200, json=[])

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            provider = OllamaModel(
                ProviderSettings(model_name="reference:4b", model_timeout_seconds=0.01), client
            )
            with pytest.raises(ModelProviderError) as error:
                await provider.generate("private prompt", "private document", {})
            suffix = (
                "transport_failure"
                if fault in {"transport", "timeout", "deadline"}
                else ("malformed_envelope" if fault in {"json", "list"} else "http_failure")
            )
            assert str(error.value) == "ollama_" + suffix
            assert error.value.__cause__ is None

    run(scenario())
    assert calls == ["/api/show"]


def test_ollama_failed_metadata_discovery_is_not_cached() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(200, json={})
        if request.url.path == "/api/show":
            return httpx.Response(200, json=MODEL_INFO)
        return httpx.Response(
            200, json={"model": "reference:4b", "done": True, "message": {"content": "{}"}}
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaModel(ProviderSettings(model_name="reference:4b"), client)
            with pytest.raises(ModelProviderError, match="ollama_invalid_context_metadata"):
                await provider.generate("prompt", "doc", {})
            assert await provider.generate("prompt", "doc", {}) == b"{}"

    run(scenario())
    assert calls == ["/api/show", "/api/show", "/api/chat"]
