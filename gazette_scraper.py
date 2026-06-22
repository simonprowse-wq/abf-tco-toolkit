#!/usr/bin/env python3
"""
gazette_scraper.py
==================
Scrapes the weekly Commonwealth of Australia Tariff Concessions Gazette (PDF),
which is the CHANGE LOG for TCOs: new applications, orders Made, Refused,
Revoked, and Intentions to Revoke.

This is a SEPARATE feed from the consolidated per-chapter corpus (scrape_tcos.py).
Use it for two things the consolidated list can't give you:
  1. Currency / revocation checks - flag corpus TCOs that have been revoked or
     are flagged for revocation.
  2. Forward-looking alerts - pending Applications and Intentions to Revoke that
     aren't yet reflected in the current-state tables.

The `TC` reference in a Gazette record (e.g. 25102112) is the same identifier as
`tco_number` in the corpus, so revocations link straight back.

Gazette URL pattern (confirmed):
    https://www.abf.gov.au/tariff-concessions-system-subsite/Gazettes/tc-YY-NN.pdf
    YY = two-digit year, NN = two-digit issue number (roughly weekly).

Output (./out_gazette/):
    gazette_records.csv / .jsonl  - one row per change, with a `status` field
    raw/tc-YY-NN.pdf              - downloaded source PDFs

Dependencies (already installed): requests, pdfplumber
    pip install requests pdfplumber

NOTE: this parser targets the MODERN Gazette layout (roughly 2015+). Very old
editions used a different table format and may need tweaks.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from pathlib import Path

import requests

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

GAZETTE_URL = ("https://www.abf.gov.au/tariff-concessions-system-subsite/"
               "Gazettes/tc-{yy:02d}-{nn:02d}.pdf")
OUT = Path("out_gazette")
RAW = OUT / "raw"
REQUEST_DELAY_SECONDS = 1.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
    "Referer": ("https://www.abf.gov.au/importing-exporting-and-manufacturing/"
                "tariff-concessions-system"),
}

# --- parsing patterns -------------------------------------------------------
CLASS_START_RE = re.compile(r"^(\d{4}\.\d{2}(?:\.\d{2})?)\s+(.*)$")
OP_TC_RE = re.compile(
    r"Op\.?\s*(\d{2}\.\d{2}\.\d{2,4})"
    r"(?:\s*Dec\.?\s*date\s*(\d{2}\.\d{2}\.\d{2,4}))?"
    r".*?TC\s*(\d{6,8})", re.IGNORECASE)
GAZETTE_DATE_RE = re.compile(
    r"No\.?\s*TC\s*\d{2}/\d{2},\s*\w+,\s*(\d{1,2}\s+\w+\s+\d{4})")

NOISE_RE = re.compile("|".join([
    r"Commonwealth of Australia Gazette", r"^No\s+TC\s+\d", r"^Published by",
    r"Description of Goods including", r"Customs Tariff Classification",
    r"^THE TABLE$", r"Continued (on next|from previous) page",
    r"^\d+$", r"^5%$", r"^50$", r"©Commonwealth", r"^ISSN", r"^Cat\. No\.",
    r"^Contact", r"tarcon@abf", r"Objections to the making",
    r"Australian manufacturers who wish", r"Submissions must be lodged",
    r"^The operative date", r"To assist local manufacturers",
    r"NOTICE PURSUANT TO SECTION", r"^CUSTOMS ACT 1901", r"Please note",
    r"next Gazette", r"^TCO Applications", r"^TCOs (Made|Refused|Revoked)",
    r"In accordance with", r"^The Chief Executive", r"In transit provisions",
]), re.IGNORECASE)


def detect_section(line: str) -> str | None:
    u = line.upper()
    if "NOTICE PURSUANT" not in u and "TARIFF CONCESSION ORDER" not in u:
        return None
    if "REFUSED" in u:
        return "refused"
    if "REVOKED" in u:
        return "revoked"
    if "INTENTION" in u and "REVOKE" in u:
        return "intention_to_revoke"
    if "INTENDED" in u and "REVOK" in u:
        return "intention_to_revoke"
    if "APPLICATIONS" in u and ("MADE FOR" in u or "LODGED" in u):
        return "application"
    if "ORDERS MADE" in u:
        return "made"
    return None


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_gazette(text: str, gazette_id: str) -> list[dict]:
    gd = GAZETTE_DATE_RE.search(text)
    gazette_date = gd.group(1) if gd else None

    records: list[dict] = []
    status: str | None = None
    cur: dict | None = None

    def push():
        nonlocal cur
        if cur and cur.get("tco_reference"):
            cur["description"] = clean(" ".join(cur.pop("_desc")))
            for k in ("_done", "_cap"):
                cur.pop(k, None)
            records.append(cur)
        cur = None

    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue

        sec = detect_section(s)
        if sec:
            push()
            status = sec
            continue
        if status is None:
            continue

        mcls = CLASS_START_RE.match(s)
        # Only treat as a new record start if not actually an "Op. ..." line
        if mcls and not s.lower().startswith("op."):
            push()
            rest = mcls.group(2).strip()
            cur = {
                "gazette": gazette_id, "gazette_date": gazette_date,
                "status": status, "tariff_classification": mcls.group(1),
                "tco_reference": None, "operative_date": None,
                "decision_date": None, "applicant": None,
                "stated_use": None, "reason": None,
                "_desc": [rest] if rest else [], "_done": False, "_cap": None,
            }
            continue
        if cur is None:
            continue

        m = OP_TC_RE.search(s)
        if m:
            cur["operative_date"] = m.group(1)
            cur["decision_date"] = m.group(2)
            cur["tco_reference"] = m.group(3)
            cur["_done"] = True
            continue

        low = s.lower()
        if low.startswith("stated use"):
            cur["_cap"] = "stated_use"
            cur["stated_use"] = s.split(":", 1)[1].strip() if ":" in s else ""
            continue
        if low.startswith("applicant"):
            val = s.split(":", 1)[1].strip() if ":" in s else ""
            cur["applicant"] = val
            cur["_cap"] = "applicant" if not val else None
            continue
        if low.startswith("reason"):
            cur["_cap"] = "reason"
            cur["reason"] = s.split(":", 1)[1].strip() if ":" in s else ""
            continue

        if NOISE_RE.search(s):
            continue

        if not cur["_done"]:
            cur["_desc"].append(s)
        else:
            cap = cur.get("_cap")
            if cap == "stated_use":
                cur["stated_use"] = clean((cur["stated_use"] or "") + " " + s)
            elif cap == "reason":
                cur["reason"] = clean((cur["reason"] or "") + " " + s)
            elif cap == "applicant" and not cur["applicant"]:
                cur["applicant"] = s
                cur["_cap"] = None

    push()
    return records


def extract_pdf_text(pdf_bytes: bytes) -> str:
    if pdfplumber is None:
        raise RuntimeError("pdfplumber not installed")
    chunks = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def fetch_gazette(session: requests.Session, year: int, issue: int):
    yy = year % 100
    url = GAZETTE_URL.format(yy=yy, nn=issue)
    try:
        resp = session.get(url, headers=HEADERS, timeout=120)
    except requests.RequestException:
        return None
    if resp.status_code != 200 or not resp.content[:4] == b"%PDF":
        return None
    return url, resp.content


def scrape_year(session: requests.Session, year: int,
                start: int = 1, end: int = 53,
                stop_after_misses: int = 6) -> list[dict]:
    yy = year % 100
    all_recs: list[dict] = []
    misses = 0
    found_any = False
    for nn in range(start, end + 1):
        got = fetch_gazette(session, year, nn)
        if got is None:
            misses += 1
            if found_any and misses >= stop_after_misses:
                break
            continue
        misses = 0
        found_any = True
        url, content = got
        gid = f"tc-{yy:02d}-{nn:02d}"
        (RAW / f"{gid}.pdf").write_bytes(content)
        try:
            recs = parse_gazette(extract_pdf_text(content), gid)
        except Exception as e:
            print(f"  ! {gid}: parse failed ({e})")
            recs = []
        all_recs.extend(recs)
        print(f"  {gid}: {len(recs)} records")
        time.sleep(REQUEST_DELAY_SECONDS)
    return all_recs


def flag_corpus_revocations(gazette_records: list[dict],
                            corpus_jsonl: str | Path) -> list[dict]:
    """Return corpus TCOs that appear as Revoked / Intention-to-Revoke."""
    revoked = {r["tco_reference"].lstrip("0")
               for r in gazette_records
               if r["status"] in ("revoked", "intention_to_revoke")
               and r.get("tco_reference")}
    hits = []
    with open(corpus_jsonl) as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("tco_key", "").lstrip("0") in revoked:
                hits.append(rec)
    return hits


def write_outputs(records: list[dict]) -> None:
    with (OUT / "gazette_records.jsonl").open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    fields = ["gazette", "gazette_date", "status", "tariff_classification",
              "tco_reference", "operative_date", "decision_date",
              "applicant", "stated_use", "reason", "description"]
    with (OUT / "gazette_records.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k, "") for k in fields})


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    session = requests.Session()
    print(f"Scraping Gazettes for {year}...")
    records = scrape_year(session, year)
    write_outputs(records)

    by_status: dict[str, int] = {}
    for r in records:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    print(f"\nDone. {len(records)} records: {by_status}")
    print(f"  -> {OUT/'gazette_records.csv'}")
    print(f"  -> {OUT/'gazette_records.jsonl'}")

    corpus = Path("out_tco/tco_normalised.jsonl")
    if corpus.exists():
        flagged = flag_corpus_revocations(records, corpus)
        print(f"\nCorpus TCOs flagged revoked / intention-to-revoke: {len(flagged)}")
        for h in flagged[:10]:
            print(f"  {h['tco_number']}  {h['tariff_classification']}  "
                  f"{h['description_oneline'][:55]}")


if __name__ == "__main__":
    main()
