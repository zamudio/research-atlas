import asyncio
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType

import pytest

from research_atlas.application.ports.literature_source import LiteratureQuery
from research_atlas.domain.studies import SourceRecord
from research_atlas.infrastructure.config import ProviderSettings


class FakeSource:
    provider_id = "fake"
    operation_id = "fake.search"

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def search(self, _query: LiteratureQuery) -> tuple[SourceRecord, ...]:
        return ()


class FakeOpenAlexSource(FakeSource):
    provider_id = "openalex"
    operation_id = "openalex.search"


class FakeRelevanceSource(FakeSource):
    provider_id = "semantic_scholar"
    operation_id = "semantic_scholar.relevance"


class FakeBulkSource(FakeSource):
    provider_id = "semantic_scholar"
    operation_id = "semantic_scholar.bulk"


class RecordingGuard(AbstractContextManager[object]):
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def __enter__(self) -> object:
        self._events.append("acquire")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self._events.append("release")


@pytest.fixture
def fake_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_atlas.cli import dry_run

    monkeypatch.setattr(dry_run, "OpenAlexLiteratureSource", FakeOpenAlexSource)
    monkeypatch.setattr(dry_run, "SemanticScholarRelevanceSearch", FakeRelevanceSource)
    monkeypatch.setattr(dry_run, "SemanticScholarBulkSearch", FakeBulkSource)


def test_openalex_only_dry_run_does_not_acquire_s2_guard(fake_sources: None) -> None:
    from research_atlas.cli.dry_run import run_dry_run

    acquisitions = 0

    def forbidden_guard() -> AbstractContextManager[object]:
        nonlocal acquisitions
        acquisitions += 1
        raise AssertionError("OpenAlex-only execution must not acquire the S2 guard")

    asyncio.run(
        run_dry_run(
            "openalex only",
            limit=1,
            settings=ProviderSettings(),
            ownership_guard_factory=forbidden_guard,
        )
    )

    assert acquisitions == 0


def test_s2_dry_run_acquires_and_releases_guard(fake_sources: None) -> None:
    from research_atlas.cli.dry_run import run_dry_run

    events: list[str] = []

    asyncio.run(
        run_dry_run(
            "openalex",
            limit=1,
            settings=ProviderSettings(),
            semantic_scholar_relevance_query="s2 relevance",
            ownership_guard_factory=lambda: RecordingGuard(events),
        )
    )

    assert events == ["acquire", "release"]


def test_bulk_query_file_preserves_exact_complex_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_atlas.cli import dry_run

    exact_query = '"intelligent tutoring systems" + ("meta analysis" | "systematic review") -survey'
    query_file = tmp_path / "s2-bulk-query.txt"
    query_file.write_text(exact_query, encoding="utf-8", newline="")
    received_query: str | None = None

    async def fake_run_dry_run(
        query_text: str,
        *,
        limit: int,
        settings: ProviderSettings,
        semantic_scholar_relevance_query: str | None = None,
        semantic_scholar_bulk_query: str | None = None,
        **_kwargs: object,
    ) -> str:
        del query_text, limit, settings, semantic_scholar_relevance_query
        nonlocal received_query
        received_query = semantic_scholar_bulk_query
        return "{}\n"

    monkeypatch.setattr(dry_run, "run_dry_run", fake_run_dry_run)

    result = dry_run.main(
        ["openalex query", "--semantic-scholar-bulk-file", str(query_file), "--limit", "1"]
    )

    assert result == 0
    assert received_query == exact_query


def test_bulk_query_file_preserves_crlf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_atlas.cli import dry_run

    exact_query = '"intelligent tutoring systems" + review\r\n-year:2020\r\n'
    query_file = tmp_path / "s2-bulk-query.txt"
    query_file.write_text(exact_query, encoding="utf-8", newline="")
    received_query: str | None = None

    async def fake_run_dry_run(
        query_text: str,
        *,
        limit: int,
        settings: ProviderSettings,
        semantic_scholar_relevance_query: str | None = None,
        semantic_scholar_bulk_query: str | None = None,
        **_kwargs: object,
    ) -> str:
        del query_text, limit, settings, semantic_scholar_relevance_query
        nonlocal received_query
        received_query = semantic_scholar_bulk_query
        return "{}\n"

    monkeypatch.setattr(dry_run, "run_dry_run", fake_run_dry_run)

    result = dry_run.main(
        ["openalex query", "--semantic-scholar-bulk-file", str(query_file), "--limit", "1"]
    )

    assert result == 0
    assert received_query == exact_query


def test_inline_bulk_query_remains_backward_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_atlas.cli import dry_run

    exact_query = '"intelligent tutoring systems" + review'
    received_query: str | None = None

    async def fake_run_dry_run(
        query_text: str,
        *,
        limit: int,
        settings: ProviderSettings,
        semantic_scholar_relevance_query: str | None = None,
        semantic_scholar_bulk_query: str | None = None,
        **_kwargs: object,
    ) -> str:
        del query_text, limit, settings, semantic_scholar_relevance_query
        nonlocal received_query
        received_query = semantic_scholar_bulk_query
        return "{}\n"

    monkeypatch.setattr(dry_run, "run_dry_run", fake_run_dry_run)

    result = dry_run.main(["openalex query", "--semantic-scholar-bulk", exact_query])

    assert result == 0
    assert received_query == exact_query


def test_bulk_query_inline_and_file_options_are_mutually_exclusive(tmp_path: Path) -> None:
    from research_atlas.cli import dry_run

    query_file = tmp_path / "s2-bulk-query.txt"
    query_file.write_text("file query", encoding="utf-8")

    with pytest.raises(SystemExit) as caught:
        dry_run.main(
            [
                "openalex query",
                "--semantic-scholar-bulk",
                "inline query",
                "--semantic-scholar-bulk-file",
                str(query_file),
            ]
        )

    assert caught.value.code == 2
