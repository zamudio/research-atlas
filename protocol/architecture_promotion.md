# Architecture Promotion Guidance v0.1

## Review sequence

Consider promotion through the following gates:

> Research relevance → definition clarity → evidence quality → generalizability → product
> observability → inference reliability → pedagogical/product actionability → architectural
> necessity

This is review guidance, not code-enforced truth. Record the rationale at each material gate. A
construct can fail a gate and remain scientifically important.

## Placement is a separate decision

Importance does not imply persistent state. A supported conclusion may belong in:

- evidence or an audit trail;
- persistent state;
- session or concept state;
- policy or curriculum;
- telemetry;
- UX guidance; or
- nowhere in the product architecture.

Prefer raw observations over inferred traits. State the signal, assumptions, confounders, failure
cost, and expiration or review conditions before proposing inferred state. If the product cannot
observe a construct reliably, it may still inform universal design or policy without being modeled
per user.

## Discovery is not proof

Recurrence across papers is a discovery signal: it suggests a construct deserves investigation.
Frequency does not establish conceptual clarity, effect importance, causal relevance, measurement
validity, or architectural necessity. Promotion requires evidence and product-specific reasoning,
not a mention count.
