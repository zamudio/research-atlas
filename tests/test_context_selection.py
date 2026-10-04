import asyncio
from collections.abc import Mapping
from hashlib import sha256
from xml.sax.saxutils import escape

import httpx
import pytest

import research_atlas.content as content_module
import research_atlas.openalex as openalex_module
import research_atlas.passages as passages_module
from research_atlas import collect_evidence, extract_evidence
from research_atlas.embeddings import EmbeddingError
from research_atlas.grobid import project_grobid
from research_atlas.openalex import OpenAlex
from research_atlas.passages import (
    PAPER_CONTEXT_CHARACTERS,
    PASSAGE_EMBEDDING_CHARACTERS,
    PassageIndex,
    build_passage_index,
    select_context,
)
from tests.test_embeddings import FakeEmbedder
from tests.test_extraction import SOURCE, XML, FakeModel, proposal_bytes
from tests.test_openalex import KEY, no_sleep


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
    selected = asyncio.run(select_context(index, "q", embedder if with_embedder else None))
    assert selected is index
    assert embedder.calls == []


def test_exact_threshold_retains_full_paper(monkeypatch: pytest.MonkeyPatch) -> None:
    index = build_passage_index(project_grobid(XML))
    embedder = FakeEmbedder(((1, 0), (1, 0), (0, 1)))
    monkeypatch.setattr(passages_module, "PAPER_CONTEXT_CHARACTERS", len(index.model_text))
    assert asyncio.run(select_context(index, "q", embedder)) is index
    assert embedder.calls == []
    monkeypatch.setattr(passages_module, "PAPER_CONTEXT_CHARACTERS", len(index.model_text) - 1)
    assert asyncio.run(select_context(index, "q", None)) is index
    selected = asyncio.run(select_context(index, "q", embedder))
    assert selected is not index
    assert len(selected.model_text) < len(index.model_text)
    assert len(embedder.calls) == 1


def test_large_paper_prioritizes_hits_neighbors_and_restores_original_ids_and_order() -> None:
    content, embedder = large_paper()
    index = build_passage_index(project_grobid(content))
    original = dict(index.passages)
    question = "  What improves learning?\n"
    selected = asyncio.run(select_context(index, question, embedder))
    assert len(index.model_text) > PAPER_CONTEXT_CHARACTERS
    assert len(selected.model_text) <= PAPER_CONTEXT_CHARACTERS
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


def test_hit_takes_priority_over_neighbors_that_do_not_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    index = build_passage_index(b"left\n\nstrong\n\nright\n\nlast\n")
    hit_cost = len("[p0002] strong\n")
    monkeypatch.setattr(passages_module, "PAPER_CONTEXT_CHARACTERS", hit_cost)
    embedder = FakeEmbedder(((1, 0), (0, 1), (1, 0), (0, 1), (0, 1)))
    selected = asyncio.run(select_context(index, "q", embedder))
    assert tuple(selected.passages) == ("p0002",)
    assert len(selected.model_text) == hit_cost


def test_overlapping_strong_hit_expands_its_window_before_a_distant_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = build_passage_index(b"AAAA\n\nBBBB\n\nCCCC\n\nDDDD\n\nEEEE\n")
    expected = "[p0001] AAAA\n\n[p0002] BBBB\n\n[p0003] CCCC\n"
    monkeypatch.setattr(passages_module, "PAPER_CONTEXT_CHARACTERS", len(expected))
    # A ranks first, B second, distant E third. A already includes B as its neighbor.
    embedder = FakeEmbedder(((1, 0), (1, 0), (1, 0.1), (0, 1), (0, 1), (1, 1)))
    selected = asyncio.run(select_context(index, "q", embedder))
    # B must expand to C before E spends the remaining budget; B is charged only once.
    assert selected.model_text == expected
    assert tuple(selected.passages) == ("p0001", "p0002", "p0003")


