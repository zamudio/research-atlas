import asyncio
import json
from asyncio import run
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from research_atlas.config import ProviderSettings
from research_atlas.extraction import EXTRACTION_INSTRUCTIONS, ExtractionProposal
from research_atlas.passages import build_passage_index
from research_atlas.providers import (
    ModelProviderError,
)
from research_atlas.providers.factory import (
    create_structured_model,
)
from tests.test_extraction import proposal_bytes

KEY = "test-only-credential"
RAW = " \n" + proposal_bytes().decode() + "\n "


@pytest.fixture(autouse=True)
def isolated_extraction_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("PROVIDER", "NAME", "BASE_URL", "TIMEOUT_SECONDS"):
        monkeypatch.delenv("RESEARCH_ATLAS_MODEL_" + name, raising=False)


def envelope(raw: str = RAW, *, status: str = "completed") -> dict[str, object]:
    return {
        "status": status,
        "model": "chosen-snapshot-2026-09-01",
        "error": None,
        "output": [
            {"type": "reasoning", "summary": [{"text": "secret hidden reasoning"}]},
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": raw}],
            },
        ],
        "other_metadata": "secret envelope",
    }


def settings(provider: str = "openai", *, timeout: float = 600) -> ProviderSettings:
    return ProviderSettings(
        model_provider=provider,
        model_name="chosen-alias",
        model_base_url="https://reference.test/v1" if provider == "openai" else None,
        openai_api_key=SecretStr(KEY),
        model_timeout_seconds=timeout,
    )


def test_openai_stateless_strict_request_and_exact_output_without_alias_equality() -> None:
    schema = ExtractionProposal.model_json_schema()
    indexed = build_passage_index(b"Results\n\nNo change.\n").model_text
    raw = ' \n{ "evidence": [], "note": "caf\u00e9" }\n '
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert (
            request.method == "POST" and str(request.url) == "https://reference.test/v1/responses"
        )
        assert request.headers["Authorization"] == "Bearer " + KEY
        assert json.loads(request.content) == {
            "model": "chosen-alias",
            "instructions": EXTRACTION_INSTRUCTIONS,
            "input": indexed,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "atlas_output",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        assert KEY.encode() not in request.content
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 600
        )
        return httpx.Response(200, json=envelope(raw))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = create_structured_model(settings(), client)
            result = await provider.generate(EXTRACTION_INSTRUCTIONS, indexed, schema)
            assert result == raw.encode()
            assert "hidden reasoning" not in repr(result) and "secret envelope" not in repr(result)

    run(scenario())
    assert calls == 1


def test_generated_extraction_schema_is_closed_and_all_fields_required() -> None:
    def walk(value: object) -> None:
        if isinstance(value, dict):
            node = cast(dict[str, object], value)
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(cast(list[str], node["required"])) == set(
                    cast(dict[str, object], node["properties"])
                )
            assert "default" not in node and "propertyNames" not in node
            for child in node.values():
                walk(child)
        elif isinstance(value, list):
            for child in cast(list[object], value):
                walk(child)

    walk(ExtractionProposal.model_json_schema())


@pytest.mark.parametrize("fault", ["http", "redirect", "transport", "timeout", "deadline", "json"])
def test_openai_request_failures_are_safe_and_never_retried(fault: str) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if fault == "transport":
            raise httpx.ConnectError(KEY, request=request)
        if fault == "timeout":
            raise httpx.ReadTimeout(KEY, request=request)
        if fault == "deadline":
            await asyncio.sleep(0.1)
            return httpx.Response(200, json=envelope())
        if fault == "redirect":
            return httpx.Response(302, headers={"Location": "https://elsewhere.test"}, text=KEY)
        return httpx.Response(500 if fault == "http" else 200, text=KEY)

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            provider = create_structured_model(settings(timeout=0.01), client)
            with pytest.raises(ModelProviderError) as error:
                await provider.generate("prompt", "doc", {})
            code = (
                "openai_http_failure"
                if fault in {"http", "redirect"}
                else (
                    "openai_malformed_envelope" if fault == "json" else "openai_transport_failure"
                )
            )
            assert str(error.value) == code
            assert KEY not in str(error.value)

    run(scenario())
    assert calls == 1


