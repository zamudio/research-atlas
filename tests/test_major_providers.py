"""Offline provider coverage and the unchanged application/passage-evidence contract."""

import asyncio
import copy
import json
from asyncio import run
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from research_atlas import extract_evidence
from research_atlas.config import ProviderSettings
from research_atlas.extraction import EXTRACTION_INSTRUCTIONS, ExtractionProposal
from research_atlas.passages import build_passage_index
from research_atlas.providers import ModelProviderError, StructuredModel
from research_atlas.providers.anthropic import AnthropicModel, anthropic_schema
from research_atlas.providers.deepseek_responses import DeepSeekResponsesModel
from research_atlas.providers.factory import (
    create_structured_model,
)
from research_atlas.providers.gemini import (
    GeminiInteractionsModel,
    gemini_schema,
)
from research_atlas.providers.kimi import KimiModel, kimi_schema
from research_atlas.providers.ollama import OllamaModel
from research_atlas.providers.openai_compatible_chat import (
    OpenAICompatibleChatModel,
)
from research_atlas.providers.openai_responses import OpenAIResponsesModel
from research_atlas.providers.openrouter import OpenRouterModel
from tests.test_extraction import PASSAGE, SOURCE, XML, proposal_bytes

KEY = "test-only-credential"
DISCARDED = "private-provider-diagnostics-and-reasoning"
RAW = " \n" + proposal_bytes().decode() + "\n "


@pytest.mark.parametrize(
    "provider_name",
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
@pytest.mark.parametrize("fault", [None, "summary", "unknown", "duplicate", "quotation"])
def test_all_providers_use_canonical_validation_and_grounding(
    provider_name: str, fault: str | None
) -> None:
    case = next(case for case in CASES if case.name == provider_name)
    proposal = json.loads(proposal_bytes())
    item = proposal["evidence"][0]
    if fault == "summary":
        item["summary"] = " "
    elif fault == "unknown":
        item["evidence_passage_ids"] = ["p9999"]
    elif fault == "duplicate":
        item["evidence_passage_ids"] = ["p0001", "p0001"]
    elif fault == "quotation":
        item["passages"] = ["model-written quotation"]
    question = "What does response time tell us?"

    def handler(request: httpx.Request) -> httpx.Response:
        if case.name == "ollama" and request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"reference.context_length": 32768}})
        assert question in request.content.decode()
        return httpx.Response(200, json=envelope(case, json.dumps(proposal)))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = create_structured_model(settings(case, model_context_tokens=16384), client)
            if fault:
                with pytest.raises(ValueError):
                    await extract_evidence(
                        question=question, source=SOURCE, content=XML, model=model
                    )
            else:
                result = await extract_evidence(
                    question=question, source=SOURCE, content=XML, model=model
                )
                assert result.evidence[0].passages == (PASSAGE,)
                assert result.source is SOURCE

    run(scenario())


@dataclass(frozen=True)
class ProviderCase:
    name: str
    adapter: type
    base: str
    suffix: str
    key_field: str
    header: str


CASES = (
    ProviderCase(
        "openai",
        OpenAIResponsesModel,
        "https://api.openai.com/v1",
        "/responses",
        "openai_api_key",
        "Authorization",
    ),
    ProviderCase(
        "anthropic",
        AnthropicModel,
        "https://api.anthropic.com/v1",
        "/messages",
        "anthropic_api_key",
        "x-api-key",
    ),
    ProviderCase(
        "gemini",
        GeminiInteractionsModel,
        "https://generativelanguage.googleapis.com/v1",
        "/interactions",
        "gemini_api_key",
        "x-goog-api-key",
    ),
    ProviderCase(
        "openrouter",
        OpenRouterModel,
        "https://openrouter.ai/api/v1",
        "/chat/completions",
        "openrouter_api_key",
        "Authorization",
    ),
    ProviderCase(
        "deepseek",
        DeepSeekResponsesModel,
        "https://api.deepseek.com",
        "/responses",
        "deepseek_api_key",
        "Authorization",
    ),
    ProviderCase(
        "ollama",
        OllamaModel,
        "http://localhost:11434",
        "/api/chat",
        "ollama_api_key",
        "Authorization",
    ),
    ProviderCase(
        "kimi",
        KimiModel,
        "https://api.moonshot.ai/v1",
        "/chat/completions",
        "kimi_api_key",
        "Authorization",
    ),
    ProviderCase(
        "openai_compatible",
        OpenAICompatibleChatModel,
        "https://compatible.test/v1",
        "/chat/completions",
        "openai_compatible_api_key",
        "Authorization",
    ),
)
NEW_CASES = tuple(case for case in CASES if case.name not in {"openai", "ollama"})
CHAT_CASES = tuple(case for case in CASES if case.suffix == "/chat/completions")


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for field in ProviderSettings.model_fields:
        monkeypatch.delenv("RESEARCH_ATLAS_" + field.upper(), raising=False)


