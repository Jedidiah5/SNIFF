"""ClearGuard: evidence-driven sanctions identity resolution.

Pure Python standard library. Every decision is made by deterministic code that
follows the screening SOP (POLICY.md). No randomness, no network calls by default.
"""
import json
import os
import re
import unicodedata
from datetime import date

# ---------------------------------------------------------------------------
# Constants from the SOP (used as defaults; name_variants.json is merged in)
# ---------------------------------------------------------------------------
DEFAULT_VARIANT_GROUPS = """muhammad, mohammed, mohammad, mohamed, muhammed, mohamad, mohd, muhamad
ahmed, ahmad, ahmet
abdul, abdel, abd
abdullah, abdallah, abdulla
abubakar, abubakr, aboubakar, bubakar
ibrahim, ebrahim, ibraheem, brahim
yusuf, yousef, youssef, yousuf, josef, joseph, joe
umar, omar, omer
usman, uthman, othman, osman
hussein, hussain, husain, hossain, hosein
hassan, hasan
ali, aly
faruk, farouk, faruq, farooq, faroq
sulaiman, suleiman, sulayman, suleman, solomon
aminu, amin, ameen
anthony, antony, tony, antonio
robert, rob, robbie, bob, bobby, roberto
william, will, bill, billy, liam, guillermo
richard, rick, ricky, dick, ricardo
james, jim, jimmy, jamie, jaime
john, johnny, jon, jack, juan, jean, johann, johannes
michael, mike, mick, mikey, miguel, michel, michele
daniel, dan, danny, dani
david, dave, davey, davit
christopher, chris, kristopher, cristobal
matthew, matt, mateo, matteo, mathieu
andrew, andy, drew, andres, andrea, andreas
thomas, tom, tommy, tomas, tomasz
joshua, josh
nicholas, nick, nicolas, nicola, nikola, nikolai
alexander, alex, alejandro, alessandro, aleksandr, sasha
peter, pete, pedro, pietro, pierre
paul, pablo, paolo
stephen, steven, steve, stefan, esteban, stefano
joseph, joe, jose, giuseppe, jozef
francis, frank, francisco, francesco, franco, francois
charles, charlie, chuck, carlos, carlo, karl, karol
edward, ed, eddie, ted, eduardo, edoardo
henry, harry, enrique, enrico, henrik, heinrich
mark, marc, marco
markus, marcus, marcos
catherine, katherine, kathryn, kate, katie, cathy, catalina, katarzyna
elizabeth, liz, beth, betty, elisabeth, isabel
margaret, maggie, meg, peggy, margarita
jennifer, jen, jenny
rebecca, becky
susan, sue, susanna, susana
maria, mary, marie, mariya
olumide, mide
oluwaseun, seun
babatunde, tunde
oluwatobiloba, tobi
chukwuemeka, emeka
ifeanyichukwu, ifeanyi
nnamdi, namdi"""
DEFAULT_LEGAL_FORMS = ("ab ag as asa bv co company corp corporation gmbh inc kg limited llc llp lp ltd "
                       "na nv oy oyj plc sa sarl sas se sf sl spa srl").split()
PLACEHOLDERS = {"na", "n/a", "test", "unknown", "xxx", "none", "null", "nil", "tbd", "n", "a"}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

LISTING_PHRASES = {
    "sanctions": "a sanctioned individual",
    "pep": "a politically exposed person",
    "enforcement": "the subject of enforcement action",
    "adverse media": "named in adverse media",
    "soe": "a state-owned enterprise official",
}
OTHER_LISTING = "named on a watchlist"

