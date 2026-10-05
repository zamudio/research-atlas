import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
from xml.sax.saxutils import escape

import httpx
import pytest

import research_atlas.content as content_module
import research_atlas.openalex as openalex_module
from research_atlas import collect_evidence, extract_evidence
from research_atlas.config import ProviderSettings
from research_atlas.embeddings import EmbeddingError
from research_atlas.extraction import EXTRACTION_INSTRUCTIONS, ExtractionProposal
from research_atlas.grobid import project_grobid
from research_atlas.openalex import OpenAlex
from research_atlas.passages import (
    PASSAGE_EMBEDDING_CHARACTERS,
    PassageIndex,
    build_passage_index,
    select_context,
)
from research_atlas.providers import ModelProviderError
from research_atlas.providers.ollama import OllamaModel
from tests.test_embeddings import FakeEmbedder
from tests.test_extraction import SOURCE, XML, FakeModel, proposal_bytes
from tests.test_openalex import KEY, no_sleep


def fits_characters(capacity: int = 50_000) -> Callable[[str], Awaitable[bool]]:
    async def fits(input_text: str) -> bool:
        return len(input_text) <= capacity

    return fits


def paper(blocks: tuple[str, ...]) -> bytes:
    return (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        + "".join(f"<p>{escape(block)}</p>" for block in blocks)
        + "</body></text></TEI>"
    ).encode()


def large_paper() -> tuple[bytes, FakeEmbedder]:
    blocks = tuple(f"Unrelated {i}. " + "x" * 3990 for i in range(20))
    # Short table fragments are retained as local context without special table logic.
    blocks = (
        *blocks[:13],
        "n = 42",
        "Strong learning result. " + "β" * 8000,
        "0.3 0.4",
        *blocks[16:],
    )
    vectors = ((1, 0), *((1, 0) if i == 14 else (0, 1) for i in range(20)))
    return paper(blocks), FakeEmbedder(vectors)


@pytest.mark.parametrize("with_embedder", [False, True])
def test_small_paper_preserves_entire_index_and_never_embeds(with_embedder: bool) -> None:
    index = build_passage_index(project_grobid(XML))
    embedder = FakeEmbedder(())
    selected = asyncio.run(
        select_context(index, "q", embedder if with_embedder else None, fits_characters())
    )
    assert selected is index
    assert embedder.calls == []


def test_small_paper_failing_embedder_is_never_called_and_extraction_proceeds() -> None:
    index = build_passage_index(project_grobid(XML))

    class FailingEmbedder(FakeEmbedder):
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            self.calls.append(texts)
            raise EmbeddingError("ollama_embedding_transport_failure")

    embedder = FailingEmbedder(())
    assert asyncio.run(select_context(index, "q", embedder, fits_characters())) is index
    model = FakeModel(proposal_bytes(), context_tokens=50_000)
    result = asyncio.run(
        extract_evidence(question="q", source=SOURCE, content=XML, model=model, embedder=embedder)
    )
    assert result.evidence[0].passages == (index.resolve("p0001"),)
    assert embedder.calls == []
    assert model.calls == 1


def test_model_capacity_boundary_and_missing_embedder() -> None:
    index = build_passage_index(project_grobid(XML))
    embedder = FakeEmbedder(((1, 0), (1, 0), (0, 1)))
    assert (
        asyncio.run(select_context(index, "q", embedder, fits_characters(len(index.model_text))))
        is index
    )
    assert embedder.calls == []
    smaller = fits_characters(len(index.model_text) - 1)
    with pytest.raises(ModelProviderError, match="context_reduction_requires_embedder"):
        asyncio.run(select_context(index, "q", None, smaller))
    selected = asyncio.run(select_context(index, "q", embedder, smaller))
    assert selected is not index
    assert len(selected.model_text) < len(index.model_text)
    assert len(embedder.calls) == 1


