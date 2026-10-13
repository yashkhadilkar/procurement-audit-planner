# Procurement risk register (revision r0)

Built 2026-10-13T20:22:52+00:00 by `.claude/skills/risk-assessment/build_register.py` from `outputs/risk-ratings.json`. Draft for the auditor's decision at the gate.

> These are **risk indicators to investigate**, drawn from published data. They are not findings and do not suggest wrongdoing by the council, any service or any supplier.

## How this register was built

**Inputs**

| File | sha256 |
| --- | --- |
| `risk-ratings.json` | `479ec5ac8a1a4461199c68f83599a4e3dc2013f0ad3ad44d915d5ac47f78ecc6` |
| `analytics.json` | `9c21ddd22edba5a620cbb50287fcb3b6c7c3a9241d721bdb43f247cd55696d76` |
| `history.json` | `9137d23214792dd7da1259d647017d4806221a6869e2c66fd3b573922fc51dcf` |
| `rules.json` | `2faecd244736c3f25b51019bdd6e83f506495f23010f878614bbff958c6d45f1` |

**Scoring method:** the council's own, from the Risk Management Strategy 2024-27 as recorded in `outputs/history.json`: score = likelihood x impact on the 5x5 matrix; Matrix label from Figure 1; Band from Table 4.

- likelihood scale: 4.4, Table 2. Likelihood Ratings (data/committee/risk-management-strategy-2024-27.pdf p15)
- impact scale: 4.3, Table 1. Impact Ratings (data/committee/risk-management-strategy-2024-27.pdf p14)
- matrix: 5.11, Figure 1. 5x5 Risk Matrix Assessments (data/committee/risk-management-strategy-2024-27.pdf p18)
- bands: 5.13, Table 4. RAG Levels, Risk Scores, Escalation and Responses (data/committee/risk-management-strategy-2024-27.pdf p19)

**Conflicting thresholds in the scoring method.** Each is resolved one way here, and the other reading is marked:

- **Used:** Table 4: a risk goes to the Corporate Risk Register in band Extreme (score 15 -25), the table the Band column comes from. **Marked:** Figure 4: Corporate Risk Register "Score 9 or above". Risks scoring 9 to 14 are marked ‡ in the register. (history: DIS-04)
- **Used:** Band column: Table 4 name "Medium High". **Marked:** Matrix label column keeps Figure 1's "High" for scores 8, 9, 10, 12; Table 4 has no band named "High". (history: DIS-03)
- **Used:** Medium = 3, as numbered in Table 1 and Figure 1. **Marked:** "Medium (2)" printed in 4.3 (p14). (history: DIS-01)
- **Used:** the £ figures printed in the same Table 1 cells (listed under Impact below); where two £ ranges share an end point the higher level takes it, unless that level is printed with '>'. **Marked:** the percentage ranges for Medium (0.1% - 0.3% annual WBC budget £175k -500k) and Major (0.25% - 1% annual WBC budget £500k £2M) overlap. (history: DIS-02)

**Other scoring-method discrepancies in history.json**, not used in any computation here:

- DIS-05: 6.3 says that where risk levels are extrene (Red) the Service Director escalates to the Executive Director so that consideration can be given to whether the risk should be moved to the Directorate Risk Register or the Corporate Risk Register; Table 4 prints "Add to Corporate Risk Register and mitigation action." for Extreme (Red).
- DIS-06: 5.10 heads the reputation statement "Reputation Risk appetite – Open" and the same paragraph says employees and Councillors aim "to ensure there is little chance of significant repercussions" and that the Council is "seeking an open reputational risk"; Table 3 prints "Little chance of significant repercussions and mitigation in place beforehand" in the Cautious column of the Reputation row and "Experimental– possible significant reputational damage or enhancement" in the Open column.
- DIS-07: 6.4 assigns to the Operations Board "Determine overall risk appetite and tolerance for the Council and for each corporate risk."; 5.10 says "This Strategy reflects the Executive’s risk appetite", and the covering report (4.1) describes "A new risk appetite to articulate the levels of risks accepted by the Executive".
- DIS-12: 7.1 says "The methodology for the scoring of risks is included in section 5 above."; Table 1 (Impact Ratings) and Table 2 (Likelihood Ratings) are printed under section 4 "How do we evaluate risks?", and Figure 1 and Table 4 under section 5.
- DIS-14: 4.1 names the evaluation levels Gross level, Actual level and Expected level; Appendix 2 defines Gross risk rating, Current risk rating and Expected Net risk rating, with matching wording for Actual/Current and Expected/Expected Net.
- DIS-15: Figure 4 names the six-monthly reviewer of the Corporate Risk Register as the "Governance and Ethics Committee"; 6.4 and Appendix 1 4.3 name the "Governance Committee".
- DIS-16: 5.2 and 5.9 cite "Government Finance Function – Risk Appetite Guidance v.2., August2021"; Appendix 2 cites "Government Finance Function – Risk Appetite Guidance note V1.0, October 2020" for the same risk appetite and risk tolerance definitions.
- DIS-20: 3.10 says previous service risk registers "have been amalgamated into Department Risk registers"; 6.3, Figure 4 and 7.2 name the "Directorate Risk Register" / "Directorate Risk Registers".

