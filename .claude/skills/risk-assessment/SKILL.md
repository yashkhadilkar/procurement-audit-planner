---
name: risk-assessment
description: The method the risk-assessor follows to rate procurement risks for the West Berkshire Council audit. The agent writes its judgments to outputs/risk-ratings.json, citing rules.json, analytics.json and history.json with [rule:ID], [metric:$.path] and [history:ID] tags and {{$.path}} placeholders for every figure; build_register.py (next to this file) resolves the citations, applies the likelihood rubric, scores on the council's 5x5 matrix and renders outputs/risk-register.md and outputs/auditor-comments.md. Also covers the revision after the auditor's gate. Finishes only when build_register.py exits 0.
---

# risk-assessment

You judge; `build_register.py` computes. You write `outputs/risk-ratings.json`,
which holds what the risks are, the evidence each rests on, and your
likelihood and impact judgments. The builder resolves every citation, fills
every figure from analytics.json, checks your likelihood against the rubric,
computes score, matrix label and band from the council's matrix, and writes
the register and the auditor's decision template. You are done only when it
exits 0.

Ground rules:
- **No number is typed by you.** Every figure in prose is a `{{$.path}}`
  placeholder into analytics.json. The builder warns on any digit it finds in
  prose; treat each warning as something to fix. Clause numbers and years
  are not figures, but clauses belong in `[rule:...]` tags anyway.
- **No arithmetic.** You never add, annualise, compare or compute a ratio. If
  a figure you need is not in analytics.json, say so in prose ("not computed")
  and ask for the spend-analyst to add it. Never derive it.
- **Every likelihood and impact justification cites at least one primary
  source that resolves:** a rule, a history item, or a `general_procurement`
  metric. Without one the risk is excluded.
- **Indicators, not accusations.** Write "risk indicator to investigate",
  "may indicate", "no published notice found". Never say or imply wrongdoing by
  the council, a service or a supplier. Name suppliers only where the
  proposed focus needs them, and only as items to sample.
- **Missing or malformed input: stop and report.** If analytics.json,
  history.json or rules.json is missing or the builder cannot read it, stop.
- **Context discipline.** Never read analytics.json, history.json or
  `outputs/analytics-full/` whole. Look things up with the builder's
  `--resolve` mode (below) or a short Python one-liner that prints one path.

## Step 1: Read the evidence

Check what a path holds, and how it counts as evidence, without loading the file:

```bash
B=.claude/skills/risk-assessment/build_register.py
.venv/bin/python -I $B --resolve '$.tests.duplicates' --resolve '$.tests.duplicates.by_tag.general_procurement'
```

Each line prints the value (or the keys of an object) and its class:
`primary` (general_procurement), `context` (another tag, or all tags
combined), `noise` (the split tier that flags by construction) or
`reference` (parameters and thresholds outside `$.tests`).

What analytics.json holds (real structure; check values with `--resolve`):

| Path | What it is |
| --- | --- |
| `$.window` | spend window: start, end, months, annualisation_factor |
| `$.parameters` | every cutoff the tests used (split_window_days, duplicate_window_days, ...) |
| `$.named_thresholds.quote.value`, `$.named_thresholds.tender_publication.value` | the quote and publication thresholds, with rule_ids |
| `$.publication_floor` | the level above which spend is published, with rule_id |
| `$.tests.<test>.status` | `run`, or why not |
| `$.tests.<test>.rule_ids` | rules the test measures |
| `$.tests.<test>.counts`, `.totals` | all tags combined (context) |
| `$.tests.<test>.by_tag.<tag>.count` / `.total` | per tag; `general_procurement` is primary |
| `$.tests.threshold_clustering.by_threshold[threshold=T].below.by_tag...` / `.comparison.by_tag...` | band just below T and the comparison band just above |
| `$.tests.split_purchases.by_threshold[threshold=T].by_tag...` | split groups for tier T |
| `$.tests.<test>.top20[n]` | the top items, each with its `spend_tag` |
| `$.tests.<test>.full_list` | the CSV in `outputs/analytics-full/` |