def test_large_paper_prioritizes_hits_neighbors_and_restores_original_ids_and_order() -> None:
    content, embedder = large_paper()
    index = build_passage_index(project_grobid(content))
    original = dict(index.passages)
    question = "  What improves learning?\n"
    selected = asyncio.run(select_context(index, question, embedder, fits_characters()))
    assert len(index.model_text) > 60_000
    assert len(selected.model_text) <= 50_000
    assert "p0015" in selected.passages
    assert selected.passages["p0014"] == "n = 42"
    assert selected.passages["p0016"] == "0.3 0.4"
    assert "p0020" not in selected.passages
    assert tuple(selected.passages) == tuple(sorted(selected.passages))
    assert all(original[key] == text for key, text in selected.passages.items())
    assert dict(index.passages) == original
    assert embedder.calls == [
        (question, *(text[:PASSAGE_EMBEDDING_CHARACTERS] for text in original.values()))
    ]
    # The complete hit survives in model input even though only its prefix was embedded.
    assert len(selected.passages["p0015"]) > PASSAGE_EMBEDDING_CHARACTERS


def test_hit_takes_priority_over_neighbors_that_do_not_fit() -> None:
    index = build_passage_index(b"left\n\nstrong\n\nright\n\nlast\n")
    hit_cost = len("[p0002] strong\n")
    embedder = FakeEmbedder(((1, 0), (0, 1), (1, 0), (0, 1), (0, 1)))
    selected = asyncio.run(select_context(index, "q", embedder, fits_characters(hit_cost)))
    assert tuple(selected.passages) == ("p0002",)
    assert len(selected.model_text) == hit_cost


def test_overlapping_strong_hit_expands_its_window_before_a_distant_hit() -> None:
    index = build_passage_index(b"AAAA\n\nBBBB\n\nCCCC\n\nDDDD\n\nEEEE\n")
    expected = "[p0001] AAAA\n\n[p0002] BBBB\n\n[p0003] CCCC\n"
    # A ranks first, B second, distant E third. A already includes B as its neighbor.
    embedder = FakeEmbedder(((1, 0), (1, 0), (1, 0.1), (0, 1), (0, 1), (1, 1)))
    selected = asyncio.run(select_context(index, "q", embedder, fits_characters(len(expected))))
    # B must expand to C before E spends the remaining budget; B is charged only once.
    assert selected.model_text == expected
    assert tuple(selected.passages) == ("p0001", "p0002", "p0003")


def test_boundary_neighbors_and_tied_hits_follow_document_order() -> None:
    index = build_passage_index(b"first\n\nnext\n\nthird\n\nlast\n")
    fits = fits_characters(len("[p0001] first\n\n[p0002] next\n"))
    embedder = FakeEmbedder(((1, 0), *((1, 0),) * 4))
    selected = asyncio.run(select_context(index, "q", embedder, fits))
    assert tuple(selected.passages) == ("p0001", "p0002")
    embedder.vectors = ((1, 0), (0, 1), (0, 1), (0, 1), (1, 0))
    selected = asyncio.run(select_context(index, "q", embedder, fits))
    assert tuple(selected.passages) == ("p0003", "p0004")


