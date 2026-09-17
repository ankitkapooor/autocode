#!/usr/bin/env python3
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
import csv, hashlib, os, re, sys, zipfile
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
REF = ROOT / "reference_data"
MANIFEST = ROOT / "MANIFEST.csv"

UA = "Mozilla/5.0 (compatible; OrthoCodingReferenceDownloader/1.0; +https://cms.gov)"
S = requests.Session()
S.headers.update({"User-Agent": UA})

rows = []

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def record(dataset, source, effective, status, local_path="", note=""):
    rows.append({
        "dataset": dataset,
        "source_url": source,
        "effective_date": effective,
        "status": status,
        "local_path": local_path,
        "sha256": sha256(local_path) if local_path and Path(local_path).exists() else "",
        "note": note,
    })

def safe_name(url, fallback):
    name = unquote(Path(urlparse(url).path).name) or fallback
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    return name

def validate_binary(resp, expected_ext):
    ct = (resp.headers.get("content-type") or "").lower()
    data = resp.content[:8]
    if expected_ext == ".zip":
        return data.startswith(b"PK")
    if expected_ext == ".pdf":
        return data.startswith(b"%PDF")
    return "text/html" not in ct

def download(dataset, url, folder, effective, filename=None):
    destdir = REF / folder
    destdir.mkdir(parents=True, exist_ok=True)
    ext = Path(urlparse(url).path).suffix.lower()
    if filename is None:
        filename = safe_name(url, re.sub(r"\W+","_",dataset)+ext)
    path = destdir / filename
    try:
        r = S.get(url, timeout=90, allow_redirects=True)
        r.raise_for_status()
        ext2 = path.suffix.lower()
        if ext2 in (".zip",".pdf") and not validate_binary(r, ext2):
            note = f"Expected {ext2} but received {r.headers.get('content-type')}; likely CMS interstitial/license page. Final URL: {r.url}"
            note_path = destdir / (path.stem + "_DOWNLOAD_REQUIRED.txt")
            note_path.write_text(
                f"{dataset}\n\nOfficial source:\n{url}\n\n{note}\n"
                "Open the official source in your browser, complete any required terms yourself, "
                "then place the downloaded file in this folder.\n", encoding="utf-8")
            record(dataset, url, effective, "manual_download_required", str(note_path), note)
            return None
        path.write_bytes(r.content)
        record(dataset, r.url, effective, "downloaded", str(path))
        return path
    except Exception as e:
        note_path = destdir / (re.sub(r"\W+","_",dataset) + "_DOWNLOAD_FAILED.txt")
        note_path.write_text(f"{dataset}\n\nOfficial source:\n{url}\n\nError:\n{e}\n", encoding="utf-8")
        record(dataset, url, effective, "failed", str(note_path), str(e))
        return None

def soup(url):
    r = S.get(url, timeout=90)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def find_anchor(page, text_contains, prefer_ext=None):
    sp = soup(page)
    candidates=[]
    for a in sp.find_all("a", href=True):
        txt=" ".join(a.stripped_strings)
        if text_contains.lower() in txt.lower():
            href=urljoin(page,a["href"])
            if prefer_ext and prefer_ext not in href.lower():
                # CMS often uses extensionless download URLs; do not exclude
                pass
            candidates.append((txt,href))
    if not candidates:
        raise RuntimeError(f"No link matching {text_contains!r} on {page}")
    return candidates[0]

def find_all_anchors(page, predicates):
    sp=soup(page)
    out=[]
    for a in sp.find_all("a", href=True):
        txt=" ".join(a.stripped_strings)
        if all(p.lower() in txt.lower() for p in predicates):
            out.append((txt,urljoin(page,a["href"])))
    return out

def download_anchor(dataset, page, match, folder, effective):
    try:
        txt,url=find_anchor(page,match)
        ext=".zip" if "zip" in txt.lower() or "rvu26c" in txt.lower() else Path(urlparse(url).path).suffix
        fname=safe_name(url, re.sub(r"\W+","_",dataset)+(ext or ""))
        if not Path(fname).suffix and ext:
            fname += ext
        return download(dataset,url,folder,effective,fname)
    except Exception as e:
        note=REF/folder/(re.sub(r"\W+","_",dataset)+"_LINK_LOOKUP_FAILED.txt")
        note.write_text(f"Page: {page}\nMatch: {match}\nError: {e}\n",encoding="utf-8")
        record(dataset,page,effective,"failed",str(note),str(e))
        return None

