# Security and privacy

The development profile is for de-identified charts only. `PHI_MODE=true` is rejected at startup unless an approved storage provider, database, Redis, JWT secret, and explicit provider approvals are configured.

- PDF/chart content is never written to ordinary logs.
- Logs use identifiers such as request, chart, job, and model-run IDs.
- Raw reference files are mounted read-only and are not served by the API.
- Licensed CPT source files live under `LICENSED_CODEBOOK_DATA_PATH`, which is ignored by Git and excluded from Docker builds.
- The frontend receives no provider secrets and no source files.
- Autonomous coding remains disabled by default.
- OpenAI requests use Structured Outputs and explicitly set `store=false`.
- TypeSafe JEV receives only bounded decision state and cited de-identified evidence spans. `JEV_PHI_ALLOWED=false` remains the default.
- JEV failures never trigger a silent OpenAI coding fallback in `jev_primary`; they create a safe review result with no fabricated lines.
- Development uploads are rejected unless the operator confirms they are de-identified.
- Model runs retain fingerprints, counts, structured outputs, and token usage—not raw request prompts in ordinary logs.

Production deployment still requires a compliance review, vendor agreements appropriate to the data, private object storage, key rotation, access controls, retention enforcement, and audit monitoring.
