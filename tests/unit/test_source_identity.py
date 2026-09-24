from datetime import UTC, datetime

import pytest

from research_atlas.application.source_identity import (
    identified_source,
    merge_sources,
    normalize_doi,
)
from research_atlas.domain.studies import ExternalIdentifier, SourceProvenance


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
    provider_id: str,
    *,
    title: str = "Same paper",
    identifiers: tuple[ExternalIdentifier, ...] = (),
):
    return identified_source(
        title=title,
        authors=("Ada Author",),
        year=2024,
        source_type="article",
        provenance=(SourceProvenance(provider, provider_id, datetime(2025, 1, 1, tzinfo=UTC)),),
        identifiers=identifiers,
        source_url=None,
    )


def test_stable_source_id_across_providers_when_doi_matches() -> None:
    openalex = _source(
        "openalex",
        "W1",
        identifiers=(
            ExternalIdentifier("openalex", "W1"),
            ExternalIdentifier("doi", "https://doi.org/10.1/SHARED"),
        ),
    )
    semantic = _source(
        "semantic_scholar",
        "S1",
        identifiers=(
            ExternalIdentifier("semanticscholar", "S1"),
            ExternalIdentifier("DOI", "10.1/shared"),
        ),
    )

    assert openalex.source_id == semantic.source_id


def test_same_provider_record_without_doi_has_stable_fallback_id() -> None:
    first = _source("openalex", "W123")
    second = _source("openalex", "W123", title="Updated metadata title")

    assert first.source_id == second.source_id


def test_merge_is_deterministic_and_combines_identifiers_and_provenance() -> None:
    openalex = _source(
        "openalex",
        "W1",
        identifiers=(ExternalIdentifier("doi", "10.1/shared"), ExternalIdentifier("pmid", "3")),
    )
    semantic = _source(
        "semantic_scholar",
        "S1",
        identifiers=(
            ExternalIdentifier("DOI", "10.1/SHARED"),
            ExternalIdentifier("arxiv", "2401.1"),
        ),
    )

    forward = merge_sources((openalex, semantic))
    reverse = merge_sources((semantic, openalex))

    assert forward == reverse
    assert len(forward) == 1
    assert {(item.namespace, item.value) for item in forward[0].external_identifiers} == {
        ("arxiv", "2401.1"),
        ("doi", "10.1/shared"),
        ("pmid", "3"),
    }
    assert {item.provider for item in forward[0].provider_provenance} == {
        "openalex",
        "semantic_scholar",
    }


def test_similar_titles_without_shared_identifier_do_not_merge() -> None:
    first = _source("openalex", "W1", title="Learning with feedback")
    second = _source("semantic_scholar", "S2", title="Learning With Feedback")

    assert len(merge_sources((first, second))) == 2
