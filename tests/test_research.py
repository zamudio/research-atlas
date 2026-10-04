import asyncio
from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError, fields
from hashlib import sha256
from typing import cast

import httpx
import pytest
from pydantic import ValidationError

import research_atlas.content as content_module
import research_atlas.openalex as openalex_module
from research_atlas import EvidenceReview, collect_evidence
from research_atlas.extraction import EXTRACTION_INSTRUCTIONS, ExtractionProposal
from research_atlas.grobid import project_grobid
from research_atlas.openalex import OpenAlex, OpenAlexError
from research_atlas.providers import ModelProviderError
from tests.test_content import text_pdf
from tests.test_extraction import OTHER, PASSAGE, XML, proposal_bytes
from tests.test_openalex import KEY, no_sleep, work_response

QUESTION = "  What does response time tell us about learning?\n"


class ReviewModel:
    def __init__(
        self,
        replies: tuple[bytes | Exception, ...] = (proposal_bytes(),),
        events: list[str] | None = None,
    ) -> None:
        self.replies = replies
        self.events = events
        self.questions: list[str] = []
        self.documents: list[str] = []

    async def generate(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bytes:
        assert instructions.startswith(EXTRACTION_INSTRUCTIONS + "\nResearch question:\n")
        assert schema == ExtractionProposal.model_json_schema()
        reply = self.replies[len(self.questions)]
        self.questions.append(
            instructions.removeprefix(EXTRACTION_INSTRUCTIONS + "\nResearch question:\n")
        )
        self.documents.append(input_text)
        if self.events is not None:
            self.events.append("extract")
        # Yield so accidental concurrent extraction changes observable call order.
        await asyncio.sleep(0)
        if self.events is not None:
            self.events.append("extracted")
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture(autouse=True)
def unpaced_semantic_search(monkeypatch: pytest.MonkeyPatch) -> None:
    async def pace() -> None:
        pass

    monkeypatch.setattr(openalex_module, "_pace_semantic", pace)


async def review_with_transport(
    handler: Callable[[httpx.Request], httpx.Response],
    model: ReviewModel,
    *,
    question: str = QUESTION,
    max_sources: int = 20,
) -> EvidenceReview:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await collect_evidence(
            question,
            literature=OpenAlex(KEY, client, retry_sleep=no_sleep),
            model=model,
            max_sources=max_sources,
        )


def test_whole_flow_preserves_question_and_returns_grounded_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    projections: list[bytes] = []

    def project(content: bytes) -> bytes:
        projections.append(content)
        return project_grobid(content)

    monkeypatch.setattr(content_module, "project_grobid", project)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            if request.url.path != "/works":
                events.append("metadata W2")
                return work_response(request)
            events.append("search")
            assert request.url.params["search.semantic"] == QUESTION
            assert "search" not in request.url.params
            assert request.url.params["per_page"] == "50"
            return httpx.Response(200, json={"results": [{"id": "W2", "title": "Learning"}]})
        assert request.url.path == "/works/W2.grobid-xml"
        events.append("fetch W2")
        return httpx.Response(200, content=XML)

    model = ReviewModel(events=events)
    review = asyncio.run(review_with_transport(handler, model))
    assert isinstance(review, EvidenceReview)
    assert review.question == QUESTION
    assert review.reviewed_sources == 1
    assert len(review.sources) == 1
    assert review.sources[0].source.title == "Learning"
    assert review.sources[0].source.key == "W2"
    assert review.sources[0].content_sha256 == sha256(XML).hexdigest()
    assert review.sources[0].evidence[0].passages == (PASSAGE,)
    assert model.questions == [QUESTION]
    assert model.documents == [f"[p0001] {PASSAGE}\n\n[p0002] {OTHER}\n"]
    assert events == ["search", "fetch W2", "extract", "extracted"]
    assert projections == [XML]
    assert [field.name for field in fields(review)] == ["question", "reviewed_sources", "sources"]
    assert not hasattr(review, "__dict__")
    with pytest.raises(FrozenInstanceError):
        review.question = "changed"  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize("fault", ["missing", "oversized"])
def test_unavailable_content_is_skipped_and_next_candidate_reviewed(
    fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(openalex_module, "MAX_CONTENT_BYTES", len(XML))
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/works":
            assert request.url.params["per_page"] == "50"
            return httpx.Response(200, json={"results": [{"id": "W1"}, {"id": "W2"}]})
        if request.url.host == "api.openalex.org":
            return work_response(request)
        fetched.append(request.url.path)
        if request.url.path == "/works/W1.grobid-xml":
            if fault == "missing":
                return httpx.Response(404)
            return httpx.Response(200, content=b"x" * (len(XML) + 1))
        if request.url.path.endswith(".pdf"):
            return httpx.Response(404)
        return httpx.Response(200, content=XML)

    model = ReviewModel()
    review = asyncio.run(review_with_transport(handler, model, max_sources=1))
    assert review.reviewed_sources == 1
    assert tuple(result.source.key for result in review.sources) == ("W2",)
    assert model.questions == [QUESTION]
    assert fetched == ["/works/W1.grobid-xml", "/works/W1.pdf", "/works/W2.grobid-xml"]


@pytest.mark.parametrize("content", [b"<TEI", b'<TEI xmlns="http://www.tei-c.org/ns/1.0"/>'])
def test_unusable_grobid_is_skipped(content: bytes) -> None:
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/works":
            return httpx.Response(200, json={"results": [{"id": "W1"}, {"id": "W2"}]})
        if request.url.host == "api.openalex.org":
            return work_response(request)
        fetched.append(request.url.path)
        return httpx.Response(200, content=content)

    model = ReviewModel(())
    review = asyncio.run(review_with_transport(handler, model))
    assert review.reviewed_sources == 0
    assert model.questions == []
    assert fetched == [
        "/works/W1.grobid-xml",
        "/works/W1.pdf",
        "/works/W2.grobid-xml",
        "/works/W2.pdf",
    ]


def test_irrelevant_paper_counts_toward_bound_without_contributing_evidence() -> None:
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            if request.url.path != "/works":
                return work_response(request)
            return httpx.Response(200, json={"results": [{"id": "W1"}, {"id": "W2"}]})
        fetched.append(request.url.path)
        return httpx.Response(200, content=XML)

    model = ReviewModel((b'{"evidence": []}',))
    review = asyncio.run(review_with_transport(handler, model, max_sources=1))
    assert review == EvidenceReview(QUESTION, 1, ())
    assert model.questions == [QUESTION]
    assert fetched == ["/works/W1.grobid-xml"]


def test_review_is_sequential_bounded_and_preserves_provider_order() -> None:
    events: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            if request.url.path != "/works":
                events.append(request.url.path)
                return work_response(request)
            events.append("search")
            return httpx.Response(
                200, json={"results": [{"id": f"W{i}"} for i in (3, 1, 2, 4, 5, 6)]}
            )
        events.append(request.url.path)
        return httpx.Response(200, content=XML)

    model = ReviewModel((proposal_bytes(), b'{"evidence": []}', proposal_bytes()), events)
    review = asyncio.run(review_with_transport(handler, model, max_sources=3))
    assert review.reviewed_sources == 3
    assert tuple(result.source.key for result in review.sources) == ("W3", "W2")
    assert model.questions == [QUESTION] * 3
    assert events == [
        "search",
        "/works/W3.grobid-xml",
        "extract",
        "extracted",
        "/works/W1.grobid-xml",
        "extract",
        "extracted",
        "/works/W2.grobid-xml",
        "extract",
        "extracted",
    ]


@pytest.mark.parametrize("max_sources", [1, 20, 25, 26, 50])
def test_candidate_compensation_and_empty_search(max_sources: int) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.openalex.org"
        assert request.url.params["per_page"] == "50"
        assert request.url.params["search.semantic"] == QUESTION
        return httpx.Response(200, json={"results": []})

    model = ReviewModel(())
    review = asyncio.run(review_with_transport(handler, model, max_sources=max_sources))
    assert review == EvidenceReview(QUESTION, 0, ())
    assert len(requests) == 1
    assert model.questions == []


@pytest.mark.parametrize("usable", [False, True])
def test_exhausted_candidates_return_partial_or_empty_review(usable: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/works":
            return httpx.Response(200, json={"results": [{"id": "W1"}, {"id": "W2"}]})
        if request.url.host == "api.openalex.org":
            return work_response(request)
        if usable and request.url.path == "/works/W2.grobid-xml":
            return httpx.Response(200, content=XML)
        return httpx.Response(404)

    model = ReviewModel()
    review = asyncio.run(review_with_transport(handler, model))
    assert review.reviewed_sources == int(usable)
    assert len(review.sources) == int(usable)
    assert len(model.questions) == int(usable)


@pytest.mark.parametrize("phase", ["search", "content"])
@pytest.mark.parametrize("fault", ["429", "503", "transport", "empty", "invalid"])
def test_general_openalex_failures_propagate(phase: str, fault: str) -> None:
    failing_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal failing_calls
        if phase == "content" and request.url.path == "/works":
            return httpx.Response(200, json={"results": [{"id": "W1"}, {"id": "W2"}]})
        failing_calls += 1
        if fault == "transport":
            raise httpx.ConnectError("remote failure", request=request)
        if fault == "empty":
            return httpx.Response(200, content=b"")
        if fault == "invalid":
            return httpx.Response(401) if phase == "content" else httpx.Response(200, content=b"{}")
        return httpx.Response(int(fault), headers={"Retry-After": "0"})

    model = ReviewModel(())
    expected = {
        "429": "http_429",
        "503": "http_503",
        "transport": "transport_failure",
        "empty": "empty_response",
        "invalid": "http_401" if phase == "content" else "malformed_search_response",
    }[fault]
    with pytest.raises(OpenAlexError) as error:
        asyncio.run(review_with_transport(handler, model))
    assert error.value.code == expected
    assert str(error.value) == expected
    attempts = 3 if fault in {"429", "503", "transport"} else 1
    assert failing_calls == attempts * (
        2 if phase == "content" and fault in {"503", "transport", "empty"} else 1
    )
    assert model.questions == []


@pytest.mark.parametrize(
    "reply,exception_type",
    [
        (ModelProviderError("provider_failed"), ModelProviderError),
        (TimeoutError("model timed out"), TimeoutError),
        (b"not JSON", ValidationError),
        (proposal_bytes(("p9999",)), ValueError),
    ],
)
def test_model_and_grounding_failures_propagate(
    reply: bytes | Exception, exception_type: type[Exception]
) -> None:
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            if request.url.path != "/works":
                return work_response(request)
            return httpx.Response(200, json={"results": [{"id": "W1"}, {"id": "W2"}]})
        fetched.append(request.url.path)
        return httpx.Response(200, content=XML)

    model = ReviewModel((reply,))
    with pytest.raises(exception_type) as error:
        asyncio.run(review_with_transport(handler, model))
    if isinstance(reply, Exception):
        assert error.value is reply
    assert model.questions == [QUESTION]
    assert fetched == ["/works/W1.grobid-xml"]


@pytest.mark.parametrize("question", ["", " \t\n", "x" * 2001, None, 42, b"question"])
def test_question_validation_precedes_io(question: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("validation must precede search")

    model = ReviewModel(())
    with pytest.raises(ValueError, match="question"):
        asyncio.run(review_with_transport(handler, model, question=cast(str, question)))
    assert model.questions == []


@pytest.mark.parametrize("max_sources", [0, 51, True, False, 1.5, "2", None])
def test_review_limit_validation_precedes_io(max_sources: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("validation must precede search")

    model = ReviewModel(())
    with pytest.raises(ValueError, match="max_sources"):
        asyncio.run(review_with_transport(handler, model, max_sources=cast(int, max_sources)))
    assert model.questions == []


def test_question_at_character_bound_is_passed_unchanged() -> None:
    question = " " + "q" * 1998 + "\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            if request.url.path != "/works":
                return work_response(request)
            assert request.url.params["search.semantic"] == question
            return httpx.Response(200, json={"results": [{"id": "W1"}]})
        return httpx.Response(200, content=XML)

    model = ReviewModel()
    review = asyncio.run(review_with_transport(handler, model, question=question))
    assert review.question == question
    assert model.questions == [question]


@pytest.mark.parametrize("pdf_backed", [False, True])
def test_review_reaches_deep_candidates_and_stops_at_usable_paper_limit(
    pdf_backed: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched: list[str] = []
    projections: list[bytes] = []
    original = text_pdf() if pdf_backed else XML
    real_prepare = content_module._project_pdf if pdf_backed else project_grobid  # pyright: ignore[reportPrivateUsage]

    def project(value: bytes) -> bytes:
        projections.append(value)
        return real_prepare(value)

    monkeypatch.setattr(content_module, "_project_pdf" if pdf_backed else "project_grobid", project)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/works":
            assert request.url.params["per_page"] == "50"
            return httpx.Response(200, json={"results": [{"id": f"W{i}"} for i in range(1, 51)]})
        fetched.append(request.url.path)
        if request.url.host == "api.openalex.org":
            return work_response(request, grobid=False, pdf=False)
        extension = "pdf" if pdf_backed else "grobid-xml"
        if request.url.path in {f"/works/W{i}.{extension}" for i in (8, 9, 10, 11)}:
            return httpx.Response(200, content=original)
        return httpx.Response(404)

    model = ReviewModel((proposal_bytes(), b'{"evidence":[]}', proposal_bytes()))
    review = asyncio.run(review_with_transport(handler, model, max_sources=3))
    assert review.reviewed_sources == 3
    assert tuple(result.source.key for result in review.sources) == ("W8", "W10")
    assert len(model.questions) == 3
    assert projections == [original] * 3
    assert all("W11" not in path for path in fetched)
    assert len(fetched) == (30 if pdf_backed else 24)
    assert all(result.content_sha256 == sha256(original).hexdigest() for result in review.sources)


def test_exhausting_fifty_candidates_with_negative_metadata_still_probes_cached_formats() -> None:
    downloads = 0
    metadata = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal downloads, metadata
        if request.url.path == "/works":
            return httpx.Response(200, json={"results": [{"id": f"W{i}"} for i in range(1, 51)]})
        if request.url.host == "api.openalex.org":
            metadata += 1
            return httpx.Response(
                200,
                json={
                    "id": request.url.path.rsplit("/", 1)[1],
                    "has_content": {"grobid_xml": False, "pdf": False},
                    "locations": [],
                },
            )
        downloads += 1
        return (
            httpx.Response(200, content=text_pdf(""))
            if request.url.path.endswith(".pdf")
            else httpx.Response(404)
        )

    model = ReviewModel(())
    review = asyncio.run(review_with_transport(handler, model, max_sources=3))
    assert review == EvidenceReview(QUESTION, 0, ())
    assert downloads == 100 and metadata == 50
    assert model.questions == []
