"""Acceptance cases C/D: real adapters, mocked wire data, bounded calls and replay."""

import asyncio
import json

import httpx
import pytest

from research_atlas.application.discovery import (
    DiscoverSources,
    DiscoveryFailedError,
    serialize_report,
)
from research_atlas.application.ports.literature_source import (
    LiteratureQuery,
    LiteratureSearchRequest,
    LiteratureSourceError,
)
from research_atlas.domain.execution import SearchParameter
from research_atlas.infrastructure.providers.crossref import CrossrefWorksSearch
from research_atlas.infrastructure.providers.openalex import (
    OpenAlexLiteratureSource,
    OpenAlexSemanticRequestCoordinator,
    OpenAlexSemanticSearch,
)


def page(provider: str, number: int, count: int = 2) -> dict[str, object]:
    if provider == "openalex":
        return {
            "results": [{"id": f"W{number}-{i}"} for i in range(count)],
            "meta": {"next_cursor": f"page-{number + 1}" if count else None},
        }
    return {
        "message": {
            "items": [{"DOI": f"10.1/{number}-{i}"} for i in range(count)],
            "next-cursor": f"page-{number + 1}",
        }
    }


@pytest.mark.parametrize("provider", ["openalex", "crossref"])
@pytest.mark.parametrize("failure_type", ["http_status", "malformed_response"])
def test_later_failure_keeps_two_batches_and_retry_starts_at_third(
    provider: str, failure_type: str
) -> None:
    requests: list[httpx.Request] = []
    fail = True

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        cursor = request.url.params["cursor"]
        number = 1 if cursor == "*" else int(cursor.removeprefix("page-"))
        if number == 3 and fail:
            return (
                httpx.Response(400, text="SECRET large payload")
                if failure_type == "http_status"
                else httpx.Response(200, json={"SECRET": "bad envelope"})
            )
        return httpx.Response(200, json=page(provider, number, 0 if number == 3 else 2))

    async def run() -> None:
        nonlocal fail
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = (
                OpenAlexLiteratureSource(client=client)
                if provider == "openalex"
                else CrossrefWorksSearch(client=client)
            )
            query = LiteratureQuery(
                " exact original query ",
                2,
                (SearchParameter("filter", "a"), SearchParameter("filter", "b")),
            )
            report = await DiscoverSources(
                (LiteratureSearchRequest(source, query, max_batches=5),)
            ).execute()
            outcome = report.provider_outcomes[0]
            assert outcome.status == "partial"
            assert outcome.raw_result_count == 4 and outcome.completed_batches == 2
            assert outcome.error_type == failure_type
            assert outcome.status_code == (400 if failure_type == "http_status" else None)
            assert len(report.sources) == len(report.metadata_observations) == 4
            assert [item.result_position for item in report.memberships] == [1, 2, 3, 4]
            assert outcome.checkpoint is not None
            assert "SECRET" not in json.dumps(serialize_report(report))
            fail = False
            resumed = await DiscoverSources(
                (LiteratureSearchRequest(source, query, checkpoint=outcome.checkpoint),)
            ).execute()
            assert resumed.provider_outcomes[0].status == "succeeded"
            assert resumed.provider_outcomes[0].checkpoint is None
        assert [r.url.params["cursor"] for r in requests] == ["*", "page-2", "page-3", "page-3"]
        expected = [(k, v) for k, v in requests[0].url.params.multi_items() if k != "cursor"]
        for request in requests[1:]:
            assert [
                (k, v) for k, v in request.url.params.multi_items() if k != "cursor"
            ] == expected
        assert requests[0].url.params.get_list("filter") == (
            ["a", "b"] if provider == "openalex" else ["a,b"]
        )

    asyncio.run(run())


