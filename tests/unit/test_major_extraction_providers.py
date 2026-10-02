"""Offline provider coverage and the unchanged application/passage-evidence contract."""

import asyncio
import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from research_atlas.application.extraction import EXTRACTION_INSTRUCTIONS, extract_source_document
from research_atlas.application.passage_index import build_passage_index
from research_atlas.application.ports.extraction import ExtractionProviderError, StructuredExtractor
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.providers.anthropic import AnthropicExtractor, anthropic_schema
from research_atlas.infrastructure.providers.deepseek_responses import DeepSeekResponsesExtractor
from research_atlas.infrastructure.providers.gemini import (
    GeminiInteractionsExtractor,
    gemini_schema,
)
from research_atlas.infrastructure.providers.kimi import KimiExtractor, kimi_schema
from research_atlas.infrastructure.providers.ollama import OllamaExtractor
from research_atlas.infrastructure.providers.openai_compatible_chat import (
    OpenAICompatibleChatExtractor,
)
from research_atlas.infrastructure.providers.openai_responses import OpenAIResponsesExtractor
from research_atlas.infrastructure.providers.openrouter import OpenRouterExtractor
from research_atlas.infrastructure.providers.structured_extraction import (
    create_structured_extractor,
)
from research_atlas.schemas.extraction_proposal import ExtractionProposal
from tests.persistence.conftest import run
from tests.unit.test_extraction import PASSAGE, PASSAGE_ID, MemoryPersistence, proposal_bytes