def settings(case: ProviderCase, **overrides: object) -> ProviderSettings:
    values: dict[str, object] = {
        "model_provider": case.name,
        "model_name": "chosen-alias",
        case.key_field: SecretStr(KEY),
    }
    if case.name == "openai_compatible":
        values["model_base_url"] = case.base
    values.update(overrides)
    return ProviderSettings.model_validate(values)


def envelope(case: ProviderCase, raw: str = RAW) -> dict[str, object]:
    model = "chosen-alias" if case.name == "ollama" else "chosen-snapshot"
    if case.name in {"openai", "deepseek"}:
        return {
            "model": model,
            "status": "completed",
            "output": [
                {"type": "reasoning", "content": [{"text": DISCARDED}]},
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": raw}],
                },
            ],
            "diagnostics": DISCARDED,
        }
    if case.name == "anthropic":
        return {
            "type": "message",
            "role": "assistant",
            "model": model,
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "content": [
                {"type": "thinking", "thinking": DISCARDED},
                {"type": "redacted_thinking", "data": DISCARDED},
                {"type": "text", "text": raw},
            ],
            "diagnostics": DISCARDED,
        }
    if case.name == "gemini":
        return {
            "id": DISCARDED,
            "model": model,
            "status": "completed",
            "steps": [
                {"type": "thought", "summary": [{"type": "text", "text": DISCARDED}]},
                {"type": "model_output", "content": [{"type": "text", "text": DISCARDED}]},
                {"type": "model_output", "content": [{"type": "text", "text": raw}]},
            ],
            "diagnostics": DISCARDED,
        }
    if case.name == "ollama":
        return {
            "model": model,
            "done": True,
            "done_reason": "stop",
            "message": {"content": raw, "thinking": DISCARDED},
        }
    return {
        "model": model,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": raw,
                    "reasoning_content": DISCARDED,
                    "reasoning_details": [{"text": DISCARDED}],
                },
            }
        ],
        "diagnostics": DISCARDED,
    }


