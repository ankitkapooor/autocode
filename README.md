# OrthoCode AI

OrthoCode AI is an evidence-first orthopedic medical-coding platform. Its runtime is constrained to a normalized, versioned codebook release and retains page-level evidence for every proposed coding line.

## Implemented workflow

- Immutable raw-file inventory with SHA-256 provenance
- Source-specific parsers for ICD-10-CM, ICD-10-PCS, HCPCS Level II and modifiers, PFS attributes, MUE, add-on-code edits, rule documents, and NCCI PTP files when supplied
- AMA CPT Standard current-format import with licensed source isolation, annual control totals, descriptors, categories, and modifiers
- Staged canonical normalization, validation reports, release fingerprints, and atomic publication
- Runtime repositories for code lookup, effective-date checks, NCCI, MUE, add-on relationships, and PFS attributes
- De-identified PDF upload, per-page text extraction, evidence spans, and bounded model inputs
- OpenAI Responses API Structured Outputs with `store=false` for atomic, evidence-linked clinical fact extraction
- Published-codebook candidate retrieval with no free-form code generation
- Three decision-engine modes: `legacy_llm`, `jev_shadow`, and `jev_primary`
- Batched TypeSafe JEV fact validation, bounded code selection, modifier decisions, diagnosis relationships, and NCCI documentation-exception decisions
- Deterministic active-code, modifier, NCCI PTP, MUE, add-on, and PFS checks
- Deterministic HCPCS unit arithmetic from validated administered quantities
- JEV-authoritative GREEN/YELLOW/RED calibration with configurable accept/review thresholds and autonomy disabled by default
- Append-only human reviews/corrections and gold-set evaluation metrics
- FastAPI chart, coding, review, evaluation, administration, and code-search endpoints
- Next.js operations, upload, processing, review, evaluation, and reference-data screens
- Parser, repository, workflow, validation, and raw-data-boundary tests

The supplied bundle passes structural validation with 11,525 licensed 2026 CPT codes and 4.49 million directional NCCI PTP revisions. Chart processing remains locked unless the active published release includes licensed CPT records for the service date.

## Decision-engine migration

`CODING_DECISION_ENGINE=legacy_llm` preserves the original OpenAI selection followed by JEV verification and is the rollback mode. `jev_shadow` keeps that legacy result user-facing while persisting a separately computed JEV decision graph and agreement metrics. `jev_primary` uses OpenAI only to structure chart evidence; TypeSafe JEV makes the uncertain coding decisions over active retrieved candidates, and Python applies deterministic rules and arithmetic. Primary mode never falls back to OpenAI code selection when JEV is unavailable.

JEV-primary is the default production configuration:

```bash
CODING_DECISION_ENGINE=jev_primary
JEV_ENABLED=true
JEV_BASE_URL=https://api.typesafe.ai
JEV_MODEL=jev-latest
JEV_ACCEPT_THRESHOLD=0.80
JEV_REVIEW_THRESHOLD=0.50
AUTONOMOUS_CODING_ENABLED=false
```

`legacy_llm` remains available only as an explicit rollback mode. If JEV is unavailable or a decision does not meet the acceptance threshold, primary mode fails closed and requires human review.

## Local development

Prerequisites: Python 3.12+, Node 20+, PostgreSQL 16+, and Redis 7+.

```bash
cp .env.example .env
docker compose up --build
```

The web app is available at `http://localhost:3000`, the API at `http://localhost:8000`, and API documentation at `http://localhost:8000/docs`.

## Reference-data import

The complete supplied bundle can be inspected without mutating the database:

```bash
cd backend
python scripts/import_reference_data.py \
  --source-root ../ortho_coding_reference_bundle/reference_data \
  --dry-run
```

Once all required source files—including licensed NCCI PTP files—are present, create, validate, and atomically publish a release:

```bash
python scripts/import_reference_data.py \
  --source-root ../ortho_coding_reference_bundle/reference_data \
  --release-name 2026-Q3 \
  --effective-from 2026-07-01 \
  --publish
```

The complete private bundle, including the AMA annual package under `reference_data/cpt`, is imported through the same atomic release:

```bash
python scripts/import_reference_data.py \
  --source-root ../ortho_coding_reference_bundle/reference_data \
  --release-name 2026-Q3 \
  --effective-from 2026-07-01 \
  --publish
```

See [reference-data normalization](docs/reference_data_normalization.md), [architecture](docs/architecture.md), [security](docs/security.md), and [Railway deployment](docs/railway.md).
