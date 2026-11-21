#!/usr/bin/env python3
"""Unit tests for MEDIUM audit fixes (stdlib unittest only)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "system"))
sys.path.insert(0, os.path.dirname(__file__))

from engine import FILE_KEYS, load_data, _is_eval_only_filename  # noqa: E402
import mutate as harness  # noqa: E402


DEV = os.environ.get("CLEARGUARD_DEV", "/tmp/screening-track/screening/dev")


class TestLabelIsolation(unittest.TestCase):
    def test_file_keys_exclude_labels(self):
        self.assertNotIn("labels", FILE_KEYS)
        self.assertTrue(_is_eval_only_filename("practice_labels.jsonl"))
        self.assertTrue(_is_eval_only_filename("ground_truth.jsonl"))
        self.assertFalse(_is_eval_only_filename("hits.jsonl"))

    @unittest.skipUnless(os.path.isdir(DEV), "official screening/dev not present")
    def test_load_data_does_not_ingest_practice_labels(self):
        data = load_data(DEV)
        self.assertNotIn("labels", data)
        # Practice file exists beside inputs but must not land in any bucket.
        practice = os.path.join(DEV, "practice_labels.jsonl")
        self.assertTrue(os.path.isfile(practice))
        with open(practice, encoding='utf-8') as f:
            practice_ids = {json.loads(l)['hit_id'] for l in f if l.strip()}
        # No loaded table should be the practice labels rows (50 labeled hits with decision field).
        for key, rows in data.items():
            if key == "names" or not isinstance(rows, list):
                continue
            with_decision = [r for r in rows if isinstance(r, dict) and "decision" in r and "reason_codes" in r]
            self.assertEqual(
                with_decision, [],
                f"{key} unexpectedly contains practice-label shaped rows",
            )
        self.assertGreater(len(practice_ids), 0)


class TestRemoveHitDob(unittest.TestCase):
    def test_scrub_dob_signals_removes_age_and_born(self):
        raw = "In October 1987, Portugal saw Clara Moreau, who was 36 and a PEP."
        scrubbed = harness.scrub_dob_signals(raw)
        self.assertNotIn("was 36", scrubbed.lower())
        self.assertNotRegex(scrubbed, r"\b1987\b")

    def test_mutate_remove_hit_dob_clears_search_and_notes(self):
        tmp = tempfile.mkdtemp(prefix="cg-test-")
        try:
            # Minimal dataset with search-derived DOB path
            write = harness.write_jsonl
            write(os.path.join(tmp, "hits.jsonl"), [{
                "hit_id": "H-TEST01",
                "alert_id": "A-TEST01",
                "name": "Test Person",
                "entity_type": "Individual",
                "dobs": ["1990-01-01"],
                "aliases": [],
                "countries": ["Spain"],
                "nationality": ["Spain"],
                "categories": ["PEP"],
                "profile_notes": "Test Person was born on 1990-01-01 in Spain. Other facts remain.",
            }])
            write(os.path.join(tmp, "alerts.jsonl"), [{
                "alert_id": "A-TEST01",
                "account_ref": None,
                "login_handle": None,
                "email": None,
                "customer": {"name": "Test Person", "entity_type": "Individual"},
                "hit_ids": ["H-TEST01"],
            }])
            for name, rows in [
                ("customers.jsonl", []),
                ("accounts.jsonl", []),
                ("onboarding.jsonl", []),
                ("kyc_checks.jsonl", []),
            ]:
                write(os.path.join(tmp, name), rows)
            write(os.path.join(tmp, "search_results.jsonl"), [{
                "result_id": "SR-TEST",
                "query": "person test",
                "title": "Test Person - report",
                "snippet": (
                    "In October 1987, Spain saw a local news piece featuring Test Person, "
                    "who was 36 and a politically exposed person."
                ),
                "source": "example",
            }, {
                "result_id": "SR-OTHER",
                "query": "someone else",
                "title": "Other",
                "snippet": "Someone Else was 40 in May 2000.",
                "source": "example",
            }])
            ctx = harness.DataCtx(tmp)
            note = harness.mutate_remove_hit_dob(ctx, "H-TEST01", [])
            hit = ctx.hit_by_id["H-TEST01"]
            self.assertEqual(hit.get("dobs"), [])
            self.assertNotIn("born", (hit.get("profile_notes") or "").lower())
            # Matching query scrubbed; unrelated query preserved
            by_id = {s["result_id"]: s for s in ctx.search}
            self.assertNotIn("was 36", (by_id["SR-TEST"].get("snippet") or "").lower())
            self.assertIn("was 40", by_id["SR-OTHER"].get("snippet") or "")
            self.assertIn("scrubbed_search_rows=", note)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCompanyExpectations(unittest.TestCase):
    def test_remove_hit_dob_company_same_passes(self):
        expected, passed, safety, notes = harness.evaluate(
            "remove_hit_dob", "SAME_ENTITY", "SAME_ENTITY", "NAME_LOCATION_MATCH",
            original_reason="NAME_LOCATION_MATCH", entity_type="Company",
        )
        self.assertTrue(passed)
        self.assertFalse(safety)
        self.assertIn("NAME_LOCATION", notes)

    def test_remove_hit_dob_company_different_is_safety(self):
        _, passed, safety, _ = harness.evaluate(
            "remove_hit_dob", "SAME_ENTITY", "DIFFERENT_ENTITY", "DOB_MISMATCH",
            original_reason="NAME_LOCATION_MATCH", entity_type="Company",
        )
        self.assertFalse(passed)
        self.assertTrue(safety)

    def test_verified_conflicting_dob_company_same_passes(self):
        _, passed, safety, notes = harness.evaluate(
            "verified_conflicting_dob", "SAME_ENTITY", "SAME_ENTITY", "NAME_LOCATION_MATCH",
            original_reason="NAME_LOCATION_MATCH", entity_type="Company",
        )
        self.assertTrue(passed)
        self.assertFalse(safety)
        self.assertIn("informational", notes)

    def test_individual_verified_conflicting_still_expects_different(self):
        _, passed, safety, _ = harness.evaluate(
            "verified_conflicting_dob", "SAME_ENTITY", "SAME_ENTITY", "NAME_DOB_MATCH",
            original_reason="NAME_DOB_LOCATION_MATCH", entity_type="Individual",
        )
        self.assertFalse(passed)
        self.assertFalse(safety)


class TestDeterministicIds(unittest.TestCase):
    def test_stable_int_deterministic(self):
        a = harness.stable_int("H-0181BD")
        b = harness.stable_int("H-0181BD")
        self.assertEqual(a, b)
        self.assertEqual(a, harness.stable_int("H-0181BD", 10_000_000))
        self.assertNotEqual(harness.stable_int("H-0181BD"), harness.stable_int("H-OTHER"))

    def test_mut_id_stable(self):
        self.assertEqual(
            harness.mut_id("CUS", "H-1", "look"),
            harness.mut_id("CUS", "H-1", "look"),
        )
        self.assertTrue(harness.mut_id("CUS", "H-1", "look").startswith("CUS-"))

    def test_lookalike_phone_uses_stable_int(self):
        phone = f"+1 555{harness.stable_int('H-0181BD', 10_000_000):07d}"
        self.assertRegex(phone, r"^\+1 555\d{7}$")
        self.assertEqual(phone, f"+1 555{harness.stable_int('H-0181BD', 10_000_000):07d}")


if __name__ == "__main__":
    unittest.main()
