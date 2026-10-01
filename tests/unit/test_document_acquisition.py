import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid7

import pytest

from research_atlas.application.document_acquisition import acquire_source_document
from research_atlas.application.ports.document_acquisition import DocumentAcquisitionResult
from research_atlas.application.source_identity import ExactSourceKey, openalex_acquisition_identity
from research_atlas.domain.content import SourceDocument

NOW = datetime(2026, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize("status", ["usable", "unavailable", "failed", "incomplete"])
def test_one_acquisition_closes_read_before_provider_and_commits_exact_result(
    status: Literal["usable", "unavailable", "failed", "incomplete"],
) -> None:
    events: list[str] = []
    expected_source_id, durable_id = uuid7(), uuid7()
    content = b"<tei>Exact XML</tei>" if status == "usable" else None
    result = DocumentAcquisitionResult(
        status,
        "grobid_xml",
        "safe outcome",
        NOW,
        "https://content.openalex.org/works/W1.grobid-xml",
        "application/xml",
        content,
    )

    class Progress:
        async def load_acquisition_identity(
            self, run_id: str, source_id: UUID, provider_id: str
        ) -> str:
            assert (run_id, source_id, provider_id) == ("run", expected_source_id, "openalex")
            events.append("read-closed")
            return "W1"

        async def commit_document_acquisition(
            self,
            run_id: str,
            document: SourceDocument,
            content: bytes | None,
            *,
            expected_identity: str,
        ) -> UUID:
            assert events == ["read-closed", "provider-returned"]
            assert expected_identity == "W1"
            assert document.source_id == expected_source_id and run_id == "run"
            assert document.status == status and content == result.content
            assert document.content_sha256 == (
                sha256(content).hexdigest() if content is not None else None
            )
            assert document.retrieved_at == NOW and document.source_url == result.source_url
            assert (
                document.content_kind == "grobid_xml" and document.media_type == "application/xml"
            )
            assert document.retrieval_context == result.retrieval_context
            events.append("commit")
            return durable_id

    class Acquirer:
        provider_id = "openalex"

        async def acquire(self, provider_record_id: str) -> DocumentAcquisitionResult:
            assert provider_record_id == "W1" and events == ["read-closed"]
            events.append("provider-returned")
            return result

    assert (
        asyncio.run(acquire_source_document(Progress(), "run", expected_source_id, Acquirer()))
        == durable_id
    )
    assert events == ["read-closed", "provider-returned", "commit"]


def test_acquisition_contract_rejects_missing_usable_or_partial_failed_content() -> None:
    with pytest.raises(ValueError, match="nonempty"):
        DocumentAcquisitionResult("usable", "xml", "context", NOW, "url", "application/xml")
    with pytest.raises(ValueError, match="discard partial"):
        DocumentAcquisitionResult(
            "incomplete", "xml", "context", NOW, "url", "application/xml", b"<partial>"
        )


@pytest.mark.parametrize(
    "keys",
    [
        (ExactSourceKey("provider_record", "openalex", "W123"),),
        (ExactSourceKey("external_identifier", "openalex", "https://openalex.org/W123"),),
        (
            ExactSourceKey("provider_record", "openalex", "https://openalex.org/W123/"),
            ExactSourceKey("external_identifier", "openalex", "W123"),
            ExactSourceKey("external_identifier", "doi", "10.1/unrelated"),
        ),
    ],
)
def test_durable_work_identity_and_equivalent_key_forms(keys: tuple[ExactSourceKey, ...]) -> None:
    assert openalex_acquisition_identity(keys) == "W123"


@pytest.mark.parametrize(
    "keys, error",
    [
        ((), "no usable"),
        ((ExactSourceKey("provider_record", "openalex", "A123"),), "no usable"),
        ((ExactSourceKey("external_identifier", "doi", "W123"),), "no usable"),
        (
            (
                ExactSourceKey("provider_record", "openalex", "W123"),
                ExactSourceKey("provider_record", "openalex", "W456"),
            ),
            "ambiguous",
        ),
        (
            (
                ExactSourceKey("external_identifier", "openalex", "W123"),
                ExactSourceKey("external_identifier", "openalex", "W456"),
            ),
            "ambiguous",
        ),
        (
            (
                ExactSourceKey("provider_record", "openalex", "W123"),
                ExactSourceKey("external_identifier", "openalex", "W456"),
            ),
            "ambiguous",
        ),
    ],
)
def test_missing_unusable_or_conflicting_durable_work_keys_fail(
    keys: tuple[ExactSourceKey, ...],
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        openalex_acquisition_identity(keys)
