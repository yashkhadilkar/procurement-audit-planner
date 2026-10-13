---
name: audit-program
description: The method the planner follows to turn the auditor-approved risk register for the West Berkshire Council procurement audit into the planning pack. The planner writes its judgments to outputs/audit-plan.json (expected controls citing rules, test steps citing a rule or metric, a sample recipe per test, the PBC items each test needs, and the rules not tested with a reason), using [rule:ID], [metric:$.path] and [history:ID] tags and {{$.path}} placeholders for every figure; build_pack.py (next to this file) checks the gate, resolves every citation, draws every sample deterministically from the general_procurement rows of the analytics-full lists, sized by score, and renders outputs/planning-memo.md, outputs/risk-control-matrix.md and outputs/audit-program.md, the sample files in outputs/samples/ and outputs/pack-figures.json. Finishes only when build_pack.py exits 0.
---

# audit-program

You judge; `build_pack.py` computes. You write `outputs/audit-plan.json`,
which holds what control the Rules expect for each approved risk, how the
audit tests it, which list each sample comes from and how it is ordered, and
what to request from the council. The builder computes the scope from the
auditor's decisions, resolves every citation, fills every figure, draws and
verifies every sample, checks the trace from rule to test, and writes the
pack. You are done only when it exits 0.

Ground rules:
- **Only the approved scope.** Plan every risk the auditor approved or
  amended, and nothing else. The builder computes the scope from
  `outputs/auditor-comments.md` and `outputs/risk-ratings.json`; you do not
  choose it, and you never re-rate a risk.
- **No number is typed by you.** Every figure in prose is a `{{$.path}}`
  placeholder into analytics.json, the same syntax as the risk register. A
  typed figure fails the build. Sample sizes, populations, scores and
  totals are written by the builder.
- **No arithmetic.** You never count, add or compare. The builder counts the
  population, sizes the sample and totals it.
- **Indicators, not accusations.** Write "risk indicator to investigate",
  "may indicate", "no published notice found". The builder fails on words
  that state wrongdoing ("off contract", "wrongdoing", "breach", "unlawful",
  "fraudulent", ...). Name suppliers only as items to sample, and leave that
  to the sample files.
- **Missing or malformed input: stop and report.** If the gate fails or an
  input is missing, stop; never work around it.
- **Context discipline.** Never read analytics.json, history.json or a list in
  `outputs/analytics-full/` whole. Use `--lists` and the register builder's
  `--resolve` (below).

## Step 1: Gate

```bash
.venv/bin/python -I .claude/skills/audit-program/build_pack.py --gate
```

It passes only when the register is a revision (r1 or later) built from the
current risk-ratings.json and inputs, every register row has a decision, and
every Amend, Reject and Add to scope decision is applied. It prints the risks
in scope (Approve or Amend) with their scores, and what is out. If it fails,
report the errors and stop: the auditor completes `auditor-comments.md` and
the risk-assessor builds the revision.

## Step 2: Read the evidence

