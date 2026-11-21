#!/usr/bin/env python3
"""Wider wording-mutation safety test.

Copies the official dataset, paraphrases free text without changing facts,
runs system/run as a black box, and asserts:

    Zero SAME/REVIEW → DIFFERENT unsafe flips.

Protected (never mutated):
  - "According to …; Month DD, YYYY:" report lines
  - SOP listing phrases in search snippets / notes

The sidecar JSON holds original true facts for audit. The engine never sees it.

Usage:
  python3 harness/unseen_wording.py --data /path/to/dev [--out-dir /tmp/sniff-wording]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_RUN = ROOT / "system" / "run"

REPORT_LINE = re.compile(
    r"^According to .*?;\s*[A-Z][a-z]+\.? \d{1,2}, \d{4}\s*:",
    re.M,
)
LISTING_PHRASES = [
    "a sanctioned individual",
    "a politically exposed person",
    "the subject of enforcement action",
    "named in adverse media",
    "a state-owned enterprise official",
    "named on a watchlist",
]

# DOB phrasing paraphrases (fact-preserving wrappers around existing dates).
DOB_PARAPHRASE = [
    (re.compile(r"(?i)\bdate of birth\b"), "birth date"),
    (re.compile(r"(?i)\bd\.?o\.?b\.?\b"), "born on"),
    (re.compile(r"(?i)\bborn on\b"), "date of birth"),
    (re.compile(r"(?i)\bborn\b"), "DOB"),
    (re.compile(r"(?i)\bbirth date\b"), "born"),
]

ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
RESIDENCE = re.compile(
    r"(?i)\b(?:lives? in|resides? in|resident of|based in)\s+([A-Z][A-Za-z ]{1,40})"
)

# Synonym swaps for notes that are *already* failed/rejected. Never inject failure
# language into a successful note — that would remove identity evidence and change facts.
FAILED_SYNONYMS = [
    (re.compile(r"(?i)\brejected\b"), "declined"),
    (re.compile(r"(?i)\bdeclined\b"), "rejected"),
    (re.compile(r"(?i)\bfailed\b"), "unsuccessful"),
    (re.compile(r"(?i)\bunsuccessful\b"), "failed"),
    (re.compile(r"(?i)\bcould not\b"), "was unable to"),
    (re.compile(r"(?i)\bunable to\b"), "could not"),
    (re.compile(r"(?i)\bdid not pass\b"), "didn't pass"),
    (re.compile(r"(?i)\bdidn't pass\b"), "did not pass"),
    (re.compile(r"(?i)\bnot approved\b"), "refused"),
    (re.compile(r"(?i)\bunder review\b"), "pending"),
    (re.compile(r"(?i)\bpending\b"), "under review"),
]
_ALREADY_FAILED = re.compile(
    r"(?i)\b(?:not approved|rejected|declined|failed|unsuccessful|could not|couldn't|"
    r"unable to|did not pass|didn't pass|expired|pending|under review|refused|"
    r"invalid|mismatch|superseded|revoked)\b"
)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _protect_spans(text: str) -> Tuple[str, Dict[str, str]]:
    """Replace protected substrings with tokens so mutations cannot touch them."""
    holders: Dict[str, str] = {}
    out = text

    def stash(match: re.Match) -> str:
        key = f"__PROT_{len(holders)}__"
        holders[key] = match.group(0)
        return key

    out = REPORT_LINE.sub(stash, out)
    for phrase in LISTING_PHRASES:
        if phrase in out:
            key = f"__PROT_{len(holders)}__"
            holders[key] = phrase
            out = out.replace(phrase, key)
    return out, holders


def _restore(text: str, holders: Dict[str, str]) -> str:
    for key, val in holders.items():
        text = text.replace(key, val)
    return text


def _title_case_name_tokens(text: str) -> str:
    """Title-Case ALL-CAPS multi-word name-like spans (fact preserved, casing changes)."""

    def repl(m: re.Match) -> str:
        words = m.group(0).split()
        if len(words) < 2:
            return m.group(0)
        return " ".join(w.title() for w in words)

    return re.sub(r"\b([A-Z]{2,}(?:\s+[A-Z]{2,})+)\b", repl, text)


def _shuffle_paragraphs(text: str, rng: random.Random) -> str:
    parts = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) < 2:
        # single block: shuffle sentences lightly
        sents = re.split(r"(?<=[.!?])\s+", text)
        if len(sents) < 2:
            return text
        head, rest = sents[0], sents[1:]
        rng.shuffle(rest)
        return " ".join([head] + rest)
    first, rest = parts[0], parts[1:]
    rng.shuffle(rest)
    return "\n\n".join([first] + rest)


def _iso_to_mmdd(text: str, rng: random.Random) -> str:
    def repl(m: re.Match) -> str:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        # Only rewrite when day and month are both <= 12 so both readings exist.
        if int(mo) <= 12 and int(d) <= 12 and rng.random() < 0.5:
            return f"{mo}/{d}/{y}"
        return m.group(0)

    return ISO_DATE.sub(repl, text)


def _paraphrase_dob(text: str, rng: random.Random) -> str:
    out = text
    for pat, repl in DOB_PARAPHRASE:
        if pat.search(out) and rng.random() < 0.7:
            out = pat.sub(repl, out, count=1)
            break
    return out


def _residence_paraphrase(text: str, rng: random.Random) -> str:
    def repl(m: re.Match) -> str:
        place = m.group(1).strip().rstrip(".,;")
        year = 2010 + rng.randint(0, 10)
        forms = [
            f"based in {place} since {year}",
            f"has lived in {place} since {year}",
            f"resident in {place} (from {year})",
        ]
        return rng.choice(forms)

    return RESIDENCE.sub(repl, text, count=1)


def mutate_text(text: str, rng: random.Random, categories: Counter) -> str:
    if not text or not str(text).strip():
        return text
    protected, holders = _protect_spans(str(text))
    out = protected

    # Category applications (independent, lightly applied).
    before = out
    out = _paraphrase_dob(out, rng)
    if out != before:
        categories["dob_phrasing"] += 1

    before = out
    out = _title_case_name_tokens(out)
    if out != before:
        categories["title_case_names"] += 1

    before = out
    out = _residence_paraphrase(out, rng)
    if out != before:
        categories["residence_notes"] += 1

    before = out
    out = _iso_to_mmdd(out, rng)
    if out != before:
        categories["numeric_mmdd"] += 1

    before = out
    out = _shuffle_paragraphs(out, rng)
    if out != before:
        categories["shuffled_paragraphs"] += 1

    # Failed/rejected KYC wording: only paraphrase notes that already fail principle 4.
    if _ALREADY_FAILED.search(out) and rng.random() < 0.8:
        before = out
        pat, repl = rng.choice(FAILED_SYNONYMS)
        out2, n = pat.subn(repl, out, count=1)
        if n:
            out = out2
            categories["failed_kyc_wording"] += 1

    return _restore(out, holders)


def mutate_dataset(src: Path, dst: Path, seed: int = 7) -> Tuple[Dict[str, Any], Counter]:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    rng = random.Random(seed)
    categories: Counter = Counter()
    sidecar: Dict[str, Any] = {
        "seed": seed,
        "notes": {},
        "hits": {},
        "customers": {},
        "kyc": {},
        "search": {},
    }

    # notes
    notes_path = dst / "notes.jsonl"
    if notes_path.exists():
        notes = _read_jsonl(notes_path)
        for n in notes:
            nid = n.get("note_id")
            orig = n.get("text")
            sidecar["notes"][nid] = {"text": orig, "channel": n.get("channel")}
            if (n.get("channel") or "").lower() == "kyc":
                n["text"] = mutate_text(orig or "", rng, categories)
        _write_jsonl(notes_path, notes)

    # hit profile notes
    hits_path = dst / "hits.jsonl"
    if hits_path.exists():
        hits = _read_jsonl(hits_path)
        for h in hits:
            hid = h.get("hit_id")
            orig = h.get("profile_notes")
            sidecar["hits"][hid] = {
                "profile_notes": orig,
                "dobs": h.get("dobs"),
                "name": h.get("name"),
            }
            if orig:
                h["profile_notes"] = mutate_text(orig, rng, categories)
        _write_jsonl(hits_path, hits)

    # customer record DOBs written as MM/DD when ISO and ambiguous
    cust_path = dst / "customers.jsonl"
    if cust_path.exists():
        custs = _read_jsonl(cust_path)
        for c in custs:
            rid = c.get("record_id")
            orig = c.get("dob")
            sidecar["customers"][rid] = {"dob": orig, "full_name": c.get("full_name")}
            if isinstance(orig, str) and ISO_DATE.fullmatch(orig.strip()):
                m = ISO_DATE.fullmatch(orig.strip())
                y, mo, d = m.group(1), m.group(2), m.group(3)
                if int(mo) <= 12 and int(d) <= 12 and mo != d and rng.random() < 0.3:
                    c["dob"] = f"{mo}/{d}/{y}"
                    categories["numeric_mmdd"] += 1
            # Title Case preferred/full names lightly
            for field in ("full_name", "preferred_name"):
                val = c.get(field)
                if isinstance(val, str) and val.isupper() and " " in val and rng.random() < 0.4:
                    c[field] = val.title()
                    categories["title_case_names"] += 1
        _write_jsonl(cust_path, custs)

    # KYC verified_dob slash form
    kyc_path = dst / "kyc_checks.jsonl"
    if kyc_path.exists():
        checks = _read_jsonl(kyc_path)
        for k in checks:
            cid = k.get("check_id")
            orig = k.get("verified_dob")
            sidecar["kyc"][cid] = {
                "verified_dob": orig,
                "verified_name": k.get("verified_name"),
                "result": k.get("result"),
            }
            if isinstance(orig, str) and ISO_DATE.fullmatch(orig.strip()):
                m = ISO_DATE.fullmatch(orig.strip())
                y, mo, d = m.group(1), m.group(2), m.group(3)
                if int(mo) <= 12 and int(d) <= 12 and mo != d and rng.random() < 0.3:
                    k["verified_dob"] = f"{mo}/{d}/{y}"
                    categories["numeric_mmdd"] += 1
        _write_jsonl(kyc_path, checks)

    # search snippets
    search_path = dst / "search_results.jsonl"
    if search_path.exists():
        rows = _read_jsonl(search_path)
        for s in rows:
            sid = s.get("result_id") or s.get("id") or f"Q:{s.get('query')}"
            orig = s.get("snippet") or s.get("text")
            sidecar["search"][str(sid)] = {"snippet": orig}
            field = "snippet" if "snippet" in s else ("text" if "text" in s else None)
            if field and s.get(field):
                s[field] = mutate_text(s[field], rng, categories)
        _write_jsonl(search_path, rows)

    return sidecar, categories


def run_engine(data_dir: Path, out_path: Path) -> Dict[str, Dict[str, Any]]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(SYSTEM_RUN), str(data_dir), str(out_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"system/run failed ({proc.returncode}): {proc.stderr or proc.stdout}"
        )
    rows = {}
    with open(out_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            rows[r["hit_id"]] = r
    return rows


def compare(
    baseline: Dict[str, Dict[str, Any]],
    mutated: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    unsafe = []
    clear_to_review = []
    same_to_review = []
    retained = 0
    for hid, b in baseline.items():
        m = mutated.get(hid)
        if not m:
            continue
        bd, md = b["decision"], m["decision"]
        if bd == md and b.get("reason_code") == m.get("reason_code"):
            retained += 1
        if bd in ("SAME_ENTITY", "REVIEW") and md == "DIFFERENT_ENTITY":
            unsafe.append(
                {
                    "hit_id": hid,
                    "from": bd,
                    "from_reason": b.get("reason_code"),
                    "to": md,
                    "to_reason": m.get("reason_code"),
                }
            )
        if bd == "DIFFERENT_ENTITY" and md == "REVIEW":
            clear_to_review.append(hid)
        if bd == "SAME_ENTITY" and md == "REVIEW":
            same_to_review.append(hid)
    return {
        "unsafe_flips": unsafe,
        "unsafe_count": len(unsafe),
        "clears_lost_to_review": len(clear_to_review),
        "confirmations_lost_to_review": len(same_to_review),
        "safely_retained": retained,
        "clear_to_review_ids": clear_to_review,
        "same_to_review_ids": same_to_review,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, help="Official dataset folder")
    ap.add_argument("--out-dir", default="/tmp/sniff-unseen-wording")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)

    src = Path(args.data).resolve()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mut_dir = out_dir / "mutated_data"

    print(f"baseline run on {src} ...", flush=True)
    baseline = run_engine(src, out_dir / "baseline.jsonl")

    print(f"mutating copy -> {mut_dir} (seed={args.seed}) ...", flush=True)
    sidecar, categories = mutate_dataset(src, mut_dir, seed=args.seed)
    side_path = out_dir / "sidecar_true_facts.json"
    # Sidecar stays outside the data folder the engine reads.
    with open(side_path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f)  # compact; facts only for audit

    print("mutated run ...", flush=True)
    mutated = run_engine(mut_dir, out_dir / "mutated.jsonl")

    stats = compare(baseline, mutated)
    report = {
        "seed": args.seed,
        "baseline_hits": len(baseline),
        "mutated_hits": len(mutated),
        "mutation_categories": dict(categories),
        **{k: v for k, v in stats.items() if k != "clear_to_review_ids" and k != "same_to_review_ids"},
        "clear_to_review_sample": stats["clear_to_review_ids"][:20],
        "same_to_review_sample": stats["same_to_review_ids"][:20],
        "sidecar": str(side_path),
        "mutated_data": str(mut_dir),
    }
    report_path = out_dir / "wording_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print()
    print("=== unseen wording mutation report ===")
    print(f"hits: {len(baseline)}")
    print(f"safely retained (same decision+code): {stats['safely_retained']}")
    print(f"original clearances lost to REVIEW: {stats['clears_lost_to_review']}")
    print(f"original confirmations lost to REVIEW: {stats['confirmations_lost_to_review']}")
    print(f"unsafe SAME/REVIEW → DIFFERENT flips: {stats['unsafe_count']}")
    print(f"mutation category counts: {dict(categories)}")
    print(f"report: {report_path}")
    print(f"sidecar (engine never reads): {side_path}")

    if stats["unsafe_count"] != 0:
        print("FAIL: unsafe flips detected:", file=sys.stderr)
        for u in stats["unsafe_flips"][:20]:
            print(f"  {u}", file=sys.stderr)
        return 1
    print("PASS: 0 unsafe flips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
