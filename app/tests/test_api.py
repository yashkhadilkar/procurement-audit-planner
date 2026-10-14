"""API tests with a fake runner: no Agent SDK session, no API calls, no cost.

    .venv/bin/python -m pytest app/tests -q

Each test gets its own WORK_DIR seeded from the repo's committed outputs.
"""

import asyncio
import json
import subprocess
import threading
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import gates
from app.runner import Outcome
from app.server import create_app
from app.settings import REPO, Secrets, load_config

CODE = "test-access-code-1234"
KEY = "sk-ant-test-not-a-real-key-0000"
AUTH = {"X-Access-Code": CODE}


class FakeRunner:
    """Stands in for run_sdk: emits a few events, writes one output, blocks until released."""

    def __init__(self, block=True, fail=False):
        self.release = threading.Event()
        if not block:
            self.release.set()
        self.fail = fail
        self.specs = []

    async def __call__(self, spec, emit):
        self.specs.append(spec)
        emit({"type": "text", "agent": "main", "text": f"env shows {KEY} and {CODE}"})
        emit({"type": "tool_use", "agent": "findings-analyst", "parent": "toolu_1", "id": "toolu_2",
              "name": "Bash", "input": {"command": "pdftotext -layout x.pdf -"}})
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        if self.fail:
            raise RuntimeError("CLI exited with code 1")
        (spec.cwd / "outputs" / "fake-output.txt").write_text("written by the fake runner\n")
        return Outcome(subtype="success", is_error=False, cost_usd=0.0123, num_turns=3, duration_ms=42,
                       result_text="done", session_id="s-1")


@pytest.fixture
def work(tmp_path):
    return tmp_path / "work"


def no_team_agents(root, run_id):
    raise AssertionError("a test reached the real team agents; pass scripted ones")


@pytest.fixture
def client_for(work):
    clients = []

    def make(runner=None, team_agents=no_team_agents):
        app = create_app(work_root=work, secrets=Secrets(api_key=KEY, access_code=CODE),
                         config=load_config(), runner=runner or FakeRunner(block=False), team_agents=team_agents)
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)


