# OrthoCode AI

OrthoCode AI is an evidence-first orthopedic medical-coding platform. Its runtime is constrained to a normalized, versioned codebook release and retains page-level evidence for every proposed coding line.

## Implemented workflow

- Immutable raw-file inventory with SHA-256 provenance
- Source-specific parsers for ICD-10-CM, ICD-10-PCS, HCPCS Level II and modifiers, PFS attributes, MUE, add-on-code edits, rule documents, and NCCI PTP files when supplied
- AMA CPT Standard current-format import with licensed source isolation, annual control totals, descriptors, categories, and modifiers
- Staged canonical normalization, validation reports, release fingerprints, and atomic publication
- Runtime repositories for code lookup, effective-date checks, NCCI, MUE, add-on relationships, and PFS attributes
- De-identified PDF upload, per-page text extraction, evidence spans, and bounded model inputs
- OpenAI Responses API Structured Outputs with `store=false` for clinical facts and constrained code selection
- Published-codebook candidate retrieval and evidence-only reasoning
- Deterministic active-code, modifier, NCCI PTP, MUE, add-on, and PFS checks
- GREEN/YELLOW/RED calibration with autonomy disabled by default
- Append-only human reviews/corrections and gold-set evaluation metrics
- FastAPI chart, coding, review, evaluation, administration, and code-search endpoints
- Next.js operations, upload, processing, review, evaluation, and reference-data screens
- Parser, repository, workflow, validation, and raw-data-boundary tests

The supplied bundle passes structural validation with 11,525 licensed 2026 CPT codes and 4.49 million directional NCCI PTP revisions. Chart processing remains locked unless the active published release includes licensed CPT records for the service date.

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
