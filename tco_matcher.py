#!/usr/bin/env python3
"""
tco_matcher.py
==============
Stage 2+3 of the pipeline, deterministic (no LLM yet):

  Stage 2  retrieval   - restrict to TCOs keyed to / covering the good's HS code
  Stage 3  scoring     - rank those candidates by keyword overlap and surface
                         the conditions a human (or, later, an LLM) must confirm

IMPORTANT - what this is and isn't:
  This is recall-oriented TRIAGE. TCO eligibility legally requires the goods to
  *precisely* meet the description, including logical conditions ("ALL/ANY/BOTH
  of the following") and numeric thresholds ("NOT less than 250 gsm"). Keyword
  overlap CANNOT evaluate those. So the matcher ranks genuine candidates and
  lists the exact clauses left to verify. It never outputs an eligibility
  decision - that stays with a broker (or a later LLM stage feeding a broker).

Usage:
    from tco_matcher import TCOMatcher
    m = TCOMatcher.from_jsonl("out_tco/tco_normalised.jsonl")
    results = m.match("woven polyester fabric 380 gsm width 5m",
                      classification="5407.10.00", top_n=10)
    for r in results:
        print(r["score"], r["tco_number"], r["conditions_to_verify"])

Dependencies: standard library only. Requires tco_loader.py in the same folder.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tco_loader import TCO, TCODatabase, hs_digits

# Words that carry no discriminating power for overlap scoring. Note the
# logical operators (all/any/both/and/or/not) are stripped for OVERLAP, but
# detected separately as conditions to verify.
STOPWORDS = {
    "the", "a", "an", "of", "or", "and", "with", "without", "having", "being",
    "comprising", "consisting", "including", "all", "any", "both", "either",
    "following", "not", "less", "greater", "than", "but", "for", "on", "in",
    "to", "per", "is", "are", "be", "as", "at", "by", "from", "that", "which",
    "whether", "each", "such", "OR", "ie", "eg", "up", "put",
}

TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?", re.IGNORECASE)
# Clauses keyword matching cannot evaluate:
COND_LOGIC_RE = re.compile(
    r"\b(ALL|ANY|BOTH|EITHER)\s+of\s+the\s+following\b", re.IGNORECASE)
COND_NUMERIC_RE = re.compile(
    r"(NOT\s+(?:less|greater|exceeding|more)\s+than\s+[^;,)]+"
    r"|between\s+[^;,)]+|[\d.,]+\s*(?:mm|cm|m|gsm|g|kg|tex|decitex|denier|"
    r"micron|%|degrees|litre|ml|watt|volt|hz|mpa)\b[^;,)]*)", re.IGNORECASE)


def tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


def content_tokens(text: str) -> set[str]:
    return {t for t in tokens(text) if t not in STOPWORDS and len(t) > 1}


def head_terms(tco_description: str) -> set[str]:
    """TCO style puts the article name before the first comma
    (e.g. 'SEWING THREAD, being ANY...' -> {'sewing','thread'})."""
    head = (tco_description or "").split(",", 1)[0]
    return content_tokens(head)


def conditions_to_verify(tco_description: str) -> list[str]:
    out = []
    if COND_LOGIC_RE.search(tco_description or ""):
        out.append("Has 'ALL/ANY/BOTH of the following' logic - each sub-clause "
                   "must be checked against the goods.")
    for m in COND_NUMERIC_RE.findall(tco_description or ""):
        clause = m if isinstance(m, str) else m[0]
        clause = re.sub(r"\s+", " ", clause).strip()
        if clause:
            out.append(f"Numeric/threshold: {clause}")
    # dedupe, keep order
    seen, deduped = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    return deduped


class TCOMatcher:
    def __init__(self, db: TCODatabase):
        self.db = db

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "TCOMatcher":
        records = []
        with open(path) as f:
            for line in f:
                if line.strip():
                    records.append(TCO(**json.loads(line)))
        return cls(TCODatabase(records))

    def _score(self, good_tokens: set[str], tco: TCO) -> dict:
        tco_content = content_tokens(tco.description)
        head = head_terms(tco.description)

        if not tco_content:
            return {"score": 0.0}

        matched = sorted(tco_content & good_tokens)
        missing = sorted(tco_content - good_tokens)
        coverage = len(matched) / len(tco_content)
        head_match = (len(head & good_tokens) / len(head)) if head else 0.0

        # Head noun (the article itself) is decisive: if it doesn't match, this
        # is almost certainly the wrong TCO regardless of incidental overlap.
        score = round(0.6 * head_match + 0.4 * coverage, 4)

        return {
            "score": score,
            "head_match": round(head_match, 3),
            "coverage": round(coverage, 3),
            "matched_terms": matched,
            "missing_terms": missing,
            "conditions_to_verify": conditions_to_verify(tco.description),
        }

    def match(self, good_description: str, classification: str | None = None,
              top_n: int = 10, min_score: float = 0.0) -> list[dict]:
        good_tok = content_tokens(good_description)

        # Stage 2: retrieval. With a classification we restrict to the legally
        # relevant set; without one we fall back to scanning everything (lower
        # precision - a classification should really be supplied).
        if classification:
            pool = self.db.candidates_for(classification)
            pool = [(c, self.db_record(c)) for c in pool]
        else:
            pool = [(None, r) for r in self.db.records]

        scored = []
        for meta, rec in pool:
            s = self._score(good_tok, rec)
            if s["score"] < min_score:
                continue
            row = {
                "score": s["score"],
                "head_match": s.get("head_match"),
                "coverage": s.get("coverage"),
                "tariff_classification": rec.tariff_classification,
                "tco_number": rec.tco_number,
                "match_level": meta["match_level"] if meta else "unfiltered",
                "description": rec.description_oneline,
                "matched_terms": s.get("matched_terms", []),
                "missing_terms": s.get("missing_terms", []),
                "conditions_to_verify": s.get("conditions_to_verify", []),
                "operative_date": rec.operative_date,
                "decision_date": rec.decision_date,
            }
            scored.append(row)

        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:top_n]

    def db_record(self, candidate_dict: dict) -> TCO:
        """Rehydrate a TCO object from a candidates_for() dict."""
        return TCO(
            chapter=candidate_dict["chapter"],
            tariff_classification=candidate_dict["tariff_classification"],
            hs_key=candidate_dict["hs_key"],
            tco_number=candidate_dict["tco_number"],
            tco_key=candidate_dict["tco_key"],
            tco_number_variants=candidate_dict["tco_number_variants"],
            description=candidate_dict["description"],
            description_oneline=candidate_dict["description_oneline"],
            operative_date=candidate_dict["operative_date"],
            decision_date=candidate_dict["decision_date"],
            source_url=candidate_dict["source_url"],
        )


def _print_results(title: str, results: list[dict]) -> None:
    print(f"\n=== {title} ===")
    if not results:
        print("  (no candidates)")
        return
    for r in results:
        print(f"\n  score={r['score']:.3f} (head={r['head_match']}, "
              f"coverage={r['coverage']})  [{r['match_level']}]")
        print(f"  TCO {r['tco_number']}  {r['tariff_classification']}")
        print(f"  {r['description']}")
        if r["missing_terms"]:
            print(f"  terms not found in goods: {', '.join(r['missing_terms'][:12])}")
        for c in r["conditions_to_verify"]:
            print(f"    VERIFY: {c}")


if __name__ == "__main__":
    m = TCOMatcher.from_jsonl("out_tco/tco_normalised.jsonl")

    # Example 1: a good with a classification (the recommended path)
    _print_results(
        "woven polyester fabric, 380 gsm, width 5m  [class 5407.10.00]",
        m.match("woven polyester fabric 380 gsm width 5 metres",
                classification="5407.10.00", top_n=3))

    # Example 2: sewing thread, coarser-level TCOs should surface too
    _print_results(
        "polyester core spun sewing thread  [class 5401.10.00]",
        m.match("polyester core spun sewing threads",
                classification="5401.10.00", top_n=3))
