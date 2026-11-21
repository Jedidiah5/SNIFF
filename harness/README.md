# SNIFF trick-test harness

Black-box test-to-fail for the sanctions engine. Copies the official dataset to a temp folder, applies **one** named mutation, runs `system/run`, and compares original vs mutated decisions. Expected outcomes are evaluation-only — they never enter the engine.

## Results

108 mutations from 12 true matches: 85 stayed SAME, 15 moved to REVIEW, 8 correctly became DIFFERENT when we injected a verified conflicting date of birth. Unsafe clears: 0.

| Count | Outcome |
|---|---|
| 108 | mutations from 12 true matches |
| 85 | stayed SAME |
| 15 | moved to REVIEW |
| 8 | correctly became DIFFERENT (verified conflicting DOB) |
| 0 | unsafe clears |

## Mutations

| Name | What changes | Safety rule |
|---|---|---|
| `name_variant` | Hit name spelling/format | Must not wrongful-clear |
| `remove_hit_dob` | Hit DOB from field + notes + search | Must not wrongful-clear |
| `verified_conflicting_dob` | Newer approved KYC DOB conflict | Expect DIFFERENT (individuals) |
| `unreliable_conflicting_dob` | Rejected/expired KYC DOB | Decision unchanged |
| `duplicate_customer` | Same phone+DOB duplicate row | Decision unchanged |
| `lookalike_customer` | Same name, different phone/DOB | Never wrongful-clear |
| `cut_account_link` | Null alert account/login/email | Never wrongful-clear |
| `randomize_ids` | Deterministic ID remapping | Decision unchanged |
| `reorder_records` | Deterministic JSONL shuffle | Decision unchanged |

## Demo (recommended for live talk)

```bash
# Fast showcase (~3 hits × 9 mutations)
python3 harness/demo.py --data /path/to/screening/dev --quick

# Full practice SAME_ENTITY matrix
python3 harness/demo.py --data /path/to/screening/dev
```

Open the HTML it prints (`demo_report.html`). Metrics are computed from that run. JSON/HTML reports are gitignored.

## Full harness CLI

```bash
python3 harness/mutate.py \
  --data /path/to/screening/dev \
  --out /tmp/sniff-harness/report.json \
  --html /tmp/sniff-harness/report.html \
  --seeds practice
```

## Tests

```bash
python3 -m unittest harness.test_audit_fixes -v
```

## Ownership

Plan B owns `harness/` and `baseline/`. Do not edit `system/*.py` decision rules from this folder — call `system/run` only.
