#!/usr/bin/env python3
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin
import csv, hashlib, re, threading, zipfile
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
REF = ROOT / "reference_data"
MANIFEST = ROOT / "MANIFEST.csv"
MAX_WORKERS = 6
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 25
FIELDS = ["dataset","source_url","effective_date","status","local_path","sha256","note"]
lock = threading.Lock()

for d in ["cpt","icd10cm","icd10pcs","hcpcs","ncci","mue","rules"]:
    (REF/d).mkdir(parents=True, exist_ok=True)

def session():
    s = requests.Session()
    retry = Retry(total=3, connect=3, read=3, backoff_factor=1,
                  status_forcelist=(429,500,502,503,504),
                  allowed_methods=frozenset(["GET","HEAD"]),
                  raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=12, pool_maxsize=12))
    s.headers.update({"User-Agent":"Mozilla/5.0 OrthoCodingReferenceDownloader/2.0"})
    return s
S = session()

def log(x): print(x, flush=True)

def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for c in iter(lambda:f.read(1024*1024),b""): h.update(c)
    return h.hexdigest()

def ensure_manifest():
    if not MANIFEST.exists():
        with MANIFEST.open("w",newline="",encoding="utf-8") as f:
            csv.DictWriter(f,fieldnames=FIELDS).writeheader()

def load_rows():
    ensure_manifest()
    with MANIFEST.open("r",newline="",encoding="utf-8") as f:
        return list(csv.DictReader(f))

def upsert(row):
    with lock:
        rows=load_rows()
        out=[]
        found=False
        for r in rows:
            if r.get("dataset")==row["dataset"]:
                out.append({k:row.get(k,"") for k in FIELDS}); found=True
            else:
                out.append(r)
        if not found: out.append({k:row.get(k,"") for k in FIELDS})
        tmp=MANIFEST.with_suffix(".csv.tmp")
        with tmp.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(out)
        tmp.replace(MANIFEST)

def valid(path,kind):
    if not path.exists() or path.stat().st_size==0: return False
    if kind=="zip": return zipfile.is_zipfile(path)
    if kind=="pdf":
        with path.open("rb") as f: return f.read(5)==b"%PDF-"
    return True

def html(resp):
    ct=(resp.headers.get("content-type") or "").lower()
    head=resp.content[:128].lstrip().lower()
    return "text/html" in ct or head.startswith(b"<html") or head.startswith(b"<!doctype")

def safe_extract(zp,out):
    out.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(zp) as z:
        base=out.resolve()
        for m in z.infolist():
            p=(out/m.filename).resolve()
            if not str(p).startswith(str(base)): raise RuntimeError("Unsafe ZIP path")
        z.extractall(out)

def note(folder,dataset,url,reason):
    p=REF/folder/(re.sub(r"\W+","_",dataset).strip("_")+"_DOWNLOAD_REQUIRED.txt")
    p.write_text(f"{dataset}\n\nOfficial source:\n{url}\n\nReason:\n{reason}\n\n"
                 "Open the official source yourself if CMS presents license/terms. "
                 "This script does not accept or bypass licensing terms.\n",encoding="utf-8")
    return p

def direct(dataset,url,folder,effective,filename,kind="zip",extract=None):
    dest=REF/folder/filename
    if valid(dest,kind):
        upsert({"dataset":dataset,"source_url":url,"effective_date":effective,
                "status":"already_present","local_path":str(dest.relative_to(ROOT)),
                "sha256":sha(dest),"note":"Skipped; valid file already exists."})
        log(f"[SKIP] {dataset}")
        if extract and kind=="zip":
            out=REF/folder/extract
            if not out.exists() or not any(out.rglob("*")): safe_extract(dest,out)
        return
    try:
        r=S.get(url,timeout=(CONNECT_TIMEOUT,READ_TIMEOUT),allow_redirects=True)
        r.raise_for_status()
        if html(r) or (kind=="zip" and not r.content.startswith(b"PK")) or (kind=="pdf" and not r.content.startswith(b"%PDF-")):
            p=note(folder,dataset,url,f"Unexpected content-type {r.headers.get('content-type')} from {r.url}")
            upsert({"dataset":dataset,"source_url":url,"effective_date":effective,
                    "status":"manual_download_required","local_path":str(p.relative_to(ROOT)),
                    "sha256":sha(p),"note":"CMS/CDC returned HTML/interstitial instead of expected file."})
            log(f"[MANUAL] {dataset}")
            return
        tmp=dest.with_suffix(dest.suffix+".part"); tmp.write_bytes(r.content); tmp.replace(dest)
        if extract and kind=="zip": safe_extract(dest,REF/folder/extract)
        upsert({"dataset":dataset,"source_url":r.url,"effective_date":effective,
                "status":"downloaded","local_path":str(dest.relative_to(ROOT)),
                "sha256":sha(dest),"note":""})
        log(f"[DONE] {dataset}")
    except Exception as e:
        p=note(folder,dataset,url,str(e))
        upsert({"dataset":dataset,"source_url":url,"effective_date":effective,
                "status":"failed","local_path":str(p.relative_to(ROOT)),
                "sha256":sha(p),"note":str(e)})
        log(f"[FAIL] {dataset}: {e}")