def extract_zip(path, outdir):
    if not path or not path.exists() or path.suffix.lower()!=".zip": return
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(outdir)
    except Exception as e:
        print("Could not extract", path, e)

def build_ortho_index():
    # Identifier-only index from downloaded/extracted public PFS data.
    # This does not copy CPT descriptors or guidelines.
    cpt_dir=REF/"cpt"
    codes=set()
    for p in cpt_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".csv",".txt"): continue
        try:
            with open(p,"r",encoding="latin-1",errors="ignore") as f:
                for line in f:
                    # Prefer first field / first token, but capture only numeric 5-char codes 20000-29999
                    head=line[:50]
                    for m in re.finditer(r'(?<!\d)(2\d{4})(?!\d)', head):
                        code=m.group(1)
                        if 20000 <= int(code) <= 29999:
                            codes.add(code)
        except Exception:
            pass
    out=cpt_dir/"ortho_cpt_codes_from_pfs.csv"
    with open(out,"w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["code_identifier"])
        for c in sorted(codes): w.writerow([c])
    record("Derived ortho CPT/HCPCS identifier index","local derivation from CMS PFS RVU26C","2026-07-01","generated",str(out),
           "Identifier-only 20000-29999 index; not AMA CPT Standard Data File.")

print("Downloading official coding references...")

# 1. CMS PFS / CPT identifiers
rvu = download_anchor(
    "CMS PFS RVU26C July 2026",
    "https://www.cms.gov/medicare/payment/fee-schedules/physician/pfs-relative-value-files/rvu26c",
    "RVU26C", "cpt", "2026-07-01")
if rvu: extract_zip(rvu, REF/"cpt"/"rvu26c_extracted")

# 2. ICD-10-CM official CDC files
cdc_base="https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2026-update/"
cdc_files=[
("ICD-10-CM April 2026 Code Descriptions","icd10cm-Code%20Descriptions-April-1-2026.zip"),
("ICD-10-CM April 2026 XML","icd10cm-April-1-2026-XML.zip"),
("ICD-10-CM April 2026 Tables and Index","icd10cm-table-and-index-April-1-2026.zip"),
("ICD-10-CM April 2026 Addenda","icd10cm-addenda-April-1-2026.zip"),
("ICD-10-CM April 2026 Guidelines","ICD-10-CM%20April%201%202026%20Guidelines%20Final.pdf"),
]
for ds,fn in cdc_files:
    p=download(ds,cdc_base+fn,"icd10cm","2026-04-01")
    if p and p.suffix.lower()==".zip": extract_zip(p,REF/"icd10cm"/"extracted")

# 3. ICD-10-PCS April 2026 from CMS
icd_page="https://www.cms.gov/medicare/coding-billing/ICD-10-codes"
pcs_targets=[
("ICD-10-PCS April 2026 Order File","April 1, 2026 ICD-10-PCS Order File"),
("ICD-10-PCS April 2026 Guidelines","April 1, 2026 Official ICD-10-PCS Coding Guidelines"),
("ICD-10-PCS April 2026 Version Update Summary","April 1, 2026 Version Update Summary"),
("ICD-10-PCS April 2026 Codes File","April 1, 2026 ICD-10-PCS Codes File"),
("ICD-10-PCS April 2026 Conversion Table","April 1, 2026 ICD-10-PCS Conversion Table"),
("ICD-10-PCS April 2026 Code Tables and Index","April 1, 2026 ICD-10-PCS Code Tables and Index"),
("ICD-10-PCS April 2026 Addendum","April 1, 2026 ICD-10-PCS Addendum"),
]
for ds,match in pcs_targets:
    p=download_anchor(ds,icd_page,match,"icd10pcs","2026-04-01")
    if p and p.suffix.lower()==".zip": extract_zip(p,REF/"icd10pcs"/"extracted")

# 4. HCPCS July 2026
hcpcs=download_anchor(
    "HCPCS July 2026 Alpha-Numeric",
    "https://www.cms.gov/medicare/coding-billing/healthcare-common-procedure-system/quarterly-update",
    "July 2026 Alpha-Numeric HCPCS File","hcpcs","2026-07-01")
if hcpcs: extract_zip(hcpcs,REF/"hcpcs"/"extracted")

# 5. NCCI Q3 2026 PTP — all split files
ptp_page="https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-procedure-procedure-ptp-edits"
try:
    links=find_all_anchors(ptp_page,["v322r0"])
    selected=[x for x in links if "Hospital PTP Edits" in x[0] or "Practitioner PTP Edits" in x[0]]
    if not selected:
        raise RuntimeError("No v322r0 PTP links found")
    for i,(txt,url) in enumerate(selected,1):
        kind="practitioner" if "Practitioner" in txt else "hospital"
        p=download(f"NCCI Q3 2026 {kind} PTP part {i}",url,"ncci","2026-07-01",
                   f"ncci_q3_2026_{kind}_ptp_part_{i}.zip")
        if p: extract_zip(p,REF/"ncci"/f"{kind}_ptp_extracted")
except Exception as e:
    note=REF/"ncci"/"PTP_Q3_2026_DOWNLOAD_REQUIRED.txt"
    note.write_text(f"Official page:\n{ptp_page}\n\nCould not retrieve automatically: {e}\n"
                    "Use the Q3 2026 v322r0 Practitioner and Hospital links on the official CMS page.\n",encoding="utf-8")
    record("NCCI Q3 2026 PTP",ptp_page,"2026-07-01","manual_download_required",str(note),str(e))

# 6. NCCI Add-on Code edits July 2026
download_anchor(
    "NCCI Add-On Code Edits effective July 1 2026",
    "https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-add-code-edits",
    "Add-On Code Edits for Medicare Effective 07012026","ncci","2026-07-01")

# 7. MUE archive July 1 2026.
# The archive has repeated identical anchor labels; collect all July-1-2026 anchors and classify by nearby headings/text.
mue_page="https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-medically-unlikely-edit-mue-archive"
try:
    sp=soup(mue_page)
    july=[]
    for a in sp.find_all("a",href=True):
        txt=" ".join(a.stripped_strings)
        if "Effective July 1, 2026" in txt:
            # Gather nearby previous heading/section text
            context=[]
            node=a
            for _ in range(25):
                node=node.find_previous()
                if node is None: break
                if getattr(node,"name",None) in ("h2","h3","h4","strong","th"):
                    t=" ".join(node.stripped_strings)
                    if t: context.append(t)
                if len(context)>=3: break
            ctx=" | ".join(context)
            july.append((ctx,txt,urljoin(mue_page,a["href"])))
    picked=[]
    for desired,label in [("Practitioner","practitioner"),("Facility Outpatient","outpatient_hospital")]:
        match=next((x for x in july if desired.lower() in x[0].lower()),None)
        if match:
            picked.append((label,match[2]))
    if len(picked)<2:
        raise RuntimeError("Could not distinguish Practitioner and Facility Outpatient July 2026 MUE links")
    for label,url in picked:
        p=download(f"MUE effective July 1 2026 {label}",url,"mue","2026-07-01",
                   f"mue_2026_07_01_{label}.zip")
        if p: extract_zip(p,REF/"mue"/f"{label}_extracted")
except Exception as e:
    note=REF/"mue"/"MUE_JULY_2026_DOWNLOAD_REQUIRED.txt"
    note.write_text(f"Official archive:\n{mue_page}\n\nCould not retrieve automatically: {e}\n"
                    "Download the Effective July 1, 2026 Practitioner and Facility Outpatient Hospital files.\n",encoding="utf-8")
    record("MUE July 1 2026",mue_page,"2026-07-01","manual_download_required",str(note),str(e))

# 8. Rules / policy manual
policy_page="https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-policy-manual"
download_anchor("2026 Medicare NCCI Full Policy Manual",policy_page,
                "Medicare Full-Complete Manual","rules","2026-01-01")
download_anchor("2026 NCCI Chapter 4 Musculoskeletal CPT 20000-29999",policy_page,
                "Chapter 4 - Surgery: Musculoskeletal System","rules","2026-01-01")

ncci_home="https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits"
download_anchor("CMS Proper Use of Modifiers 59 XE XP XS XU",ncci_home,
                "Proper Use of Modifiers 59, XE, XP, XS, and XU","rules","2026-01-01")

build_ortho_index()

with open(MANIFEST,"w",newline="",encoding="utf-8") as f:
    fields=["dataset","source_url","effective_date","status","local_path","sha256","note"]
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

print(f"\nDone. Manifest: {MANIFEST}")
print("Review any *_DOWNLOAD_REQUIRED.txt files. They indicate a CMS interstitial/license step that must be completed by you.")
