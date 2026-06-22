#!/usr/bin/env python3
"""
abf_tco_scraper.py
==================
Scrapes the Australian Border Force "Current Tariff Concession Orders" page,
follows each per-chapter document link, downloads it, and extracts the text.

Why this design:
- The TCO page is a SharePoint site. The chapter links must be pulled from the
  raw HTML <a> tags; a plain text/markdown extraction drops the real hrefs.
- The chapter documents are PDFs (the actual TCO descriptions live there, NOT
  on the "Working Tariff" classification page).
- TCO records are tabular and regular, so we attempt a best-effort parse into
  structured rows in addition to dumping raw text.

Output:
    out/
      raw/                 <- downloaded source files (.pdf / .html)
      text/                <- one .txt per chapter
      tco_corpus.txt       <- everything concatenated (for quick inspection)
      tco_records.jsonl    <- best-effort structured records (TUNE the regex
                              after you eyeball real output)

Dependencies:
    pip install requests beautifulsoup4 pdfplumber

Notes:
- Be polite: this throttles requests. Government data is public, but don't hammer it.
- The structured parser is a STARTING POINT. PDF layout varies by chapter, so
  inspect out/text/*.txt and adjust extract_records() to match what you see.
"""

from __future__ import annotations  # lets "X | None" type hints work on Python 3.9

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # text extraction from PDFs will be skipped with a warning

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TCO_INDEX_URL = (
    "https://www.abf.gov.au/tariff-classification-subsite/Pages/"
    "Tariff-concession-orders.aspx"
)
OUT = Path("out")
RAW = OUT / "raw"
TEXT = OUT / "text"
REQUEST_DELAY_SECONDS = 1.5          # politeness throttle between downloads
HEADERS = {
    # The ABF SharePoint server returns 403 for non-browser User-Agents,
    # so we present a realistic browser header set.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/pdf,*/*;q=0.8"
    ),
    "Accept-Language": "en-AU,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
# Match anchors like "Chapter 84 - Tariff Concessions"
CHAPTER_LINK_RE = re.compile(r"chapter\s+\d+\s*-\s*tariff\s+concession", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Step 1: discover the per-chapter document links from the index page HTML
# ---------------------------------------------------------------------------
def discover_chapter_links(session: requests.Session) -> list[tuple[str, str]]:
    """Return list of (label, absolute_url) for each chapter TCO document."""
    resp = session.get(TCO_INDEX_URL, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        label = a.get_text(strip=True)
        href = a["href"].strip()
        if not label or href in ("", "#"):
            continue
        if CHAPTER_LINK_RE.search(label):
            abs_url = urljoin(TCO_INDEX_URL, href)
            if abs_url not in seen:
                seen.add(abs_url)
                links.append((label, abs_url))

    if not links:
        # Fallback: SharePoint sometimes routes links via document libraries.
        # Grab any link to a PDF on the same host as a backup so you still get data.
        host = urlparse(TCO_INDEX_URL).netloc
        for a in soup.find_all("a", href=True):
            abs_url = urljoin(TCO_INDEX_URL, a["href"])
            if abs_url.lower().endswith(".pdf") and urlparse(abs_url).netloc == host:
                if abs_url not in seen:
                    seen.add(abs_url)
                    links.append((a.get_text(strip=True) or abs_url, abs_url))

    return links


# ---------------------------------------------------------------------------
# Step 2: download each document
# ---------------------------------------------------------------------------
def safe_name(label: str, url: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").lower() or "chapter"
    ext = ".pdf" if ".pdf" in url.lower() else ".html"
    return f"{base}{ext}"


def download(session: requests.Session, url: str, dest: Path) -> Path | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ! download failed: {url} ({e})")
        return None
    dest.write_bytes(resp.content)
    return dest


# ---------------------------------------------------------------------------
# Step 3: extract text
# ---------------------------------------------------------------------------
def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        if pdfplumber is None:
            print("  ! pdfplumber not installed; cannot read PDF text")
            return ""
        chunks = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                chunks.append(page.extract_text() or "")
        return "\n".join(chunks)
    # HTML fallback
    soup = BeautifulSoup(path.read_text(errors="ignore"), "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


# ---------------------------------------------------------------------------
# Step 4: best-effort structured parse (TUNE THIS against real output)
# ---------------------------------------------------------------------------
# TCO rows look roughly like:
#   3926.90.90 CHAIR MATS, polypropylene, width NOT less than 914 mm ...
#   ... Op. 24.06.03 - TC 0307523
CLASSIFICATION_RE = re.compile(r"\b(\d{4}\.\d{2}\.\d{2})\b")
TC_REF_RE = re.compile(r"\bTC\s*([0-9]{6,8})\b")
OP_DATE_RE = re.compile(r"\bOp\.?\s*([0-9]{2}\.[0-9]{2}\.[0-9]{2,4})\b")


def extract_records(text: str, source: str) -> list[dict]:
    """Naive splitter: start a new record whenever a TC reference appears.
    Real chapter PDFs wrap descriptions across lines, so verify and adjust."""
    records = []
    # Normalise whitespace but keep it readable
    flat = re.sub(r"[ \t]+", " ", text)
    # Split into candidate blocks on the TC reference, keeping the reference.
    parts = re.split(r"(?=\bTC\s*[0-9]{6,8}\b)", flat)
    carry = ""
    for part in parts:
        block = (carry + " " + part).strip()
        tc = TC_REF_RE.search(block)
        cls = CLASSIFICATION_RE.search(block)
        if tc and cls:
            op = OP_DATE_RE.search(block)
            # description = text between classification and the Op./TC tail
            desc = block[cls.end():]
            desc = re.split(r"\bOp\.?\b", desc)[0].strip(" .-")
            records.append({
                "tariff_classification": cls.group(1),
                "description": desc,
                "operative_date": op.group(1) if op else None,
                "tc_reference": tc.group(1),
                "source": source,
            })
            carry = ""
        else:
            carry = block  # accumulate until we have both a class and a TC ref
    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    for d in (RAW, TEXT):
        d.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    print("Discovering chapter links...")
    links = discover_chapter_links(session)
    print(f"Found {len(links)} chapter documents.\n")
    if not links:
        print("No links found. Inspect the page HTML manually; SharePoint may "
              "be routing links through a document library or JS.")
        return

    corpus_parts: list[str] = []
    all_records: list[dict] = []

    for i, (label, url) in enumerate(links, 1):
        print(f"[{i}/{len(links)}] {label}")
        raw_path = RAW / safe_name(label, url)
        if not raw_path.exists():
            if download(session, url, raw_path) is None:
                continue
            time.sleep(REQUEST_DELAY_SECONDS)
        text = extract_text(raw_path)
        (TEXT / (raw_path.stem + ".txt")).write_text(text)
        corpus_parts.append(f"\n\n===== {label} =====\n{url}\n\n{text}")
        all_records.extend(extract_records(text, source=label))

    (OUT / "tco_corpus.txt").write_text("".join(corpus_parts))
    with (OUT / "tco_records.jsonl").open("w") as f:
        for rec in all_records:
            f.write(json.dumps(rec) + "\n")

    print(f"\nDone. {len(all_records)} candidate records parsed.")
    print(f"  Raw files:   {RAW}")
    print(f"  Per-chapter: {TEXT}")
    print(f"  Corpus:      {OUT/'tco_corpus.txt'}")
    print(f"  Records:     {OUT/'tco_records.jsonl'}")
    print("\nNext: eyeball out/text/*.txt and tune extract_records() to the real layout.")


if __name__ == "__main__":
    main()
