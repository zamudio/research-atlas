from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid7

import pytest

from research_atlas.application.contributor_identity import (
    ContributorIdentityConflictError,
    ExactContributorKey,
    exact_contributor_match_keys,
    normalize_contributor_identifier,
    normalize_orcid,
    observed_contribution,
    resolve_exact_contributors,
)
from research_atlas.domain.contributors import (
    ContributionObservation,
    ContributionResolution,
    Contributor,
    ContributorIdentifier,
)
from research_atlas.domain.studies import ExternalIdentifier

VALID_ORCID = "0000-0002-1825-0097"
OTHER_VALID_ORCID = "0000-0001-5109-3700"


def _observation(
    provider: str,
    provider_record_id: str | None,
    *,
    display_name: str = "Ada Author",
    identifiers: tuple[ContributorIdentifier, ...] = (),
    kind: str | None = None,
) -> ContributionObservation:
    return observed_contribution(
        source_id=uuid7(),
        display_name=display_name,
        role="author",
        provider=provider,
        provider_record_id=provider_record_id,
        external_identifiers=identifiers,
        observed_contributor_kind=kind,
    )


def test_observed_contribution_creates_normalized_provider_neutral_observation() -> None:
    source_id = uuid7()
    retrieved_at = datetime(2026, 1, 2, tzinfo=UTC)

    observation = observed_contribution(
        source_id=source_id,
        display_name="  Ada Author  ",
        role="  author  ",
        provider="  OpenAlex  ",
        provider_record_id="  A123  ",
        provider_position=1,
        external_identifiers=(
            ContributorIdentifier(" ORCID ", "https://orcid.org/0000-0002-1825-0097"),
        ),
        observed_contributor_kind=" Person ",
        retrieved_at=retrieved_at,
    )

    assert observation.contribution_observation_id.version == 7
    assert observation.source_id == source_id
    assert observation.display_name == "Ada Author"
    assert observation.role == "author"
    assert observation.provider == "openalex"
    assert observation.provider_record_id == "A123"
    assert observation.provider_position == 1
    assert observation.external_identifiers == (ContributorIdentifier("orcid", VALID_ORCID),)
    assert observation.observed_contributor_kind == "person"
    assert observation.retrieved_at == retrieved_at


@pytest.mark.parametrize("provider_position", (0, -1))
def test_provider_position_must_be_positive(provider_position: int) -> None:
    with pytest.raises(ValueError, match="provider_position must be positive"):
        observed_contribution(
            source_id=uuid7(),
            display_name="Ada Author",
            role="author",
            provider="openalex",
            provider_position=provider_position,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("display_name", " ", "display_name must be non-blank"),
        ("role", " ", "role must be non-blank"),
        ("provider", " ", "provider must be non-blank"),
        ("provider_record_id", " ", "provider_record_id cannot be blank"),
        ("observed_contributor_kind", " ", "observed_contributor_kind cannot be blank"),
    ),
)
def test_blank_required_observation_fields_are_rejected(
    field: str, value: str, message: str
) -> None:
    arguments: dict[str, object] = {
        "source_id": uuid7(),
        "display_name": "Ada Author",
        "role": "author",
        "provider": "openalex",
    }
    arguments[field] = value

    with pytest.raises(ValueError, match=message):
        observed_contribution(**arguments)  # type: ignore[arg-type]


def test_contributor_and_identifier_blank_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="namespace and value must be non-blank"):
        ContributorIdentifier(" ", "value")
    with pytest.raises(ValueError, match="display_name must be non-blank"):
        Contributor(uuid7(), " ")
    with pytest.raises(ValueError, match="kind must be non-blank"):
        Contributor(uuid7(), "Ada Author", " ")


def test_contributor_identifiers_are_distinct_from_source_identifiers() -> None:
    normalized = normalize_contributor_identifier(ContributorIdentifier(" ORCID ", VALID_ORCID))

    assert normalized == ContributorIdentifier("orcid", VALID_ORCID)
    assert not isinstance(normalized, ExternalIdentifier)


@pytest.mark.parametrize(
    "raw",
    (
        "https://orcid.org/0000-0002-1825-0097",
        "http://orcid.org/0000-0002-1825-0097",
        "0000-0002-1825-0097",
        "0000000218250097",
    ),
)
def test_common_orcid_representations_normalize_to_canonical_form(raw: str) -> None:
    assert normalize_orcid(raw) == VALID_ORCID