**Evidence basis.**

- Likelihood and impact rest on the `general_procurement` figures in analytics.json. Placement, grant, agency staff and premises figures, and figures for all tags combined, are cited as context only: placements recur by design.
- The split_purchases tier at £1,000 cannot raise a rating on its own. Every published payment exceeds the £500 publication floor, so any two published payments under £1,000 already add up to more than £1,000: the tier flags by construction. Its figures, and split_purchases totals that include it, are context only.
- Repeat finding: a cited audit with an adverse opinion (Limited Assurance or worse) on the same theme raises likelihood by 1, stated in the risk. The papers do not define the opinion scale (history: GAP-02); Weak is read as worse than Limited Assurance.
- Every likelihood and impact justification cites at least one rule, history item or `general_procurement` metric that resolves. A risk without one, or with any citation or figure that does not resolve, is excluded and listed below.

**Likelihood rubric.** The signal is the `general_procurement` count of the one test or threshold tier the risk rests on; the builder computes the row from it.

| Row | Evidence | Base likelihood |
| --- | --- | --- |
| NT | No analytics test measures the risk, or its test or tier did not run | 2 Unlikely |
| S0 | Signal count is 0 | 1 Rare |
| S1 | Signal count 1 to 4; or a threshold_clustering tier whose below-band count does not exceed its comparison band | 2 Unlikely |
| S2 | Signal count 5 to 19 | 3 Likely |
| S3 | Signal count 20 or more | 4 Almost Certain |

Likelihood = base + 1 for a repeat finding, at most 5. 5 Certain is reached only through that uplift.

**Impact** is chosen from Table 1: each risk names the column it is judged on.

- Financial loss to Council, as printed: 1 Negligible: Less than 0.01% annual WBC budget £17.5k; 2 Minor: 0.01% 0.1% of annual WBC budget £17.5k £175k; 3 Medium: 0.1% - 0.3% annual WBC budget £175k -500k; 4 Major: 0.25% - 1% annual WBC budget £500k £2M; 5 Critical: > 1% annual WBC budget >£2m

## Risk summary

| Risk | Title | Likelihood | Impact | Score | Matrix label | Band |
| --- | --- | --- | --- | --- | --- | --- |
| R-01 | Purchases split to stay under the quote and contract-notice threshold | 4 Almost Certain | 3 Medium | 12 ‡ | High | Medium High (Amber) |
| R-02 | Purchases split to stay under the full-tender and Key Decision level | 2 Unlikely | 4 Major | 8 | High | Medium High (Amber) |
| R-03 | Payment values held just under the quote and contract-notice threshold | 2 Unlikely | 3 Medium | 6 | Moderate | Moderate |
| R-04 | Payment values held just under the single-quote threshold | 4 Almost Certain | 1 Negligible | 4 | Moderate | Moderate |
| R-05 | Spend at or above the publication threshold with no published notice found | 4 Almost Certain | 3 Medium | 12 ‡ | High | Medium High (Amber) |
| R-06 | Spend continuing after the matching notice ended, without an approved extension | 3 Likely | 3 Medium | 9 ‡ | High | Medium High (Amber) |
| R-07 | Spend beyond the awarded contract value without an approved variation | 3 Likely | 3 Medium | 9 ‡ | High | Medium High (Amber) |
| R-08 | Possible duplicate payments to the same supplier | 4 Almost Certain | 2 Minor | 8 | High | Medium High (Amber) |
| R-09 | Waivers or exceptions to the Rules not approved in advance or not documented | 2 Unlikely | 3 Medium | 6 | Moderate | Moderate |
| R-10 | Contract awards not made by the authorised decision-maker or not recorded as a Key Decision | 2 Unlikely | 3 Medium | 6 | Moderate | Moderate |

