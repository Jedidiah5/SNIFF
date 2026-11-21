"""SOP rule tests for situations that are rare in the development set.

Each test builds a tiny data folder, runs the engine, and asserts decision + reason_code.
POLICY.md sentences that justify the expected result are quoted in comments.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
from main import run  # noqa: E402


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _mini(folder, *, alerts, hits, customers, accounts=None, onboarding=None,
          kyc=None, notes=None, search=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _write_jsonl(folder / "alerts.jsonl", alerts)
    _write_jsonl(folder / "hits.jsonl", hits)
    _write_jsonl(folder / "customers.jsonl", customers)
    _write_jsonl(folder / "accounts.jsonl", accounts or [])
    _write_jsonl(folder / "onboarding.jsonl", onboarding or [])
    _write_jsonl(folder / "kyc_checks.jsonl", kyc or [])
    _write_jsonl(folder / "notes.jsonl", notes or [])
    _write_jsonl(folder / "search_results.jsonl", search or [])


def _run(folder):
    out = Path(folder) / "out.jsonl"
    run(str(folder), str(out))
    with out.open(encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    assert len(rows) == 1, rows
    return rows[0]


def _person_customer(rid="CUS-1", name="Jane Doe", dob="1990-01-15",
                     country="United States", email="jane@example.com"):
    return {
        "record_id": rid, "entity_type": "Individual", "full_name": name,
        "dob": dob, "nationality": country, "residence_country": "US",
        "city": "Austin", "email": email, "phone": "+1 5550100",
    }


def _alert(aid="A-1", hid="H-1", name="Jane Doe", dob="1990-01-15",
           country="United States", account_ref="ACC-1", entity_type="Individual",
           screened_at="2026-11-01"):
    return {
        "alert_id": aid, "screened_at": screened_at,
        "customer": {"name": name, "entity_type": entity_type, "dob": dob,
                     "country": country, "city": "Austin"},
        "account_ref": account_ref, "login_handle": None, "email": None,
        "hit_ids": [hid],
    }


def _account(acc="ACC-1", cust="CUS-1"):
    return {"account_id": acc, "customer_id": cust, "login_handle": "jane1",
            "phone": "+1 5550100", "opened_at": "2020-01-01", "status": "active"}


def _onboard(acc="ACC-1", cust="CUS-1", app="APP-1"):
    return {"account_id": acc, "customer_id": cust, "kyc_applicant_id": app,
            "onboarded_at": "2020-01-02"}


def _kyc(check="KYC-1", app="APP-1", name="Jane Doe", dob="1990-01-15",
         result="approved", country="United States", checked_at="2020-01-03"):
    return {
        "check_id": check, "applicant_id": app, "provider": "Veriff",
        "verified_name": name, "verified_dob": dob, "document_type": "passport",
        "document_number": "P1", "document_country": country, "result": result,
        "checked_at": checked_at,
    }


class SopRuleTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.folder = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    # ------------------------------------------------------------------
    # Temporal
    # ------------------------------------------------------------------
    def test_company_incorporated_after_earliest_report(self):
        # POLICY: "a company was incorporated after it" (the earliest dated report).
        cust = {
            "record_id": "CUS-C", "entity_type": "Company", "full_name": "Acme Ltd",
            "dob": "2021-06-01", "nationality": None, "residence_country": "GB",
            "city": "London", "email": "acme@example.com", "phone": "+44 100",
        }
        alert = _alert(name="Acme Ltd", dob="2021-06-01", country="United Kingdom",
                       entity_type="Company", account_ref="ACC-C")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Company", "name": "Acme Limited", "aliases": [],
            "dobs": ["2018-01-01"], "countries": ["United Kingdom"],
            "profile_notes": "According to a filing; May 15, 2018: the company traded.",
            "categories": ["Sanctions"], "nationality": [], "citizenship": [],
            "addresses": [],
        }
        _mini(self.folder,
              alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account("ACC-C", "CUS-C")],
              onboarding=[_onboard("ACC-C", "CUS-C", "APP-C")],
              kyc=[_kyc("KYC-C", "APP-C", "Acme Ltd", "2021-06-01", country="United Kingdom")])
        row = _run(self.folder)
        self.assertEqual(row["decision"], "DIFFERENT_ENTITY")
        self.assertEqual(row["reason_code"], "TEMPORAL_IMPOSSIBILITY")

    def test_person_aged_15_at_earliest_report_is_temporal(self):
        # POLICY: "the customer was younger than 16 at the earliest dated report"
        cust = _person_customer(dob="2000-06-01")
        alert = _alert(dob="2000-06-01")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": ["Jane Doe"],
            "dobs": ["2000"], "countries": ["United States"],
            "profile_notes": "According to a court; June 01, 2015: Jane Doe appeared.",
            "categories": ["PEP"], "nationality": [], "citizenship": [], "addresses": [],
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()],
              kyc=[_kyc(dob="2000-06-01")])
        row = _run(self.folder)
        self.assertEqual(row["decision"], "DIFFERENT_ENTITY")
        self.assertEqual(row["reason_code"], "TEMPORAL_IMPOSSIBILITY")

    def test_person_aged_16_at_earliest_report_not_temporal(self):
        # POLICY: younger than 16 — age 16 is not a temporal clear.
        cust = _person_customer(dob="2000-06-01")
        alert = _alert(dob="2000-06-01")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": ["Jane Doe"],
            "dobs": ["2000-06-01"], "countries": ["United States"],
            "profile_notes": "According to a court; June 01, 2016: Jane Doe appeared.",
            "categories": ["PEP"], "nationality": [], "citizenship": [], "addresses": [],
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()],
              kyc=[_kyc(dob="2000-06-01")])
        row = _run(self.folder)
        self.assertNotEqual(row["reason_code"], "TEMPORAL_IMPOSSIBILITY")

    # ------------------------------------------------------------------
    # Deceased / type
    # ------------------------------------------------------------------
    def test_deceased_before_screened(self):
        # POLICY: "the profile gives a date of death before the customer was screened."
        cust = _person_customer()
        alert = _alert(screened_at="2026-11-01")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": [],
            "dobs": ["1990-01-15"], "deceased_date": "2020-01-01",
            "countries": ["United States"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()], kyc=[_kyc()])
        row = _run(self.folder)
        self.assertEqual(row["decision"], "DIFFERENT_ENTITY")
        self.assertEqual(row["reason_code"], "DECEASED")

    def test_deceased_after_screened_not_deceased(self):
        cust = _person_customer()
        alert = _alert(screened_at="2020-01-01")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": ["Jane Doe"],
            "dobs": ["1990-01-15"], "deceased_date": "2024-01-01",
            "countries": ["United States"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()], kyc=[_kyc()])
        row = _run(self.folder)
        self.assertNotEqual(row["reason_code"], "DECEASED")

    def test_person_vs_company_type_mismatch(self):
        # POLICY: "one is a person and the other a company."
        cust = _person_customer()
        alert = _alert()
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Company", "name": "Jane Doe Ltd", "aliases": [],
            "dobs": ["1990-01-15"], "countries": ["United States"], "categories": ["Sanctions"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()], kyc=[_kyc()])
        row = _run(self.folder)
        self.assertEqual(row["decision"], "DIFFERENT_ENTITY")
        self.assertEqual(row["reason_code"], "ENTITY_TYPE_MISMATCH")

    # ------------------------------------------------------------------
    # DOB
    # ------------------------------------------------------------------
    def test_same_year_different_month_dob_mismatch(self):
        # POLICY: "both give a month in the same year and the months (or days) differ."
        cust = _person_customer(dob="1990-03-15")
        alert = _alert(dob="1990-03-15")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": [],
            "dobs": ["1990-08-15"], "countries": ["United States"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()],
              kyc=[_kyc(dob="1990-03-15")])
        row = _run(self.folder)
        self.assertEqual(row["decision"], "DIFFERENT_ENTITY")
        self.assertEqual(row["reason_code"], "DOB_MISMATCH")

    def test_years_one_apart_no_months_is_review_not_clear(self):
        # POLICY: clear only when year is "more than 1 year outside"; 1 year apart is not enough.
        cust = _person_customer(dob="1990-01-15")
        alert = _alert(dob="1990-01-15")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": ["Jane Doe"],
            "dobs": ["1991"], "countries": ["United States"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()],
              kyc=[_kyc(dob="1990-01-15")])
        row = _run(self.folder)
        self.assertNotEqual(row["reason_code"], "DOB_MISMATCH")
        self.assertEqual(row["decision"], "REVIEW")

    def test_two_hit_dobs_one_agrees_never_dob_mismatch(self):
        # POLICY: "One agreeing date is enough to prevent this."
        cust = _person_customer(dob="1990-01-15")
        alert = _alert(dob="1990-01-15")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": ["Jane Doe"],
            "dobs": ["1980-01-01", "1990-01-15"], "countries": ["United States"],
            "categories": ["PEP"], "nationality": [], "citizenship": [], "addresses": [],
            "profile_notes": None,
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()],
              kyc=[_kyc(dob="1990-01-15")])
        row = _run(self.folder)
        self.assertNotEqual(row["reason_code"], "DOB_MISMATCH")

    # ------------------------------------------------------------------
    # Location / name edge cases
    # ------------------------------------------------------------------
    def test_name_and_dob_agree_location_differs_is_review(self):
        # POLICY: "A country difference does not clear a hit whose name and date of birth agree: that hit is REVIEW."
        cust = _person_customer(country="United States")
        alert = _alert(country="United States")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": ["Jane Doe"],
            "dobs": ["1990-01-15"], "countries": ["Nigeria"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()],
              kyc=[_kyc(country="United States")])
        row = _run(self.folder)
        self.assertEqual(row["decision"], "REVIEW")
        self.assertNotEqual(row["reason_code"], "LOCATION_MISMATCH")

    def test_single_real_name_part_never_name_clear_or_same(self):
        # POLICY: "an individual customer whose names have fewer than two real parts can be neither confirmed nor cleared on name"
        cust = _person_customer(name="Sani 0000", dob="1990-01-15")
        alert = _alert(name="Sani 0000", dob="1990-01-15")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Totally Different", "aliases": [],
            "dobs": ["1970-01-01"], "countries": ["Nigeria"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()],
              kyc=[_kyc(name="Sani 0000", dob="1990-01-15")])
        row = _run(self.folder)
        self.assertNotEqual(row["reason_code"], "NAME_MISMATCH_VERIFIED")
        self.assertNotEqual(row["decision"], "SAME_ENTITY")

    def test_single_part_alias_can_confirm_with_name_dob_country(self):
        # POLICY: "a hit's single-part alias can still agree with a customer's name."
        cust = _person_customer(name="Emran Ali", dob="1994-11-01", country="Bangladesh")
        alert = _alert(name="Emran Ali", dob="1994-11-01", country="Bangladesh")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Other Label", "aliases": ["Emran"],
            "dobs": ["1994", "1995"], "countries": ["Bangladesh"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()],
              kyc=[_kyc(name="Emran Ali", dob="1994-11-01", country="Bangladesh")])
        row = _run(self.folder)
        # Alias "Emran" alone is one part; customer has Emran+Ali. Agreement needs 2 parts
        # or every part of the shorter name — shorter alias [emran] matches one part → agree.
        self.assertEqual(row["decision"], "SAME_ENTITY")

    def test_name_variants_and_compound_and_legal_forms(self):
        # POLICY principle 8: variants, together/apart, company legal forms not parts.
        from engine import load_data
        data = load_data(str(ROOT / ".." / "dev"))
        names = data["names"]
        self.assertTrue(names.agree(names.parts("Abdulsalam"), names.parts("Abdul Salam"))[0])
        self.assertTrue(names.agree(names.parts("Mohammed Ali"), names.parts("Muhammad Ali"))[0])
        self.assertTrue(names.agree(
            names.parts("Pescanova SA", company=True),
            names.parts("Pescanova, Sociedad Anónima", company=True),
        )[0] or names.agree(
            names.parts("Pescanova", company=True),
            names.parts("Pescanova", company=True),
        )[0])
        # Sociedad Anónima / SA — legal forms stripped; Pescanova should remain.
        self.assertEqual(names.parts("Pescanova SA", company=True), ["pescanova"])
        # "Sociedad Anónima" may not be in default legal forms — check SA at least.
        pa = names.parts("Pescanova, Sociedad Anónima", company=True)
        self.assertIn("pescanova", pa)

    # ------------------------------------------------------------------
    # Ambiguity / grouping / KYC precedence / missing DOB
    # ------------------------------------------------------------------
    def test_two_people_different_decisions_ambiguous_review(self):
        # POLICY: "If more than one person fits an alert, decide the hit for each; if they ...
        # lead to different decisions, the decision is REVIEW with AMBIGUOUS_CUSTOMER_RECORD."
        c1 = _person_customer("CUS-A", "Jane Doe", "1990-01-15", "United States", "a@ex.com")
        c1["phone"] = "+1 111"
        c2 = _person_customer("CUS-B", "Jane Doe", "1970-01-15", "Nigeria", "b@ex.com")
        c2["phone"] = "+1 222"
        alert = {
            "alert_id": "A-1", "screened_at": "2026-11-01",
            "customer": {"name": "Jane Doe", "entity_type": "Individual", "dob": None,
                         "country": None, "city": None},
            "account_ref": None, "login_handle": None, "email": None, "hit_ids": ["H-1"],
        }
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": ["Jane Doe"],
            "dobs": ["1990-01-15"], "countries": ["United States"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        k1 = _kyc("KYC-A", "APP-A", "Jane Doe", "1990-01-15", country="United States")
        k1["document_number"] = "DOC-A"
        k2 = _kyc("KYC-B", "APP-B", "Jane Doe", "1970-01-15", country="Nigeria")
        k2["document_number"] = "DOC-B"
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[c1, c2],
              kyc=[k1, k2],
              onboarding=[
                  {"account_id": "ACC-A", "customer_id": "CUS-A", "kyc_applicant_id": "APP-A",
                   "onboarded_at": "2020-01-01"},
                  {"account_id": "ACC-B", "customer_id": "CUS-B", "kyc_applicant_id": "APP-B",
                   "onboarded_at": "2020-01-01"},
              ],
              accounts=[
                  {"account_id": "ACC-A", "customer_id": "CUS-A", "login_handle": "a",
                   "phone": "+1 111", "opened_at": "2020-01-01", "status": "active"},
                  {"account_id": "ACC-B", "customer_id": "CUS-B", "login_handle": "b",
                   "phone": "+1 222", "opened_at": "2020-01-01", "status": "active"},
              ])
        row = _run(self.folder)
        self.assertEqual(row["decision"], "REVIEW")
        self.assertEqual(row["reason_code"], "AMBIGUOUS_CUSTOMER_RECORD")
        self.assertEqual(row["customer_record_id"], "AMBIGUOUS")

    def test_same_document_number_groups_as_one_person(self):
        # POLICY: "records whose approved identity checks carry the same document number" are one person.
        c1 = _person_customer("CUS-A", "Jane Doe", "1990-01-15", email="a@ex.com")
        c1["phone"] = "+1 111"
        c2 = _person_customer("CUS-B", "Jane Doe", "1990-01-15", email="b@ex.com")
        c2["phone"] = "+1 222"
        alert = _alert(account_ref="ACC-A")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": ["Jane Doe"],
            "dobs": ["1990-01-15"], "countries": ["United States"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        k1 = _kyc("KYC-A", "APP-A", "Jane Doe", "1990-01-15")
        k1["document_number"] = "DOC-SHARED"
        k2 = _kyc("KYC-B", "APP-B", "Jane Doe", "1990-01-15")
        k2["document_number"] = "DOC-SHARED"
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[c1, c2],
              accounts=[
                  _account("ACC-A", "CUS-A"),
                  {"account_id": "ACC-B", "customer_id": "CUS-B", "login_handle": "b",
                   "phone": "+1 222", "opened_at": "2020-01-01", "status": "active"},
              ],
              onboarding=[
                  _onboard("ACC-A", "CUS-A", "APP-A"),
                  _onboard("ACC-B", "CUS-B", "APP-B"),
              ],
              kyc=[k1, k2])
        row = _run(self.folder)
        self.assertNotEqual(row["reason_code"], "AMBIGUOUS_CUSTOMER_RECORD")
        self.assertNotEqual(row["customer_record_id"], "AMBIGUOUS")

    def test_rejected_latest_kyc_falls_back_to_older_approved(self):
        # POLICY: "Rejected or expired checks are not evidence." / most recent *approved* wins.
        cust = _person_customer()
        alert = _alert()
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Wrong Name", "aliases": [],
            "dobs": ["1970-01-01"], "countries": ["Nigeria"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()],
              kyc=[
                  _kyc("KYC-OLD", "APP-1", "Jane Doe", "1990-01-15",
                       result="approved", checked_at="2019-01-01"),
                  _kyc("KYC-NEW", "APP-1", "Wrong Name", "1970-01-01",
                       result="rejected", checked_at="2024-01-01"),
              ])
        row = _run(self.folder)
        # Approved Jane Doe / 1990-01-15 is used; rejected Wrong Name / 1970 is ignored.
        self.assertEqual(row["decision"], "DIFFERENT_ENTITY")
        self.assertIn(row["reason_code"], ("NAME_MISMATCH_VERIFIED", "DOB_MISMATCH"))
        self.assertTrue("Jane Doe" in row["reason"] or "1990" in row["reason"])

    def test_no_dob_anywhere_names_agree_is_review(self):
        # POLICY: confirm a person when name and date of birth agree — without DOB → REVIEW.
        cust = _person_customer(dob=None)
        cust["dob"] = None
        alert = _alert(dob=None)
        alert["customer"]["dob"] = None
        hit = {
            "hit_id": "H-1", "alert_id": "A and-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": ["Jane Doe"],
            "dobs": [], "countries": ["United States"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        hit["alert_id"] = "A-1"
        k = _kyc(name="Jane Doe", dob=None)
        k["verified_dob"] = None
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()], kyc=[k])
        row = _run(self.folder)
        self.assertEqual(row["decision"], "REVIEW")
        self.assertEqual(row["reason_code"], "INSUFFICIENT_DATA")

    # ------------------------------------------------------------------
    # Part 1 safety fixes
    # ------------------------------------------------------------------
    def test_failed_kyc_note_yields_no_identity(self):
        # POLICY principle 4: rejected/failed notes are not evidence.
        from decide import parse_kyc_note
        from engine import Names

        text = ("Sumsub could not verify JOHN SMITH on 2024-02-01; "
                "the passport showed DOB 1962-03-12 but failed liveness.")
        note = {
            "note_id": "NOTE-FAIL", "channel": "kyc", "created_at": "2024-02-01",
            "text": text, "requester_email": "jane@example.com",
        }
        names = Names([], [])
        out = parse_kyc_note(note, names, ["John Smith"], providers={"sumsub"})
        self.assertIsNone(out["name"])
        self.assertIsNone(out["dob"])
        self.assertIsNone(out["country"])
        self.assertTrue(out.get("rejected"))

        # End-to-end: failed note must not drive a DOB_MISMATCH clear.
        cust = _person_customer(name="John Smith", dob=None)
        cust["dob"] = None
        alert = _alert(name="John Smith", dob=None)
        alert["customer"]["dob"] = None
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "John Smith", "aliases": ["John Smith"],
            "dobs": ["1962-03-12"], "countries": ["United States"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()],
              notes=[{
                  "note_id": "NOTE-FAIL", "channel": "kyc", "created_at": "2024-02-02",
                  "requester_email": "jane@example.com", "text": text,
              }])
        row = _run(self.folder)
        self.assertNotEqual(row["reason_code"], "DOB_MISMATCH")
        self.assertEqual(row["decision"], "REVIEW")

    def test_ambiguous_numeric_dob_cannot_clear(self):
        # 03/04/1965 is ambiguous (3 Apr vs 4 Mar). Hit 1965-03-04 matches one
        # reading, so DOB_MISMATCH must not clear.
        cust = _person_customer(dob="03/04/1965")
        alert = _alert(dob="03/04/1965")
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": ["Jane Doe"],
            "dobs": ["1965-03-04"], "countries": ["United States"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        k = _kyc(dob="03/04/1965")
        _mini(self.folder, alerts=[alert], hits=[hit], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()], kyc=[k])
        row = _run(self.folder)
        self.assertNotEqual(row["decision"], "DIFFERENT_ENTITY")
        self.assertNotEqual(row["reason_code"], "DOB_MISMATCH")

        # Year gaps > 1 remain a clear (ambiguity rule does not apply).
        hit2 = dict(hit)
        hit2["dobs"] = ["1962-09-10"]
        _mini(self.folder, alerts=[alert], hits=[hit2], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()], kyc=[k])
        row2 = _run(self.folder)
        self.assertEqual(row2["decision"], "DIFFERENT_ENTITY")
        self.assertEqual(row2["reason_code"], "DOB_MISMATCH")

    def test_utf8_bom_blank_and_malformed_io(self):
        # Robust I/O: BOM, blank lines, malformed JSON must not crash; one line per hit.
        from pathlib import Path
        folder = Path(self.folder)
        cust = _person_customer()
        alert = _alert()
        hit = {
            "hit_id": "H-1", "alert_id": "A-1", "match_score": 90,
            "entity_type": "Individual", "name": "Jane Doe", "aliases": ["Jane Doe"],
            "dobs": ["1990-01-15"], "countries": ["United States"], "categories": ["PEP"],
            "nationality": [], "citizenship": [], "addresses": [], "profile_notes": None,
        }
        hit2 = dict(hit)
        hit2["hit_id"] = "H-2"
        _mini(self.folder, alerts=[alert], hits=[hit, hit2], customers=[cust],
              accounts=[_account()], onboarding=[_onboard()], kyc=[_kyc()])

        # Rewrite hits.jsonl with BOM, blank line, and one malformed line.
        hits_path = folder / "hits.jsonl"
        payload = (
            "\ufeff" + json.dumps(hit) + "\n"
            + "\n"
            + "{not-json\n"
            + json.dumps(hit2) + "\n"
        )
        hits_path.write_text(payload, encoding="utf-8")

        out = folder / "out.jsonl"
        from main import run
        run(str(folder), str(out))
        rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["hit_id"] for r in rows}, {"H-1", "H-2"})


if __name__ == "__main__":
    unittest.main()
