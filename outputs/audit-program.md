# Audit program (register revision r1)

Built 2026-10-14T01:07:59+00:00 by `.claude/skills/audit-program/build_pack.py` from `outputs/audit-plan.json`, on the risks the auditor approved in register r1. For auditor sign-off.

> These are **risk indicators to investigate**, drawn from published data. They are not findings and do not suggest wrongdoing by the council, any service or any supplier.

Per approved risk: the expected controls, the test steps, and the sample each test pulls. Sampled transactions are in `outputs/samples/`, one file per test. The PBC (request) list closes the program.

## R-01 Purchases split to stay under the quote and contract-notice threshold

Score 12: likelihood 4 Almost Certain x impact 3 Medium, band Medium High (Amber). Auditor's decision: Approve. Comment: Strongest signal in the register.

**Expected controls**

- **C-01** Each requirement is valued as a whole before the procurement route is chosen, and is not split or disaggregated to avoid the Rules `rule:CPR-12`.
- **C-02** For requirements from the quote and notice level up to the Threshold, quotes are invited through the Procurement Portal from at least three appropriate sources `rule:CPR-52` `rule:CPR-54` and a contract notice is published `rule:CPR-53` `rule:CPR-55`, with the progress of the procedure documented `rule:CPR-29`.

**Tests**

### T-01 (tests C-01, C-02)

For each sampled supplier group, obtain the purchase orders, requisitions and invoices for the payments in the qualifying window and establish whether they relate to one requirement `rule:CPR-12`. Where they do, confirm that quotes were invited through the Procurement Portal from at least three sources `rule:CPR-52` `rule:CPR-54`, that a contract notice was published `rule:CPR-53` `rule:CPR-55` and that the procedure is documented `rule:CPR-29`. Where the payments are call-offs under a framework or other purchasing scheme, obtain the scheme record and the approval for its use instead `rule:CPR-26` `rule:CPR-62`. The indicator is cleared where the payments are separate requirements or were procured through the correct route; it is confirmed where one requirement was procured without the quotes or notice its combined value calls for `metric:$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count`.

- **Population:** `outputs/analytics-full/split_purchases.csv`, general_procurement rows where threshold = 25000: 46 (`metric:$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count`).
- **Selection:** sorted by best_window_total descending; size 20 items for score 12.
- **Drawn:** 20 items, 319 transactions from best_window_ids, £1,677,616.08: `outputs/samples/T-01.csv`.
- **Needs:** PBC-01, PBC-02, PBC-03, PBC-08, PBC-11

## R-02 Purchases split to stay under the full-tender and Key Decision level

Score 8: likelihood 2 Unlikely x impact 4 Major, band Medium High (Amber). Auditor's decision: Approve. Comment: Few groups but high value; examine every one.

**Expected controls**

- **C-03** Requirements whose total value is above the full-tender level are procured by full competitive tender with the required number of written tenders sought through the Procurement Portal and advertised `rule:CPR-56` `rule:CPR-57`, or above the Threshold by the Procurement Legislation procedures `rule:CPR-58` `rule:CPR-59`, recorded in a written procurement report `rule:CPR-27`, and are not split to avoid them `rule:CPR-12`.
- **C-04** An award above the Key Decision level is taken and recorded as a Key Decision by the decision-maker the Rules name for its value `rule:CPR-04` `rule:CPR-49` `rule:CPR-50`.

**Tests**

### T-02 (tests C-03, C-04)

For every supplier group in the full-tender tier, obtain the contract, the tender record and the Key Decision record `metric:$.tests.split_purchases.by_threshold[threshold=500000].by_tag.general_procurement.count`. Establish the contract type and whether the payments are instalments under one competed contract. Where they are, confirm that the tender followed the route for its type and value `rule:CPR-56` `rule:CPR-57` `rule:CPR-58` `rule:CPR-59`, that above the Threshold the Invitation to Tender was issued and the tenders received electronically through the Procurement Portal `rule:CPR-13`, that a written procurement report exists where required `rule:CPR-27`, and that the award was recorded as a Key Decision by the authorised decision-maker `rule:CPR-04` `rule:CPR-49` `rule:CPR-50`. The indicator is confirmed where one requirement above the full-tender level was not tendered or the award was not recorded as a Key Decision `rule:CPR-12`.

- **Population:** `outputs/analytics-full/split_purchases.csv`, general_procurement rows where threshold = 500000: 2 (`metric:$.tests.split_purchases.by_threshold[threshold=500000].by_tag.general_procurement.count`).
- **Selection:** sorted by best_window_total descending; size every item, at the planner's request (score 8 gives 15).
- **Drawn:** 2 items, 59 transactions from best_window_ids, £3,510,454.59: `outputs/samples/T-02.csv`.
- **Size reason:** The auditor's gate comment on R-02 asks for every group in this tier to be examined.
- **Needs:** PBC-01, PBC-02, PBC-03, PBC-06, PBC-08