def expected_payload(
    case: ProviderCase, schema: dict[str, object], indexed: str
) -> dict[str, object]:
    if case.name in {"openai", "deepseek"}:
        output_format: dict[str, object] = {
            "type": "json_schema",
            "name": "atlas_output",
            "schema": schema,
        }
        payload: dict[str, object] = {
            "model": "chosen-alias",
            "instructions": EXTRACTION_INSTRUCTIONS,
            "input": indexed,
            "text": {"format": output_format},
        }
        if case.name == "openai":
            output_format["strict"] = True
            payload["store"] = False  # OpenAI defaults to nonstreaming.
        else:
            payload["stream"] = False  # DeepSeek is natively stateless; store is unsupported.
        return payload
    if case.name == "gemini":
        return {
            "model": "chosen-alias",
            "system_instruction": EXTRACTION_INSTRUCTIONS,
            "input": [{"type": "user_input", "content": [{"type": "text", "text": indexed}]}],
            "store": False,
            "stream": False,
            "background": False,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": gemini_schema(schema),
            },
        }
    if case.name == "anthropic":
        # Schema projection is verified independently below, including canonical nonmutation.
        return {
            "model": "chosen-alias",
            "system": EXTRACTION_INSTRUCTIONS,
            "messages": [{"role": "user", "content": indexed}],
            "max_tokens": 8192,
            "stream": False,
            "output_config": {
                "format": {"type": "json_schema", "schema": anthropic_schema(schema)}
            },
        }
    payload = {
        "model": "chosen-alias",
        "stream": False,
        "messages": [
            {"role": "system", "content": EXTRACTION_INSTRUCTIONS},
            {"role": "user", "content": indexed},
        ],
    }
    if case.name == "ollama":
        material = {"messages": payload["messages"], "format": schema}
        required = len(json.dumps(material, ensure_ascii=False).encode("utf-8")) + 8192
        payload.update(
            {
                "think": False,
                "format": schema,
                "options": {"temperature": 0, "num_ctx": required, "num_predict": 8192},
            }
        )
    else:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "atlas_output",
                "strict": True,
                "schema": kimi_schema(schema) if case.name == "kimi" else schema,
            },
        }
        if case.name == "openrouter":
            payload["provider"] = {"require_parameters": True, "allow_fallbacks": False}
    return payload


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("context_override", [None, 16384])
def test_exact_request_auth_and_cross_provider_result(
    case: ProviderCase, context_override: int | None
) -> None:
    schema = ExtractionProposal.model_json_schema()
    canonical = copy.deepcopy(schema)
    indexed = build_passage_index(b"Results\n\nNo change.\n").model_text
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if case.name == "ollama" and request.url.path == "/api/show":
            assert request.method == "POST" and str(request.url) == case.base + "/api/show"
            assert request.headers["Authorization"] == "Bearer " + KEY
            assert json.loads(request.content) == {"model": "chosen-alias"}
            return httpx.Response(200, json={"model_info": {"reference.context_length": 32768}})
        assert request.method == "POST" and str(request.url) == case.base + case.suffix
        assert request.headers[case.header] == (
            "Bearer " + KEY if case.header == "Authorization" else KEY
        )
        if case.header != "Authorization":
            assert "Authorization" not in request.headers
        if case.name == "anthropic":
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert "anthropic-beta" not in request.headers
        expected = expected_payload(case, schema, indexed)
        assert json.loads(request.content) == expected
        assert request.extensions["timeout"] == {
            "connect": 600,
            "read": 600,
            "write": 600,
            "pool": 600,
        }
        return httpx.Response(200, json=envelope(case))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider: StructuredModel = create_structured_model(
                settings(case, model_context_tokens=context_override), client
            )
            assert isinstance(provider, case.adapter)
            result = await provider.generate(EXTRACTION_INSTRUCTIONS, indexed, schema)
        assert result == RAW.encode("utf-8")
        assert ExtractionProposal.model_validate_json(result).evidence
        assert DISCARDED not in repr(result) and KEY not in repr(result)

    run(scenario())
    assert calls == (2 if case.name == "ollama" else 1) and schema == canonical


@pytest.mark.parametrize(
    "case", [case for case in CASES if case.name != "ollama"], ids=lambda case: case.name
)
@pytest.mark.parametrize("margin", [-1, 0, 1])
def test_hosted_context_fit_includes_complete_wire_request_and_output_reserve(
    case: ProviderCase, margin: int
) -> None:
    schema = ExtractionProposal.model_json_schema()
    indexed = build_passage_index('Quote " and Unicode β.\n'.encode()).model_text
    payload = expected_payload(case, schema, indexed)
    if case.name == "anthropic":
        payload["max_tokens"] = 7
    required = len(json.dumps(payload, ensure_ascii=False).encode()) + 7
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert json.loads(request.content) == payload
        return httpx.Response(200, json=envelope(case))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = create_structured_model(
                settings(case, model_context_tokens=required + margin, model_max_output_tokens=7),
                client,
            )
            assert await model.fits_context(EXTRACTION_INSTRUCTIONS, indexed, schema) is (
                margin >= 0
            )
            assert calls == 0
            assert await model.generate(EXTRACTION_INSTRUCTIONS, indexed, schema) == RAW.encode()

    run(scenario())
    assert calls == 1


@pytest.mark.parametrize(
    "case", [case for case in CASES if case.name != "ollama"], ids=lambda case: case.name
)
def test_unknown_hosted_model_context_fails_safely_without_io(case: ProviderCase) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("unknown context capacity must fail before generation I/O")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = create_structured_model(settings(case), client)
            with pytest.raises(ModelProviderError) as error:
                await model.fits_context("private instructions", "private input", {"private": KEY})
            assert str(error.value) == case.name + "_context_capacity_required"
            assert error.value.__cause__ is None

    run(scenario())


@pytest.mark.parametrize(
    "provider_name,model_name",
    [
        ("openai", "gpt-6.1-sol"),
        ("anthropic", "claude-sonnet-5-5"),
        ("gemini", "gemini-3.8-flash"),
        ("kimi", "kimi-k3"),
        ("deepseek", "deepseek-flash"),
        ("openrouter", "anthropic/claude-sonnet-5.5"),
    ],
)
def test_known_hosted_models_extract_without_manual_context_capacity(
    provider_name: str, model_name: str
) -> None:
    case = next(case for case in CASES if case.name == provider_name)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=envelope(case))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model = create_structured_model(settings(case, model_name=model_name), client)
            result = await extract_evidence(question="q", source=SOURCE, content=XML, model=model)
            assert result.evidence[0].passages == (PASSAGE,)

    run(scenario())
    assert calls == 1


