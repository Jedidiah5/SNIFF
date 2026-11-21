# Optional Tavily integration

Dormant external web-search adapter. **Not used by the sanctions engine, harness, or console.**

## Activate later

```bash
export TAVILY_API_KEY=tvly-...
python3 -c '
from integrations.tavily import search_external_intelligence
print(search_external_intelligence("example query", max_results=3).to_dict())
'
```

## Behaviour

| Condition | Result |
|---|---|
| Key missing | `TavilyNotConfiguredError` only when you call search |
| Network / HTTP error | `TavilyAPIError` |
| Key present, never called | Zero network traffic |

## Design notes

- Stdlib `urllib` only — no Tavily SDK dependency.
- API key read from `TAVILY_API_KEY` only; never hard-coded or sent to the frontend.
- Normalized output: title, url, content, source/domain, score, metadata.
- Safe to delete this folder; core SNIFF keeps working.