@pytest.mark.parametrize("ids", [("p0015",), (), ("p0020",), ("p9999",), ("p0015", "p0015")])
def test_selected_extraction_grounding_empty_output_and_rejected_ids(
    ids: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    content, embedder = large_paper()
    full = build_passage_index(project_grobid(content))
    projections: list[bytes] = []

    def project(value: bytes) -> bytes:
        projections.append(value)
        return project_grobid(value)

    monkeypatch.setattr(content_module, "project_grobid", project)

    class CheckingModel(FakeModel):
        async def generate(
            self, instructions: str, input_text: str, schema: Mapping[str, object]
        ) -> bytes:
            assert "[p0015] " + full.passages["p0015"] in input_text
            assert "[p0020]" not in input_text
            assert await self.fits_context(instructions, input_text, schema)
            return proposal_bytes(ids) if ids else b'{"evidence":[]}'

    async def extract() -> object:
        result = await extract_evidence(
            question="q",
            source=SOURCE,
            content=content,
            model=CheckingModel(b"", context_tokens=50_000),
            embedder=embedder,
        )
        assert result.content_sha256 == sha256(content).hexdigest()
        assert result.source is SOURCE
        assert tuple(p for evidence in result.evidence for p in evidence.passages) == (
            (full.passages["p0015"],) if ids else ()
        )
        return result

    if ids in (("p0015",), ()):
        asyncio.run(extract())
    else:
        with pytest.raises(ValueError):
            asyncio.run(extract())
    assert projections == [content]
    assert full.resolve("p0020")  # Still available in the authoritative full index.


@pytest.mark.parametrize("ids", [("p0020",), (), ("p9999",), ("p0020", "p0020")])
def test_large_paper_without_embedder_preserves_full_paper_extraction(
    ids: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    content, _ = large_paper()
    full = build_passage_index(project_grobid(content))
    projections: list[bytes] = []

    def project(value: bytes) -> bytes:
        projections.append(value)
        return project_grobid(value)

    monkeypatch.setattr(content_module, "project_grobid", project)

    class CheckingModel(FakeModel):
        async def generate(
            self, instructions: str, input_text: str, schema: Mapping[str, object]
        ) -> bytes:
            assert input_text == full.model_text
            assert len(input_text) > 60_000
            return await super().generate(instructions, input_text, schema)

    assert (
        asyncio.run(select_context(full, "q", None, fits_characters(len(full.model_text)))) is full
    )
    model = CheckingModel(proposal_bytes(ids) if ids else b'{"evidence":[]}')

    async def extract() -> None:
        result = await extract_evidence(
            question="q", source=SOURCE, content=content, model=model, embedder=None
        )
        assert result.content_sha256 == sha256(content).hexdigest()
        assert result.source is SOURCE
        assert tuple(p for evidence in result.evidence for p in evidence.passages) == (
            (full.passages["p0020"],) if ids else ()
        )

    if ids in (("p0020",), ()):
        asyncio.run(extract())
    else:
        with pytest.raises(ValueError):
            asyncio.run(extract())
    assert model.calls == 1
    assert projections == [content]


@pytest.mark.parametrize(
    "code",
    [
        "malformed_embedding_vectors",
        "ollama_embedding_transport_failure",
        "ollama_embedding_http_failure",
    ],
)
def test_large_paper_embedding_failure_propagates_before_model_generation(code: str) -> None:
    content, _ = large_paper()
    full = build_passage_index(project_grobid(content))
    assert len(full.model_text) > 60_000
    error = EmbeddingError(code)

    class FailingEmbedder:
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            raise error

    embedder = FakeEmbedder(()) if code == "malformed_embedding_vectors" else FailingEmbedder()
    with pytest.raises(EmbeddingError) as selected_error:
        asyncio.run(select_context(full, "q", embedder, fits_characters()))
    assert str(selected_error.value) == code
    if code != "malformed_embedding_vectors":
        assert selected_error.value is error

    model = FakeModel(proposal_bytes(), context_tokens=50_000)
    with pytest.raises(EmbeddingError) as extraction_error:
        asyncio.run(
            extract_evidence(
                question="q", source=SOURCE, content=content, model=model, embedder=embedder
            )
        )
    assert str(extraction_error.value) == code
    if code != "malformed_embedding_vectors":
        assert extraction_error.value is error
    assert model.calls == 0


@pytest.mark.parametrize(
    "error", [ValueError("programming error"), RuntimeError("programming error")]
)
def test_large_paper_unrelated_embedding_errors_propagate(error: Exception) -> None:
    content, _ = large_paper()
    model = FakeModel(proposal_bytes(), context_tokens=50_000)

    class BrokenEmbedder:
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            raise error

    with pytest.raises(type(error)) as raised:
        asyncio.run(
            extract_evidence(
                question="q", source=SOURCE, content=content, model=model, embedder=BrokenEmbedder()
            )
        )
    assert raised.value is error
    assert model.calls == 0


@pytest.mark.parametrize("fault", [None, "validation", "provider"])
def test_semantic_review_uses_embedder_only_for_large_paper_extraction(
    monkeypatch: pytest.MonkeyPatch,
    fault: str | None,
) -> None:
    monkeypatch.setattr(openalex_module, "_pace_semantic", lambda: no_sleep(0))
    content, passage_embedder = large_paper()
    calls: list[tuple[str, ...]] = []
    visible: list[str] = []
    error = EmbeddingError("ollama_embedding_transport_failure")

    class SharedEmbedder:
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            calls.append(texts)
            if fault == "provider":
                raise error
            return () if fault == "validation" else passage_embedder.vectors

    class Model(FakeModel):
        async def generate(
            self, instructions: str, input_text: str, schema: Mapping[str, object]
        ) -> bytes:
            visible.append(input_text)
            return proposal_bytes(("p0015",))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            assert request.url.path == "/works"
            assert request.url.params["search.semantic"] == "question"
            assert "search" not in request.url.params
            assert request.url.params["filter"] == "has_fulltext:true"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "has_content": {"grobid_xml": True, "pdf": True},
                            "id": "W1",
                            "title": "Learning",
                        }
                    ]
                },
            )
        return httpx.Response(200, content=content)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            if fault is not None:
                with pytest.raises(EmbeddingError) as raised:
                    await collect_evidence(
                        "question",
                        literature=OpenAlex(KEY, client),
                        model=Model(b"", context_tokens=50_000),
                        embedder=SharedEmbedder(),
                        max_sources=1,
                    )
                assert str(raised.value) == (
                    "malformed_embedding_vectors" if fault == "validation" else str(error)
                )
                if fault == "provider":
                    assert raised.value is error
                return
            result = await collect_evidence(
                "question",
                literature=OpenAlex(KEY, client),
                model=Model(b"", context_tokens=50_000),
                embedder=SharedEmbedder(),
                max_sources=1,
            )
            assert result.question == "question"
            assert result.reviewed_sources == 1
            assert result.sources[0].source.key == "W1"
            assert result.sources[0].evidence[0].passages[0].startswith("Strong learning result.")

    asyncio.run(scenario())
    assert len(calls) == 1
    assert len(calls[0]) == len(passage_embedder.vectors)
    assert all(texts[0] == "question" for texts in calls)
    if fault is None:
        assert len(visible) == 1 and len(visible[0]) <= 50_000
    else:
        assert visible == []