# Country names, ISO codes and demonyms seen in customer-side data, plus common ones.
COUNTRY_ALIASES = {
    "us": "United States", "usa": "United States", "united states of america": "United States",
    "american": "United States", "u.s.": "United States",
    "gb": "United Kingdom", "uk": "United Kingdom", "british": "United Kingdom", "great britain": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom", "wales": "United Kingdom",
    "ng": "Nigeria", "nigerian": "Nigeria", "de": "Germany", "german": "Germany",
    "es": "Spain", "spanish": "Spain", "fr": "France", "french": "France",
    "bd": "Bangladesh", "bangladeshi": "Bangladesh", "it": "Italy", "italian": "Italy",
    "ie": "Ireland", "irish": "Ireland", "pl": "Poland", "polish": "Poland",
    "in": "India", "indian": "India", "ca": "Canada", "canadian": "Canada",
    "nl": "Netherlands", "dutch": "Netherlands", "the netherlands": "Netherlands",
    "au": "Australia", "australian": "Australia", "ke": "Kenya", "kenyan": "Kenya",
    "at": "Austria", "austrian": "Austria", "za": "South Africa", "south african": "South Africa",
    "pk": "Pakistan", "pakistani": "Pakistan", "sg": "Singapore", "singaporean": "Singapore",
    "se": "Sweden", "swedish": "Sweden", "rs": "Serbia", "serbian": "Serbia",
    "dk": "Denmark", "danish": "Denmark", "ec": "Ecuador", "ecuadorian": "Ecuador",
    "pt": "Portugal", "portuguese": "Portugal", "th": "Thailand", "thai": "Thailand",
    "br": "Brazil", "brazilian": "Brazil", "ch": "Switzerland", "swiss": "Switzerland",
    "no": "Norway", "norwegian": "Norway", "vn": "Vietnam", "vietnamese": "Vietnam", "viet nam": "Vietnam",
    "gh": "Ghana", "ghanaian": "Ghana", "pa": "Panama", "panamanian": "Panama",
    "me": "Montenegro", "montenegrin": "Montenegro", "ht": "Haiti", "haitian": "Haiti",
    "sy": "Syria", "syrian": "Syria", "dz": "Algeria", "algerian": "Algeria",
    "cz": "Czech Republic", "czech": "Czech Republic", "czechia": "Czech Republic",
    "kp": "North Korea", "north korean": "North Korea", "ru": "Russia", "russian": "Russia",
    "russian federation": "Russia", "nz": "New Zealand", "new zealander": "New Zealand",
    "ci": "Cote D'Ivoire", "ivorian": "Cote D'Ivoire", "côte d'ivoire": "Cote D'Ivoire",
    "cote d'ivoire": "Cote D'Ivoire", "ivory coast": "Cote D'Ivoire",
    "pe": "Peru", "peruvian": "Peru", "am": "Armenia", "armenian": "Armenia",
    "ma": "Morocco", "moroccan": "Morocco", "id": "Indonesia", "indonesian": "Indonesia",
    "mx": "Mexico", "mexican": "Mexico", "hu": "Hungary", "hungarian": "Hungary",
    "ro": "Romania", "romanian": "Romania", "lb": "Lebanon", "lebanese": "Lebanon",
    "md": "Moldova", "moldovan": "Moldova", "ae": "United Arab Emirates", "emirati": "United Arab Emirates",
    "uae": "United Arab Emirates", "do": "Dominican Republic", "dominican": "Dominican Republic",
    "ar": "Argentina", "argentine": "Argentina", "argentinian": "Argentina",
    "jm": "Jamaica", "jamaican": "Jamaica", "il": "Israel", "israeli": "Israel",
    "si": "Slovenia", "slovenian": "Slovenia", "co": "Colombia", "colombian": "Colombia",
    "fi": "Finland", "finnish": "Finland", "cn": "China", "chinese": "China",
    "be": "Belgium", "belgian": "Belgium", "tr": "Turkey", "turkish": "Turkey", "türkiye": "Turkey",
    "ir": "Iran", "iranian": "Iran", "iq": "Iraq", "iraqi": "Iraq", "eg": "Egypt", "egyptian": "Egypt",
    "kr": "South Korea", "south korean": "South Korea", "korea": "South Korea",
    "jp": "Japan", "japanese": "Japan", "my": "Malaysia", "malaysian": "Malaysia",
    "ph": "Philippines", "filipino": "Philippines", "ua": "Ukraine", "ukrainian": "Ukraine",
    "gr": "Greece", "greek": "Greece", "af": "Afghanistan", "afghan": "Afghanistan",
    "palestine": "Palestina", "palestinian": "Palestina", "macao": "Macao", "macau": "Macao",
    "macao special administrative region of china": "Macao",
    "hong kong": "Hong Kong", "uk overseas": "United Kingdom",
}
KNOWN_COUNTRIES = sorted(set(COUNTRY_ALIASES.values()) | {
    "Afghanistan", "Albania", "Argentina", "Armenia", "Australia", "Austria", "Azerbaijan", "Bahrain",
    "Bangladesh", "Belgium", "Bosnia and Herzegovina", "Brazil", "British Virgin Islands", "Canada", "China",
    "Colombia", "Costa Rica", "Denmark", "Dominican Republic", "Ecuador", "Egypt", "Eritrea", "Estonia",
    "Ethiopia", "Finland", "France", "Georgia", "Germany", "Ghana", "Guatemala", "Haiti", "Honduras",
    "Hungary", "Iceland", "India", "Iran", "Iraq", "Ireland", "Italy", "Jamaica", "Japan", "Jersey",
    "Jordan", "Kenya", "Kosovo", "Latvia", "Lebanon", "Liechtenstein", "Luxembourg", "Malaysia", "Mexico",
    "Moldova", "Montenegro", "Morocco", "New Zealand", "Nicaragua", "Nigeria", "North Korea",
    "Northern Mariana Islands", "Norway", "Pakistan", "Palestina", "Panama", "Paraguay", "Peru",
    "Philippines", "Poland", "Portugal", "Puerto Rico", "Romania", "Russia", "Serbia", "Sierra Leone",
    "Singapore", "Slovenia", "Somalia", "South Africa", "South Korea", "Spain", "Sudan", "Sweden",
    "Switzerland", "Syria", "Thailand", "Trinidad and Tobago", "Turkey", "Uganda", "Ukraine",
    "United Arab Emirates", "United Kingdom", "United States", "Uruguay", "Venezuela", "Vietnam",
    "Czech Republic", "Indonesia", "Israel", "Algeria", "Cote D'Ivoire", "Greece", "Slovakia",
    "Croatia", "Bulgaria", "Lithuania", "Cyprus", "Malta", "Monaco", "Qatar", "Saudi Arabia", "Kuwait",
    "Oman", "Yemen", "Libya", "Tunisia", "Senegal", "Cameroon", "Tanzania", "Zimbabwe", "Zambia",
    "Belarus", "Kazakhstan", "Uzbekistan", "Chile", "Bolivia", "Cuba", "El Salvador", "Myanmar",
    "Cambodia", "Laos", "Nepal", "Sri Lanka", "Hong Kong", "Macao", "Taiwan", "Ukraine", "Gibraltar",
    "Cayman Islands", "Bermuda", "Bahamas", "Barbados", "Isle of Man", "Guernsey", "North Macedonia",
})
NOT_COUNTRIES = {"international", "europe", "global", "worldwide", "unknown", "n/a", "na", ""}


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_country(v):
    """Return a canonical country name, or None."""
    if v is None:
        return None
    s = re.sub(r"\[.*?\]", "", str(v)).strip().strip(".")
    if not s:
        return None
    low = strip_accents(s).lower().strip()
    if low in NOT_COUNTRIES:
        return None
    if low in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[low]
    for c in KNOWN_COUNTRIES:
        if strip_accents(c).lower() == low:
            return c
    return s.strip()


