# Reference-data normalization

## Source mapping

| Source family | Preferred input | Parser | Canonical output | Effective-date semantics |
|---|---|---|---|---|
| ICD-10-CM | Official tabular XML ZIP | XML hierarchy adapter | `code_entries` + `code_search_documents` | Source release date; official hierarchy and leaf status preserved |
| ICD-10-PCS | Official order-file ZIP | Fixed-width order adapter | `code_entries` with system `ICD10PCS` | Stored for future compatibility; not active for V1 coding |
| HCPCS Level II | CMS Alpha-Numeric ZIP | Fixed-width contractor record | `code_entries`, `modifier_entries` | Source release effective date; numeric Level I rows excluded from the public HCPCS import |
| PFS/RVU | CMS CSV inside release ZIP | Header-driven CSV adapter | `pfs_procedure_attributes` | Release effective date; CPT/HCPCS identifiers preserved as strings |
| NCCI PTP | CMS practitioner/hospital XLSX or CSV ZIPs | Header-driven tabular adapter | `ncci_ptp_edits` | Directional Column 1/Column 2 records; setting is mandatory |
| MUE | CMS practitioner/facility XLSX ZIPs | Minimal OpenXML adapter | `mue_edits` | Setting is mandatory; disclosed values only |
| Add-on codes | CMS AOC XLSX ZIP | Minimal OpenXML adapter | `addon_code_relations` | Effective/deletion Julian dates are converted without inventing ranges |
| Policy manuals | Versioned official PDFs | Metadata/checksum adapter | `rule_source_documents` | Document release date; narrative is not converted into hard rules automatically |
| CPT | AMA CPT Standard current-format annual package | Tab-delimited licensed boundary adapter | `code_entries`, `code_search_documents`, `modifier_entries` | Annual codes use the code-set effective year; descriptor-effective dates remain metadata and are not misrepresented as code-effective dates |

## Canonical rules

Codes remain strings. Display punctuation is preserved while `code_key` is uppercased and stripped of non-alphanumeric formatting. Leading zeroes are retained. Every row links to a release and a raw source record. Missing values remain missing; parsers do not synthesize descriptions, dates, flags, or relationships.

## Validation and publication

Validation checks required sources, AMA annual control totals, checksums, blank and duplicate keys, effective-date order, MUE values, NCCI directionality/indicator values, source links, and cross-source references. Historical NCCI revisions receive a deterministic revision key so valid intervals are preserved without collapsing distinct records. References to inactive, deleted, or later-quarter codes remain advisory. Missing CPT or NCCI PTP data is blocking. Publication is a separate transaction and only accepts a validated release.

## Known limitations

- The supplied bundle contains extracted practitioner and hospital NCCI PTP data; the adapter streams these multi-million-row files in bounded batches.
- Licensed CPT source artifacts must remain outside Git, Docker images, frontend assets, logs, and API source-file responses.
- Narrative NCCI policy PDFs are inventoried but not transformed into deterministic rules.
- Embeddings are deferred until a canonical release can be published; lexical search documents are generated now.
