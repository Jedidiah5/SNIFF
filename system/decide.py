"""Customer resolution, fact gathering and SOP decisions."""
import re
from collections import defaultdict

from engine import (as_list, parse_date, dates_in_text, fmt_date, full_date, to_pydate, norm_country,
                    countries_in_text, strip_accents, MONTHS, LISTING_PHRASES, OTHER_LISTING,
                    PLACEHOLDERS, KNOWN_COUNTRIES, COUNTRY_ALIASES, DATE_IN_TEXT)


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------
class Index:
    def __init__(self, data):
        self.data = data
        self.names = data["names"]
        self.cust = {c["record_id"]: c for c in data["customers"]}
        self.acc_by_id = defaultdict(list)
        self.acc_by_login = defaultdict(list)
        self.acc_by_cust = defaultdict(list)
        for a in data["accounts"]:
            self.acc_by_id[a.get("account_id")].append(a)
            if a.get("login_handle"):
                self.acc_by_login[str(a["login_handle"]).lower()].append(a)
            self.acc_by_cust[a.get("customer_id")].append(a)
        self.onb = defaultdict(list)  # (account_id, customer_id) -> onboarding rows
        self.onb_by_cust = defaultdict(list)
        for o in data["onboarding"]:
            self.onb[(o.get("account_id"), o.get("customer_id"))].append(o)
            self.onb_by_cust[o.get("customer_id")].append(o)
        self.kyc_by_app = defaultdict(list)
        for k in data["kyc"]:
            self.kyc_by_app[k.get("applicant_id")].append(k)
        self.notes_by_email = defaultdict(list)
        for n in data["notes"]:
            if n.get("requester_email"):
                self.notes_by_email[str(n["requester_email"]).lower()].append(n)
        self.cust_by_email = defaultdict(list)
        self.cust_by_phone_dob = defaultdict(list)
        self.cust_by_part = defaultdict(set)
        self.cust_dob = {}
        for c in data["customers"]:
            rid = c["record_id"]
            if c.get("email"):
                self.cust_by_email[str(c["email"]).lower()].append(rid)
            d = parse_date(c.get("dob"))
            self.cust_dob[rid] = d
            if full_date(d):
                for ph in self._phones(rid):
                    self.cust_by_phone_dob[(ph, d)].append(rid)
            company = (c.get("entity_type") or "").lower().startswith("comp")
            for f in ("full_name", "preferred_name", "login_name"):
                for p in self.names.parts(c.get(f), company):
                    self.cust_by_part[p].add(rid)
        self.search_by_query = defaultdict(list)
        for s in data["search"]:
            self.search_by_query[self._qkey(s.get("query"))].append(s)
        self.providers = {str(k.get("provider") or "").strip().lower()
                          for k in data["kyc"] if k.get("provider")}
        # document number -> customers (approved checks only)
        self.cust_by_doc = defaultdict(set)
        self.docs_by_cust = defaultdict(set)
        for rid in self.cust:
            for k in self.kyc_checks(rid):
                if (k.get("result") or "").lower() == "approved" and k.get("document_number"):
                    self.cust_by_doc[k["document_number"]].add(rid)
                    self.docs_by_cust[rid].add(k["document_number"])

    def _phones(self, rid):
        out = set()
        c = self.cust.get(rid, {})
        if c.get("phone"):
            out.add(re.sub(r"\D", "", str(c["phone"])))
        return {p for p in out if p}

    @staticmethod
    def _qkey(s):
        w = re.sub(r"[^a-z0-9 ]+", " ", strip_accents(str(s or "")).lower()).split()
        return " ".join(sorted(w))

    def kyc_checks(self, rid):
        out = []
        for o in self.onb_by_cust.get(rid, []):
            out.extend(self.kyc_by_app.get(o.get("kyc_applicant_id"), []))
        return out

    def kyc_notes(self, rid):
        c = self.cust.get(rid, {})
        return [n for n in self.notes_by_email.get(str(c.get("email") or "").lower(), [])]