def wait_idle(client, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if client.get("/api/state").json()["running"] is None:
            return
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def committed(path):
    """A file's content as committed at the repo's HEAD."""
    return subprocess.run(["git", "-C", str(REPO), "show", f"HEAD:{path}"], capture_output=True,
                          check=True).stdout


# ---------------------------------------------------------------- workspace

def test_workspace_seeded_from_committed_outputs(client_for, work):
    c = client_for()
    assert (work / "outputs/rules.json").read_bytes() == committed("outputs/rules.json")
    assert (work / ".git").is_dir() and (work / ".venv").is_symlink()
    st = c.get("/api/state").json()
    by = {s["stage"]: s for s in st["stages"]}
    assert list(by) == ["rules", "spend", "history", "register", "revise", "team", "signoff"]
    assert by["history"]["model"] == "claude-haiku-5-5" and by["rules"]["model"] == "claude-sonnet-5-5"
    assert all(by[s]["max_budget_usd"] == 1.5 for s in ("rules", "spend", "history", "register", "revise"))
    assert by["rules"]["status"] == "signed-off run"
    assert by["team"]["status"] == "signed-off run" and by["team"]["kind"] == "team"
    assert by["team"]["max_budget_usd"] == 3.0 and by["team"]["planner_model"] == "claude-sonnet-5-5"
    assert by["team"]["challenger_model"] == "claude-haiku-5-5"
    assert by["signoff"]["status"] == "signed"
    assert KEY not in json.dumps(st) and CODE not in json.dumps(st)


def test_reset_restores_signed_off_run(client_for, work):
    c = client_for()
    (work / "outputs/rules.json").write_text("{}")
    assert c.post("/api/reset").status_code == 401
    r = c.post("/api/reset", headers=AUTH)
    assert r.status_code == 200
    assert (work / "outputs/rules.json").read_bytes() == committed("outputs/rules.json")


# ---------------------------------------------------------------- files

def test_files_serves_outputs(client_for, work):
    c = client_for()
    r = c.get("/api/files/rules.json")
    assert r.status_code == 200 and r.content == (work / "outputs/rules.json").read_bytes()
    assert r.headers["content-type"].startswith("application/json")
    listing = c.get("/api/files/samples").json()
    assert "T-01.csv" in listing["entries"]
    assert c.get("/api/files/no-such-file.md").status_code == 404


@pytest.mark.parametrize("path", [
    "../workspace.json",
    "..%2Fworkspace.json",
    "%2e%2e/workspace.json",
    "%2e%2e%2fworkspace.json",
    "analytics-full/../../workspace.json",
    "analytics-full/%2e%2e/%2e%2e/workspace.json",
    "%2Fetc%2Fpasswd",
    "/etc/passwd",
    "..\\workspace.json",
    "../.git/config",
    "../data/contracts.csv",
])
def test_files_refuses_paths_outside_outputs(client_for, work, path):
    c = client_for()
    r = c.get(f"/api/files/{path}")
    assert r.status_code in (403, 404), (path, r.status_code)
    assert b"seeded_at" not in r.content and b"root:" not in r.content and b"[core]" not in r.content


def test_files_refuses_symlink_out_of_outputs(client_for, work):
    c = client_for()
    (work / "outputs/escape.json").symlink_to(work / "workspace.json")
    (work / "outputs/escape-dir").symlink_to(work / "data", target_is_directory=True)
    assert c.get("/api/files/escape.json").status_code == 403
    assert c.get("/api/files/escape-dir/contracts.csv").status_code == 403


# ---------------------------------------------------------------- gate 1

def comments(work):
    return work / "outputs/auditor-comments.md"


def test_gate1_writes_decision_and_comment(client_for, work):
    c = client_for()
    before = comments(work).read_text().split("\n")
    r = c.post("/api/gate1", headers=AUTH, json={"decisions": [
        {"id": "R-09", "decision": "amend", "comment": "Raise impact to 4: waivers cover the largest awards."}]})
    assert r.status_code == 200, r.text
    after = comments(work).read_text().split("\n")
    parsed = gates.builder().parse_comments(comments(work))
    assert parsed["R-09"]["decision"] == "Amend"
    assert parsed["R-09"]["comment"] == "Raise impact to 4: waivers cover the largest awards."
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(before) == len(after) and len(changed) == 1 and after[changed[0]].startswith("| R-09 |")
    assert r.json()["pending"] == ["R-09"] and r.json()["closed"] is True


def test_gate1_keeps_comment_and_clears_applied(client_for, work):
    c = client_for()
    r = c.post("/api/gate1", headers=AUTH, json={"decisions": [
        {"id": "R-05", "decision": "Amend", "clear_applied": True},
        {"id": "AUD-11", "decision": "Add to scope", "comment": "Rate it."}]})
    assert r.status_code == 200, r.text
    parsed = gates.builder().parse_comments(comments(work))
    assert parsed["R-05"]["applied"] == "" and parsed["R-05"]["comment"].startswith("Lower likelihood")
    assert parsed["AUD-11"]["decision"] == "Add to scope"
    assert sorted(r.json()["pending"]) == ["AUD-11", "R-05"]


@pytest.mark.parametrize("decision, fragment", [
    ({"id": "R-01", "decision": "Maybe"}, "not one of"),
    ({"id": "R-99", "decision": "Approve"}, "not a row"),
    ({"id": "AUD-16", "decision": "Approve"}, "not one of"),
    ({"id": "R-02", "decision": "Approve", "comment": "a | b"}, "may not contain |"),
    ({"id": "R-02", "decision": "Approve", "comment": "line one\nline two"}, "line break"),
    ({"id": "R-06", "decision": "Amend"}, "needs a comment"),
])
def test_gate1_rejects_invalid_and_leaves_file_unchanged(client_for, work, decision, fragment):
    c = client_for()
    before = comments(work).read_bytes()
    r = c.post("/api/gate1", headers=AUTH, json={"decisions": [decision]})
    assert r.status_code == 422 and fragment in r.json()["detail"], r.text
    assert comments(work).read_bytes() == before


def test_gate1_rejects_whole_batch_if_one_row_is_bad(client_for, work):
    c = client_for()
    before = comments(work).read_bytes()
    r = c.post("/api/gate1", headers=AUTH, json={"decisions": [
        {"id": "R-01", "decision": "Reject", "comment": "ok"}, {"id": "R-02", "decision": "Nope"}]})
    assert r.status_code == 422 and comments(work).read_bytes() == before


def test_gate1_needs_access_code_and_file(client_for, work):
    c = client_for()
    body = {"decisions": [{"id": "R-01", "decision": "Approve"}]}
    before = comments(work).read_bytes()
    assert c.post("/api/gate1", json=body).status_code == 401
    assert c.post("/api/gate1", json=body, headers={"X-Access-Code": "wrong"}).status_code == 401
    assert comments(work).read_bytes() == before
    comments(work).unlink()
    assert c.post("/api/gate1", json=body, headers=AUTH).status_code == 404


# ---------------------------------------------------------------- sign-off

def review(work):
    return work / "outputs/review.md"


def blank_signoff(path, verdict="READY FOR SIGN-OFF"):
    """Turn the committed (signed) review.md back into an unsigned one, as QA writes it."""
    blank = {"Decision": "Signed off / Not signed off", "Auditor": "", "Date": "", "Comment": ""}
    out, in_block = [], False
    for line in path.read_text().split("\n"):
        if line.startswith("## "):
            in_block = line.strip() == "## Auditor sign-off"
        if line.strip() == "**READY FOR SIGN-OFF**":
            line = f"**{verdict}**"
        if in_block and line.startswith("| "):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells[0] in blank:
                line = f"| {cells[0]} | {blank[cells[0]]} |"
            elif cells[0].startswith(("Challenges marked", "QA points answered")):
                line = f"| {cells[0]} | Yes / No |"
            elif cells[0] == "QA verdict":
                line = f"| QA verdict | {verdict} |"
        out.append(line)
    path.write_text("\n".join(out))


SIGN = {"auditor": "A. Auditor", "decision": "Signed off", "challenges_considered": True,
        "qa_points_considered": "yes", "comment": "Considered challenge #1."}


def test_signoff_fills_block_when_ready(client_for, work):
    c = client_for()
    blank_signoff(review(work))
    before = review(work).read_text().split("\n")
    r = c.post("/api/signoff", headers=AUTH, json=SIGN)
    assert r.status_code == 200, r.text
    after = review(work).read_text().split("\n")
    st = gates.review_status(review(work))
    assert st["signed"] and st["decision"] == "Signed off" and st["auditor"] == "A. Auditor"
    assert st["date"] == date.today().isoformat() and st["verdict"] == "READY FOR SIGN-OFF"
    changed = [after[i] for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(before) == len(after) and len(changed) == 6
    assert "| Comment | Considered challenge #1. |" in changed
    by = {s["stage"]: s for s in c.get("/api/state").json()["stages"]}
    assert by["signoff"]["status"] == "signed"


def test_signoff_refused_when_blocked(client_for, work):
    c = client_for()
    blank_signoff(review(work), verdict="BLOCKED")
    before = review(work).read_bytes()
    r = c.post("/api/signoff", headers=AUTH, json=SIGN)
    assert r.status_code == 409 and "BLOCKED" in r.json()["detail"]
    assert review(work).read_bytes() == before


def test_signoff_refused_when_already_signed(client_for, work):
    c = client_for()
    before = review(work).read_bytes()
    r = c.post("/api/signoff", headers=AUTH, json=SIGN)
    assert r.status_code == 409 and "already signed" in r.json()["detail"]
    assert review(work).read_bytes() == before


@pytest.mark.parametrize("change, status", [
    ({"challenges_considered": False}, 422),
    ({"comment": "fine | done"}, 422),
    ({"auditor": "  "}, 422),
    ({"decision": "Approved"}, 422),
    ({"qa_points_considered": "maybe"}, 422),
])
def test_signoff_validation(client_for, work, change, status):
    c = client_for()
    blank_signoff(review(work))
    before = review(work).read_bytes()
    r = c.post("/api/signoff", headers=AUTH, json={**SIGN, **change})
    assert r.status_code == status, r.text
    assert review(work).read_bytes() == before


def test_signoff_not_signed_off_and_auth(client_for, work):
    c = client_for()
    blank_signoff(review(work))
    assert c.post("/api/signoff", json=SIGN).status_code == 401
    r = c.post("/api/signoff", headers=AUTH, json={**SIGN, "decision": "not signed off",
                                                   "challenges_considered": False})
    assert r.status_code == 200 and gates.review_status(review(work))["decision"] == "Not signed off"


# ---------------------------------------------------------------- runs and the lock

def test_one_run_at_a_time(client_for, work):
    runner = FakeRunner(block=True)
    c = client_for(runner)
    r = c.post("/api/run/history", headers=AUTH)
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    assert c.get("/api/state").json()["running"] == {"id": run_id, "stage": "history"}

    # Everything that runs or writes is refused while the run holds the lock.
    for path, body in [("/api/run/history", None), ("/api/run/spend", None),
                       ("/api/gate1", {"decisions": [{"id": "R-01", "decision": "Approve"}]}),
                       ("/api/signoff", SIGN), ("/api/reset", None)]:
        r2 = c.post(path, headers=AUTH, json=body)
        assert r2.status_code == 409 and run_id in r2.json()["detail"], (path, r2.text)

    runner.release.set()
    wait_idle(c)
    assert c.post("/api/run/history", headers=AUTH).status_code == 202  # lock released
    wait_idle(c)

    rec = json.loads((work / "runs" / f"{run_id}.json").read_text())
    assert rec["status"] == "succeeded" and rec["cost_usd"] == 0.0123 and rec["finished_at"]
    assert rec["outputs_changed"] == ["fake-output.txt"]
    assert KEY not in json.dumps(rec) and CODE not in json.dumps(rec)
    spec = runner.specs[0]
    assert spec.model == "claude-haiku-5-5" and spec.max_budget_usd == 1.5 and "findings-analyst" in spec.prompt
    assert spec.cwd == work.resolve() and str(REPO / "CLAUDE.md") in spec.exclude_claude_md

    hist = {s["stage"]: s for s in c.get("/api/state").json()["stages"]}["history"]
    assert hist["status"] == "succeeded" and hist["last_run"]["cost_usd"] == 0.0123


def test_events_stream_replays_and_redacts(client_for, work):
    c = client_for(FakeRunner(block=False))
    run_id = c.post("/api/run/history", headers=AUTH).json()["run_id"]
    wait_idle(c)
    with c.stream("GET", f"/api/runs/{run_id}/events") as s:
        body = "".join(s.iter_text())
    kinds = [l.split(": ", 1)[1] for l in body.splitlines() if l.startswith("event: ")]
    assert kinds == ["run_started", "text", "tool_use", "run_finished", "end"]
    assert KEY not in body and CODE not in body and "[redacted]" in body
    with c.stream("GET", f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "3"}) as s:
        kinds = [l.split(": ", 1)[1] for l in s.iter_lines() if l.startswith("event: ")]
    assert kinds == ["run_finished", "end"]
    assert c.get("/api/runs/20990101T000000Z-history-abcdef/events").status_code == 404
    assert c.get("/api/runs/..%2Fworkspace/events").status_code == 404


def test_runner_failure_is_recorded_and_releases_lock(client_for, work):
    c = client_for(FakeRunner(block=False, fail=True))
    run_id = c.post("/api/run/history", headers=AUTH).json()["run_id"]
    wait_idle(c)
    rec = json.loads((work / "runs" / f"{run_id}.json").read_text())
    assert rec["status"] == "error" and "code 1" in rec["error"]
    assert c.post("/api/run/history", headers=AUTH).status_code == 202


def test_run_endpoint_refusals(client_for, work):
    c = client_for()
    assert c.post("/api/run/history").status_code == 401
    assert c.post("/api/run/nonsense", headers=AUTH).status_code == 404
    assert c.post("/api/run/signoff", headers=AUTH).status_code == 400
    # The signed-off run's comments are all decided and applied: no r0 build, nothing to revise.
    r = c.post("/api/run/register", headers=AUTH)
    assert r.status_code == 409 and "already recorded decisions" in r.json()["detail"]
    r = c.post("/api/run/revise", headers=AUTH)
    assert r.status_code == 409 and "nothing to revise" in r.json()["detail"]
    assert c.get("/api/state").json()["running"] is None  # a refused precheck does not hold the lock


def test_run_needs_api_key(work):
    app = create_app(work_root=work, secrets=Secrets(api_key=None, access_code=CODE), config=load_config(),
                     runner=FakeRunner(block=False))
    with TestClient(app) as c:
        assert c.post("/api/run/history", headers=AUTH).status_code == 503