‡ Score 9 to 14: Figure 4 would place this risk on the Corporate Risk Register; Table 4, which is used here, does not. See the conflicting thresholds above.

## Risks

### R-01 Purchases split to stay under the quote and contract-notice threshold

Two or more payments to one supplier within 30 days that together reach £25,000, while each payment stays below it, may indicate a requirement disaggregated so that the three-quote and contract-notice rules are not applied `rule:CPR-12` `rule:CPR-52` `rule:CPR-53`. This is a risk indicator to investigate: recurring orders under a call-off or framework produce the same pattern.

- **Likelihood: 4 Almost Certain.** Rubric row S3 (signal $.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count = 46), base 4 Almost Certain. 46 general procurement supplier groups in the spend window reach £25,000 in combination `metric:$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count`; at that value quotes from at least three sources and a published contract notice are required `rule:CPR-52` `rule:CPR-53`, and splitting to avoid the Rules is prohibited `rule:CPR-12`.
- **Impact: 3 Medium.** Table 1, Compliance (litigation, regulatory, contract): "Reasonable possibility of successful legal challenge. Reasonable possibility of regulatory interest." If a requirement was split, the competition and notice rules for the band from £25,000 to the Threshold were not applied `rule:CPR-52` `rule:CPR-53` `rule:CPR-12`; the general procurement groups total £3,217,547.48 over the window `metric:$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.total`, giving a reasonable possibility of challenge or regulatory interest in the sub-Threshold band.
- **Score:** 12 ‡; matrix label High; band Medium High (Amber): Allocate to Service Director to put in place Controls Assurance.
- **Evidence:** Split tier at £25,000: 46 general procurement groups, £3,217,547.48 `metric:$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count`. The tier at the Threshold itself was not run: parameter not supplied, because rules.json does not hold the Threshold value. The lowest split tier flags by construction and is not used `rule:CPR-51`.
- **Proposed focus:** Sample the general procurement groups in the split_purchases full list for the £25,000 tier; for each, obtain the order and quote records and establish whether the payments relate to one requirement and, if so, whether three quotes were invited and a notice published.
- **Sources:**
  - rule CPR-12: clause 6.16, page 5, anti-avoidance
  - rule CPR-52: clause AppB-B1, page 12, threshold
  - rule CPR-53: clause AppB-B1, page 12, threshold
  - metric $.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count = 46 (primary: general_procurement)
  - metric $.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.total = 3,217,547.48 (primary: general_procurement)
  - rule CPR-51: clause AppB-A, page 12, threshold

### R-02 Purchases split to stay under the full-tender and Key Decision level

Payments to one supplier within 30 days that together reach £500,000, while each stays below it, may indicate a requirement disaggregated so that a full competitive tender and Key Decision were not applied `rule:CPR-12` `rule:CPR-56` `rule:CPR-04`. Risk indicator to investigate.

- **Likelihood: 2 Unlikely.** Rubric row S1 (signal $.tests.split_purchases.by_threshold[threshold=500000].by_tag.general_procurement.count = 2), base 2 Unlikely. 2 general procurement supplier groups reach £500,000 in combination `metric:$.tests.split_purchases.by_threshold[threshold=500000].by_tag.general_procurement.count`; above that value a full tender is required for works, concession and light touch contracts `rule:CPR-56` and the award is a Key Decision `rule:CPR-04`.
- **Impact: 4 Major.** Table 1, Compliance (litigation, regulatory, contract): "High possibility of legal challenge. High possibility of regulatory intervention." At this value a split requirement would bypass a full competitive tender `rule:CPR-56`, and for goods and services the Procurement Legislation procedures above the Threshold `rule:CPR-58`, as well as the Key Decision `rule:CPR-04`; the general procurement groups total £6,046,162.94 `metric:$.tests.split_purchases.by_threshold[threshold=500000].by_tag.general_procurement.total`, giving a high possibility of legal challenge if the rules were not applied.
- **Score:** 8; matrix label High; band Medium High (Amber): Allocate to Service Director to put in place Controls Assurance.
- **Evidence:** Split tier at £500,000: 2 general procurement groups, £6,046,162.94 `metric:$.tests.split_purchases.by_threshold[threshold=500000].by_tag.general_procurement.total`. The council's contract type for each group is not in the spend data, so whether `rule:CPR-56` or `rule:CPR-58` applies is for the auditor to establish.
- **Proposed focus:** Examine every general procurement group in the £500,000 tier: obtain the contract, the tender record and the Key Decision record, and establish whether the payments are instalments under one competed contract.
- **Sources:**
  - rule CPR-12: clause 6.16, page 5, anti-avoidance
  - rule CPR-56: clause AppB-C, page 12, threshold
  - rule CPR-04: clause 4.3, page 3, threshold
  - metric $.tests.split_purchases.by_threshold[threshold=500000].by_tag.general_procurement.count = 2 (primary: general_procurement)
  - rule CPR-58: clause AppB-D, page 12, threshold
  - metric $.tests.split_purchases.by_threshold[threshold=500000].by_tag.general_procurement.total = 6,046,162.94 (primary: general_procurement)

