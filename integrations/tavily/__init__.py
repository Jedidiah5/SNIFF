"""Optional Tavily external-intelligence adapter (dormant until explicitly called)."""

from .client import TavilyNotConfiguredError, search_external_intelligence
from .models import ExternalSearchHit, ExternalSearchResult

__all__ = [
    "ExternalSearchHit",
    "ExternalSearchResult",
    "TavilyNotConfiguredError",
    "search_external_intelligence",
]
