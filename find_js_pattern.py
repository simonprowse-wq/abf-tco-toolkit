#!/usr/bin/env python3
"""
find_js_pattern.py
==================
Reads the already-saved page.html and hunts for the JavaScript that turns a
chapter's data-ch number into a real document URL. Prints context around any
likely tokens so we can read off the URL template.

Run:  python find_js_pattern.py
(No network needed — it only reads the local page.html.)
"""

import re

with open("page.html", "r", errors="ignore") as f:
    html = f.read()

# Tokens that are likely to sit near the URL-building logic.
TOKENS = [
    "data-ch", "dataCh", "dataset.ch", ".ch", "'ch'", '"ch"',
    "concession", "Concession",
    ".pdf", ".aspx",
    "tariff-classification-subsite", "tariff-concessions-system-subsite",
    "/files/", "Gazette",
    ".attr(", ".data(", "window.open", "window.location", "location.href",
    "function", "var url", "let url", "href =",
]

WINDOW = 300  # characters of context on each side
seen = set()

for token in TOKENS:
    for m in re.finditer(re.escape(token), html):
        start = max(0, m.start() - WINDOW)
        end = min(len(html), m.end() + WINDOW)
        snippet = html[start:end]
        # Only show snippets that look JS/URL-ish, and dedupe.
        if not any(h in snippet.lower() for h in
                   ("http", ".pdf", ".aspx", "url", "ch", "concession", "files")):
            continue
        key = snippet[:120]
        if key in seen:
            continue
        seen.add(key)
        cleaned = re.sub(r"\s+", " ", snippet).strip()
        print(f"\n--- near {token!r} ---")
        print(cleaned)

print("\n\n=== Any script blocks mentioning 'ch' and a URL ===")
for script in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE):
    if ("ch" in script.lower()
            and any(t in script.lower() for t in ("http", ".pdf", ".aspx", "url", "concession", "files"))):
        cleaned = re.sub(r"\s+", " ", script).strip()
        # cap each script so the terminal isn't flooded
        print("\n--- script block (first 1200 chars) ---")
        print(cleaned[:1200])
