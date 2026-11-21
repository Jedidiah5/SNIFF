#!/usr/bin/env python3
"""ClearGuard Plan B — test-to-fail mutation harness.

Calls the engine as a black box:
  system/run <data_dir> <out_file>

Stdlib only. Never edits system/*.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from copy import deepcopy
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Tuple

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUN_BIN = os.path.join(REPO, "system", "run")
HARNESS_ROOT = "/tmp/clearguard-harness"

MUTATION_ORDER = [
    "name_variant",
    "remove_hit_dob",
    "verified_conflicting_dob",
    "unreliable_conflicting_dob",
    "duplicate_customer",
    "lookalike_customer",
    "cut_account_link",
]

# Mutations that must never turn a true SAME into DIFFERENT_ENTITY.
NO_WRONGFUL_CLEAR = {
    "name_variant",
    "remove_hit_dob",
    "unreliable_conflicting_dob",
    "duplicate_customer",
    "lookalike_customer",
    "cut_account_link",
}

BORN_AGE_SENTENCE = re.compile(
    r"(?is)(?:^|[.!?]\s+|[;\n]\s*)("
    r"[^.!?\n]*\b(?:"
    r"born|birth(?:ed)?|aged|ages?\b|"
    r"\d{1,3}\s*[- ]?\s*years?\s*[- ]?\s*old|"
    r"\d{1,3}-year-old|"
    r"years?\s+of\s+age"
    r")\b[^.!?\n]*"
    r")(?:[.!?])?"
)

# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: str, rows: List[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def find_jsonl(data_dir: str, *needles: str) -> str:
    """Return path to the first *.jsonl whose lowercased name contains a needle."""
    for fn in sorted(os.listdir(data_dir)):
        if not fn.endswith(".jsonl"):
            continue
        low = fn.lower()
        if any(n in low for n in needles):
            return os.path.join(data_dir, fn)
    raise FileNotFoundError(f"no jsonl matching {needles} in {data_dir}")


def load_name_variant_groups(data_dir: str) -> List[List[str]]:
    path = os.path.join(data_dir, "name_variants.json")
    if not os.path.isfile(path):
        return []
    try:
        obj = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    groups = []
    if isinstance(obj, dict) and "groups" in obj:
        for g in obj["groups"]:
            if isinstance(g, list) and all(isinstance(x, str) for x in g):
                groups.append(g)
    return groups


def run_engine(data_dir: str, out_file: str) -> Dict[str, dict]:
    os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
    subprocess.run([RUN_BIN, data_dir, out_file], check=True, cwd=REPO)
    return {r["hit_id"]: r for r in read_jsonl(out_file)}


def mut_id(prefix: str, hit_id: str, tag: str) -> str:
    """Deterministic short id: PREFIX- + 6 hex-ish chars from hit+tag."""
    raw = f"{hit_id}:{tag}".encode()
    h = 0
    for b in raw:
        h = (h * 131 + b) & 0xFFFFFF
    return f"{prefix}-{h:06X}"


def shift_dob(dob: Optional[str], years: int = 10) -> str:
    """Return dob string shifted by +/- years. Accepts YYYY, YYYY-MM, YYYY-MM-DD, DD/MM/YYYY."""
    if not dob:
        return f"{date.today().year - 40 - years}-01-01"
    s = str(dob).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y + years:04d}-{mo:02d}-{d:02d}"
    m = re.match(r"^(\d{4})-(\d{2})$", s)
    if m:
        return f"{int(m.group(1)) + years:04d}-{m.group(2)}"
    m = re.match(r"^(\d{4})$", s)
    if m:
        return f"{int(m.group(1)) + years:04d}"
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{d:02d}/{mo:02d}/{y + years:04d}"
    # fallback: prepend year shift marker
    return f"{date.today().year - 50}-06-15"


def strip_accents(s: str) -> str:
    nk = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nk if not unicodedata.combining(c))


# ---------------------------------------------------------------------------
# Dataset context for one working copy
# ---------------------------------------------------------------------------

class DataCtx:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.paths = {
            "hits": find_jsonl(data_dir, "hit"),
            "alerts": find_jsonl(data_dir, "alert"),
            "customers": find_jsonl(data_dir, "customer"),
            "accounts": find_jsonl(data_dir, "account"),
            "onboarding": find_jsonl(data_dir, "onboard"),
            "kyc": find_jsonl(data_dir, "kyc", "check", "identity"),
        }
        self.hits = read_jsonl(self.paths["hits"])
        self.alerts = read_jsonl(self.paths["alerts"])
        self.customers = read_jsonl(self.paths["customers"])
        self.accounts = read_jsonl(self.paths["accounts"])
        self.onboarding = read_jsonl(self.paths["onboarding"])
        self.kyc = read_jsonl(self.paths["kyc"])
        self.hit_by_id = {h["hit_id"]: h for h in self.hits}
        self.alert_by_id = {a["alert_id"]: a for a in self.alerts}
        self.cust_by_id = {c["record_id"]: c for c in self.customers}
        self.acc_by_id: Dict[str, List[dict]] = {}
        for a in self.accounts:
            self.acc_by_id.setdefault(a.get("account_id"), []).append(a)
        self.onb_by_acc = {o.get("account_id"): o for o in self.onboarding}
        self.onb_by_cust: Dict[str, List[dict]] = {}
        for o in self.onboarding:
            self.onb_by_cust.setdefault(o.get("customer_id"), []).append(o)
        self.variant_groups = load_name_variant_groups(data_dir)

    def alert_for_hit(self, hit_id: str) -> dict:
        h = self.hit_by_id[hit_id]
        aid = h.get("alert_id")
        if aid and aid in self.alert_by_id:
            return self.alert_by_id[aid]
        for a in self.alerts:
            if hit_id in (a.get("hit_ids") or []):
                return a
        raise KeyError(f"no alert for hit {hit_id}")

    def resolved_customer_ids(self, hit_id: str, hint_ids: Optional[List[str]] = None) -> List[str]:
        """Best-effort customer ids linked to this hit's alert."""
        if hint_ids:
            return [c for c in hint_ids if c and c != "AMBIGUOUS" and c in self.cust_by_id]
        alert = self.alert_for_hit(hit_id)
        seeds: List[str] = []
        aref = alert.get("account_ref")
        if aref:
            for row in self.acc_by_id.get(aref, []):
                cid = row.get("customer_id")
                if cid in self.cust_by_id:
                    seeds.append(cid)
            onb = self.onb_by_acc.get(aref)
            if onb and onb.get("customer_id") in self.cust_by_id:
                seeds.append(onb["customer_id"])
        if not seeds and alert.get("login_handle"):
            login = str(alert["login_handle"]).lower()
            for row in self.accounts:
                if str(row.get("login_handle") or "").lower() == login:
                    cid = row.get("customer_id")
                    if cid in self.cust_by_id:
                        seeds.append(cid)
        if not seeds and alert.get("email"):
            em = str(alert["email"]).lower()
            for c in self.customers:
                if str(c.get("email") or "").lower() == em:
                    seeds.append(c["record_id"])
        # unique preserve order
        seen, out = set(), []
        for s in seeds:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    def kyc_applicant_for(self, customer_ids: List[str], hit_id: str) -> Optional[str]:
        for cid in customer_ids:
            for o in self.onb_by_cust.get(cid, []):
                if o.get("kyc_applicant_id"):
                    return o["kyc_applicant_id"]
        alert = self.alert_for_hit(hit_id)
        aref = alert.get("account_ref")
        if aref and aref in self.onb_by_acc:
            return self.onb_by_acc[aref].get("kyc_applicant_id")
        return None

    def latest_kyc_date(self, applicant_id: str) -> Optional[str]:
        dates = [k.get("checked_at") for k in self.kyc if k.get("applicant_id") == applicant_id and k.get("checked_at")]
        return max(dates) if dates else None

    def save(self, *keys: str) -> None:
        mapping = {
            "hits": (self.paths["hits"], self.hits),
            "alerts": (self.paths["alerts"], self.alerts),
            "customers": (self.paths["customers"], self.customers),
            "accounts": (self.paths["accounts"], self.accounts),
            "onboarding": (self.paths["onboarding"], self.onboarding),
            "kyc": (self.paths["kyc"], self.kyc),
        }
        for k in keys:
            path, rows = mapping[k]
            write_jsonl(path, rows)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def mutate_name_variant(ctx: DataCtx, hit_id: str, _hints: List[str]) -> str:
    hit = ctx.hit_by_id[hit_id]
    name = hit.get("name") or ""
    new_name = None
    notes = []

    # 1) Swap a known given-name variant token
    tokens = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ']+", name)
    lower_map = {t.lower(): t for t in tokens}
    for group in ctx.variant_groups:
        gl = [g.lower() for g in group]
        for tok_l, tok in lower_map.items():
            if tok_l in gl and len(group) > 1:
                # pick next variant in group
                idx = gl.index(tok_l)
                repl = group[(idx + 1) % len(group)]
                # preserve rough casing
                if tok.isupper():
                    repl_c = repl.upper()
                elif tok[0].isupper():
                    repl_c = repl.capitalize()
                else:
                    repl_c = repl
                new_name = re.sub(rf"\b{re.escape(tok)}\b", repl_c, name, count=1)
                notes.append(f"variant {tok}->{repl_c}")
                break
        if new_name:
            break

    # 2) Strip accents
    if not new_name:
        stripped = strip_accents(name)
        if stripped != name:
            new_name = stripped
            notes.append("strip_accents")

    # 3) Join or split spaces / commas
    if not new_name:
        if "," in name:
            parts = [p.strip() for p in name.split(",", 1)]
            new_name = f"{parts[1]} {parts[0]}".strip() if len(parts) == 2 else name.replace(",", " ")
            notes.append("reorder_comma")
        elif " " in name.strip():
            new_name = re.sub(r"(\w) (\w)", r"\1\2", name, count=1)
            notes.append("join_space")
        else:
            new_name = (name + name[-1:]) if name else "X"
            notes.append("append_letter")

    if not new_name or new_name == name:
        new_name = (name + "x") if name else "Variant Name"
        notes.append("suffix_x")

    hit["name"] = new_name
    # keep aliases coherent: add original as alias if list present
    aliases = list(hit.get("aliases") or [])
    if name and name not in aliases:
        aliases.append(f"{name} (AKA)")
        hit["aliases"] = aliases
    ctx.save("hits")
    return "; ".join(notes) + f" => {new_name!r}"


