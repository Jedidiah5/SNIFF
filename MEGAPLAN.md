# ClearGuard MEGAPLAN

Track 2 (Sanctions screening), Grok Bot London Financial Crime Hackathon. Code freeze **17:00**.
Open this file in Cursor and work through it top to bottom.

---

## 1. Where we are (handover at ~13:05)

The scored engine works end to end.

| Check | Result |
|---|---|
| Practice labels (50) | **50/50 decisions, 50/50 reason codes, 50/50 customer records** |
| Wrongful clears on practice labels | **0** |
| Full dev set (819 hits, built from the browse workbook) | 465 DIFFERENT, 134 SAME, 220 REVIEW, so **73% auto-resolved** |
| Reproducibility | 5 runs, byte-identical output (same md5) |
| Runtime | ~7 seconds for all 819 hits (limit is 30 min) |

Caveat: these numbers come from JSONL **converted from the browse workbook**, not the official `dev/` folder. Step 3.1 fixes that.

---

## 2. How the engine works (learn this, the judges will ask)

```
alert + hit
  -> 1. resolve the customer   (decide.py: resolve, group_persons)
  -> 2. customer facts         (decide.py: customer_facts)
  -> 3. hit facts              (decide.py: hit_dobs, hit_countries, earliest_report)
  -> 4. contradictions first   (decide.py: decide_person)
  -> 5. agreement to confirm   (decide.py: decide_person)
  -> 6. otherwise REVIEW
  -> output line: decision, reason_code, customer_record_id, reason, evidence
```

1. **Resolve the customer (SOP principles 2 and 3).** Follow the alert's link: `account_ref -> accounts -> customer_id`, else `login_handle -> accounts`, else `email -> customers`. If a link gives several holders (a joint account), keep the ones whose record fits the screened name, DOB, country and city. If there's no link, search all customers by name part and keep the records that fit. Then group records into **people**: same phone **and** same full DOB, or the same document number on approved KYC checks. Several people means each is decided separately: same decision gives `customer_record_id = AMBIGUOUS`; different decisions give `REVIEW / AMBIGUOUS_CUSTOMER_RECORD`.
2. **Customer facts.** The **most recent approved** identity check wins. It can come from the KYC provider (`customer -> accounts -> onboarding -> kyc_applicant_id -> kyc_checks`) or from a KYC note filed under the customer's email (we parse the CAPS name, the DOB and the document country). Rejected or expired checks are ignored. Countries = residence + nationality on every record + verified document country + countries named in support notes ("lived and worked in X").
3. **Hit facts.** DOB comes from the `dobs` field. Failing that, from the first paragraph of the profile notes ("born in 1966", or "aged 30 in November 1998", which gives 1967 or 1968). Failing that, from **web search results**, used only when the snippet names the hit's kind of listing (e.g. "a politically exposed person" for PEP) **and** a country tied to the hit. Countries come from countries, nationality, citizenship, the last part of each address, and place of birth. Dated reports are the "According to ...; Month DD, YYYY:" lines.
4. **Clear only on a contradiction** (any one is enough):
   - TYPE: person vs company
   - DECEASED: died before the screening date
   - TEMPORAL: under 16 at the earliest dated report, or a company incorporated after it
   - DOB: every hit birth date contradicted (more than 1 year off, or the same year with a different month or day)
   - NAME: the verified legal name agrees with none of the hit's names
   - LOCATION: no country in common. **This one never clears if name and DOB agree**; that case goes to REVIEW.
5. **Confirm only on agreement.** A person when name and DOB agree (`NAME_DOB_LOCATION_MATCH` if a country is shared too, else `NAME_DOB_MATCH`). A company when name and country agree (`NAME_LOCATION_MATCH`).
6. **Everything else is REVIEW / INSUFFICIENT_DATA.**

**Names (principle 8)** live in `engine.py: Names`:
- Lowercase, strip accents, drop anything in brackets, punctuation, initials and placeholders (NA, TEST...), plus legal forms for companies.
- Two parts match if they are identical, in the same `name_variants` group, written together vs apart, or within 1 edit (4–6 letters) or 2 edits (7+ letters).
- Names agree if 2 or more parts match, or every part of the shorter name matches.

**Why it's reproducible:** no LLM, no randomness, sorted output. Same input, same bytes.

---

## 3. Task list, split for two people

