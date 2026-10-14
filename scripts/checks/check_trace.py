#!/usr/bin/env python3
"""QA traceability check: rule -> risk -> control -> test, scope decisions, and the challenge record.

    .venv/bin/python -I scripts/checks/check_trace.py            during the team run
    .venv/bin/python -I scripts/checks/check_trace.py --final    before review.md: also challenges.md

The scope is computed here from outputs/auditor-comments.md and
outputs/risk-ratings.json (in scope: Approve or Amend, not rejected).

1. Rules: every rule in rules.json is cited ([rule:ID]) by an in-scope risk's
   prose in risk-ratings.json, a control or a test step in audit-plan.json,
   or listed in rules_not_tested with a reason; never both; and the Rule
   coverage table of risk-control-matrix.md agrees, one row per rule.
2. Risks: every in-scope risk is planned, has at least one control, every
   control is tested by a test of the same risk, and the risk, its controls
   and its tests appear in risk-control-matrix.md, audit-program.md and the
   memo's scope table. Nothing out of scope is planned or rendered.
3. High risks (Figure 1 label High or Extreme, or Table 4 band Medium High or
   Extreme, from history.json): each is in scope, or rejected with the
   auditor's comment and listed in the memo's out-of-scope table.
4. Every rejected risk and every noted item left out has its decision and a
   comment in auditor-comments.md, and the memo's out-of-scope table carries
   them.
5. --final only: outputs/challenges.md exists; every challenge row cites
   evidence that resolves (a rule, a metric, a history item, or an
   auditor-comments.md row) and none is open.

Exit 0 when everything checked passes, 1 otherwise.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_lib as Q  # noqa: E402

NAME = "check_trace"


# ---------------------------------------------------------------- rules

def check_rules(rules, ratings, plan, in_scope, rcm, res):
    rule_ids = [r.get("rule_id") for r in rules.get("rules", [])]
    known = set(rule_ids)
    cited = {}

    def cite(text, where):
        for rid in Q.rule_tags(text or ""):
            if rid not in known:
                res.fail(f"{where} cites rule {rid}, which is not in rules.json")
                continue
            cited.setdefault(rid, [])
            if where not in cited[rid]:
                cited[rid].append(where)

    risks = {r["risk_id"]: r for r in ratings.get("risks", [])}
    for rid in in_scope:
        for f in Q.RISK_PROSE_FIELDS:
            v = Q.get_field(risks.get(rid, {}), f)
            if isinstance(v, str):
                cite(v, rid)
    for r in plan.get("risks", []):
        if r.get("risk_id") not in in_scope:
            continue
        for c in r.get("controls", []):
            cite(c.get("control"), c.get("control_id"))
        for t in r.get("tests", []):
            cite(t.get("step"), t.get("test_id"))

    not_tested = {}
    for x in plan.get("rules_not_tested", []):
        rid, reason = x.get("rule_id"), (x.get("reason") or "").strip()
        if rid not in known:
            res.fail(f"rules_not_tested lists {rid}, which is not in rules.json")
        elif rid in not_tested:
            res.fail(f"rules_not_tested lists {rid} twice")
        elif not reason:
            res.fail(f"rules_not_tested lists {rid} with no reason")
        not_tested[rid] = reason

    for rid in rule_ids:
        res.count("rules")
        if rid in cited and rid in not_tested:
            res.fail(f"{rid} is cited by {', '.join(cited[rid])} and also listed as not tested")
        elif rid not in cited and rid not in not_tested:
            res.fail(f"{rid} is neither cited by an in-scope risk, a control or a test nor listed as not tested "
                     "with a reason")

    if rcm is None:
        return
    rows, _ = Q.find_table(rcm, "Rule", heading="Rule coverage")
    if rows is None:
        res.fail("risk-control-matrix.md has no Rule coverage table")
        return
    seen = {}
    for ln, row in rows:
        rid = row.get("Rule", "")
        if rid in seen:
            res.fail(f"risk-control-matrix.md line {ln}: {rid} has a second row in Rule coverage")
        seen[rid] = row
        if rid not in known:
            res.fail(f"risk-control-matrix.md line {ln}: Rule coverage row for {rid}, which is not in rules.json")
    for rid in rule_ids:
        row = seen.get(rid)
        if row is None:
            res.fail(f"risk-control-matrix.md: Rule coverage has no row for {rid}")
            continue
        traced = [x.strip() for x in row.get("Traced to", "").split(",") if x.strip()]
        reason = row.get("Not tested: reason", "").strip()
        if rid in cited and sorted(traced) != sorted(cited[rid]):
            res.fail(f"risk-control-matrix.md: {rid} traced to {', '.join(traced) or 'nothing'}, but it is cited by "
                     f"{', '.join(cited[rid])}")
        if rid not in cited and traced:
            res.fail(f"risk-control-matrix.md: {rid} traced to {', '.join(traced)}, but nothing in scope cites it")
        if rid in not_tested and not reason:
            res.fail(f"risk-control-matrix.md: {rid} is not tested but its row gives no reason")
        if rid not in not_tested and reason:
            res.fail(f"risk-control-matrix.md: {rid} has a not-tested reason but is not in rules_not_tested")


# ---------------------------------------------------------------- risks

def check_risks(plan, in_scope, out_ids, rcm, prog, memo, res):
    planned = {}
    for r in plan.get("risks", []):
        rid = r.get("risk_id")
        if rid in planned:
            res.fail(f"audit-plan.json plans {rid} twice")
        planned[rid] = r
        if rid not in in_scope:
            res.fail(f"audit-plan.json plans {rid}, which is not in the approved scope")

    rcm_rows, _ = Q.find_table(rcm or "", "Risk")
    rcm_rows = rcm_rows or []
    if rcm is not None and not rcm_rows:
        res.fail("risk-control-matrix.md has no risk-control table")
    prog_secs = Q.md_sections(prog or "", 2)
    prog_by_risk = {h.split()[0]: body for h, (_, body) in prog_secs.items() if re.match(r"R-\d+\b", h)}
    memo_rows, _ = Q.find_table(memo or "", "Risk", heading="Scope")
    memo_risks = {row.get("Risk") for _, row in (memo_rows or [])}
    if memo is not None and memo_rows is None:
        res.fail("planning-memo.md has no scope table")

    for rid in in_scope:
        res.count("in-scope risks")
        r = planned.get(rid)
        if r is None:
            res.fail(f"{rid} is in the approved scope but not in audit-plan.json")
            continue
        controls = {c.get("control_id"): c for c in r.get("controls", [])}
        tests = r.get("tests", [])
        if not controls:
            res.fail(f"{rid} has no control")
        covered = {}
        for t in tests:
            res.count("tests")
            tc = t.get("controls") or []
            if not tc:
                res.fail(f"{rid} {t.get('test_id')} names no control")
            for c in tc:
                if c not in controls:
                    res.fail(f"{rid} {t.get('test_id')} tests {c}, which is not a control of {rid}")
                covered.setdefault(c, []).append(t.get("test_id"))
        for cid in controls:
            res.count("controls")
            if cid not in covered:
                res.fail(f"{rid} {cid} has no test")

        if rcm is not None:
            mine = [row for _, row in rcm_rows if row.get("Risk", "").split(" ")[0] == rid]
            if not mine:
                res.fail(f"{rid} does not appear in risk-control-matrix.md")
            by_c = {row.get("Control"): row for row in mine}
            for cid in controls:
                row = by_c.get(cid)
                if row is None:
                    res.fail(f"risk-control-matrix.md has no row for {rid} {cid}")
                    continue
                shown = sorted(x.strip() for x in row.get("Tests", "").split(",") if x.strip())
                if shown != sorted(covered.get(cid, [])):
                    res.fail(f"risk-control-matrix.md: {rid} {cid} lists tests {', '.join(shown) or 'none'}, "
                             f"audit-plan.json {', '.join(sorted(covered.get(cid, []))) or 'none'}")
            for cid in by_c:
                if cid not in controls:
                    res.fail(f"risk-control-matrix.md: {rid} row for {cid}, which is not a control of {rid}")
        if prog is not None:
            body = prog_by_risk.get(rid)
            if body is None:
                res.fail(f"{rid} does not appear in audit-program.md")
            else:
                for cid in controls:
                    if not re.search(rf"^- \*\*{re.escape(cid)}\*\*", body, re.M):
                        res.fail(f"audit-program.md: {rid} section does not list control {cid}")
                for t in tests:
                    if not re.search(rf"^### {re.escape(t.get('test_id', ''))}\b", body, re.M):
                        res.fail(f"audit-program.md: {rid} section has no test {t.get('test_id')}")
        if memo is not None and rid not in memo_risks:
            res.fail(f"{rid} is not in planning-memo.md's scope table")

    for rid in out_ids:
        if rcm is not None and any(row.get("Risk", "").split(" ")[0] == rid for _, row in rcm_rows):
            res.fail(f"{rid} is out of scope but appears in risk-control-matrix.md")
        if rid in prog_by_risk:
            res.fail(f"{rid} is out of scope but has a section in audit-program.md")
        if rid in memo_risks:
            res.fail(f"{rid} is out of scope but is in planning-memo.md's scope table")


# ---------------------------------------------------------------- scope decisions

def scoring(history, res):
    """(label(l, i), band(score)) from the council's matrix and bands in history.json."""
    m = (history or {}).get("risk_scoring_method") or {}
    rows = {r.get("impact"): r for r in (m.get("matrix") or {}).get("rows", [])}
    bands = []
    for b in m.get("bands", []):
        s = (b.get("score_printed") or "").strip()
        mm = re.fullmatch(r"(?i)up\s+to\s*(\d+)", s) or re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", s)
        if not mm:
            res.fail(f"history.json band {b.get('level')!r} score {s!r} cannot be read as a range")
            continue
        lo, hi = (1, int(mm.group(1))) if len(mm.groups()) == 1 else (int(mm.group(1)), int(mm.group(2)))
        bands.append((lo, hi, b.get("level")))

    def label(l, i):
        r = rows.get(i)
        return r["labels"][l - 1] if r and len(r.get("labels", [])) >= l else None

    def band(score):
        return next((lvl for lo, hi, lvl in bands if lo <= score <= hi), None)

    if m.get("status") != "found" or len(rows) != 5:
        res.fail("history.json holds no usable 5x5 matrix, so High risks cannot be identified")
    return label, band