def find_link(page,terms):
    r=S.get(page,timeout=(CONNECT_TIMEOUT,READ_TIMEOUT)); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    for a in soup.find_all("a",href=True):
        txt=" ".join(a.stripped_strings).lower()
        if all(t.lower() in txt for t in terms):
            return urljoin(page,a["href"])
    raise RuntimeError(f"No link containing {terms}")

def anchored(dataset,page,terms,folder,effective,filename,kind="zip",extract=None):
    try:
        url=find_link(page,terms)
        direct(dataset,url,folder,effective,filename,kind,extract)
    except Exception as e:
        p=note(folder,dataset,page,str(e))
        upsert({"dataset":dataset,"source_url":page,"effective_date":effective,
                "status":"link_lookup_failed","local_path":str(p.relative_to(ROOT)),
                "sha256":sha(p),"note":str(e)})
        log(f"[LOOKUP FAIL] {dataset}: {e}")

ensure_manifest()

# Record already-downloaded items from the previous run.
already=[
("CMS PFS RVU26C July 2026", REF/"cpt"/"rvu26c-updated-06-30-2026.zip",
 "https://www.cms.gov/medicare/payment/fee-schedules/physician/pfs-relative-value-files/rvu26c","2026-07-01","zip"),
("ICD-10-CM April 2026 Code Descriptions", REF/"icd10cm"/"icd10cm-Code Descriptions-April-1-2026.zip",
 "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2026-update/","2026-04-01","zip"),
("ICD-10-CM April 2026 XML", REF/"icd10cm"/"icd10cm-April-1-2026-XML.zip",
 "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2026-update/","2026-04-01","zip"),
]
for ds,p,u,e,k in already:
    if valid(p,k):
        upsert({"dataset":ds,"source_url":u,"effective_date":e,"status":"already_present",
                "local_path":str(p.relative_to(ROOT)),"sha256":sha(p),
                "note":"Recovered from prior downloader run."})

jobs=[]
def add_direct(*args,**kwargs): jobs.append(("direct",args,kwargs))
def add_anchor(*args,**kwargs): jobs.append(("anchor",args,kwargs))

CDC="https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2026-update/"
add_direct("ICD-10-CM April 2026 Tables and Index",CDC+"icd10cm-table-and-index-April-1-2026.zip",
           "icd10cm","2026-04-01","icd10cm-table-and-index-April-1-2026.zip","zip","extracted")
add_direct("ICD-10-CM April 2026 Addenda",CDC+"icd10cm-addenda-April-1-2026.zip",
           "icd10cm","2026-04-01","icd10cm-addenda-April-1-2026.zip","zip","extracted")
add_direct("ICD-10-CM April 2026 Guidelines",CDC+"ICD-10-CM%20April%201%202026%20Guidelines%20Final.pdf",
           "icd10cm","2026-04-01","ICD-10-CM_April-1-2026_Guidelines.pdf","pdf",None)

ICD="https://www.cms.gov/medicare/coding-billing/icd-10-codes"
for ds,terms,fn,kind in [
("ICD-10-PCS April 2026 Codes File",["April 1, 2026","ICD-10-PCS","Codes File"],"icd10pcs_april_2026_codes.zip","zip"),
("ICD-10-PCS April 2026 Order File",["April 1, 2026","ICD-10-PCS","Order File"],"icd10pcs_april_2026_order_file.zip","zip"),
("ICD-10-PCS April 2026 Code Tables and Index",["April 1, 2026","ICD-10-PCS","Code Tables","Index"],"icd10pcs_april_2026_tables_index.zip","zip"),
("ICD-10-PCS April 2026 Addendum",["April 1, 2026","ICD-10-PCS","Addendum"],"icd10pcs_april_2026_addendum.zip","zip"),
("ICD-10-PCS April 2026 Conversion Table",["April 1, 2026","ICD-10-PCS","Conversion Table"],"icd10pcs_april_2026_conversion_table.zip","zip"),
("ICD-10-PCS April 2026 Guidelines",["April 1, 2026","Official","ICD-10-PCS","Coding Guidelines"],"icd10pcs_april_2026_guidelines.pdf","pdf"),
]:
    add_anchor(ds,ICD,terms,"icd10pcs","2026-04-01",fn,kind,"extracted" if kind=="zip" else None)

