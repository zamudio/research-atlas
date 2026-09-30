from datetime import UTC, datetime

import pytest

from research_atlas.application.source_identity import (
    ExactSourceKey,
    exact_source_match_keys,
    identified_source,
    normalize_doi,
    resolve_exact_sources,
)
from research_atlas.domain.studies import ExternalIdentifier, SourceProvenance, SourceRecord


def resolved(records: tuple[SourceRecord, ...]) -> tuple[SourceRecord, ...]:
    result = resolve_exact_sources(records)
    assert not result.conflicts
    return result.sources


@pytest.mark.parametrize(
    "raw",
    (
        "10.1000/ABC.Def",
        " doi: 10.1000/ABC.Def ",
        "https://doi.org/10.1000/ABC.Def",
        "HTTP://DX.DOI.ORG/10.1000/ABC.Def",
        " 10.1000 / ABC.Def ",
    ),
)
def test_normalize_doi_variants(raw: str) -> None:
    assert normalize_doi(raw) == "10.1000/abc.def"


def _source(
    provider: str,
    provider_id: str | None,
    *,
    title: str = "Same paper",
    authors: tuple[str, ...] = ("Ada Author",),
    year: int | None = 2024,
    identifiers: tuple[ExternalIdentifier, ...] = (),
    additional_provenance: tuple[SourceProvenance, ...] = (),
) -> SourceRecord:
    return identified_source(
        title=title,
        authors=authors,
        year=year,
        source_type="article",
        provenance=(
            SourceProvenance(provider, provider_id, datetime(2025, 1, 1, tzinfo=UTC)),
            *additional_provenance,
        ),
        identifiers=identifiers,
        source_url=None,
    )


def test_identified_source_uses_uuid7() -> None:
    source = _source("openalex", "W1")

    assert source.source_id.version == 7


def test_identical_identity_evidence_gets_distinct_candidate_source_ids() -> None:
    identifiers = (ExternalIdentifier("doi", "10.1/shared"),)
    first = _source("openalex", "W1", identifiers=identifiers)
    second = _source("openalex", "W1", identifiers=identifiers)

    assert first.source_id != second.source_id


def test_exact_source_keys_are_typed_and_cannot_collide() -> None:
    source = _source(
        "doi",
        "10.1/shared",
        identifiers=(ExternalIdentifier("doi", "10.1/shared"),),
    )

    assert exact_source_match_keys(source) == frozenset(
        {
            ExactSourceKey("external_identifier", "doi", "10.1/shared"),
            ExactSourceKey("provider_record", "doi", "10.1/shared"),
        }
    )


def test_same_normalized_doi_merges_different_uuid7_candidates() -> None:
    first = _source(
        "openalex",
        "W1",
        identifiers=(ExternalIdentifier("doi", "https://doi.org/10.1/SHARED"),),
    )
    second = _source(
        "openalex",
        "W2",
        identifiers=(ExternalIdentifier("DOI", "10.1/shared"),),
    )

    merged = resolved((first, second))

    assert len(merged) == 1
    assert merged[0].source_id == first.source_id


def test_same_provider_record_merges_when_one_candidate_lacks_doi() -> None:
    identified = _source(
        "openalex",
        "W123",
        identifiers=(ExternalIdentifier("doi", "10.1/shared"),),
    )
    provider_only = _source("openalex", "W123", title="Updated metadata title")

    merged = resolved((identified, provider_only))

    assert len(merged) == 1
    assert ExternalIdentifier("doi", "10.1/shared") in merged[0].external_identifiers


def test_cross_provider_candidates_with_same_doi_merge() -> None:
    openalex = _source(
        "openalex",
        "W1",
        identifiers=(ExternalIdentifier("doi", "10.1/shared"),),
    )
    semantic = _source(
        "crossref",
        "10.1/shared",
        identifiers=(ExternalIdentifier("DOI", "10.1/SHARED"),),
    )

    merged = resolved((openalex, semantic))

    assert len(merged) == 1
    assert {item.provider for item in merged[0].provider_provenance} == {
        "openalex",
        "crossref",
    }


def test_transitive_exact_identity_connectivity_merges_one_component() -> None:
    first = _source(
        "openalex",
        "W1",
        identifiers=(ExternalIdentifier("doi", "10.1/shared"),),
    )
    bridge = _source(
        "openalex",
        "W1",
        additional_provenance=(SourceProvenance("crossref", "10.1/shared"),),
    )
    third = _source("crossref", "10.1/shared")

    resolution = resolve_exact_sources((first, bridge, third))

    assert len(resolution.sources) == 1
    assert resolution.source_ids_by_input == (first.source_id,) * 3


def test_merge_preserves_first_seen_candidate_source_id() -> None:
    first = _source(
        "openalex",
        "W1",
        identifiers=(ExternalIdentifier("doi", "10.1/shared"),),
    )
    second = _source(
        "crossref",
        "10.1/shared",
        identifiers=(ExternalIdentifier("doi", "10.1/shared"),),
    )

    assert resolved((first, second))[0].source_id == first.source_id
    assert resolved((second, first))[0].source_id == second.source_id


