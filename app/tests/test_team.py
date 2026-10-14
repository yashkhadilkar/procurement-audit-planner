"""Team stage tests: scripted planner and challenger, the real build_pack.py and run_checks.py, no cost.

    .venv/bin/python -m pytest app/tests/test_team.py -q

Each test runs in its own workspace seeded from the repo's committed outputs.
"""

import asyncio
import json
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import gates
from app.runner import Outcome, RunSpec, make_guard
from app.server import create_app
from app.settings import REPO, Secrets, load_config, team_config
from app.team import PROTECTED, READY, BLOCKED, clean_env, run_team, tree_hashes
from app.team_agents import ROLES, SdkTeamAgents
from app.team_dryrun import (SCENARIOS, SCOPE_AUD16, TEST_R08, RATING_R09, ScriptedAgents, accept_t06, challenger,
                             planner, run_scenario)
from app.workspace import Workspace

CODE = "test-access-code-1234"
KEY = "sk-ant-test-not-a-real-key-0000"
AUTH = {"X-Access-Code": CODE}
CFG = load_config()["team"]


def protocol(events, kind=None):
    return [e for e in events if e["type"] == "protocol" and (kind is None or e["kind"] == kind)]


def kinds(events):
    return [e["kind"] for e in protocol(events)]


def scenario(name, tmp_path):
    return asyncio.run(run_scenario(name, tmp_path))


@pytest.fixture
def ws(tmp_path):
    w = Workspace(tmp_path / "ws")
    w.ensure()
    return w


def run(ws, steps, cfg=None):
    events = []
    agents = ScriptedAgents(ws.root, steps)
    outcome = asyncio.run(run_team(ws.root, cfg or CFG, agents, events.append))
    return outcome, events, agents


def review(root):
    return gates.review_status(root / "outputs/review.md")


def assert_protected_unchanged(root):
    """Nothing the team may not change differs from a freshly seeded workspace."""
    fresh = Workspace(root.parent / "fresh")
    fresh.ensure()
    assert tree_hashes(root, PROTECTED) == tree_hashes(fresh.root, PROTECTED)


# ---------------------------------------------------------------- the dry-run scenarios

def test_pass_v1(tmp_path):
    out, events, agents, root = scenario("pass_v1", tmp_path)
    assert out.verdict == READY and out.version == 1 and not agents.steps
    assert kinds(events) == ["GATE", "PACK READY", "QA", "CHALLENGER DONE", "PLANNER DONE", "QA DONE"]
    assert protocol(events, "QA")[0]["text"].startswith("QA v1: PASS\nPack: built ")
    ch = (root / "outputs/challenges.md").read_text()
    assert "Round 1 on: v1 · Round 2 on: not run: round 1 raised nothing" in ch
    st = review(root)
    assert st["verdict"] == READY and st["table_verdict"] == READY and st["pack_version"] == "v1" and not st["signed"]
    assert_protected_unchanged(root)
    # The auditor can sign the review the harness wrote.
    signed = gates.sign_off(root / "outputs/review.md", "A. Auditor", "Signed off", True, True, "ok")
    assert signed["signed"] and signed["date"] == date.today().isoformat()


def test_qa_fail_then_fix(tmp_path):
    out, events, agents, root = scenario("qa_fail_fix", tmp_path)
    assert out.verdict == READY and out.version == 2 and not agents.steps
    qa = protocol(events, "QA")
    assert [q["verdict"] for q in qa] == ["FAIL", "PASS"]
    assert "#1 check_numbers: planning-memo.md line" in qa[0]["text"] and "900.00 is not a value" in qa[0]["text"]
    fix = next(c for c in agents.calls if c.purpose.startswith("fix QA v1"))
    assert "#1 check_numbers:" in fix.prompt and "attempt 1 of 3" in fix.purpose
    assert protocol(events, "PACK READY")[1]["text"].count("(QA v1 #1)") == 1
    assert [r["text"].split("\n")[0] for r in protocol(events, "RESPONSE")] == ["RESPONSE #1: for the auditor"]
    text = (root / "outputs/review.md").read_text()
    assert "| v1 | Pack: built" in text and "| FAIL | 1 point: #1 check_numbers |" in text
    assert "| v2 | Pack: built" in text and "| PASS |" in text
    assert "- #1 [scope] AUD-16:" in (root / "outputs/challenges.md").read_text()


