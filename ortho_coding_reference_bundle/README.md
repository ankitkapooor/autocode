# Ortho Coding Reference Bundle — 2026

This bundle is a downloader/organizer for official public CMS/CDC medical-coding reference files.

Target date of service: 2026-09-17

It downloads/organizes:
- CMS Physician Fee Schedule July 2026 (RVU26C)
- ICD-10-CM April 1, 2026 files (CDC/CMS)
- ICD-10-PCS April 1, 2026 files (CMS)
- HCPCS Level II July 2026 Alpha-Numeric file (CMS)
- Medicare NCCI Q3 2026 PTP edits (Practitioner + Hospital), when directly downloadable
- Medicare MUE tables effective July 1, 2026 (Practitioner + Facility Outpatient Hospital)
- Medicare NCCI Add-On Code edits effective July 1, 2026
- 2026 Medicare NCCI Policy Manual and musculoskeletal chapter
- CMS guidance on NCCI modifiers

## Important CPT licensing note
This package intentionally does NOT contain the AMA CPT Standard Data File, full CPT descriptors, CPT guidelines, or any other licensed AMA CPT product.

CMS public-use files may contain CPT/HCPCS code identifiers and Medicare attributes, but that does not grant a license to redistribute the AMA CPT Standard Data File or use licensed CPT content outside its terms.

For a production coding engine, keep licensed CPT content in a separately controlled retrieval layer under the applicable AMA license.

## Run
Python 3.10+ recommended.

1. unzip this bundle
2. open a terminal in the unzipped directory
3. install dependencies:
   pip install -r requirements.txt
4. run:
   python fetch_reference_data.py

Downloaded files will be placed under `reference_data/`.

The script also writes `MANIFEST.csv` with source URL, effective date, status, local path, and SHA-256.

## Why the data is not already embedded in this ZIP
The chat file-building sandbox cannot retrieve binary archives from CMS/CDC even though their public pages are accessible. This downloader uses your own normal internet connection to retrieve the official binaries directly from CMS/CDC and produces the intended dataset structure.
