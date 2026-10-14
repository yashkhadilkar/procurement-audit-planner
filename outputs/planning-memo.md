# Audit planning memo: procurement (register revision r1)

Built 2026-10-14T01:07:59+00:00 by `.claude/skills/audit-program/build_pack.py` from `outputs/audit-plan.json`, on the risks the auditor approved in register r1. For auditor sign-off.

> These are **risk indicators to investigate**, drawn from published data. They are not findings and do not suggest wrongdoing by the council, any service or any supplier.

## Objective

To obtain evidence on whether the controls the Contract Procedure Rules require over procurement operated for the payments published in the spend window, for the eight risks the auditor approved or amended at the gate: aggregation of requirements and the competition and notice route for their value `rule:CPR-12` `rule:CPR-52` `rule:CPR-53` `rule:CPR-56`, publication of contract notices and a complete contracts register `rule:CPR-07`, approval of extensions and variations `rule:CPR-63` `rule:CPR-64`, evidence for every purchase `rule:CPR-30`, the approval and documentation of waivers `rule:CPR-20` `rule:CPR-24`, and the authority behind each award `rule:CPR-02` `rule:CPR-04`. The tests follow up risk indicators to investigate; they are not findings, and a flagged item may have a proper explanation such as a framework call-off or a competed contract paid in instalments.

## Background

The plan rests on the full population of payments over the publication floor for the spend window 2026-05-01 to 2026-07-31, analysed by code against the Rules, and on the Contracts Finder notice export, of which 141 notices name the council as buyer and 61 were active in the window. The most recent Contract Letting audit gave Reasonable Assurance `history:AUD-01` and the most recent Accounts Payable audit gave Reasonable Assurance `history:AUD-15`. The strongest data signal is the split-purchase tier at the quote and notice level, with 46 general procurement supplier groups `metric:$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count`; 165 general procurement suppliers at or above the publication level have no published notice found `metric:$.tests.no_published_notice.by_tag.general_procurement.count`.

## Scope

The auditor decided every row of register r1 in `outputs/auditor-comments.md`. In scope: the 8 risks approved or amended.

| Risk | Title | Likelihood | Impact | Score | Band | Decision | Tests | Sample items |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-01 | Purchases split to stay under the quote and contract-notice threshold | 4 Almost Certain | 3 Medium | 12 | Medium High (Amber) | Approve: Strongest signal in the register. | T-01 | 20 |
| R-02 | Purchases split to stay under the full-tender and Key Decision level | 2 Unlikely | 4 Major | 8 | Medium High (Amber) | Approve: Few groups but high value; examine every one. | T-02 | 2 |
| R-05 | Spend at or above the publication threshold with no published notice found | 3 Likely (auditor override; the rubric gives 4 Almost Certain) | 3 Medium | 9 | Medium High (Amber) | Amend: Lower likelihood from 4 to 3: the count is inflated by the export only holding notices since 2021 and by framework call-offs that have no notice of their own. | T-03 | 15 |
| R-06 | Spend continuing after the matching notice ended, without an approved extension | 3 Likely | 3 Medium | 9 | Medium High (Amber) | Approve | T-04 | 5 |
| R-07 | Spend beyond the awarded contract value without an approved variation | 3 Likely | 3 Medium | 9 | Medium High (Amber) | Approve | T-05 | 7 |
| R-08 | Possible duplicate payments to the same supplier | 4 Almost Certain | 2 Minor | 8 | Medium High (Amber) | Approve: Match the sampled payments to invoices. | T-06 | 15 |
| R-09 | Waivers or exceptions to the Rules not approved in advance or not documented | 2 Unlikely | 3 Medium | 6 | Moderate | Approve: The Rules disagree on who may grant a waiver; test alongside R-05. | T-07 | 0 |
| R-10 | Contract awards not made by the authorised decision-maker or not recorded as a Key Decision | 2 Unlikely | 3 Medium | 6 | Moderate | Approve: Sample the largest suppliers' award decisions. | T-08 | 10 |

### Out of scope

