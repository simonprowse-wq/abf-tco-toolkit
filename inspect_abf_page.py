#!/usr/bin/env python3
"""
inspect_abf_page.py
===================
Diagnostic: figures out HOW the ABF TCO page encodes its chapter links so we
know whether we can scrape them with plain HTTP or need a headless browser.

Run:  python inspect_abf_page.py

It saves the raw HTML to page.html and prints:
  - total <a> tag count (very low => page is JS-rendered)
  - every anchor whose text mentions "Chapter", with its href / onclick / data-*
  - any .pdf URLs found anywhere in the HTML (href, onclick, data attrs, scripts)
"""

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = ("https://www.abf.gov.au/tariff-classification-subsite/Pages/"
       "Tariff-concession-orders.aspx")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "application/pdf,*/*;q=0.8"),
    "Accept-Language": "en-AU,en;q=0.9",
}

resp = requests.get(URL, headers=HEADERS, timeout=60)
resp.raise_for_status()
html = resp.text

with open("page.html", "w") as f:
    f.write(html)
print(f"Saved raw HTML to page.html ({len(html):,} bytes)\n")

soup = BeautifulSoup(html, "html.parser")
anchors = soup.find_all("a")
print(f"Total <a> tags in static HTML: {len(anchors)}")
print("(If this is very low, the page builds its links with JavaScript.)\n")

print("=== Anchors whose text mentions 'Chapter' ===")
found_any = False
for a in anchors:
    text = a.get_text(strip=True)
    if "chapter" in text.lower():
        found_any = True
        attrs = {k: v for k, v in a.attrs.items()
                 if k in ("href", "onclick") or k.startswith("data-")}
        print(f"  text   : {text!r}")
        print(f"  attrs  : {attrs}")
        print()
if not found_any:
    print("  (none found as <a> tags)\n")

print("=== All .pdf references found anywhere in the HTML ===")
pdf_urls = sorted(set(re.findall(r"""['"]([^'"]+?\.pdf)['"]""", html, re.IGNORECASE)))
if pdf_urls:
    for u in pdf_urls:
        print(" ", urljoin(URL, u))
else:
    print("  (no .pdf URLs in the static HTML — links are loaded dynamically)")
