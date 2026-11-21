# SNIFF: Sanctions Name & Identity Fact Finder

Track 2 (Sanctions screening): is this screening hit really our customer?

Team: Jedidiah Onotu, Collins

For each screening hit we decide **SAME_ENTITY**, **DIFFERENT_ENTITY**, or **REVIEW**, following `POLICY.md` literally. We clear only when a fact contradicts the hit, confirm only when name and date of birth (or name and country for a company) agree and nothing contradicts them, and otherwise send the hit to **REVIEW**. An unsafe clear costs 60 points; when the evidence is thin we prefer REVIEW.

## Results on official `dev` (819 hits)

| Metric | Value |
|---|---|
| Practice labels | **50/50** on decision, reason code, and customer record |
| Wrongful clears | **0** |
| `validate.py --score` | decision score **100.0**, 0 problems |
| Decisions | **465** DIFFERENT_ENTITY / **122** SAME_ENTITY / **232** REVIEW (**72%** resolved automatically) |
| Reproducibility | 5 runs, byte-identical — MD5 `72bc532a9dfcaad410d69a8439eb833d` |
| Runtime | ~10 s (Python 3 stdlib only) |
| Cost | **£0** (no API, no LLM required) |
| SOP rule tests | **20** passing (`tests/test_sop_rules.py`) |
| Unseen-wording mutation | **0** SAME/REVIEW → DIFFERENT (`harness/unseen_wording.py`) |

50/50 and 0 unsafe clears are measured on the 50 practice labels only. The other 769 dev hits have no labels, which is why we built rule tests and mutation tests.

Reproduce the numbers:

```bash
# practice score (decision / reason code / customer record) + wrongful clears
python tools_score.py ../dev/practice_labels.jsonl output/dev.jsonl
python ../dev/validate.py --data ../dev --output output/dev.jsonl --score ../dev/practice_labels.jsonl

# md5 across 5 runs (must be identical)
for i in 1 2 3 4 5; do
  system/run ../dev output/_r$i.jsonl
  md5sum output/_r$i.jsonl   # or: CertUtil -hashfile output/_r$i.jsonl MD5
done

# wording-mutation: SAME/REVIEW -> DIFFERENT must stay 0
python3 harness/unseen_wording.py --data ../dev
```

## Architecture

```
alert
  -> resolve()          who is the customer?
  -> customer_facts()   verified name, DOB, countries
  -> hit_dobs() / hit_countries() / earliest_report()
  -> decide_person()    contradictions first
  -> decide_person()    then agreement
  -> else REVIEW
decide_hit() wraps multi-person / AMBIGUOUS cases
```

**Resolve.** `resolve()` follows the alert link in order: `account_ref`, then `login_handle`, then `email`. If several account holders share a link, `fits_screened()` keeps those whose name, DOB, country and city match what was screened. With no link, it searches customer name parts and applies the same filter. `group_persons()` then merges records that share a phone number and a full date of birth, or the same approved document number, into one person.

**Customer facts.** `customer_facts()` collects every **approved** identity check from both sources — KYC provider checks and KYC-channel notes — and takes the most recent by date (principle 4: “whether it is recorded by the KYC provider or only in a note by the onboarding team”). Rejected and expired checks are ignored. Failed / pending / rejected KYC **notes** yield no identity fields. Residence, nationality, document country and places notes say they lived become the country set.

**Hit facts.** `hit_dobs()` reads the `dobs` field, then the first paragraph of profile notes (an age at a dated event yields two possible birth years), then search snippets only when they carry the listing phrase for the hit’s category **and** a country tied to the hit. Companies use the `dobs` field only. Dated reports are the English lines `According to …; Month DD, YYYY:` via `earliest_report()`.