Keys with spaces are bracket-quoted: `$.tests.no_published_notice.counts['no published notice found']`.

From history.json you cite items by `id`: audits `AUD-nn` (title, opinion),
risk themes `THM-nn`, discrepancies `DIS-nn`, gaps `GAP-nn`, opinion notes
`OPB-nn`. From rules.json you cite `CPR-nn`.

## Step 2: Decide the risks

A risk is a way the Contract Procedure Rules could fail, framed so the audit
can test it. Start from the rules each test measures (`$.tests.<test>.rule_ids`)
and from the anti-avoidance, approval and required-action rules no test
measures. One risk per distinct failure (splitting to avoid competition,
spend with no published notice found, spend after a notice expired, spend
beyond an award, duplicate payments, missing waivers or approvals...).
Number them `R-01`, `R-02`, ... in the order you write them.

Decisions that apply to every rating:

1. **General procurement is the evidence.** Likelihood and impact rest on
   the `general_procurement` figures. Placement, grant, agency staff and
   premises figures, and all-tags totals, may be cited as context, never as
   the main evidence: placements recur by design. The builder enforces this:
   context metrics do not count as a primary citation, and the likelihood
   signal must be a `general_procurement` count.
2. **The £1,000 split_purchases tier can't raise a rating on its own.** Any two
   published payments under £1,000 add up to more than £1,000, so it flags by
   construction. The builder classes any split tier at or below twice the
   publication floor as `noise`, refuses it as a signal or primary evidence,
   treats split_purchases totals that include it as context, and says so in
   the register header. Use `by_threshold[threshold=T]` for the tiers above it.
3. **Noted, not rated.** An audit in history.json with a Limited (or worse)
   opinion on an area the spend tests exclude (for example Personal Budgets
   (Direct Payments), whose payments are excluded before tagging) is neither
   rated nor dropped. Put it in `noted_not_rated` with the reason; the
   auditor decides at the gate. The builder warns about any adverse audit
   you have neither cited nor noted. Every adverse audit is either cited in
   a rated risk it bears on, or listed in `noted_not_rated` with a reason
   (for an audit plainly outside procurement, such as a single school, the
   reason says so). Never leave one as a warning.

## Step 3: Write outputs/risk-ratings.json

```json
{
  "risks": [
    {
      "risk_id": "R-01",
      "title": "Purchases split to stay under the quote and tender threshold",
      "description": "Payments to one supplier ... within {{$.parameters.split_window_days}} days may indicate ... [rule:CPR-12].",
      "likelihood": {
        "score": 4,
        "rubric_row": "S3",
        "signal": "$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count",
        "justification": "{{$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count}} general procurement groups reach the quote threshold of £{{$.named_thresholds.quote.value}} [metric:$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.count]; quotes are required at that value [rule:CPR-52].",
        "repeat_uplift": null
      },
      "impact": {
        "score": 3,
        "category": "Compliance (litigation, regulatory, contract)",
        "justification": "... [rule:CPR-53] [metric:$.tests.split_purchases.by_threshold[threshold=25000].by_tag.general_procurement.total] ..."
      },
      "evidence": "prose with tags and placeholders",
      "proposed_focus": "what the audit should look at, in one or two sentences"
    }
  ],
  "noted_not_rated": [
    {"history": "AUD-16", "reason": "Direct Payments are excluded from every spend test, so no test measures this area [history:AUD-16]."}
  ],
  "revision": null
}
```

Citations, inside any prose field:
- `[rule:CPR-52]` must be a rule_id in rules.json.
- `[history:AUD-16]` must be an id in history.json.
- `[metric:$.path]` must resolve in analytics.json to a non-null value.
- `{{$.path}}` must resolve to a number or text, which the builder writes
  in. Integers render as `1,234` and decimals as `1,234.56`, so write the `£` yourself.