@pytest.mark.parametrize("provider", ["openalex", "crossref"])
def test_one_call_is_one_bounded_batch_with_replay_and_request_bound_checkpoint(
    provider: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        cursor = request.url.params["cursor"]
        return httpx.Response(200, json=page(provider, 1 if cursor == "*" else 2))

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = (
                OpenAlexLiteratureSource(client=client)
                if provider == "openalex"
                else CrossrefWorksSearch(client=client)
            )
            query = LiteratureQuery("original", 2)
            first = await source.search(query)
            assert len(requests) == 1 and len(first.records) == 2
            assert not first.exhausted and first.start_position == 0
            second = await source.search(query, checkpoint=first.next_checkpoint)
            replay = await source.search(query, checkpoint=first.next_checkpoint)
            assert second.start_position == replay.start_position == 2
            assert [r.source.external_identifiers for r in second.records] == [
                r.source.external_identifiers for r in replay.records
            ]
            assert second.next_checkpoint == replay.next_checkpoint
            with pytest.raises(LiteratureSourceError, match="checkpoint"):
                await source.search(LiteratureQuery("changed", 2), checkpoint=first.next_checkpoint)
            assert len(requests) == 3
            report = await DiscoverSources((LiteratureSearchRequest(source, query),)).execute()
            assert report.provider_outcomes[0].status == "partial"
            assert report.provider_outcomes[0].error_type is None
            assert report.provider_outcomes[0].checkpoint is not None
            resumed = await DiscoverSources(
                (LiteratureSearchRequest(source, query, checkpoint=first.next_checkpoint),)
            ).execute()
            assert [m.result_position for m in resumed.memberships] == [3, 4]

    asyncio.run(run())


OPENALEX_BAD: list[object] = [
    {},
    [],
    None,
    {"results": {}},
    {"results": []},
    {"results": [], "meta": {}},
    {"results": [], "meta": []},
    {"results": [], "meta": {"next_cursor": 4}},
    {"results": [{"id": "W1"}], "meta": {"next_cursor": ""}},
    {"results": [{"id": "W1"}], "meta": {"next_cursor": "   "}},
    {"results": [{"id": "W1"}, None], "meta": {"next_cursor": None}},
    {"results": [{"id": "W1", "authorships": [None]}], "meta": {"next_cursor": None}},
    {"results": [{"id": "W1", "publication_year": True}], "meta": {"next_cursor": None}},
]
CROSSREF_BAD: list[object] = [
    {},
    [],
    None,
    {"message": []},
    {"message": {}},
    {"message": {"items": {}}},
    {"message": {"items": [{"DOI": "10.1/one"}, None]}},
    {"message": {"items": [{"DOI": "10.1/one"}, {"DOI": "10.1/two"}]}},
    {"message": {"items": [{"DOI": "10.1/one"}, {"DOI": "10.1/two"}], "next-cursor": "   "}},
    {"message": {"items": [{"DOI": "10.1/one", "author": [None]}]}},
    {"message": {"items": [{"DOI": "10.1/one", "title": [42]}]}},
]


@pytest.mark.parametrize(
    ("provider", "payload"),
    [("openalex", p) for p in OPENALEX_BAD] + [("crossref", p) for p in CROSSREF_BAD],
)
def test_malformed_http_200_never_becomes_empty_success(provider: str, payload: object) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=payload))
        ) as client:
            source = (
                OpenAlexLiteratureSource(client=client)
                if provider == "openalex"
                else CrossrefWorksSearch(client=client)
            )
            with pytest.raises(DiscoveryFailedError) as error:
                await DiscoverSources(
                    (LiteratureSearchRequest(source, LiteratureQuery("q", 2)),)
                ).execute()
            outcome = error.value.report.provider_outcomes[0]
            assert outcome.status == "failed"
            assert outcome.error_type == "malformed_response"
            assert outcome.checkpoint is None and outcome.raw_result_count == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "payload", [{}, [], {"results": [None]}, {"results": [{"id": "W1"}, {"id": "W2"}]}]
)
def test_semantic_response_validation_and_single_request_bound(payload: object) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=payload))
        ) as client:
            source = OpenAlexSemanticSearch(
                client=client, request_coordinator=OpenAlexSemanticRequestCoordinator(0.001)
            )
            with pytest.raises(LiteratureSourceError) as error:
                await source.search(LiteratureQuery("question", 1))
            assert error.value.error_type == "malformed_response"
            with pytest.raises(LiteratureSourceError, match="continuation"):
                await source.search(LiteratureQuery("question", 1), checkpoint="not-allowed")

    asyncio.run(run())


