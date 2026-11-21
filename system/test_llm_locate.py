"""Isolated tests for the optional LLM locator (no network)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

import llm_locate


class TestLlmLocateDormant(unittest.TestCase):
    def setUp(self):
        llm_locate.reset_run_state()

    def test_inactive_without_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(llm_locate.is_active())
            self.assertIsNone(llm_locate.locate("born 1962-03-12", "customer_dob"))
            self.assertEqual(llm_locate.call_count(), 0)

    def test_inactive_when_sniff_llm_off(self):
        with mock.patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "test-key", "SNIFF_LLM": "off"},
            clear=True,
        ):
            self.assertFalse(llm_locate.is_active())
            self.assertIsNone(llm_locate.locate("born 1962-03-12", "customer_dob"))

    def test_triple_agree_substring(self):
        calls = {"n": 0}

        def transport(key, messages):
            calls["n"] += 1
            return '{"quote": "born 1962-03-12"}'

        text = "Sumsub verified JOHN SMITH born 1962-03-12 in Lagos."
        with mock.patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "test-key", "SNIFF_LLM": "on"},
            clear=True,
        ):
            q = llm_locate.locate(text, "customer_dob", _transport=transport)
        self.assertEqual(q, "born 1962-03-12")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(llm_locate.call_count(), 3)

    def test_reject_non_substring(self):
        def transport(key, messages):
            return '{"quote": "invented date 1900-01-01"}'

        with mock.patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "test-key"},
            clear=True,
        ):
            q = llm_locate.locate("no dates here", "customer_dob", _transport=transport)
        self.assertIsNone(q)

    def test_reject_disagreement(self):
        replies = iter([
            '{"quote": "born 1962-03-12"}',
            '{"quote": "born 1962-03-13"}',
            '{"quote": "born 1962-03-12"}',
        ])

        def transport(key, messages):
            return next(replies)

        text = "born 1962-03-12 and born 1962-03-13"
        with mock.patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "test-key"},
            clear=True,
        ):
            q = llm_locate.locate(text, "customer_dob", _transport=transport)
        self.assertIsNone(q)


if __name__ == "__main__":
    unittest.main()
