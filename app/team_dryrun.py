"""Dry runs of the team stage: scripted planner and challenger replies, no model calls, no cost.

    .venv/bin/python -m app.team_dryrun                 every scenario
    .venv/bin/python -m app.team_dryrun round2 cost_cap  some of them
    .venv/bin/python -m app.team_dryrun --list

Each scenario runs app.team.run_team in its own throwaway workspace,
WORK_DIR/dry-runs/<stamp>/<scenario>/workspace, seeded from the repo's
committed outputs like WORK_DIR itself. Everything except the two model calls
is real: the gate and the builds are build_pack.py, QA is run_checks.py, and
the fingerprint, ownership and cost checks are the harness's. A scripted
planner reply edits outputs/audit-plan.json and runs build_pack.py, as the
real planner would; a scripted cost above the budget left is cut off the way
the SDK's max_budget_usd cuts a session off.

Next to each workspace: events.json (every event), transcript.md (the
protocol messages in order), and the challenges.md and review.md the run
wrote.
"""

import argparse
import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import runs
from .settings import load_config, load_secrets, work_dir
from .team import BUILD, PLAN, Reply, run_team
from .workspace import Workspace

# ---------------------------------------------------------------- scripted agents


@dataclass
class Step:
    role: str
    reply: dict
    cost: float = 0.05
    edit: Callable | None = None     # edit(plan dict): the planner's change to audit-plan.json, then a build
    action: Callable | None = None   # action(root): anything else the agent does to the workspace


class ScriptedAgents:
    """Stands in for SdkTeamAgents: each call takes the next step of the script, in order."""

    def __init__(self, root, steps):
        self.root = Path(root)
        self.steps = list(steps)
        self.calls = []

    async def __call__(self, call, emit):
        self.calls.append(call)
        if not self.steps:
            raise AssertionError(f"the script has no step left for the {call.role} call ({call.purpose})")
        step = self.steps.pop(0)
        if step.role != call.role:
            raise AssertionError(f"the script expected a {step.role} call; the harness made a {call.role} call "
                                 f"({call.purpose})")
        emit({"type": "text", "agent": "main", "text": f"[dry run] scripted {call.role} reply: {call.purpose}"})
        if step.cost > call.max_budget_usd:  # what max_budget_usd does to a real session
            return Reply(None, round(call.max_budget_usd + 0.01, 4), "error_max_budget_usd", True)
        if step.action:
            await asyncio.to_thread(step.action, self.root)
        reply = json.loads(json.dumps(step.reply))
        if step.edit or (call.role == "planner" and call.purpose.startswith("build") and reply["status"] == "built"):
            if step.edit:
                p = self.root / PLAN
                plan = json.loads(p.read_text(encoding="utf-8"))
                step.edit(plan)
                p.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            emit({"type": "tool_use", "agent": "main", "name": "Bash",
                  "input": {"command": f".venv/bin/python -I {BUILD}"}})
            r = await asyncio.to_thread(subprocess.run, [str(self.root / ".venv/bin/python"), "-I", BUILD],
                                        cwd=self.root, capture_output=True, text=True)
            out = (r.stdout + r.stderr).strip()
            emit({"type": "tool_result", "agent": "main", "is_error": r.returncode != 0, "content": out[:3000]})
            reply["ok_line"] = next((l for l in out.splitlines() if l.startswith("OK: ")), "")
        return Reply(reply, step.cost)


def planner(changes=(), responses=(), qa=(), cost=0.30, edit=None, action=None, blocked=""):
    return Step("planner", {
        "status": "blocked" if blocked else "built", "ok_line": "",
        "changes": [{"change": c, "because": b} for c, b in changes],
        "responses": [{"n": n, "answer": a, "detail": d} for n, a, d in responses],
        "qa_responses": [{"n": n, "answer": a, "detail": d} for n, a, d in qa],
        "blocked_reason": blocked}, cost, edit, action)


def challenger(challenges=(), verified=(), cost=0.05, action=None):
    return Step("challenger", {"challenges": [dict(c) for c in challenges],
                               "verified": [{"n": n, "found": f, "note": note} for n, f, note in verified]},
                cost, None, action)


# ---------------------------------------------------------------- plan edits (each builds; checked against the real tools)

BAND = "{{$.tests.threshold_clustering.by_threshold[0].band_below}}"
BAND_SENTENCE = f" The clustering band tested below the lowest threshold is {BAND}."


def test_of(plan, tid):
    return next(t for r in plan["risks"] for t in r["tests"] if t["test_id"] == tid)


def add_band(plan):
    """Builds (the placeholder resolves) but fails check_numbers: the band string prints 900.00."""
    plan["memo"]["limitations"] += BAND_SENTENCE


def reword_band(plan):
    """A fix that misses the point: the wording changes, the placeholder stays."""
    lim = plan["memo"]["limitations"]
    a, b = f" is {BAND}", f" reads {BAND}"
    plan["memo"]["limitations"] = lim.replace(a, b) if a in lim else lim.replace(b, a)


def remove_band(plan):
    plan["memo"]["limitations"] = plan["memo"]["limitations"].replace(BAND_SENTENCE, "")


