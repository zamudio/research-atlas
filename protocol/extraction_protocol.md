# Extraction guidance

The bounded extraction callable uses an immutable prepared GROBID SourceDocument and a deterministic
passage index. Extraction identifies its exact content version, configuration, validation and review
outcome; see [execution details](../docs/providers.md#extraction-execution).

A Source is a publication; create a separate Study for each clearly separable study or analysis.
A Finding states what that Study reported, before Atlas synthesizes evidence across studies.
Preserve missing or uncertain information explicitly.

Capture, where available:

- the exact content version and passage, page, or table supporting the extraction;
- study design, population, setting, sample, and domain;
- attributed construct definitions, operationalization, instruments, and timescales;
- treatments/interventions and comparators, when applicable;
- outcomes, result direction, estimates, uncertainty, moderators, and subgroup conditions;
- author interpretations separately from reviewer judgments;
- limitations, generalizability, replication context, and unresolved questions.

Constructs, measurements, and interventions retain distinct scientific meanings without requiring
independent relational identities. A measured signal is not automatically the construct it is
used to infer; an intervention is not automatically an outcome measure.

Retain extraction contract, projection and passage-index versions, instructions, schema and effective
provider/model settings. Reconstruct indexed input from the exact prepared content and index version.
Application code depends only on `StructuredExtractor`; runtime infrastructure chooses an adapter,
model, endpoint and credentials. Neither Ollama nor OpenAI is a default. Custom providers implement
and inject the same protocol. Credentials never enter extraction configuration or evidence provenance.
Extraction contract v3 uses explicit nulls/empty lists and bounded unique key/value detail entries;
Atlas maps details to the existing domain dictionaries. Historical evidence remains readable.
Models select supporting passage IDs only, never quotations or locators. Atlas resolves known IDs to
exact source blocks and deterministic locators; unknown or duplicate IDs cannot publish. Ambiguous
output stays marked for review. No empirical statement should gain support merely because it fits a
structured schema.

Study.extraction_id identifies the attempt; Finding anchors are passages and/or locators in that
attempt's immutable SourceDocument. Verify anchors against the checksummed content before accepting
output. Re-extraction creates a new attempt; the run explicitly selects one accepted extraction per
Source instead of treating repeated attempts as independent studies.