@pytest.mark.parametrize(
    "status,code",
    [
        ("incomplete", "openai_incomplete_response"),
        ("queued", "openai_incomplete_response"),
        ("in_progress", "openai_incomplete_response"),
        ("failed", "openai_failed_response"),
        ("cancelled", "openai_failed_response"),
    ],
)
def test_openai_noncompleted_responses_fail(status: str, code: str) -> None:
    raw = ' \n{"evidence": ['
    body = envelope(raw, status=status)
    body["incomplete_details"] = {"reason": "max_output_tokens", "other": KEY}

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            with pytest.raises(ModelProviderError, match=code):
                await create_structured_model(settings(), client).generate("prompt", "doc", {})

    run(scenario())


@pytest.mark.parametrize(
    "fault,code,expected_raw",
    [
        ("list", "openai_malformed_envelope", None),
        ("status", "openai_malformed_envelope", None),
        ("output", "openai_malformed_envelope", None),
        ("message", "openai_malformed_envelope", None),
        ("content", "openai_malformed_envelope", None),
        ("text", "openai_malformed_envelope", None),
        ("multiple", "openai_malformed_envelope", None),
        ("refusal", "openai_refusal", None),
        ("message_incomplete", "openai_incomplete_response", RAW.encode()),
        ("incomplete_details", "openai_incomplete_response", RAW.encode()),
        ("error", "openai_failed_response", RAW.encode()),
        ("no_output", "openai_empty_output", None),
        ("empty", "openai_empty_output", b" \n"),
    ],
)
def test_openai_response_validation(fault: str, code: str, expected_raw: bytes | None) -> None:
    body = envelope()
    outputs = cast(list[dict[str, object]], body["output"])
    message = outputs[1]
    response_body: object = body
    if fault == "list":
        response_body = []
    elif fault == "status":
        body["status"] = {"secret": KEY}
    elif fault == "output":
        body["output"] = None
    elif fault == "message":
        message["role"] = "user"
    elif fault == "content":
        message["content"] = None
    elif fault == "text":
        message["content"] = [{"type": "output_text", "text": 42}]
    elif fault == "multiple":
        outputs.append(message)
    elif fault == "refusal":
        message["content"] = [{"type": "refusal", "refusal": KEY}]
    elif fault == "message_incomplete":
        message["status"] = "incomplete"
    elif fault == "error":
        body["error"] = {"message": KEY}
    elif fault == "incomplete_details":
        body["incomplete_details"] = {"reason": "max_output_tokens"}
    elif fault == "no_output":
        body["output"] = []
    elif fault == "empty":
        message["content"] = [{"type": "output_text", "text": " \n"}]
    else:
        body["model"] = None

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_body))
        ) as client:
            with pytest.raises(ModelProviderError) as error:
                await create_structured_model(settings(), client).generate("prompt", "doc", {})
            assert KEY not in str(error.value) and error.value.__cause__ is None

    run(scenario())


def test_only_final_text_is_retained_and_text_parts_preserve_exact_bytes() -> None:
    body = envelope()
    outputs = cast(list[dict[str, object]], body["output"])
    outputs.insert(
        1,
        {
            "type": "message",
            "role": "assistant",
            "phase": "commentary",
            "status": "completed",
            "content": [{"type": "output_text", "text": "secret commentary"}],
        },
    )
    outputs[2]["phase"] = "final_answer"
    outputs[2]["content"] = [
        {"type": "output_text", "text": RAW[:10]},
        {"type": "output_text", "text": RAW[10:]},
    ]

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            result = await create_structured_model(settings(), client).generate("prompt", "doc", {})
            assert result == RAW.encode()
            assert "commentary" not in repr(result)

    run(scenario())