### 3.1 FIRST, both of us (15 min): run on the official data
- [ ] On the hackathon site, open Track 2 and click **Get the dataset**. Put the `dev/` folder **next to** the repo, not inside it.
- [ ] Run: `system/run ../dev output/dev.jsonl`
- [ ] Run the official validator: `python3 ../dev/validate.py output/dev.jsonl` and `python3 ../dev/validate.py output/dev.jsonl --score ../dev/practice_labels.jsonl` (check the exact usage in the data's README).
- [ ] Also run our scorer: `python3 tools_score.py ../dev/practice_labels.jsonl output/dev.jsonl -v`
- [ ] If anything breaks, it's almost certainly a **field-format difference** between the workbook and the real JSONL. Usual suspects: lists instead of `"a; b"` strings, or different file names. `engine.load_data` matches files by keyword, and `as_list()` handles both lists and strings. Fix it there.

### 3.2 Person A: engine owner (correctness)
- [ ] Read `system/decide.py` top to bottom with Cursor. Ask it to explain each function. You must be able to explain every rule.
- [ ] Spot-check 20 random **DIFFERENT_ENTITY** outputs by hand (`--debug` adds a `path` field to each line). Every clear must rest on a real contradiction. Highest risk first:
  - `LOCATION_MISMATCH` (218): are the countries complete? Are note-derived countries right?
  - `NAME_MISMATCH_VERIFIED` (126): is the CAPS name from the note right? Is it the *latest* approved check?
  - `TEMPORAL_IMPOSSIBILITY` (22): is the dated report line parsed right? Year-only DOBs?
- [ ] Spot-check 10 **AMBIGUOUS** cases (35): are they really two different people?
- [ ] Known soft spots to test:
  - `parse_kyc_note()`: picks the DOB as "the date that isn't the note's created_at". Check notes where they're the same day.
  - `countries_in_text()` on support notes: could pick up a country that isn't a residence.
  - `younger_than_16()` with a year-only DOB.
  - No-link resolution when the screened name is a nickname or typo.
- [ ] **Don't overfit.** Any rule change must be justified by a sentence in the SOP, not by one case.

### 3.3 Person B: test-to-fail harness + story
- [ ] Build `harness/mutate.py`. It copies the data folder to a temp dir, applies one mutation, runs `system/run`, and compares results. Mutations (from our team doc):
  1. Name variant on the hit (Mohammed -> Muhammad, add or remove accents, join or split parts). **Expect:** same decision.
  2. Remove the hit's DOB (dobs field and notes sentence). **Expect:** SAME becomes REVIEW, **never DIFFERENT**.
  3. Add a verified conflicting DOB: a newer approved KYC check with a DOB 10 years off. **Expect:** DIFFERENT / DOB_MISMATCH.
  4. Add unreliable conflicting data: a rejected or expired KYC check with a different DOB. **Expect:** no change.
  5. Duplicate a customer record (same phone + DOB). **Expect:** no change; grouped as one person.
  6. Add a look-alike customer: same name, different phone and DOB, fits the screened details. **Expect:** REVIEW / AMBIGUOUS if decisions differ, **never a wrongful clear**.
  7. Cut the account link from the alert. **Expect:** found by name search or REVIEW, never a wrong clear.
- [ ] Seed set: the 12 SAME_ENTITY practice labels plus all SAME_ENTITY dev outputs. Report: "N mutations from M true matches: X stayed SAME, Y moved to REVIEW, **0 became DIFFERENT**".
- [ ] One simple **baseline** for the demo: name-match only (say SAME if names agree, else DIFFERENT). Show how many true matches it gets wrong vs ClearGuard.
- [ ] Optional if time: `console/build.py` turns `output/dev.jsonl` into one static HTML page (hit, decision, reason, evidence IDs, path). No server.

### 3.4 Together, from 15:45
- [ ] **Code freeze at 15:45.** After that, only README, video and bug fixes.
- [ ] Write `system/README.md` (template in section 5).
- [ ] Record the video (script in section 4). This is also the backup if the live demo fails.
- [ ] Push. Check the repo is **public**, has **no `dev/` data and no keys**, and that `system/run` and `output/dev.jsonl` are there.
- [ ] Submit the repo link through the hackathon portal before 17:00.

---

## 4. Timeline (London time)

| By | What |
|---|---|
| 13:30 | Official data downloaded, engine run, validate.py score in |
| 14:30 | A: 30 manual spot-checks done. B: harness mutations 1–4 working |
| 15:00 | Office hours: bring our riskiest cases and harness results |
| 15:45 | Code freeze. Harness numbers final |
| 16:15 | README done |
| 16:30 | Video recorded |
| 16:55 | Final push + submitted |

---

## 5. Demo (3 minutes) and README

**Pitch line:** "Most screening hits are false alarms, but clearing a real match is the mistake that gets banks fined. ClearGuard follows the SOP in code: it finds the right customer across six systems, clears only on hard contradictions, confirms only on agreement, and sends the rest to a person. On the dev set it resolves 73% of hits automatically, scores 50/50 on the practice labels with zero wrongful clears, and gives the same answer every run. Now watch us try to break it."

1. 0:00–0:30: problem + numbers.
2. 0:30–1:30: one hit end to end (use the debug `path`): a DOB_MISMATCH clear, then one AMBIGUOUS review.
3. 1:30–2:30: live harness: mutations, outcome spread, 0 wrongly cleared. Then the name-only baseline failing.
4. 2:30–3:00: "Same harness can test any screening agent against a firm's own SOP."

**README must have:** architecture (paste section 2), how we find the customer and the listed person, how evidence is represented, how results stay the same run to run, model and prompts ("none: fully deterministic, by design"), time and cost ("~7 s, £0"), and three example cases (a clear mismatch, a match, a REVIEW). Use H-58A39C (DOB_MISMATCH), H-91AC66 (NAME_DOB_LOCATION_MATCH) and H-6C7985 (AMBIGUOUS review).

---

## 6. Rules we must not break
- Python standard library only. An LLM only via OpenRouter, if we add one at all. We don't need one.
- `system/run <data folder> <output file>` must work from any working directory. It does: `run` finds its own folder.
- Never commit `dev/` data or API keys (`.gitignore` covers them).
- One output line per hit. A missing hit counts against us. `main.py` falls back to REVIEW if a hit ever crashes.

## 7. Files
```
system/run          entry point (shell -> main.py)
system/main.py      loads data, decides every hit, writes JSONL (--debug adds the path)
system/engine.py    loading, dates, countries, name matching (SOP principle 8)
system/decide.py    resolution, facts, SOP decision rules
tools_score.py      our scorer vs practice labels (confusion matrix + wrongful clears)
output/dev.jsonl    predictions on the dev set
MEGAPLAN.md         this file
```