@pytest.mark.parametrize("case", NEW_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize(
    "fault",
    ["transport", "timeout", "deadline", "400", "401", "429", "500", "redirect", "json", "list"],
)
def test_safe_transport_http_and_envelope_failures_no_retry_or_redirect(
    case: ProviderCase, fault: str
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if fault == "transport":
            raise httpx.ConnectError(KEY + DISCARDED, request=request)
        if fault == "timeout":
            raise httpx.ReadTimeout(KEY + DISCARDED, request=request)
        if fault == "deadline":
            await asyncio.sleep(0.05)
        if fault == "redirect":
            return httpx.Response(
                307, headers={"Location": "https://other.test/"}, text=KEY + DISCARDED
            )
        if fault.isdigit():
            return httpx.Response(int(fault), text=KEY + DISCARDED)
        if fault == "json":
            return httpx.Response(200, text=KEY + DISCARDED)
        return httpx.Response(200, json=[])

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            provider = create_structured_model(
                settings(case, model_timeout_seconds=0.001 if fault == "deadline" else 600),
                client,
            )
            with pytest.raises(ModelProviderError) as error:
                await provider.generate("instructions", "[p0001] document\n", {})
            suffix = (
                "transport_failure"
                if fault in {"transport", "timeout", "deadline"}
                else ("malformed_envelope" if fault in {"json", "list"} else "http_failure")
            )
            assert str(error.value) == f"{case.name}_{suffix}"
            assert KEY not in str(error.value) and DISCARDED not in str(error.value)

    run(scenario())
    assert calls == 1


def mutate_completion(case: ProviderCase, body: dict[str, object], fault: str) -> None:
    if case.name == "anthropic":
        if fault == "incomplete":
            body["stop_reason"] = "max_tokens"
        elif fault == "refusal":
            body["stop_reason"] = "refusal"
            body["content"] = [{"type": "text", "text": KEY + DISCARDED}]
        elif fault == "content":
            body["content"] = [{"type": "text", "text": 42}]
        else:
            body["role"] = "user"
    elif case.name == "gemini":
        if fault == "incomplete":
            body["status"] = "incomplete"
        elif fault == "refusal":
            body["status"] = "failed"
            body["error"] = {"message": KEY + DISCARDED}
        elif fault == "content":
            body["steps"] = [{"type": "model_output", "content": [{"type": "text", "text": 42}]}]
        else:
            body["steps"] = None
    elif case.name == "deepseek":
        if fault == "incomplete":
            body["status"] = "incomplete"
        elif fault == "refusal":
            body["incomplete_details"] = {"reason": "content_filter", "message": KEY + DISCARDED}
        elif fault == "content":
            body["output"] = [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": 42}],
                }
            ]
        else:
            body["status"] = {"secret": KEY}
    else:
        choice = cast(list[dict[str, object]], body["choices"])[0]
        message = cast(dict[str, object], choice["message"])
        if fault == "incomplete":
            choice["finish_reason"] = "length"
        elif fault == "refusal":
            choice["finish_reason"] = "content_filter"
            message["content"] = KEY + DISCARDED
        elif fault == "content":
            message["content"] = 42
        else:
            message["role"] = "user"


@pytest.mark.parametrize("case", NEW_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("fault", ["incomplete", "refusal", "content", "envelope", "empty"])
def test_safe_response_failures(case: ProviderCase, fault: str) -> None:
    body = envelope(case, " \n" if fault == "empty" else RAW)
    if fault in {"model", "credential_model"}:
        body["model"] = None if fault == "model" else KEY
    elif fault != "empty":
        mutate_completion(case, body, fault)

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            with pytest.raises(ModelProviderError) as error:
                await create_structured_model(settings(case), client).generate(
                    "instructions", "document", {}
                )
            assert KEY not in str(error.value) and DISCARDED not in str(error.value)
            assert error.value.__cause__ is None

    run(scenario())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("host", ["remote.test", "localhost.remote.test", "192.168.1.2", "[::2]"])
def test_selected_credential_enforces_tls_before_io(case: ProviderCase, host: str) -> None:
    with pytest.raises(ValueError, match="requires HTTPS") as error:
        create_structured_model(settings(case, model_base_url=f"http://{host}/v1"))
    assert KEY not in str(error.value) and host not in str(error.value)


@pytest.mark.parametrize("case", NEW_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize(
    "base",
    [
        "http://localhost:8000/v1",
        "http://127.0.0.1:8000/v1",
        "http://[::1]:8000/v1",
        "https://remote.test/v1",
    ],
)
def test_authenticated_loopback_and_remote_https_allowed(case: ProviderCase, base: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == base + case.suffix
        assert KEY in request.headers[case.header]
        return httpx.Response(200, json=envelope(case))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = create_structured_model(settings(case, model_base_url=base), client)
            assert (await provider.generate("instructions", "document", {})) == RAW.encode()

    run(scenario())


@pytest.mark.parametrize("case", NEW_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize(
    "url",
    ["ftp://host", "https://user:secret@host", "https://host?secret=key", "https://host#secret"],
)
def test_endpoint_credentials_rejected(case: ProviderCase, url: str) -> None:
    with pytest.raises(ValueError) as error:
        create_structured_model(settings(case, model_base_url=url))
    assert "secret" not in str(error.value) and KEY not in str(error.value)


@pytest.mark.parametrize("case", NEW_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("key", [None, "", " \t"])
def test_only_selected_provider_credentials_required(case: ProviderCase, key: str | None) -> None:
    values = settings(case).model_dump()
    values[case.key_field] = SecretStr(key) if key is not None else None
    # Native providers must not accidentally use another provider's key.
    values["openai_api_key"] = SecretStr("unrelated-openai-key")
    chosen = ProviderSettings.model_validate(values)
    if case.name == "openai_compatible":
        assert isinstance(create_structured_model(chosen), OpenAICompatibleChatModel)
    else:
        with pytest.raises(ValueError, match="API key must be configured"):
            create_structured_model(chosen)


def test_generic_requires_explicit_base_and_can_use_unauthenticated_local_endpoint() -> None:
    with pytest.raises(ValueError, match="base URL must be explicitly configured"):
        create_structured_model(
            ProviderSettings(model_provider="openai_compatible", model_name="chosen")
        )
    case = CASES[-1]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=envelope(case))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = create_structured_model(
                settings(
                    case,
                    openai_compatible_api_key=None,
                    model_base_url="http://localhost:8000/v1",
                ),
                client,
            )
            assert (await provider.generate("instructions", "document", {})) == RAW.encode()

    run(scenario())


@pytest.mark.parametrize("case", CHAT_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("raw", ["Here is JSON: {}", "[]", "{broken", "null"])
def test_compatible_output_never_downgrades_or_heals(case: ProviderCase, raw: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert json.loads(request.content)["response_format"]["type"] == "json_schema"
        return httpx.Response(200, json=envelope(case, raw))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ModelProviderError, match="invalid_structured_output"):
                await create_structured_model(settings(case), client).generate(
                    "instructions", "document", {}
                )

    run(scenario())
    assert calls == 1


def test_kimi_projection_changes_only_future_pattern_and_keeps_mfjs_structure() -> None:
    schema = ExtractionProposal.model_json_schema()
    before = copy.deepcopy(schema)
    projected = kimi_schema(schema)
    preserved: set[str] = set()
    patterns: set[str] = set()
    # Atlas's actual schema keywords audited against MoonshotAI/walle model.go and
    # keyword_validators.go. Property/definition names are deliberately not keywords.
    mfjs_keywords = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "$defs",
        "$ref",
        "anyOf",
        "items",
        "title",
        "description",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
    }

    def compare(original: Mapping[str, object], transformed: Mapping[str, object]) -> None:
        assert set(transformed) <= mfjs_keywords
        expected_keys = set(original) - {"pattern"}
        if "pattern" in original:
            patterns.add(str(original["pattern"]))
            expected_keys.add("description")
            prefix = f"{original['description']} " if original.get("description") else ""
            assert transformed["description"] == (
                prefix + f"Atlas constraints: pattern={original['pattern']}"
            )
        assert set(transformed) == expected_keys
        for name, value in original.items():
            if name == "pattern" or (name == "description" and "pattern" in original):
                continue
            preserved.add(name)
            if name in {"properties", "$defs"}:
                nested = cast(dict[str, dict[str, object]], value)
                changed = cast(dict[str, dict[str, object]], transformed[name])
                assert nested.keys() == changed.keys()
                for key, item in nested.items():
                    compare(item, changed[key])
            elif name == "items":
                compare(cast(dict[str, object], value), cast(dict[str, object], transformed[name]))
            elif name == "anyOf":
                for item, changed in zip(
                    cast(list[dict[str, object]], value),
                    cast(list[dict[str, object]], transformed[name]),
                    strict=True,
                ):
                    compare(item, changed)
            else:
                assert transformed[name] == value

    compare(schema, projected)
    assert patterns == {r"\S", r"^p[0-9]{4,}$"}
    assert {
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "properties",
        "required",
        "additionalProperties",
        "anyOf",
        "$ref",
        "$defs",
        "title",
    } <= preserved
    assert schema == before
    assert kimi_schema(schema) == projected and kimi_schema(projected) == projected


def test_kimi_projection_preserves_keyword_like_field_names_and_existing_descriptions() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "title": "Pattern",
                "description": "Nonblank.",
                "minLength": 1,
                "maxLength": 100,
                "pattern": r"\S",
            },
            "maxLength": {"anyOf": [{"$ref": "#/$defs/pattern"}, {"type": "null"}]},
        },
        "required": ["pattern", "maxLength"],
        "additionalProperties": False,
        "$defs": {"pattern": {"type": "string", "pattern": r"^p[0-9]{4,}$"}},
    }
    before = copy.deepcopy(schema)
    expected = copy.deepcopy(schema)
    field = cast(dict[str, dict[str, object]], expected["properties"])["pattern"]
    del field["pattern"]
    field["description"] = r"Nonblank. Atlas constraints: pattern=\S"
    definition = cast(dict[str, dict[str, object]], expected["$defs"])["pattern"]
    del definition["pattern"]
    definition["description"] = r"Atlas constraints: pattern=^p[0-9]{4,}$"
    projected = kimi_schema(schema)
    assert projected == expected and schema == before
    cast(list[str], projected["required"]).append("another")
    assert schema == before


def test_kimi_response_does_not_require_model_metadata() -> None:
    case = next(case for case in CASES if case.name == "kimi")
    body = envelope(case)
    del body["model"]

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            result = await create_structured_model(settings(case), client).generate("i", "d", {})
            assert result == RAW.encode()

    run(scenario())


def test_anthropic_schema_projection_preserves_structure_constraints_and_original() -> None:
    schema = ExtractionProposal.model_json_schema()
    before = copy.deepcopy(schema)
    projected = anthropic_schema(schema)

    def compare(original: Mapping[str, object], transformed: Mapping[str, object]) -> None:
        for name, value in original.items():
            unsupported = name in {"minLength", "maxLength", "maxItems"} or (
                name == "minItems" and value not in (0, 1)
            )
            if unsupported:
                assert name not in transformed
                assert f"{name}={value}" in str(transformed["description"])
            elif name in {"properties", "$defs"}:
                nested = cast(dict[str, dict[str, object]], value)
                changed = cast(dict[str, dict[str, object]], transformed[name])
                assert nested.keys() == changed.keys()
                for key, item in nested.items():
                    compare(item, changed[key])
            elif isinstance(value, dict):
                compare(cast(dict[str, object], value), cast(dict[str, object], transformed[name]))
            elif isinstance(value, list) and name == "anyOf":
                for item, changed in zip(
                    cast(list[dict[str, object]], value),
                    cast(list[dict[str, object]], transformed[name]),
                    strict=True,
                ):
                    compare(item, changed)
            else:
                assert transformed[name] == value

    compare(schema, projected)
    assert schema == before
    named_fields: dict[str, object] = {
        "type": "object",
        "properties": {"maxItems": {"type": "string", "maxLength": 100}},
    }
    properties = cast(dict[str, object], anthropic_schema(named_fields)["properties"])
    assert "maxItems" in properties


def test_gemini_canonical_projection_preserves_every_supported_field_and_original() -> None:
    schema = ExtractionProposal.model_json_schema()
    before = copy.deepcopy(schema)
    projected = gemini_schema(schema)
    removed: set[str] = set()
    preserved: set[str] = set()

    def compare(original: Mapping[str, object], transformed: Mapping[str, object]) -> None:
        constraints = {
            name: value
            for name, value in original.items()
            if name in {"minLength", "maxLength", "pattern"}
        }
        expected_keys = set(original) - constraints.keys()
        if constraints:
            expected_keys.add("description")
        assert set(transformed) == expected_keys
        for name, value in original.items():
            if name in constraints:
                removed.add(name)
                assert f"{name}={value}" in str(transformed["description"])
            elif name in {"properties", "$defs"}:
                nested = cast(dict[str, dict[str, object]], value)
                changed = cast(dict[str, dict[str, object]], transformed[name])
                assert nested.keys() == changed.keys()
                for key, item in nested.items():
                    compare(item, changed[key])
            elif name == "items":
                compare(cast(dict[str, object], value), cast(dict[str, object], transformed[name]))
            elif name == "anyOf":
                preserved.add(name)
                for item, changed in zip(
                    cast(list[dict[str, object]], value),
                    cast(list[dict[str, object]], transformed[name]),
                    strict=True,
                ):
                    compare(item, changed)
            elif name == "description" and constraints:
                assert str(transformed[name]).startswith(str(value) + " ")
            else:
                preserved.add(name)
                assert transformed[name] == value

    compare(schema, projected)
    assert removed == {"minLength", "maxLength", "pattern"}
    assert {
        "minItems",
        "maxItems",
        "required",
        "additionalProperties",
        "$ref",
        "anyOf",
        "title",
    } <= preserved
    assert schema == before
    assert gemini_schema(schema) == projected and gemini_schema(projected) == projected


def test_gemini_constraint_descriptions_have_fixed_order_and_preserve_existing_text() -> None:
    schema: dict[str, object] = {
        "type": "string",
        "title": "Passage",
        "description": "Exact passage ID.",
        "pattern": r"^p[0-9]{4,}$",
        "maxLength": 12,
        "minLength": 1,
    }
    expected = {
        "type": "string",
        "title": "Passage",
        "description": (
            "Exact passage ID. Atlas constraints: minLength=1, maxLength=12, pattern=^p[0-9]{4,}$"
        ),
    }
    assert gemini_schema(schema) == expected
    assert gemini_schema(dict(reversed(tuple(schema.items())))) == expected
    assert schema["description"] == "Exact passage ID."


def test_gemini_keyword_named_properties_and_definitions_are_not_rewritten() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "title": "Keyword names",
        "description": "Keep this description.",
        "properties": {
            "minLength": {"$ref": "#/$defs/pattern"},
            "maxLength": {"type": "string", "minLength": 1},
            "pattern": {"anyOf": [{"type": "string", "pattern": r"\S"}, {"type": "null"}]},
        },
        "required": ["minLength", "maxLength", "pattern"],
        "additionalProperties": False,
        "$defs": {"pattern": {"type": "string", "maxLength": 100}},
    }
    before = copy.deepcopy(schema)
    expected: dict[str, object] = {
        "type": "object",
        "title": "Keyword names",
        "description": "Keep this description.",
        "properties": {
            "minLength": {"$ref": "#/$defs/pattern"},
            "maxLength": {"type": "string", "description": "Atlas constraints: minLength=1"},
            "pattern": {
                "anyOf": [
                    {"type": "string", "description": r"Atlas constraints: pattern=\S"},
                    {"type": "null"},
                ]
            },
        },
        "required": ["minLength", "maxLength", "pattern"],
        "additionalProperties": False,
        "$defs": {"pattern": {"type": "string", "description": "Atlas constraints: maxLength=100"}},
    }
    projected = gemini_schema(schema)
    assert projected == expected and schema == before
    # The returned schema owns its nested containers as well as leaving input untouched.
    cast(list[str], projected["required"]).append("another")
    assert schema == before


def test_provider_specific_environment_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for case in CASES:
        monkeypatch.setenv("RESEARCH_ATLAS_" + case.key_field.upper(), KEY)
    monkeypatch.setenv("RESEARCH_ATLAS_OPENALEX_API_KEY", "existing-openalex-key")
    loaded = ProviderSettings()
    assert loaded.openalex_api_key is not None
    assert loaded.openalex_api_key.get_secret_value() == "existing-openalex-key"
    for case in CASES:
        assert isinstance(getattr(loaded, case.key_field), SecretStr)
    assert KEY not in repr(loaded)


def test_gemini_response_does_not_require_model_metadata() -> None:
    case = CASES[2]
    body = envelope(case)
    del body["model"]

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            result = await create_structured_model(settings(case), client).generate(
                "instructions", "document", {}
            )
            assert result == RAW.encode()

    run(scenario())


@pytest.mark.parametrize("case", NEW_CASES, ids=lambda case: case.name)
def test_unicode_final_parts_are_exact_and_owned_http_client_closes(
    case: ProviderCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = ' \n{ "evidence": [], "note": "café 研究" }\n '
    body = envelope(case, raw)
    parts = [raw[:12], raw[12:]]
    if case.name == "anthropic":
        body["content"] = [{"type": "text", "text": part} for part in parts]
    elif case.name == "gemini":
        steps = cast(list[dict[str, object]], body["steps"])
        steps[-1]["content"] = [{"type": "text", "text": part} for part in parts]
    elif case.name == "deepseek":
        output = cast(list[dict[str, object]], body["output"])
        output[-1]["content"] = [{"type": "output_text", "text": part} for part in parts]
    owned = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    )

    def owned_client(**_: object) -> httpx.AsyncClient:
        return owned

    monkeypatch.setattr(httpx, "AsyncClient", owned_client)

    async def scenario() -> None:
        provider = create_structured_model(settings(case))
        result = await provider.generate("instructions", "document", {})
        assert result == raw.encode("utf-8") and owned.is_closed

    run(scenario())


@pytest.mark.parametrize("case", CHAT_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("fault", ["refusal", "tools", "multiple", "error"])
def test_chat_refusal_tools_multiple_choices_and_error_are_never_final_output(
    case: ProviderCase, fault: str
) -> None:
    body = envelope(case)
    choices = cast(list[dict[str, object]], body["choices"])
    message = cast(dict[str, object], choices[0]["message"])
    if fault == "refusal":
        message["refusal"] = DISCARDED
        message["content"] = None
    elif fault == "tools":
        message["tool_calls"] = [{"arguments": DISCARDED}]
    elif fault == "multiple":
        choices.append(choices[0])
    else:
        body["error"] = {"message": DISCARDED, "code": KEY}

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            with pytest.raises(ModelProviderError) as error:
                await create_structured_model(settings(case), client).generate("i", "d", {})
        assert DISCARDED not in str(error.value) and KEY not in str(error.value)

    run(scenario())


@pytest.mark.parametrize("stop", ["max_tokens", "stop_sequence", "tool_use", "pause_turn", None])
def test_anthropic_requires_normal_completion(stop: str | None) -> None:
    case = CASES[1]
    body = envelope(case)
    body["stop_reason"] = stop

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            with pytest.raises(ModelProviderError, match="anthropic_incomplete_response"):
                await create_structured_model(settings(case), client).generate("i", "d", {})

    run(scenario())


@pytest.mark.parametrize(
    "status", ["incomplete", "in_progress", "requires_action", "failed", "cancelled"]
)
def test_gemini_noncompleted_interactions(status: str) -> None:
    case = CASES[2]
    body = envelope(case)
    body["status"] = status

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            with pytest.raises(ModelProviderError):
                await create_structured_model(settings(case), client).generate("i", "d", {})

    run(scenario())


@pytest.mark.parametrize("fault", ["failed", "message_incomplete", "refusal", "multiple"])
def test_deepseek_own_response_policy(fault: str) -> None:
    case = CASES[4]
    body = envelope(case)
    output = cast(list[dict[str, object]], body["output"])
    if fault == "failed":
        body["status"] = "failed"
        body["error"] = {"message": DISCARDED}
    elif fault == "message_incomplete":
        output[-1]["status"] = "incomplete"
    elif fault == "refusal":
        output[-1]["content"] = [{"type": "refusal", "refusal": DISCARDED}]
    else:
        output.append(output[-1])

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            with pytest.raises(ModelProviderError) as error:
                await create_structured_model(settings(case), client).generate("i", "d", {})
        assert DISCARDED not in str(error.value)

    run(scenario())


def test_explicit_model_overrides_and_anthropic_token_budget_are_not_defaults() -> None:
    case = CASES[1]
    for model in ("chosen\nunsafe", "x" * 201):
        with pytest.raises(ValueError, match="bounded printable"):
            create_structured_model(settings(case, model_name=model))
    for budget in (0, 131073):
        with pytest.raises(ValueError):
            settings(case, model_max_output_tokens=budget)

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["max_tokens"] == 4096
        return httpx.Response(200, json=envelope(case))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = create_structured_model(settings(case, model_max_output_tokens=4096), client)
            await provider.generate("i", "d", {})

    run(scenario())
