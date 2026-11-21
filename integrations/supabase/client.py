"""Optional Supabase client wrapper (stdlib urllib only).

Never auto-connects at startup. Never used by the sanctions decision path.
Service-role keys stay server-side via environment variables only.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

DEFAULT_TIMEOUT_SEC = 10.0


class SupabaseNotConfiguredError(RuntimeError):
    """Raised when required Supabase env vars are missing."""


class SupabaseAPIError(RuntimeError):
    """Raised when a Supabase REST call fails."""


@dataclass
class SupabaseClient:
    """Minimal REST helper. Not a full SDK replacement."""

    url: str
    anon_key: str = ""
    service_role_key: str = ""
    timeout: float = DEFAULT_TIMEOUT_SEC
    _transport: Any = None  # injectable for tests

    def _key(self, *, prefer_service_role: bool = False) -> str:
        if prefer_service_role and self.service_role_key:
            return self.service_role_key
        if self.anon_key:
            return self.anon_key
        if self.service_role_key:
            return self.service_role_key
        raise SupabaseNotConfiguredError(
            "Neither SUPABASE_ANON_KEY nor SUPABASE_SERVICE_ROLE_KEY is set."
        )

    def _headers(self, *, prefer_service_role: bool = False) -> Dict[str, str]:
        key = self._key(prefer_service_role=prefer_service_role)
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Dict[str, Any]] = None,
        prefer_service_role: bool = False,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        base = self.url if self.url.endswith("/") else self.url + "/"
        url = urljoin(base, path.lstrip("/"))
        headers = self._headers(prefer_service_role=prefer_service_role)
        if extra_headers:
            headers.update(extra_headers)
        data = None if body is None else json.dumps(body).encode("utf-8")

        if self._transport is not None:
            return self._transport(method, url, headers, data, self.timeout)

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                status = getattr(resp, "status", None) or resp.getcode()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                detail = str(exc)
            raise SupabaseAPIError(f"Supabase HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SupabaseAPIError(f"Supabase network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise SupabaseAPIError("Supabase request timed out") from exc

        if status and int(status) >= 400:
            raise SupabaseAPIError(f"Supabase HTTP {status}: {raw[:500]}")
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def health_check(self) -> Dict[str, Any]:
        """Lightweight connectivity probe against PostgREST root."""
        try:
            self._request("GET", "/rest/v1/")
            return {"ok": True, "provider": "supabase", "url": self.url}
        except SupabaseAPIError as exc:
            return {
                "ok": False,
                "provider": "supabase",
                "url": self.url,
                "error": str(exc),
            }

    def insert_row(
        self,
        table: str,
        row: Dict[str, Any],
        *,
        prefer_service_role: bool = False,
    ) -> Any:
        """Example generic persistence helper for a future iteration.

        Does not migrate schemas or replace local screening storage.
        """
        table_name = (table or "").strip()
        if not table_name:
            raise ValueError("table must be a non-empty string")
        if not isinstance(row, dict) or not row:
            raise ValueError("row must be a non-empty dict")
        return self._request(
            "POST",
            f"/rest/v1/{table_name}",
            body=row,
            prefer_service_role=prefer_service_role,
            extra_headers={"Prefer": "return=representation"},
        )

    def select_rows(
        self,
        table: str,
        *,
        limit: int = 10,
        prefer_service_role: bool = False,
    ) -> List[Dict[str, Any]]:
        """Example read helper. Optional future use only."""
        table_name = (table or "").strip()
        if not table_name:
            raise ValueError("table must be a non-empty string")
        n = max(1, min(int(limit), 1000))
        path = f"/rest/v1/{table_name}?select=*&limit={n}"
        payload = self._request(
            "GET",
            path,
            prefer_service_role=prefer_service_role,
        )
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise SupabaseAPIError("Expected a JSON array from Supabase select")
        return [item for item in payload if isinstance(item, dict)]


def is_configured() -> bool:
    url = os.environ.get("SUPABASE_URL", "").strip()
    anon = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    service = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return bool(url and (anon or service))


def get_supabase_client(
    *,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    _transport=None,
) -> SupabaseClient:
    """Build a client from environment variables. No network I/O."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    anon = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    service = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not (anon or service):
        raise SupabaseNotConfiguredError(
            "Set SUPABASE_URL and SUPABASE_ANON_KEY "
            "(or SUPABASE_SERVICE_ROLE_KEY) to activate persistence."
        )
    return SupabaseClient(
        url=url.rstrip("/"),
        anon_key=anon,
        service_role_key=service,
        timeout=timeout,
        _transport=_transport,
    )


def health_check(*, timeout: float = DEFAULT_TIMEOUT_SEC, _transport=None) -> Dict[str, Any]:
    """Convenience wrapper: build client then probe. No-op if never called."""
    client = get_supabase_client(timeout=timeout, _transport=_transport)
    return client.health_check()
