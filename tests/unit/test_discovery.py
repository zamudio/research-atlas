import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from research_atlas.application.discovery import (
    DiscoverSources,
    DiscoveryFailedError,
    serialize_report,
)
from research_atlas.application.ports.literature_source import (
    LiteratureBatch,
    LiteratureQuery,
    LiteratureRecord,
    LiteratureSearchRequest,
    LiteratureSourceError,
)
from research_atlas.application.source_identity import identified_source
from research_atlas.domain.contributors import BibliographicCredit
from research_atlas.domain.execution import SearchParameter, SourceDiscovery
from research_atlas.domain.studies import ExternalIdentifier, SourceProvenance


class FakeSource:
    def __init__(
        self,
        provider: str,
        records: tuple[LiteratureRecord, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.provider_id = provider
        self.operation_id = f"{provider}.search"
        self.records = records
        self.error = error
        self.queries: list[LiteratureQuery] = []

    async def search(
        self, query: LiteratureQuery, *, checkpoint: str | None = None
    ) -> LiteratureBatch:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return LiteratureBatch(self.records, None, True)


def record(
    provider: str, provider_id: str, doi: str, names: tuple[str, ...] = ("A. Author",)
) -> LiteratureRecord:
    return LiteratureRecord(
        identified_source(
            title=f"Source from {provider_id}",
            authors=names,
            year=2024,
            source_type="article",
            provenance=(SourceProvenance(provider, provider_id, datetime(2026, 1, 1, tzinfo=UTC)),),
            identifiers=(ExternalIdentifier("doi", doi),),
        ),
        tuple(BibliographicCredit(name) for name in names),
    )


def request(source: FakeSource, query: LiteratureQuery | None = None) -> LiteratureSearchRequest:
    return LiteratureSearchRequest(source, query or LiteratureQuery("test"))


@pytest.mark.parametrize("failed_index", [0, 1])
def test_provider_failure_preserves_other_results_and_provenance(failed_index: int) -> None:
    sources = [
        FakeSource("first", (record("first", "one", "10.1/first"),)),
        FakeSource("second", (record("second", "two", "10.1/second"),)),
    ]
    sources[failed_index].error = LiteratureSourceError(
        "unavailable", error_type="http_status", status_code=429
    )
    report = asyncio.run(DiscoverSources(tuple(request(source) for source in sources)).execute())
    assert len(report.sources) == len(report.metadata_observations) == len(report.memberships) == 1
    assert report.memberships[0].search_index == 1 - failed_index
    assert report.provider_outcomes[failed_index].status_code == 429
    assert report.provider_outcomes[1 - failed_index].status == "succeeded"
    assert report.provider_outcomes[failed_index].raw_result_count == 0


def test_all_failures_are_observable_but_successful_empty_search_is_valid() -> None:
    first = FakeSource("first", error=RuntimeError("unavailable"))
    second = FakeSource("second", error=ValueError("malformed"))
    with pytest.raises(DiscoveryFailedError) as caught:
        asyncio.run(DiscoverSources((request(first), request(second))).execute())
    assert [item.error_type for item in caught.value.report.provider_outcomes] == [
        "RuntimeError",
        "ValueError",
    ]
    assert caught.value.report.sources == caught.value.report.metadata_observations == ()
    second.error = None
    report = asyncio.run(DiscoverSources((request(first), request(second))).execute())
    assert report.sources == ()
    assert report.provider_outcomes[1].status == "succeeded"
    assert report.provider_outcomes[1].raw_result_count == 0


def test_exact_queries_parameters_and_per_search_limits_are_preserved() -> None:
    first = FakeSource("same", (record("same", "one", "10.1/one"),))
    second = FakeSource("same", (record("same", "two", "10.1/two"),))
    queries = (
        LiteratureQuery(
            " exact query \r\n",
            1,
            (SearchParameter("filter", "first"), SearchParameter("filter", "second")),
        ),
        LiteratureQuery("different query", 1),
    )
    report = asyncio.run(
        DiscoverSources((request(first, queries[0]), request(second, queries[1]))).execute()
    )
    assert first.queries == [queries[0]]
    assert second.queries == [queries[1]]
    assert [item.query for item in report.searches] == [item.query for item in queries]
    assert report.searches[0].parameters == queries[0].parameters
    assert len(report.sources) == 2
    assert [item.search_index for item in report.memberships] == [0, 1]


def test_exact_merge_preserves_whole_provider_observations_and_search_memberships() -> None:
    first = record("openalex", "W1", "10.1/shared", ("A. Smith", "B. Jones"))
    second = record("crossref", "10.1/shared", "10.1/shared", ("Alice Smith", "Bob Jones"))
    filler = record("crossref", "10.1/other", "10.1/other")
    report = asyncio.run(
        DiscoverSources(
            (
                request(FakeSource("openalex", (first,))),
                request(FakeSource("crossref", (filler, second))),
            )
        ).execute()
    )
    merged = report.sources[0]
    assert merged.source_id == first.source.source_id
    assert merged.authors == first.source.authors
    observations = [
        item for item in report.metadata_observations if item.resolved_source_id == merged.source_id
    ]
    assert observations == [
        replace(first, resolved_source_id=merged.source_id),
        replace(second, resolved_source_id=merged.source_id),
    ]
    assert [item.source.authors for item in observations] == [
        first.source.authors,
        second.source.authors,
    ]
    assert [item.source.provider_provenance[0].provider_record_id for item in observations] == [
        "W1",
        "10.1/shared",
    ]
    memberships = [item for item in report.memberships if item.source_id == merged.source_id]
    assert [
        (item.search_index, item.result_position, item.provider_record_id) for item in memberships
    ] == [(0, 1, "W1"), (1, 2, "10.1/shared")]
    payload = json.loads(json.dumps(serialize_report(report)))
    assert payload["cross_provider_merge_count"] == 1
    assert payload["normalized_source_count"] == 2
    assert payload["metadata_observations"][2]["credits"][0]["display_name"] == "Alice Smith"
    assert payload["metadata_observations"][2]["provider_provenance"][0]["provider"] == "crossref"


def test_same_provider_duplicate_keeps_original_publication_grouping_and_credit_roles() -> None:
    first = record("openalex", "W1", "10.1/shared", ("Same Name", "Same Name"))
    second = record("openalex", "W2", "10.1/shared", ("Other Name",))
    second = replace(
        second, credits=(BibliographicCredit("Other Name", role="editor", kind="organization"),)
    )
    report = asyncio.run(
        DiscoverSources((request(FakeSource("openalex", (first, second))),)).execute()
    )
    assert len(report.sources) == len(report.memberships) == 1
    assert report.memberships[0].provider_record_id == "W1"
    assert report.memberships[0].result_position == 1
    assert report.provider_outcomes[0].raw_result_count == 2
    assert len(report.metadata_observations) == 2
    assert report.metadata_observations[0].credits == first.credits
    assert report.metadata_observations[1].credits == second.credits
    assert report.metadata_observations[1].source.provider_provenance[0].provider_record_id == "W2"


def test_discovery_and_metadata_provider_identity_can_differ() -> None:
    metadata = record("metadata-provider", "metadata-id", "10.1/one")
    report = asyncio.run(
        DiscoverSources((request(FakeSource("discovery-provider", (metadata,))),)).execute()
    )
    assert report.searches[0].provider == "discovery-provider"
    assert report.memberships[0].provider_record_id is None
    assert (
        report.metadata_observations[0].source.provider_provenance[0].provider
        == "metadata-provider"
    )

    membership = report.memberships[0]
    assert membership.source_id is not None
    discovery = SourceDiscovery(
        discovery_id="discovery-1",
        search_execution_id="search-1",
        run_id="run-1",
        source_id=membership.source_id,
        observation_id=membership.observation_id,
        discovered_at=datetime(2026, 1, 2, tzinfo=UTC),
        result_position=membership.result_position,
        provider_record_id=membership.provider_record_id,
    )
    assert discovery.observation_id == metadata.observation_id
    assert discovery.source_id == report.metadata_observations[0].resolved_source_id
    assert discovery.provider_record_id is None  # Metadata ID is not a discovery-provider ID.
    assert metadata.source.provider_provenance[0].provider_record_id == "metadata-id"


def test_display_metadata_selects_exactly_one_attributable_observation() -> None:
    first = record("openalex", "W1", "10.1/shared", ())
    second = record("crossref", "10.1/shared", "10.1/shared", ("Different author",))
    first = replace(first, source=replace(first.source, title="Short", year=None, source_url=None))
    second = replace(
        second,
        source=replace(
            second.source,
            title="Longer alternate title",
            year=1999,
            source_type="journal-article",
            source_url="https://example.test/alternative",
        ),
    )
    report = asyncio.run(
        DiscoverSources(
            (request(FakeSource("openalex", (first,))), request(FakeSource("crossref", (second,))))
        ).execute()
    )
    display = report.sources[0]
    assert (
        display.title,
        display.authors,
        display.year,
        display.source_type,
        display.source_url,
    ) == (
        first.source.title,
        first.source.authors,
        first.source.year,
        first.source.source_type,
        first.source.source_url,
    )
    assert display.display_observation_id == first.observation_id
    assert [item.source for item in report.metadata_observations] == [first.source, second.source]


def test_conflict_has_observations_but_no_resolved_membership() -> None:
    first = record("openalex", "W1", "10.1/shared")
    second = record("openalex", "W1", "10.1/conflict")
    valid = record("openalex", "W2", "10.1/valid")
    report = asyncio.run(
        DiscoverSources((request(FakeSource("openalex", (first, second, valid))),)).execute()
    )
    assert len(report.sources) == 1
    assert [item.source_id for item in report.memberships] == [None, None, valid.source.source_id]
    assert [item.resolved_source_id for item in report.metadata_observations] == [
        None,
        None,
        valid.source.source_id,
    ]
    payload = json.loads(json.dumps(serialize_report(report)))
    assert payload["identity_conflicts"][0]["observation_ids"] == [
        str(first.observation_id),
        str(second.observation_id),
    ]
    assert payload["provider_outcomes"][0]["status"] == "succeeded"


def test_unexpected_exception_payload_does_not_leak_into_report() -> None:
    with pytest.raises(DiscoveryFailedError) as error:
        asyncio.run(
            DiscoverSources(
                (request(FakeSource("one", error=ValueError("SECRET and enormous payload"))),)
            ).execute()
        )
    assert "SECRET" not in json.dumps(serialize_report(error.value.report))