# ---------------------------------------------------------------------------
# Customer resolution (SOP principles 2 and 3)
# ---------------------------------------------------------------------------
def fits_screened(ix, rid, alert, use_name=True):
    c = ix.cust[rid]
    names = ix.names
    company = (c.get("entity_type") or "").lower().startswith("comp")
    if use_name and alert.get("customer_name"):
        sp = names.parts(alert["customer_name"], company)
        ok = False
        for f in ("full_name", "preferred_name", "login_name"):
            cp = names.parts(c.get(f), company)
            if cp and sp and names.agree(sp, cp)[0]:
                ok = True
                break
        if not ok:
            return False
    sd = parse_date(alert.get("dob"))
    cd = ix.cust_dob.get(rid)
    if sd and cd:
        if sd[0] != cd[0] or (sd[1] and cd[1] and sd[1] != cd[1]) or (sd[2] and cd[2] and sd[2] != cd[2]):
            return False
    elif sd and not cd:
        return False
    sc = norm_country(alert.get("country"))
    if sc:
        if sc not in {norm_country(c.get("residence_country")), norm_country(c.get("nationality"))}:
            return False
    city = alert.get("city")
    if city:
        cl = strip_accents(str(city)).lower()
        hay = strip_accents(" ".join(str(c.get(f) or "") for f in ("city", "address"))).lower()
        if cl not in hay:
            return False
    return True


def resolve(ix, alert):
    """Return (persons, path) where persons is a list of lists of record ids."""
    path = []
    seeds = []
    linked = False
    if alert.get("account_ref"):
        rows = ix.acc_by_id.get(alert["account_ref"], [])
        seeds = sorted({r.get("customer_id") for r in rows if r.get("customer_id") in ix.cust})
        path.append(f"account_ref {alert['account_ref']} -> accounts -> {', '.join(seeds) or 'none'}")
        linked = bool(rows)
    if not seeds and alert.get("login_handle"):
        rows = ix.acc_by_login.get(str(alert["login_handle"]).lower(), [])
        seeds = sorted({r.get("customer_id") for r in rows if r.get("customer_id") in ix.cust})
        path.append(f"login_handle {alert['login_handle']} -> accounts -> {', '.join(seeds) or 'none'}")
        linked = linked or bool(rows)
    if not seeds and alert.get("email"):
        seeds = sorted(set(ix.cust_by_email.get(str(alert["email"]).lower(), [])))
        path.append(f"email {alert['email']} -> customers -> {', '.join(seeds) or 'none'}")
        linked = linked or bool(seeds)
    if len(seeds) > 1:
        fit = [r for r in seeds if fits_screened(ix, r, alert)]
        if fit:
            path.append(f"several holders; screened details fit {', '.join(fit)}")
            seeds = fit
    if not seeds and not linked:
        cand = None
        is_company = (alert.get("entity_type") or "").lower().startswith("comp")
        for p in ix.names.parts(alert.get("customer_name"), is_company):
            s = ix.cust_by_part.get(p, set())
            cand = set(s) if cand is None else cand | s
        cand = sorted(cand or [])
        seeds = [r for r in cand if fits_screened(ix, r, alert)]
        path.append(f"name, date of birth, country and city -> customers -> {', '.join(seeds) or 'none'}")
    persons = group_persons(ix, seeds)
    if any(len(p) > 1 for p in persons):
        path.append("same phone and date of birth, or same document number -> " +
                    " | ".join(", ".join(p) for p in persons))
    return persons, path


def group_persons(ix, seeds):
    persons, seen = [], set()
    for s in seeds:
        if s in seen:
            continue
        group, todo = set(), [s]
        while todo:
            r = todo.pop()
            if r in group:
                continue
            group.add(r)
            d = ix.cust_dob.get(r)
            if full_date(d):
                for ph in ix._phones(r):
                    todo.extend(x for x in ix.cust_by_phone_dob.get((ph, d), []) if x not in group)
            for doc in ix.docs_by_cust.get(r, ()):
                todo.extend(x for x in ix.cust_by_doc.get(doc, ()) if x not in group)
        seen |= group
        persons.append(sorted(group))
    return persons


# ---------------------------------------------------------------------------
# Customer facts
# ---------------------------------------------------------------------------
CAPS_NAME = re.compile(r"\b([A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'\-]+(?:\s+[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'\-]+)*)\b")
TITLE_NAME = re.compile(
    r"\b([A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'\-]+(?:\s+[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ'\-]+)+)\b"
)
NOT_NAME = {"DOB", "ID", "KYC", "PEP", "SOE", "UK", "US", "USA", "UAE", "EU"}
BIRTH_TOKEN = re.compile(r"(?i)\bborn\b|\bbirth\b|\bd\.?o\.?b\.?\b|\bdate of birth\b")
WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
DEFAULT_PROVIDERS = {"veriff", "onfido", "sumsub", "persona", "jumio", "companies registry lookup"}


