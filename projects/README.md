# Project-owned definitions

Each directory here contains project data consumed by Research Atlas workflows. These files are
outside the `research_atlas` package, and core code must not import them or branch on their values.

A project directory may contain a `project.yaml` profile, versioned project vocabulary or
taxonomies, and planned run definitions under `runs/`. A planned definition is not an executed
`ResearchRun`: it has no start timestamp, query log, screened sources, or extracted records until
execution begins.
