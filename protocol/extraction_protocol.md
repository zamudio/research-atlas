# Extraction guidance

Extraction execution is future work; SourceDocument and Extraction contracts now identify its
exact content version, configuration, validation and review outcome.

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

Record the actual extraction inputs, instructions, model/tool details, and review information
when extraction is implemented. Ambiguous output stays marked for review. No empirical statement
should gain support merely because it fits a structured schema.

Study.extraction_id identifies the attempt; Finding anchors are passages and/or locators in that
attempt's immutable SourceDocument. Verify anchors against the checksummed content before accepting
output. Re-extraction creates a new attempt; the run explicitly selects one accepted extraction per
Source instead of treating repeated attempts as independent studies.