**Decide.** `decide_person()` tests contradictions first (time, deceased, DOB, location, verified name, entity type — principle 6). If none fire, it tests agreement (principle 7). Name and DOB that agree while every country differs become REVIEW, not a clear and not a confirm. Ambiguous numeric customer DOBs (`03/04/1965`) clear on `DOB_MISMATCH` only when every day/month reading contradicts the hit. `decide_hit()` runs that per person; if several people fit and disagree, the decision is `AMBIGUOUS_CUSTOMER_RECORD` with `customer_record_id` `AMBIGUOUS`; if they agree, that decision is kept and the id is still `AMBIGUOUS`.

## Evidence and policy trace

Every row cites only the IDs that decided the hit (`evidence`, `customer_record_id`), exactly as they appear in the files (principle 9). Pass `--debug` to attach a per-hit `trace`: principle number, the exact `POLICY.md` sentence, the fact sentences, whether a free-text guard fired (`fragile_guard`), and the resolution path. The reason-code ↔ principle map is generated from the engine’s `POLICY_RULES` table — see [`docs/POLICY_MAP.md`](../docs/POLICY_MAP.md).

Display the trace with [`console/trace.py`](../console/trace.py): it reads `system/run … --debug` JSONL and writes a static HTML page. It never decides anything; it only shows what the engine already decided. Generated HTML is gitignored because it contains dev data.

```bash
system/run ../dev output/debug.jsonl --debug
python3 console/trace.py --debug output/debug.jsonl --data ../dev --out /tmp/sniff-trace.html
```

## Determinism — rules first

The engine is pure Python 3 standard library by default: no LLM, no network, no randomness, stable sort orders. Judges must be able to re-run the same folder and get the same bytes; every clear must point at a named record; and an unsafe clear is scored at 60. We chose rules over a model for auditability and reproducibility. An LLM locator with code-side verification is our adaptive layer (see How SNIFF adapts).

## How SNIFF adapts

**The AI points. The code reads. The policy decides.**

When regex parsing misses a fact, an optional OpenRouter locator (`system/llm_locate.py`, branch `adaptive-llm` when merged) may return an exact quote from the source text. Our existing parsers and SOP rules still extract and decide. The locator never invents facts, never decides SAME/DIFFERENT/REVIEW, and stays off unless `OPENROUTER_API_KEY` is set and `SNIFF_LLM` is not `"off"`.

## Safety on unseen wording

KYC notes are free text. Guards keep shaky parses from clearing or confirming:

- a placeholder or unverifiable note name cannot clear on name;
- a note DOB needs a birth keyword nearby, or must be the only non-created date in the note;
- Title Case note names, after-only keyword DOBs, and note DOBs paired with a failed name check cannot confirm SAME — they fall back to REVIEW;
- failed / rejected / pending KYC notes yield no identity evidence.

`harness/unseen_wording.py` paraphrases DOB phrasing, Title Case names, residence notes, numeric MM/DD dates, shuffled paragraphs, and already-failed KYC wording across the official set: **0** SAME or REVIEW hits became DIFFERENT_ENTITY. On seed 7: 10 original clearances and 43 confirmations moved to REVIEW (safe conservatism); 761 decision+code pairs retained.

## Known gaps

- Unseen note wording falls back to REVIEW.
- Ambiguous numeric dates.
- Phone formats (`+44` versus `0`).
- Approximate ages (“in his 40s”) are not parsed.

## Three real cases

**H-58A39C — clear (`DOB_MISMATCH`).** Customer DOB 1965-03-28 (KYC-232AE0); hit lists 1962-09-10.

**Principle 6 (date of birth):** “every birth date the hit gives is contradicted: the customer's birth year is more than 1 year outside it, or both give a month in the same year and the months (or days) differ. One agreeing date is enough to prevent this.”

```json
{"hit_id": "H-58A39C", "alert_id": "A-2642A1", "decision": "DIFFERENT_ENTITY", "reason_code": "DOB_MISMATCH", "customer_record_id": "CUS-604925", "reason": "The customer's date of birth is 1965-03-28 (KYC-232AE0) but the hit's listed date of birth is 1962-09-10.", "evidence": ["KYC-232AE0"]}
```