def test_accepted_challenge_and_round2(tmp_path):
    out, events, agents, root = scenario("round2", tmp_path)
    assert out.verdict == READY and out.version == 3 and not agents.steps
    assert [c.purpose for c in agents.calls] == ["build v1", "round 1", "answer round 1", "verify and round 2",
                                                 "answer round 2", "verify v3"]
    assert [e["n"] for e in protocol(events, "CHALLENGE")] == [1, 2, 3, 4]
    assert [e["n"] for e in protocol(events, "VERIFIED")] == [2, 4]
    rows = [l for l in (root / "outputs/challenges.md").read_text().splitlines() if l.startswith("| ") and l[2].isdigit()]
    status = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    assert [(s[0], s[1], s[8], s[9]) for s in status] == [
        ("1", "1 (v1)", "for the auditor", ""), ("2", "1 (v1)", "resolved", "v2"),
        ("3", "1 (v1)", "declined", ""), ("4", "2 (v2)", "resolved", "v3")]
    plan = json.loads((root / "outputs/audit-plan.json").read_text())
    t05 = next(t for r in plan["risks"] for t in r["tests"] if t["test_id"] == "T-05")
    assert t05["sample"]["max_per_item"] == 3
    done = protocol(events, "CHALLENGER DONE")[0]["text"]
    assert "Challenges: 4 (round 1: 3, round 2: 1); resolved 2, declined 1, for the auditor 1." in done
    # The round 2 prompt asked the challenger to verify #2 and allowed at most 2 challenges.
    r2 = agents.calls[3]
    assert "#2" in r2.prompt and r2.schema["properties"]["challenges"]["maxItems"] == CFG["challenges_round2"]
    assert agents.calls[5].schema["properties"]["challenges"]["maxItems"] == 0
    assert_protected_unchanged(root)


def test_round2_skipped_and_bad_challenge_refused(tmp_path):
    out, events, agents, root = scenario("round2_skipped", tmp_path)
    assert out.verdict == READY and out.version == 1 and not agents.steps
    assert [c.purpose for c in agents.calls] == ["build v1", "round 1", "round 1", "answer round 1"]
    assert "rule CPR-999 is not in rules.json" in agents.calls[2].prompt  # asked again, with the reason
    refused = [e for e in events if e["type"] == "challenge_refused"]
    assert len(refused) == 1 and refused[0]["challenge"]["risk"] == "R-02"
    assert [e["n"] for e in protocol(events, "CHALLENGE")] == [1, 2]
    ch = (root / "outputs/challenges.md").read_text()
    assert "Round 2 on: not run: no round 1 challenge was accepted" in ch and "## Not raised" in ch


def test_cost_cap_blocks(tmp_path):
    out, events, agents, root = scenario("cost_cap", tmp_path)
    assert out.verdict == BLOCKED and out.version == 2 and out.cost_usd == pytest.approx(3.0)
    assert [c.purpose for c in agents.calls] == ["build v1", "round 1", "answer round 1"]
    assert any("cost cap reached: $3.00 spent of the $3.00 cap, so the challenger call" in r for r in out.reasons)
    # The budget each call was given is what was left under the cap.
    assert [round(c.max_budget_usd, 2) for c in agents.calls] == [3.0, 1.4, 1.2]
    st = review(root)
    assert st["verdict"] == BLOCKED and st["table_verdict"] == BLOCKED
    assert "Not for signature" in (root / "outputs/review.md").read_text()
    with pytest.raises(gates.GateError) as e:
        gates.sign_off(root / "outputs/review.md", "A. Auditor", "Signed off", True, True)
    assert e.value.status == 409
    # The accepted challenge was never verified: closed for the auditor, not left open.
    assert "accepted, not verified: the stage stopped at v2" in (root / "outputs/challenges.md").read_text()