def accept_t06(plan):
    t = test_of(plan, "T-06")
    t["pbc"].append("PBC-03")
    t["step"] += " Confirm against the contracts register whether a contract covers the repeated payment [rule:CPR-30]."


def accept_t05(plan):
    test_of(plan, "T-05")["sample"]["max_per_item"] = 3


# ---------------------------------------------------------------- challenges (citations resolve, except BAD)

SCOPE_AUD16 = dict(
    type="scope", risk="AUD-16", citation="[history:AUD-16] [history:GAP-01]; auditor-comments.md row AUD-16",
    point="The Leave out comment relies on the existing audit's follow-up; history.json records the audit but "
          "no follow-up of its agreed actions.",
    ask="The auditor to look at the AUD-16 Leave out decision.")
TEST_R08 = dict(
    type="test", risk="R-08", citation="[rule:CPR-30] [metric:$.tests.duplicates.by_tag.general_procurement.count]; "
                                       "T-06; PBC-03",
    point="T-06 matches each repeated payment to its invoices but does not check whether a contract covers it, "
          "and does not request the contracts register.",
    ask="Add PBC-03 to T-06 and a step confirming against the contracts register whether a contract covers "
        "the repeated payment.")
COVERAGE_R01 = dict(
    type="coverage", risk="R-01", citation="[rule:CPR-12]; planning-memo.md Approach",
    point="The memo Approach does not say that split groups are tested at the quote tier only.",
    ask="Add to the memo Approach that the Threshold tier is not run.")
SAMPLE_R07 = dict(
    type="sample", risk="R-07", citation="[metric:$.tests.spend_vs_award.by_tag.general_procurement.count]; T-05",
    point="T-05 pulls every payment of each sampled supplier, so a supplier with many payments may fill the sample.",
    ask="Set max_per_item to 3 on T-05 so the sample reaches more suppliers.")
RATING_R09 = dict(
    type="rating", risk="R-09",
    citation="[metric:$.tests.no_published_notice.by_tag.general_procurement.count]; auditor-comments.md row R-09",
    point="R-09's likelihood rests on the waiver log alone while the no published notice found count is a risk "
          "indicator that bears on it.",
    ask="The auditor to look at the R-09 likelihood.")
CONTROL_R06 = dict(
    type="control", risk="R-06", citation="[rule:CPR-67]; C-07",
    point="C-07 asks only for the S151 Officer's approval of an extension.",
    ask="Reword C-07 to add the board approval CPR-67 requires above the Threshold.")
BAD_R02 = dict(
    type="test", risk="R-02", citation="[rule:CPR-999]; T-02",
    point="T-02 does not say which tender records clear the indicator.",
    ask="Name the tender records T-02 needs.")


# ---------------------------------------------------------------- scenarios

SCENARIOS = {
    "pass_v1": ("v1 passes QA, round 1 raises nothing, round 2 is not run: READY on v1", lambda: [
        planner(changes=[("first build of the approved scope", "first build")], cost=0.60),
        challenger([], cost=0.08),
    ]),
    "qa_fail_fix": ("v1 fails check_numbers, the planner fixes it, v2 passes; one scope challenge goes to the "
                    "auditor: READY on v2", lambda: [
        planner(changes=[("first build of the approved scope", "first build")], edit=add_band, cost=0.60),
        planner(qa=[(1, "fixed", "Removed the clustering band placeholder from the memo limitations: it prints "
                                 "a band string, not a figure.")],
                changes=[("memo limitations: removed the band placeholder", "QA v1 #1")], edit=remove_band, cost=0.25),
        challenger([SCOPE_AUD16], cost=0.08),
        planner(responses=[(1, "for the auditor", "Concerns the AUD-16 Leave out decision at the gate; no change to "
                                                  "audit-plan.json.")], cost=0.10),
    ]),
    "round2": ("round 1: for the auditor, accepted, declined; v2 carries the change; round 2 raises one more, "
               "accepted into v3 and verified: READY on v3", lambda: [
        planner(changes=[("first build of the approved scope", "first build")], cost=0.60),
        challenger([SCOPE_AUD16, TEST_R08, COVERAGE_R01], cost=0.10),
        planner(responses=[
            (1, "for the auditor", "Concerns the AUD-16 Leave out decision at the gate."),
            (2, "accepted", "T-06 adds PBC-03 and a step confirming against the contracts register whether a "
                            "contract covers the repeated payment, citing CPR-30."),
            (3, "declined", "The builder writes the sampling method and the tiers not run into the memo itself; "
                            "the skill says not to restate them.")],
            changes=[("T-06: PBC-03 added; contracts register step citing CPR-30", "CHALLENGE #2")],
            edit=accept_t06, cost=0.30),
        challenger([SAMPLE_R07], verified=[(2, True, "")], cost=0.08),
        planner(responses=[(4, "accepted", "T-05 sets max_per_item 3.")],
                changes=[("T-05: max_per_item 3", "CHALLENGE #4")], edit=accept_t05, cost=0.20),
        challenger([], verified=[(4, True, "")], cost=0.05),
    ]),
    "round2_skipped": ("round 1: one challenge refused by the harness (its rule does not resolve), one for the "
                       "auditor, one declined; nothing accepted, so round 2 is not run: READY on v1", lambda: [
        planner(changes=[("first build of the approved scope", "first build")], cost=0.60),
        challenger([RATING_R09, CONTROL_R06, BAD_R02], cost=0.08),
        challenger([RATING_R09, CONTROL_R06, BAD_R02], cost=0.08),  # asked again; the bad one is refused
        planner(responses=[
            (1, "for the auditor", "Concerns the R-09 likelihood score; ratings are the auditor's."),
            (2, "declined", "C-07 already cites CPR-67 and T-04 checks the board approval; rules.json leaves the "
                            "reading of the closing paragraph to the auditor.")], cost=0.12),
    ]),
    "cost_cap": ("the first three calls spend the whole $3.00 cap; the challenger's verification call is not made: "
                 "BLOCKED", lambda: [
        planner(changes=[("first build of the approved scope", "first build")], cost=1.60),
        challenger([TEST_R08], cost=0.20),
        planner(responses=[(1, "accepted", "T-06 adds PBC-03 and the contracts register step.")],
                changes=[("T-06: PBC-03 added; contracts register step citing CPR-30", "CHALLENGE #1")],
                edit=accept_t06, cost=1.20),
    ]),
    "qa_blocked": ("v1 fails QA and three fix attempts do not clear it: BLOCKED on v4", lambda: [
        planner(changes=[("first build of the approved scope", "first build")], edit=add_band, cost=0.40),
        *[planner(qa=[(1, "fixed", "Reworded the clustering band sentence in the memo limitations.")],
                  changes=[("memo limitations: reworded the band sentence", f"QA v{k} #1")], edit=reword_band,
                  cost=0.15) for k in (1, 2, 3)],
    ]),
}