def test_valid_orcid_is_trusted_exact_evidence() -> None:
    observation = _observation(
        "provider_without_record_id",
        None,
        identifiers=(ContributorIdentifier("orcid", VALID_ORCID),),
    )

    assert exact_contributor_match_keys(observation) == frozenset(
        {ExactContributorKey("external_identifier", "orcid", VALID_ORCID)}
    )


@pytest.mark.parametrize("invalid_orcid", ("0000-0002-1825-0098", "not-an-orcid"))
def test_invalid_orcid_is_preserved_but_not_trusted_exact_evidence(
    invalid_orcid: str,
) -> None:
    observation = _observation(
        "provider_without_record_id",
        None,
        identifiers=(ContributorIdentifier("orcid", invalid_orcid),),
    )

    assert observation.external_identifiers == (ContributorIdentifier("orcid", invalid_orcid),)
    assert exact_contributor_match_keys(observation) == frozenset()
    resolution = resolve_exact_contributors((observation,))
    assert resolution.contributors == ()
    assert resolution.unresolved_contribution_observation_ids == (
        observation.contribution_observation_id,
    )


def test_unknown_identifier_namespace_is_preserved_without_identity_authority() -> None:
    identifier = ContributorIdentifier(" Future Registry ", " shared ")
    first = _observation("provider_a", None, identifiers=(identifier,))
    second = _observation("provider_b", None, identifiers=(identifier,))

    assert first.external_identifiers == (ContributorIdentifier("future_registry", "shared"),)
    resolution = resolve_exact_contributors((first, second))
    assert resolution.contributors == ()
    assert resolution.unresolved_contribution_observation_ids == (
        first.contribution_observation_id,
        second.contribution_observation_id,
    )


def test_same_exact_orcid_across_providers_resolves_to_one_contributor() -> None:
    first = _observation(
        "openalex",
        None,
        identifiers=(ContributorIdentifier("orcid", VALID_ORCID),),
    )
    second = _observation(
        "semantic_scholar",
        None,
        identifiers=(ContributorIdentifier("ORCID", VALID_ORCID.replace("-", "")),),
    )

    resolution = resolve_exact_contributors((first, second))

    assert len(resolution.contributors) == 1
    assert {item.contributor_id for item in resolution.resolutions} == {
        resolution.contributors[0].contributor_id
    }


def test_same_provider_and_provider_record_resolves_to_one_contributor() -> None:
    first = _observation(" OpenAlex ", "A1")
    second = _observation("openalex", " A1 ")

    resolution = resolve_exact_contributors((first, second))

    assert len(resolution.contributors) == 1
    assert len(resolution.resolutions) == 2


def test_same_provider_record_value_under_different_providers_does_not_match() -> None:
    first = _observation("openalex", "A1")
    second = _observation("semantic_scholar", "A1")

    resolution = resolve_exact_contributors((first, second))

    assert len(resolution.contributors) == 2
    assert resolution.resolutions[0].contributor_id != resolution.resolutions[1].contributor_id


def test_provider_record_and_orcid_evidence_resolves_transitively() -> None:
    first = _observation("openalex", "A1", display_name="A. Author")
    bridge = _observation(
        "openalex",
        "A1",
        identifiers=(ContributorIdentifier("orcid", VALID_ORCID),),
    )
    third = _observation(
        "semantic_scholar",
        "S7",
        identifiers=(ContributorIdentifier("orcid", VALID_ORCID),),
    )

    resolution = resolve_exact_contributors((first, bridge, third))

    assert len(resolution.contributors) == 1
    assert resolution.contributors[0].display_name == "A. Author"
    assert len(resolution.resolutions) == 3


def test_identical_names_without_exact_evidence_remain_unresolved() -> None:
    first = _observation("provider_a", None, display_name="Same Name")
    second = _observation("provider_b", None, display_name="Same Name")

    resolution = resolve_exact_contributors((first, second))

    assert resolution.contributors == ()
    assert resolution.resolutions == ()
    assert resolution.unresolved_contribution_observation_ids == (
        first.contribution_observation_id,
        second.contribution_observation_id,
    )