def _name_blocklist(providers):
    """Tokens that are never personal name parts (SOP principle 8 + providers/geo/time words)."""
    blocked = set(PLACEHOLDERS) | set(MONTHS) | set(WEEKDAYS) | set(DEFAULT_PROVIDERS)
    for p in providers or ():
        for w in strip_accents(str(p)).lower().split():
            if len(w) > 1:
                blocked.add(w)
    for c in KNOWN_COUNTRIES:
        for w in strip_accents(c).lower().split():
            if len(w) > 2:
                blocked.add(w)
    for alias in COUNTRY_ALIASES:
        for w in alias.split():
            if len(w) > 2:
                blocked.add(w)
    return blocked


def _year_ok(d, created):
    if d is None or d[0] is None:
        return False
    if d[0] < 1900:
        return False
    if created and d[0] > created[0]:
        return False
    return True


def _birth_keyword_sides(text, start, end, radius=40):
    """Return (near, keyword_before_date, keyword_after_date)."""
    left = text[max(0, start - radius):start]
    right = text[end:min(len(text), end + radius)]
    before = bool(BIRTH_TOKEN.search(left))
    after = bool(BIRTH_TOKEN.search(right))
    return (before or after), before, after


def _trust_note_name(cand, names_obj, anchors, blocklist):
    """Return (name_or_None, failed). Failed name must not drive NAME_MISMATCH_VERIFIED."""
    if not cand:
        return None, False
    parts = [p for p in names_obj.parts(cand, False) if p not in blocklist]
    if len(parts) < 2:
        return None, True
    shared = False
    for anchor in anchors:
        ap = [p for p in names_obj.parts(anchor, False) if p not in blocklist]
        for p in parts:
            if any(names_obj.part_match(p, a) for a in ap):
                shared = True
                break
        if shared:
            break
    if not shared:
        return None, True
    return cand, False


def _pick_trusted_name(cands, names_obj, anchors, blocklist):
    """Try candidates longest-first; skip spans whose parts are all blocked."""
    any_failed = False
    for cand in sorted(set(cands), key=len, reverse=True):
        parts = [p for p in names_obj.parts(cand, False) if p not in blocklist]
        if len(parts) < 2:
            any_failed = True
            continue
        name, failed = _trust_note_name(cand, names_obj, anchors, blocklist)
        if name:
            return name, False
        if failed:
            any_failed = True
    return None, any_failed


def parse_kyc_note(note, names_obj, anchors, providers=None):
    """Extract verified name/DOB from a KYC note (SOP principles 4 and 8).

    A failed name check only suppresses the note name. It does not mark the DOB unusual.
    """
    text = note.get("text") or ""
    created = parse_date(note.get("created_at"))
    blocklist = _name_blocklist(providers)

    # Prefer ALL-CAPS verified names; Title Case only when no CAPS candidate exists.
    caps_cands = []
    for m in CAPS_NAME.finditer(text):
        words = [w for w in m.group(1).split() if w.upper() not in NOT_NAME]
        if words:
            caps_cands.append(" ".join(words))
    name, name_check_failed = None, False
    name_from_title_case = False
    if caps_cands:
        name, name_check_failed = _pick_trusted_name(caps_cands, names_obj, anchors, blocklist)
    else:
        title_cands = []
        for m in TITLE_NAME.finditer(text):
            words = [w for w in m.group(1).split() if w.upper() not in NOT_NAME]
            if len(words) >= 2:
                title_cands.append(" ".join(words))
        if title_cands:
            name, name_check_failed = _pick_trusted_name(title_cands, names_obj, anchors, blocklist)
            name_from_title_case = bool(name)

    # DOB: keyword within ~40 chars either side; else single non-created_at date only.
    dated = []
    for m in DATE_IN_TEXT.finditer(text or ""):
        d = parse_date(m.group(0))
        if d:
            dated.append((m.start(), m.end(), m.group(0), d))
    non_created = []
    seen = set()
    for start, end, raw, d in dated:
        if created and d == created:
            continue
        if d in seen:
            continue
        seen.add(d)
        non_created.append((start, end, raw, d))

    dob, dob_keyword_anchored = None, False
    dob_keyword_before = False  # classic: cue left of the date
    dob_keyword_after_only = False  # needed the either-side window (cue right of date only)
    for start, end, raw, d in dated:
        if created and d == created:
            continue
        if not _year_ok(d, created):
            continue
        near, before, after = _birth_keyword_sides(text, start, end)
        if near:
            dob, dob_keyword_anchored = d, True
            dob_keyword_before = before
            dob_keyword_after_only = (not before) and after
            break
    if dob is None and len(non_created) == 1 and _year_ok(non_created[0][3], created):
        dob, dob_keyword_anchored = non_created[0][3], False

    # Unusual DOB only: no keyword on either side AND more than one non-created_at date.
    # Name failure must not poison the DOB (principle 4: verified DOB is still verified).
    unusual = bool(dob is not None and not dob_keyword_anchored and len(non_created) > 1)
    countries = countries_in_text(text)
    return {"name": name, "dob": dob, "country": countries[0] if countries else None,
            "date": created, "id": note.get("note_id"), "source": "note",
            "unusual": unusual, "dob_keyword_anchored": dob_keyword_anchored,
            "dob_keyword_before": dob_keyword_before,
            "dob_keyword_after_only": dob_keyword_after_only,
            "name_from_title_case": name_from_title_case,
            "name_check_failed": name_check_failed}


