"""Lightweight Tavily search adapter (stdlib urllib only).

Dormant by default: no startup calls, no engine hooks, no credentials required
for SNIFF to run. Call search_external_intelligence() only when activating.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .models import ExternalSearchHit, ExternalSearchResult

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DEFAULT_TIMEOUT_SEC = 15.0


class TavilyNotConfiguredError(RuntimeError):
    """Raised when TAVILY_API_KEY is missing and a search is attempted."""


class TavilyAPIError(RuntimeError):
    """Raised when the Tavily HTTP API returns an error or invalid payload."""


def _api_key() -> Optional[str]:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    return key or None


def is_configured() -> bool:
    return _api_key() is not None


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _normalize_payload(query: str, payload: Dict[str, Any], *, elapsed_ms: Optional[float] = None) -> ExternalSearchResult:
    if not isinstance(payload, dict):
        raise TavilyAPIError("Tavily response was not a JSON object")

    raw_results = payload.get("results")
    if raw_results is None:
        raise TavilyAPIError("Tavily response missing 'results'")
    if not isinstance(raw_results, list):
        raise TavilyAPIError("Tavily 'results' must be a list")

    hits = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or item.get("snippet") or "").strip()
        source = str(item.get("source") or _domain_of(url)).strip()
        score_raw = item.get("score")
        score: Optional[float]
        try:
            score = float(score_raw) if score_raw is not None else None
        except (TypeError, ValueError):
            score = None
        hits.append(
            ExternalSearchHit(
                title=title,
                url=url,
                content=content,
                source=source,
                score=score,
            )
        )

    answer = payload.get("answer")
    if answer is not None:
        answer = str(answer)

    metadata: Dict[str, Any] = {
        "response_time": payload.get("response_time"),
        "result_count": len(hits),
    }
    if elapsed_ms is not None:
        metadata["elapsed_ms"] = elapsed_ms
    # Pass through non-secret retrieval hints when present.
    for key in ("request_id", "images"):
        if key in payload:
            metadata[key] = payload[key]

    return ExternalSearchResult(
        query=query,
        results=hits,
        provider="tavily",
        answer=answer,
        metadata=metadata,
    )


def _post_json(url: str, body: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = getattr(resp, "status", None) or resp.getcode()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = str(exc)
        raise TavilyAPIError(f"Tavily HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TavilyAPIError(f"Tavily network error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise TavilyAPIError("Tavily request timed out") from exc

    if status and int(status) >= 400:
        raise TavilyAPIError(f"Tavily HTTP {status}: {raw[:500]}")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TavilyAPIError("Tavily response was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise TavilyAPIError("Tavily response was not a JSON object")
    return parsed


def search_external_intelligence(
    query: str,
    max_results: int = 5,
    *,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    search_depth: str = "basic",
    include_answer: bool = False,
    _transport=None,
) -> ExternalSearchResult:
    """Search the open web via Tavily. Does nothing until explicitly called.

    Args:
        query: Search query.
        max_results: Max hits to request (clamped 1..20).
        timeout: Socket timeout in seconds.
        search_depth: Tavily depth ("basic" or "advanced").
        include_answer: Whether to request Tavily's short answer field.
        _transport: Optional injectable POST callable for tests
            ``(url, body, timeout) -> dict``.

    Raises:
        TavilyNotConfiguredError: if TAVILY_API_KEY is unset.
        TavilyAPIError: on HTTP/network/parse failures.
        ValueError: on empty query.
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("query must be a non-empty string")

    key = _api_key()
    if not key:
        raise TavilyNotConfiguredError(
            "TAVILY_API_KEY is not set. Export it to activate external search."
        )

    n = max(1, min(int(max_results), 20))
    body = {
        "api_key": key,
        "query": q,
        "max_results": n,
        "search_depth": search_depth,
        "include_answer": bool(include_answer),
    }

    transport = _transport or _post_json
    started = time.monotonic()
    payload = transport(TAVILY_SEARCH_URL, body, timeout)
    elapsed_ms = round((time.monotonic() - started) * 1000, 2)
    return _normalize_payload(q, payload, elapsed_ms=elapsed_ms)