KEY = "test-only-credential"
DISCARDED = "private-provider-diagnostics-and-reasoning"
RAW = " \n" + proposal_bytes().decode() + "\n "


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
        OpenAIResponsesExtractor,
        "https://api.openai.com/v1",
        "/responses",
        "openai_api_key",
        "Authorization",
    ),
    ProviderCase(
        "anthropic",
        AnthropicExtractor,
        "https://api.anthropic.com/v1",
        "/messages",
        "anthropic_api_key",
        "x-api-key",
    ),
    ProviderCase(
        "gemini",
        GeminiInteractionsExtractor,
        "https://generativelanguage.googleapis.com/v1",
        "/interactions",
        "gemini_api_key",
        "x-goog-api-key",
    ),
    ProviderCase(
        "openrouter",
        OpenRouterExtractor,
        "https://openrouter.ai/api/v1",
        "/chat/completions",
        "openrouter_api_key",
        "Authorization",
    ),
    ProviderCase(
        "deepseek",
        DeepSeekResponsesExtractor,
        "https://api.deepseek.com",
        "/responses",
        "deepseek_api_key",
        "Authorization",
    ),
    ProviderCase(
        "ollama",
        OllamaExtractor,
        "http://localhost:11434",
        "/api/chat",
        "extraction_api_key",
        "Authorization",
    ),
    ProviderCase(
        "kimi",
        KimiExtractor,
        "https://api.moonshot.ai/v1",
        "/chat/completions",
        "kimi_api_key",
        "Authorization",
    ),
    ProviderCase(
        "openai_compatible",
        OpenAICompatibleChatExtractor,
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
        "extraction_provider": case.name,
        "extraction_model": "chosen-alias",
        case.key_field: SecretStr(KEY),
    }
    if case.name == "openai_compatible":
        values["extraction_base_url"] = case.base
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
            "name": "atlas_extraction",
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
        payload.update({"think": False, "format": schema, "options": {"temperature": 0}})
    else:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "atlas_extraction",
                "strict": True,
                "schema": kimi_schema(schema) if case.name == "kimi" else schema,
            },
        }
        if case.name == "openrouter":
            payload["provider"] = {"require_parameters": True, "allow_fallbacks": False}
    return payload


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_exact_request_auth_configuration_and_cross_provider_result(case: ProviderCase) -> None:
    schema = ExtractionProposal.model_json_schema()
    canonical = copy.deepcopy(schema)
    indexed = build_passage_index(b"Results\n\nNo change.\n").model_text
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "POST" and str(request.url) == case.base + case.suffix
        assert request.headers[case.header] == (
            "Bearer " + KEY if case.header == "Authorization" else KEY
        )
        if case.header != "Authorization":
            assert "Authorization" not in request.headers
        if case.name == "anthropic":
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert "anthropic-beta" not in request.headers
        assert json.loads(request.content) == expected_payload(case, schema, indexed)
        assert request.extensions["timeout"] == {
            "connect": 600,
            "read": 600,
            "write": 600,
            "pool": 600,
        }
        return httpx.Response(200, json=envelope(case))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider: StructuredExtractor = create_structured_extractor(settings(case), client)
            assert isinstance(provider, case.adapter)
            config = dict(provider.configuration)
            assert config["provider"] == case.name and config["model"] == "chosen-alias"
            assert config["base_url"] == case.base
            if case.name == "gemini":
                assert config["schema_transform"] == "atlas.gemini-schema.v1"
            if case.name == "kimi":
                assert config["schema_transform"] == "atlas.kimi-schema.v1"
            assert KEY not in json.dumps(config) + repr(settings(case))
            assert not any("key" in field or "header" in field for field in config)
            result = await provider.extract(EXTRACTION_INSTRUCTIONS, indexed, schema)
        assert result.raw_output == RAW.encode("utf-8")
        assert ExtractionProposal.model_validate_json(result.raw_output).studies
        assert result.model_version == (
            "chosen-alias" if case.name == "ollama" else "chosen-snapshot"
        )
        assert result.tool_name.startswith("atlas-") and result.tool_version == config["adapter"]
        assert DISCARDED not in repr(result) and KEY not in repr(result)

    run(scenario())
    assert calls == 1 and schema == canonical


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_each_adapter_flows_through_application_to_immutable_passage_anchors(
    case: ProviderCase,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert f"[{PASSAGE_ID}] {PASSAGE}" in json.dumps(body)
        return httpx.Response(200, json=envelope(case))

    async def scenario() -> None:
        store = MemoryPersistence()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = create_structured_extractor(settings(case), client)
            result = await extract_source_document(
                store,
                provider,
                run_id="run",
                source_id=store.parent.source_id,
                document_id=store.parent.document_id,
            )
        assert result.status == "accepted" and store.published is not None
        anchor = store.published[1][0].evidence_anchors[0]
        assert anchor.passage == PASSAGE and anchor.locator == PASSAGE_ID
        assert PASSAGE not in RAW
        assert store.saved[-1][2] == RAW.encode()
        assert DISCARDED not in repr(store.saved) and KEY not in repr(store.saved)

    run(scenario())


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
            provider = create_structured_extractor(
                settings(case, extraction_timeout_seconds=0.001 if fault == "deadline" else 600),
                client,
            )
            with pytest.raises(ExtractionProviderError) as error:
                await provider.extract("instructions", "[p0001] document\n", {})
            suffix = (
                "transport_failure"
                if fault in {"transport", "timeout", "deadline"}
                else ("malformed_envelope" if fault in {"json", "list"} else "http_failure")
            )
            assert str(error.value) == f"{case.name}_{suffix}"
            assert error.value.raw_output is None and error.value.__cause__ is None
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
@pytest.mark.parametrize(
    "fault", ["incomplete", "refusal", "content", "envelope", "model", "credential_model", "empty"]
)
def test_safe_response_failures_and_partial_final_bytes(case: ProviderCase, fault: str) -> None:
    body = envelope(case, " \n" if fault == "empty" else RAW)
    if fault in {"model", "credential_model"}:
        body["model"] = None if fault == "model" else KEY
    elif fault != "empty":
        mutate_completion(case, body, fault)

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            with pytest.raises(ExtractionProviderError) as error:
                await create_structured_extractor(settings(case), client).extract(
                    "instructions", "document", {}
                )
            expected_raw = (
                RAW.encode()
                if fault in {"incomplete", "model", "credential_model"}
                else (b" \n" if fault == "empty" else None)
            )
            assert error.value.raw_output == expected_raw
            assert KEY not in str(error.value) and DISCARDED not in str(error.value)
            assert error.value.__cause__ is None

    run(scenario())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("host", ["remote.test", "localhost.remote.test", "192.168.1.2", "[::2]"])
def test_selected_credential_enforces_tls_before_io(case: ProviderCase, host: str) -> None:
    with pytest.raises(ValueError, match="requires HTTPS") as error:
        create_structured_extractor(settings(case, extraction_base_url=f"http://{host}/v1"))
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
            provider = create_structured_extractor(settings(case, extraction_base_url=base), client)
            assert (
                await provider.extract("instructions", "document", {})
            ).raw_output == RAW.encode()

    run(scenario())


@pytest.mark.parametrize("case", NEW_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize(
    "url",
    ["ftp://host", "https://user:secret@host", "https://host?secret=key", "https://host#secret"],
)
def test_secrets_in_endpoint_never_reach_configuration(case: ProviderCase, url: str) -> None:
    with pytest.raises(ValueError) as error:
        create_structured_extractor(settings(case, extraction_base_url=url))
    assert "secret" not in str(error.value) and KEY not in str(error.value)


@pytest.mark.parametrize("case", NEW_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("key", [None, "", " \t"])
def test_only_selected_provider_credentials_required(case: ProviderCase, key: str | None) -> None:
    values = settings(case).model_dump()
    values[case.key_field] = SecretStr(key) if key is not None else None
    # Native providers must not accidentally use a legacy or another provider's key.
    values["extraction_api_key"] = SecretStr("unrelated-legacy-key")
    values["openai_api_key"] = SecretStr("unrelated-openai-key")
    chosen = ProviderSettings.model_validate(values)
    if case.name == "openai_compatible":
        assert isinstance(create_structured_extractor(chosen), OpenAICompatibleChatExtractor)
    else:
        with pytest.raises(ValueError, match="API key must be configured"):
            create_structured_extractor(chosen)


def test_generic_requires_explicit_base_and_can_use_unauthenticated_local_endpoint() -> None:
    with pytest.raises(ValueError, match="base URL must be explicitly configured"):
        create_structured_extractor(
            ProviderSettings(extraction_provider="openai_compatible", extraction_model="chosen")
        )
    case = CASES[-1]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=envelope(case))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = create_structured_extractor(
                settings(
                    case,
                    openai_compatible_api_key=None,
                    extraction_base_url="http://localhost:8000/v1",
                ),
                client,
            )
            assert (
                await provider.extract("instructions", "document", {})
            ).raw_output == RAW.encode()

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
            with pytest.raises(ExtractionProviderError, match="invalid_structured_output") as error:
                await create_structured_extractor(settings(case), client).extract(
                    "instructions", "document", {}
                )
            assert error.value.raw_output == raw.encode()

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


@pytest.mark.parametrize("fault", ["blank_text", "invalid_passage_id"])
def test_kimi_output_still_rejects_projected_canonical_patterns(fault: str) -> None:
    case = next(case for case in CASES if case.name == "kimi")
    proposal = ExtractionProposal.model_validate_json(proposal_bytes()).model_dump(mode="json")
    finding = proposal["studies"][0]["findings"][0]
    if fault == "blank_text":
        finding["result_summary"] = " \t"
    else:
        finding["evidence_passage_ids"] = ["invalid"]
    raw = json.dumps(proposal)

    def handler(request: httpx.Request) -> httpx.Response:
        schema = json.loads(request.content)["response_format"]["json_schema"]["schema"]
        fields = schema["$defs"]["ProposedFinding"]["properties"]
        assert fields["result_summary"] == {
            "title": "Result Summary",
            "type": "string",
            "minLength": 1,
            "maxLength": 20000,
            "description": r"Atlas constraints: pattern=\S",
        }
        ids = fields["evidence_passage_ids"]
        assert ids["minItems"] == 1 and ids["maxItems"] == 20
        assert "pattern" not in ids["items"]
        assert ids["items"]["description"] == r"Atlas constraints: pattern=^p[0-9]{4,}$"
        return httpx.Response(200, json=envelope(case, raw))

    async def scenario() -> None:
        store = MemoryPersistence()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await extract_source_document(
                store,
                create_structured_extractor(settings(case), client),
                run_id="run",
                source_id=store.parent.source_id,
                document_id=store.parent.document_id,
            )
        assert result.status == "failed" and store.published is None
        assert store.saved[-1][2] == raw.encode()

    run(scenario())


def test_kimi_missing_returned_model_uses_explicit_requested_identity() -> None:
    case = next(case for case in CASES if case.name == "kimi")
    body = envelope(case)
    del body["model"]

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            result = await create_structured_extractor(settings(case), client).extract("i", "d", {})
        assert result.model_version == "chosen-alias"

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


@pytest.mark.parametrize("value", ["", "x" * 20_001, " \t"])
def test_gemini_output_still_rejects_removed_canonical_string_constraints(value: str) -> None:
    case = CASES[2]
    proposal = ExtractionProposal.model_validate_json(proposal_bytes()).model_dump(mode="json")
    proposal["studies"][0]["findings"][0]["result_summary"] = value
    raw = json.dumps(proposal)

    def handler(request: httpx.Request) -> httpx.Response:
        schema = json.loads(request.content)["response_format"]["schema"]
        field = schema["$defs"]["ProposedFinding"]["properties"]["result_summary"]
        assert not {"minLength", "maxLength", "pattern"} & field.keys()
        assert (
            field["description"] == "Atlas constraints: minLength=1, maxLength=20000, pattern=\\S"
        )
        return httpx.Response(200, json=envelope(case, raw))

    async def scenario() -> None:
        store = MemoryPersistence()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await extract_source_document(
                store,
                create_structured_extractor(settings(case), client),
                run_id="run",
                source_id=store.parent.source_id,
                document_id=store.parent.document_id,
            )
        assert result.status == "failed" and store.published is None
        assert store.saved[-1][2] == raw.encode()

    run(scenario())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("fault", ["empty_text", "too_many_details", "unknown_passage"])
def test_canonical_validation_and_passage_resolution_are_not_weakened(
    case: ProviderCase, fault: str
) -> None:
    proposal = ExtractionProposal.model_validate_json(proposal_bytes()).model_dump(mode="json")
    if fault == "empty_text":
        proposal["studies"][0]["findings"][0]["result_summary"] = ""
    elif fault == "too_many_details":
        proposal["studies"][0]["details"] = [
            {"key": str(index), "value": "x"} for index in range(21)
        ]
    else:
        proposal["studies"][0]["findings"][0]["evidence_passage_ids"] = ["p9999"]
    raw = json.dumps(proposal)

    async def scenario() -> None:
        store = MemoryPersistence()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope(case, raw)))
        ) as client:
            result = await extract_source_document(
                store,
                create_structured_extractor(settings(case), client),
                run_id="run",
                source_id=store.parent.source_id,
                document_id=store.parent.document_id,
            )
        assert result.status == ("review_needed" if fault == "unknown_passage" else "failed")
        assert store.published is None and store.saved[-1][2] == raw.encode()

    run(scenario())