## R-05 Spend at or above the publication threshold with no published notice found

Score 9: likelihood 3 Likely x impact 3 Medium, band Medium High (Amber). Likelihood is an auditor override; the rubric gives 4 Almost Certain. Auditor's decision: Amend. Comment: Lower likelihood from 4 to 3: the count is inflated by the export only holding notices since 2021 and by framework call-offs that have no notice of their own.

**Expected controls**

- **C-05** A contract notice is published for every contract from the publication level `rule:CPR-53` `rule:CPR-55`; where a contract is let through a purchasing scheme without further competition, the scheme's use is confirmed and approved in advance `rule:CPR-26` `rule:CPR-62`.
- **C-06** Every award is notified to the Service Lead for Commissioning and Procurement `rule:CPR-33` and recorded in the published contracts register with its value and duration `rule:CPR-07`.

**Tests**

### T-03 (tests C-05, C-06)

For each sampled supplier with no published notice found, obtain the contract or order covering the sampled payments and check it against the contracts register `rule:CPR-07` `rule:CPR-33`. Establish whether a contract notice was published under another buyer name or before the export period `rule:CPR-53` `rule:CPR-55`, whether the payments are call-offs under a framework or other purchasing scheme with the advance approval the Rules require `rule:CPR-26` `rule:CPR-62`, or whether a waiver or exception covers them (cross-matched to the waiver and exception log with T-07) `rule:CPR-20`. Where the contract is a health care service let under the Provider Selection Regime, confirm that the key decisions are recorded and the relevant PSR process was followed `rule:CPR-61`. The indicator is cleared by any of these; it is confirmed where a contract at or above the publication level has no notice, no scheme and no approved waiver `metric:$.tests.no_published_notice.by_tag.general_procurement.count`.

- **Population:** `outputs/analytics-full/no_published_notice.csv`, general_procurement rows where class_active = no published notice found: 165 (`metric:$.tests.no_published_notice.by_tag.general_procurement.count`).
- **Selection:** sorted by total descending; size 15 items for score 9.
- **Drawn:** 15 items, 36 transactions from transaction_ids, at most 3 per item (largest first), £13,949,334.20: `outputs/samples/T-03.csv`.
- **Needs:** PBC-01, PBC-03, PBC-04, PBC-05, PBC-08, PBC-11

## R-06 Spend continuing after the matching notice ended, without an approved extension

Score 9: likelihood 3 Likely x impact 3 Medium, band Medium High (Amber). Auditor's decision: Approve.

**Expected controls**

- **C-07** A contract is extended only as provided for in the contract and with the approval of the statutory finance officer before the original term ends `rule:CPR-63`, and with the approval of the relevant board where the Rules' closing provision on exemptions applies to a contract above the Threshold `rule:CPR-67`.

**Tests**

### T-04 (tests C-07)

For each sampled supplier paid after every matching notice had ended, obtain the contract under which the sampled payments were made and the contracts register entry `rule:CPR-07`. Establish whether a newer contract exists, or whether the original contract was extended under its own terms with the statutory finance officer's approval dated before the term ended `rule:CPR-63`. Where the contract's annual or total value is above the Threshold, also establish whether the relevant board approved it `rule:CPR-67`; whether that closing provision applies to extensions is for the auditor to decide, so record the board approval found or its absence. The indicator is cleared by a current contract or an approved extension; it is confirmed where payments continued after expiry with neither `metric:$.tests.expired_notice_spend.by_tag.general_procurement.count`.

- **Population:** `outputs/analytics-full/expired_notice_spend.csv`, all general_procurement rows: 5 (`metric:$.tests.expired_notice_spend.by_tag.general_procurement.count`).
- **Selection:** sorted by total descending; size 15 items for score 9; the population is smaller, so all 5 are taken.
- **Drawn:** 5 items, 12 transactions from transaction_ids, £121,644.98: `outputs/samples/T-04.csv`.
- **Needs:** PBC-01, PBC-03, PBC-06, PBC-09

## R-07 Spend beyond the awarded contract value without an approved variation

Score 9: likelihood 3 Likely x impact 3 Medium, band Medium High (Amber). Auditor's decision: Approve.

**Expected controls**

- **C-08** A variation of scope or value is made only as provided for in the contract or permitted by the Procurement Legislation, with the prior written approval of the Monitoring Officer and the statutory finance officer `rule:CPR-64` and, above the Threshold, the approval of the relevant board `rule:CPR-65`.

**Tests**

### T-05 (tests C-08)