def test_invalid_json_response_has_safe_error_metadata() -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _r: httpx.Response(200, text="SECRET invalid JSON")
            )
        ) as client:
            with pytest.raises(LiteratureSourceError) as error:
                await OpenAlexLiteratureSource(client=client).search(LiteratureQuery("q"))
            assert error.value.error_type == "malformed_response"
            assert "SECRET" not in str(error.value)

    asyncio.run(run())


def test_openalex_preserves_unknown_ids_and_conflicting_reported_dois() -> None:
    payload = {
        "results": [
            {
                "id": "W1",
                "doi": "https://doi.org/10.1/ONE",
                "ids": {"doi": "10.1/two", "unknown_registry": "raw value"},
            }
        ],
        "meta": {"next_cursor": None},
    }

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=payload))
        ) as client:
            report = await DiscoverSources(
                (
                    LiteratureSearchRequest(
                        OpenAlexLiteratureSource(client=client), LiteratureQuery("q")
                    ),
                )
            ).execute()
            assert report.sources == () and len(report.identity_conflicts) == 1
            ids = {
                (item.namespace, item.value)
                for item in report.metadata_observations[0].source.external_identifiers
            }
            assert {
                ("doi", "https://doi.org/10.1/ONE"),
                ("doi", "10.1/two"),
                ("unknown_registry", "raw value"),
            } <= ids
            assert report.metadata_observations[0].resolved_source_id is None

    asyncio.run(run())


def test_crossref_uses_successive_returned_cursors_and_preserves_parameters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        number = len(requests)
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [{"DOI": f"10.1/{number}"}] if number < 3 else [],
                    "next-cursor": f"cursor-{number}"
                    if number < 3
                    else request.url.params["cursor"],
                }
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = CrossrefWorksSearch(mailto="one@example.test", client=client)
            query = LiteratureQuery(
                "q", 1, (SearchParameter("filter", "a"), SearchParameter("filter", "b"))
            )
            first = await source.search(query)
            second = await source.search(query, checkpoint=first.next_checkpoint)
            last = await source.search(query, checkpoint=second.next_checkpoint)
            assert [r.url.params["cursor"] for r in requests] == ["*", "cursor-1", "cursor-2"]
            assert last.exhausted and last.next_checkpoint is None
            original = [(k, v) for k, v in requests[0].url.params.multi_items() if k != "cursor"]
            assert all(
                [(k, v) for k, v in r.url.params.multi_items() if k != "cursor"] == original
                for r in requests[1:]
            )
            with pytest.raises(LiteratureSourceError, match="checkpoint"):
                await CrossrefWorksSearch(mailto="changed@example.test", client=client).search(
                    query, checkpoint=first.next_checkpoint
                )
            assert len(requests) == 3

    asyncio.run(run())


@pytest.mark.parametrize("repeat_on", [1, 2])
def test_crossref_rejects_nonterminal_repeated_native_cursor(repeat_on: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [{"DOI": f"10.1/{calls}"}],
                    "next-cursor": request.url.params["cursor"]
                    if calls == repeat_on
                    else f"cursor-{calls}",
                }
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = CrossrefWorksSearch(client=client)
            query = LiteratureQuery("q", 1)
            checkpoint = None
            if repeat_on == 2:
                checkpoint = (await source.search(query)).next_checkpoint
            with pytest.raises(LiteratureSourceError) as error:
                await source.search(query, checkpoint=checkpoint)
            assert error.value.error_type == "malformed_response"
            assert calls == repeat_on

    asyncio.run(run())
