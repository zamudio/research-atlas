# Screening protocol 0.1

Screening decisions are append-only records tied to a research run, source, stage, and optionally
one study within the source. Use the small core decision vocabulary while keeping project/run
reason codes as extensible strings.

A correction creates a new decision with `supersedes_decision_id`; it does not overwrite history.
The current state is the set of decisions not superseded by another valid decision. Record the
reviewer, method, timing, and review state through `RecordProvenance`.
