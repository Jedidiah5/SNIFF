"""Optional LLM evidence locator for SNIFF.

The AI points. The code reads. The policy decides.

Active only when OPENROUTER_API_KEY is set and SNIFF_LLM is not \"off\".
Otherwise every public function returns None with no network I/O.

The model may only return an exact quote from the source text. Our parsers
and SOP rules still extract facts and make decisions.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

# Pinned OpenRouter model id (do not change without re-running adaptive gates).
OPENROUTER_MODEL = "x-ai/grok-4-fast"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_TOKENS = 120
TEMPERATURE = 0
SEED = 7
TIMEOUT_SEC = 15.0
MAX_CALLS_PER_RUN = 300
MAX_THREADS = 4
PROVIDER = {"allow_fallbacks": False}

_FIELDS = ("customer_dob", "customer_name", "hit_dob_sentence")

_lock = threading.Lock()
_cache: Dict[str, Optional[str]] = {}
_call_count = 0
_sem = threading.Semaphore(MAX_THREADS)


def reset_run_state() -> None:
    """Clear per-run cache and call counter (tests / harness)."""
    global _call_count
    with _lock:
        _cache.clear()
        _call_count = 0


def call_count() -> int:
    with _lock:
        return _call_count


def is_active() -> bool:
    if (os.environ.get("SNIFF_LLM") or "").strip().lower() == "off":
        return False
    return bool((os.environ.get("OPENROUTER_API_KEY") or "").strip())


def _prompt(field: str, text: str) -> str:
    guides = {
        "customer_dob": (
            "Locate the exact substring that states the customer's date of birth "
            "or birth year. Copy it verbatim."
        ),
        "customer_name": (
            "Locate the exact substring that states the verified customer legal name. "
            "Copy it verbatim."
        ),
        "hit_dob_sentence": (
            "Locate the exact sentence in the first paragraph that states birth date, "
            "born-on, or age. Copy that sentence verbatim."
        ),
    }
    return (
        f"Field: {field}\n"
        f"{guides[field]}\n"
        "Respond with JSON only: {\"quote\": \"exact substring copied from the source, or empty\"}\n"
        "Do not paraphrase. If unsure, return an empty quote.\n\n"
        f"SOURCE:\n{text}"
    )


def _post_chat(api_key: str, messages: list) -> str:
    body = {
        "model": OPENROUTER_MODEL,
        "temperature": TEMPERATURE,
        "seed": SEED,
        "max_tokens": MAX_TOKENS,
        "provider": PROVIDER,
        "messages": messages,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        raw = resp.read().decode("utf-8")
    payload = json.loads(raw)
    choices = payload.get("choices") or []
    if not choices:
        return ""
    msg = (choices[0].get("message") or {}).get("content") or ""
    return str(msg)


def _extract_quote(content: str) -> str:
    content = (content or "").strip()
    if not content:
        return ""
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        # tolerate fenced JSON
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            return ""
        try:
            obj = json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            return ""
    if not isinstance(obj, dict):
        return ""
    q = obj.get("quote")
    return "" if q is None else str(q)


def locate(text: str, field: str, *, _transport=None) -> Optional[str]:
    """Return an exact source substring for field, or None.

    Calls the model three times; accepts the quote only when all three agree,
    the quote is non-empty, and it is an exact substring of text.
    """
    if field not in _FIELDS:
        return None
    if not is_active():
        return None
    src = text or ""
    if not src.strip():
        return None

    cache_key = f"{field}\n{src}"
    with _lock:
        if cache_key in _cache:
            return _cache[cache_key]
        global _call_count
        # each locate uses 3 API calls; refuse before exceeding budget
        if _call_count + 3 > MAX_CALLS_PER_RUN:
            _cache[cache_key] = None
            return None

    api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    messages = [
        {"role": "system", "content": "You are an evidence locator. Return JSON only."},
        {"role": "user", "content": _prompt(field, src)},
    ]

    quotes = []
    transport = _transport or (lambda key, msgs: _post_chat(key, msgs))
    try:
        for _ in range(3):
            with _sem:
                with _lock:
                    _call_count += 1
                content = transport(api_key, messages)
            quotes.append(_extract_quote(content))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        with _lock:
            _cache[cache_key] = None
        return None
    except Exception:
        with _lock:
            _cache[cache_key] = None
        return None

    quote = quotes[0] if quotes and all(q == quotes[0] for q in quotes) else ""
    if not quote or quote not in src:
        with _lock:
            _cache[cache_key] = None
        return None
    with _lock:
        _cache[cache_key] = quote
    return quote