def check_scope(ratings, decisions, history, in_scope, rejected, left_out, undecided, memo, res):
    for k in undecided:
        res.fail(f"{k} has no decision in auditor-comments.md")
    out_rows, _ = Q.find_table(memo or "", "Item", heading="Out of scope")
    out_rows = {row.get("Item"): (ln, row) for ln, row in (out_rows or [])}
    if memo is not None and not out_rows and (rejected or left_out):
        res.fail("planning-memo.md has no out-of-scope table")

    def recorded(k, want):
        d = decisions.get(k, {})
        ok = True
        if d.get("decision") != want:
            res.fail(f"{k}: decision in auditor-comments.md is {d.get('decision') or 'blank'}, expected {want}")
            ok = False
        if not d.get("comment", "").strip():
            res.fail(f"{k}: {want} has no auditor comment in auditor-comments.md")
            ok = False
        if memo is not None:
            ln_row = out_rows.get(k)
            if ln_row is None:
                res.fail(f"{k} ({want}) is not in planning-memo.md's out-of-scope table")
                ok = False
            else:
                ln, row = ln_row
                if row.get("Decision") != d.get("decision") or row.get("Auditor's comment", "") != d.get("comment", ""):
                    res.fail(f"planning-memo.md line {ln}: {k} decision or comment differs from auditor-comments.md")
                    ok = False
        return ok

    for k in rejected:
        res.count("rejected risks")
        recorded(k, "Reject")
    for k in left_out:
        res.count("noted items left out")
        recorded(k, "Leave out")

    label, band = scoring(history, res)
    for r in ratings.get("risks", []):
        try:
            l, i = int(r["likelihood"]["score"]), int(r["impact"]["score"])
        except (KeyError, TypeError, ValueError):
            res.fail(f"{r.get('risk_id')}: likelihood or impact score missing in risk-ratings.json")
            continue
        lab, bnd = label(l, i), band(l * i)
        if lab not in Q.HIGH_LABELS and bnd not in Q.HIGH_BANDS:
            continue
        res.count("High risks")
        rid = r["risk_id"]
        if rid in in_scope:
            continue
        if rid not in rejected:
            res.fail(f"{rid} is High (score {l * i}, {lab}, {bnd}) but neither in scope nor rejected with a reason")
        # a rejected High risk's reason is checked with the rejected risks above


