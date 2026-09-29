import asyncio
import json
from pathlib import Path

import pytest

from research_atlas.application.ports.literature_source import LiteratureQuery, LiteratureRecord
from research_atlas.cli import dry_run
from research_atlas.infrastructure.config import ProviderSettings


class FakeOpenAlex:
    provider_id = "openalex"
    operation_id = "openalex.search"

    def __init__(self, _api_key: str | None = None) -> None:
        pass

    async def search(self, _query: LiteratureQuery) -> tuple[LiteratureRecord, ...]:
        return ()


class FakeSemantic(FakeOpenAlex):
    operation_id = "openalex.semantic"


class FakeCrossref(FakeOpenAlex):
    provider_id = "crossref"
    operation_id = "crossref.works"

    def __init__(self, mailto: str | None = None) -> None:
        assert mailto == "researcher@example.test"


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dry_run, "OpenAlexLiteratureSource", FakeOpenAlex)
    monkeypatch.setattr(dry_run, "OpenAlexSemanticSearch", FakeSemantic)
    monkeypatch.setattr(dry_run, "CrossrefWorksSearch", FakeCrossref)
    monkeypatch.setenv("RESEARCH_ATLAS_CROSSREF_MAILTO", "researcher@example.test")


def test_cli_supported_operations_preserve_exact_queries_and_write_report(
    providers: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "dry-run.json"
    assert (
        dry_run.main(
            [
                " lexical query ",
                "--openalex-semantic",
                " semantic question? ",
                "--crossref-bibliographic",
                " bibliography ",
                "--limit",
                "2",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert json.loads(output.read_text()) == report
    assert [(item["operation"], item["query"], item["limit"]) for item in report["searches"]] == [
        ("openalex.search", " lexical query ", 2),
        ("openalex.semantic", " semantic question? ", 2),
        ("crossref.works", " bibliography ", 2),
    ]
    assert report["metadata_observations"] == []
    assert captured.err == ""


def test_openalex_only_is_the_default(providers: None) -> None:
    report = json.loads(
        asyncio.run(dry_run.run_dry_run("question", limit=1, settings=ProviderSettings()))
    )
    assert [item["operation"] for item in report["searches"]] == ["openalex.search"]


def test_cli_failure_has_json_stdout_and_nonzero_exit(
    providers: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FailingSource(FakeOpenAlex):
        async def search(self, _query: LiteratureQuery) -> tuple[LiteratureRecord, ...]:
            raise RuntimeError("unavailable")

    monkeypatch.setattr(dry_run, "OpenAlexLiteratureSource", FailingSource)
    assert dry_run.main(["query"]) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["provider_outcomes"][0]["success"] is False
    assert "all literature searches failed" in captured.err
