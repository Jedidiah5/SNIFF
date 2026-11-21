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
| Reproducibility | 5 runs, byte-identical — MD5 `72bc532a9dfcaad410d69a8439eb833d` |
| Runtime | ~10 s (Python 3 stdlib only) |
| Cost | **£0** (no API, no LLM required) |
| SOP rule tests | **20** passing (`tests/test_sop_rules.py`) |
| Unseen-wording mutation | **0** SAME/REVIEW → DIFFERENT (`harness/unseen_wording.py`) |

50/50 and 0 unsafe clears are measured on the 50 practice labels only. The other 769 dev hits have no labels, which is why we built rule tests and mutation tests.

## How to run

```bash
system/run <data folder> <output file>
system/run <data folder> <output file> --debug   # policy trace per hit
python3 -m unittest tests.test_sop_rules
python3 harness/unseen_wording.py --data /path/to/dev
```

## Docs and extras

- [`system/README.md`](system/README.md) — full write-up for judges
- [`docs/POLICY_MAP.md`](docs/POLICY_MAP.md) — reason code → exact POLICY sentence
- [`tests/`](tests/) — 20 SOP rule tests
- [`harness/`](harness/) — test-to-fail mutation harness + `unseen_wording.py`
- [`baseline/`](baseline/) — name-only foil baseline
- [`console/trace.py`](console/trace.py) — static policy-trace HTML from `--debug` output (generated HTML is gitignored; contains dev data)
- [`integrations/`](integrations/) — optional Tavily / Supabase adapters (dormant; not used by screening)

## Known gaps

- Unseen note wording falls back to REVIEW.
- Ambiguous numeric dates (`03/04/1965`) require contradiction under both readings before a DOB clear.
- Phone formats (`+44` versus `0`) are not normalized for matching.
- Approximate ages (“in his 40s”) are not parsed.
