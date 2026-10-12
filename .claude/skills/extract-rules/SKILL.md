---
name: extract-rules
description: Turn the West Berkshire Council Contract Procedure Rules (data/contract-rules.pdf) into outputs/rules.json, one entry per testable rule with clause, page, value band, required action, approver, evidence source and a verbatim quote, plus named-only parameters, excluded clauses and drafting notes. Human-invoked as /extract-rules; finishes only when verify_quotes.py passes.
---

# extract-rules

Converts `data/contract-rules.pdf` into `outputs/rules.json`, the criteria every
later step tests against. You read the document and decide what counts as a
rule. `verify_quotes.py` (next to this file) checks your work mechanically.
You are done only when it exits 0.

Ground rules:
- **Nothing from memory.** Every value, quote and clause number comes from the PDF
  text. If the PDF names a threshold without giving its value (for example "the
  Threshold"), the value stays `null`, even if you know the current statutory
  figure.
- **Never renumber, correct or tidy the document.** Record clauses exactly as
  printed. Problems go in `notes`.
- **Every numbered clause is accounted for.** It goes in `rules` or in
  `excluded`, never in neither.
- **Missing or malformed input: stop and report.** Do not guess.

## Step 1: Extract and check the document

```bash
S=<your scratchpad dir>
pdftotext        data/contract-rules.pdf "$S/rules-plain.txt"
pdftotext -layout data/contract-rules.pdf "$S/rules-layout.txt"
```

Write the extracts to the scratchpad, never to `outputs/`. Read both files in full.
Then check them against the document map below. If the page count, footer or
section layout differs, the PDF has been replaced. Stop and tell the human
before extracting anything.

How the two modes differ, and what to use each one for:

| | `pdftotext` (plain) | `pdftotext -layout` |
| --- | --- | --- |
| Paragraph text | contiguous; **copy quotes from here** | contiguous but indented |
| Clause numbers | displaced (e.g. `5.1` and `5.1.1` stacked above the text) | on the left of their own text; **use this to see which number owns which text** |
| Table cells (Appendices A–C) | each cell contiguous; copy cell quotes from here | columns interleaved line by line; use it to see which cells form a row |
| Line-end hyphens | removed (`(Call-`/`In)` becomes `(CallIn)`) | kept |

## Document map (Sept 2025 edition, 15 pages)

- Every page ends with the footer `$3inav0bz.docx` and a page number. The footer
  number equals the PDF page number. In `pdftotext` output, pages are separated
  by form feeds (`\f`). A quote never crosses a footer.
- Body clauses `1`–`11` are on pages 1–10. Appendix A (delegated authority by
  contract value, an unlabelled 4-row table) is on page 11. Appendix B (financial
  thresholds and mandatory processes, rows `A`, `B1`, `B2`, `C`, `D`) is on page 12,
  with its footnotes `*`–`****` on page 13. Appendix C (exclusions from
  competition, rows `A`–`F`, then a closing paragraph) is on pages 14–15.
- "Threshold" is defined in 1.4 by reference to the Procurement Legislation and
  the Procurement intranet page. Its values are **not** in the PDF. Appendix B
  footnote `***` also describes the thresholds.
- The numbering is irregular in places: headings that carry a clause number,
  items numbered at the wrong level, sub-clauses whose parent number is missing.
  Keep the printed number and log each irregularity in `notes`.
- Bullets render as the private-use glyph U+F0B7. Both curly (’) and straight (')
  apostrophes occur, sometimes in the same clause.

## Clause ids

| Text | `clause` value |
| --- | --- |
| Numbered body clause | the printed number exactly: `6.16`, `7.4.2`, `5.2.1` |
| Appendix A rows (unlabelled) | `AppA-1` … `AppA-4`, top to bottom |
| Appendix B / C lettered rows | `AppB-B1`, `AppC-E`, … (the printed row label) |
| Appendix footnotes | `AppB-fn1` for `*`, `AppB-fn2` for `**`, `AppB-fn3` for `***`, `AppB-fn4` for `****` |
| Appendix text before / after a table | `AppB-intro`, `AppC-intro`, `AppC-closing` |

Unnumbered bullets belong to the clause above them. Unnumbered section headings
("Advertising", "Sealing") are not clauses.

## Step 2: Decide, clause by clause

Walk the document in order. For each clause or appendix row, ask: **could an
auditor, given the council's records, decide pass or fail for one specific
purchase or contract?** That needs:
1. a trigger: a value band, contract type or circumstance, and
2. something that leaves evidence: a required action (quotes sought, notice
   published, report written, contract sealed) or a named approver.

If both are present, it is a rule. Otherwise it goes in `excluded` with a
one-line reason. Typical exclusions:
- a definition, purpose statement or list of legislation;
- advice only ("should seek advice"), or a duty that leaves no record;
- a heading that carries a number;
- custody and sealing of non-procurement documents;
- a clause too ambiguous to test. Say what is ambiguous; don't guess a reading.

Do not use one exclusion to cover several clauses with different reasons. `covers`
groups sub-clauses only when the parent's reason applies to every one of them.

Splitting:
- **One obligation per rule.** If a table row has an award procedure and a
  separate advertising requirement, write two rules, because they are tested
  from different evidence.
- If one band applies to several contract types, keep one rule. Put the types in
  `scope`. If the band edge is a named threshold that differs by type, the
  parameter carries one value per type (see Parameters).
- If a clause and its sub-clauses form one test (e.g. a list of approval
  conditions), use one rule with `covers` listing the sub-clauses. The quote must
  still sit on one page, so split by page if the list crosses one.

The anti-splitting / disaggregation clause gets `"type": "anti-avoidance"`. The
verifier fails if no rule has that type.

## Step 3: Fill in each rule

```json
{
  "rule_id": "CPR-01",
  "clause": "<printed clause id>",
  "page": 12,
  "type": "threshold",
  "scope": ["goods_services"],
  "condition": "<plain-English trigger, including the band as printed>",
  "band_printed": "<the band text exactly as printed, or null if no value band>",
  "threshold_low": 25000,
  "threshold_low_inclusive": true,
  "threshold_low_param": null,
  "threshold_high": null,
  "threshold_high_inclusive": false,
  "threshold_high_param": "THRESHOLD",
  "required_action": "<what must be done, in plain English>",
  "approver": null,
  "evidence_source": ["procurement_portal"],
  "verbatim_quote": ["<cell text>", "<cell text>"]
}
```

| Field | Rule |
| --- | --- |
| `rule_id` | `CPR-01`, `CPR-02`, … sequential in array order with no gaps. Number them in document order. |
| `clause`, `covers` | see Clause ids. `covers` is optional: the sub-clauses this rule also accounts for. |
| `page` | PDF page the quote is on (1-based) |
| `type` | `threshold` (a value band triggers a process); `approval` (a value band or circumstance triggers a named approver; `approver` must be set); `required-action` (no band, no approver: a must-do); `anti-avoidance` (no splitting) |
| `scope` | non-empty subset of `goods_services`, `works`, `concession`, `light_touch`, or `["all"]` alone when the text applies to every contract type |
| `condition` | the trigger in plain English |
| `band_printed` | the band words copied exactly, e.g. what the row's value cell says. It must appear inside the quote. `null` only when the rule has no value band. |
| `threshold_low/high` | GBP integers as printed: `Above £1,000` → `1000`, never `1001`. `£2.5million` → `2500000`. `null` for an open end or when the bound is a parameter. |
| `*_inclusive` | `true` for "or more", "at least", "up to"; `false` for "above", "over", "more than", "exceeds", "in excess of", "less than", "below". `null` only for an open end. If the wording leaves inclusion unclear, choose the literal reading and add an `interpretation` note. |
| `*_param` | the parameter name when the bound is a named-only threshold ("less than the Threshold"). Set either the integer or the param, never both. |
| `required_action` | what must be done |
| `approver` | who must approve or authorise, as printed ("S.151 Officer", "relevant board"); `null` if none |
| `evidence_source` | non-empty list of where an auditor would find evidence: `spend_data` (Expenditure over £500 payments), `contract_notices` (Contracts Finder export), `procurement_portal` (RFQ/ITT/tender records), `decision_records` (delegated decisions, board/Executive reports, waivers and exception reports), `contract_documents` (signed or sealed contracts, bonds, insurance, risk assessments), `contract_register` (the council's own contract register) |
| `verbatim_quote` | see Quotes |

Amounts printed with pence: a band like "more than £24,999.99" cannot be an
integer as printed. Record its whole-pound equivalent, `25000` with `inclusive:
true`. Keep `band_printed` exactly as printed, and add an `interpretation` note
naming the clause. The verifier allows this conversion and nothing else.

## Parameters

Each threshold that the PDF names without a value becomes one top-level
parameter:

```json
"parameters": {
  "THRESHOLD": {
    "values": {"goods_services": null, "works": null, "concession": null, "light_touch": null},
    "printed_as": ["Threshold"],
    "defined_in": [{"clause": "<id>", "page": 1, "verbatim_quote": "<exact text>"}],
    "description": "<what it is and where the PDF says the value is published>"
  }
}
```

- `values` has one key per contract type the PDF distinguishes, or one key `all`.
  Every value is `null`. The verifier rejects any filled-in value. Values are
  supplied later by the auditor from the source the PDF names, never from memory.
- `printed_as`: the word(s) used in band text. The verifier checks that each rule
  using the parameter has one of these in its `band_printed`.
- `defined_in`: every place that defines or describes the parameter, each with a
  verbatim quote. If two definitions disagree (for example, different lists of
  contract types), add a `contradiction` note.
- A rule that uses a parameter must have a `values` key for every type in its
  `scope`.

## Quotes

- Copy from the **plain** extract. The verifier collapses whitespace and line
  breaks and ignores bullet glyphs. Every other character must match exactly:
  curly vs straight apostrophes, en/em dashes, `[]` placeholders, typos and
  grammatical slips ("such decision have been").
- Quote the clause text only. Leave out the clause number, the bullet glyph and
  the footer. Never use `...` or `…`. If you need two separate passages, use a
  list.
- A string quote is one contiguous passage on `page`. A **list** is for table
  rows and for parent-plus-sub-clause rules: each element is one contiguous
  passage of at least 10 characters, and all elements are on `page`.
- Quote enough to show the trigger and the action (and approver, if set). For a
  table row, that usually means the band cell plus the relevant action cell.
- For a line-end hyphen the plain extract dropped (`CallIn`), the printed form
  (`Call-In`) also matches.

## Excluded and notes

```json
"excluded": [
  {"clause": "1.1", "page": 1, "reason": "<one line: why it is not testable>"},
  {"clause": "10.7", "covers": ["10.7.1", "10.7.2"], "page": 8, "reason": "<one line>"}
],
"notes": [
  {"kind": "gap", "clauses": ["AppB-A", "AppB-B1"], "issue": "<what is wrong and why it matters for testing>"}
]
```

- `excluded[].page` is the page where the clause number (or row label) is printed.
  `reason` is one line of at most 250 characters.
- `notes[].kind` is `contradiction` (two provisions disagree), `gap` (a value or
  case no provision covers), `drafting` (numbering errors, placeholders like
  `Parts []`, typos, references to documents outside the PDF), or
  `interpretation` (a reading you had to choose, including the pence conversion).
- Look specifically for: band edges where an exact amount falls in no band or in
  two; a value band that the document states differently in two places (body
  vs appendix, label vs cell text); bands that may be empty depending on how a
  named threshold compares with a printed amount (state it conditionally, since
  the threshold's value is unknown); different lists of contract types for the
  same threshold; "should" in one place and "must" in another for the same
  duty; misnumbered clauses.
- Record each problem. Don't resolve it. A rule affected by a note is still
  extracted as printed.

## Step 4: Write and verify

Write the top-level object to `outputs/rules.json` (replace any existing file and
mention that you did):

```json
{
  "source": {"file": "data/contract-rules.pdf", "sha256": "<sha256 of the PDF>", "pages": 15, "title": "<as printed>"},
  "parameters": {},
  "rules": [],
  "excluded": [],
  "notes": []
}
```

Get the hash with `shasum -a 256 data/contract-rules.pdf`. Then run:

```bash
.venv/bin/python .claude/skills/extract-rules/verify_quotes.py outputs/rules.json --pdf data/contract-rules.pdf
```

The verifier checks:
- the schema and enums;
- sequential `rule_id`s;
- that parameters are declared, used, cover each rule's scope and are all `null`;
- that every quote appears on its stated page, and every `band_printed` sits
  inside its quote and agrees with the integer bounds;
- that every clause number and lettered appendix row detected in the PDF is in
  `rules` or `excluded`;
- that no clause id is invented;
- that the PDF hash and page count match.

Fix every error it reports and re-run until it exits 0. A failing quote is
fixed by copying the text again from the plain extract, never by paraphrasing.
Never edit the verifier to make a check pass. If you believe the verifier is
wrong, stop and report it to the human.

Appendix A rows, the Appendix B footnotes and the `-intro` / `-closing`
paragraphs have no printed labels, so the verifier cannot detect them. Check by
hand that each one is in `rules` or `excluded`.

## Step 5: Report to the human (under 200 words)

- counts: rules by type, exclusions, notes by kind;
- the parameters whose values the auditor must supply before spend analysis
  can use them, and the source the PDF names for each;
- the notes most likely to affect testing (band gaps, contradictions);
- the verifier result, quoted as printed.
