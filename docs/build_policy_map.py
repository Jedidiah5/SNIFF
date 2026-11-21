"""Generate docs/POLICY_MAP.md from decide.POLICY_RULES so docs cannot drift from code."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
from decide import POLICY_RULES  # noqa: E402

DECISION = {
    "TEMPORAL_IMPOSSIBILITY": "DIFFERENT_ENTITY",
    "DOB_MISMATCH": "DIFFERENT_ENTITY",
    "LOCATION_MISMATCH": "DIFFERENT_ENTITY",
    "NAME_MISMATCH_VERIFIED": "DIFFERENT_ENTITY",
    "ENTITY_TYPE_MISMATCH": "DIFFERENT_ENTITY",
    "DECEASED": "DIFFERENT_ENTITY",
    "NAME_DOB_LOCATION_MATCH": "SAME_ENTITY",
    "NAME_DOB_MATCH": "SAME_ENTITY",
    "NAME_LOCATION_MATCH": "SAME_ENTITY",
    "INSUFFICIENT_DATA": "REVIEW",
    "AMBIGUOUS_CUSTOMER_RECORD": "REVIEW",
}

# reason_code -> (enforcing function, test method name)
ENFORCEMENT = {
    "TEMPORAL_IMPOSSIBILITY": ("decide_person (temporal)", "test_company_incorporated_after_earliest_report; test_person_aged_15_at_earliest_report_is_temporal"),
    "DOB_MISMATCH": ("decide_person (dob)", "test_same_year_different_month_dob_mismatch; test_two_hit_dobs_one_agrees_never_dob_mismatch"),
    "LOCATION_MISMATCH": ("decide_person (location)", "test_name_and_dob_agree_location_differs_is_review"),
    "NAME_MISMATCH_VERIFIED": ("decide_person (names)", "test_single_real_name_part_never_name_clear_or_same; test_rejected_latest_kyc_falls_back_to_older_approved"),
    "ENTITY_TYPE_MISMATCH": ("decide_person (type)", "test_person_vs_company_type_mismatch"),
    "DECEASED": ("decide_person (deceased)", "test_deceased_before_screened; test_deceased_after_screened_not_deceased"),
    "NAME_DOB_LOCATION_MATCH": ("decide_person (confirm)", "test_single_part_alias_can_confirm_with_name_dob_country"),
    "NAME_DOB_MATCH": ("decide_person (confirm)", "test_years_one_apart_no_months_is_review_not_clear"),
    "NAME_LOCATION_MATCH": ("decide_person (confirm company)", "test_person_vs_company_type_mismatch (company path covered in engine)"),
    "INSUFFICIENT_DATA": ("decide_person / decide_hit", "test_no_dob_anywhere_names_agree_is_review; test_name_and_dob_agree_location_differs_is_review"),
    "AMBIGUOUS_CUSTOMER_RECORD": ("decide_hit", "test_two_people_different_decisions_ambiguous_review"),
}

ORDER = [
    "TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH", "LOCATION_MISMATCH", "NAME_MISMATCH_VERIFIED",
    "ENTITY_TYPE_MISMATCH", "DECEASED", "NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH",
    "NAME_LOCATION_MATCH", "INSUFFICIENT_DATA", "AMBIGUOUS_CUSTOMER_RECORD",
]


def main():
    lines = [
        "# POLICY_MAP",
        "",
        "Generated from `system/decide.py:POLICY_RULES` by `docs/build_policy_map.py`.",
        "Do not edit the reason-code table by hand — regenerate it.",
        "",
        "## Reason codes",
        "",
        "| Reason code | Decision | Principle + exact POLICY sentence | Enforced in | Proven by |",
        "|---|---|---|---|---|",
    ]
    for code in ORDER:
        meta = POLICY_RULES[code]
        enf, test = ENFORCEMENT[code]
        rule = meta["rule"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{code}` | `{DECISION[code]}` | **{meta['principle']}.** {rule} | `{enf}` | `{test}` |"
        )

    lines += [
        "",
        "## Non-code principles (enforced across the pipeline)",
        "",
        "| Principle | Exact duty | Where |",
        "|---|---|---|",
        "| **2** Know who the customer is | Follow the alert link; without a link, find records that fit the screened name/DOB/country/city. | `resolve`, `fits_screened` |",
        "| **3** One person, one picture | Same phone + full DOB, or same approved document number → one person; else decide each and `AMBIGUOUS` if they disagree. | `group_persons`, `decide_hit` |",
        "| **4** Verified beats declared | Latest *approved* KYC check or KYC note wins; rejected/expired ignored. | `customer_facts`, `parse_kyc_note` |",
        "| **5** Hit facts + search filter | DOB from `dobs`, else profile notes, else search only if listing phrase + hit country; companies: **only** `dobs`. Dated reports: `According to …; Month DD, YYYY:`. | `hit_dobs`, `earliest_report`, `listing_phrase` |",
        "| **8** Names | Accents/punctuation/brackets ignored; variants; together/apart; edit distance; placeholders not parts; company legal forms not parts. | `engine.Names` |",
        "| **9** Cite what you used | Decision names record IDs and the resolved customer (`null` / `AMBIGUOUS`). | output `evidence`, `customer_record_id` |",
        "",
        "## Engineering choices",
        "",
        "Free-text guards (failed note-name check does not poison DOB; Title Case / after-only keyword / "
        "name-failed+note-DOB confirms; all-fragile unusual clears) fall back to `REVIEW`.",
        "",
        "> Clearing a hit that is the customer is the worst mistake; when in doubt, `REVIEW`.",
        "",
        "Run with `--debug` to attach a per-hit `trace` (`principle`, `rule`, `facts`, `fragile_guard`, `resolution`).",
        "",
    ]
    out = ROOT / "docs" / "POLICY_MAP.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