def test_qa_fix_limit_blocks(tmp_path):
    out, events, agents, root = scenario("qa_blocked", tmp_path)
    assert out.verdict == BLOCKED and out.version == 4 and not agents.steps
    assert [q["verdict"] for q in protocol(events, "QA")] == ["FAIL"] * 4
    assert any("the 3 QA fix attempts for the stage are used up" in r for r in out.reasons)
    assert any(r.startswith("#1 check_numbers:") for r in out.reasons)  # the final run's points, as printed
    assert not [c for c in agents.calls if c.role == "challenger"]


def test_every_scenario_is_tested():
    tested = {"pass_v1", "qa_fail_fix", "round2", "round2_skipped", "cost_cap", "qa_blocked"}
    assert set(SCENARIOS) == tested


# ---------------------------------------------------------------- stops and guardrails

def test_gate_closed_runs_nothing_and_writes_nothing(ws):
    p = ws.outputs / "auditor-comments.md"
    p.write_text(p.read_text().replace("| Medium High (Amber) | Approve | Strongest", "| Medium High (Amber) |  | Strongest", 1))
    before = tree_hashes(ws.root, ["outputs"])
    out, events, agents = run(ws, [planner()])
    assert out.verdict == "GATE FAILED" and not agents.calls
    assert kinds(events) == ["GATE"] and "R-01 has no decision" in protocol(events)[0]["text"]
    assert tree_hashes(ws.root, ["outputs"]) == before


def test_tampered_input_blocks(ws):
    def tamper(root):
        p = root / "outputs/rules.json"
        p.write_text(p.read_text() + " ")
    out, events, agents = run(ws, [planner(changes=[("first", "first build")], action=tamper)])
    assert out.verdict == BLOCKED and len(agents.calls) == 1
    assert any("inputs changed: outputs/rules.json" in r for r in out.reasons)
    assert not protocol(events, "PACK READY")


def test_planner_may_not_write_challenges_md(ws):
    def write(root):
        (root / "outputs/challenges.md").write_text("# mine\n")
    out, _, _ = run(ws, [planner(changes=[("first", "first build")], action=write)])
    assert out.verdict == BLOCKED
    assert any("the planner changed outputs/challenges.md" in r for r in out.reasons)


def test_challenger_may_not_touch_the_plan(ws):
    out, _, _ = run(ws, [planner(changes=[("first", "first build")]),
                         challenger([], action=lambda root: accept_t06_on_disk(root))])
    assert out.verdict == BLOCKED
    assert any("the challenger changed outputs/audit-plan.json" in r for r in out.reasons)


def accept_t06_on_disk(root):
    p = root / "outputs/audit-plan.json"
    plan = json.loads(p.read_text())
    accept_t06(plan)
    p.write_text(json.dumps(plan))


def test_call_cut_off_at_the_budget_left(ws):
    out, _, agents = run(ws, [planner(changes=[("first", "first build")], cost=2.90), challenger([], cost=0.50)])
    assert out.verdict == BLOCKED
    assert round(agents.calls[1].max_budget_usd, 2) == 0.10
    assert any("the challenger call (round 1) stopped at the $0.10 left" in r for r in out.reasons)
    assert out.cost_usd == pytest.approx(3.01)


def test_planner_blocked(ws):
    out, events, _ = run(ws, [planner(blocked="build_pack.py: ERROR gate: risk-ratings.json has changed")])
    assert out.verdict == BLOCKED and out.version == 0
    assert protocol(events, "PLANNER BLOCKED")[0]["text"].startswith("PLANNER BLOCKED v0\n")
    assert "Planner: PLANNER BLOCKED v0" in (ws.outputs / "review.md").read_text()


def test_rebuild_without_announcement_becomes_a_version(ws):
    """A planner that only rebuilds still changes pack-figures.json: the harness makes it vN+1 and QA's it."""
    def rebuild(root):
        import subprocess
        time.sleep(1.1)  # build times are to the second
        subprocess.run([str(root / ".venv/bin/python"), "-I", ".claude/skills/audit-program/build_pack.py"],
                       cwd=root, check=True, capture_output=True)
    out, events, _ = run(ws, [
        planner(changes=[("first", "first build")]),
        challenger([SCOPE_AUD16]),
        planner(responses=[(1, "for the auditor", "Concerns the AUD-16 decision.")], action=rebuild),
    ])
    assert out.verdict == READY and out.version == 2, out.reasons
    assert [q["verdict"] for q in protocol(events, "QA")] == ["PASS", "PASS"]


