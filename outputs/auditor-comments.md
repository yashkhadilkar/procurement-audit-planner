# Auditor comments: risk register decisions

Register revision: r0  
Built: 2026-10-13T20:22:52+00:00 from outputs/risk-ratings.json (sha256 479ec5ac8a1a)

Reviewer: Yash Khadilkar  
Date: 2026-10-13

Fill in a Decision for every row, and a Comment where needed. Edit only the Decision and
Comment cells; build_register.py rewrites the other columns and keeps what you wrote.
Do not use the | character in a comment.

- Rated risks: **Approve**, **Amend** (say in Comment exactly what to change) or **Reject**.
- Noted, not rated: **Add to scope** (it will be rated in the next revision) or **Leave out**.
- Applied names the revision in which an Amend, Reject or Add to scope was carried out. To ask
  for a further change to the same row, set the Decision again and clear Applied.

## Rated risks

| Risk | Title | Likelihood | Impact | Score | Band | Decision | Comment | Applied |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-01 | Purchases split to stay under the quote and contract-notice threshold | 4 Almost Certain | 3 Medium | 12 | Medium High (Amber) | Approve | Strongest signal in the register. |  |
| R-02 | Purchases split to stay under the full-tender and Key Decision level | 2 Unlikely | 4 Major | 8 | Medium High (Amber) | Approve | Few groups but high value; examine every one. |  |
| R-03 | Payment values held just under the quote and contract-notice threshold | 2 Unlikely | 3 Medium | 6 | Moderate | Reject | No clustering: fewer payments just below £25,000 than just above it. |  |
| R-04 | Payment values held just under the single-quote threshold | 4 Almost Certain | 1 Negligible | 4 | Moderate | Reject | Negligible impact and low total value; not worth fieldwork time. |  |
| R-05 | Spend at or above the publication threshold with no published notice found | 4 Almost Certain | 3 Medium | 12 | Medium High (Amber) | Amend | Lower likelihood from 4 to 3: the count is inflated by the export only holding notices since 2021 and by framework call-offs that have no notice of their own. |  |
| R-06 | Spend continuing after the matching notice ended, without an approved extension | 3 Likely | 3 Medium | 9 | Medium High (Amber) | Approve |  |  |
| R-07 | Spend beyond the awarded contract value without an approved variation | 3 Likely | 3 Medium | 9 | Medium High (Amber) | Approve |  |  |
| R-08 | Possible duplicate payments to the same supplier | 4 Almost Certain | 2 Minor | 8 | Medium High (Amber) | Approve | Match the sampled payments to invoices. |  |
| R-09 | Waivers or exceptions to the Rules not approved in advance or not documented | 2 Unlikely | 3 Medium | 6 | Moderate | Approve | The Rules disagree on who may grant a waiver; test alongside R-05. |  |
| R-10 | Contract awards not made by the authorised decision-maker or not recorded as a Key Decision | 2 Unlikely | 3 Medium | 6 | Moderate | Approve | Sample the largest suppliers' award decisions. |  |

## Noted, not rated

| Item | Area | Opinion | Decision | Comment | Applied |
| --- | --- | --- | --- | --- | --- |
| AUD-16 | Personal Budgets (Direct Payments) | Limited Assurance | Leave out | Payments to individuals, not council procurement; covered by the existing audit's follow-up. |  |
| AUD-11 | Garland (now Burghfield Common Federation) | Weak | Leave out | Single-school follow-up, outside council-level procurement. |  |
| AUD-12 | Westwood Farm | Limited Assurance | Leave out | Single-school follow-up, outside council-level procurement. |  |
