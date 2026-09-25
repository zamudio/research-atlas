# Extraction Protocol v0.3

## Unit of extraction

Create one source record per publication, report, chapter, or preprint. Create a separate study
record for each study or clearly separable analysis reported by that source. Preserve provider
identifiers as source provenance rather than adopting them as internal identity. Record absence or
uncertainty explicitly; do not fill gaps with assumptions.

The extraction and optional promotion chain is:

```text
Source/publication -> Study/analysis -> Measurement/Intervention -> Finding
                   -> EvidenceAssessment
                        -> optional, separate ApplicationCandidate/DecisionImplication
```

A finding records what one study reported. An evidence assessment is the later cross-study
assessment of an explicit claim or body of evidence and references findings as supporting,
contradictory, or null. It may link relevant constructs but is not required to resolve to one.

## Required extraction frame

Across the source and its studies, capture:

1. source citation, URL, external identifiers, and provider provenance;
2. each study's type or design;
3. population, domain, setting, and sample;
4. constructs and the source-attributed definitions used;
5. operationalization and measurements;
6. intervention or manipulation and comparator, when applicable;
7. outcomes;
8. timescale;
9. each finding's result, direction or status, generic estimate information, and uncertainty;
10. limitations stated by authors and limitations identified by reviewers;
11. moderators and subgroup conditions;
12. replication and generalization notes;
13. follow-up questions.

When a later, separately scoped evidence-application stage is performed, also record consumer
observability, candidate raw signals, inference risks and confounders, plausible actions,
and a destination from the project-supplied destination vocabulary (or no destination). These
application fields are not required for every finding or every evidence assessment.

Every study, construct, measurement, intervention, finding, evidence assessment, application
candidate, and decision implication records its creation run, time, creation method, optional
tool and model versions, and optional review state. The creation run must be present in the same
validated record set. This required process provenance is separate from source-provider
provenance. Every extracted conclusion must retain a path to the study and source. Separate author
interpretation, reviewer notes, and the evidence assessment.

## Terms that must not be collapsed

- A **construct** is an explanatory or descriptive concept under investigation.
- An **observable or measurement** is a recorded operation, response, instrument, or signal used
  as evidence about a construct. It is not the construct itself.
- An **intervention** is something manipulated, assigned, or deliberately done. It is not a measure
  of the outcome merely because it appears in the same study.

The same surface event may play different roles in different designs. Record the role asserted by
the study and the assumptions required to connect measurement to construct.

## Review

Ambiguous extractions remain marked for review. Reviewer changes preserve rationale and the source
reference. Protocol deviations must be noted on the research run rather than silently normalized.