# ---------------------------------------------------------------- challenges

def check_challenges(root, rules, analytics, history, decisions, res):
    text = Q.read_text(root / "outputs/challenges.md", res, "challenges.md")
    if text is None:
        return
    rows, header = Q.find_table(text, "#")
    if rows is None:
        res.fail("challenges.md has no challenge table (header starting '| # |')")
        return
    for col in ("Citation", "Status"):
        if col not in header:
            res.fail(f"challenges.md: the challenge table has no {col} column")
            return
    rule_ids = {r.get("rule_id") for r in (rules or {}).get("rules", [])}
    hist_ids = Q.history_ids(history)
    for ln, row in rows:
        res.count("challenges")
        n = row.get("#", "?")
        status = row.get("Status", "").strip().lower().strip("*_ ")
        if status == "open":
            res.fail(f"challenges.md line {ln}: #{n} is open")
        elif status not in Q.CLOSED_STATUSES:
            res.fail(f"challenges.md line {ln}: #{n} status {row.get('Status')!r} is not one of "
                     f"{', '.join(Q.CLOSED_STATUSES)}")
        cell = row.get("Citation", "")
        good, bad = [], []
        for kind, ref in Q.scan_citations(cell):
            if ref is None:
                bad.append(f"an unclosed {kind} citation")
            elif kind == "rule":
                (good if ref in rule_ids else bad).append(f"rule {ref}")
            elif kind == "history":
                (good if ref in hist_ids else bad).append(f"history {ref}")
            else:
                try:
                    Q.resolve_path(analytics or {}, ref)
                    good.append(f"metric {ref}")
                except ValueError as e:
                    bad.append(f"metric {ref} ({e})")
        if "auditor-comments" in cell:
            ids = re.findall(r"\b(?:R|AUD)-\d+\b", cell)
            hits = [k for k in ids if k in decisions]
            (good if hits else bad).append("auditor-comments.md row " + (", ".join(ids) or "(no row named)"))
        for b in bad:
            res.fail(f"challenges.md line {ln}: #{n} citation {b} does not resolve")
        if not good:
            res.fail(f"challenges.md line {ln}: #{n} cites no evidence (a rule, metric, history item or "
                     "auditor-comments.md row)")