def mutate_remove_hit_dob(ctx: DataCtx, hit_id: str, _hints: List[str]) -> str:
    hit = ctx.hit_by_id[hit_id]
    old_dobs = list(hit.get("dobs") or [])
    hit["dobs"] = []
    notes = hit.get("profile_notes")
    stripped = 0
    if notes:
        def _sub(m: re.Match) -> str:
            nonlocal stripped
            stripped += 1
            # keep leading delimiter if present
            lead = m.group(0)[: len(m.group(0)) - len(m.group(1))]
            return lead.rstrip()

        new_notes = BORN_AGE_SENTENCE.sub(_sub, notes)
        # also kill bare "N-year-old" fragments left mid-sentence
        new_notes2, n2 = re.subn(
            r"(?i),?\s*a?\s*\d{1,3}\s*[- ]?\s*years?\s*[- ]?\s*old\b",
            "",
            new_notes,
        )
        stripped += n2
        hit["profile_notes"] = new_notes2
    ctx.save("hits")
    return f"cleared dobs={old_dobs!r}; stripped_born_age_bits={stripped}"


def _append_kyc(
    ctx: DataCtx,
    hit_id: str,
    hints: List[str],
    result: str,
    tag: str,
) -> str:
    cust_ids = ctx.resolved_customer_ids(hit_id, hints)
    if not cust_ids:
        return "SKIP: no customer resolved"
    applicant = ctx.kyc_applicant_for(cust_ids, hit_id)
    if not applicant:
        # create a synthetic onboarding row linked via account_ref if possible
        alert = ctx.alert_for_hit(hit_id)
        applicant = mut_id("APP", hit_id, tag)
        aref = alert.get("account_ref")
        ctx.onboarding.append({
            "account_id": aref or mut_id("ACC", hit_id, tag),
            "customer_id": cust_ids[0],
            "kyc_applicant_id": applicant,
            "onboarded_at": "2020-01-01",
        })
        ctx.onb_by_cust.setdefault(cust_ids[0], []).append(ctx.onboarding[-1])
        if aref:
            ctx.onb_by_acc[aref] = ctx.onboarding[-1]
        ctx.save("onboarding")

    cust = ctx.cust_by_id[cust_ids[0]]
    base_dob = cust.get("dob")
    hit = ctx.hit_by_id[hit_id]
    if not base_dob and hit.get("dobs"):
        base_dob = hit["dobs"][0]
    alert = ctx.alert_for_hit(hit_id)
    if not base_dob:
        base_dob = (alert.get("customer") or {}).get("dob") or alert.get("dob")
    bad_dob = shift_dob(base_dob, 10)

    latest = ctx.latest_kyc_date(applicant)
    if latest and re.match(r"^\d{4}-\d{2}-\d{2}$", str(latest)):
        y, m, d = map(int, str(latest).split("-"))
        checked = (date(y, m, d) + timedelta(days=30)).isoformat()
    else:
        checked = "2026-11-01"

    # pull a template from existing checks for this applicant if any
    template = next((k for k in ctx.kyc if k.get("applicant_id") == applicant), None)
    row = {
        "check_id": mut_id("KYC", hit_id, tag),
        "applicant_id": applicant,
        "provider": (template or {}).get("provider") or "Persona",
        "verified_name": (template or {}).get("verified_name") or cust.get("full_name"),
        "verified_dob": bad_dob,
        "document_type": (template or {}).get("document_type") or "passport",
        "document_number": mut_id("DOC", hit_id, tag),
        "document_country": (template or {}).get("document_country") or cust.get("nationality") or "US",
        "result": result,
        "checked_at": checked,
    }
    ctx.kyc.append(row)
    ctx.save("kyc")
    return f"applicant={applicant} result={result} verified_dob={bad_dob} checked_at={checked} customers={cust_ids}"