def test_different_names_with_same_exact_evidence_resolve_to_one_contributor() -> None:
    first = _observation("openalex", "A1", display_name="A. Author")
    second = _observation("openalex", "A1", display_name="Ada Author")

    resolution = resolve_exact_contributors((first, second))

    assert len(resolution.contributors) == 1
    assert resolution.contributors[0].display_name == "A. Author"


def test_conflicting_valid_orcids_in_one_exact_component_fail_closed() -> None:
    first = _observation(
        "openalex",
        "A1",
        identifiers=(ContributorIdentifier("orcid", VALID_ORCID),),
    )
    second = _observation(
        "openalex",
        "A1",
        identifiers=(ContributorIdentifier("orcid", OTHER_VALID_ORCID),),
    )

    with pytest.raises(ContributorIdentityConflictError) as error:
        resolve_exact_contributors((first, second))

    assert error.value.namespace == "orcid"
    assert error.value.values == tuple(sorted((VALID_ORCID, OTHER_VALID_ORCID)))


def test_contributor_kind_agreement_is_retained() -> None:
    first = _observation("openalex", "A1", kind="person")
    second = _observation("openalex", "A1", kind="PERSON")
    third = _observation("openalex", "A1", kind="unknown")

    resolution = resolve_exact_contributors((first, second, third))

    assert resolution.contributors[0].kind == "person"


def test_contributor_kind_disagreement_yields_unknown_without_splitting() -> None:
    first = _observation("openalex", "A1", kind="person")
    second = _observation("openalex", "A1", kind="organization")

    resolution = resolve_exact_contributors((first, second))

    assert len(resolution.contributors) == 1
    assert resolution.contributors[0].kind == "unknown"


def test_atlas_ids_are_opaque_uuid7_values_not_derived_from_evidence() -> None:
    first = _observation("openalex", "A1", display_name="Same Name")
    second = _observation("openalex", "A1", display_name="Same Name")

    assert first.contribution_observation_id.version == 7
    assert second.contribution_observation_id.version == 7
    assert first.contribution_observation_id != second.contribution_observation_id

    first_resolution = resolve_exact_contributors((first, second))
    second_resolution = resolve_exact_contributors((first, second))
    assert first_resolution.contributors[0].contributor_id.version == 7
    assert first_resolution.contributors[0].contributor_id != (
        second_resolution.contributors[0].contributor_id
    )


def test_automatic_resolution_basis_is_exact_identity_and_preserves_input_order() -> None:
    first = _observation("openalex", "A1")
    unresolved = _observation("provider_without_record_id", None)
    third = _observation("openalex", "A1")

    resolution = resolve_exact_contributors((first, unresolved, third))

    assert [item.contribution_observation_id for item in resolution.resolutions] == [
        first.contribution_observation_id,
        third.contribution_observation_id,
    ]
    assert all(item.resolution_basis == "exact_identity" for item in resolution.resolutions)
    assert resolution.unresolved_contribution_observation_ids == (
        unresolved.contribution_observation_id,
    )


def test_unsupported_contribution_resolution_basis_is_rejected_at_runtime() -> None:
    unsupported = cast(
        Literal["exact_identity", "manual_adjudication"],
        "name_similarity",
    )

    with pytest.raises(ValueError, match="unsupported contribution resolution basis"):
        ContributionResolution(
            contribution_observation_id=uuid7(),
            contributor_id=uuid7(),
            resolution_basis=unsupported,
        )


def test_manual_adjudication_is_a_valid_domain_basis_but_not_automatically_produced() -> None:
    resolution = ContributionResolution(
        contribution_observation_id=uuid7(),
        contributor_id=uuid7(),
        resolution_basis="manual_adjudication",
    )

    assert resolution.resolution_basis == "manual_adjudication"


def test_resolution_result_uses_uuid_typed_unresolved_ids() -> None:
    observation = _observation("provider_without_record_id", None)

    unresolved_ids = resolve_exact_contributors(
        (observation,)
    ).unresolved_contribution_observation_ids

    assert unresolved_ids == (observation.contribution_observation_id,)
    assert isinstance(unresolved_ids[0], UUID)


