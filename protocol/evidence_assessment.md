# Evidence assessment guidance

An assessment evaluates an explicit claim across reported Findings. It is not a copy of authors'
interpretations, a publication count, or a universal numeric evidence score.

Reason about relevant dimensions, with explanations rather than a mandatory ontology:

- study design and fitness for causal claims;
- independent replication and overlapping study populations/publications;
- consistency, contradictory findings, null results, and publication bias;
- measurement validity and uncertainty in estimates;
- population coverage and transfer across settings, tasks, and timescales.

Reviews and meta-analyses can be useful but require attention to eligibility, heterogeneity,
analytic choices, and overlap with primary evidence. Non-significance is not proof of no effect.

Insights must identify the Findings being used, explain their relationship to the claim,
and preserve uncertainty and generalizability limits. Findings must lead back to Studies and exact
source content. Insufficient evidence must remain insufficient. Insight contracts
alone do not establish that a claim is supported. InsightFinding requires an explicit supporting,
contradicting or contextual role with rationale; nullness is a Finding property, never an inferred role.

Published results and citations must remain reproducible when later evidence changes conclusions.
Correction behavior belongs with the implemented evidence workflow, without requiring a generic
supersession graph now.

## Implemented synthesis boundary

The caller deliberately selects 1..100 distinct Finding IDs valid for the producing run's currently
selected accepted extractions. A provider-neutral supplied synthesizer receives only that bounded
evidence packet and exact instructions/configuration bytes. Its strict `InsightProposal` JSON has
one claim, plain-text qualifications, uncertainty/limitations and generalizability notes, plus one
explicit supporting/contradicting/contextual rationale for every selected Finding. Unknown fields,
blank claims/rationales, duplicates, omissions and introduced evidence fail validation. At least one
explicit supporting relationship is required; this is an appraisal requirement, not proof of truth.

Publication rechecks selection and acceptance under membership locks and commits the Insight and
all links atomically. Published content and links cannot be edited. Exact UUID/content retries are
idempotent; new appraisal results use new UUIDs. Later extraction selection never redirects history.
Source citations project the whole selected metadata observation; evidence identities and anchors
refer to the immutable historical chain.

Count Findings, distinct Studies and distinct Sources separately. Several Findings from one Study
do not constitute independent replication. Different Study/Source IDs do not establish independence;
retain an overlap warning without inventing cross-publication identity resolution. Evidence Briefs
must retain all roles and uncertainty and may only format published claims. See the
[callable workflow and reads](../docs/synthesis-and-product-access.md).
