# Architecture decision records

Accepted decisions guide current architecture. Superseded records preserve historical reasoning;
their original bodies are not current implementation requirements.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-durable-source-identity.md) | Durable Source identity | Accepted |
| [0002](0002-architectural-boundaries-and-neutrality.md) | Architectural boundaries and neutrality | Accepted |
| [0003](0003-research-execution-and-provenance-model.md) | Original execution/provenance contracts | Superseded by the lean v1 intervention |
| [0004](0004-independent-contract-versioning.md) | Independent pre-release contract lattice | Superseded by the lean v1 intervention |
| [0005](0005-contribution-and-contributor-identity.md) | Durable contributor identity | Superseded by the lean v1 intervention |

The independent architecture audit authorizes the [lean v1 intervention](../architecture.md).
Stage 1 keeps actual execution and provenance distinctions while removing formal approval,
aggregate/export consistency, compulsory contract versions, and contributor resolution.
Provider-attributable bibliographic credit remains flexible data. Software versioning remains.
