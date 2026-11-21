# PLAN B: Proof, demo and submission

You own: `harness/`, `baseline/`, `console/`, `system/README.md`, the video and the submission.
You do NOT touch: `system/engine.py`, `system/decide.py`, `system/main.py`, `system/run`, `output/dev.jsonl` (Person A owns those).
Code freeze **15:45**. Final push **16:55**.

## Git rules (so we never collide)
- Work on branch `proof`. Only ever add or edit files inside your own folders, plus `system/README.md`.
- Call the engine as a **black box**: `system/run <data folder> <output file>`. Never import or edit its code. If you think the engine is wrong, tell A with the hit ID; don't fix it yourself.
- Never copy dev data into the repo. Mutated copies go in a temp folder outside the repo.

## What the engine does (one paragraph for the README and pitch)
For each screening hit, ClearGuard finds the right customer across six systems with no shared key. It gathers the verified facts: the latest approved identity check wins, and rejected or expired checks are ignored. It clears the hit only when a trusted fact contradicts it (type, death, age at the first report, DOB, verified name, country). It confirms only when name and DOB agree (or name and country for companies), and sends everything else to a person. It's plain code with no LLM, so the same input always gives the same output. Current numbers: 50/50 on the practice labels, 0 wrongful clears, 73% of 819 dev hits resolved automatically, 5 identical runs, ~7 seconds.

## Tasks, in order

### B1. Test-to-fail harness: `harness/mutate.py` (13:30–15:00)
How it works: copy `../dev` to a temp folder, apply ONE mutation to the files, run `system/run`, and compare the mutated hit's decision to the original. Python standard library only.

Seeds: hits the engine (or the practice labels) say are SAME_ENTITY. Mutations, from our team doc:
1. **Name variant on the hit** (Mohammed -> Muhammad, add or remove accents, join or split parts). Expect: same decision.
2. **Remove the hit's DOB** (dobs field + the born/age sentence in the notes). Expect: SAME -> REVIEW, **never DIFFERENT**.
3. **Verified conflicting DOB**: add a newer *approved* KYC check with a DOB 10 years off. Expect: DIFFERENT / DOB_MISMATCH. This shows it reacts to real evidence.
4. **Unreliable conflicting data**: add a *rejected* or *expired* KYC check with a different DOB. Expect: no change.
5. **Duplicate customer record** (same phone + same DOB). Expect: no change; grouped as one person.
6. **Look-alike customer**: same name, different phone and DOB, fits the screened details. Expect: REVIEW (AMBIGUOUS), **never a wrongful clear**.
7. **Cut the account link** from the alert. Expect: found by name search or REVIEW, never a wrong clear.

Output: a table plus one headline line, e.g. "N mutations from M true matches: X stayed SAME, Y moved to REVIEW, 0 became DIFFERENT". Quote M honestly; the real sample is the number of true matches.

### B2. Baseline: `baseline/name_only.py` (by 15:15)
- [ ] Says SAME if the hit name equals the customer name (simple lowercase compare), else DIFFERENT. Run it on the practice labels.
- [ ] One line for the demo: "Name-only matching gets X of 50 right and wrongly clears Y real matches. ClearGuard: 50/50, 0."

### B3. Optional, only if B1 and B2 are done: `console/build.py`
- [ ] Turns the output (run with `--debug`) into one static HTML page: hit, decision, reason, evidence IDs, path. No server, no libraries.

### B4. README: `system/README.md` (15:45–16:15)
Must include:
- architecture (the 6 steps)
- how we find the customer and the listed person
- how evidence is represented (IDs exactly as in the files)
- how results stay the same each run (deterministic, no LLM; 5 identical runs, md5)
- model and prompts: none, by design
- time and cost: ~7 s, £0
- three example cases: **H-58A39C** (DOB_MISMATCH clear), **H-91AC66** (NAME_DOB_LOCATION_MATCH), **H-6C7985** (AMBIGUOUS review)

Get the final numbers from A at 15:45.

### B5. Video + submit (16:15–16:55)
3-minute script:
1. **0:00–0:30.** "Most screening hits are false alarms, but clearing a real match is what gets banks fined." Show the numbers.
2. **0:30–1:30.** One hit end to end with its debug path (a DOB_MISMATCH clear), then one AMBIGUOUS review.
3. **1:30–2:30.** Run the harness live: outcome spread, **0 became DIFFERENT**. Then the name-only baseline failing.
4. **2:30–3:00.** "The same harness can test any screening agent against a firm's own SOP."

- [ ] Record it (it's also our backup if the live demo fails).
- [ ] Merge `proof` into `main`. Check the repo is **public**, has no data and no keys, and has `system/run` + `output/dev.jsonl`.
- [ ] Submit the repo link and video through the hackathon portal **before 17:00**.

## Cursor prompt
"Read PLAN_B_PROOF.md. I own harness/, baseline/, console/ and system/README.md only. Never edit system/*.py; call `system/run <data> <out>` as a black box. Standard library only. Start with task B1: write harness/mutate.py that copies ../dev to a temp dir, applies one mutation at a time, runs system/run, and reports how each seed hit's decision changed."