### R-03 Payment values held just under the quote and contract-notice threshold

A concentration of single payments just below £25,000 may indicate values set to stay under the three-quote and contract-notice rules `rule:CPR-52` `rule:CPR-53`. These are payment values, not contract values; risk indicator to investigate.

- **Likelihood: 2 Unlikely.** Rubric row S1 (signal $.tests.threshold_clustering.by_threshold[threshold=25000].below.by_tag.general_procurement.count = 10; comparison band = 15, no excess (capped at S1)), base 2 Unlikely. 10 general procurement payments fall in the band just below £25,000 `metric:$.tests.threshold_clustering.by_threshold[threshold=25000].below.by_tag.general_procurement.count` and 15 in the comparison band just above it `metric:$.tests.threshold_clustering.by_threshold[threshold=25000].comparison.by_tag.general_procurement.count`; the rubric row is set from these two counts. The threshold is set by `rule:CPR-52`.
- **Impact: 3 Medium.** Table 1, Compliance (litigation, regulatory, contract): "Reasonable possibility of successful legal challenge. Reasonable possibility of regulatory interest." A value held below £25,000 to avoid three quotes and a published notice would mean the sub-Threshold competition rules were not applied `rule:CPR-52` `rule:CPR-53`; the band holds £238,120.44 of general procurement payments `metric:$.tests.threshold_clustering.by_threshold[threshold=25000].below.by_tag.general_procurement.total`, a reasonable possibility of challenge or regulatory interest.
- **Score:** 6; matrix label Moderate; band Moderate: Monitor risk
- **Evidence:** Clustering tier at £25,000: band below 10 payments, £238,120.44; comparison band 15 payments `metric:$.tests.threshold_clustering.by_threshold[threshold=25000].comparison.by_tag.general_procurement.total`. The tier at £500,000 found 0 general procurement payments below it `metric:$.tests.threshold_clustering.by_threshold[threshold=500000].below.by_tag.general_procurement.count`.
- **Proposed focus:** Sample general procurement payments from the band just below £25,000 in the threshold_clustering full list and check the order value against the quote and notice records.
- **Sources:**
  - rule CPR-52: clause AppB-B1, page 12, threshold
  - rule CPR-53: clause AppB-B1, page 12, threshold
  - metric $.tests.threshold_clustering.by_threshold[threshold=25000].below.by_tag.general_procurement.count = 10 (primary: general_procurement)
  - metric $.tests.threshold_clustering.by_threshold[threshold=25000].comparison.by_tag.general_procurement.count = 15 (primary: general_procurement)
  - metric $.tests.threshold_clustering.by_threshold[threshold=25000].below.by_tag.general_procurement.total = 238,120.44 (primary: general_procurement)
  - metric $.tests.threshold_clustering.by_threshold[threshold=25000].comparison.by_tag.general_procurement.total = 396,487.45 (primary: general_procurement)
  - metric $.tests.threshold_clustering.by_threshold[threshold=500000].below.by_tag.general_procurement.count = 0 (primary: general_procurement)

### R-04 Payment values held just under the single-quote threshold

A concentration of single payments just below £1,000 may indicate values set to stay under the requirement to seek at least one quote `rule:CPR-51`. These are payment values, not contract values; risk indicator to investigate.