_COUNTRY_SCAN = None


def countries_in_text(text):
    """Find country names or demonyms mentioned in free text (whole-word match)."""
    global _COUNTRY_SCAN
    if _COUNTRY_SCAN is None:
        terms = {}
        for c in KNOWN_COUNTRIES:
            terms[strip_accents(c).lower()] = c
        for k, v in COUNTRY_ALIASES.items():
            if len(k) > 3:  # skip 2-3 letter codes in prose
                terms[strip_accents(k).lower()] = v
        pats = sorted(terms, key=len, reverse=True)
        _COUNTRY_SCAN = (re.compile(r"\b(" + "|".join(re.escape(p) for p in pats) + r")\b"), terms)
    rx, terms = _COUNTRY_SCAN
    low = strip_accents(text or "").lower()
    return sorted({terms[m.group(1)] for m in rx.finditer(low)})


def as_list(v):
    """Normalise a field that may be a JSON list or a ';'-separated string (browse workbook)."""
    if v is None:
        return []
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict):
                # keep structured values as one item (caller decides how to read them)
                out.append(x)
            else:
                out.extend(as_list(x))
        return out
    if isinstance(v, dict):
        return [v]
    s = str(v).strip()
    if not s:
        return []
    return [p.strip() for p in s.split(";") if p.strip()]


