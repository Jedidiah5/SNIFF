# Optional Supabase integration

Dormant persistence adapter. **Not used by the sanctions engine, harness, or console.**

SNIFF decisions stay file-based and local. Supabase is never the source of truth for screening.

## Activate later

```bash
export SUPABASE_URL=https://YOUR_PROJECT.supabase.co
export SUPABASE_ANON_KEY=eyJ...
# Optional server-only key — never ship to a browser/frontend:
# export SUPABASE_SERVICE_ROLE_KEY=eyJ...

python3 -c '
from integrations.supabase import get_supabase_client, health_check
print(health_check())
# Example future write (requires a table you create yourself):
# client = get_supabase_client()
# client.insert_row("notes", {"hit_id": "H-demo", "text": "optional note"})
'
```

## Behaviour

| Condition | Result |
|---|---|
| Creds missing | `SupabaseNotConfiguredError` only when you call get/health |
| Network / HTTP error | `ok: false` from `health_check()`, or `SupabaseAPIError` from writes |
| Creds present, never called | Zero network traffic |

## Design notes

- Stdlib `urllib` only — no `supabase-py` dependency.
- Service-role key is env-only and must never be exposed to frontend code.
- No migrations, no auth rewrite, no replacement of existing storage.
- Safe to delete this folder; core SNIFF keeps working.
