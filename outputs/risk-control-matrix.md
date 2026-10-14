# Risk-control matrix (register revision r1)

Built 2026-10-14T01:07:59+00:00 by `.claude/skills/audit-program/build_pack.py` from `outputs/audit-plan.json`, on the risks the auditor approved in register r1. For auditor sign-off.

> These are **risk indicators to investigate**, drawn from published data. They are not findings and do not suggest wrongdoing by the council, any service or any supplier.

Each in-scope risk, the controls expected to address it, the rules each control rests on and the tests that check it.

| Risk | Score | Band | Control | Expected control | Rules | Tests |
| --- | --- | --- | --- | --- | --- | --- |
| R-01 Purchases split to stay under the quote and contract-notice threshold | 12 | Medium High (Amber) | C-01 | Each requirement is valued as a whole before the procurement route is chosen, and is not split or disaggregated to avoid the Rules `rule:CPR-12`. | CPR-12 | T-01 |
| R-01 Purchases split to stay under the quote and contract-notice threshold | 12 | Medium High (Amber) | C-02 | For requirements from the quote and notice level up to the Threshold, quotes are invited through the Procurement Portal from at least three appropriate sources `rule:CPR-52` `rule:CPR-54` and a contract notice is published `rule:CPR-53` `rule:CPR-55`, with the progress of the procedure documented `rule:CPR-29`. | CPR-29, CPR-52, CPR-53, CPR-54, CPR-55 | T-01 |
| R-02 Purchases split to stay under the full-tender and Key Decision level | 8 | Medium High (Amber) | C-03 | Requirements whose total value is above the full-tender level are procured by full competitive tender with the required number of written tenders sought through the Procurement Portal and advertised `rule:CPR-56` `rule:CPR-57`, or above the Threshold by the Procurement Legislation procedures `rule:CPR-58` `rule:CPR-59`, recorded in a written procurement report `rule:CPR-27`, and are not split to avoid them `rule:CPR-12`. | CPR-12, CPR-27, CPR-56, CPR-57, CPR-58, CPR-59 | T-02 |
| R-02 Purchases split to stay under the full-tender and Key Decision level | 8 | Medium High (Amber) | C-04 | An award above the Key Decision level is taken and recorded as a Key Decision by the decision-maker the Rules name for its value `rule:CPR-04` `rule:CPR-49` `rule:CPR-50`. | CPR-04, CPR-49, CPR-50 | T-02 |
| R-05 Spend at or above the publication threshold with no published notice found | 9 | Medium High (Amber) | C-05 | A contract notice is published for every contract from the publication level `rule:CPR-53` `rule:CPR-55`; where a contract is let through a purchasing scheme without further competition, the scheme's use is confirmed and approved in advance `rule:CPR-26` `rule:CPR-62`. | CPR-26, CPR-53, CPR-55, CPR-62 | T-03 |
| R-05 Spend at or above the publication threshold with no published notice found | 9 | Medium High (Amber) | C-06 | Every award is notified to the Service Lead for Commissioning and Procurement `rule:CPR-33` and recorded in the published contracts register with its value and duration `rule:CPR-07`. | CPR-07, CPR-33 | T-03 |
| R-06 Spend continuing after the matching notice ended, without an approved extension | 9 | Medium High (Amber) | C-07 | A contract is extended only as provided for in the contract and with the approval of the statutory finance officer before the original term ends `rule:CPR-63`, and with the approval of the relevant board where the Rules' closing provision on exemptions applies to a contract above the Threshold `rule:CPR-67`. | CPR-63, CPR-67 | T-04 |
| R-07 Spend beyond the awarded contract value without an approved variation | 9 | Medium High (Amber) | C-08 | A variation of scope or value is made only as provided for in the contract or permitted by the Procurement Legislation, with the prior written approval of the Monitoring Officer and the statutory finance officer `rule:CPR-64` and, above the Threshold, the approval of the relevant board `rule:CPR-65`. | CPR-64, CPR-65 | T-05 |
| R-08 Possible duplicate payments to the same supplier | 8 | Medium High (Amber) | C-09 | Every payment rests on written evidence of a purchase, so that a second payment for the same purchase is not made `rule:CPR-30`. | CPR-30 | T-06 |
| R-09 Waivers or exceptions to the Rules not approved in advance or not documented | 6 | Moderate | C-10 | A waiver of or exception to the Rules is sought in advance and granted only by the officers the Rules name `rule:CPR-20`, on the grounds allowed for contracts above the waiver level `rule:CPR-19`, with the approval the value band requires `rule:CPR-21` `rule:CPR-22` `rule:CPR-23`, and an exemption is given the prior approval the Rules require `rule:CPR-60` `rule:CPR-67`. | CPR-19, CPR-20, CPR-21, CPR-22, CPR-23, CPR-60, CPR-67 | T-07 |
| R-09 Waivers or exceptions to the Rules not approved in advance or not documented | 6 | Moderate | C-11 | Each waiver or exception is fully documented in a written exception report giving the reasons, and the statutory finance officer records that the reasons were considered `rule:CPR-24` `rule:CPR-25`. | CPR-24, CPR-25 | T-07 |
| R-10 Contract awards not made by the authorised decision-maker or not recorded as a Key Decision | 6 | Moderate | C-12 | Every contract rests on a recorded decision of the Council, the Executive or an officer with delegated authority `rule:CPR-02`, within an existing budgetary provision `rule:CPR-03`, taken by the decision-maker the Rules name for its total contract value `rule:CPR-47` `rule:CPR-48` `rule:CPR-49` `rule:CPR-50`. | CPR-02, CPR-03, CPR-47, CPR-48, CPR-49, CPR-50 | T-08 |
| R-10 Contract awards not made by the authorised decision-maker or not recorded as a Key Decision | 6 | Moderate | C-13 | An award above the Key Decision level is treated, recorded and published as a Key Decision `rule:CPR-04` `rule:CPR-49`. | CPR-04, CPR-49 | T-08 |