HCPCS="https://www.cms.gov/medicare/coding-billing/healthcare-common-procedure-system/quarterly-update"
add_anchor("HCPCS July 2026 Alpha-Numeric",HCPCS,["July 2026","Alpha-Numeric","HCPCS"],
           "hcpcs","2026-07-01","hcpcs_july_2026_alpha_numeric.zip","zip","extracted")

ADDON="https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-add-code-edits"
add_anchor("NCCI Add-On Code Edits July 1 2026",ADDON,["Add-On Code","07012026"],
           "ncci","2026-07-01","ncci_addon_codes_2026_07_01.zip","zip","addon_extracted")

POLICY="https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-policy-manual"
add_anchor("2026 Medicare NCCI Full Policy Manual",POLICY,["Full","Complete","Manual"],
           "rules","2026-01-01","2026_medicare_ncci_full_policy_manual.pdf","pdf",None)
add_anchor("2026 NCCI Chapter 4 Musculoskeletal System",POLICY,["Chapter 4","Musculoskeletal"],
           "rules","2026-01-01","2026_ncci_chapter_4_musculoskeletal.pdf","pdf",None)

# Discover NCCI Q3 PTP links.
PTP="https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-procedure-procedure-ptp-edits"
try:
    r=S.get(PTP,timeout=(CONNECT_TIMEOUT,READ_TIMEOUT)); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    idx=0
    for a in soup.find_all("a",href=True):
        txt=" ".join(a.stripped_strings)
        low=txt.lower()
        if ("v32.2" in low or "v322" in low) and ("practitioner" in low or "hospital" in low):
            idx+=1
            kind="practitioner" if "practitioner" in low else "hospital"
            add_direct(f"NCCI Q3 2026 {kind.title()} PTP Part {idx}",urljoin(PTP,a["href"]),
                       "ncci","2026-07-01",f"ncci_q3_2026_{kind}_ptp_part_{idx}.zip","zip",f"{kind}_ptp_extracted")
    if idx==0: raise RuntimeError("No v32.2/v322 Q3 2026 PTP links found")
except Exception as e:
    p=note("ncci","NCCI Q3 2026 PTP",PTP,str(e))
    upsert({"dataset":"NCCI Q3 2026 PTP","source_url":PTP,"effective_date":"2026-07-01",
            "status":"manual_download_required","local_path":str(p.relative_to(ROOT)),
            "sha256":sha(p),"note":str(e)})

# Discover MUE July 1 2026 practitioner and outpatient hospital.
MUE="https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-medically-unlikely-edit-mue-archive"
try:
    r=S.get(MUE,timeout=(CONNECT_TIMEOUT,READ_TIMEOUT)); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    cands=[]
    for a in soup.find_all("a",href=True):
        txt=" ".join(a.stripped_strings)
        if "Effective July 1, 2026" not in txt: continue
        ctx=[]
        n=a
        for _ in range(25):
            n=n.find_previous()
            if n is None: break
            if getattr(n,"name",None) in {"h2","h3","h4","strong","th"}:
                t=" ".join(n.stripped_strings)
                if t: ctx.append(t)
            if len(ctx)>=4: break
        cands.append((" | ".join(ctx).lower(),urljoin(MUE,a["href"])))
    for label,needles in [("practitioner",["practitioner"]),("outpatient_hospital",["facility outpatient","outpatient hospital"])]:
        hit=next((u for c,u in cands if any(n in c for n in needles)),None)
        if not hit: raise RuntimeError(f"Could not identify {label} July 1 2026 MUE")
        add_direct(f"MUE July 1 2026 {label}",hit,"mue","2026-07-01",
                   f"mue_2026_07_01_{label}.zip","zip",f"{label}_extracted")
except Exception as e:
    p=note("mue","MUE July 1 2026",MUE,str(e))
    upsert({"dataset":"MUE July 1 2026","source_url":MUE,"effective_date":"2026-07-01",
            "status":"manual_download_required","local_path":str(p.relative_to(ROOT)),
            "sha256":sha(p),"note":str(e)})

log(f"\nStarting {len(jobs)} remaining jobs with {MAX_WORKERS} workers...\n")
def run(job):
    mode,args,kwargs=job
    return direct(*args,**kwargs) if mode=="direct" else anchored(*args,**kwargs)

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
    futs=[ex.submit(run,j) for j in jobs]
    done=0
    for f in as_completed(futs):
        done+=1
        try: f.result()
        except Exception as e: log(f"[UNHANDLED] {e}")
        log(f"[PROGRESS] {done}/{len(futs)}")

rows=load_rows()
counts={}
for r in rows: counts[r["status"]]=counts.get(r["status"],0)+1
log("\n=== COMPLETE ===")
for k in sorted(counts): log(f"{k}: {counts[k]}")
log(f"Manifest: {MANIFEST}")
log("Safe to rerun: valid existing downloads will be skipped.")