- **Likelihood: 4 Almost Certain.** Rubric row S3 (signal $.tests.threshold_clustering.by_threshold[threshold=1000].below.by_tag.general_procurement.count = 57; comparison band = 40), base 4 Almost Certain. 57 general procurement payments fall in the band just below £1,000 `metric:$.tests.threshold_clustering.by_threshold[threshold=1000].below.by_tag.general_procurement.count` and 40 in the comparison band just above it `metric:$.tests.threshold_clustering.by_threshold[threshold=1000].comparison.by_tag.general_procurement.count`; the rubric row is set from these two counts. The threshold is set by `rule:CPR-51`.
- **Impact: 1 Negligible.** Table 1, Compliance (litigation, regulatory, contract): "Negligible possibility of legal challenge or regulatory interest" The rule at this level asks for one quote and mandates no advertising `rule:CPR-51`, and the band holds £54,809.89 of general procurement payments `metric:$.tests.threshold_clustering.by_threshold[threshold=1000].below.by_tag.general_procurement.total`: a negligible possibility of legal challenge or regulatory interest.
- **Score:** 4; matrix label Moderate; band Moderate: Monitor risk
- **Evidence:** Clustering tier at £1,000: band below 57 payments, £54,809.89; comparison band 40 payments, £42,114.81 `metric:$.tests.threshold_clustering.by_threshold[threshold=1000].comparison.by_tag.general_procurement.total`. Published spend starts just above £500 `rule:CPR-05`, and rules.json notes that no requirement is stated at or below the lower bound of `rule:CPR-51`.
- **Proposed focus:** A small sample of general procurement payments from the band just below £1,000, checked for a quote record and for repeat orders to the same supplier.
- **Sources:**
  - rule CPR-51: clause AppB-A, page 12, threshold
  - metric $.tests.threshold_clustering.by_threshold[threshold=1000].below.by_tag.general_procurement.count = 57 (primary: general_procurement)
  - metric $.tests.threshold_clustering.by_threshold[threshold=1000].comparison.by_tag.general_procurement.count = 40 (primary: general_procurement)
  - metric $.tests.threshold_clustering.by_threshold[threshold=1000].below.by_tag.general_procurement.total = 54,809.89 (primary: general_procurement)
  - metric $.tests.threshold_clustering.by_threshold[threshold=1000].comparison.by_tag.general_procurement.total = 42,114.81 (primary: general_procurement)
  - rule CPR-05: clause 5.1, page 3, threshold

### R-05 Spend at or above the publication threshold with no published notice found

Suppliers whose annualised estimate (3-month total times 4) is at or above £25,000 with no exact match among active Contracts Finder notices may indicate contracts let without the required contract notice `rule:CPR-53` `rule:CPR-55`. The result is a list of suppliers to request contract evidence for, not a finding: frameworks, older contracts or notices under another buyer name may cover them.

- **Likelihood: 4 Almost Certain.** Rubric row S3 (signal $.tests.no_published_notice.by_tag.general_procurement.count = 165), base 4 Almost Certain. 165 general procurement suppliers at or above £25,000 annualised have no published notice found `metric:$.tests.no_published_notice.by_tag.general_procurement.count`; a contract notice is required from that value `rule:CPR-53` `rule:CPR-55`.
- **Impact: 3 Medium.** Table 1, Compliance (litigation, regulatory, contract): "Reasonable possibility of successful legal challenge. Reasonable possibility of regulatory interest." Where no notice was published the publication rule was not applied `rule:CPR-53` and the contracts register may be incomplete `rule:CPR-07`; the general procurement suppliers concerned account for £22,996,068.03 over the window `metric:$.tests.no_published_notice.by_tag.general_procurement.total`, a reasonable possibility of regulatory interest.
- **Score:** 12 ‡; matrix label High; band Medium High (Amber): Allocate to Service Director to put in place Controls Assurance.
- **Evidence:** no_published_notice: 165 general procurement suppliers, £22,996,068.03 `metric:$.tests.no_published_notice.by_tag.general_procurement.total`. The high_value_suppliers population is 205 general procurement suppliers, £25,532,234.94 `metric:$.tests.high_value_suppliers.by_tag.general_procurement.count`. The council's contracts register is not an input. The most recent Contract Letting audit gave Reasonable Assurance `history:AUD-01`, so no repeat-finding uplift applies.
- **Proposed focus:** Request the contracts register and contract evidence for the high_value_suppliers population, starting with general procurement suppliers marked no published notice found, and check each for a notice, a framework call-off or an approved waiver.
- **Sources:**
  - rule CPR-53: clause AppB-B1, page 12, threshold
  - rule CPR-55: clause AppB-B2, page 12, threshold
  - metric $.tests.no_published_notice.by_tag.general_procurement.count = 165 (primary: general_procurement)
  - rule CPR-07: clause 5.2.1, page 3, required-action
  - metric $.tests.no_published_notice.by_tag.general_procurement.total = 22,996,068.03 (primary: general_procurement)
  - metric $.tests.high_value_suppliers.by_tag.general_procurement.count = 205 (primary: general_procurement)
  - history AUD-01: Contract Letting (Reasonable Assurance), data/committee/audit-completed-work-2024-25-annual.pdf p1

