# Project-owned definitions

Each directory here contains project data consumed by Research Atlas workflows. These files are
outside the `research_atlas` package, and core code must not import them or branch on their values.

A project directory may contain a generic `project.yaml`, an optional consumer-specific
`application.yaml`, versioned vocabulary or taxonomies, and validated `RunDefinition` YAML under
`runs/`. A planned definition is not an executed `ResearchRun`: it has no timestamps, search
results, screening decisions, or extracted records. Exact queries may remain intentionally absent
while the definition is planned. SearchSpec identities become stable when the definition is
approved.