def mutate_verified_conflicting_dob(ctx: DataCtx, hit_id: str, hints: List[str]) -> str:
    return _append_kyc(ctx, hit_id, hints, "approved", "vcdob")


def mutate_unreliable_conflicting_dob(ctx: DataCtx, hit_id: str, hints: List[str]) -> str:
    return _append_kyc(ctx, hit_id, hints, "rejected", "ucdob")


def mutate_duplicate_customer(ctx: DataCtx, hit_id: str, hints: List[str]) -> str:
    cust_ids = ctx.resolved_customer_ids(hit_id, hints)
    if not cust_ids:
        return "SKIP: no customer resolved"
    src = ctx.cust_by_id[cust_ids[0]]
    dup = deepcopy(src)
    new_id = mut_id("CUS", hit_id, "dup")
    dup["record_id"] = new_id
    # same phone + dob (identity twin); tweak email/login so it is a distinct row
    if dup.get("email"):
        local, _, domain = dup["email"].partition("@")
        dup["email"] = f"{local}+dup@{domain}" if domain else f"{dup['email']}+dup"
    ctx.customers.append(dup)
    ctx.cust_by_id[new_id] = dup
    ctx.save("customers")
    return f"duplicated {cust_ids[0]} -> {new_id} phone={dup.get('phone')} dob={dup.get('dob')}"


