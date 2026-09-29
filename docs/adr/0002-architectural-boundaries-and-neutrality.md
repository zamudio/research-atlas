# ADR 0002: Architectural boundaries and neutrality

## Status

Accepted. Lean v1 retains this central decision while reducing its original entity inventory.

## Decision

Keep user intent, actual execution, reported evidence, and downstream interpretation distinct.
The reusable domain is independent of scholarly providers, storage technology, AI Tutor,
LLM/agent frameworks, and output consumers.

Provider implementations belong behind application ports. Dataclasses are useful for trusted
internal state; external input is validated at its boundary. Project configuration is data,
not a switch that imports consumer-specific behavior into the core.

Source, Study, and Finding have different responsibilities. Future synthesis must explicitly
reference Findings; consumer recommendations must retain evidence and its qualifications.
This separation does not require formal approval contracts, ontology registries, or application
promotion entities.

## Consequences

If AI Tutor disappeared, the research model would still make sense. Provider changes and future
persistence work must preserve the meaning and provenance of evidence. Current concrete scope is
described in the [lean v1 architecture](../architecture.md).
