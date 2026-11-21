"""Isolated mocked tests for the optional Tavily adapter."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from integrations.tavily.client import (
    TavilyAPIError,
    TavilyNotConfiguredError,
    is_configured,
    search_external_intelligence,
)


class TestTavilyConfig(unittest.TestCase):
    def test_missing_key_is_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_configured())

    def test_key_present_is_configured(self):
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}, clear=True):
            self.assertTrue(is_configured())

    def test_missing_key_raises_on_search(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TavilyNotConfiguredError):
                search_external_intelligence("acme sanctions")

    def test_empty_query_raises(self):
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}, clear=True):
            with self.assertRaises(ValueError):
                search_external_intelligence("  ")


class TestTavilySearch(unittest.TestCase):
    def test_successful_mocked_search(self):
        def fake_transport(url, body, timeout):
            self.assertIn("api.tavily.com", url)
            self.assertEqual(body["query"], "ClearGuard sanctions hit")
            self.assertEqual(body["max_results"], 2)
            self.assertEqual(body["api_key"], "tvly-test")
            return {
                "answer": None,
                "response_time": 0.12,
                "results": [
                    {
                        "title": "Example",
                        "url": "https://www.example.com/a",
                        "content": "snippet text",
                        "score": 0.91,
                    },
                    {
                        "title": "Other",
                        "url": "https://news.example.org/b",
                        "content": "more",
                        "score": "0.5",
                    },
                ],
            }

        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}, clear=True):
            result = search_external_intelligence(
                "ClearGuard sanctions hit",
                max_results=2,
                _transport=fake_transport,
            )

        self.assertEqual(result.provider, "tavily")
        self.assertEqual(len(result.results), 2)
        self.assertEqual(result.results[0].title, "Example")
        self.assertEqual(result.results[0].source, "example.com")
        self.assertEqual(result.results[0].score, 0.91)
        self.assertEqual(result.results[1].score, 0.5)
        self.assertEqual(result.metadata["result_count"], 2)
        self.assertIn("elapsed_ms", result.metadata)

    def test_api_error_from_transport(self):
        def boom(url, body, timeout):
            raise TavilyAPIError("Tavily HTTP 401: unauthorized")

        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-bad"}, clear=True):
            with self.assertRaises(TavilyAPIError):
                search_external_intelligence("q", _transport=boom)

    def test_invalid_response_missing_results(self):
        def bad_payload(url, body, timeout):
            return {"answer": "no results key"}

        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}, clear=True):
            with self.assertRaises(TavilyAPIError):
                search_external_intelligence("q", _transport=bad_payload)

    def test_invalid_response_results_not_list(self):
        def bad_payload(url, body, timeout):
            return {"results": {"oops": True}}

        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}, clear=True):
            with self.assertRaises(TavilyAPIError):
                search_external_intelligence("q", _transport=bad_payload)


if __name__ == "__main__":
    unittest.main()