For each sampled supplier whose annualised spend is at or above the award ratio, obtain the contract, the basis of the awarded value (estimate, maximum or fixed price) and any variation or uplift `metric:$.tests.spend_vs_award.by_tag.general_procurement.count`. Confirm that any variation had the prior written approval of the Monitoring Officer and the statutory finance officer `rule:CPR-64`, and board approval where its value is above the Threshold `rule:CPR-65`. The indicator is cleared where the award value is an estimate the contract permits exceeding, the spend falls within the contract's total value over its term, or an approved variation covers it; it is confirmed where spend exceeds the award with no approved variation.

- **Population:** `outputs/analytics-full/spend_vs_award.csv`, general_procurement rows where flag = True: 7 (`metric:$.tests.spend_vs_award.by_tag.general_procurement.count`).
- **Selection:** sorted by ratio descending; size 15 items for score 9; the population is smaller, so all 7 are taken.
- **Drawn:** 7 items, 31 transactions from transaction_ids, £643,153.28: `outputs/samples/T-05.csv`.
- **Needs:** PBC-01, PBC-03, PBC-06, PBC-10

## R-08 Possible duplicate payments to the same supplier

Score 8: likelihood 4 Almost Certain x impact 2 Minor, band Medium High (Amber). Auditor's decision: Approve. Comment: Match the sampled payments to invoices.

**Expected controls**

- **C-09** Every payment rests on written evidence of a purchase, so that a second payment for the same purchase is not made `rule:CPR-30`.

**Tests**

### T-06 (tests C-09)

For each sampled group of same-supplier, same-amount payments, match every payment to its own invoice and purchase order, as the auditor asked `rule:CPR-30` `metric:$.tests.duplicates.by_tag.general_procurement.count`. The indicator is cleared where each payment matches a separate invoice for a separate supply (for example a regular fixed fee); it is confirmed where two payments rest on the same invoice or purchase, in which case obtain evidence that the repeated payment was identified and recovered.

- **Population:** `outputs/analytics-full/duplicates.csv`, all general_procurement rows: 50 (`metric:$.tests.duplicates.by_tag.general_procurement.count`).
- **Selection:** sorted by repeat_value descending; size 15 items for score 8.
- **Drawn:** 15 items, 35 transactions from transaction_ids, £542,579.56: `outputs/samples/T-06.csv`.
- **Needs:** PBC-01, PBC-12

## R-09 Waivers or exceptions to the Rules not approved in advance or not documented

Score 6: likelihood 2 Unlikely x impact 3 Medium, band Moderate. Auditor's decision: Approve. Comment: The Rules disagree on who may grant a waiver; test alongside R-05.

**Expected controls**

- **C-10** A waiver of or exception to the Rules is sought in advance and granted only by the officers the Rules name `rule:CPR-20`, on the grounds allowed for contracts above the waiver level `rule:CPR-19`, with the approval the value band requires `rule:CPR-21` `rule:CPR-22` `rule:CPR-23`, and an exemption is given the prior approval the Rules require `rule:CPR-60` `rule:CPR-67`.
- **C-11** Each waiver or exception is fully documented in a written exception report giving the reasons, and the statutory finance officer records that the reasons were considered `rule:CPR-24` `rule:CPR-25`.

**Tests**

### T-07 (tests C-10, C-11)

Obtain the waiver and exception log for the spend window and cross-match it to the suppliers with no published notice found, alongside T-03 as the auditor asked `metric:$.tests.no_published_notice.by_tag.general_procurement.count`. Test every log entry the cross-match finds, then the log entries for contracts above the waiver level `rule:CPR-19`, largest value first. For each entry tested, confirm that approval was sought and given in advance by the officers named `rule:CPR-20`, that the grounds fall within those allowed `rule:CPR-19`, that the approval matches the value band `rule:CPR-21` `rule:CPR-22` `rule:CPR-23` `rule:CPR-60` `rule:CPR-67`, and that a written exception report exists with the statutory finance officer's record of consideration `rule:CPR-24` `rule:CPR-25`. Record which officer approved each waiver, since the Rules differ on who may grant one `rule:CPR-19` `rule:CPR-20`; the auditor decides how that difference is read.

- **No sample:** Waivers and exceptions are not in the published spend data; the items are taken from the council's waiver and exception log once supplied, and from the cross-match to the suppliers with no published notice found.
- **Needs:** PBC-05, PBC-13

## R-10 Contract awards not made by the authorised decision-maker or not recorded as a Key Decision

Score 6: likelihood 2 Unlikely x impact 3 Medium, band Moderate. Auditor's decision: Approve. Comment: Sample the largest suppliers' award decisions.

**Expected controls**

- **C-12** Every contract rests on a recorded decision of the Council, the Executive or an officer with delegated authority `rule:CPR-02`, within an existing budgetary provision `rule:CPR-03`, taken by the decision-maker the Rules name for its total contract value `rule:CPR-47` `rule:CPR-48` `rule:CPR-49` `rule:CPR-50`.
- **C-13** An award above the Key Decision level is treated, recorded and published as a Key Decision `rule:CPR-04` `rule:CPR-49`.

