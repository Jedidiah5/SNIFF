"""Informational status for optional integrations.

Does not connect to any network service and does not affect startup or decisions.
"""

from __future__ import annotations

import os
from typing import Dict


def _tavily_configured() -> bool:
    return bool(os.environ.get("TAVILY_API_KEY", "").strip())


def _supabase_configured() -> bool:
    url = os.environ.get("SUPABASE_URL", "").strip()
    anon = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    service = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return bool(url and (anon or service))


def integration_status() -> Dict[str, str]:
    """Return configured/unavailable for each optional integration."""
    return {
        "tavily": "configured" if _tavily_configured() else "unavailable",
        "supabase": "configured" if _supabase_configured() else "unavailable",
    }