### R-06 Spend continuing after the matching notice ended, without an approved extension

Suppliers paid in the window (2026-05-01 to 2026-07-31) whose every exact-match notice ended before the window started may indicate spend after expiry without the extension approval the Rules require `rule:CPR-63`. A newer contract may exist with no notice; risk indicator to investigate.

- **Likelihood: 3 Likely.** Rubric row S2 (signal $.tests.expired_notice_spend.by_tag.general_procurement.count = 5), base 3 Likely. 5 general procurement suppliers were paid after every matching notice had ended `metric:$.tests.expired_notice_spend.by_tag.general_procurement.count`; an extension needs the approval of the statutory finance officer named in `rule:CPR-63`.
- **Impact: 3 Medium.** Table 1, Compliance (litigation, regulatory, contract): "Reasonable possibility of successful legal challenge. Reasonable possibility of regulatory interest." Spend after expiry without an approved extension would be a direct award outside the Rules `rule:CPR-63`; the general procurement spend concerned is £121,644.98 over the window `metric:$.tests.expired_notice_spend.by_tag.general_procurement.total`, a reasonable possibility of challenge or regulatory interest.
- **Score:** 9 ‡; matrix label High; band Medium High (Amber): Allocate to Service Director to put in place Controls Assurance.
- **Evidence:** expired_notice_spend: 5 general procurement suppliers, £121,644.98 `metric:$.tests.expired_notice_spend.by_tag.general_procurement.total`. A further 5 suppliers match a notice only as candidates and are listed separately, not treated as matches.
- **Proposed focus:** For each general procurement supplier in the expired_notice_spend list, obtain the current contract and any extension approval required by `rule:CPR-63`.
- **Sources:**
  - rule CPR-63: clause AppC-D, page 14, approval
  - metric $.tests.expired_notice_spend.by_tag.general_procurement.count = 5 (primary: general_procurement)
  - metric $.tests.expired_notice_spend.by_tag.general_procurement.total = 121,644.98 (primary: general_procurement)

### R-07 Spend beyond the awarded contract value without an approved variation

Suppliers whose annualised estimate is at or above 1.25 times the annual value of their single active notice may indicate spend beyond the award without the variation approval the Rules require `rule:CPR-64` `rule:CPR-65`. Award values may be estimates or maxima; risk indicator to investigate.

- **Likelihood: 3 Likely.** Rubric row S2 (signal $.tests.spend_vs_award.by_tag.general_procurement.count = 7), base 3 Likely. 7 general procurement suppliers are flagged at or above the award ratio `metric:$.tests.spend_vs_award.by_tag.general_procurement.count`; a variation needs prior written approval of the Monitoring Officer and the statutory finance officer below the Threshold `rule:CPR-64` and board approval above it `rule:CPR-65`.
- **Impact: 3 Medium.** Table 1, Compliance (litigation, regulatory, contract): "Reasonable possibility of successful legal challenge. Reasonable possibility of regulatory interest." A variation made without approval would modify a contract outside the Rules `rule:CPR-64`; the flagged general procurement spend is £643,153.28 over the window `metric:$.tests.spend_vs_award.by_tag.general_procurement.total`, a reasonable possibility of challenge or regulatory interest.
- **Score:** 9 ‡; matrix label High; band Medium High (Amber): Allocate to Service Director to put in place Controls Assurance.
- **Evidence:** spend_vs_award: 7 general procurement suppliers, £643,153.28 `metric:$.tests.spend_vs_award.by_tag.general_procurement.total`. Only suppliers with one active single-supplier notice with a positive award value are evaluated (20 suppliers, all tags).
- **Proposed focus:** For each flagged general procurement supplier, obtain the contract, its value basis and any variation approval.
- **Sources:**
  - rule CPR-64: clause AppC-E, page 14, approval
  - rule CPR-65: clause AppC-E, page 14, approval
  - metric $.tests.spend_vs_award.by_tag.general_procurement.count = 7 (primary: general_procurement)
  - metric $.tests.spend_vs_award.by_tag.general_procurement.total = 643,153.28 (primary: general_procurement)