| Item | Title | Decision | Auditor's comment |
| --- | --- | --- | --- |
| R-03 | Payment values held just under the quote and contract-notice threshold | Reject | No clustering: fewer payments just below £25,000 than just above it. |
| R-04 | Payment values held just under the single-quote threshold | Reject | Negligible impact and low total value; not worth fieldwork time. |
| AUD-16 | Personal Budgets (Direct Payments) (Limited Assurance) | Leave out | Payments to individuals, not council procurement; covered by the existing audit's follow-up. |
| AUD-11 | Garland (now Burghfield Common Federation) (Weak) | Leave out | Single-school follow-up, outside council-level procurement. |
| AUD-12 | Westwood Farm (Limited Assurance) | Leave out | Single-school follow-up, outside council-level procurement. |

## Escalation under the Risk Management Strategy

The Risk Management Strategy contradicts itself on escalation (history DIS-04): Figure 4 places risks scoring 9 or above on the Corporate Risk Register, while Table 4 adds a risk to it only in band Extreme (score 15 -25). In-scope risks scoring 9 to 14 would go to the Corporate Risk Register under Figure 4, though not under Table 4, which the register uses: R-01 (score 12), R-05 (score 9), R-06 (score 9), R-07 (score 9).

This pack does not resolve the conflict; the auditor decides whether to raise it with the risk owner.

## Approach

Each approved risk is mapped to the controls the Rules expect and to test steps that examine them. Where an analytics test measures the risk, the sample is drawn by the builder from the general procurement rows of that test's full list, so the sample population is the population the register was rated on, ordered by value so the largest items are examined first: split-purchase groups at the quote and notice level and at the full-tender level `rule:CPR-12`, suppliers with no published notice found `metric:$.tests.no_published_notice.by_tag.general_procurement.count`, suppliers paid after their matching notice ended `metric:$.tests.expired_notice_spend.by_tag.general_procurement.count`, suppliers whose annualised spend is at or above the award ratio `metric:$.tests.spend_vs_award.by_tag.general_procurement.count`, possible duplicate payment groups `metric:$.tests.duplicates.by_tag.general_procurement.count` and the largest suppliers by value `metric:$.tests.high_value_suppliers.by_tag.general_procurement.count`. The waiver risk has no spend test; it is tested from the waiver and exception log, cross-matched to the suppliers with no published notice found as the auditor asked `rule:CPR-20`. Every sampled payment is matched to its order and invoice `rule:CPR-30`, and the request list follows from the test steps.

### Sampling

Every sample is drawn by `build_pack.py` from the general_procurement rows of the `outputs/analytics-full/` lists, the rows the register's ratings rest on; placement, grant, agency staff and premises rows are not sampled. Each test names its list, a filter, a sort order and a size. The draw is deterministic (a stable sort on the list as published, ties in list order), so the same inputs give the same sample, and every sampled transaction is checked against `spend-clean.csv`. A sample may be larger than its score gives, never smaller; where the population is smaller, all of it is taken.

| Risk score | Items per test |
| --- | --- |
| 15 to 25 | 25 |
| 10 to 14 | 20 |
| 8 to 9 | 15 |
| 4 to 7 | 10 |
| 1 to 3 | 5 |

| Test | Risk | List | Population | Size | Items | Transactions | Value |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-01 | R-01 | `split_purchases.csv` | 46 | 20 items for score 12 | 20 | 319 | £1,677,616.08 |
| T-02 | R-02 | `split_purchases.csv` | 2 | every item, at the planner's request (score 8 gives 15) | 2 | 59 | £3,510,454.59 |
| T-03 | R-05 | `no_published_notice.csv` | 165 | 15 items for score 9 | 15 | 36 | £13,949,334.20 |
| T-04 | R-06 | `expired_notice_spend.csv` | 5 | 15 items for score 9; the population is smaller, so all 5 are taken | 5 | 12 | £121,644.98 |
| T-05 | R-07 | `spend_vs_award.csv` | 7 | 15 items for score 9; the population is smaller, so all 7 are taken | 7 | 31 | £643,153.28 |
| T-06 | R-08 | `duplicates.csv` | 50 | 15 items for score 8 | 15 | 35 | £542,579.56 |
| T-07 | R-09 | none | | | | | |
| T-08 | R-10 | `high_value_suppliers.csv` | 205 | 10 items for score 6 | 10 | 28 | £13,639,190.99 |