**Tests**

### T-08 (tests C-12, C-13)

For each of the largest sampled suppliers, as the auditor asked, identify from the sampled payments the contract under which they were made and obtain its award decision record `metric:$.tests.high_value_suppliers.by_tag.general_procurement.count`. Confirm that the decision is recorded `rule:CPR-02`, that budgetary provision existed `rule:CPR-03`, that the decision-maker matches the approval band for the total contract value `rule:CPR-47` `rule:CPR-48` `rule:CPR-49` `rule:CPR-50`, and that an award above the Key Decision level was recorded and published as a Key Decision `rule:CPR-04`. The indicator is cleared where the record shows the authorised decision-maker; it is confirmed where the record is missing or was made outside the band's authority.

- **Population:** `outputs/analytics-full/high_value_suppliers.csv`, all general_procurement rows: 205 (`metric:$.tests.high_value_suppliers.by_tag.general_procurement.count`).
- **Selection:** sorted by total descending; size 10 items for score 6.
- **Drawn:** 10 items, 28 transactions from transaction_ids, at most 3 per item (largest first), £13,639,190.99: `outputs/samples/T-08.csv`.
- **Needs:** PBC-01, PBC-03, PBC-04, PBC-06, PBC-08

## PBC list

Documents and records to request from the council before fieldwork.

| PBC | Request | Needed for |
| --- | --- | --- |
| PBC-01 | Purchase orders, requisitions and invoices for every sampled payment `rule:CPR-30`. | T-01, T-02, T-03, T-04, T-05, T-06, T-08 |
| PBC-02 | Procurement Portal records for the sampled groups: quote invitations and responses, tender records, advertisements and contract notices, and the procedure record `rule:CPR-52` `rule:CPR-56` `rule:CPR-29`. | T-01, T-02 |
| PBC-03 | The council's contracts register for the spend window, with value, duration and supplier for each contract `rule:CPR-07`. | T-01, T-02, T-03, T-04, T-05, T-08 |
| PBC-04 | Contract evidence (contract, order or framework call-off, and any notice) for the high value suppliers population `metric:$.tests.high_value_suppliers.by_tag.general_procurement.count`. Population: the 205 general_procurement suppliers in `outputs/analytics-full/high_value_suppliers.csv`. Request first for the 165 marked no published notice found, largest total first, then for the rest, largest total first. | T-03, T-08 |
| PBC-05 | The waiver and exception log for the spend window, with the approval and exception report for each entry `rule:CPR-20` `rule:CPR-24`. | T-03, T-07 |
| PBC-06 | The Threshold values the Rules name but do not state, as the council applied them in the spend window `rule:CPR-52`. Named in the Rules with no value stated: Threshold (goods_services, works, concession, light_touch), defined in clause 1.4 p1 and clause AppB-fn3 p13, bounding CPR-01, CPR-10, CPR-13, CPR-21, CPR-22, CPR-27, CPR-45, CPR-47, CPR-48, CPR-52, CPR-53, CPR-56, CPR-57, CPR-58, CPR-59, CPR-64, CPR-65, CPR-67. | T-02, T-04, T-05, T-08 |
| PBC-07 | The appendices of the Internal Audit Plan that are missing from the published paper `history:GAP-05`. | planning (standing request) |
| PBC-08 | Award decision records for the sampled contracts: officer delegated decisions, board reports and recommendations, Key Decision records and written procurement reports, and for contracts under the Provider Selection Regime the record of key decisions `rule:CPR-02` `rule:CPR-04` `rule:CPR-47` `rule:CPR-27` `rule:CPR-61`. | T-01, T-02, T-03, T-08 |
| PBC-09 | For each sampled supplier paid after its matching notice ended, the current contract or the extension provision, the statutory finance officer's extension approval, and any board approval for a contract above the Threshold `rule:CPR-63` `rule:CPR-67`. | T-04 |
| PBC-10 | For each sampled supplier above the award ratio, the basis of the awarded value and every variation with its approvals `rule:CPR-64` `rule:CPR-65`. | T-05 |
| PBC-11 | Records of purchasing scheme use for the sampled suppliers: the scheme, the advice confirming the council may use it, and any approval for a call-off without further competition `rule:CPR-26` `rule:CPR-62`. | T-01, T-03 |
| PBC-12 | For any sampled payment matched to an invoice already paid, the accounts payable record of its identification and recovery `rule:CPR-30`. | T-06 |
| PBC-13 | Exemption approvals for contracts let without competition under the exclusions or exemptions of the Rules, with the board approval where the value requires it `rule:CPR-60` `rule:CPR-67`. | T-07 |