## Rule coverage

Every rule in `outputs/rules.json` (67): 38 traced to the in-scope risk, control or test that cites it, 29 listed as not tested with the planner's reason.

| Rule | Clause | Type | Traced to | Not tested: reason |
| --- | --- | --- | --- | --- |
| CPR-01 | 3.5 | threshold |  | Social value consideration for service contracts above the Threshold; no in-scope risk concerns it. |
| CPR-02 | 4.1 | approval | R-10, C-12, T-08 |  |
| CPR-03 | 4.2 | required-action | C-12, T-08 |  |
| CPR-04 | 4.3 | threshold | R-02, C-04, T-02, R-10, C-13, T-08 |  |
| CPR-05 | 5.1 | threshold |  | Publication of expenditure under the Transparency Code; the published spend data is the input itself, not a risk in scope. |
| CPR-06 | 5.2 | threshold |  | Transparency publication of invitations to tender; no in-scope risk concerns it and no test measures invitations. |
| CPR-07 | 5.2.1 | required-action | R-05, C-06, T-03, T-04 |  |
| CPR-08 | 5.3 | required-action |  | Monthly contract reporting to the board; no in-scope risk concerns it. |
| CPR-09 | 6.8 | required-action |  | Advertising on the Procurement Portal; the notice tests use the published contract notice rules instead. |
| CPR-10 | 6.10 | threshold |  | Order of advertising across media above the Threshold; no test can measure the sequence of advertisements. |
| CPR-11 | 6.14 | approval |  | Approval and issue of notices by the Service Lead; no in-scope risk concerns who issues a notice. |
| CPR-12 | 6.16 | anti-avoidance | R-01, C-01, T-01, R-02, C-03, T-02 |  |
| CPR-13 | 6.19 | threshold | T-02 |  |
| CPR-14 | 6.20 | required-action |  | Electronic tender submission and storage; tender handling is not an in-scope risk. |
| CPR-15 | 6.21 | approval |  | Treatment of late tenders; tender handling is not an in-scope risk. |
| CPR-16 | 6.22 | required-action |  | Electronic opening of tenders; tender handling is not an in-scope risk. |
| CPR-17 | 6.24 | required-action |  | Evaluation against advertised criteria; evaluation is not an in-scope risk. |
| CPR-18 | 6.26 | approval |  | Award on the most advantageous basis; evaluation is not an in-scope risk. |
| CPR-19 | 7.2 | threshold | R-09, C-10, T-07 |  |
| CPR-20 | 7.3 | approval | T-03, R-09, C-10, T-07 |  |
| CPR-21 | 7.4.1 | approval | R-09, C-10, T-07 |  |
| CPR-22 | 7.4.2 | approval | C-10, T-07 |  |
| CPR-23 | 7.4.3 | approval | C-10, T-07 |  |
| CPR-24 | 7.5 | required-action | R-09, C-11, T-07 |  |
| CPR-25 | 7.5.3 | approval | R-09, C-11, T-07 |  |
| CPR-26 | 8.2 | required-action | T-01, C-05, T-03 |  |
| CPR-27 | 9.1 | threshold | C-03, T-02 |  |
| CPR-28 | 9.2 | required-action |  | Retention of procurement reports; record retention is not an in-scope risk. |
| CPR-29 | 9.3 | required-action | C-02, T-01 |  |
| CPR-30 | 10.1 | required-action | R-08, C-09, T-06 |  |
| CPR-31 | 10.2 | approval |  | Form of written contracts; contract documentation is not an in-scope risk. |
| CPR-32 | 10.3 | required-action |  | Retention of sealed contracts by Legal Services; contract documentation is not an in-scope risk. |
| CPR-33 | 10.4 | required-action | C-06, T-03 |  |
| CPR-34 | 10.5 | required-action |  | Standard clauses in contracts; contract content is not an in-scope risk. |
| CPR-35 | 10.6 | approval |  | Approval of amended standard forms; contract content is not an in-scope risk. |
| CPR-36 | 10.7 | required-action |  | Minimum contract clauses; contract content is not an in-scope risk. |
| CPR-37 | 10.7.7 | required-action |  | Data protection impact assessment; contract content is not an in-scope risk. |
| CPR-38 | 10.7.10 | required-action |  | Enforceable specifications; contract content is not an in-scope risk. |
| CPR-39 | 11.1 | approval |  | Relaxation of indemnities; contract terms are not an in-scope risk. |
| CPR-40 | 11.3 | approval |  | Form of performance bonds; contract security is not an in-scope risk. |
| CPR-41 | 11.4 | approval |  | Approval where no performance bond is required; contract security is not an in-scope risk. |
| CPR-42 | 11.5 | required-action |  | Contract risk assessment and insurance; contract security is not an in-scope risk. |
| CPR-43 | 11.8 | approval |  | Attestation of sealing; execution of documents is not an in-scope risk. |
| CPR-44 | 11.9 | required-action |  | Sealing register entries; execution of documents is not an in-scope risk. |
| CPR-45 | 11.11 | threshold |  | Sealing of contracts above the Threshold; execution of documents is not an in-scope risk. |
| CPR-46 | 11.13 | required-action |  | Signing and recording of unsealed documents; execution of documents is not an in-scope risk. |
| CPR-47 | AppA-1 | approval | R-10, C-12, T-08 |  |
| CPR-48 | AppA-2 | approval | R-10, C-12, T-08 |  |
| CPR-49 | AppA-3 | approval | C-04, T-02, R-10, C-12, C-13, T-08 |  |
| CPR-50 | AppA-4 | approval | C-04, T-02, R-10, C-12, T-08 |  |
| CPR-51 | AppB-A | threshold | R-01 |  |
| CPR-52 | AppB-B1 | threshold | R-01, C-02, T-01 |  |
| CPR-53 | AppB-B1 | threshold | R-01, C-02, T-01, R-05, C-05, T-03 |  |
| CPR-54 | AppB-B2 | threshold | C-02, T-01 |  |
| CPR-55 | AppB-B2 | threshold | C-02, T-01, R-05, C-05, T-03 |  |
| CPR-56 | AppB-C | threshold | R-02, C-03, T-02 |  |
| CPR-57 | AppB-C | threshold | C-03, T-02 |  |
| CPR-58 | AppB-D | threshold | R-02, C-03, T-02 |  |
| CPR-59 | AppB-D | threshold | C-03, T-02 |  |
| CPR-60 | AppC-A | approval | C-10, T-07 |  |
| CPR-61 | AppC-B | required-action | T-03 |  |
| CPR-62 | AppC-C | approval | T-01, C-05, T-03 |  |
| CPR-63 | AppC-D | approval | R-06, C-07, T-04 |  |
| CPR-64 | AppC-E | approval | R-07, C-08, T-05 |  |
| CPR-65 | AppC-E | approval | R-07, C-08, T-05 |  |
| CPR-66 | AppC-F | required-action |  | Individual social care placements are outside the general procurement rows every sample is drawn from. |
| CPR-67 | AppC-closing | approval | C-07, T-04, C-10, T-07 |  |