Path syntax: `.key`, `['key with spaces']`, `[0]`, and `[field=value]`,
which picks the one list item whose field equals value (for example
`[threshold=25000]`). Prefer `[field=value]` to `[n]`: it says which tier you mean.

Any citation or placeholder that does not resolve excludes the whole risk.
The register lists it under "Excluded" with the reason. Fix it before you hand over.

### Likelihood rubric

Pick the one test (or threshold tier) that measures the risk. Its
`general_procurement` count is the **signal**. Put the path in
`likelihood.signal` and cite the same path as a `[metric:...]` in the
justification. The builder computes the row from the signal, and fails if
your `rubric_row` or `score` disagrees:

| Row | Evidence | Base likelihood |
| --- | --- | --- |
| NT | No analytics test measures the risk, or its test or tier did not run (`signal: null`) | 2 Unlikely |
| S0 | Signal count is 0 | 1 Rare |
| S1 | Signal count 1 to 4; or a threshold_clustering tier whose below-band count does not exceed its comparison band | 2 Unlikely |
| S2 | Signal count 5 to 19 | 3 Likely |
| S3 | Signal count 20 or more | 4 Almost Certain |

Likelihood = base, + 1 for a repeat finding, at most 5. Certain (5) is reached only through the uplift.

Signal rules:
- It must point into `$.tests`, at a test whose status is `run`, and end in
  `.by_tag.general_procurement.count`.
- For `split_purchases` and `threshold_clustering`, it names one tier:
  `$.tests.split_purchases.by_threshold[threshold=T].by_tag.general_procurement.count`
  or `$.tests.threshold_clustering.by_threshold[threshold=T].below.by_tag.general_procurement.count`.
  A clustering tier with no excess over its comparison band is capped at S1.
- `high_value_suppliers` is never a signal: it is a population to request
  contract evidence for, not an indicator. It can be cited (its
  general_procurement figures are primary) for impact or focus.