def customer_facts(ix, person, alert=None):
    """Facts for one person (list of record ids)."""
    recs = [ix.cust[r] for r in person]
    anchors = []
    for c in recs:
        for f in ("full_name", "preferred_name"):
            if c.get(f) and c[f] not in anchors:
                anchors.append(c[f])
    if alert and alert.get("customer_name"):
        anchors.append(alert["customer_name"])
    verified = []
    for rid in person:
        for k in ix.kyc_checks(rid):
            if (k.get("result") or "").lower() != "approved":
                continue
            verified.append({"name": k.get("verified_name"), "dob": parse_date(k.get("verified_dob")),
                             "country": norm_country(k.get("document_country")),
                             "date": parse_date(k.get("checked_at")), "id": k.get("check_id"), "source": "kyc",
                             "unusual": False, "name_from_title_case": False,
                             "dob_keyword_after_only": False, "name_check_failed": False})
    notes_seen = set()
    lived = {}
    for rid in person:
        for n in ix.kyc_notes(rid):
            if n.get("note_id") in notes_seen:
                continue
            notes_seen.add(n.get("note_id"))
            if (n.get("channel") or "").lower() == "kyc":
                v = parse_kyc_note(n, ix.names, anchors, ix.providers)
                if v["name"] or v["dob"]:
                    verified.append(v)
            else:
                for c in countries_in_text(n.get("text")):
                    lived.setdefault(c, n.get("note_id"))
    verified.sort(key=lambda v: (v["date"] or (0, 0, 0), v["source"] == "kyc", v["id"] or ""))
    latest = verified[-1] if verified else None
    rec_dobs = [ix.cust_dob.get(r) for r in person if ix.cust_dob.get(r)]
    if latest and latest["dob"]:
        dob, dob_src = latest["dob"], latest["id"]
    elif rec_dobs:
        dob, dob_src = rec_dobs[0], person[0]
    else:
        dob, dob_src = None, None
    countries = {}
    for c in recs:
        for f in ("residence_country", "nationality"):
            v = norm_country(c.get(f))
            if v:
                countries.setdefault(v, c["record_id"])
    if latest and latest.get("country"):
        countries.setdefault(latest["country"], latest["id"])
    for c, nid in lived.items():
        countries.setdefault(c, nid)
    company = any((c.get("entity_type") or "").lower().startswith("comp") for c in recs)
    names = []
    for c in recs:
        for f in ("full_name", "preferred_name"):
            if c.get(f) and c[f] not in names:
                names.append(c[f])
    note_unusual = bool(latest and latest.get("source") == "note" and latest.get("unusual"))
    dob_from_note = bool(latest and latest.get("source") == "note" and latest.get("dob") and dob_src == latest.get("id"))
    name_from_note = bool(latest and latest.get("source") == "note" and latest.get("name"))
    name_from_title_case = bool(latest and latest.get("source") == "note" and latest.get("name_from_title_case"))
    note_name_failed = bool(latest and latest.get("source") == "note" and latest.get("name_check_failed"))
    dob_keyword_after_only = bool(latest and latest.get("source") == "note" and latest.get("dob_keyword_after_only"))
    return {
        "records": person, "company": company, "verified": latest,
        "verified_name": latest["name"] if latest else None,
        "record_names": names, "dob": dob, "dob_src": dob_src,
        "countries": countries, "entity_type": "Company" if company else "Individual",
        "note_unusual": note_unusual, "dob_from_note": dob_from_note, "name_from_note": name_from_note,
        "name_from_title_case": name_from_title_case, "note_name_failed": note_name_failed,
        "dob_keyword_after_only": dob_keyword_after_only,
    }