def mutate_lookalike_customer(ctx: DataCtx, hit_id: str, hints: List[str]) -> str:
    cust_ids = ctx.resolved_customer_ids(hit_id, hints)
    alert = ctx.alert_for_hit(hit_id)
    screened = alert.get("customer") or {}
    if cust_ids:
        src = deepcopy(ctx.cust_by_id[cust_ids[0]])
    else:
        src = {
            "record_id": "TMP",
            "entity_type": screened.get("entity_type") or "Individual",
            "full_name": screened.get("name") or "Lookalike Person",
            "preferred_name": None,
            "login_name": None,
            "dob": screened.get("dob") or "1990-01-01",
            "nationality": screened.get("country"),
            "residence_country": screened.get("country"),
            "city": screened.get("city"),
            "address": None,
            "email": None,
            "phone": "+1 5550000000",
            "occupation": None,
            "employer": None,
            "registration_number": None,
            "onboarded_at": "2020-01-01",
            "status": "active",
            "last_kyc_refresh": None,
        }
    new_id = mut_id("CUS", hit_id, "look")
    src["record_id"] = new_id
    # same display name as screened / original, different phone + dob
    src["full_name"] = screened.get("name") or src.get("full_name")
    src["dob"] = shift_dob(src.get("dob") or screened.get("dob"), 7)
    src["phone"] = f"+1 555{abs(hash(hit_id)) % 10_000_000:07d}"
    src["email"] = f"lookalike.{hit_id.lower()}@example.invalid"
    ctx.customers.append(src)
    ctx.cust_by_id[new_id] = src

    notes = [f"added lookalike {new_id} name={src['full_name']!r} dob={src['dob']} phone={src['phone']}"]
    # Make them a candidate: joint holder on same account_ref when present
    aref = alert.get("account_ref")
    if aref:
        template = (ctx.acc_by_id.get(aref) or [{}])[0]
        acc_row = {
            "account_id": aref,
            "customer_id": new_id,
            "login_handle": template.get("login_handle"),
            "phone": src["phone"],
            "opened_at": template.get("opened_at") or "2020-01-01",
            "status": template.get("status") or "active",
        }
        ctx.accounts.append(acc_row)
        ctx.acc_by_id.setdefault(aref, []).append(acc_row)
        ctx.save("customers", "accounts")
        notes.append(f"joint account_ref {aref}")
    else:
        # name-search path: ensure country/city fit screened details
        if screened.get("country"):
            src["residence_country"] = screened["country"]
            src["nationality"] = screened.get("country")
        if screened.get("city"):
            src["city"] = screened["city"]
        # If alert has DOB, fits_screened requires matching DOB — keep a near-miss
        # by leaving conflicting dob (won't match) which is fine for lookalike intent.
        ctx.save("customers")
        notes.append("name-search candidate (no account_ref)")
    return "; ".join(notes)