# ---------------------------------------------------------------- main

def run(root=Q.ROOT_DEFAULT, final=False):
    root = Path(root).resolve()
    out = root / "outputs"
    res = Q.Result(NAME)
    rules = Q.load_json(out / "rules.json", res, "rules.json")
    ratings = Q.load_json(out / "risk-ratings.json", res, "risk-ratings.json")
    history = Q.load_json(out / "history.json", res, "history.json")
    plan = Q.load_json(out / "audit-plan.json", res, "audit-plan.json")
    comments = Q.read_text(out / "auditor-comments.md", res, "auditor-comments.md")
    memo = Q.read_text(out / "planning-memo.md", res, "planning-memo.md")
    rcm = Q.read_text(out / "risk-control-matrix.md", res, "risk-control-matrix.md")
    prog = Q.read_text(out / "audit-program.md", res, "audit-program.md")
    if ratings is None or comments is None:
        return res
    decisions = Q.parse_comments(comments)
    in_scope, rejected, left_out, undecided = Q.scope(ratings, decisions)
    out_ids = [r["risk_id"] for r in ratings.get("risks", []) if r["risk_id"] not in in_scope]

    if rules is not None and plan is not None:
        check_rules(rules, ratings, plan, in_scope, rcm, res)
    if plan is not None:
        check_risks(plan, in_scope, out_ids, rcm, prog, memo, res)
    check_scope(ratings, decisions, history, in_scope, rejected, left_out, undecided, memo, res)
    if final:
        analytics = Q.load_json(out / "analytics.json", res, "analytics.json")
        check_challenges(root, rules, analytics, history, decisions, res)
    else:
        res.notes.append("challenges.md not checked: it is checked in the final run (--final)")
    return res


def main(argv=None):
    a = Q.parse_args(__doc__, argv, final=True)
    return run(a.root, a.final).print()


if __name__ == "__main__":
    sys.exit(main())
