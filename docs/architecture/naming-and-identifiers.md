# Naming and identifiers

Atlas UUIDs identify Sources, metadata observations, documents, extraction attempts, Studies,
Findings and Insights. Run/project/search IDs identify their respective ownership boundaries.
No contributor, construct, measurement or intervention identity is created.

Provider-qualified publication IDs and explicitly trusted normalized external keys are Source
matching evidence, not Atlas identity. Unknown reported identifiers stay on metadata observations.
Provider author IDs and ORCID are bibliographic credit data only. Source metadata provenance and
search/discovery provenance remain separate.

LiteratureRecord.observation_id identifies the exact attributable snapshot; its candidate Source
UUID is provisional. resolved_source_id identifies reconciliation success and is null for conflicts.
Source.display_observation_id names the selected whole snapshot. Stage 3 reuses stored Source IDs
and observation IDs through indexed identity lookup and replay idempotency; it does not persist
provisional candidate IDs as extra Sources.

SourceDocument.document_id pins immutable anchorable bytes with content_sha256. Retrieval URLs
may change and are not version identities. Extraction.source_document_id selects that exact version;
Study.extraction_id and Finding.source_study_id complete the provenance path. Evidence anchors are
plain passage/locator values within that document, not separately identified layout entities.

InsightFinding uses the (insight_id, finding_id) relationship with an explicit role/rationale.
A Finding's result direction is independent of its relationship to a claim. Configuration hashes
identify exact retained instructions/settings; software versioning remains independent.

See [persistence semantics](../persistence-boundary.md) for uniqueness and concurrency rules.
