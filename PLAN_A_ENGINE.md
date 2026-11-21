# PLAN A: Engine owner (correctness)

You own: `system/engine.py`, `system/decide.py`, `system/main.py`, `system/run`, `tools_score.py`, `output/dev.jsonl`.
You do NOT touch: `harness/`, `baseline/`, `console/`, `system/README.md` (Person B owns those).
Code freeze **15:45**. Final push **16:55**.

## Git rules (so we never collide)
- Work on branch `engine`. Merge into `main` only when tools_score.py shows **0 wrongful clears** and no drop in score.
- You are the only person who commits `output/dev.jsonl`. Regenerate it after every merged change.
- Person B treats `system/run` as a black box. If you change its inputs or outputs, tell B first.

## Where we are
- 50/50 on the practice labels (decision, reason code, customer record), 0 wrongful clears.
- 819 dev hits: 465 DIFFERENT, 134 SAME, 220 REVIEW (73% auto-resolved). 5 runs are byte-identical. ~7 seconds.
- Built on JSONL converted from the browse workbook, **not yet on the official dev/ folder**.

## How the engine decides (you must be able to explain this)
1. **Resolve the customer** (`resolve`, `group_persons`). Follow account_ref, then login_handle, then email. For joint holders, keep the ones that fit the screened name, DOB, country and city. With no link, search by name and keep the records that fit. Group records into people: same phone + same full DOB, or the same document number on approved checks. Several people means each is decided; if they disagree, `REVIEW / AMBIGUOUS_CUSTOMER_RECORD`.
2. **Customer facts** (`customer_facts`): the latest approved identity check wins, from KYC provider checks or KYC notes. Rejected or expired checks are ignored. Countries come from residence and nationality on all records, the document country, and countries named in support notes.
3. **Hit facts** (`hit_dobs`, `hit_countries`, `earliest_report`): DOB from the dobs field, else the first paragraph of the profile notes, else search results that name the same kind of listing and a country tied to the hit.
4. **Clear on any contradiction:** type, deceased, temporal (<16 at earliest dated report), DOB, verified name, location. A location difference **never** clears if name and DOB agree.
5. **Confirm on agreement:** a person on name + DOB; a company on name + country.
6. **Otherwise REVIEW.**

## Tasks, in order

### A1. Run on the official data (by 13:30)
- [ ] Download the Track 2 dataset from the hackathon site. Put `dev/` **next to** the repo: `../dev`.
- [ ] `system/run ../dev output/dev.jsonl`
- [ ] Official validator: `python3 ../dev/validate.py output/dev.jsonl` and with `--score ../dev/practice_labels.jsonl` (check the exact usage in the data's README).
- [ ] `python3 tools_score.py ../dev/practice_labels.jsonl output/dev.jsonl -v`
- [ ] If it breaks, it's a field-format difference (lists vs `"a; b"` strings, or file names). Fix it in `engine.load_data` / `as_list`. **Send B the validator command once it works.**

### A2. Hand spot-checks (13:30–15:00)
Run with `--debug` to get a `path` field per line. Check each case by hand against POLICY.md.
- [ ] 10 x `LOCATION_MISMATCH`: are the customer's countries complete? Did a support note add a wrong country?
- [ ] 10 x `NAME_MISMATCH_VERIFIED`: is the verified name the latest approved one? Was the CAPS name parsed right from the note?
- [ ] 5 x `TEMPORAL_IMPOSSIBILITY`: is the dated report line right? Was the DOB year-only?
- [ ] 5 x `AMBIGUOUS`: really two different people?
- [ ] 5 x `REVIEW / INSUFFICIENT_DATA`: is there a fact we missed that should decide it?
- [ ] Known soft spots: `parse_kyc_note()` DOB picking, `countries_in_text()` on support notes, `younger_than_16()` with a year-only DOB, no-link search when the screened name is a nickname or typo.

### A3. Fix rules (only with SOP backing)
- [ ] Every change: quote the POLICY.md sentence that justifies it in the commit message.
- [ ] After every change: rerun, rescore. If wrongful clears go above 0 or the score drops, revert.

### A4. Freeze (15:45)
- [ ] Merge `engine` into `main`, regenerate `output/dev.jsonl`, commit.
- [ ] Final reproducibility check: run 5 times, `md5sum` must match. Send B the numbers for the README.
- [ ] Prepare for Q&A: be ready to explain any decision from the `--debug` path.

## Cursor prompt
"Read PLAN_A_ENGINE.md, then the data's POLICY.md, then system/decide.py. Explain in 5 bullets how a hit is decided. Then help me with task A1. Standard library only; never change a rule without quoting the SOP sentence; rerun tools_score.py after every change."
