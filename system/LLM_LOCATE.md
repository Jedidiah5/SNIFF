# Adaptive LLM locator (`llm_locate.py`)

**The AI points. The code reads. The policy decides.**

Pinned model: `x-ai/grok-4-fast` (OpenRouter).

## Activate

```bash
export OPENROUTER_API_KEY=...
# optional force-off: export SNIFF_LLM=off
system/run ../dev output/dev.jsonl
```

Inactive (no key / `SNIFF_LLM=off`): every `locate()` returns `None`, zero network calls, output matches the rules-only engine.

## Behaviour

- Three identical quote responses required; quote must be an exact substring.
- Used only when regex parsing missed a field.
- Failed/rejected KYC notes never call the locator.
- Age-derived LLM hit years never clear; LLM names never sole-basis `NAME_MISMATCH_VERIFIED`.
- Debug traces set `llm_located=true` when a locator quote contributed.