def normalize_alert(a):
    """Official JSONL nests screened fields under customer{}; browse/flat form keeps them on top."""
    out = dict(a)
    cust = out.get("customer")
    if isinstance(cust, dict):
        mapping = (("name", "customer_name"), ("entity_type", "entity_type"),
                   ("dob", "dob"), ("country", "country"), ("city", "city"))
        for src, dst in mapping:
            if out.get(dst) in (None, "") and cust.get(src) not in (None, ""):
                out[dst] = cust[src]
    return out


# ---------------------------------------------------------------------------
# Dates. A partial date is (year, month or None, day or None).
# ---------------------------------------------------------------------------
def parse_date(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        y = int(s)
        return (y, None, None) if 1000 < y < 3000 else None
    t = str(s).strip().strip(".")
    if not t or t.lower() in ("none", "null", "unknown"):
        return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?", t)
    if m:
        return (int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", t)
    if m:
        return (int(m[1]), int(m[2]), None)
    m = re.fullmatch(r"(\d{4})", t)
    if m:
        return (int(m[1]), None, None)
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t)
    if m:  # day/month/year (UK style; the data never has month > 12 in 2nd slot)
        a, b = int(m[1]), int(m[2])
        if b > 12 and a <= 12:
            a, b = b, a
        return (int(m[3]), b, a)
    m = re.fullmatch(r"([A-Za-z]+)\.? (\d{1,2}),? (\d{4})", t)
    if m and m[1].lower() in MONTHS:
        return (int(m[3]), MONTHS[m[1].lower()], int(m[2]))
    m = re.fullmatch(r"(\d{1,2}) ([A-Za-z]+)\.?,? (\d{4})", t)
    if m and m[2].lower() in MONTHS:
        return (int(m[3]), MONTHS[m[2].lower()], int(m[1]))
    m = re.fullmatch(r"([A-Za-z]+)\.? (\d{4})", t)
    if m and m[1].lower() in MONTHS:
        return (int(m[2]), MONTHS[m[1].lower()], None)
    return None


DATE_IN_TEXT = re.compile(
    r"(\d{4}-\d{1,2}-\d{1,2})|(\d{1,2}/\d{1,2}/\d{4})|"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\.? \d{1,2},? \d{4})|"
    r"(\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December),? \d{4})",
    re.I)


def dates_in_text(text):
    out = []
    for m in DATE_IN_TEXT.finditer(text or ""):
        d = parse_date(m.group(0))
        if d:
            out.append((m.group(0), d))
    return out


def fmt_date(d):
    if d is None:
        return "unknown"
    y, m, dd = d
    if m is None:
        return f"{y}"
    if dd is None:
        return f"{y}-{m:02d}"
    return f"{y}-{m:02d}-{dd:02d}"


def full_date(d):
    return d is not None and d[1] is not None and d[2] is not None


def to_pydate(d):
    try:
        return date(d[0], d[1] or 1, d[2] or 1)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Names (SOP principle 8)