# ---------------------------------------------------------------------------
# Hit facts
# ---------------------------------------------------------------------------
REPORT_LINE = re.compile(r"^According to .*?;\s*([A-Z][a-z]+\.? \d{1,2}, \d{4})\s*:", re.M)
MONTH_YEAR = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\.?,? (\d{4})\b")
AGE_PATTERNS = [
    re.compile(r"\baged? (\d{1,3})\b", re.I),
    re.compile(r"\bage of (\d{1,3})\b", re.I),
    re.compile(r"\bat age (\d{1,3})\b", re.I),
    re.compile(r"\b(\d{1,3})[- ]years?[- ]old\b", re.I),
    # "was N" only with a clear age cue, or as the clause end after a dated event
    # (SOP principle 5: "aged 45 when … in March 2019" / "… in January 2023, he was 46.").
    re.compile(
        r"\bwas (\d{1,3})\b(?:\s+years?\s+old|\s+at the time|\s+when|(?=\s*[.,;]|\s*$))",
        re.I,
    ),
    re.compile(r",\s*(\d{1,3})\s*,"),
    re.compile(r",\s*(\d{1,3})\s*(?:was|is|who|served|appeared|participated|gave|achieved|accepted|identified|a |an |the )", re.I),
]


def age_years(text):
    """An age at a dated time gives two possible birth years (SOP principle 5).

    If more than one candidate age or year appears, return nothing: a wrong DOB
    can wrongly clear a hit, which the SOP says is the worst mistake.
    """
    ages = []
    for p in AGE_PATTERNS:
        for m in p.finditer(text or ""):
            a = int(m.group(1))
            if 14 <= a <= 100 and a not in ages:
                ages.append(a)
    years = []
    for my in MONTH_YEAR.finditer(text or ""):
        y = int(my.group(2))
        if y not in years:
            years.append(y)
    for m in re.finditer(r"\b(19\d{2}|20\d{2})\b", text or ""):
        y = int(m.group(1))
        if y not in years:
            years.append(y)
    if len(ages) != 1 or len(years) != 1:
        return None
    age, yr = ages[0], years[0]
    return [yr - age - 1, yr - age]


def snippet_years(text):
    """Search snippets carry exactly one small number: the person's age at the dated report."""
    nums = [int(n) for n in re.findall(r"(?<![\d,.])\b(\d{1,3})\b(?![\d,.]\d)", text or "")]
    my = MONTH_YEAR.search(text or "")
    if len(set(nums)) == 1 and my and 0 < nums[0] < 120:
        yr = int(my.group(2))
        return [yr - nums[0] - 1, yr - nums[0]]
    return age_years(text or "")


def hit_countries(h):
    out = []
    for f in ("countries", "nationality", "citizenship"):
        for v in as_list(h.get(f)):
            if not isinstance(v, str):
                continue
            last = re.sub(r"\[.*?\]", "", v).split(",")[-1]
            c = norm_country(last)
            if c and c not in out:
                out.append(c)
    for v in as_list(h.get("addresses")):
        if not isinstance(v, str):
            continue
        last = re.sub(r"\[.*?\]", "", v).split(",")[-1]
        c = norm_country(last)
        if c and c not in out:
            out.append(c)
    for v in as_list(h.get("place_of_birth")):
        if not isinstance(v, str):
            continue
        c = norm_country(v.split(",")[-1])
        if c and c not in out:
            out.append(c)
    return out


def hit_names(h):
    return [h.get("name")] + [a for a in as_list(h.get("aliases")) if isinstance(a, str)]


def listing_phrase(h):
    cat = (h.get("primary_category") or (as_list(h.get("categories")) or [""])[0] or "").strip().lower()
    return LISTING_PHRASES.get(cat, OTHER_LISTING)