def test_rerunning_with_existing_state_reuses_durable_contributor_id() -> None:
    first = _observation("openalex", "A1")
    second = _observation("openalex", "A1")
    initial = resolve_exact_contributors((first, second))

    rerun = resolve_exact_contributors(
        (first, second),
        existing_contributors=initial.contributors,
        existing_resolutions=initial.resolutions,
    )

    assert rerun.contributors == initial.contributors
    assert rerun.contributors[0].contributor_id == initial.contributors[0].contributor_id
    assert rerun.resolutions == initial.resolutions


def test_rerunning_does_not_mint_a_replacement_contributor() -> None:
    observation = _observation("openalex", "A1")
    initial = resolve_exact_contributors((observation,))

    rerun = resolve_exact_contributors(
        (observation,),
        existing_contributors=initial.contributors,
        existing_resolutions=initial.resolutions,
    )

    assert len(rerun.contributors) == 1
    assert rerun.contributors[0] is initial.contributors[0]
    assert rerun.resolutions[0] is initial.resolutions[0]


def test_new_orcid_linked_observation_reuses_established_contributor() -> None:
    established_observation = _observation(
        "openalex",
        "A1",
        identifiers=(ContributorIdentifier("orcid", VALID_ORCID),),
    )
    initial = resolve_exact_contributors((established_observation,))
    new_observation = _observation(
        "semantic_scholar",
        "S7",
        identifiers=(ContributorIdentifier("orcid", VALID_ORCID),),
    )

    resolution = resolve_exact_contributors(
        (established_observation, new_observation),
        existing_contributors=initial.contributors,
        existing_resolutions=initial.resolutions,
    )

    assert resolution.contributors == initial.contributors
    assert resolution.resolutions[1].contributor_id == initial.contributors[0].contributor_id
    assert resolution.resolutions[1].resolution_basis == "exact_identity"


def test_new_provider_record_linked_observation_reuses_established_contributor() -> None:
    established_observation = _observation("openalex", "A1")
    initial = resolve_exact_contributors((established_observation,))
    new_observation = _observation("OPENALEX", " A1 ")

    resolution = resolve_exact_contributors(
        (established_observation, new_observation),
        existing_contributors=initial.contributors,
        existing_resolutions=initial.resolutions,
    )

    assert len(resolution.contributors) == 1
    assert resolution.contributors[0].contributor_id == initial.contributors[0].contributor_id
    assert resolution.resolutions[1].contributor_id == initial.contributors[0].contributor_id


def test_existing_manual_basis_is_preserved_and_only_new_link_is_exact() -> None:
    established_observation = _observation(
        "openalex",
        None,
        identifiers=(ContributorIdentifier("orcid", VALID_ORCID),),
    )
    contributor = Contributor(uuid7(), "Established Name", "person")
    manual_resolution = ContributionResolution(
        established_observation.contribution_observation_id,
        contributor.contributor_id,
        "manual_adjudication",
    )
    new_observation = _observation(
        "semantic_scholar",
        None,
        identifiers=(ContributorIdentifier("orcid", VALID_ORCID),),
    )

    resolution = resolve_exact_contributors(
        (established_observation, new_observation),
        existing_contributors=(contributor,),
        existing_resolutions=(manual_resolution,),
    )

    assert resolution.resolutions[0] is manual_resolution
    assert resolution.resolutions[0].resolution_basis == "manual_adjudication"
    assert resolution.resolutions[1].resolution_basis == "exact_identity"
    assert resolution.resolutions[1].contributor_id == contributor.contributor_id


def test_existing_contributor_metadata_is_preserved_unchanged() -> None:
    established_observation = _observation("openalex", "A1", kind="organization")
    contributor = Contributor(uuid7(), "Durable Display Name", "person")
    established_resolution = ContributionResolution(
        established_observation.contribution_observation_id,
        contributor.contributor_id,
        "exact_identity",
    )
    later_observation = _observation(
        "openalex",
        "A1",
        display_name="Different Later Name",
        kind="organization",
    )

    resolution = resolve_exact_contributors(
        (established_observation, later_observation),
        existing_contributors=(contributor,),
        existing_resolutions=(established_resolution,),
    )

    assert resolution.contributors == (contributor,)
    assert resolution.contributors[0] is contributor
    assert resolution.contributors[0].display_name == "Durable Display Name"
    assert resolution.contributors[0].kind == "person"


