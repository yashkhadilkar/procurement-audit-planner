# QA review: audit planning pack

Register revision: r1 (gate: GATE OK: register r1; 8 risks in scope: R-01 (Approve, score 12), R-02 (Approve, score 8), R-05 (Amend, score 9), R-06 (Approve, score 9), R-07 (Approve, score 9), R-08 (Approve, score 8), R-09 (Approve, score 6), R-10 (Approve, score 6))
Version reviewed: v3 · Planner: PLANNER DONE v3 · Challenger: CHALLENGER DONE
Reviewed: 2026-10-14T01:09:13Z

## Verdict

**READY FOR SIGN-OFF**

Every check passed in the final run on v3, the version the planner finished on; the pack is unchanged since QA v3: PASS.

## Final check run (as printed)

```text
QA checks (final run)
Pack: built 2026-10-14T01:07:59+00:00, register r1; audit-plan.json e854327f68b4; planning-memo.md 144ea449f6ee; risk-control-matrix.md e08b00057e91; audit-program.md de37e071ee6a; pack-figures.json 45af71d2635d; challenges.md 723242e7ea4a; samples (7 files) 159d331ac167

| Check | Result | Checked | Failures |
| --- | --- | --- | --- |
| check_quotes | PASS | 1 verifier runs, 121 rule quote passages, 2 parameter quote passages, 64 register rule citations, 26 register rule source lines, 8 register history excerpts (not rule quotes) | 0 |
| check_numbers | PASS | 6 pack inputs fingerprinted, 3 documents, 31 figures | 0 |
| check_trace | PASS | 67 rules, 8 in-scope risks, 8 tests, 13 controls, 2 rejected risks, 3 noted items left out, 6 High risks, 7 challenges | 0 |
| check_samples | PASS | 7 sample files, 520 sampled transactions, 0 row IDs in audit-program.md | 0 |

VERDICT: PASS

note (check_numbers): skipped: dates 5, citations, paths and hashes 203, IDs 472, years 3, clause and page references 83, file paths 4, $.paths 1
```

## Versions checked

| Version | Pack | Verdict | Points |
| --- | --- | --- | --- |
| v1 | Pack: built 2026-10-14T00:59:35+00:00, register r1; audit-plan.json 5ce51ab15b60; planning-memo.md a14ea862f27f; risk-control-matrix.md 7af127ff49d7; audit-program.md 6ad13798467d; pack-figures.json 96066a675881; samples (7 files) 159d331ac167 | PASS | |
| v2 | Pack: built 2026-10-14T01:06:37+00:00, register r1; audit-plan.json e84c6301c594; planning-memo.md 742cdd4338c5; risk-control-matrix.md cd6aa3c785f9; audit-program.md c0f2a5d7cdd9; pack-figures.json 3d6d24be0a74; samples (7 files) 159d331ac167 | PASS | |
| v3 | Pack: built 2026-10-14T01:07:59+00:00, register r1; audit-plan.json e854327f68b4; planning-memo.md 144ea449f6ee; risk-control-matrix.md e08b00057e91; audit-program.md de37e071ee6a; pack-figures.json 45af71d2635d; samples (7 files) 159d331ac167 | PASS | |

## QA points answered for the auditor

None.

## Auditor sign-off

To be completed by the auditor. QA does not sign off.

| Item | Entry |
| --- | --- |
| QA verdict | READY FOR SIGN-OFF |
| Pack version | v3 |
| Challenges marked *for the auditor* in `outputs/challenges.md` considered | Yes |
| QA points answered *for the auditor* considered | Yes |
| Decision | Signed off |
| Auditor | Yash Khadilkar |
| Date | 2026-10-13 |
| Comment | Challenge #1 (AUD-16) considered. The Leave out decision stands, but its gate comment overstated the record: history.json shows no follow-up of this audit. The reason for leaving it out is that Direct Payments are payments to individuals, not council procurement, and the spend tests exclude them. The Limited opinion and its agreed actions should be followed up with the internal audit plan owner, outside this audit. |