For each in-scope risk, read its entry in `outputs/risk-register.md` (the
register is short; read the risk's section, not the whole file) and its
proposed focus. Then:

```bash
P=.claude/skills/audit-program/build_pack.py
.venv/bin/python -I $P --lists          # each list: its test, general_procurement rows, columns, id columns
B=.claude/skills/risk-assessment/build_register.py
.venv/bin/python -I $B --resolve '$.tests.duplicates.by_tag.general_procurement'
```

A rule's text: `.venv/bin/python -I -c "import json; print(json.dumps([r for r in json.load(open('outputs/rules.json'))['rules'] if r['rule_id']=='CPR-30'], indent=1))"`.

## Step 3: Write outputs/audit-plan.json

```json
{
  "register_revision": 1,
  "memo": {
    "objective": "one paragraph",
    "background": "the spend window {{$.window.start}} to {{$.window.end}}, prior audits [history:AUD-01] ...",
    "approach": "how the risks are tested ...",
    "limitations": "what the data cannot show ..."
  },
  "risks": [
    {
      "risk_id": "R-01",
      "controls": [
        {"control_id": "C-01", "control": "Requirements are aggregated before the route is chosen [rule:CPR-12]."}
      ],
      "tests": [
        {
          "test_id": "T-01",
          "controls": ["C-01"],
          "step": "For each sampled group, obtain the orders ... [rule:CPR-12] [metric:$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count]",
          "sample": {
            "file": "split_purchases.csv",
            "where": [{"field": "threshold", "op": "eq", "value": 25000}],
            "population_metric": "$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count",
            "sort": [{"field": "best_window_total", "order": "desc"}],
            "size": "by_score",
            "transactions": "best_window_ids"
          },
          "pbc": ["PBC-01", "PBC-02"]
        }
      ]
    }
  ],
  "pbc": [
    {"pbc_id": "PBC-01", "item": "Purchase orders and quote records for the sampled groups [rule:CPR-52].", "standing": null},
    {"pbc_id": "PBC-02", "item": "The council's contracts register [rule:CPR-07].", "standing": "contracts_register"}
  ],
  "rules_not_tested": [
    {"rule_id": "CPR-14", "reason": "Electronic tender handling; no in-scope risk concerns it."}
  ]
}
```

`register_revision` is the revision the gate reported. IDs are `C-01`,
`T-01`, `PBC-01`, numbered across the whole plan.

**Controls.** One per control the Rules expect to prevent or detect the
failure the risk names. Each cites at least one rule (`[rule:CPR-nn]`); a
control with no resolvable rule fails the build. Every control is covered by
at least one test.

**Test steps.** What the auditor does with each sampled item, and what result
would clear or confirm the indicator. Each cites at least one rule or one
`general_procurement` metric, names the controls it tests (of the same risk)
and the PBC items it needs. A test that works from documents alone (for
example a walkthrough of the waiver approval process) sets `"sample": null`
and gives `no_sample_reason`.

**Sample recipe.** The builder draws it; you say where from and in what order.
- `file`: a list in `outputs/analytics-full/` that a test publishes (see `--lists`).
- Samples come **only from the `general_procurement` rows** of the list, the
  rows the register's ratings rest on. The builder applies this itself;
  never filter `spend_tag`.
- `where`: further conditions, `{field, op, value}` with op `eq`, `ne`, `in`,
  `gt`, `gte`, `lt` or `lte`; `[]` for the whole list. Use `true`/`false` for
  the `flag` column of spend_vs_award.csv.
- `population_metric`: the `general_procurement` count in analytics.json for
  the same test. The rows left after the filter must equal it, so the sample
  population is the population the register rated. For a split or
  clustering tier, filter `threshold` and cite that tier.
- `sort`: one or more `{field, order: asc|desc}`, for example the largest
  total first. Ties keep the list's own order, so the draw is reproducible.
- `size`: `"by_score"` (the default), `"all"`, or a larger whole number. Any
  size other than `"by_score"` needs `size_reason` (for example, an auditor
  comment asking to examine every group). A sample is never smaller than the
  score gives:

  | Risk score | Items per test |
  | --- | --- |
  | 15 to 25 | 25 |
  | 10 to 14 | 20 |
  | 8 to 9 | 15 |
  | 4 to 7 | 10 |
  | 1 to 3 | 5 |

  Where the population is smaller, all of it is taken.
- `transactions`: the column holding each item's transaction ids
  (`transaction_ids`, `best_window_ids` for a split group's qualifying window,
  or `transaction_id` for a single-payment list).
- `max_per_item` (optional): at most this many transactions per item, the
  largest first. Use it where one supplier carries many payments.

The builder checks every pulled transaction against `spend-clean.csv` (same
id, supplier and amount) and writes `outputs/samples/T-nn.csv`.

**PBC list.** Every item that a test needs, each tied to at least one test.
Five standing items appear in every pack, whatever the tests need; mark each
with `standing` and cite its source:

| standing | Request | Must cite |
| --- | --- | --- |
| `contracts_register` | the council's contracts register | a rule whose evidence source is the contract register |
| `contract_evidence` | contract evidence for the high_value_suppliers population | a `high_value_suppliers` metric; the builder adds the population and the order (no published notice found first) |
| `waiver_log` | the waiver and exception log | a rule on waivers |
| `threshold_values` | the Threshold values the Rules name but do not state | a rule bounded by that parameter; the builder lists the parameter, its clauses and the rules it bounds |
| `audit_plan_appendices` | the Internal Audit Plan appendices missing from the published paper | the history.json gap that records them |

**Rules not tested.** Every rule in rules.json is either cited by an in-scope
risk (its text in risk-ratings.json), a control or a test step, or listed in
`rules_not_tested` with a one-line reason. A rule cited by a PBC item only is
not tested. Listing a rule that is cited fails, as does leaving one out.

**Memo.** Four fields, each prose with citations and placeholders:
`objective`, `background`, `approach`, `limitations`. The builder writes the
rest: the scope table (scores, bands, decisions, tests, sample sizes), what
is out of scope and why (the auditor's comments), the sampling method and
size table, the inputs, and the escalation conflict in the Risk Management
Strategy (history DIS-04: Figure 4 sends risks scoring 9 or above to the
Corporate Risk Register, Table 4 only Extreme), with the in-scope risks it
affects. Do not restate any of these.

## Step 4: Build

```bash
.venv/bin/python -I .claude/skills/audit-program/build_pack.py
```

- **FAIL** (exit 1, nothing written): fix every error listed and re-run.
  Errors are: the gate; a schema problem; a risk in scope but not planned, or
  planned but not in scope; a citation or placeholder that does not resolve; a
  control with no rule or no test; a test with no rule or metric; a typed
  figure or accusatory word; a sample recipe whose file, columns, population
  or size is wrong, or a pulled transaction not in spend-clean.csv; a PBC item
  that no test needs, or a standing item missing or uncited; a rule neither
  cited nor listed as not tested.
- **OK**: it writes `outputs/planning-memo.md`, `outputs/risk-control-matrix.md`,
  `outputs/audit-program.md` (ending with the PBC list), one
  `outputs/samples/T-nn.csv` per sampled test (stale ones removed) and
  `outputs/pack-figures.json`, which lists every figure the builder computed
  (scores, populations, sizes, items, transactions, values, escalation, rule
  counts) and every placeholder it filled, for the QA number check.

Report back: the risks planned, controls and tests per risk, the samples
(items and transactions), the PBC items, the rules not tested, and that the
pack is ready for challenge and QA.

## Do not

- Do not edit the three documents, the sample files or pack-figures.json by
  hand; change audit-plan.json and rebuild.
- Do not change the register, risk-ratings.json, auditor-comments.md or any
  input, or plan a risk the auditor did not approve.
- Do not pick samples by hand, shrink a sample below its score, or sample
  placement, grant, agency staff or premises rows.
- Do not resolve the conflicts in the council's scoring method; the memo
  states them and the auditor decides.
