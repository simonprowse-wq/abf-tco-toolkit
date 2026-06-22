# ABF Tariff Concession Order (TCO) Toolkit

A small Python pipeline for working with Australian Border Force (ABF) Tariff
Concession Orders. It scrapes the publicly published TCO data, normalises it
into a structured corpus, matches imported goods against candidate TCOs, and
tracks weekly Gazette changes (made / refused / revoked / applications) so that
revoked or soon-to-be-revoked orders are filtered out of results.

> **Disclaimer:** This is a tool to *assist* with identifying candidate TCOs.
> It does not determine duty liability or TCO eligibility. A TCO claim requires
> the goods to be classifiable to the relevant tariff line and to *precisely*
> meet the order's wording — a judgement that should be confirmed by a licensed
> customs broker. Always verify against the current ABF data and the Gazette.

## Pipeline

```
scrape_tcos.py      ->  out_tco/tco_records.csv        (all current TCOs, by chapter)
tco_loader.py       ->  out_tco/tco_normalised.jsonl   (deduped, normalised, + SQLite)
gazette_scraper.py  ->  out_gazette/gazette_records.csv (weekly change log)
reconcile_tco.py    ->  pending / imminent-revocation / revoked views
tco_matcher.py      ->  ranks candidate TCOs for a good (revoked ones filtered out)
```

## Requirements

- Python 3.10+
- Install dependencies: `pip install -r requirements.txt`

## Usage

**1. Scrape the current TCOs** (≈63 chapter pages, about a minute):

```bash
python scrape_tcos.py
```

**2. Normalise into a clean corpus** (dedupes leading-zero duplicates, parses
dates, builds a queryable SQLite DB):

```bash
python tco_loader.py out_tco/tco_records.csv
```

**3. Scrape the weekly Gazette change log** for a given year:

```bash
python gazette_scraper.py 2026
```

**4. Reconcile the Gazette into actionable views** (genuinely-pending
applications, imminent revocations still in the corpus, recently revoked):

```bash
python reconcile_tco.py out_gazette/gazette_records.csv out_tco/tco_normalised.jsonl
```

**5. Match a good against candidate TCOs:**

```python
from tco_matcher import TCOMatcher

m = TCOMatcher.from_jsonl(
    "out_tco/tco_normalised.jsonl",
    gazette_csv="out_gazette/gazette_records.csv",   # enables revocation filtering
)
results = m.match("woven polyester fabric 380 gsm width 5m",
                  classification="5407.10.00", top_n=10)
for r in results:
    print(r["score"], r["tco_number"], r["revocation_status"], r["description"])
```

Each result includes a relevance `score`, the real `tco_number`,
`matched_terms` / `missing_terms`, `conditions_to_verify` (numeric thresholds
and AND/OR logic a human must confirm), and `revocation_status`.

## How matching works

1. **Classification** — supply the good's HS code (ideally from the import
   declaration). Matching is restricted to TCOs keyed to that code or to a
   coarser code that covers it.
2. **Retrieval** — pure data lookup against the corpus, so the model/keyword
   step can only ever see real TCOs (no hallucinated orders).
3. **Scoring** — keyword overlap weighted toward the head noun, with numeric
   and logical conditions surfaced as items to verify. This is **triage, not
   adjudication**: it ranks candidates for confirmation, it does not decide
   eligibility.

Revoked TCOs (per the Gazette) are excluded from results by default;
intention-to-revoke TCOs are kept but flagged.

## Data currency

The per-chapter tables are ABF's current list, but the Gazette is the authority
on revocation timing and can be more current than the consolidated pages.
Re-run the scrapers periodically (the Gazette publishes each Wednesday) and
treat anything the Gazette reports as revoked as not claimable, regardless of
whether it still appears in the chapter tables.

## A note on data and licensing

The scraped data is published by the Australian Border Force (Commonwealth of
Australia). Before committing or redistributing any scraped data in this
repository, check the applicable copyright/licence terms on the ABF website.
By default this repo's `.gitignore` excludes the scraped output directories.
