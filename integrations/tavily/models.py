"""Normalized shapes for optional Tavily search results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ExternalSearchHit:
    title: str
    url: str
    content: str
    source: str
    score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExternalSearchResult:
    query: str
    results: List[ExternalSearchHit] = field(default_factory=list)
    provider: str = "tavily"
    answer: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "provider": self.provider,
            "answer": self.answer,
            "results": [r.to_dict() for r in self.results],
            "metadata": dict(self.metadata),
        }
