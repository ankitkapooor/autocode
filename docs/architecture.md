# Architecture

OrthoCode is a monorepo with a Next.js web service, FastAPI API, background worker, PostgreSQL/pgvector, Redis, and private object storage. The application is delivered in phases so no AI output can outrun the reference-data controls beneath it.

## Phase 0 data flow

```text
immutable raw files
  -> source discovery + SHA-256 inventory
  -> source-specific parsers
  -> canonical staged release
  -> validation + cross-source checks
  -> immutable report and release fingerprint
  -> atomic publication
  -> runtime repositories and search documents
```

Import code is isolated under `app/reference_data`. Runtime code depends only on repository interfaces in `app/repositories`; it never opens the raw bundle. The automated boundary test enforces that separation.

## Release safety

Every import creates a distinct release. Validation errors mark the release `rejected`. Publication checks the status again and, in one transaction, supersedes the previous release and activates the new one. A failed import therefore cannot affect runtime coding.

## Coding workflow

```text
de-identified PDF
  -> page text + immutable evidence spans
  -> OpenAI atomic clinical facts (bounded chunks, store=false)
  -> JEV fact validation (performed/planned/historical/ruled-out/unsupported)
  -> active published-codebook candidate retrieval
  -> JEV bounded procedure, diagnosis, modifier, and relationship decisions
  -> evidence-backed coding-line assembly
  -> deterministic active-code/NCCI/MUE/add-on/PFS and unit checks
  -> JEV documentation adjudication only where a deterministic rule permits an exception
  -> confidence calibration
  -> mandatory review or guarded submission-ready state
  -> append-only corrections + evaluation
```

OpenAI calls use the Responses API with strict JSON schemas and `store=false`. OpenAI receives page-derived evidence chunks and produces atomic facts and retrieval phrases; in `jev_primary` it does not select codes, modifiers, units, or diagnosis pointers. JEV receives bounded state containing the service date, setting, relevant facts, cited raw evidence spans, active candidates, descriptions, and applicable metadata. Its `Choice` and `Noul` answers are validated again at the application boundary. Unknown candidates, missing probabilities, missing answers, and evidence-free lines are rejected.

Runtime repositories read normalized tables only. Candidate codes come exclusively from `CodebookRepository` for the active service-date release. Deterministic rules remain authoritative: JEV cannot override an inactive code, MUE, NCCI indicator `0`, invalid add-on relationship, inactive modifier, or fee-schedule constraint. For NCCI indicator `1`, JEV answers only the documentation question and Python applies the rule outcome. Administered quantities may be validated by JEV, but Python performs unit conversion.

## Decision-engine modes

- `legacy_llm`: OpenAI fact extraction → candidate retrieval → OpenAI code selection → legacy JEV verification → deterministic rules. This is the rollback path.
- `jev_shadow`: the legacy result remains user-facing and reviewable. The full JEV graph runs separately, is stored under `CodingResult.jev_output.shadow`, and includes code-system, modifier, unit, line-count, and confidence comparison metrics.
- `jev_primary`: OpenAI fact extraction → JEV fact validation → candidate retrieval → JEV code/modifier/link decisions → coding assembly → deterministic rules. `OpenAIClinicalProvider.select_codes()` is not invoked.

If JEV is disabled, blocked for PHI, times out, returns an HTTP failure, or produces malformed typed answers in primary mode, the chart, facts, evidence, and retrieved candidates remain persisted. The result contains no fabricated coding lines, records `JEV_UNAVAILABLE`, is RED/needs-review, and is never autonomous-eligible. Rollback requires an explicit environment change to `legacy_llm`.

## Decision trace and confidence

The complete graph is stored in the existing `CodingResult.jev_output` JSON field and individual provider calls are represented by `ModelRun`. Primary coding lines use `source="jev_decision_engine"`, retain evidence-span IDs, and take confidence from the JEV choices that actually contributed to the line. Rationale text is generated from this trace rather than by a second generative explanation call.

`JEV_ACCEPT_THRESHOLD` and `JEV_REVIEW_THRESHOLD` control routing. Primary calibration uses the weakest contributing line decision, unresolved/abstained decisions, provider availability, pipeline warnings, and deterministic failures; it does not average unrelated probabilities. Autonomous eligibility additionally requires primary mode, successful JEV execution, all line decisions above the accept threshold, no deterministic failure, GREEN state, and an explicit `AUTONOMOUS_CODING_ENABLED=true`.

OrthoCode uses a generative model to transform unstructured orthopedic charts into evidence-grounded clinical state. Candidate codes are retrieved exclusively from the active normalized codebook. TypeSafe JEV then makes the probabilistic clinical and coding decisions over those bounded candidates. Deterministic CMS rules enforce NCCI, MUE, add-on, active-code, and fee-schedule constraints. Uncertain or conflicting decisions are routed to human review.
