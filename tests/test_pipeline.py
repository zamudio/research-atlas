import asyncio
import sys

import httpx
import pytest

from conftest import RESULTS, MockHTTP
from research_atlas import EvidenceResult, evidence
from research_atlas.cli import main
from research_atlas.config import Settings


def test_complete_offline_pipeline_continues_failures_and_counts_successes(
    mock_http: MockHTTP, settings: Settings, grobid: bytes, pdf: bytes
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.host == "api.openalex.org":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": f"W{i}",
                            "title": f"Paper {i}",
                            "has_content": {"grobid_xml": True, "pdf": True},
                        }
                        for i in range(1, 6)
                    ]
                },
            )
        if request.url.path.startswith("/works/W1"):
            return httpx.Response(404)
        if request.url.path.startswith("/works/W2"):
            return httpx.Response(200, content=b"broken")
        if request.url.path == "/works/W3.grobid-xml":
            return httpx.Response(200, content=grobid)
        if request.url.path == "/works/W4.grobid-xml":
            return httpx.Response(503)
        if request.url.path == "/works/W4.pdf":
            return httpx.Response(200, content=pdf)
        pytest.fail("Fetched beyond max_papers or refetched metadata")

    mock_http(handler)
    question = "  Does spending time outside reduce stress?  "
    result = asyncio.run(evidence(question, max_papers=2, settings=settings))
    assert result.question == question
    assert [paper.work.openalex_id for paper in result.papers] == ["W3", "W4"]
    assert [(item.openalex_id, item.stage) for item in result.failures] == [
        ("W1", "acquisition"),
        ("W2", "preparation"),
    ]
    assert result.papers[0].source.kind == "grobid_xml"
    assert result.papers[1].source.kind == "openalex_pdf"
    assert result.papers[0].evidence[0].text == result.papers[1].evidence[0].text == RESULTS
    assert result.papers[0].evidence[0].passage_id == "p0002"
    assert result.papers[0].evidence[0].section == "Results"
    assert result.papers[1].evidence[0].section is None
    assert calls == [
        "/works",
        "/works/W1.grobid-xml",
        "/works/W1.pdf",
        "/works/W2.grobid-xml",
        "/works/W2.pdf",
        "/works/W3.grobid-xml",
        "/works/W4.grobid-xml",
        "/works/W4.pdf",
    ]
    encoded = result.model_dump_json()
    assert '"routes":' not in encoded and "test-secret" not in encoded
    assert EvidenceResult.model_validate_json(encoded).model_dump() == result.model_dump()


@pytest.mark.parametrize("mode", ["empty", "ineligible", "unavailable", "no_overlap"])
def test_empty_results_and_success_without_lexical_overlap(
    mode: str, mock_http: MockHTTP, settings: Settings, grobid: bytes
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            records = (
                []
                if mode == "empty"
                else [
                    {
                        "id": "W1",
                        "has_content": {"grobid_xml": mode != "ineligible"},
                    }
                ]
            )
            return httpx.Response(200, json={"results": records})
        return httpx.Response(404) if mode == "unavailable" else httpx.Response(200, content=grobid)

    mock_http(handler)
    result = asyncio.run(evidence("astronomy", settings=settings))
    assert len(result.papers) == (1 if mode == "no_overlap" else 0)
    assert len(result.failures) == (1 if mode == "unavailable" else 0)
    assert not result.papers or result.papers[0].evidence == ()


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_invalid_question_is_fatal_before_network(question: str, settings: Settings) -> None:
    with pytest.raises(ValueError, match="question"):
        asyncio.run(evidence(question, settings=settings))


@pytest.mark.parametrize("limit", [0, -1, 51, True, 1.5])
def test_invalid_paper_limit_is_fatal_before_network(limit: int, settings: Settings) -> None:
    with pytest.raises(ValueError, match="max_papers"):
        asyncio.run(evidence("stress", max_papers=limit, settings=settings))


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "121", "invalid"])
def test_invalid_timeout_is_fatal_before_network(
    timeout: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESEARCH_ATLAS_OPENALEX_API_KEY", "test-secret")
    monkeypatch.setenv("RESEARCH_ATLAS_HTTP_TIMEOUT_SECONDS", timeout)
    with pytest.raises(ValueError):
        asyncio.run(evidence("stress"))


def test_missing_configuration_is_fatal_before_network() -> None:
    with pytest.raises(ValueError):
        asyncio.run(evidence("stress"))


@pytest.mark.parametrize("mode", ["401", "429", "503", "timeout"])
def test_discovery_failures_are_fatal_without_retries(
    mode: str, mock_http: MockHTTP, settings: Settings
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if mode == "timeout":
            raise httpx.ConnectTimeout("offline")
        return httpx.Response(int(mode))

    mock_http(handler)
    with pytest.raises(httpx.HTTPError):
        asyncio.run(evidence("stress", settings=settings))
    assert calls == ["/works"]


def test_cli_executes_same_pipeline_and_emits_only_json(
    mock_http: MockHTTP,
    grobid: bytes,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RESEARCH_ATLAS_OPENALEX_API_KEY", "test-secret")
    monkeypatch.setattr(sys, "argv", ["atlas", "evidence", "stress", "--max-papers", "1"])
    mock_http(
        lambda request: (
            httpx.Response(
                200, json={"results": [{"id": "W1", "has_content": {"grobid_xml": True}}]}
            )
            if request.url.host == "api.openalex.org"
            else httpx.Response(200, content=grobid)
        )
    )
    assert main() == 0
    output = capsys.readouterr()
    result = EvidenceResult.model_validate_json(output.out)
    assert result.question == "stress" and result.papers[0].evidence[0].text == RESULTS
    assert output.err == ""


def test_cli_fatal_error_keeps_stdout_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["atlas", "evidence", "stress"])
    assert main() == 1
    output = capsys.readouterr()
    assert output.out == "" and "configuration" in output.err
