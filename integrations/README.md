# Optional integrations

Prepared, isolated adapters for future activation. **Not part of the scored screening path.**

| Integration | Purpose | Status helper |
|---|---|---|
| [`tavily/`](tavily/) | External web intelligence search | `TAVILY_API_KEY` |
| [`supabase/`](supabase/) | Optional remote persistence | `SUPABASE_URL` + key |

```python
from integrations import integration_status
print(integration_status())
# -> {"tavily": "unavailable", "supabase": "unavailable"}  when env unset
```

Rules:

- Missing credentials must not break `system/run`, the harness, or the console.
- Neither adapter is imported by `system/`, `harness/`, `baseline/`, or `console/`.
- No network calls at import or process startup.
- Removing `integrations/` entirely must leave the product working.

See `.env.example` for variable names.
