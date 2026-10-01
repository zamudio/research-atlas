# Research Atlas documentation

Research Atlas separates research intent, actual execution, reported findings, and downstream
interpretation. Executable paths include metadata discovery and the durable research slice accepting
supplied content/evidence, plus bounded OpenAlex cached GROBID XML acquisition for a persisted Source.

- [Architecture](architecture.md): lean v1 boundaries through Stage 4.
- [Lifecycle](research-lifecycle.md): user request through evidence-backed output.
- [Identifiers](architecture/naming-and-identifiers.md): Source, provider, and execution identity.
- [Providers](providers.md): OpenAlex and optional Crossref behavior.
- [Persistence boundary](persistence-boundary.md): Stage 3 identity, idempotency, transactions and reads.
- [Database setup](database.md): PostgreSQL configuration, migrations, operations and acceptance tests.
- [Synthesis and product access](synthesis-and-product-access.md): validated proposals, seven reads,
  query bounds and deterministic Evidence Brief usage.
- [CLI](cli.md): metadata-only developer diagnostic.
- [ADR register](adr/README.md): retained decisions and explicitly superseded history.
- [Project examples](../projects/README.md): optional project and request data.

The package retains software versioning. Internal request and record classes are evolving
pre-v1 implementation details, without independently versioned aggregate/export contracts.
Document acquisition supports only OpenAlex cached GROBID XML, one run/Source at a time.
Extraction execution, concrete synthesis-provider execution and frontend/API remain unimplemented.
Run 001 remains unexecuted.
