# ClearGuard engine

For each screening hit we decide **SAME_ENTITY**, **DIFFERENT_ENTITY**, or **REVIEW**, following `POLICY.md` literally. We clear only when a fact contradicts the hit, confirm only when name and date of birth (or name and country for a company) agree and nothing contradicts them, and otherwise send the hit to **REVIEW**. An unsafe clear costs 60 points; when the evidence is thin we prefer REVIEW.

## Results on official `dev` (819 hits)

| Metric | Value |
|---|---|
| Practice labels | **50/50** on decision, reason code, and customer record |
| Wrongful clears | **0** |
| `validate.py --score` | decision score **100.0**, 0 problems |
| Decisions | **465** DIFFERENT_ENTITY / **122** SAME_ENTITY / **232** REVIEW (**72%** resolved automatically) |
| Reproducibility | 5 runs, byte-identical — MD5 `B9D645D65E66CD76C067984170E16830` |
| Runtime | ~10 s (Python 3 stdlib only) |
| Cost | **£0** (no API, no LLM) |
| SOP rule tests | **17** passing (`tests/test_sop_rules.py`) |
| Wording-mutation test | **0** true matches turned into DIFFERENT_ENTITY |

Tagged engine: `submission-engine` @ `ae502fe`.

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

**Customer facts.** `customer_facts()` takes the latest **approved** KYC check, or a KYC-channel note when that is all there is (principle 4: verified beats declared). Rejected and expired checks are ignored. Residence, nationality, document country and places notes say they lived become the country set.

**Hit facts.** `hit_dobs()` reads the `dobs` field, then the first paragraph of profile notes (an age at a dated event yields two possible birth years), then search snippets only when they carry the listing phrase for the hit’s category **and** a country tied to the hit. Companies use the `dobs` field only. Dated reports are the English lines `According to …; Month DD, YYYY:` via `earliest_report()`.

**Decide.** `decide_person()` tests contradictions first (time, deceased, DOB, location, verified name, entity type — principle 6). If none fire, it tests agreement (principle 7). Name and DOB that agree while every country differs become REVIEW, not a clear and not a confirm. `decide_hit()` runs that per person; if several people fit and disagree, the decision is `AMBIGUOUS_CUSTOMER_RECORD` with `customer_record_id` `AMBIGUOUS`; if they agree, that decision is kept and the id is still `AMBIGUOUS`.

## Evidence and policy trace

Every row cites only the IDs that decided the hit (`evidence`, `customer_record_id`), exactly as they appear in the files (principle 9). Pass `--debug` to attach a per-hit `trace`: principle number, the exact `POLICY.md` sentence, the fact sentences, whether a free-text guard fired (`fragile_guard`), and the resolution path. The reason-code ↔ principle map is generated from the engine’s `POLICY_RULES` table — see [`docs/POLICY_MAP.md`](../docs/POLICY_MAP.md).

## Determinism — no model, no prompts

The engine is pure Python 3 standard library: no LLM, no network, no randomness, stable sort orders. We chose that on purpose. Judges must be able to re-run the same folder and get the same bytes; every clear must point at a named record; and an unsafe clear is scored at 60. A generative model cannot give those guarantees.

## Safety on unseen wording

KYC notes are free text. Guards keep shaky parses from clearing or confirming:

- a placeholder or unverifiable note name cannot clear on name;
- a note DOB needs a birth keyword nearby, or must be the only non-created date in the note;
- Title Case note names, after-only keyword DOBs, and note DOBs paired with a failed name check cannot confirm SAME — they fall back to REVIEW.

A wording-mutation test rewrites DOB phrasing and name casing across the official set: **0** SAME or REVIEW hits became DIFFERENT_ENTITY.

## Three real cases

**H-58A39C — clear (`DOB_MISMATCH`).** Customer DOB 1965-03-28 (KYC-232AE0); hit lists 1962-09-10. Policy: every birth date the hit gives is contradicted when the year is more than one year outside, or months differ in the same year.

```json
{"hit_id": "H-58A39C", "alert_id": "A-2642A1", "decision": "DIFFERENT_ENTITY", "reason_code": "DOB_MISMATCH", "customer_record_id": "CUS-604925", "reason": "The customer's date of birth is 1965-03-28 (KYC-232AE0) but the hit's listed date of birth is 1962-09-10.", "evidence": ["KYC-232AE0"]}
```

**H-91AC66 — confirm (`NAME_DOB_LOCATION_MATCH`).** Verified DOB 1994-11-01 agrees with the hit’s 1994; 1995; both linked to Bangladesh; name agrees with Emran Ali. Policy: confirm a person when name and date of birth agree and nothing contradicts them.

```json
{"hit_id": "H-91AC66", "alert_id": "A-7EE3F4", "decision": "SAME_ENTITY", "reason_code": "NAME_DOB_LOCATION_MATCH", "customer_record_id": "CUS-962814", "reason": "The customer's date of birth 1994-11-01 (KYC-038F14) agrees with the hit's 1994; 1995. Both the customer and the hit are linked to Bangladesh. The customer's name agrees with the hit's name Emran Ali.", "evidence": ["KYC-038F14", "CUS-962814"]}
```

**H-6C7985 — review (two people fit).** CUS-618916 and CUS-885413 both fit the alert and lead to the same inconclusive path (name agrees, no comparable DOB). Policy: more than one person → `customer_record_id` is `AMBIGUOUS`; here both paths are REVIEW / `INSUFFICIENT_DATA`.

```json
{"hit_id": "H-6C7985", "alert_id": "A-688B31", "decision": "REVIEW", "reason_code": "INSUFFICIENT_DATA", "customer_record_id": "AMBIGUOUS", "reason": "2 different people fit the alert (CUS-618916, CUS-885413) and each leads to the same decision. Both the customer and the hit are linked to Pakistan. The customer's name agrees with the hit's name Mohammad Nadeem. Nothing in the customer's records contradicts the hit, and the date of birth cannot be compared with it, so the hit can be neither cleared nor confirmed.", "evidence": ["CUS-618916", "KYC-8DE62A", "CUS-885413", "NOTE-BC6437"]}
```

## Honest limits

Regex parsing of free text can miss wordings we have not seen; the mitigation is the REVIEW fallback, not a guessed clear. Location conflicts where name and DOB already agree go to REVIEW under the SOP, which correctly blocks unsafe clears but lowers automation (12 such hits on `dev`). We built first against the browse sample, then verified every gate on the official development set before freeze.

## How to run

```bash
system/run <data folder> <output file>
system/run <data folder> <output file> --debug          # adds path + policy trace per hit
python -m unittest tests.test_sop_rules                 # 17 SOP rule tests
```

Python 3 standard library only. Output is one JSON object per line: `hit_id`, `alert_id`, `decision`, `reason_code`, `customer_record_id`, `reason`, `evidence`.
