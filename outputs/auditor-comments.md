# Auditor comments: risk register decisions

Register revision: r0  
Built: 2026-10-13T20:22:52+00:00 from outputs/risk-ratings.json (sha256 479ec5ac8a1a)

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
| R-01 | Purchases split to stay under the quote and contract-notice threshold | 4 Almost Certain | 3 Medium | 12 | Medium High (Amber) |  |  |  |
| R-02 | Purchases split to stay under the full-tender and Key Decision level | 2 Unlikely | 4 Major | 8 | Medium High (Amber) |  |  |  |
| R-03 | Payment values held just under the quote and contract-notice threshold | 2 Unlikely | 3 Medium | 6 | Moderate |  |  |  |
| R-04 | Payment values held just under the single-quote threshold | 4 Almost Certain | 1 Negligible | 4 | Moderate |  |  |  |
| R-05 | Spend at or above the publication threshold with no published notice found | 4 Almost Certain | 3 Medium | 12 | Medium High (Amber) |  |  |  |
| R-06 | Spend continuing after the matching notice ended, without an approved extension | 3 Likely | 3 Medium | 9 | Medium High (Amber) |  |  |  |
| R-07 | Spend beyond the awarded contract value without an approved variation | 3 Likely | 3 Medium | 9 | Medium High (Amber) |  |  |  |
| R-08 | Possible duplicate payments to the same supplier | 4 Almost Certain | 2 Minor | 8 | Medium High (Amber) |  |  |  |
| R-09 | Waivers or exceptions to the Rules not approved in advance or not documented | 2 Unlikely | 3 Medium | 6 | Moderate |  |  |  |
| R-10 | Contract awards not made by the authorised decision-maker or not recorded as a Key Decision | 2 Unlikely | 3 Medium | 6 | Moderate |  |  |  |

## Noted, not rated

| Item | Area | Opinion | Decision | Comment | Applied |
| --- | --- | --- | --- | --- | --- |
| AUD-16 | Personal Budgets (Direct Payments) | Limited Assurance |  |  |  |
| AUD-11 | Garland (now Burghfield Common Federation) | Weak |  |  |  |
| AUD-12 | Westwood Farm | Limited Assurance |  |  |  |