def hit_dobs(ix, h):
    """Return (candidates, source_label, evidence_ids, from_profile_notes).

    Each candidate: dict(years, month, day). from_profile_notes marks a fragile DOB.
    """
    cands = []
    for v in as_list(h.get("dobs")):
        d = parse_date(v)
        if d:
            cands.append({"years": [d[0]], "month": d[1], "day": d[2], "text": fmt_date(d)})
    # POLICY principle 5: "For companies, only the dobs field is an incorporation date."
    if (h.get("entity_type") or "").lower().startswith("comp"):
        if cands:
            return cands, "listed date of birth", [], False
        return [], None, [], False
    if cands:
        return cands, "listed date of birth", [], False
    notes = (h.get("profile_notes") or "").strip()
    if notes:
        first = re.split(r"\n\s*\n", notes)[0].strip()
        if not first.startswith("According to"):
            m = re.search(r"born (?:on |in )?(.+?)(?:\.|$|,| in [A-Z])", first)
            d = None
            if m:
                d = parse_date(m.group(1).strip())
            if d:
                return [{"years": [d[0]], "month": d[1], "day": d[2], "text": fmt_date(d)}], "profile notes", [], True
            ys = age_years(first)
            if ys:
                return [{"years": ys, "month": None, "day": None,
                         "text": f"{ys[0]} or {ys[1]}"}], "profile notes", [], True
    # web search results: only those describing the same kind of listing in a country tied to the hit
    phrase = listing_phrase(h)
    hc = set(hit_countries(h))
    ev = []
    for s in ix.search_by_query.get(ix._qkey(h.get("name")), []):
        snip = s.get("snippet") or ""
        if phrase.lower() not in snip.lower():
            continue
        if not hc or not (set(countries_in_text(snip)) & hc):
            continue
        ys = snippet_years(snip)
        if ys:
            cands.append({"years": ys, "month": None, "day": None, "text": f"{ys[0]} or {ys[1]}"})
            ev.append(s.get("result_id"))
    if cands:
        return cands, "search results", ev, False
    return [], None, [], False


def earliest_report(h):
    best = None
    for m in REPORT_LINE.finditer(h.get("profile_notes") or ""):
        d = parse_date(m.group(1))
        if d and (best is None or d < best):
            best = d
    return best


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------
def dob_agrees(cd, cand):
    if cd is None:
        return False
    if cd[0] not in cand["years"]:
        return False
    if cand["month"] and cd[1] and cand["month"] != cd[1]:
        return False
    if cand["day"] and cd[2] and cand["day"] != cd[2]:
        return False
    return True


def dob_contradicts(cd, cand):
    if cd is None:
        return False
    if all(abs(cd[0] - y) > 1 for y in cand["years"]):
        return True
    if len(cand["years"]) == 1 and cd[0] == cand["years"][0]:
        if cand["month"] and cd[1] and cand["month"] != cd[1]:
            return True
        if cand["month"] and cd[1] and cand["day"] and cd[2] and cand["day"] != cd[2]:
            return True
    return False


def younger_than_16(cd, report):
    if cd is None or report is None:
        return False
    rd = to_pydate(report)
    if cd[1] and cd[2]:
        b = to_pydate(cd)
        if not b or not rd:
            return False
        age = rd.year - b.year - ((rd.month, rd.day) < (b.month, b.day))
        return age < 16
    # year only: certainly younger than 16 only if the year gap is at most 15
    return (report[0] - cd[0]) <= 15


