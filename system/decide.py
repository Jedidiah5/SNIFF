"""Customer resolution, fact gathering and SOP decisions."""
import re
from collections import defaultdict

from engine import (as_list, parse_date, dates_in_text, fmt_date, full_date, to_pydate, norm_country,
                    countries_in_text, strip_accents, MONTHS, LISTING_PHRASES, OTHER_LISTING)


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
NOT_NAME = {"DOB", "ID", "KYC", "PEP", "SOE", "UK", "US", "USA", "UAE", "EU"}


def parse_kyc_note(note):
    text = note.get("text") or ""
    created = parse_date(note.get("created_at"))
    name = None
    best = ""
    for m in CAPS_NAME.finditer(text):
        words = [w for w in m.group(1).split() if w not in NOT_NAME]
        cand = " ".join(words)
        if len(cand) > len(best):
            best = cand
    name = best or None
    dob = None
    for raw, d in dates_in_text(text):
        if created and d == created:
            continue
        if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", raw) and created is None and dob is not None:
            continue
        dob = d if dob is None else dob
    if dob is None:
        ds = [d for _, d in dates_in_text(text)]
        if len(ds) >= 2:
            dob = min(ds)
    countries = countries_in_text(text)
    return {"name": name, "dob": dob, "country": countries[0] if countries else None,
            "date": created, "id": note.get("note_id"), "source": "note"}


def customer_facts(ix, person):
    """Facts for one person (list of record ids)."""
    recs = [ix.cust[r] for r in person]
    verified = []
    for rid in person:
        for k in ix.kyc_checks(rid):
            if (k.get("result") or "").lower() != "approved":
                continue
            verified.append({"name": k.get("verified_name"), "dob": parse_date(k.get("verified_dob")),
                             "country": norm_country(k.get("document_country")),
                             "date": parse_date(k.get("checked_at")), "id": k.get("check_id"), "source": "kyc"})
    notes_seen = set()
    lived = {}
    for rid in person:
        for n in ix.kyc_notes(rid):
            if n.get("note_id") in notes_seen:
                continue
            notes_seen.add(n.get("note_id"))
            if (n.get("channel") or "").lower() == "kyc":
                v = parse_kyc_note(n)
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
    return {
        "records": person, "company": company, "verified": latest,
        "verified_name": latest["name"] if latest else None,
        "record_names": names, "dob": dob, "dob_src": dob_src,
        "countries": countries, "entity_type": "Company" if company else "Individual",
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
    re.compile(r"\bwas (\d{1,3})\b", re.I),
    re.compile(r",\s*(\d{1,3})\s*,"),
    re.compile(r",\s*(\d{1,3})\s*(?:was|is|who|served|appeared|participated|gave|achieved|accepted|identified|a |an |the )", re.I),
]


def age_years(text):
    """An age at a dated time gives two possible birth years."""
    age = None
    for p in AGE_PATTERNS:
        m = p.search(text)
        if m and 0 < int(m.group(1)) < 120:
            age = int(m.group(1))
            break
    my = MONTH_YEAR.search(text)
    yr = int(my.group(2)) if my else None
    if yr is None:
        m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
        yr = int(m.group(1)) if m else None
    if age is None or yr is None:
        return None
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
    """Return (candidates, source_label, evidence_ids). Each candidate: dict(years, month, day)."""
    cands = []
    for v in as_list(h.get("dobs")):
        d = parse_date(v)
        if d:
            cands.append({"years": [d[0]], "month": d[1], "day": d[2], "text": fmt_date(d)})
    if cands:
        return cands, "listed date of birth", []
    notes = (h.get("profile_notes") or "").strip()
    if notes:
        first = re.split(r"\n\s*\n", notes)[0].strip()
        if not first.startswith("According to"):
            m = re.search(r"born (?:on |in )?(.+?)(?:\.|$|,| in [A-Z])", first)
            d = None
            if m:
                d = parse_date(m.group(1).strip())
            if d:
                return [{"years": [d[0]], "month": d[1], "day": d[2], "text": fmt_date(d)}], "profile notes", []
            ys = age_years(first)
            if ys:
                return [{"years": ys, "month": None, "day": None, "text": f"{ys[0]} or {ys[1]}"}], "profile notes", []
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
        return cands, "search results", ev
    return [], None, []


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
    contra = []  # (code, sentence, evidence ids)
    ev_base = []

    # Type
    if h_company != cf["company"]:
        contra.append(("ENTITY_TYPE_MISMATCH",
                       f"The customer is {'a company' if cf['company'] else 'a person'} but the hit is "
                       f"{'a company' if h_company else 'a person'}.", list(cf["records"][:1])))

    # Deceased
    dd = parse_date(h.get("deceased_date"))
    screened = parse_date(alert.get("screened_at"))
    if dd and screened and (dd[0], dd[1] or 12, dd[2] or 28) < screened:
        contra.append(("DECEASED", f"The hit's profile gives a date of death of {fmt_date(dd)}, before the "
                                   f"customer was screened on {fmt_date(screened)}.", []))

    cd, cd_src = cf["dob"], cf["dob_src"]
    # Temporal
    rep = earliest_report(h)
    if rep and cd:
        if cf["company"]:
            if to_pydate(cd) and to_pydate(rep) and to_pydate(cd) > to_pydate(rep):
                contra.append(("TEMPORAL_IMPOSSIBILITY",
                               f"The customer was incorporated on {fmt_date(cd)} ({cd_src}), after the hit's "
                               f"profile reports activity on {fmt_date(rep)}.", [cd_src]))
        elif younger_than_16(cd, rep):
            contra.append(("TEMPORAL_IMPOSSIBILITY",
                           f"The customer was born in {cd[0]} ({cd_src}), so they were at most "
                           f"{max(0, rep[0] - cd[0])} when the hit's profile reports activity on {fmt_date(rep)}.",
                           [cd_src]))

    # Date of birth
    cands, dsrc, dev = hit_dobs(ix, h)
    dob_agree = any(dob_agrees(cd, c) for c in cands) if cands and cd else False
    dob_contra = bool(cands) and cd is not None and all(dob_contradicts(cd, c) for c in cands)
    if h_company and not cf["company"]:
        dob_agree = dob_contra = False
    if dob_contra:
        hd = "; ".join(c["text"] for c in cands)
        what = "listed date of birth is" if dsrc == "listed date of birth" else f"{dsrc} put its birth year at"
        contra.append(("DOB_MISMATCH", f"The customer's date of birth is {fmt_date(cd)} ({cd_src}) but the "
                                       f"hit's {what} {hd}.", [cd_src] + dev))

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
                           f"match the hit's name {h.get('name')}.", [cf["verified"]["id"]]))
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
                       f"{', '.join(sorted(hc))}.", sorted(set(cc.values()))))

    if contra:
        code, sent, ev = contra[0]
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

    if cf["company"] and h_company:
        if name_agree and loc_agree:
            return "SAME_ENTITY", "NAME_LOCATION_MATCH", " ".join(agree_bits), evid
    elif name_agree and dob_agree:
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
        cf = customer_facts(ix, p)
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
