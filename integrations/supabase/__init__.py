"""Optional Supabase persistence adapter (dormant until explicitly called)."""

from .client import (
    SupabaseNotConfiguredError,
    get_supabase_client,
    health_check,
    is_configured,
)

__all__ = [
    "SupabaseNotConfiguredError",
    "get_supabase_client",
    "health_check",
    "is_configured",
]
