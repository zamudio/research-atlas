# Architecture Promotion Guidance v0.1

## Review sequence

Consider promotion through the following gates:

> Research relevance → definition clarity → evidence quality → generalizability → product
> observability → inference reliability → project/domain actionability → architectural
> necessity

This is review guidance, not code-enforced truth. Record the rationale at each material gate. A
construct can fail a gate and remain scientifically important.

## Placement is a separate decision

Importance does not imply that a conclusion belongs in product architecture. When translation is
in scope, select a destination only from the project's supplied destination vocabulary, or record
that no product destination is warranted. Destination names are project data, not protocol enums.

Prefer raw observations over inferred traits. State the signal, assumptions, confounders, failure
cost, and expiration or review conditions before proposing inferred state. If the product cannot
observe a construct reliably, it may still inform a project-wide design rule without being modeled
per user.

Promotion creates separate `ArchitectureCandidate` or `ProductImplication` records that reference
the supporting `EvidenceAssessment`. It must not mutate, relabel, or rewrite that assessment.

## Discovery is not proof

Recurrence across papers is a discovery signal: it suggests a construct deserves investigation.
Frequency does not establish conceptual clarity, effect importance, causal relevance, measurement
validity, or architectural necessity. Promotion requires evidence and product-specific reasoning,
not a mention count.