@pytest.mark.parametrize(
    ("namespace", "first_value", "second_value"),
    (
        ("doi", "10.1/one", "10.1/two"),
        ("pmid", "1", "2"),
        ("pmcid", "PMC1", "PMC2"),
        ("arxiv", "2401.00001", "2401.00002"),
    ),
)
def test_conflicting_strong_identifiers_fail_explicitly(
    namespace: str,
    first_value: str,
    second_value: str,
) -> None:
    first = _source(
        "openalex",
        "W1",
        identifiers=(ExternalIdentifier(namespace, first_value),),
    )
    second = _source(
        "openalex",
        "W1",
        identifiers=(ExternalIdentifier(namespace, second_value),),
    )

    resolution = resolve_exact_sources((first, second))
    assert resolution.sources == ()
    assert resolution.source_ids_by_input == (None, None)
    assert resolution.conflicts[0].input_indices == (0, 1)
    assert resolution.conflicts[0].conflicting_identifiers == tuple(
        ExternalIdentifier(namespace, value) for value in sorted((first_value, second_value))
    )


def test_unknown_identifier_namespace_is_not_automatic_match_authority() -> None:
    first = _source(
        "provider_a",
        None,
        identifiers=(ExternalIdentifier("future_registry", "shared"),),
    )
    second = _source(
        "provider_b",
        None,
        identifiers=(ExternalIdentifier("future_registry", "shared"),),
    )

    assert len(resolved((first, second))) == 2


@pytest.mark.parametrize(
    "namespace",
    (
        "acl",
        "arxiv",
        "dblp",
        "doi",
        "mag",
        "openalex",
        "pmcid",
        "pmid",
    ),
)
def test_unique_identifier_namespaces_emitted_by_providers_are_exact_keys(
    namespace: str,
) -> None:
    source = _source(
        "provider_without_record_id",
        None,
        identifiers=(ExternalIdentifier(namespace, "record-1"),),
    )

    expected_value = "RECORD-1" if namespace == "pmcid" else "record-1"
    assert ExactSourceKey(
        "external_identifier", namespace, expected_value
    ) in exact_source_match_keys(source)


def test_titles_authors_and_years_without_exact_keys_do_not_merge() -> None:
    first = _source(
        "provider_a",
        None,
        title="Example research topic",
        authors=("Same Author",),
        year=2024,
    )
    second = _source(
        "provider_b",
        None,
        title="Example Research Topic",
        authors=("Same Author",),
        year=2024,
    )

    assert len(resolved((first, second))) == 2


def test_merging_never_combines_different_provider_bylines() -> None:
    first = _source(
        "openalex",
        "W1",
        authors=("A. Smith", "B. Jones"),
        identifiers=(ExternalIdentifier("doi", "10.1/shared"),),
    )
    second = _source(
        "crossref",
        "10.1/shared",
        authors=("Alice Smith", "Bob Jones"),
        identifiers=(ExternalIdentifier("doi", "10.1/shared"),),
    )

    assert resolved((first, second))[0].authors == first.authors
    assert resolved((second, first))[0].authors == second.authors


def test_empty_display_byline_is_not_filled_from_another_observation() -> None:
    first = _source(
        "openalex", "W1", authors=(), identifiers=(ExternalIdentifier("doi", "10.1/shared"),)
    )
    second = _source(
        "crossref",
        "10.1/shared",
        authors=("Same Name", "Same Name"),
        identifiers=(ExternalIdentifier("doi", "10.1/shared"),),
    )

    assert resolved((first, second))[0].authors == ()


def test_conflicted_transitive_component_does_not_discard_unrelated_or_keyless_sources() -> None:
    first = _source(
        "one",
        "1",
        identifiers=(ExternalIdentifier("doi", "10.1/shared"), ExternalIdentifier("pmid", "1")),
    )
    bridge = _source("two", "2", identifiers=(ExternalIdentifier("doi", "10.1/shared"),))
    last = _source("two", "2", identifiers=(ExternalIdentifier("pmid", "2"),))
    valid = _source("three", "3", identifiers=(ExternalIdentifier("doi", "10.1/valid"),))
    keyless = _source("four", None)
    inputs = (first, bridge, valid, last, keyless)
    result = resolve_exact_sources(inputs)
    assert result == resolve_exact_sources(inputs)
    assert [item.source_id for item in result.sources] == [valid.source_id, keyless.source_id]
    assert result.source_ids_by_input == (None, None, valid.source_id, None, keyless.source_id)
    assert result.conflicts[0].input_indices == (0, 1, 3)


def test_unknown_reported_identifiers_are_not_promoted_to_resolved_source() -> None:
    candidate = _source(
        "one", "1", identifiers=(ExternalIdentifier("future_registry", "raw VALUE"),)
    )
    assert resolved((candidate,))[0].external_identifiers == ()
    assert candidate.external_identifiers == (ExternalIdentifier("future_registry", "raw VALUE"),)


@pytest.mark.parametrize(
    ("namespace", "raw", "expected"),
    [
        ("pubmed", "https://pubmed.ncbi.nlm.nih.gov/123/", "123"),
        ("pmc", "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC42/", "PMC42"),
        ("arxiv", "https://arxiv.org/pdf/2401.01234v2.pdf", "2401.01234"),
        ("openalex", "https://openalex.org/W42", "W42"),
    ],
)
def test_identifier_normalization_preserves_reported_value(
    namespace: str, raw: str, expected: str
) -> None:
    source = _source("one", None, identifiers=(ExternalIdentifier(namespace, raw),))
    assert next(iter(exact_source_match_keys(source))).value == expected
    assert source.external_identifiers[0].value == raw
