#!/usr/bin/env python3
"""Deliberately dumb name-only screening baseline (stdlib only).

Resolves a customer via account_ref / login_handle / email, then decides
SAME_ENTITY only when hit.name equals a customer full_name after lowercase+strip.
No accent folding, no fuzzy matching — a harsh demo foil for SNIFF.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Dict, Iterable, List, Optional


def load_jsonl(path: str) -> List[dict]:
    rows: List[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def norm_name(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def build_indexes(data_dir: str):
    alerts = {a["alert_id"]: a for a in load_jsonl(os.path.join(data_dir, "alerts.jsonl"))}
    hits = load_jsonl(os.path.join(data_dir, "hits.jsonl"))
    customers = {c["record_id"]: c for c in load_jsonl(os.path.join(data_dir, "customers.jsonl"))}

    acc_by_id: Dict[str, List[dict]] = defaultdict(list)
    acc_by_login: Dict[str, dict] = {}
    for a in load_jsonl(os.path.join(data_dir, "accounts.jsonl")):
        acc_by_id[a.get("account_id")].append(a)
        lh = a.get("login_handle")
        if lh:
            # first wins; joint accounts share account_id and are found via acc_by_id
            acc_by_login.setdefault(str(lh).lower(), a)

    cust_by_email: Dict[str, dict] = {}
    for c in customers.values():
        email = c.get("email")
        if email:
            cust_by_email.setdefault(str(email).lower(), c)

    return alerts, hits, acc_by_id, acc_by_login, customers, cust_by_email


def resolve_customers(
    alert: dict,
    acc_by_id: Dict[str, List[dict]],
    acc_by_login: Dict[str, dict],
    customers: Dict[str, dict],
    cust_by_email: Dict[str, dict],
) -> List[dict]:
    """Return customer records linked to the alert (0..N). Joint accounts return all holders."""
    account_ref = alert.get("account_ref")
    if account_ref:
        out: List[dict] = []
        seen = set()
        for acc in acc_by_id.get(account_ref, []):
            cid = acc.get("customer_id")
            if cid and cid not in seen and cid in customers:
                seen.add(cid)
                out.append(customers[cid])
        return out

    login_handle = alert.get("login_handle")
    if login_handle:
        acc = acc_by_login.get(str(login_handle).lower())
        if acc:
            cid = acc.get("customer_id")
            if cid and cid in customers:
                return [customers[cid]]
        return []

    email = alert.get("email")
    if email:
        c = cust_by_email.get(str(email).lower())
        return [c] if c else []

    return []


def decide_hit(hit: dict, customers: List[dict]) -> dict:
    hit_id = hit.get("hit_id")
    alert_id = hit.get("alert_id")
    hit_name = norm_name(hit.get("name"))

    if not customers:
        return {
            "hit_id": hit_id,
            "alert_id": alert_id,
            "decision": "DIFFERENT_ENTITY",
            "reason_code": "NO_CUSTOMER",
            "customer_record_id": None,
            "reason": "No customer could be resolved from the alert, so the baseline clears the hit.",
            "evidence": [],
        }

    for c in customers:
        if norm_name(c.get("full_name")) == hit_name and hit_name:
            return {
                "hit_id": hit_id,
                "alert_id": alert_id,
                "decision": "SAME_ENTITY",
                "reason_code": "NAME_EXACT",
                "customer_record_id": c.get("record_id"),
                "reason": f"Hit name equals customer full_name after lowercase+strip ({c.get('full_name')}).",
                "evidence": [c.get("record_id")],
            }

    first = customers[0]
    return {
        "hit_id": hit_id,
        "alert_id": alert_id,
        "decision": "DIFFERENT_ENTITY",
        "reason_code": "NAME_MISMATCH",
        "customer_record_id": first.get("record_id"),
        "reason": "Hit name does not exactly equal any linked customer full_name (lowercase+strip only).",
        "evidence": [c.get("record_id") for c in customers if c.get("record_id")],
    }


def score_against_labels(preds: Dict[str, dict], labels_path: str) -> None:
    labels = load_jsonl(labels_path)
    n = len(labels)
    ok = 0
    wrongful_clears = 0  # true SAME -> predicted DIFFERENT
    false_confirms = 0  # true DIFFERENT/REVIEW -> predicted SAME

    for lab in labels:
        hid = lab["hit_id"]
        true = lab["decision"]
        pred = preds.get(hid, {}).get("decision", "MISSING")
        if pred == true:
            ok += 1
        if true == "SAME_ENTITY" and pred == "DIFFERENT_ENTITY":
            wrongful_clears += 1
        if true in ("DIFFERENT_ENTITY", "REVIEW") and pred == "SAME_ENTITY":
            false_confirms += 1

    print(f"decision accuracy {ok}/{n}")
    print(f"wrongful clears (true SAME → predicted DIFFERENT) {wrongful_clears}")
    print(f"false confirms (true DIFFERENT/REVIEW → SAME) {false_confirms}")
    print(
        f"Name-only matching gets {ok} of {n} right and wrongly clears {wrongful_clears} real matches."
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Name-only screening baseline (harsh exact match).")
    p.add_argument("--data", required=True, help="Path to screening data folder (alerts/hits/customers/accounts).")
    p.add_argument("--out", required=True, help="Output JSONL path.")
    p.add_argument("--labels", default=None, help="Optional practice_labels.jsonl for accuracy report.")
    args = p.parse_args(list(argv) if argv is not None else None)

    alerts, hits, acc_by_id, acc_by_login, customers, cust_by_email = build_indexes(args.data)

    rows: List[dict] = []
    preds: Dict[str, dict] = {}
    for hit in sorted(hits, key=lambda x: (x.get("alert_id") or "", x.get("hit_id") or "")):
        alert = alerts.get(hit.get("alert_id"), {})
        custs = resolve_customers(alert, acc_by_id, acc_by_login, customers, cust_by_email)
        row = decide_hit(hit, custs)
        rows.append(row)
        if row.get("hit_id"):
            preds[row["hit_id"]] = row

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    if args.labels:
        score_against_labels(preds, args.labels)

    return 0


if __name__ == "__main__":
    sys.exit(main())