def test_exact_evidence_connecting_established_contributors_fails_closed() -> None:
    first = _observation(
        "openalex",
        None,
        identifiers=(ContributorIdentifier("orcid", VALID_ORCID),),
    )
    second = _observation(
        "semantic_scholar",
        None,
        identifiers=(ContributorIdentifier("orcid", VALID_ORCID),),
    )
    first_contributor = Contributor(uuid7(), "First")
    second_contributor = Contributor(uuid7(), "Second")
    existing_resolutions = (
        ContributionResolution(
            first.contribution_observation_id,
            first_contributor.contributor_id,
            "manual_adjudication",
        ),
        ContributionResolution(
            second.contribution_observation_id,
            second_contributor.contributor_id,
            "exact_identity",
        ),
    )

    with pytest.raises(ContributorIdentityConflictError) as error:
        resolve_exact_contributors(
            (first, second),
            existing_contributors=(first_contributor, second_contributor),
            existing_resolutions=existing_resolutions,
        )

    expected_ids = tuple(
        sorted((first_contributor.contributor_id, second_contributor.contributor_id), key=str)
    )
    assert error.value.namespace == "contributor_id"
    assert error.value.contributor_ids == expected_ids
    assert error.value.values == tuple(str(contributor_id) for contributor_id in expected_ids)
    assert all(str(contributor_id) in str(error.value) for contributor_id in expected_ids)


def test_duplicate_observation_ids_are_rejected() -> None:
    first = _observation("openalex", "A1")
    duplicate = replace(
        _observation("semantic_scholar", "S1"),
        contribution_observation_id=first.contribution_observation_id,
    )

    with pytest.raises(ValueError, match="duplicate contribution_observation_id"):
        resolve_exact_contributors((first, duplicate))


def test_multiple_existing_resolutions_for_one_observation_are_rejected() -> None:
    observation = _observation("openalex", "A1")
    contributor = Contributor(uuid7(), "Ada Author")
    resolution = ContributionResolution(
        observation.contribution_observation_id,
        contributor.contributor_id,
        "exact_identity",
    )

    with pytest.raises(ValueError, match="multiple existing resolutions"):
        resolve_exact_contributors(
            (observation,),
            existing_contributors=(contributor,),
            existing_resolutions=(resolution, resolution),
        )


def test_existing_resolution_referencing_missing_observation_is_rejected() -> None:
    observation = _observation("openalex", "A1")
    contributor = Contributor(uuid7(), "Ada Author")
    resolution = ContributionResolution(
        uuid7(),
        contributor.contributor_id,
        "exact_identity",
    )

    with pytest.raises(ValueError, match="observation not supplied"):
        resolve_exact_contributors(
            (observation,),
            existing_contributors=(contributor,),
            existing_resolutions=(resolution,),
        )


def test_existing_resolution_referencing_missing_contributor_is_rejected() -> None:
    observation = _observation("openalex", "A1")
    resolution = ContributionResolution(
        observation.contribution_observation_id,
        uuid7(),
        "exact_identity",
    )

    with pytest.raises(ValueError, match="contributor absent"):
        resolve_exact_contributors(
            (observation,),
            existing_resolutions=(resolution,),
        )


def test_duplicate_existing_contributor_ids_are_rejected() -> None:
    observation = _observation("openalex", "A1")
    contributor = Contributor(uuid7(), "Ada Author")
    duplicate = replace(contributor, display_name="Different metadata")

    with pytest.raises(ValueError, match="duplicate contributor_id"):
        resolve_exact_contributors(
            (observation,),
            existing_contributors=(contributor, duplicate),
        )


def test_existing_name_only_manual_resolution_remains_durable() -> None:
    observation = _observation("provider_without_record_id", None)
    contributor = Contributor(uuid7(), "Established Name", "unknown")
    manual_resolution = ContributionResolution(
        observation.contribution_observation_id,
        contributor.contributor_id,
        "manual_adjudication",
    )

    resolution = resolve_exact_contributors(
        (observation,),
        existing_contributors=(contributor,),
        existing_resolutions=(manual_resolution,),
    )

    assert resolution.contributors == (contributor,)
    assert resolution.resolutions == (manual_resolution,)
    assert resolution.unresolved_contribution_observation_ids == ()