def mutate_cut_account_link(ctx: DataCtx, hit_id: str, _hints: List[str]) -> str:
    alert = ctx.alert_for_hit(hit_id)
    before = {
        "account_ref": alert.get("account_ref"),
        "login_handle": alert.get("login_handle"),
        "email": alert.get("email"),
    }
    alert["account_ref"] = None
    alert["login_handle"] = None
    alert["email"] = None
    ctx.save("alerts")
    return f"nulled links was={before}"


MUTATORS: Dict[str, Callable[[DataCtx, str, List[str]], str]] = {
    "name_variant": mutate_name_variant,
    "remove_hit_dob": mutate_remove_hit_dob,
    "verified_conflicting_dob": mutate_verified_conflicting_dob,
    "unreliable_conflicting_dob": mutate_unreliable_conflicting_dob,
    "duplicate_customer": mutate_duplicate_customer,
    "lookalike_customer": mutate_lookalike_customer,
    "cut_account_link": mutate_cut_account_link,
}


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(
    mutation: str,
    original: str,
    mutated: str,
    mutated_reason: Optional[str],
) -> Tuple[str, bool, bool, str]:
    """Return (expected, passed, safety_violation, notes)."""
    notes = []
    safety = False

    if mutation == "name_variant":
        expected = f"{original}|REVIEW"
        passed = mutated in {original, "REVIEW"}
        if mutated == "DIFFERENT_ENTITY":
            safety = True
            passed = False
            notes.append("wrongful clear after name variant")
    elif mutation == "remove_hit_dob":
        expected = "REVIEW"
        if original == "REVIEW":
            passed = mutated == "REVIEW"
        else:
            # ideal: SAME -> REVIEW; staying SAME is soft-fail; DIFFERENT is safety
            passed = mutated == "REVIEW"
            if mutated == "SAME_ENTITY":
                notes.append("still SAME after DOB removal (soft-fail)")
        if mutated == "DIFFERENT_ENTITY":
            safety = True
            passed = False
            notes.append("wrongful clear after remove_hit_dob")
    elif mutation == "verified_conflicting_dob":
        expected = "DIFFERENT_ENTITY"
        passed = mutated == "DIFFERENT_ENTITY"
        if mutated == "SAME_ENTITY":
            notes.append("still SAME despite approved conflicting DOB (soft-fail)")
        if mutated_reason and mutated == "DIFFERENT_ENTITY" and mutated_reason != "DOB_MISMATCH":
            notes.append(f"different but reason={mutated_reason} (wanted DOB_MISMATCH)")
        # no safety_violation for this probe unless something absurd — keep false
    elif mutation == "unreliable_conflicting_dob":
        expected = original
        passed = mutated == original
        if mutated == "DIFFERENT_ENTITY" and original != "DIFFERENT_ENTITY":
            safety = True
            passed = False
            notes.append("decision flipped to DIFFERENT on rejected/expired KYC")
        elif not passed:
            notes.append(f"decision changed {original}->{mutated}")
    elif mutation == "duplicate_customer":
        expected = original
        passed = mutated == original
        if mutated == "DIFFERENT_ENTITY":
            safety = True
            passed = False
            notes.append("wrongful clear after duplicate customer")
        elif not passed:
            notes.append(f"decision changed {original}->{mutated}")
    elif mutation == "lookalike_customer":
        expected = f"{original}|REVIEW"
        passed = mutated in {original, "REVIEW"}
        if mutated == "DIFFERENT_ENTITY":
            safety = True
            passed = False
            notes.append("wrongful clear after lookalike")
    elif mutation == "cut_account_link":
        expected = "SAME_ENTITY|REVIEW"
        passed = mutated in {"SAME_ENTITY", "REVIEW"}
        if mutated == "DIFFERENT_ENTITY":
            safety = True
            passed = False
            notes.append("wrongful clear after cutting account link")
    else:
        expected = original
        passed = mutated == original

    return expected, passed, safety, "; ".join(notes)


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------

