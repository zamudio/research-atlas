import asyncio

import pytest

from research_atlas.application.discovery import (
    DiscoverSources,
    DiscoveryFailedError,
    DiscoveryMembership,
    serialize_report,
)
from research_atlas.application.ports.literature_source import (
    LiteratureQuery,
    LiteratureSearchRequest,
    LiteratureSourceError,
)
from research_atlas.application.source_identity import identified_source
from research_atlas.domain.execution import SearchParameter
from research_atlas.domain.studies import ExternalIdentifier, SourceProvenance, SourceRecord
from research_atlas.schemas.run_definition import SearchSpec


class FakeLiteratureSource:
    def __init__(
        self,
        provider_id: str,
        records: tuple[SourceRecord, ...] = (),
        error: Exception | None = None,
        *,
        operation_id: str | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.operation_id = operation_id or f"{provider_id}.search"
        self.records = records
        self.error = error
        self.queries: list[LiteratureQuery] = []

    async def search(self, query: LiteratureQuery) -> tuple[SourceRecord, ...]:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.records


def _record(provider: str, provider_id: str, doi: str) -> SourceRecord:
    return identified_source(
        title=f"Source {doi}",
        authors=("A. Author",),
        year=2023,
        source_type="article",
        provenance=(SourceProvenance(provider, provider_id),),
        identifiers=(ExternalIdentifier("doi", doi),),
        source_url="https://example.test/paper",
    )


def _request(
    source: FakeLiteratureSource, query: str = "example topic", limit: int = 8
) -> LiteratureSearchRequest:
    return LiteratureSearchRequest(source, LiteratureQuery(query, limit=limit))


def test_openalex_success_is_preserved_when_semantic_scholar_fails() -> None:
    openalex = FakeLiteratureSource("openalex", (_record("openalex", "W1", "10.1/one"),))
    semantic_scholar = FakeLiteratureSource(
        "semantic_scholar",
        error=LiteratureSourceError("throttled", error_type="http_status", status_code=429),
    )

    report = asyncio.run(
        DiscoverSources(
            (_request(openalex, limit=3), _request(semantic_scholar, limit=3))
        ).execute()
    )

    assert len(report.sources) == 1
    assert report.provider_outcomes[0].success is True
    assert report.provider_outcomes[0].raw_result_count == 1
    assert report.provider_outcomes[1].success is False
    assert report.provider_outcomes[1].error_type == "http_status"
    assert report.provider_outcomes[1].status_code == 429
    assert report.provider_outcomes[1].error_message == "throttled"
    assert report.memberships == (DiscoveryMembership(0, report.sources[0].source_id, 1, "W1"),)


def test_semantic_scholar_success_is_preserved_when_openalex_fails() -> None:
    openalex = FakeLiteratureSource("openalex", error=RuntimeError("unavailable"))
    semantic_scholar = FakeLiteratureSource(
        "semantic_scholar", (_record("semantic_scholar", "S1", "10.1/one"),)
    )

    report = asyncio.run(
        DiscoverSources(
            (_request(openalex, limit=3), _request(semantic_scholar, limit=3))
        ).execute()
    )

    assert len(report.sources) == 1
    assert report.provider_outcomes[0].success is False
    assert report.provider_outcomes[1].success is True
    assert report.provider_outcomes[1].raw_result_count == 1


def test_all_provider_failures_raise_with_observable_outcomes() -> None:
    providers = (
        FakeLiteratureSource("openalex", error=RuntimeError("first")),
        FakeLiteratureSource("semantic_scholar", error=ValueError("second")),
    )

    with pytest.raises(DiscoveryFailedError) as caught:
        asyncio.run(DiscoverSources(tuple(_request(provider) for provider in providers)).execute())

    assert caught.value.report.sources == ()
    assert [outcome.provider for outcome in caught.value.report.provider_outcomes] == [
        "openalex",
        "semantic_scholar",
    ]
    assert all(not outcome.success for outcome in caught.value.report.provider_outcomes)


def test_limit_is_per_provider_and_does_not_globally_truncate() -> None:
    openalex = FakeLiteratureSource(
        "openalex",
        tuple(_record("openalex", f"W{index}", f"10.1/openalex-{index}") for index in range(3)),
    )
    semantic_scholar = FakeLiteratureSource(
        "semantic_scholar",
        tuple(
            _record("semantic_scholar", f"S{index}", f"10.1/semantic-{index}") for index in range(3)
        ),
    )
    query = LiteratureQuery("example topic", limit=3)

    report = asyncio.run(
        DiscoverSources(
            (
                LiteratureSearchRequest(openalex, query),
                LiteratureSearchRequest(semantic_scholar, query),
            )
        ).execute()
    )

    assert len(report.sources) == 6
    assert openalex.queries == semantic_scholar.queries == [query]


def test_repeated_operation_id_supports_multiple_search_requests() -> None:
    first = FakeLiteratureSource(
        "openalex",
        (_record("openalex", "W1", "10.1/first"),),
        operation_id="openalex.search",
    )
    second = FakeLiteratureSource(
        "openalex",
        (_record("openalex", "W2", "10.1/second"),),
        operation_id="openalex.search",
    )

    report = asyncio.run(
        DiscoverSources(
            (_request(first, "first exact query"), _request(second, "second exact query"))
        ).execute()
    )

    assert [summary.operation for summary in report.searches] == [
        "openalex.search",
        "openalex.search",
    ]
    assert [summary.query for summary in report.searches] == [
        "first exact query",
        "second exact query",
    ]
    assert len(report.sources) == 2
    assert [membership.search_index for membership in report.memberships] == [0, 1]


def test_unique_search_memberships_preserve_positions_and_final_source_ids() -> None:
    source = FakeLiteratureSource(
        "openalex",
        (
            _record("openalex", "W1", "10.1/first"),
            _record("openalex", "W2", "10.1/second"),
        ),
    )

    report = asyncio.run(DiscoverSources((_request(source),)).execute())

    assert report.memberships == (
        DiscoveryMembership(0, report.sources[0].source_id, 1, "W1"),
        DiscoveryMembership(0, report.sources[1].source_id, 2, "W2"),
    )
    assert {membership.source_id for membership in report.memberships} == {
        source.source_id for source in report.sources
    }


def test_shared_source_keeps_each_search_membership_and_original_position() -> None:
    shared_doi = "10.1/shared"
    searches: list[LiteratureSearchRequest] = []
    for search_index, position in enumerate((2, 7, 1)):
        records = tuple(
            _record("openalex", f"W{search_index}-{index}", shared_doi)
            if index == position
            else _record(
                "openalex",
                f"W{search_index}-{index}",
                f"10.1/filler-{search_index}-{index}",
            )
            for index in range(1, position + 1)
        )
        searches.append(
            _request(
                FakeLiteratureSource("openalex", records, operation_id="openalex.search"),
                f"exact query {search_index}",
            )
        )

    report = asyncio.run(DiscoverSources(tuple(searches)).execute())
    shared_source = next(
        source
        for source in report.sources
        if ExternalIdentifier("doi", shared_doi) in source.external_identifiers
    )
    memberships = [
        membership
        for membership in report.memberships
        if membership.source_id == shared_source.source_id
    ]

    assert (
        len(
            [
                source
                for source in report.sources
                if ExternalIdentifier("doi", shared_doi) in source.external_identifiers
            ]
        )
        == 1
    )
    assert [membership.search_index for membership in memberships] == [0, 1, 2]
    assert [membership.result_position for membership in memberships] == [2, 7, 1]
    assert [membership.provider_record_id for membership in memberships] == [
        "W0-2",
        "W1-7",
        "W2-1",
    ]


def test_failed_search_contributes_no_memberships() -> None:
    failed = FakeLiteratureSource("openalex", error=RuntimeError("unavailable"))
    successful = FakeLiteratureSource(
        "semantic_scholar",
        (_record("semantic_scholar", "S1", "10.1/one"),),
    )

    report = asyncio.run(DiscoverSources((_request(failed), _request(successful))).execute())

    assert report.memberships == (DiscoveryMembership(1, report.sources[0].source_id, 1, "S1"),)


def test_same_search_duplicate_keeps_earliest_position_and_provider_record_id() -> None:
    source = FakeLiteratureSource(
        "openalex",
        (
            _record("openalex", "W-early", "10.1/shared"),
            _record("openalex", "W-late", "10.1/shared"),
        ),
    )

    report = asyncio.run(DiscoverSources((_request(source),)).execute())

    assert len(report.sources) == 1
    assert report.memberships == (
        DiscoveryMembership(0, report.sources[0].source_id, 1, "W-early"),
    )


def test_membership_record_id_stays_with_its_original_provider_result() -> None:
    openalex = FakeLiteratureSource("openalex", (_record("openalex", "W1", "10.1/shared"),))
    semantic_scholar = FakeLiteratureSource(
        "semantic_scholar",
        (_record("semantic_scholar", "S1", "10.1/shared"),),
    )

    report = asyncio.run(
        DiscoverSources((_request(openalex), _request(semantic_scholar))).execute()
    )

    assert len(report.sources) == 1
    assert [membership.provider_record_id for membership in report.memberships] == [
        "W1",
        "S1",
    ]
    assert all(
        membership.source_id == report.sources[0].source_id for membership in report.memberships
    )


def test_membership_omits_ambiguous_provider_record_id() -> None:
    ambiguous = identified_source(
        title="Ambiguous provider result",
        authors=("A. Author",),
        year=2023,
        source_type="article",
        provenance=(
            SourceProvenance("openalex", "W1"),
            SourceProvenance("openalex", "W2"),
        ),
        identifiers=(ExternalIdentifier("doi", "10.1/ambiguous"),),
    )

    report = asyncio.run(
        DiscoverSources((_request(FakeLiteratureSource("openalex", (ambiguous,))),)).execute()
    )

    assert report.memberships[0].provider_record_id is None


def test_execution_ready_search_spec_maps_losslessly_to_literature_query() -> None:
    source = FakeLiteratureSource("openalex", operation_id="openalex.search")
    parameters = (SearchParameter("filter", "type:review"),)
    spec = SearchSpec(
        search_spec_id="review-search",
        label="Review search",
        query_intent="Find reviews",
        execution_ready=True,
        provider_id="openalex",
        operation_id="openalex.search",
        exact_query='"example topic"',
        parameters=parameters,
        requested_limit=25,
    )

    request = LiteratureSearchRequest.from_search_spec(source, spec)

    assert request.query == LiteratureQuery('"example topic"', 25, parameters)


def test_overlap_across_providers_still_deduplicates() -> None:
    openalex = FakeLiteratureSource("openalex", (_record("openalex", "W1", "10.1/shared"),))
    semantic_scholar = FakeLiteratureSource(
        "semantic_scholar",
        (_record("semantic_scholar", "S1", "10.1/shared"),),
        operation_id="semantic_scholar.bulk",
    )

    report = asyncio.run(
        DiscoverSources((_request(openalex), _request(semantic_scholar))).execute()
    )

    assert len(report.sources) == 1
    assert {item.provider for item in report.sources[0].provider_provenance} == {
        "openalex",
        "semantic_scholar",
    }


def test_s2_operations_have_distinct_outcomes_and_partial_success() -> None:
    openalex = FakeLiteratureSource("openalex", (_record("openalex", "W1", "10.1/openalex"),))
    relevance = FakeLiteratureSource(
        "semantic_scholar",
        error=LiteratureSourceError("throttled", error_type="http_status", status_code=429),
        operation_id="semantic_scholar.relevance",
    )
    bulk = FakeLiteratureSource(
        "semantic_scholar",
        (_record("semantic_scholar", "S1", "10.1/bulk"),),
        operation_id="semantic_scholar.bulk",
    )

    report = asyncio.run(
        DiscoverSources(
            (
                _request(openalex, "OpenAlex text"),
                _request(relevance, "plain natural language"),
                _request(bulk, '"exact phrase" + review'),
            )
        ).execute()
    )

    assert [outcome.operation for outcome in report.provider_outcomes] == [
        "openalex.search",
        "semantic_scholar.relevance",
        "semantic_scholar.bulk",
    ]
    assert [outcome.provider for outcome in report.provider_outcomes] == [
        "openalex",
        "semantic_scholar",
        "semantic_scholar",
    ]
    assert [outcome.success for outcome in report.provider_outcomes] == [True, False, True]
    assert len(report.sources) == 2


def test_dry_run_report_serialization_includes_provider_health_and_counts() -> None:
    openalex = FakeLiteratureSource("openalex", (_record("openalex", "W1", "10.1/one"),))
    semantic_scholar = FakeLiteratureSource(
        "semantic_scholar",
        error=LiteratureSourceError("throttled", error_type="http_status", status_code=429),
    )
    report = asyncio.run(
        DiscoverSources(
            (
                LiteratureSearchRequest(
                    openalex,
                    LiteratureQuery(
                        '"example phrase" AND review',
                        parameters=(SearchParameter("filter", "type:review"),),
                    ),
                ),
                _request(semantic_scholar, '"example phrase" AND review'),
            )
        ).execute()
    )

    payload = serialize_report(report)

    assert [search["query"] for search in payload["searches"]] == [
        '"example phrase" AND review',
        '"example phrase" AND review',
    ]
    assert payload["searches"][0]["parameters"] == [{"name": "filter", "value": "type:review"}]
    assert payload["searches"][1]["parameters"] == []
    assert payload["normalized_source_count"] == 1
    assert payload["cross_provider_merge_count"] == 0
    assert payload["provider_outcomes"] == [
        {
            "provider": "openalex",
            "operation": "openalex.search",
            "success": True,
            "raw_result_count": 1,
            "error_type": None,
            "status_code": None,
            "error_message": None,
        },
        {
            "provider": "semantic_scholar",
            "operation": "semantic_scholar.search",
            "success": False,
            "raw_result_count": None,
            "error_type": "http_status",
            "status_code": 429,
            "error_message": "throttled",
        },
    ]
    assert payload["sources"][0]["external_identifiers"] == {"doi": ["10.1/one"]}
    assert "research_run" not in payload["sources"][0]
    assert "memberships" not in payload