# ---------------------------------------------------------------------------
class Names:
    def __init__(self, groups, legal_forms):
        self.group_of = {}
        for gi, g in enumerate(groups):
            for w in g:
                self.group_of.setdefault(strip_accents(w).lower(), set()).add(gi)
        self.legal = {strip_accents(x).lower().strip(".") for x in legal_forms}

    def parts(self, name, company=False):
        if not name:
            return []
        s = strip_accents(str(name)).lower()
        s = re.sub(r"\(.*?\)|\[.*?\]|\{.*?\}", " ", s)
        s = s.replace("n/a", " ")
        s = re.sub(r"[^a-z0-9]+", " ", s)
        out = []
        for p in s.split():
            if len(p) < 2:  # initials are not parts
                continue
            if p in PLACEHOLDERS or re.search(r"\d", p):
                continue
            if company and p in self.legal:
                continue
            if p not in out:
                out.append(p)
        return out

    @staticmethod
    def _edits(a, b):
        if abs(len(a) - len(b)) > 2:
            return 99
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]

    def part_match(self, a, b):
        if a == b:
            return True
        ga, gb = self.group_of.get(a), self.group_of.get(b)
        if ga and gb and ga & gb:
            return True
        short = min(len(a), len(b))
        if short < 4:
            return False
        limit = 1 if short <= 6 else 2
        return self._edits(a, b) <= limit

    def agree(self, A, B):
        """Do two name-part lists agree? Returns (bool, matched_count)."""
        if not A or not B:
            return False, 0
        if len(A) > len(B):
            A, B = B, A
        usedB = set()
        matched = 0
        for a in A:
            hit = None
            for j, b in enumerate(B):
                if j not in usedB and self.part_match(a, b):
                    hit = (j,)
                    break
            if hit is None:  # written together vs apart: a == b1+b2
                for j, b1 in enumerate(B):
                    for k, b2 in enumerate(B):
                        if j != k and j not in usedB and k not in usedB and a == b1 + b2:
                            hit = (j, k)
                            break
                    if hit:
                        break
            if hit is None:  # b == a1+a2 handled from the other side
                for j, b in enumerate(B):
                    if j in usedB:
                        continue
                    for a2 in A:
                        if a2 != a and (b == a + a2 or b == a2 + a):
                            hit = (j,)
                            break
                    if hit:
                        break
            if hit is not None:
                usedB.update(hit)
                matched += 1
        ok = matched >= 2 or matched == len(A)
        return ok, matched

    def any_agree(self, names_a, names_b, company=False):
        """Return the first (name_a, name_b) pair that agrees, or None."""
        for na in names_a:
            pa = self.parts(na, company)
            if not pa:
                continue
            for nb in names_b:
                pb = self.parts(nb, company)
                if pb and self.agree(pa, pb)[0]:
                    return na, nb
        return None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# Decision-facing inputs only. Practice / ground-truth labels must never be loaded here —
# evaluation tools (tools_score.py, harness seed selection, validate.py) read them separately.
FILE_KEYS = {
    "alerts": ["alert"], "hits": ["hit"], "customers": ["customer"], "accounts": ["account"],
    "onboarding": ["onboard"], "kyc": ["kyc", "check", "identity"], "notes": ["note"],
    "search": ["search"],
}

# Filenames that are evaluation-only. Never match these into FILE_KEYS buckets.
_EVAL_ONLY_NAME_PARTS = ("practice", "label", "labels", "answer", "ground_truth", "ground-truth")


def _is_eval_only_filename(fn):
    low = fn.lower()
    return any(part in low for part in _EVAL_ONLY_NAME_PARTS)


def load_data(folder):
    files = {}
    for root, _, fnames in os.walk(folder):
        for fn in sorted(fnames):
            files[fn] = os.path.join(root, fn)
    data = {k: [] for k in FILE_KEYS}
    used = set()
    order = ["onboarding", "kyc", "search", "alerts", "hits", "customers", "accounts", "notes"]
    for key in order:
        for fn, path in sorted(files.items()):
            if not fn.endswith(".jsonl") or fn in used or _is_eval_only_filename(fn):
                continue
            low = fn.lower()
            if any(k in low for k in FILE_KEYS[key]):
                data[key] = _read_jsonl(path)
                used.add(fn)
                break
    data["alerts"] = [normalize_alert(a) for a in data["alerts"]]
    groups = [[w.strip() for w in line.split(",") if w.strip()] for line in DEFAULT_VARIANT_GROUPS.splitlines()]
    legal = list(DEFAULT_LEGAL_FORMS)
    for fn, path in files.items():
        if fn.lower().startswith("name_variants") and fn.endswith(".json"):
            try:
                g2, l2 = _parse_variants(json.load(open(path, encoding="utf-8")))
                if g2:
                    groups = groups + g2
                if l2:
                    legal = sorted(set(legal) | set(l2))
            except Exception:
                pass
    data["names"] = Names(groups, legal)
    return data


def _parse_variants(obj):
    groups, legal = [], []

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k.lower())
        elif isinstance(o, list):
            if o and all(isinstance(x, str) for x in o):
                if "legal" in key or "form" in key or "compan" in key:
                    legal.extend(o)
                else:
                    groups.append(o)
            else:
                for x in o:
                    walk(x, key)
        elif isinstance(o, str) and ("legal" in key or "form" in key):
            legal.extend(w.strip() for w in o.split(","))
    walk(obj)
    return groups, legal
