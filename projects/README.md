# Optional project data

Project directories contain reusable research context and unexecuted request examples. Core code
must not import these files or branch on a particular project ID.

`project.yaml` supplies identity and optional objectives, scope, and constraints. Files under
`runs/` can contain a ResearchRequest with a question and optional subquestions/plan notes; loading
one does not create or execute a ResearchRun. Actual searches are recorded separately when execution
is implemented.

AI Tutor's `application.yaml` is optional downstream output guidance, not a validated core profile
or a required evidence lifecycle. Its taxonomy is an inquiry aid. Neither governs core contracts.
The Learning Foundations request (Run 001) remains unexecuted.