**H-91AC66 — confirm (`NAME_DOB_LOCATION_MATCH`).** Verified DOB 1994-11-01 agrees with the hit’s 1994; 1995; both linked to Bangladesh; name agrees with Emran Ali.

**Principle 7:** “Confirm a person when name and date of birth agree and nothing contradicts them; a company when name and country agree and nothing contradicts them. Otherwise, `REVIEW`.”

```json
{"hit_id": "H-91AC66", "alert_id": "A-7EE3F4", "decision": "SAME_ENTITY", "reason_code": "NAME_DOB_LOCATION_MATCH", "customer_record_id": "CUS-962814", "reason": "The customer's date of birth 1994-11-01 (KYC-038F14) agrees with the hit's 1994; 1995. Both the customer and the hit are linked to Bangladesh. The customer's name agrees with the hit's name Emran Ali.", "evidence": ["KYC-038F14", "CUS-962814"]}
```

**H-6C7985 — review (two people fit).** CUS-618916 and CUS-885413 both fit the alert and lead to the same inconclusive path (name agrees, no comparable DOB). Here both paths are REVIEW / `INSUFFICIENT_DATA`.

**Principle 3:** “If more than one person fits an alert, decide the hit for each; if they all lead to the same decision, give it, otherwise the decision is `REVIEW` with `AMBIGUOUS_CUSTOMER_RECORD`. Either way `customer_record_id` is `AMBIGUOUS`.”

```json
{"hit_id": "H-6C7985", "alert_id": "A-688B31", "decision": "REVIEW", "reason_code": "INSUFFICIENT_DATA", "customer_record_id": "AMBIGUOUS", "reason": "2 different people fit the alert (CUS-618916, CUS-885413) and each leads to the same decision. Both the customer and the hit are linked to Pakistan. The customer's name agrees with the hit's name Mohammad Nadeem. Nothing in the customer's records contradicts the hit, and the date of birth cannot be compared with it, so the hit can be neither cleared nor confirmed.", "evidence": ["CUS-618916", "KYC-8DE62A", "CUS-885413", "NOTE-BC6437"]}
```

## Honest limits

Regex parsing of free text can miss wordings we have not seen; the mitigation is the REVIEW fallback, not a guessed clear. Location conflicts where name and DOB already agree go to REVIEW under the SOP, which correctly blocks unsafe clears but lowers automation (12 such hits on `dev`). Our rare-situation rule tests caught a bug in our first version: it confirmed name+DOB matches even when every country conflicted. We fixed it to REVIEW per principle 6 (“A country difference does not clear a hit whose name and date of birth agree: that hit is REVIEW”) and principle 7 (“…and nothing contradicts them”). That moved 12 dev hits from SAME_ENTITY to REVIEW. We built first against the browse sample, then verified every gate on the official development set before freeze.

## What's in the repo

- `system/` — the engine (scored)
- `output/dev.jsonl` — predictions on the dev set
- `tests/test_sop_rules.py` — 20 rule tests for situations rare in the dev data
- `docs/POLICY_MAP.md` — each reason code mapped to its exact policy sentence
- `harness/` — test-to-fail mutation harness (108 mutations, 0 unsafe clears) and `unseen_wording.py` (0 unsafe flips)
- `baseline/` — name-only foil baseline
- `console/trace.py` — static policy-trace viewer built on `--debug`

## How to run

```bash
system/run <data folder> <output file>
system/run <data folder> <output file> --debug          # adds path + policy trace per hit
python -m unittest tests.test_sop_rules                 # 20 SOP rule tests
python3 harness/unseen_wording.py --data <data folder>
```

Python 3 standard library only (optional adaptive locator is isolated). Output is one JSON object per line: `hit_id`, `alert_id`, `decision`, `reason_code`, `customer_record_id`, `reason`, `evidence`.