def test_boundary_neighbors_and_tied_hits_follow_document_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = build_passage_index(b"first\n\nnext\n\nthird\n\nlast\n")
    monkeypatch.setattr(
        passages_module, "PAPER_CONTEXT_CHARACTERS", len("[p0001] first\n\n[p0002] next\n")
    )
    embedder = FakeEmbedder(((1, 0), *((1, 0),) * 4))
    selected = asyncio.run(select_context(index, "q", embedder))
    assert tuple(selected.passages) == ("p0001", "p0002")
    embedder.vectors = ((1, 0), (0, 1), (0, 1), (0, 1), (1, 0))
    selected = asyncio.run(select_context(index, "q", embedder))
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

    class CheckingModel:
        async def generate(
            self, instructions: str, input_text: str, schema: Mapping[str, object]
        ) -> bytes:
            assert "[p0015] " + full.passages["p0015"] in input_text
            assert "[p0020]" not in input_text
            assert len(input_text) <= PAPER_CONTEXT_CHARACTERS
            return proposal_bytes(ids) if ids else b'{"evidence":[]}'

    async def extract() -> object:
        result = await extract_evidence(
            question="q", source=SOURCE, content=content, model=CheckingModel(), embedder=embedder
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


@pytest.mark.parametrize("fault", ["missing", "validation", "provider"])
@pytest.mark.parametrize("ids", [("p0020",), (), ("p9999",), ("p0020", "p0020")])
def test_large_paper_unavailable_embeddings_preserve_full_paper_extraction(
    fault: str, ids: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    content, _ = large_paper()
    full = build_passage_index(project_grobid(content))
    projections: list[bytes] = []

    def project(value: bytes) -> bytes:
        projections.append(value)
        return project_grobid(value)

    monkeypatch.setattr(content_module, "project_grobid", project)

    class FailingEmbedder:
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            raise EmbeddingError("ollama_embedding_transport_failure")

    class CheckingModel(FakeModel):
        async def generate(
            self, instructions: str, input_text: str, schema: Mapping[str, object]
        ) -> bytes:
            assert input_text == full.model_text
            assert len(input_text) > PAPER_CONTEXT_CHARACTERS
            return await super().generate(instructions, input_text, schema)

    embedder = (
        None
        if fault == "missing"
        else (FakeEmbedder(()) if fault == "validation" else FailingEmbedder())
    )
    assert asyncio.run(select_context(full, "q", embedder)) is full
    model = CheckingModel(proposal_bytes(ids) if ids else b'{"evidence":[]}')

    async def extract() -> None:
        result = await extract_evidence(
            question="q", source=SOURCE, content=content, model=model, embedder=embedder
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
    "error", [ValueError("programming error"), RuntimeError("programming error")]
)
def test_large_paper_unrelated_embedding_errors_propagate(error: Exception) -> None:
    content, _ = large_paper()
    model = FakeModel(proposal_bytes())

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


def test_semantic_review_uses_embedder_only_for_large_paper_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(openalex_module, "_pace_semantic", lambda: no_sleep(0))
    content, passage_embedder = large_paper()
    calls: list[tuple[str, ...]] = []
    visible: list[str] = []

    class SharedEmbedder:
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            calls.append(texts)
            return passage_embedder.vectors

    class Model:
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
            result = await collect_evidence(
                "question",
                literature=OpenAlex(KEY, client),
                model=Model(),
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
    assert len(visible) == 1 and len(visible[0]) <= PAPER_CONTEXT_CHARACTERS


def test_full_index_can_supply_another_context_view_later() -> None:
    content, embedder = large_paper()
    full: PassageIndex = build_passage_index(project_grobid(content))
    first = asyncio.run(select_context(full, "first question", embedder))
    embedder.vectors = ((1, 0), *((1, 0) if i == 19 else (0, 1) for i in range(20)))
    second = asyncio.run(select_context(full, "second question", embedder))
    assert "p0020" not in first.passages
    assert "p0020" in second.passages
    assert len(full.passages) == 20