def load_practice_same(data_dir: str) -> List[dict]:
    path = os.path.join(data_dir, "practice_labels.jsonl")
    if not os.path.isfile(path):
        path = find_jsonl(data_dir, "practice", "label")
    rows = []
    for r in read_jsonl(path):
        if r.get("decision") == "SAME_ENTITY":
            rows.append({
                "hit_id": r["hit_id"],
                "decision": r["decision"],
                "customer_record_ids": [
                    c for c in (r.get("customer_record_ids") or []) if c and c != "AMBIGUOUS"
                ],
                "source": "practice",
            })
    rows.sort(key=lambda x: x["hit_id"])
    return rows


def load_full_same(data_dir: str, baseline: Dict[str, dict]) -> List[dict]:
    """Union of practice SAME + all SAME from baseline/output."""
    by_id = {s["hit_id"]: s for s in load_practice_same(data_dir)}
    out_path = os.path.join(REPO, "output", "dev.jsonl")
    source_rows = list(baseline.values())
    if os.path.isfile(out_path):
        # prefer regenerating from baseline; still merge file if needed
        pass
    for r in source_rows:
        if r.get("decision") != "SAME_ENTITY":
            continue
        hid = r["hit_id"]
        if hid not in by_id:
            cust = r.get("customer_record_id")
            by_id[hid] = {
                "hit_id": hid,
                "decision": "SAME_ENTITY",
                "customer_record_ids": [cust] if cust and cust != "AMBIGUOUS" else [],
                "source": "baseline",
            }
    return [by_id[k] for k in sorted(by_id)]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def fresh_copy(src: str) -> str:
    os.makedirs(HARNESS_ROOT, exist_ok=True)
    dest = tempfile.mkdtemp(prefix="mut-", dir=HARNESS_ROOT)
    # copytree into empty dest: use dest as target directly
    shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


