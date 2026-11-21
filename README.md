# SNIFF: Sanctions Name & Identity Fact Finder

Track 2 (Sanctions screening): is this screening hit really our customer?

Team: Jedidiah Onotu, Collins

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

## How to run

```bash
system/run <data folder> <output file>
```

## Docs and extras

- [`system/README.md`](system/README.md) — full write-up for judges
- [`docs/POLICY_MAP.md`](docs/POLICY_MAP.md) — reason code → exact POLICY sentence
- [`tests/`](tests/) — 17 SOP rule tests
- [`harness/`](harness/) — test-to-fail mutation harness
- [`baseline/`](baseline/) — name-only foil baseline
- `integrations/`: optional Tavily live-search demo (`python -m integrations.tavily.demo`) showing SNIFF's principle-5 filter on real web results; not part of the scored run.
- `console/trace.py`: generates a static policy-trace page from `--debug` output (open the HTML locally; it is gitignored because it contains dev data).