### R-08 Possible duplicate payments to the same supplier

Payments to one supplier of the same amount within 7 days may indicate a payment made twice for one purchase, contrary to the requirement that every purchase is evidenced `rule:CPR-30`. Regular fixed-fee payments produce the same pattern; risk indicator to investigate.

- **Likelihood: 4 Almost Certain.** Rubric row S3 (signal $.tests.duplicates.by_tag.general_procurement.count = 50), base 4 Almost Certain. 50 general procurement groups of same-supplier, same-amount payments fall within 7 days `metric:$.tests.duplicates.by_tag.general_procurement.count`; each payment should rest on written evidence of a purchase `rule:CPR-30`.
- **Impact: 2 Minor.** Table 1, Financial loss to Council: "0.01% 0.1% of annual WBC budget £17.5k £175k" A confirmed duplicate is a loss of the repeated payment only; the general procurement group total of £634,682.11 includes the original payments `metric:$.tests.duplicates.by_tag.general_procurement.total`, and the repeat value per tag is not computed in analytics.json. The most recent Accounts Payable audit gave Reasonable Assurance `history:AUD-15`.
- **Score:** 8; matrix label High; band Medium High (Amber): Allocate to Service Director to put in place Controls Assurance.
- **Evidence:** duplicates: 50 general procurement groups, £634,682.11 `metric:$.tests.duplicates.by_tag.general_procurement.total`. Accounts Payable: Reasonable Assurance `history:AUD-15`. No rule in rules.json addresses duplicate payment directly; `rule:CPR-30` is the nearest.
- **Proposed focus:** Sample general procurement groups from the duplicates full list and match each payment to an invoice; confirm any duplicate was recovered.
- **Sources:**
  - rule CPR-30: clause 10.1, page 8, required-action
  - metric $.tests.duplicates.by_tag.general_procurement.count = 50 (primary: general_procurement)
  - metric $.tests.duplicates.by_tag.general_procurement.total = 634,682.11 (primary: general_procurement)
  - history AUD-15: Accounts Payable (Reasonable Assurance), data/committee/audit-completed-work-2025-26-q3.pdf p1

### R-09 Waivers or exceptions to the Rules not approved in advance or not documented

Contracts let under a waiver or exception may lack the prior approval of the Monitoring Officer or the statutory finance officer, or the written exception report, that the Rules require `rule:CPR-20` `rule:CPR-24` `rule:CPR-25`. Risk to test from the waiver records.

- **Likelihood: 2 Unlikely.** Rubric row NT (no signal), base 2 Unlikely. No spend test measures whether a waiver was approved in advance; the Rules require advance approval by the Monitoring Officer and/or the statutory finance officer `rule:CPR-20` and a written, documented exception report `rule:CPR-24`.
- **Impact: 3 Medium.** Table 1, Compliance (litigation, regulatory, contract): "Reasonable possibility of successful legal challenge. Reasonable possibility of regulatory interest." A waiver without the required approval would set aside competition for contracts above the waiver level `rule:CPR-19` without the safeguards of `rule:CPR-20` and `rule:CPR-25`, a reasonable possibility of challenge or regulatory interest.
- **Score:** 6; matrix label Moderate; band Moderate: Monitor risk
- **Evidence:** rules.json records a conflict on who may grant a waiver between `rule:CPR-19` and `rule:CPR-20`, and a gap between the waiver level of `rule:CPR-19` and the exception route of `rule:CPR-21`. Suppliers with no published notice found `metric:$.tests.no_published_notice.by_tag.general_procurement.count` are where waivers would be expected to appear.
- **Proposed focus:** Request the waiver and exception log for the window; for a sample of waivers, check advance approval and the exception report, and cross-match the log to the suppliers with no published notice found.
- **Sources:**
  - rule CPR-20: clause 7.3, page 6, approval
  - rule CPR-24: clause 7.5, page 6, required-action
  - rule CPR-25: clause 7.5.3, page 7, approval
  - rule CPR-19: clause 7.2, page 6, threshold
  - rule CPR-21: clause 7.4.1, page 6, approval
  - metric $.tests.no_published_notice.by_tag.general_procurement.count = 165 (primary: general_procurement)

