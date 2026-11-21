"""Isolated mocked tests for the optional Supabase adapter."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from integrations.supabase.client import (
    SupabaseAPIError,
    SupabaseNotConfiguredError,
    get_supabase_client,
    health_check,
    is_configured,
)


class TestSupabaseConfig(unittest.TestCase):
    def test_missing_credentials_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_configured())

    def test_url_without_key_not_configured(self):
        with mock.patch.dict(
            os.environ,
            {"SUPABASE_URL": "https://example.supabase.co"},
            clear=True,
        ):
            self.assertFalse(is_configured())

    def test_url_and_anon_configured(self):
        with mock.patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "anon-test",
            },
            clear=True,
        ):
            self.assertTrue(is_configured())

    def test_missing_credentials_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SupabaseNotConfiguredError):
                get_supabase_client()


class TestSupabaseHealth(unittest.TestCase):
    def test_mocked_successful_connection(self):
        calls = []

        def transport(method, url, headers, data, timeout):
            calls.append((method, url, headers["apikey"]))
            self.assertEqual(method, "GET")
            self.assertTrue(url.endswith("/rest/v1/"))
            self.assertEqual(headers["Authorization"], "Bearer anon-test")
            return {}

        with mock.patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "anon-test",
            },
            clear=True,
        ):
            result = health_check(_transport=transport)

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "supabase")
        self.assertEqual(len(calls), 1)

    def test_mocked_failure(self):
        def transport(method, url, headers, data, timeout):
            raise SupabaseAPIError("Supabase HTTP 401: unauthorized")

        with mock.patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "anon-test",
            },
            clear=True,
        ):
            result = health_check(_transport=transport)

        self.assertFalse(result["ok"])
        self.assertIn("401", result["error"])

    def test_insert_row_example(self):
        def transport(method, url, headers, data, timeout):
            self.assertEqual(method, "POST")
            self.assertIn("/rest/v1/audit_notes", url)
            self.assertEqual(headers.get("Prefer"), "return=representation")
            return [{"id": 1, "hit_id": "H-1"}]

        with mock.patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_ANON_KEY": "anon-test",
                "SUPABASE_SERVICE_ROLE_KEY": "service-secret",
            },
            clear=True,
        ):
            client = get_supabase_client(_transport=transport)
            # Default uses anon key (service role never preferred unless asked).
            out = client.insert_row("audit_notes", {"hit_id": "H-1"})
            self.assertEqual(out[0]["hit_id"], "H-1")
            self.assertEqual(client._key(), "anon-test")
            self.assertEqual(client._key(prefer_service_role=True), "service-secret")


class TestRegistry(unittest.TestCase):
    def test_registry_reports_unavailable_without_env(self):
        from integrations import integration_status

        with mock.patch.dict(os.environ, {}, clear=True):
            status = integration_status()
        self.assertEqual(status["tavily"], "unavailable")
        self.assertEqual(status["supabase"], "unavailable")


if __name__ == "__main__":
    unittest.main()