# ---------------------------------------------------------------- running

def transcript(name, desc, events, outcome):
    L = [f"# Dry run: {name}", "", desc, "",
         f"**Outcome: {outcome.verdict}** on v{outcome.version}, scripted cost ${outcome.cost_usd:.2f}", "",
         outcome.summary, ""]
    for e in events:
        if e["type"] == "protocol":
            L += [f"### {e['from']} → {', '.join(e['to'])}: {e['kind']}", "", "```text", e["text"], "```", ""]
        elif e["type"] == "cost":
            L += [f"*cost: {e['role']} ({e['purpose']}) ${e['call_usd']:.2f}; spent ${e['spent_usd']:.2f} "
                  f"of ${e['cap_usd']:.2f}*", ""]
        elif e["type"] in ("challenge_refused", "reply_refused"):
            L += [f"*{e['type']}: " + "; ".join(e.get("reasons") or e.get("errors")) + "*", ""]
    return "\n".join(L) + "\n"


async def run_scenario(name, base, repo=None, cfg=None):
    """Run one scenario in base/<name>/workspace. Returns (outcome, events, agents, workspace root)."""
    desc, script = SCENARIOS[name]
    ws = Workspace(base / name / "workspace", **({"repo": repo} if repo else {}))
    ws.ensure()
    cfg = cfg or load_config()["team"]
    redact = runs.make_redactor(load_secrets().values())
    events = []
    agents = ScriptedAgents(ws.root, script())
    outcome = await run_team(ws.root, cfg, agents, lambda e: events.append(redact(dict(e))))
    left = [f"{s.role}" for s in agents.steps]
    if left:
        outcome.summary += f" (script not used up: {len(left)} steps left: {', '.join(left)})"
    d = base / name
    (d / "events.json").write_text(json.dumps(events, indent=1, default=str) + "\n", encoding="utf-8")
    (d / "transcript.md").write_text(transcript(name, desc, events, outcome), encoding="utf-8")
    for f in ("challenges.md", "review.md"):
        p = ws.outputs / f
        if p.exists():
            (d / f).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    return outcome, events, agents, ws.root


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scenarios", nargs="*", help=f"default: all ({', '.join(SCENARIOS)})")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", type=Path, help="default: WORK_DIR/dry-runs/<stamp>")
    a = ap.parse_args(argv)
    if a.list:
        for k, (desc, _) in SCENARIOS.items():
            print(f"{k:16} {desc}")
        return 0
    names = a.scenarios or list(SCENARIOS)
    bad = [n for n in names if n not in SCENARIOS]
    if bad:
        ap.error(f"unknown scenario {', '.join(bad)}; --list shows them")
    base = (a.out or work_dir() / "dry-runs" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}").resolve()
    base.mkdir(parents=True, exist_ok=True)
    for n in names:
        outcome, events, agents, _ = asyncio.run(run_scenario(n, base))
        kinds = [e["kind"] for e in events if e["type"] == "protocol"]
        print(f"{n:16} {outcome.verdict:18} v{outcome.version}  ${outcome.cost_usd:.2f}  "
              f"{len(agents.calls)} scripted calls  {len(kinds)} messages")
        print(f"{'':16} {outcome.summary}")
    print(f"\ntranscripts, events, challenges.md and review.md: {base}/<scenario>/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