## Limitations

The Rules name the Threshold but do not state its value `rule:CPR-52`, so the split-purchase tier at the Threshold was not run and the approval and route bands that depend on it are tested from the council's own figures once supplied. The value bands are tested on the Net amount the spend data reports; the Rules differ on the VAT basis, since the Rules' definition of Total Contract Value includes VAT while the Appendix B value column is headed exclusive of VAT `rule:CPR-52` `rule:CPR-47`, and the auditor decides which reading applies. Payments published with the supplier name withheld (147 rows, £422,766.47) cannot be grouped by supplier and are outside every supplier test. Supplier spend is an annualised estimate (window total times 4), not a contract value. The notice export holds notices published from 2021 onwards and framework call-offs have no notice of their own, so a supplier with no published notice found may be covered by an older contract or a purchasing scheme `rule:CPR-26`. Award values in notices may be estimates or maxima `rule:CPR-64`. The contract type of each payment is not in the spend data, so which tender route applies is established from the contract file `rule:CPR-56` `rule:CPR-58`. The council's contracts register and the Corporate Risk Register are not public inputs `history:GAP-07`.

## Inputs

| File | sha256 |
| --- | --- |
| `audit-plan.json` | `e854327f68b45583ffb72f82cb48d66ae36994bb171102636d6f26cfccead68b` |
| `analytics.json` | `9c21ddd22edba5a620cbb50287fcb3b6c7c3a9241d721bdb43f247cd55696d76` |
| `history.json` | `9137d23214792dd7da1259d647017d4806221a6869e2c66fd3b573922fc51dcf` |
| `rules.json` | `2faecd244736c3f25b51019bdd6e83f506495f23010f878614bbff958c6d45f1` |
| `risk-ratings.json` | `1818ec8028a5ac16816afe1b7cc8354254fcfbac41a31d8cce9d35a613d1681d` |
| `spend-clean.csv` | `66a15a5974c4b029ed6b36fbb07cda17833bcbe87f0c54d597e4ec011d1ed5b9` |

## Sources

- rule CPR-12: clause 6.16, page 5, anti-avoidance
- rule CPR-52: clause AppB-B1, page 12, threshold
- rule CPR-53: clause AppB-B1, page 12, threshold
- rule CPR-56: clause AppB-C, page 12, threshold
- rule CPR-07: clause 5.2.1, page 3, required-action
- rule CPR-63: clause AppC-D, page 14, approval
- rule CPR-64: clause AppC-E, page 14, approval
- rule CPR-30: clause 10.1, page 8, required-action
- rule CPR-20: clause 7.3, page 6, approval
- rule CPR-24: clause 7.5, page 6, required-action
- rule CPR-02: clause 4.1, page 2, approval
- rule CPR-04: clause 4.3, page 3, threshold
- history AUD-01: Contract Letting (Reasonable Assurance), data/committee/audit-completed-work-2024-25-annual.pdf p1
- history AUD-15: Accounts Payable (Reasonable Assurance), data/committee/audit-completed-work-2025-26-q3.pdf p1
- metric $.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count = 46 (primary: general_procurement)
- metric $.tests.no_published_notice.by_tag.general_procurement.count = 165 (primary: general_procurement)
- metric $.tests.expired_notice_spend.by_tag.general_procurement.count = 5 (primary: general_procurement)
- metric $.tests.spend_vs_award.by_tag.general_procurement.count = 7 (primary: general_procurement)
- metric $.tests.duplicates.by_tag.general_procurement.count = 50 (primary: general_procurement)
- metric $.tests.high_value_suppliers.by_tag.general_procurement.count = 205 (primary: general_procurement)
- rule CPR-47: clause AppA-1, page 11, approval
- rule CPR-26: clause 8.2, page 7, required-action
- rule CPR-58: clause AppB-D, page 12, threshold
- history GAP-07: The Corporate Risk Register is not among the papers in data/committee/. The strategy sa..., data/committee/risk-management-strategy-2024-27.pdf p28
- history DIS-04: Figure 4 says the Corporate Risk Register (CRR) "Includes risks that: Score 9 or above"..., data/committee/risk-management-strategy-2024-27.pdf p21