# ---------------------------------------------------------------------------
# Decision for one hit and one person
# ---------------------------------------------------------------------------
def decide_person(ix, alert, h, cf):
    names = ix.names
    hn = [n for n in hit_names(h) if n]
    h_company = (h.get("entity_type") or "").lower().startswith("comp")
    # (code, sentence, evidence ids, fragile)
    contra = []

    # Type
    if h_company != cf["company"]:
        contra.append(("ENTITY_TYPE_MISMATCH",
                       f"The customer is {'a company' if cf['company'] else 'a person'} but the hit is "
                       f"{'a company' if h_company else 'a person'}.", list(cf["records"][:1]), False))

    # Deceased
    dd = parse_date(h.get("deceased_date"))
    screened = parse_date(alert.get("screened_at"))
    if dd and screened and (dd[0], dd[1] or 12, dd[2] or 28) < screened:
        contra.append(("DECEASED", f"The hit's profile gives a date of death of {fmt_date(dd)}, before the "
                                   f"customer was screened on {fmt_date(screened)}.", [], False))

    cd, cd_src = cf["dob"], cf["dob_src"]
    # Temporal
    rep = earliest_report(h)
    if rep and cd:
        fragile_t = bool(cf.get("dob_from_note"))
        if cf["company"]:
            if to_pydate(cd) and to_pydate(rep) and to_pydate(cd) > to_pydate(rep):
                contra.append(("TEMPORAL_IMPOSSIBILITY",
                               f"The customer was incorporated on {fmt_date(cd)} ({cd_src}), after the hit's "
                               f"profile reports activity on {fmt_date(rep)}.", [cd_src], fragile_t))
        elif younger_than_16(cd, rep):
            contra.append(("TEMPORAL_IMPOSSIBILITY",
                           f"The customer was born in {cd[0]} ({cd_src}), so they were at most "
                           f"{max(0, rep[0] - cd[0])} when the hit's profile reports activity on {fmt_date(rep)}.",
                           [cd_src], fragile_t))

    # Date of birth
    cands, dsrc, dev, hit_dob_fragile = hit_dobs(ix, h)
    dob_agree = any(dob_agrees(cd, c) for c in cands) if cands and cd else False
    dob_contra = bool(cands) and cd is not None and all(dob_contradicts(cd, c) for c in cands)
    if h_company and not cf["company"]:
        dob_agree = dob_contra = False
    if dob_contra:
        hd = "; ".join(c["text"] for c in cands)
        what = "listed date of birth is" if dsrc == "listed date of birth" else f"{dsrc} put its birth year at"
        fragile_d = bool(cf.get("dob_from_note")) or bool(hit_dob_fragile)
        contra.append(("DOB_MISMATCH", f"The customer's date of birth is {fmt_date(cd)} ({cd_src}) but the "
                                       f"hit's {what} {hd}.", [cd_src] + dev, fragile_d))

    # Names
    cust_is_company = cf["company"]
    vname = cf["verified_name"]
    name_pair = None
    name_ok_for_decision = True
    if vname:
        vparts = names.parts(vname, cust_is_company)
        if not cust_is_company and len(vparts) < 2:
            name_ok_for_decision = False
        name_pair = names.any_agree([vname], hn, cust_is_company)
        if name_ok_for_decision and name_pair is None:
            contra.append(("NAME_MISMATCH_VERIFIED",
                           f"The customer's verified name is {vname} ({cf['verified']['id']}), which does not "
                           f"match the hit's name {h.get('name')}.", [cf["verified"]["id"]],
                           bool(cf.get("name_from_note"))))
    else:
        rparts = [names.parts(n, cust_is_company) for n in cf["record_names"]]
        if not cust_is_company and not any(len(p) >= 2 for p in rparts):
            name_ok_for_decision = False
        name_pair = names.any_agree(cf["record_names"], hn, cust_is_company)
    name_agree = name_pair is not None and name_ok_for_decision

    # Location
    hc = hit_countries(h)
    cc = cf["countries"]
    loc_agree = bool(set(hc) & set(cc))
    loc_contra = bool(hc) and bool(cc) and not loc_agree
    if loc_contra and not (name_agree and dob_agree):
        contra.append(("LOCATION_MISMATCH",
                       f"The customer is linked only to {', '.join(sorted(cc))} but the hit is linked only to "
                       f"{', '.join(sorted(hc))}.", sorted(set(cc.values())), False))

    if contra:
        # SOP: clearing a real match is the worst mistake; when in doubt, REVIEW.
        # Unsure free-text parses may hint at a contradiction but must not clear alone.
        all_fragile = all(c[3] for c in contra)
        unusual = bool(cf.get("note_unusual"))
        if all_fragile and unusual:
            evid = []
            for c in contra[:2]:
                evid.extend(c[2])
            reason = ("A possible contradiction rests only on free-text parsing that is not reliable enough "
                      "to clear the hit, so a person must review it. " + " ".join(c[1] for c in contra[:2]))
            return "REVIEW", "INSUFFICIENT_DATA", reason, evid
        code, sent, ev, _frag = contra[0]
        reason = " ".join(c[1] for c in contra[:2])
        evid = []
        for c in contra[:2]:
            evid.extend(c[2])
        return "DIFFERENT_ENTITY", code, reason, evid

    agree_bits = []
    evid = []
    if dob_agree:
        hd = "; ".join(c["text"] for c in cands)
        agree_bits.append(f"The customer's date of birth {fmt_date(cd)} ({cd_src}) agrees with the hit's {hd}.")
        evid += [cd_src] + dev
    if loc_agree:
        common = sorted(set(hc) & set(cc))
        agree_bits.append(f"Both the customer and the hit are linked to {', '.join(common)}.")
        evid += [cc[c] for c in common]
    if name_agree:
        agree_bits.append(f"The customer's name agrees with the hit's name {name_pair[1]}.")
        if cf["verified"] and vname:
            evid.append(cf["verified"]["id"])
        else:
            evid.append(cf["records"][0])

    # Confirmations that rest only on fragile note parsing → REVIEW (same fail-safe as clears).
    # Title Case note names, note DOBs found only via a keyword *after* the date, or note DOB
    # used while the note's name check failed (so CRM names fill in) are not solid enough to confirm.
    fragile_confirm = False
    if name_agree and (dob_agree or (cf["company"] and h_company and loc_agree)):
        if cf.get("name_from_title_case"):
            fragile_confirm = True
        if cf.get("dob_from_note") and cf.get("dob_keyword_after_only"):
            fragile_confirm = True
        if cf.get("dob_from_note") and cf.get("note_name_failed") and not cf.get("verified_name"):
            fragile_confirm = True
    if fragile_confirm:
        reason = ("Agreement rests only on free-text parsing that is not reliable enough to confirm "
                  "the hit, so a person must review it. " + " ".join(agree_bits))
        return "REVIEW", "INSUFFICIENT_DATA", reason, evid

    if cf["company"] and h_company:
        if name_agree and loc_agree:
            return "SAME_ENTITY", "NAME_LOCATION_MATCH", " ".join(agree_bits), evid
    elif name_agree and dob_agree:
        # POLICY: "A country difference does not clear a hit whose name and date of birth agree: that hit is REVIEW."
        if loc_contra:
            tail = ("The name and date of birth agree but the countries differ, so the hit can be neither "
                    "cleared nor confirmed.")
            return "REVIEW", "INSUFFICIENT_DATA", " ".join(agree_bits + [tail]), evid
        code = "NAME_DOB_LOCATION_MATCH" if loc_agree else "NAME_DOB_MATCH"
        return "SAME_ENTITY", code, " ".join(agree_bits), evid

    tail = ("Nothing in the customer's records contradicts the hit, and the evidence does not show enough "
            "agreement to confirm it, so the hit can be neither cleared nor confirmed.")
    if not cands or cd is None:
        tail = ("Nothing in the customer's records contradicts the hit, and the date of birth cannot be "
                "compared with it, so the hit can be neither cleared nor confirmed.")
    if loc_contra and name_agree and dob_agree:
        tail = ("The name and date of birth agree but the countries differ, so the hit can be neither cleared "
                "nor confirmed.")
    return "REVIEW", "INSUFFICIENT_DATA", " ".join(agree_bits + [tail]), evid


