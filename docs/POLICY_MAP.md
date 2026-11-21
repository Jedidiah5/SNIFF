# POLICY map

Generated from `system/decide.py` → `POLICY_RULES` by `tools_policy_map.py`.
Do not edit the reason-code table by hand — regenerate it.

## Reason codes

| Reason code | Decision | Principle + exact POLICY sentence | Enforced in | Test |
|---|---|---|---|---|
| `TEMPORAL_IMPOSSIBILITY` | `DIFFERENT_ENTITY` | **6.** the customer was younger than 16 at the earliest dated report, or a company was incorporated after it; or the profile gives a date of death before the customer was screened. | `decide_person (temporal branch)` | `test_company_incorporated_after_earliest_report; test_person_aged_15_at_earliest_report_is_temporal; test_person_aged_16_at_earliest_report_not_temporal` |
| `DOB_MISMATCH` | `DIFFERENT_ENTITY` | **6.** every birth date the hit gives is contradicted: the customer's birth year is more than 1 year outside it, or both give a month in the same year and the months (or days) differ. One agreeing date is enough to prevent this. | `decide_person (DOB contradiction)` | `test_same_year_different_month_dob_mismatch; test_years_one_apart_no_months_is_review_not_clear; test_two_hit_dobs_one_agrees_never_dob_mismatch` |
| `LOCATION_MISMATCH` | `DIFFERENT_ENTITY` | **6.** every country tied to the customer (residence and nationality on all their records, the approved identity document, and places the notes say they lived) differs from every country tied to the hit. Codes and nationalities are countries; territories count as their own country. A country difference does not clear a hit whose name and date of birth agree: that hit is `REVIEW`. | `decide_person (location contradiction)` | `test_name_and_dob_agree_location_differs_is_review` |
| `NAME_MISMATCH_VERIFIED` | `DIFFERENT_ENTITY` | **6.** the customer's verified legal name agrees with none of the hit's names or aliases (principle 8), even if the name on their record does. | `decide_person (verified name contradiction)` | `test_single_real_name_part_never_name_clear_or_same; test_rejected_latest_kyc_falls_back_to_older_approved` |
| `ENTITY_TYPE_MISMATCH` | `DIFFERENT_ENTITY` | **6.** one is a person and the other a company. | `decide_person (type contradiction)` | `test_person_vs_company_type_mismatch` |
| `DECEASED` | `DIFFERENT_ENTITY` | **6.** the customer was younger than 16 at the earliest dated report, or a company was incorporated after it; or the profile gives a date of death before the customer was screened. | `decide_person (deceased branch)` | `test_deceased_before_screened; test_deceased_after_screened_not_deceased` |
| `NAME_DOB_LOCATION_MATCH` | `SAME_ENTITY` | **7.** Confirm a person when name and date of birth agree and nothing contradicts them; a company when name and country agree and nothing contradicts them. Otherwise, `REVIEW`. | `decide_person (agreement)` | `test_single_part_alias_can_confirm_with_name_dob_country` |
| `NAME_DOB_MATCH` | `SAME_ENTITY` | **7.** Confirm a person when name and date of birth agree and nothing contradicts them; a company when name and country agree and nothing contradicts them. Otherwise, `REVIEW`. | `decide_person (agreement without shared country — only when one side has no countries)` | `(covered indirectly; shared-country conflict is REVIEW per principle 6 location clause)` |
| `NAME_LOCATION_MATCH` | `SAME_ENTITY` | **7.** Confirm a person when name and date of birth agree and nothing contradicts them; a company when name and country agree and nothing contradicts them. Otherwise, `REVIEW`. | `decide_person (company agreement)` | `(company name+country confirm path in decide_person)` |
| `INSUFFICIENT_DATA` | `REVIEW` | **7.** Confirm a person when name and date of birth agree and nothing contradicts them; a company when name and country agree and nothing contradicts them. Otherwise, `REVIEW`. | `decide_person / decide_hit` | `test_no_dob_anywhere_names_agree_is_review; test_name_and_dob_agree_location_differs_is_review` |
| `AMBIGUOUS_CUSTOMER_RECORD` | `REVIEW` | **3.** If more than one person fits an alert, decide the hit for each; if they all lead to the same decision, give it, otherwise the decision is `REVIEW` with `AMBIGUOUS_CUSTOMER_RECORD`. Either way `customer_record_id` is `AMBIGUOUS`. | `decide_hit (multi-person)` | `test_two_people_different_decisions_ambiguous_review; test_same_document_number_groups_as_one_person` |

## Non-code principles (how the engine uses them)

| Principle | Role in the engine |
|---|---|
| **2. Know who the customer is** | `resolve()` / `fits_screened()` follow account_ref, login_handle, email, else name search. |
| **3. One person, one picture** | `group_persons()` merges by phone+full DOB or shared approved document number; multi-person disagreement → `AMBIGUOUS_CUSTOMER_RECORD`. |
| **4. Verified beats declared** | `customer_facts()` takes the latest **approved** KYC check or KYC note; rejected/expired checks are ignored. |
| **5. Gather the hit's facts** | `hit_dobs()` / `hit_countries()` / `earliest_report()`; search snippets only with listing phrase + shared country; **companies: `dobs` only**. |
| **8. Names** | `engine.Names` (variants, together/apart, edit distance, legal forms, placeholders). |
| **9. Cite what you used** | Output `evidence` and `customer_record_id`; `--debug` adds `path` and `trace`. |

## Engineering choices

Free-text guards (failed note-name trust, after-only birth-keyword DOBs, Title Case confirms, all-fragile unusual clears) fall back to `REVIEW` / `INSUFFICIENT_DATA`.

> Clearing a hit that is the customer is the worst mistake; when in doubt, `REVIEW`.

Run with `--debug` to attach a per-hit `trace` object: principle, exact rule, facts, `fragile_guard`, and resolution path.
