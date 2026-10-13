#!/usr/bin/env python3
"""Tests for .claude/skills/risk-assessment/build_register.py.

    .venv/bin/python scripts/tests/test_build_register.py

The fixture risk-ratings-good-broken.json has one good risk (R-01: rubric
row S3 on the split_purchases quote-threshold tier, every citation and
placeholder resolving) and one broken risk (R-02: a rule that does not exist,
a metric path that does not resolve, and an impact cited only on placement
figures). R-01 must be rated and R-02 excluded with those reasons. Variants
of the fixture then exercise the error, warning, decision and revision rules.
Runs against the real outputs/analytics.json, history.json and rules.json,
read-only; everything is written to a temporary directory.
"""

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUILDER = REPO / ".claude/skills/risk-assessment/build_register.py"
FIXTURE = json.loads((REPO / "scripts/tests/fixtures/risk-ratings-good-broken.json").read_text())
SIGNAL_1000 = "$.tests.split_purchases.by_threshold[threshold=1000].by_tag.general_procurement.count"

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)
        if detail:
            print("     " + detail[:1500].replace("\n", "\n     "))


def run(out, ratings):
    p = out / "risk-ratings.json"
    p.write_text(json.dumps(ratings, indent=1, ensure_ascii=False))
    r = subprocess.run([sys.executable, "-I", str(BUILDER), "--root", str(REPO), "--out-dir", str(out)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def set_decision(out, item, decision, comment="", applied=None):
    path = out / "auditor-comments.md"
    lines, header = path.read_text().splitlines(), None
    for i, line in enumerate(lines):
        if line.startswith("| Risk |") or line.startswith("| Item |"):
            header = [c.strip().lower() for c in line.strip("|").split("|")]
        elif header and line.startswith(f"| {item} |"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            cells[header.index("decision")] = decision
            cells[header.index("comment")] = comment
            if applied is not None:
                cells[header.index("applied")] = applied
            lines[i] = "| " + " | ".join(cells) + " |"
            break
    else:
        raise AssertionError(f"no row {item} in auditor-comments.md")
    path.write_text("\n".join(lines) + "\n")


def r01(ratings):
    return next(r for r in ratings["risks"] if r["risk_id"] == "R-01")


def fresh(ratings=None):
    out = Path(tempfile.mkdtemp(prefix="risk-reg-"))
    code, log = run(out, ratings or FIXTURE)
    return out, code, log


# ------------------------------------------------------------ the fixture itself
out, code, log = fresh()
reg = (out / "risk-register.md").read_text() if (out / "risk-register.md").exists() else ""
com = (out / "auditor-comments.md").read_text() if (out / "auditor-comments.md").exists() else ""
check("fixture builds (exit 0)", code == 0, log)
check("R-01 rated: likelihood 4 Almost Certain, impact 3 Medium, score 12, High / Medium High (Amber), marked ‡",
      re.search(r"\| R-01 \| .* \| 4 Almost Certain \| 3 Medium \| 12 ‡ \| High \| Medium High \(Amber\) \|", reg), reg[:3000])
check("R-01 rubric row S3 from the quote-threshold tier signal", "Rubric row S3 (signal $.tests.split_purchases.by_threshold[threshold=25000]" in reg)
check("placeholders filled from analytics.json, none left", "{{" not in reg and "within 30 days" in reg)
check("R-02 excluded, not rated", "**R-02 Spend after contract expiry**" in reg and "| R-02 |" not in reg.split("## Risks")[0])
check("R-02 reasons: missing rule, unresolvable metric, no primary citation for likelihood and impact",
      all(s in reg for s in ["rule CPR-99 is not in rules.json", "expired_notice_scan", "likelihood.justification: no resolvable primary citation",
                             "impact.justification: no resolvable primary citation"]))
check("placement metric cited as context only", "placement tag" in reg)
check("conflicting CRR threshold: Table 4 used, Figure 4 marked, cites DIS-04",
      re.search(r"\*\*Used:\*\* Table 4.*\*\*Marked:\*\* Figure 4.*DIS-04", reg))
check("band-name, impact-numbering and financial-overlap conflicts stated with their history items",
      all(re.search(p, reg) for p in [r"Figure 1's \"High\".*DIS-03", r"Medium = 3.*DIS-01", r"overlap.*DIS-02"]))
check("£1,000 split tier stated as noise in the header", "split_purchases tier at £1,000 cannot raise a rating on its own" in reg)
check("likelihood rubric in the header", "| S3 | Signal count 20 or more | 4 Almost Certain |" in reg)
check("Noted, not rated lists AUD-16", re.search(r"\| AUD-16 \| Personal Budgets \(Direct Payments\).*\| Limited Assurance \|", reg))
check("register ends with Auditor decisions", reg.rstrip().split("\n## ")[-1].startswith("Auditor decisions"))
check("auditor-comments.md: R-01 row with blank Decision and Comment, no R-02 row, AUD-16 row",
      re.search(r"\| R-01 \|.*\| Medium High \(Amber\) \|  \|  \|  \|", com) and "| R-02 |" not in com and "| AUD-16 |" in com, com)
check("snapshot r0 written", (out / "register-snapshots/r0.json").exists())

# ------------------------------------------------------------ decisions are kept
set_decision(out, "R-01", "Approve", "Agreed")
set_decision(out, "AUD-16", "Leave out", "Covered by the People audit plan")
code, log = run(out, FIXTURE)
com = (out / "auditor-comments.md").read_text()
check("rebuild of unchanged r0 keeps the decisions", code == 0 and "| Approve | Agreed |" in com
      and "| Leave out | Covered by the People audit plan |" in com, log + com)
check("register Auditor decisions mirrors them", "| R-01 | Approve | Agreed |" in (out / "risk-register.md").read_text())

changed = copy.deepcopy(FIXTURE)
r01(changed)["evidence"] += " Also see the duplicates list."
code, log = run(out, changed)
check("r0 changed after decisions without a revision block fails", code == 1 and "changes after the gate go in a revision block" in log, log)

# ------------------------------------------------------------ errors in the agent's judgments
bad = copy.deepcopy(FIXTURE)
r01(bad)["likelihood"]["repeat_uplift"] = {"history": "AUD-01", "justification": "Contract Letting again."}
r01(bad)["likelihood"]["score"] = 5
code, log = fresh(bad)[1:]
check("uplift citing a Reasonable Assurance audit fails", code == 1 and "is not adverse" in log, log)

bad = copy.deepcopy(FIXTURE)
r01(bad)["likelihood"]["score"] = 3
code, log = fresh(bad)[1:]
check("likelihood score that departs from the rubric fails", code == 1 and "rubric row S3 (base 4) gives 4" in log, log)

bad = copy.deepcopy(FIXTURE)
r01(bad)["likelihood"]["signal"] = SIGNAL_1000
r01(bad)["likelihood"]["justification"] += f" [metric:{SIGNAL_1000}]"
code, log = fresh(bad)[1:]
check("signal on the £1,000 split tier fails (noise by construction)", code == 1 and "flags by construction" in log, log)

warn = copy.deepcopy(FIXTURE)
r01(warn)["evidence"] += " Roughly £3.2m in total."
code, log = fresh(warn)[1:]
check("typed figure in prose is a warning, not a failure", code == 0 and "R-01.evidence: figure typed in prose (£3.2m" in log, log)

# ------------------------------------------------------------ revision after the gate
def gated(r01_decision, r01_comment="", aud16="Leave out"):
    out, code, log = fresh()
    assert code == 0, log
    set_decision(out, "R-01", r01_decision, r01_comment)
    set_decision(out, "AUD-16", aud16)
    return out


out = gated("Amend", "Lower likelihood to 3: the groups overlap across tiers")
rev = copy.deepcopy(FIXTURE)
r01(rev)["likelihood"]["score"] = 3
r01(rev)["likelihood"]["justification"] += " The auditor judges the groups to overlap across tiers."
rev["revision"] = {"number": 1, "changes": [{"target": "R-01", "decision_ref": "R-01",
                                             "fields": ["likelihood.score", "likelihood.justification"],
                                             "summary": "Likelihood lowered at the auditor's request."}]}
code, log = run(out, rev)
reg = (out / "risk-register.md").read_text()
com = (out / "auditor-comments.md").read_text()
check("revision r1 applying an Amend builds", code == 0, log)
check("revision header names what changed and the decision behind it",
      "## Revision r1" in reg and "**R-01**: likelihood.justification, likelihood.score." in reg and "R-01 Amend (\"Lower likelihood" in reg, reg[:2500])
check("auditor override marked with the rubric value",
      "**Auditor override:** the rubric gives 4 Almost Certain" in reg and "(auditor override)" in reg)
check("Applied = r1 in auditor-comments.md", re.search(r"\| R-01 \|.*\| Amend \| Lower likelihood.*\| r1 \|", com), com)

out = gated("Amend", "Lower likelihood to 3")
rev2 = copy.deepcopy(FIXTURE)
rev2["revision"] = {"number": 1, "changes": []}
code, log = run(out, rev2)
check("Amend with no change fails: decision left unapplied", code == 1 and "R-01: Amend decision left unapplied" in log, log)

out = gated("Approve", "Agreed")
rev3 = copy.deepcopy(FIXTURE)
r01(rev3)["evidence"] += " Also see the duplicates list."
rev3["revision"] = {"number": 1, "changes": []}
code, log = run(out, rev3)
check("change to an approved risk fails: not asked for", code == 1 and "R-01: evidence changed but no revision change declares it" in log, log)

rev3["revision"]["changes"] = [{"target": "R-01", "decision_ref": "R-01", "fields": ["evidence"], "summary": "Added a pointer."}]
code, log = run(out, rev3)
check("declaring that change against an Approve still fails", code == 1 and "a change the auditor did not ask for" in log, log)

undecided = gated("Approve")
(undecided / "auditor-comments.md").write_text((undecided / "auditor-comments.md").read_text().replace("| Leave out |", "|  |"))
rev4 = copy.deepcopy(FIXTURE)
rev4["revision"] = {"number": 1, "changes": []}
code, log = run(undecided, rev4)
check("revision with an undecided row fails", code == 1 and "AUD-16 has no decision" in log, log)

out = gated("Approve", "Agreed", aud16="Add to scope")
add = copy.deepcopy(FIXTURE)
add["noted_not_rated"] = []
add["risks"].append({
    "risk_id": "R-03", "title": "Personal budget payments outside the spend tests",
    "description": "Direct Payments are excluded from the spend tests; the last audit gave Limited Assurance [history:AUD-16].",
    "likelihood": {"score": 2, "rubric_row": "NT", "signal": None,
                   "justification": "No test measures this area; the audit opinion is the only evidence [history:AUD-16].",
                   "repeat_uplift": None},
    "impact": {"score": 2, "category": "Compliance (litigation, regulatory, contract)",
               "justification": "Every purchase needs written evidence [rule:CPR-30]."},
    "evidence": "Audit opinion [history:AUD-16].", "proposed_focus": "Follow up the agreed actions from that audit."})
add["revision"] = {"number": 1, "changes": [
    {"target": "AUD-16", "decision_ref": "AUD-16", "fields": ["removed"], "summary": "Moved into scope."},
    {"target": "R-03", "decision_ref": "AUD-16", "fields": ["added"], "summary": "Rated at the auditor's request."}]}
code, log = run(out, add)
reg = (out / "risk-register.md").read_text()
com = (out / "auditor-comments.md").read_text()
check("Add to scope: noted item becomes a rated risk in r1", code == 0 and "| R-03 |" in reg
      and "**AUD-16**: removed." in reg and "**R-03**: added." in reg, log)
check("Add to scope decision kept with Applied = r1", re.search(r"\| AUD-16 \|.*\| Add to scope \|.*\| r1 \|", com), com)

print()
print(f"{len(failures)} failure(s)" if failures else "all checks passed")
sys.exit(1 if failures else 0)