def test_malformed_replies_are_asked_again(ws):
    out, events, agents = run(ws, [
        planner(changes=[("first", "first build")]),
        challenger([RATING_R09, TEST_R08]),
        planner(responses=[(1, "accepted", "Raise it."), (2, "declined", "No.")]),   # a rating cannot be accepted
        planner(responses=[(1, "for the auditor", "Concerns the R-09 likelihood."), (2, "declined", "No.")]),
    ])
    assert out.verdict == READY, out.reasons
    retry = agents.calls[3]
    assert "CHALLENGE #1 is a rating challenge: the answer is always for the auditor" in retry.prompt
    assert [e for e in events if e["type"] == "reply_refused"]


def test_checks_run_without_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("ACCESS_CODE", CODE)
    env = clean_env()
    assert "ANTHROPIC_API_KEY" not in env and "ACCESS_CODE" not in env and KEY not in json.dumps(env)


# ---------------------------------------------------------------- the SDK agents (no session started)

@pytest.fixture(autouse=True)
def only_tmp_is_temp(monkeypatch):
    """The guard always allows the system temp dir, and pytest's workspaces live there; keep /tmp only."""
    from pathlib import Path
    monkeypatch.setattr("app.runner.TEMP_ROOTS", {Path("/tmp").resolve()})


def guard_for(role, root):
    spec = SdkTeamAgents(root, KEY).spec(_call(role))
    denied = []
    g = make_guard(spec, lambda e: denied.append(e))

    def decide(tool, **ti):
        r = asyncio.run(g({"tool_name": tool, "tool_input": ti, "cwd": str(root)}, "t", None))
        return "deny" if r else "allow"
    return decide


def _call(role):
    from app.team import Call, challenger_schema, planner_schema
    return Call(role, "test", "prompt", planner_schema() if role == "planner" else challenger_schema(2), 1.25,
                "claude-haiku-5-5")


def test_challenger_guard(ws):
    d = guard_for("challenger", ws.root)
    P, B = ".claude/skills/audit-program/build_pack.py", ".claude/skills/risk-assessment/build_register.py"
    assert d("Bash", command=f".venv/bin/python -I {P} --gate") == "allow"
    assert d("Bash", command=f".venv/bin/python -I {B} --resolve '$.tests.duplicates'") == "allow"
    assert d("Bash", command="head -1 outputs/samples/T-03.csv && wc -l outputs/samples/T-03.csv") == "allow"
    for cmd in [f".venv/bin/python -I {P}", f".venv/bin/python -I {P} --lists", f".venv/bin/python -I {B}",
                f"{P} --gate --root /tmp/x", "head data/contracts.csv", "wc -l outputs/analytics-full/x.csv",
                "ls ~/procurement-holding", "cat .env"]:
        assert d("Bash", command=cmd) == "deny", cmd
    assert d("Read", file_path=str(ws.root / "data/contracts.csv")) == "deny"
    assert d("Read", file_path="outputs/analytics-full/spend-clean.csv") == "deny"
    assert d("Glob", pattern="data/**/*.xlsx") == "deny"
    assert d("Glob", pattern="outputs/samples/*.csv") == "allow"
    assert d("Read", file_path="outputs/risk-register.md") == "allow"
    assert "Write" not in ROLES["challenger"]["tools"] and "Edit" not in ROLES["challenger"]["tools"]


def test_planner_guard(ws):
    d = guard_for("planner", ws.root)
    P = ".claude/skills/audit-program/build_pack.py"
    assert d("Write", file_path="outputs/audit-plan.json", content="{}") == "allow"
    assert d("Write", file_path="/tmp/scratch.txt", content="x") == "allow"
    for f in ["outputs/rules.json", "outputs/challenges.md", "outputs/review.md", "outputs/planning-memo.md",
              ".claude/skills/audit-program/build_pack.py", "data/contracts.csv"]:
        assert d("Edit", file_path=f, old_string="a", new_string="b") == "deny", f
    assert d("Bash", command=f".venv/bin/python -I {P}") == "allow"
    assert d("Bash", command=f".venv/bin/python -I {P} --lists") == "allow"
    assert d("Bash", command=f".venv/bin/python -I {P} --plan /tmp/p.json") == "deny"
    assert d("Bash", command=".venv/bin/python -I scripts/checks/run_checks.py") == "deny"


