#!/usr/bin/env python3
"""
tco_loader.py
=============
Loads the scraped tco_records.csv, normalises it, de-duplicates, and exposes a
classification-based candidate lookup that is the foundation of the match layer.

Design decisions (important for a compliance tool):
- The raw `tco_number` is preserved VERBATIM, because that is the identifier
  quoted on an import declaration and ABF publishes some numbers both with and
  without a leading zero. We do NOT overwrite it.
- For de-duplication and joining we add `tco_key` = the number with leading
  zeros stripped, so 614168 and 0614168 collapse to one logical order.
- Dates are parsed from dd/mm/YYYY to ISO (YYYY-MM-DD).
- `hs_key` = the tariff classification with dots removed, used for prefix-aware
  matching (a TCO keyed at a coarser level, e.g. 5401.10, covers a good
  classified to a finer code, e.g. 5401.10.00).

Outputs:
    tco_normalised.jsonl   <- clean records, one JSON per logical TCO
    tco.sqlite             <- queryable DB (table `tcos`, index on hs_key)

Lookup:
    db = TCODatabase.from_csv("out_tco/tco_records.csv")
    candidates = db.candidates_for("5402.46.00")
    # -> TCOs keyed to that code OR to a coarser code that covers it

Dependencies: standard library only (csv, json, sqlite3, datetime, re).
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path


def to_iso(d: str) -> str | None:
    d = (d or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(d, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def hs_digits(classification: str) -> str:
    """'5402.46.00' -> '54024600' (digits only)."""
    return re.sub(r"\D", "", classification or "")


def oneline(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()


@dataclass
class TCO:
    chapter: int
    tariff_classification: str
    hs_key: str
    tco_number: str                       # verbatim, as published (for declarations)
    tco_key: str                          # leading zeros stripped (for matching)
    tco_number_variants: list[str]        # every raw form seen for this logical TCO
    description: str                      # full text, line structure preserved
    description_oneline: str              # whitespace-collapsed, for search/display
    operative_date: str | None           # ISO
    decision_date: str | None            # ISO
    source_url: str


class TCODatabase:
    def __init__(self, records: list[TCO]):
        self.records = records
        # index by hs_key for fast lookup
        self._by_hs: dict[str, list[TCO]] = {}
        for r in records:
            self._by_hs.setdefault(r.hs_key, []).append(r)
        # sorted unique hs_keys for prefix scanning
        self._hs_keys = sorted(self._by_hs.keys())

    # -- construction --------------------------------------------------------
    @classmethod
    def from_csv(cls, path: str | Path) -> "TCODatabase":
        raw_rows = []
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                raw_rows.append(row)

        # group by (classification, zero-stripped number, description) to dedup
        groups: dict[tuple, dict] = {}
        for row in raw_rows:
            num = (row["tco_number"] or "").strip()
            key = (row["tariff_classification"].strip(),
                   num.lstrip("0") or "0",
                   oneline(row["description"]))
            g = groups.setdefault(key, {"variants": set(), "row": row})
            g["variants"].add(num)
            # prefer the longest raw form as the display value (usually zero-padded)
            if len(num) > len(g["row"]["tco_number"].strip()):
                g["row"] = row

        records: list[TCO] = []
        for (classification, numkey, _desc1), g in groups.items():
            row = g["row"]
            records.append(TCO(
                chapter=int(row["chapter"]),
                tariff_classification=classification,
                hs_key=hs_digits(classification),
                tco_number=row["tco_number"].strip(),
                tco_key=numkey,
                tco_number_variants=sorted(g["variants"]),
                description=row["description"],
                description_oneline=oneline(row["description"]),
                operative_date=to_iso(row["operative_date"]),
                decision_date=to_iso(row["decision_date"]),
                source_url=row["source_url"],
            ))
        return cls(records)

    # -- lookup --------------------------------------------------------------
    def candidates_for(self, classification: str) -> list[dict]:
        """Return TCOs that a good of the given classification could claim.

        A TCO is a candidate if it is keyed to the good's classification, OR to
        a COARSER classification that the good falls within (the good's hs_key
        starts with the TCO's hs_key). Each result is tagged with match_level.
        Final eligibility still requires the good to PRECISELY meet the TCO
        description - that is the job of the match layer / a broker, not this
        function.
        """
        good = hs_digits(classification)
        out = []
        for hk in self._hs_keys:
            if good == hk:
                level = "exact"
            elif good.startswith(hk) and len(hk) >= 4:
                level = f"covered_by_{len(hk)}digit"
            else:
                continue
            for r in self._by_hs[hk]:
                d = asdict(r)
                d["match_level"] = level
                out.append(d)
        return out

    # -- export --------------------------------------------------------------
    def write_jsonl(self, path: str | Path) -> None:
        with open(path, "w") as f:
            for r in self.records:
                f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    def write_sqlite(self, path: str | Path) -> None:
        if Path(path).exists():
            Path(path).unlink()
        con = sqlite3.connect(path)
        con.execute("""
            CREATE TABLE tcos (
                chapter INTEGER,
                tariff_classification TEXT,
                hs_key TEXT,
                tco_number TEXT,
                tco_key TEXT,
                tco_number_variants TEXT,
                description TEXT,
                description_oneline TEXT,
                operative_date TEXT,
                decision_date TEXT,
                source_url TEXT
            )""")
        con.executemany(
            "INSERT INTO tcos VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(r.chapter, r.tariff_classification, r.hs_key, r.tco_number,
              r.tco_key, json.dumps(r.tco_number_variants), r.description,
              r.description_oneline, r.operative_date, r.decision_date,
              r.source_url) for r in self.records])
        con.execute("CREATE INDEX idx_hs ON tcos(hs_key)")
        con.execute("CREATE INDEX idx_tcokey ON tcos(tco_key)")
        con.commit()
        con.close()


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "out_tco/tco_records.csv"
    db = TCODatabase.from_csv(src)
    out = Path("out_tco")
    out.mkdir(exist_ok=True)
    db.write_jsonl(out / "tco_normalised.jsonl")
    db.write_sqlite(out / "tco.sqlite")
    print(f"Loaded {len(db.records)} logical TCOs (after dedup).")
    print(f"  -> {out/'tco_normalised.jsonl'}")
    print(f"  -> {out/'tco.sqlite'}")
    # demo lookup
    demo = db.candidates_for("5402.46.00")
    print(f"\nDemo: candidates_for('5402.46.00') -> {len(demo)} candidate(s):")
    for c in demo[:5]:
        print(f"  [{c['match_level']}] {c['tariff_classification']} "
              f"TCO {c['tco_number']}: {c['description_oneline'][:60]}")