### R-10 Contract awards not made by the authorised decision-maker or not recorded as a Key Decision

Awards may be made without the delegated authority, board report or Key Decision record that the Rules require for their value band `rule:CPR-02` `rule:CPR-04` `rule:CPR-47` `rule:CPR-48` `rule:CPR-49` `rule:CPR-50`. Risk to test from decision records.

- **Likelihood: 2 Unlikely.** Rubric row NT (no signal), base 2 Unlikely. No spend test measures award authority; every contract must rest on a recorded decision `rule:CPR-02`, and awards over the Key Decision level are Key Decisions `rule:CPR-04`.
- **Impact: 3 Medium.** Table 1, Compliance (litigation, regulatory, contract): "Reasonable possibility of successful legal challenge. Reasonable possibility of regulatory interest." An award without the required authority or Key Decision record would leave the contract open to challenge on the decision-maker's authority `rule:CPR-02` `rule:CPR-49`, a reasonable possibility of challenge or regulatory interest.
- **Score:** 6; matrix label Moderate; band Moderate: Monitor risk
- **Evidence:** The high_value_suppliers population of 205 general procurement suppliers `metric:$.tests.high_value_suppliers.by_tag.general_procurement.count` is where the larger awards sit. The approval bands depend on the Threshold, which rules.json does not hold `rule:CPR-47` `rule:CPR-48`.
- **Proposed focus:** For a sample of the largest general procurement suppliers, obtain the award decision record and check it against the approval band in Appendix A `rule:CPR-47` and the Key Decision requirement `rule:CPR-04`.
- **Sources:**
  - rule CPR-02: clause 4.1, page 2, approval
  - rule CPR-04: clause 4.3, page 3, threshold
  - rule CPR-47: clause AppA-1, page 11, approval
  - rule CPR-48: clause AppA-2, page 11, approval
  - rule CPR-49: clause AppA-3, page 11, approval
  - rule CPR-50: clause AppA-4, page 11, approval
  - metric $.tests.high_value_suppliers.by_tag.general_procurement.count = 205 (primary: general_procurement)

## Noted, not rated

Audits with a Limited (or worse) opinion on areas the spend tests exclude. They are not rated because no test measures them; they are not dropped either. The auditor decides at the gate.

| Item | Area | Opinion | Source | Why not rated |
| --- | --- | --- | --- | --- |
| AUD-16 | Personal Budgets (Direct Payments) (Children with Disabilities and SEN Teams) | Limited Assurance | data/committee/audit-completed-work-2025-26-q3.pdf p1 | Personal Budgets (Direct Payments) audit, Limited Assurance `history:AUD-16`. Payments with the Narrative Direct Payment are excluded before tagging as payments to individuals (475 rows in the exclusion log), so no spend test measures this area. |
| AUD-11 | Garland (now Burghfield Common Federation) (Schools) | Weak | data/committee/audit-completed-work-2024-25-annual.pdf p2 | Follow-up of a single school, Garland (now Burghfield Common Federation), opinion Weak, implementation progress Unsatisfactory `history:AUD-11`. The record does not state the areas the follow-up covered, and no spend test measures an individual school's controls. |
| AUD-12 | Westwood Farm (Schools) | Limited Assurance | data/committee/audit-completed-work-2024-25-annual.pdf p2 | Follow-up of a single school, Westwood Farm, opinion Limited Assurance, implementation progress Satisfactory `history:AUD-12`. The record does not state the areas the follow-up covered, and no spend test measures an individual school's controls. |

## Excluded: no resolvable citation

None.

## Build warnings

None.

## Auditor decisions

Record decisions in `outputs/auditor-comments.md`; this section is regenerated from it on every build.

| Item | Decision | Comment | Applied |
| --- | --- | --- | --- |
| R-01 | (undecided) |  |  |
| R-02 | (undecided) |  |  |
| R-03 | (undecided) |  |  |
| R-04 | (undecided) |  |  |
| R-05 | (undecided) |  |  |
| R-06 | (undecided) |  |  |
| R-07 | (undecided) |  |  |
| R-08 | (undecided) |  |  |
| R-09 | (undecided) |  |  |
| R-10 | (undecided) |  |  |
| AUD-16 | (undecided) |  |  |
| AUD-11 | (undecided) |  |  |
| AUD-12 | (undecided) |  |  |