- A threshold test whose tier did not run ("not run: parameter not
  supplied") gives NT, with `signal: null`.
- When two tests bear on one risk, the signal is the one that most directly
  measures the failure the risk names; cite the other as further evidence.
  If they measure different failures, they are different risks.

Repeat finding: `repeat_uplift: {"history": "AUD-nn", "justification": "..."}`
raises likelihood by 1. It must cite an audit with an adverse opinion
(Limited Assurance or worse, including Weak) on the same theme as the risk,
and the justification says why the theme is the same. The builder fails an
uplift that cites anything else. If no adverse audit covers the theme, there is no uplift.

### Impact

Impact is your judgment against the council's Table 1. Name the column you
judge it on in `impact.category`, which must be one of Table 1's headings as
recorded in history.json (for example "Compliance (litigation, regulatory,
contract)"). Choose the level whose printed criterion fits, and justify it
with a primary citation. The register prints the criterion beside your score.
- For a procurement-rule risk the usual column is Compliance: the chance of
  legal challenge or regulatory interest when competition, publication or
  approval rules are not followed.
- Use "Financial loss to Council" only where the indicator is itself a
  possible loss (for example a duplicate payment). Flagged spend is not a
  loss. Spend that went through without competition is the exposure, not the loss.
- The builder states in the register header which of Table 1's printed
  figures are used where they conflict (the percentage ranges overlap; the £
  ranges are used). Do not restate them.

### Scoring method

Score, matrix label and band are computed, not chosen. Where the council's
method conflicts with itself (for example Figure 4 escalates to the
Corporate Risk Register at a lower score than Table 4), the builder uses one
reading, marks the other, and says so in the register header with the
history item. If history.json reports no usable method, the builder falls
back to 1 to 5, Very low to Very high, and says so. Never adjust a score to
land in a band.

## Step 4: Build

```bash
.venv/bin/python -I .claude/skills/risk-assessment/build_register.py
```

- **FAIL** (exit 1, nothing written): fix every error listed and re-run.
  The possible errors are a schema problem, a rubric mismatch, an invalid uplift,
  an unknown impact category, an unusable scoring method, or a revision rule.
- **EXCLUDED**: the risk's citations do not resolve, or its likelihood or
  impact has no primary citation. Fix it, or remove the risk if the evidence
  is not there. Do not hand over a register with exclusions you could fix.
- **WARNING**: typed figures (replace them with placeholders), a risk citing no
  rule (add the rule: the planner traces rule → risk → control → test),
  NT despite a cited test metric, adverse audits neither cited nor noted.

It writes `outputs/risk-register.md`, `outputs/auditor-comments.md` (one row
per rated risk and per noted item, with blank Decision and Comment; decisions
already in the file are kept) and `outputs/register-snapshots/r0.json`. Once
the auditor has written any decision, r0 can no longer change: a rebuild with
different ratings or inputs fails, and changes go through a revision.

Report back: the risks rated (ID, title, likelihood, impact, band), the noted
items, every warning you left and why, and that the auditor now completes
`outputs/auditor-comments.md`.

## Step 5: Revision after the gate

When the auditor has decided every row in `outputs/auditor-comments.md`:

1. Read the decisions. A decision is pending when its Applied cell is blank.
   - **Approve** or **Leave out**: change nothing for that row.
   - **Amend**: make exactly the change the Comment asks for, nothing more.
   - **Reject**: set the risk's `"status": "rejected"`. Never delete a risk.
   - **Add to scope** (noted item): remove it from `noted_not_rated` and add
     a new risk (next free R- number) rated by the same method.
2. Record each change in the revision block. `number` is the latest snapshot
   number plus 1 (r0 → 1).
   ```json
   "revision": {"number": 1, "changes": [
     {"target": "R-02", "decision_ref": "R-02", "fields": ["likelihood.score", "likelihood.justification"],
      "summary": "Likelihood lowered at the auditor's request."},
     {"target": "R-04", "decision_ref": "R-04", "fields": ["status"], "summary": "Rejected by the auditor."},
     {"target": "AUD-16", "decision_ref": "AUD-16", "fields": ["removed"], "summary": "Moved into scope."},
     {"target": "R-07", "decision_ref": "AUD-16", "fields": ["added"], "summary": "Rated at the auditor's request."}
   ]}
   ```
   `fields` names exactly what changed: `title`, `description`,
   `likelihood.score`, `likelihood.rubric_row`, `likelihood.signal`,
   `likelihood.justification`, `likelihood.repeat_uplift`, `impact.score`,
   `impact.category`, `impact.justification`, `evidence`, `proposed_focus`,
   `status`; `added` / `removed` for whole risks or noted items; `reason` for
   a noted item's reason.
3. Build. The builder diffs the ratings against the previous snapshot and fails if:
   - a pending decision is left unapplied;
   - anything changed that no pending decision asked for, or that the revision
     block does not declare;
   - a declared change did not happen;
   - a row is still undecided;
   - analytics.json, history.json or rules.json changed since the snapshot.
   It writes a revision header naming each change and the decision behind it,
   marks an **auditor override** wherever an Amend sets a likelihood the
   rubric would not give (with the rubric's value) or changes an impact,
   sets Applied to the revision in auditor-comments.md, and writes the new snapshot.

An Amend whose Comment is unclear, or that asks you to break a rule above
(type a figure, cite a context metric as primary, drop a risk silently), is not
applied: stop and ask the auditor through the main agent.

## Do not

- Do not edit risk-register.md, auditor-comments.md (other than through the
  builder) or the snapshots by hand.
- Do not change rules.json, analytics.json or history.json, or work around a
  citation that will not resolve.
- Do not resolve a conflict in the council's scoring method yourself, or pick
  scores to reach a band.
- Do not fold the auditor's decisions into the ratings without a revision block.
