# Research Atlas documentation

Research Atlas separates research intent, actual execution, reported findings, and downstream
interpretation. The current executable workflow is metadata discovery.

- [Architecture](architecture.md): lean v1 boundaries and Stage 1 limits.
- [Lifecycle](research-lifecycle.md): user request through future evidence-backed output.
- [Identifiers](architecture/naming-and-identifiers.md): Source, provider, and execution identity.
- [Providers](providers.md): OpenAlex and optional Crossref behavior.
- [CLI](cli.md): metadata-only developer diagnostic.
- [ADR register](adr/README.md): retained decisions and explicitly superseded history.
- [Project examples](../projects/README.md): optional project and request data.

The package retains software versioning. Internal request and record classes are evolving
pre-v1 implementation details, without independently versioned aggregate/export contracts.
No database, extraction engine, synthesis service, or frontend is implemented. Run 001 remains
unexecuted.