def decide_hit(ix, alert, h):
    persons, path = resolve(ix, alert)
    if not persons:
        return {"decision": "REVIEW", "reason_code": "INSUFFICIENT_DATA", "customer_record_id": None,
                "reason": "No customer record in the system of record fits the screened details, so the hit "
                          "can be neither cleared nor confirmed.", "evidence": [], "path": path}
    results = []
    for p in persons:
        cf = customer_facts(ix, p, alert)
        results.append((p, decide_person(ix, alert, h, cf)))
    if len(results) == 1:
        p, (dec, code, reason, ev) = results[0]
        return {"decision": dec, "reason_code": code, "customer_record_id": p[0], "reason": reason,
                "evidence": _clean(ev), "path": path}
    decs = {r[1][0] for r in results}
    allev = []
    for p, r in results:
        allev.extend(p)
        allev.extend(r[3])
    recs = ", ".join("/".join(p) for p, _ in results)
    if len(decs) == 1:
        p, (dec, code, reason, ev) = results[0]
        return {"decision": dec, "reason_code": code, "customer_record_id": "AMBIGUOUS",
                "reason": f"{len(results)} different people fit the alert ({recs}) and each leads to the same "
                          f"decision. " + reason,
                "evidence": _clean(allev), "path": path}
    return {"decision": "REVIEW", "reason_code": "AMBIGUOUS_CUSTOMER_RECORD", "customer_record_id": "AMBIGUOUS",
            "reason": f"{len(results)} different people fit the alert ({recs}) and they lead to different "
                      f"decisions ({', '.join(sorted(decs))}), so a person must review it.",
            "evidence": _clean(allev), "path": path}


def _clean(ev):
    out = []
    for e in ev:
        if e and e not in out:
            out.append(e)
    return out
