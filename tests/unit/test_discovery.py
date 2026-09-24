import asyncio

from research_workbench.application.discovery import DiscoverSources, serialize_sources
from research_workbench.application.ports.literature_source import LiteratureQuery
from research_workbench.application.source_identity import identified_source
from research_workbench.domain.studies import ExternalIdentifier, SourceProvenance, SourceRecord


class FakeLiteratureSource:
    def __init__(self, records: tuple[SourceRecord, ...]) -> None:
        self.records = records
        self.queries: list[LiteratureQuery] = []

    async def search(self, query: LiteratureQuery) -> tuple[SourceRecord, ...]:
        self.queries.append(query)
        return self.records


def _record(provider: str, provider_id: str) -> SourceRecord:
    return identified_source(
        title="A source",
        authors=("A. Author",),
        year=2023,
        source_type="article",
        provenance=(SourceProvenance(provider, provider_id),),
        identifiers=(ExternalIdentifier("doi", "10.1/example"),),
        source_url="https://example.test/paper",
    )


def test_discovery_service_uses_fake_providers_and_deduplicates() -> None:
    first = FakeLiteratureSource((_record("openalex", "W1"),))
    second = FakeLiteratureSource((_record("semantic_scholar", "S1"),))
    query = LiteratureQuery("feedback", limit=5)

    records = asyncio.run(DiscoverSources((first, second)).execute(query))

    assert len(records) == 1
    assert first.queries == second.queries == [query]


def test_dry_run_serialization_is_human_reviewable() -> None:
    payload = serialize_sources((_record("openalex", "W1"),))

    assert payload[0]["source_id"]
    assert payload[0]["external_identifiers"] == {"doi": ["10.1/example"]}
    assert payload[0]["provider_provenance"][0]["provider"] == "openalex"
    assert payload[0]["merged_across_providers"] is False
    assert "research_run" not in payload[0]