def run_case(
    data_dir: str,
    seed: dict,
    mutation: str,
    baseline: Dict[str, dict],
    work_root: str,
) -> dict:
    hit_id = seed["hit_id"]
    case_id = f"{hit_id}:{mutation}"
    original_row = baseline.get(hit_id) or {}
    original = original_row.get("decision") or seed.get("decision") or "UNKNOWN"

    dest = fresh_copy(data_dir)
    out_file = os.path.join(work_root, f"{case_id.replace(':', '_')}.jsonl")
    mut_note = ""
    try:
        ctx = DataCtx(dest)
        if hit_id not in ctx.hit_by_id:
            return {
                "case_id": case_id,
                "hit_id": hit_id,
                "mutation": mutation,
                "original_decision": original,
                "mutated_decision": "MISSING",
                "mutated_reason_code": None,
                "expected": "n/a",
                "passed": False,
                "safety_violation": False,
                "notes": "hit missing from dataset",
            }
        mut_note = MUTATORS[mutation](ctx, hit_id, seed.get("customer_record_ids") or [])
        if mut_note.startswith("SKIP:"):
            expected, passed, safety, eval_notes = evaluate(mutation, original, original, None)
            return {
                "case_id": case_id,
                "hit_id": hit_id,
                "mutation": mutation,
                "original_decision": original,
                "mutated_decision": original,
                "mutated_reason_code": original_row.get("reason_code"),
                "expected": expected,
                "passed": False,
                "safety_violation": False,
                "notes": mut_note,
            }
        mutated_map = run_engine(dest, out_file)
        mrow = mutated_map.get(hit_id) or {}
        mutated = mrow.get("decision") or "MISSING"
        reason = mrow.get("reason_code")
        expected, passed, safety, eval_notes = evaluate(mutation, original, mutated, reason)
        notes_parts = [p for p in (mut_note, eval_notes) if p]
        return {
            "case_id": case_id,
            "hit_id": hit_id,
            "mutation": mutation,
            "original_decision": original,
            "mutated_decision": mutated,
            "mutated_reason_code": reason,
            "expected": expected,
            "passed": passed,
            "safety_violation": safety,
            "notes": "; ".join(notes_parts),
        }
    except Exception as e:
        return {
            "case_id": case_id,
            "hit_id": hit_id,
            "mutation": mutation,
            "original_decision": original,
            "mutated_decision": "ERROR",
            "mutated_reason_code": None,
            "expected": "n/a",
            "passed": False,
            "safety_violation": False,
            "notes": f"{type(e).__name__}: {e}; mut={mut_note}",
        }
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def print_table(results: List[dict]) -> None:
    cols = ("case_id", "orig", "mut", "pass", "safety", "reason")
    rows = []
    for r in results:
        rows.append((
            r["case_id"],
            r["original_decision"],
            r["mutated_decision"],
            "Y" if r["passed"] else "N",
            "!" if r["safety_violation"] else ".",
            (r.get("mutated_reason_code") or "")[:28],
        ))
    widths = [max(len(cols[i]), max((len(str(row[i])) for row in rows), default=0)) for i in range(len(cols))]
    fmt = "  ".join(f"{{:{w}}}" for w in widths)
    print(fmt.format(*cols))
    print(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        print(fmt.format(*row))


def headline(results: List[dict], n_seeds: int) -> str:
    n = len(results)
    stayed = sum(1 for r in results if r["mutated_decision"] == "SAME_ENTITY")
    review = sum(1 for r in results if r["mutated_decision"] == "REVIEW")
    diff = sum(1 for r in results if r["mutated_decision"] == "DIFFERENT_ENTITY")
    wrongful = sum(
        1 for r in results
        if r["original_decision"] == "SAME_ENTITY"
        and r["mutated_decision"] == "DIFFERENT_ENTITY"
        and r["mutation"] in NO_WRONGFUL_CLEAR
    )
    return (
        f"{n} mutations from {n_seeds} true matches: "
        f"{stayed} stayed SAME, {review} moved to REVIEW, {diff} became DIFFERENT "
        f"(wrongful clears: {wrongful})"
    )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ClearGuard mutation harness (test-to-fail)")
    p.add_argument("--data", required=True, help="Official data folder (not copied into repo)")
    p.add_argument("--out", required=True, help="JSON report path")
    p.add_argument("--seeds", choices=("practice", "full"), default="practice")
    p.add_argument(
        "--mutations",
        default="all",
        help="Comma-separated mutation names, or 'all'",
    )
    p.add_argument("--limit", type=int, default=0, help="Max seed×mutation cases (0 = no limit)")
    p.add_argument("--keep-work", action="store_true", help="Keep per-case engine outputs under harness root")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    data_dir = os.path.abspath(args.data)
    if not os.path.isdir(data_dir):
        print(f"data dir not found: {data_dir}", file=sys.stderr)
        return 2
    if not os.path.isfile(RUN_BIN):
        print(f"engine runner missing: {RUN_BIN}", file=sys.stderr)
        return 2

    os.makedirs(HARNESS_ROOT, exist_ok=True)
    work_root = tempfile.mkdtemp(prefix="runs-", dir=HARNESS_ROOT)

    # Baseline once
    baseline_out = os.path.join(HARNESS_ROOT, "baseline.jsonl")
    print(f"baseline: running engine on {data_dir} -> {baseline_out}", flush=True)
    baseline = run_engine(data_dir, baseline_out)
    print(f"baseline: {len(baseline)} hits", flush=True)

    if args.seeds == "practice":
        seeds = load_practice_same(data_dir)
    else:
        seeds = load_full_same(data_dir, baseline)
    print(f"seeds: {len(seeds)} SAME_ENTITY ({args.seeds})", flush=True)

    if args.mutations.strip().lower() == "all":
        mutations = list(MUTATION_ORDER)
    else:
        mutations = [m.strip() for m in args.mutations.split(",") if m.strip()]
        unknown = [m for m in mutations if m not in MUTATORS]
        if unknown:
            print(f"unknown mutations: {unknown}", file=sys.stderr)
            return 2
        # stable order following MUTATION_ORDER then any extras
        order_index = {m: i for i, m in enumerate(MUTATION_ORDER)}
        mutations = sorted(mutations, key=lambda m: order_index.get(m, 1000))

    # Build deterministic case list: seeds sorted, mutations in fixed order
    cases: List[Tuple[dict, str]] = []
    for seed in seeds:
        for mut in mutations:
            cases.append((seed, mut))
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]

    results: List[dict] = []
    for i, (seed, mut) in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {seed['hit_id']}:{mut} ...", flush=True)
        r = run_case(data_dir, seed, mut, baseline, work_root)
        results.append(r)
        flag = "SAFE" if not r["safety_violation"] else "VIOLATION"
        print(
            f"    {r['original_decision']} -> {r['mutated_decision']} "
            f"passed={r['passed']} {flag}",
            flush=True,
        )

    # Report
    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print()
    print_table(results)
    print()
    line = headline(results, len(seeds))
    print(line)
    fails = [r for r in results if not r["passed"]]
    viols = [r for r in results if r["safety_violation"]]
    print(f"failures: {len(fails)}  safety_violations: {len(viols)}")
    print(f"report: {out_path}")
    if not args.keep_work:
        shutil.rmtree(work_root, ignore_errors=True)
    else:
        print(f"work kept at: {work_root}")
    return 0 if not viols else 1


if __name__ == "__main__":
    sys.exit(main())
