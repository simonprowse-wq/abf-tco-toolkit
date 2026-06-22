#!/usr/bin/env python3
"""
scrape_tcos.py
==============
Scrapes the Australian Border Force current Tariff Concession Orders (TCOs).

How it works (confirmed against the live site):
- The chapter index page (Tariff-concession-orders.aspx) has links with
  class="tariff-link" and a data-ch="NN" attribute for each HS chapter.
- Clicking one opens:
      /tariff-classification-subsite/Pages/TariffConcessionOrders.aspx?ch=NN
- That page returns a server-rendered HTML TABLE with columns:
      Tariff Classification | TCO Number | TCO description | Operative date | Decision date
  No JavaScript is needed to read the descriptions, so plain requests works.

Output (in ./out_tco/):
    tco_records.jsonl   <- one JSON object per TCO (best for feeding a program)
    tco_records.csv     <- same data as a spreadsheet
    raw/ch_NN.html      <- raw HTML per chapter, kept for auditing

Dependencies (already installed): requests, beautifulsoup4
    pip install requests beautifulsoup4

Note on currency: this table is the current per-chapter list, but for a legally
reliable decision the operative/decision dates and continued validity should be
confirmed against the weekly Tariff Concessions Gazette (or via a Tariff Advice).
The matching layer should treat these as candidates for confirmation, not final
determinations.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INDEX_URL = ("https://www.abf.gov.au/tariff-classification-subsite/Pages/"
             "Tariff-concession-orders.aspx")
CHAPTER_URL = ("https://www.abf.gov.au/tariff-classification-subsite/Pages/"
               "TariffConcessionOrders.aspx?ch={ch}")

OUT = Path("out_tco")
RAW = OUT / "raw"
REQUEST_DELAY_SECONDS = 1.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    "Accept-Language": "en-AU,en;q=0.9",
    "Referer": INDEX_URL,
}

# Fallback chapter list (used only if the index page can't be read).
FALLBACK_CHAPTERS = [
    15, 17, 22, 25, 27, 28, 29, 30, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42,
    43, 44, 45, 48, 49, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 62, 63, 64, 66,
    68, 69, 70, 71, 72, 73, 74, 75, 76, 79, 82, 83, 84, 85, 86, 87, 89, 90, 91,
    92, 93, 94, 95, 96,
]


# ---------------------------------------------------------------------------
# Step 1: get the list of chapter numbers
# ---------------------------------------------------------------------------
def get_chapters(session: requests.Session) -> list[int]:
    try:
        resp = session.get(INDEX_URL, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        chapters = []
        for a in soup.select("a.tariff-link[data-ch]"):
            try:
                chapters.append(int(a["data-ch"]))
            except (ValueError, KeyError):
                continue
        chapters = sorted(set(chapters))
        if chapters:
            return chapters
    except requests.RequestException as e:
        print(f"  ! could not read index page ({e}); using fallback list")
    return FALLBACK_CHAPTERS


# ---------------------------------------------------------------------------
# Step 2: parse one chapter page's TCO table
# ---------------------------------------------------------------------------
def parse_chapter(html: str, chapter: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict] = []

    for table in soup.find_all("table"):
        first_row = table.find("tr")
        if not first_row:
            continue
        headers = [c.get_text(" ", strip=True).lower()
                   for c in first_row.find_all(["th", "td"])]
        if not any("tco description" in h for h in headers):
            continue  # not the data table (SharePoint has layout tables too)

        def col(name: str):
            for i, h in enumerate(headers):
                if name in h:
                    return i
            return None

        ci_class = col("tariff classification")
        ci_num = col("tco number")
        ci_desc = col("tco description")
        ci_op = col("operative")
        ci_dec = col("decision")

        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue

            def text(i, keep_lines=False):
                if i is None or i >= len(cells):
                    return ""
                if keep_lines:
                    lines = [ln.rstrip()
                             for ln in cells[i].get_text("\n").splitlines()]
                    return "\n".join(ln for ln in lines if ln.strip())
                return cells[i].get_text(" ", strip=True)

            rec = {
                "chapter": chapter,
                "tariff_classification": text(ci_class),
                "tco_number": text(ci_num),
                "description": text(ci_desc, keep_lines=True),
                "operative_date": text(ci_op),
                "decision_date": text(ci_dec),
                "source_url": CHAPTER_URL.format(ch=chapter),
            }
            if rec["tariff_classification"] or rec["tco_number"]:
                records.append(rec)
        break  # we found and processed the data table

    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    chapters = get_chapters(session)
    print(f"Scraping {len(chapters)} chapters...\n")

    all_records: list[dict] = []
    for i, ch in enumerate(chapters, 1):
        url = CHAPTER_URL.format(ch=ch)
        try:
            resp = session.get(url, headers=HEADERS, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[{i}/{len(chapters)}] ch={ch}: FAILED ({e})")
            continue

        (RAW / f"ch_{ch}.html").write_text(resp.text)
        recs = parse_chapter(resp.text, ch)
        all_records.extend(recs)
        print(f"[{i}/{len(chapters)}] ch={ch}: {len(recs)} TCOs")
        time.sleep(REQUEST_DELAY_SECONDS)

    # Write JSONL
    with (OUT / "tco_records.jsonl").open("w") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Write CSV
    fields = ["chapter", "tariff_classification", "tco_number",
              "description", "operative_date", "decision_date", "source_url"]
    with (OUT / "tco_records.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_records)

    print(f"\nDone. {len(all_records)} TCO records from {len(chapters)} chapters.")
    print(f"  JSONL: {OUT/'tco_records.jsonl'}")
    print(f"  CSV:   {OUT/'tco_records.csv'}")
    print(f"  Raw:   {RAW}/ch_*.html")


if __name__ == "__main__":
    main()