def test_provider_specific_environment_secret_and_legacy_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for case in CASES:
        monkeypatch.setenv("RESEARCH_ATLAS_" + case.key_field.upper(), KEY)
    monkeypatch.setenv("RESEARCH_ATLAS_OPENALEX_API_KEY", "existing-openalex-key")
    loaded = ProviderSettings()
    assert loaded.openalex_api_key == "existing-openalex-key"
    for case in CASES:
        assert isinstance(getattr(loaded, case.key_field), SecretStr)
    assert KEY not in repr(loaded)
    case = CASES[0]
    for key in (None, SecretStr(""), SecretStr(" \t")):
        chosen = settings(case, openai_api_key=key, extraction_api_key=SecretStr(KEY))
        assert isinstance(create_structured_extractor(chosen), OpenAIResponsesExtractor)


def test_gemini_missing_optional_model_uses_requested_identity() -> None:
    case = CASES[2]
    body = envelope(case)
    del body["model"]

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            result = await create_structured_extractor(settings(case), client).extract(
                "instructions", "document", {}
            )
        assert result.model_version == "chosen-alias"

    run(scenario())


@pytest.mark.parametrize("case", NEW_CASES, ids=lambda case: case.name)
def test_unicode_final_parts_are_exact_and_owned_http_client_closes(
    case: ProviderCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = ' \n{ "studies": [], "note": "café 研究" }\n '
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
        provider = create_structured_extractor(settings(case))
        result = await provider.extract("instructions", "document", {})
        assert result.raw_output == raw.encode("utf-8") and owned.is_closed

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
            with pytest.raises(ExtractionProviderError) as error:
                await create_structured_extractor(settings(case), client).extract("i", "d", {})
        assert error.value.raw_output is None
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
            with pytest.raises(
                ExtractionProviderError, match="anthropic_incomplete_response"
            ) as error:
                await create_structured_extractor(settings(case), client).extract("i", "d", {})
        assert error.value.raw_output == RAW.encode()

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
            with pytest.raises(ExtractionProviderError) as error:
                await create_structured_extractor(settings(case), client).extract("i", "d", {})
        assert error.value.raw_output == (
            None if status in {"failed", "cancelled"} else RAW.encode()
        )

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
            with pytest.raises(ExtractionProviderError) as error:
                await create_structured_extractor(settings(case), client).extract("i", "d", {})
        assert error.value.raw_output == (
            RAW.encode() if fault in {"failed", "message_incomplete"} else None
        )
        assert DISCARDED not in str(error.value)

    run(scenario())


def test_explicit_model_overrides_and_anthropic_token_budget_are_not_defaults() -> None:
    case = CASES[1]
    for model in ("chosen\nunsafe", "x" * 201):
        with pytest.raises(ValueError, match="bounded printable"):
            create_structured_extractor(settings(case, extraction_model=model))
    for budget in (0, 131073):
        with pytest.raises(ValueError):
            settings(case, extraction_max_output_tokens=budget)

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["max_tokens"] == 4096
        return httpx.Response(200, json=envelope(case))

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = create_structured_extractor(
                settings(case, extraction_max_output_tokens=4096), client
            )
            assert provider.configuration["max_tokens"] == 4096
            await provider.extract("i", "d", {})

    run(scenario())
