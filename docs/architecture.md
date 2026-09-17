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
  -> structured clinical facts (bounded chunks)
  -> published-codebook candidate retrieval
  -> constrained model selection
  -> Jev adapter (mock unless explicitly configured)
  -> deterministic active-code/NCCI/MUE/add-on/PFS checks
  -> confidence calibration
  -> mandatory review or guarded submission-ready state
  -> append-only corrections + evaluation
```

Model calls use the Responses API with strict JSON schemas and `store=false`. They receive page-derived evidence chunks rather than a single raw-PDF prompt. Runtime repositories read normalized tables only. A model cannot introduce a code outside the retrieved active candidate set, and every accepted line must link back to evidence spans.