def test_sdk_agents_spec_and_reply(ws):
    seen = []

    async def fake_runner(spec, emit):
        seen.append(spec)
        return Outcome(subtype="success", is_error=False, cost_usd=0.12,
                       structured_output={"verified": [], "challenges": []})

    agents = SdkTeamAgents(ws.root, KEY, "run-1", exclude_claude_md=[str(REPO / "CLAUDE.md")], runner=fake_runner)
    reply = asyncio.run(agents(_call("challenger"), lambda e: None))
    assert reply.data == {"verified": [], "challenges": []} and reply.cost_usd == 0.12
    s: RunSpec = seen[0]
    assert s.model == "claude-haiku-5-5" and s.max_budget_usd == 1.25 and s.write_roots == [] and s.skills == []
    assert s.output_format["type"] == "json_schema" and s.output_format["schema"]["properties"]["challenges"]
    assert "# challenger (web app harness)" in s.system_prompt and "# audit-program" in s.system_prompt
    assert s.cwd == ws.root and s.api_key == KEY and KEY not in repr(s)
    p = agents.spec(_call("planner"))
    assert p.write_roots == [ws.root / "outputs/audit-plan.json"] and "Write" in p.tools and "Agent" not in p.tools


def test_team_config_validation():
    assert team_config(None, "x")["max_cost_usd"] == 3.0
    assert team_config({"max_cost_usd": 1}, "x")["max_cost_usd"] == 1.0
    for bad in [{"max_cost_usd": 0}, {"max_cost_usd": True}, {"challenges_round1": -1}, {"qa_fix_attempts": 1.5},
                {"planner_model": ""}, {"nonsense": 1}]:
        with pytest.raises(ValueError):
            team_config(bad, "x")


# ---------------------------------------------------------------- through the API

def wait_idle(client, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if client.get("/api/state").json()["running"] is None:
            return
        time.sleep(0.05)
    raise AssertionError("run did not finish")


@pytest.mark.parametrize("name, status, verdict", [("round2", "succeeded", READY), ("cost_cap", "blocked", BLOCKED)])
def test_team_stage_through_the_api(tmp_path, name, status, verdict):
    made = []

    def team_agents(root, run_id):
        made.append(ScriptedAgents(root, SCENARIOS[name][1]()))
        return made[-1]

    app = create_app(work_root=tmp_path / "work", secrets=Secrets(api_key=KEY, access_code=CODE),
                     config=load_config(), team_agents=team_agents)
    with TestClient(app) as c:
        r = c.post("/api/run/team", headers=AUTH)
        assert r.status_code == 202, r.text
        run_id = r.json()["run_id"]
        wait_idle(c)
        rec = json.loads((tmp_path / "work/runs" / f"{run_id}.json").read_text())
        assert rec["status"] == status and rec["verdict"] == verdict and rec["max_budget_usd"] == 3.0
        assert rec["cost_usd"] == pytest.approx(sum(e["call_usd"] for e in rec["events"] if e["type"] == "cost"))
        assert "review.md" in rec["outputs_changed"] and "challenges.md" in rec["outputs_changed"]
        assert not rec["other_changed"]
        with c.stream("GET", f"/api/runs/{run_id}/events") as s:
            body = "".join(s.iter_text())
        assert "event: protocol" in body and "PACK READY v1" in body and "QA DONE" in body
        assert KEY not in body and CODE not in body
        by = {s["stage"]: s for s in c.get("/api/state").json()["stages"]}
        assert by["team"]["status"] == status
        assert by["signoff"]["status"] == ("ready" if verdict == READY else "blocked")
        sign = c.post("/api/signoff", headers=AUTH, json={"auditor": "A. Auditor", "challenges_considered": True,
                                                          "qa_points_considered": True})
        assert sign.status_code == (200 if verdict == READY else 409), sign.text
        assert not made[0].steps