def test_full_index_can_supply_another_context_view_later() -> None:
    content, embedder = large_paper()
    full: PassageIndex = build_passage_index(project_grobid(content))
    first = asyncio.run(select_context(full, "first question", embedder, fits_characters()))
    embedder.vectors = ((1, 0), *((1, 0) if i == 19 else (0, 1) for i in range(20)))
    second = asyncio.run(select_context(full, "second question", embedder, fits_characters()))
    assert "p0020" not in first.passages
    assert "p0020" in second.passages
    assert len(full.passages) == 20


@pytest.mark.parametrize(
    "advertised,override,reduced",
    [(262_144, None, False), (24_000, None, True), (262_144, 24_000, True)],
)
def test_ollama_extraction_uses_complete_request_and_model_capacity(
    advertised: int, override: int | None, reduced: bool
) -> None:
    content, embedder = large_paper()
    full = build_passage_index(project_grobid(content))
    assert len(full.model_text) > 60_000
    paths: list[str] = []
    question = "What improves learning?"
    ceiling = override if override is not None else advertised

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        payload = json.loads(request.content)
        if request.url.path == "/api/show":
            assert payload == {"model": "qwen3.5:4b"}
            return httpx.Response(
                200,
                json={
                    "model_info": {"qwen35.context_length": advertised},
                    "template": "<turn>{{.Content}}</turn>",
                    "messages": [{"role": "system", "content": "Embedded model instructions."}],
                },
            )
        assert request.url.path == "/api/chat"
        assert 0 < payload["options"]["num_ctx"] <= ceiling
        assert payload["options"]["num_predict"] == 127
        assert question in payload["messages"][0]["content"]
        visible = payload["messages"][1]["content"]
        assert visible == full.model_text if not reduced else visible != full.model_text
        assert "[p0015] " + full.resolve("p0015") in visible
        assert "[p0020]" in visible if not reduced else "[p0020]" not in visible
        return httpx.Response(
            200,
            json={
                "model": "qwen3.5:4b",
                "done": True,
                "message": {"content": proposal_bytes(("p0015",)).decode()},
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await extract_evidence(
                question=question,
                source=SOURCE,
                content=content,
                model=OllamaModel(
                    ProviderSettings(
                        model_name="qwen3.5:4b",
                        model_context_tokens=override,
                        model_max_output_tokens=127,
                    ),
                    client,
                ),
                embedder=embedder,
            )
            assert result.evidence[0].passages == (full.resolve("p0015"),)

    asyncio.run(scenario())
    assert paths == ["/api/show", "/api/chat"]
    assert embedder.calls == (
        [(question, *(text[:PASSAGE_EMBEDDING_CHARACTERS] for text in full.passages.values()))]
        if reduced
        else []
    )


def test_model_capacity_that_cannot_fit_any_passage_fails_before_generation() -> None:
    embedder = FakeEmbedder(((1, 0), (1, 0), (0, 1)))
    model = FakeModel(proposal_bytes(), context_tokens=1)
    with pytest.raises(ModelProviderError, match="context_capacity_cannot_fit_passage"):
        asyncio.run(
            extract_evidence(
                question="q", source=SOURCE, content=XML, model=model, embedder=embedder
            )
        )
    assert len(embedder.calls) == 1
    assert model.calls == 0


def test_oversized_extraction_without_embedder_fails_before_generation() -> None:
    content, _ = large_paper()
    model = FakeModel(proposal_bytes(), context_tokens=24_000)
    with pytest.raises(ModelProviderError, match="context_reduction_requires_embedder"):
        asyncio.run(extract_evidence(question="q", source=SOURCE, content=content, model=model))
    assert model.calls == 0


@pytest.mark.parametrize("margin", [0, -1])
def test_extraction_selection_accounts_for_overhead_even_when_paper_alone_fits(margin: int) -> None:
    full = build_passage_index(project_grobid(XML))
    question = "What does response time tell us?"
    instructions = EXTRACTION_INSTRUCTIONS + "\nResearch question:\n" + question
    schema = ExtractionProposal.model_json_schema()
    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": full.model_text},
    ]
    required = (
        len(json.dumps({"messages": messages, "format": schema}, ensure_ascii=False).encode()) + 127
    )
    ceiling = required + margin
    assert len(full.model_text) < ceiling
    embedder = FakeEmbedder(((1, 0), (1, 0), (0, 1)))
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"reference.context_length": ceiling}})
        payload = json.loads(request.content)
        assert payload["messages"][0]["content"] == instructions
        assert payload["format"] == schema
        assert payload["options"]["num_ctx"] <= ceiling
        assert payload["messages"][1]["content"] == (
            full.model_text if margin == 0 else f"[p0001] {full.resolve('p0001')}\n"
        )
        return httpx.Response(
            200,
            json={
                "model": "reference",
                "done": True,
                "message": {"content": proposal_bytes().decode()},
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await extract_evidence(
                question=question,
                source=SOURCE,
                content=XML,
                model=OllamaModel(
                    ProviderSettings(model_name="reference", model_max_output_tokens=127), client
                ),
                embedder=embedder,
            )
            assert result.evidence[0].passages == (full.resolve("p0001"),)

    asyncio.run(scenario())
    assert paths == ["/api/show", "/api/chat"]
    assert len(embedder.calls) == (0 if margin == 0 else 1)
