"""FastAPI backend for the audit planner web app (Part B).

    .venv/bin/python -m app                      # http://127.0.0.1:8000
    .venv/bin/uvicorn app.server:create_app --factory

Endpoints
    GET  /                          the web UI (app/static/, plain HTML, CSS and JavaScript)
    GET  /api/state                 each stage's status, last run, cost and outputs; total spend
    GET  /api/access                200 if the X-Access-Code header is right (the UI's unlock check)
    POST /api/run/{stage}           start a stage (X-Access-Code); 409 while another run is active
    GET  /api/runs/{id}/events      server-sent events: the run's steps and tool calls, live
    GET  /api/files/{path}          read-only, files inside WORK_DIR/outputs only
    POST /api/gate1                 write auditor decisions into auditor-comments.md (X-Access-Code)
    POST /api/signoff               fill review.md's sign-off block if READY FOR SIGN-OFF (X-Access-Code)
    POST /api/reset                 restore the signed-off run (X-Access-Code)

One process, one run at a time. ANTHROPIC_API_KEY and ACCESS_CODE are read
from the environment or .env and never printed, logged or returned.
"""

import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import gates, runs
from .runner import Outcome, RunSpec, run_sdk
from .settings import REPO, STAGES, load_config, load_secrets, work_dir
from .team import run_team
from .team_agents import SdkTeamAgents
from .workspace import Workspace, WorkspaceError

STATIC = Path(__file__).resolve().parent / "static"
# What each stage needs before it may start (relative to WORK_DIR) and what it produces (in outputs/).
REGISTER_OUT = ["risk-ratings.json", "risk-register.md", "auditor-comments.md", "register-snapshots"]
STAGE_SPEC = {
    "rules": {"skill": "extract-rules", "needs": ["data/contract-rules.pdf"], "outputs": ["rules.json"]},
    "spend": {"agent": "spend-analyst", "needs": ["outputs/rules.json", "data/spend", "data/contracts.csv"],
              "outputs": ["analytics.json", "analytics-full"]},
    "history": {"agent": "findings-analyst", "needs": ["data/committee"], "outputs": ["history.json"]},
    "register": {"agent": "risk-assessor", "task": " for an initial build of the risk register (r0)",
                 "needs": ["outputs/rules.json", "outputs/analytics.json", "outputs/history.json"],
                 "outputs": REGISTER_OUT},
    "revise": {"agent": "risk-assessor",
               "task": " to apply the auditor's decisions in outputs/auditor-comments.md as a revision",
               "needs": ["outputs/rules.json", "outputs/analytics.json", "outputs/history.json",
                         "outputs/risk-ratings.json", "outputs/auditor-comments.md"],
               "outputs": REGISTER_OUT},
    "team": {"needs": ["outputs/rules.json", "outputs/analytics.json", "outputs/analytics-full", "outputs/history.json",
                       "outputs/risk-ratings.json", "outputs/risk-register.md", "outputs/auditor-comments.md",
                       "outputs/register-snapshots"],
             "outputs": ["audit-plan.json", "planning-memo.md", "risk-control-matrix.md", "audit-program.md",
                         "samples", "pack-figures.json", "challenges.md", "review.md"]},
    "signoff": {"outputs": ["review.md"]},
}
AGENT_PROMPT = """Run the {stage} stage of the audit flow in CLAUDE.md for the web app.
Launch the {agent} sub-agent exactly once{task}. Do not do its work yourself and do not
edit any file. No person is watching this session: if the sub-agent stops on a problem,
relay the problem and stop. When it finishes, relay its report as it gave it."""


class Decision(BaseModel):
    id: str
    decision: str
    comment: str | None = None
    clear_applied: bool = False


class Gate1Body(BaseModel):
    decisions: list[Decision]


class SignoffBody(BaseModel):
    auditor: str
    decision: str = "Signed off"
    challenges_considered: bool | str
    qa_points_considered: bool | str
    comment: str = ""


def prompt_for(stage):
    spec = STAGE_SPEC[stage]
    if "skill" in spec:
        return f"/{spec['skill']}"
    return AGENT_PROMPT.format(stage=stage, agent=spec["agent"], task=spec.get("task", ""))


def create_app(work_root=None, secrets=None, config=None, runner=None, repo=REPO, team_agents=None):
    """runner stands in for run_sdk and team_agents(root, run_id) for the team's SDK agents (tests)."""
    secrets = secrets or load_secrets()
    config = config or load_config()
    ws = Workspace(work_root or work_dir(), repo=repo)
    redact = runs.make_redactor(secrets.values())
    team_agents = team_agents or (lambda root, run_id: SdkTeamAgents(
        root, secrets.api_key, run_id, exclude_claude_md=[str(repo / "CLAUDE.md")]))

    @asynccontextmanager
    async def lifespan(app):
        ws.ensure()
        app.state.summaries = runs.load_summaries(ws.runs)
        yield
        task = app.state.task
        if task and not task.done():
            task.cancel()

    app = FastAPI(title="Procurement audit planner", lifespan=lifespan)
    app.state.ws = ws
    app.state.runner = runner or run_sdk
    app.state.current = None   # RunHandle of the active run
    app.state.task = None
    app.state.handles = {}     # runs started by this process, for live streaming
    app.state.summaries = {}

    # ------------------------------------------------------------ helpers

    def require_code(code):
        if not secrets.access_code:
            raise HTTPException(503, "the server has no ACCESS_CODE configured")
        if not code or not hmac.compare_digest(code.encode(), secrets.access_code.encode()):
            raise HTTPException(401, "missing or wrong X-Access-Code header")

    def require_idle():
        cur = app.state.current
        if cur is not None:
            raise HTTPException(409, f"run {cur.id} ({cur.record['stage']}) is in progress; one run at a time")

    def gate_error(e):
        return HTTPException(e.status, e.message)

    def output_info(rel):
        p = ws.outputs / rel
        if not p.exists():
            return {"path": rel, "exists": False}
        st = p.stat()
        info = {"path": rel, "exists": True,
                "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")}
        if p.is_dir():
            info["files"] = sum(1 for f in p.rglob("*") if f.is_file())
        else:
            info["size"] = st.st_size
        return info

    def precheck(stage):
        missing = []
        for rel in STAGE_SPEC[stage].get("needs", []):
            p = ws.root / rel
            if not p.exists() or (p.is_dir() and not any(p.iterdir())):
                missing.append(rel)
        if missing:
            raise HTTPException(409, f"{stage} cannot start: missing {', '.join(missing)}")
        if stage in ("register", "revise"):
            g = gates.gate_status(ws.outputs / "auditor-comments.md")
            if g.get("error"):
                raise HTTPException(409, f"auditor-comments.md does not parse: {g['error']}")
            if stage == "register" and g.get("decided"):
                raise HTTPException(409, "the auditor has already recorded decisions, so the risk-assessor "
                                         "would revise rather than build r0: run revise, or reset")
            if stage == "revise":
                if not g.get("closed"):
                    raise HTTPException(409, "the gate is not closed: every row in auditor-comments.md needs "
                                             f"a Decision first (undecided: {', '.join(g.get('undecided', [])) or 'none'})")
                if not g.get("pending"):
                    raise HTTPException(409, "nothing to revise: no Amend, Reject or Add to scope decision "
                                             "is waiting to be applied")

    def stage_state(stage, kind):
        cur = app.state.current
        seeded_at = ws.info().get("seeded_at", "")
        mine = [s for s in app.state.summaries.values() if s.get("stage") == stage]
        last = max(mine, key=lambda s: s.get("started_at", ""), default=None)
        out = {"stage": stage, "kind": kind}
        if kind == "agent":
            out.update(config["stages"][stage])
        elif kind == "team":
            out.update(config["team"], max_budget_usd=config["team"]["max_cost_usd"])
        out["outputs"] = [output_info(rel) for rel in STAGE_SPEC[stage]["outputs"]]
        if cur is not None and cur.record["stage"] == stage:
            status = "running"
        elif kind == "stub":
            status = "not available"
        elif stage == "signoff":
            r = gates.review_status(ws.outputs / "review.md")
            status = ("signed" if r.get("signed") else "ready" if r.get("verdict") == gates.READY
                      else "blocked" if r.get("verdict") else "not ready")
            out["review"] = r
        elif last and last.get("started_at", "") >= seeded_at:
            status = last.get("status")
        else:
            status = "signed-off run" if all(o["exists"] for o in out["outputs"]) else "not run"
        out["status"] = status
        if last:
            out["last_run"] = {k: last.get(k) for k in ("id", "status", "started_at", "finished_at", "cost_usd",
                                                         "model", "outputs_changed")}
        return out

    # ------------------------------------------------------------ run execution

    async def run_team_stage(handle):
        """The team stage as an Outcome: success only on READY FOR SIGN-OFF."""
        cfg = config["team"]
        result = await run_team(ws.root, cfg, team_agents(ws.root, handle.id), handle.emit)
        handle.update(verdict=result.verdict, pack_version=result.version, reasons=result.reasons)
        ok = result.verdict == gates.READY
        return Outcome(subtype="success" if ok else "blocked", is_error=not ok, cost_usd=result.cost_usd,
                       result_text=result.summary)

    async def execute(handle, work, before):
        status, error = "error", None
        try:
            outcome = await work()
            status = ("succeeded" if outcome.subtype == "success" and not outcome.is_error
                      else "blocked" if outcome.subtype == "blocked" else "failed")
            handle.update(cost_usd=outcome.cost_usd, num_turns=outcome.num_turns, duration_ms=outcome.duration_ms,
                          result_subtype=outcome.subtype, result_text=outcome.result_text,
                          session_id=outcome.session_id)
        except asyncio.CancelledError:
            error = "cancelled: the server shut down"
            raise
        except Exception as e:  # reported in the run record, never swallowed
            error = str(e)
            handle.emit({"type": "error", "message": error})
        finally:
            changed = []
            try:
                after = ws.commit(f"Run {handle.id} ({handle.record['stage']}): {status}")
                changed = ws.changed(before, after)
            except WorkspaceError as e:
                error = (error + "; " if error else "") + str(e)
            outs = [p.removeprefix("outputs/") for _, p in changed if p.startswith("outputs/")]
            handle.update(status=status, error=error, finished_at=runs.now_iso(), outputs_changed=outs,
                          other_changed=[p for _, p in changed if not p.startswith("outputs/")])
            handle.emit({"type": "run_finished", "status": status, "cost_usd": handle.record.get("cost_usd"),
                         "outputs_changed": outs})
            handle.finish()
            app.state.summaries[handle.id] = runs.summary(handle.record)
            app.state.current = None

    # ------------------------------------------------------------ endpoints

    @app.get("/api/state")
    async def state():
        cur = app.state.current
        costs = [s["cost_usd"] for s in app.state.summaries.values() if isinstance(s.get("cost_usd"), (int, float))]
        return {
            "work_dir": str(ws.root),
            "workspace": ws.info(),
            "running": {"id": cur.id, "stage": cur.record["stage"]} if cur else None,
            "spend": {"total_usd": round(sum(costs), 6), "runs": len(app.state.summaries),
                      "runs_with_cost": len(costs)},
            "stages": [stage_state(s, k) for s, k in STAGES.items()],
            "gate1": {k: v for k, v in gates.gate_status(ws.outputs / "auditor-comments.md").items()
                      if k != "decisions"},
        }

    @app.get("/api/access")
    async def access(x_access_code: str | None = Header(default=None)):
        require_code(x_access_code)
        return {"ok": True}

    @app.post("/api/run/{stage}", status_code=202)
    async def run(stage: str, x_access_code: str | None = Header(default=None)):
        require_code(x_access_code)
        if stage not in STAGES:
            raise HTTPException(404, f"unknown stage {stage!r}; stages: {', '.join(STAGES)}")
        if STAGES[stage] == "stub":
            raise HTTPException(501, f"the {stage} stage is not built yet")
        if STAGES[stage] == "none":
            raise HTTPException(400, f"{stage} has no agent: use POST /api/{stage}")
        if not secrets.api_key:
            raise HTTPException(503, "the server has no ANTHROPIC_API_KEY configured")
        require_idle()
        if STAGES[stage] == "team":
            t = config["team"]
            cfg = {"model": f"planner {t['planner_model']}, challenger {t['challenger_model']}",
                   "max_budget_usd": t["max_cost_usd"]}
        else:
            cfg = config["stages"][stage]
        run_id = runs.new_run_id(stage)
        record = {"id": run_id, "stage": stage, "status": "running", "model": cfg["model"],
                  "max_budget_usd": cfg["max_budget_usd"], "started_at": runs.now_iso(), "finished_at": None,
                  "cost_usd": None, "error": None}
        handle = runs.RunHandle(record, ws.runs / f"{run_id}.json", redact)
        app.state.current = handle  # taken before any await: the lock
        try:
            ws.refresh_inputs()
            precheck(stage)
            before = ws.commit(f"Before run {run_id} ({stage})")
        except BaseException:
            app.state.current = None
            raise
        handle.update(workspace_commit_before=before)
        if STAGES[stage] == "team":
            handle.emit({"type": "run_started", "stage": stage, "model": cfg["model"],
                         "max_budget_usd": cfg["max_budget_usd"], "team": config["team"]})

            def work():
                return run_team_stage(handle)
        else:
            spec = RunSpec(run_id=run_id, stage=stage, prompt=prompt_for(stage), model=cfg["model"],
                           max_budget_usd=cfg["max_budget_usd"], cwd=ws.root, write_roots=ws.write_roots(),
                           forward_subagent_text=config["forward_subagent_text"],
                           exclude_claude_md=[str(repo / "CLAUDE.md")], api_key=secrets.api_key)
            handle.emit({"type": "run_started", "stage": stage, "model": cfg["model"],
                         "max_budget_usd": cfg["max_budget_usd"], "prompt": spec.prompt})

            def work():
                return app.state.runner(spec, handle.emit)
        app.state.handles[run_id] = handle
        app.state.summaries[run_id] = runs.summary(record)
        app.state.task = asyncio.create_task(execute(handle, work, before))
        return {"run_id": run_id, "events": f"/api/runs/{run_id}/events"}

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str, request: Request, last_event_id: str | None = Header(default=None)):
        if not runs.RUN_ID_RE.match(run_id):
            raise HTTPException(404, "no such run")
        handle = app.state.handles.get(run_id)
        if handle is None:
            path = ws.runs / f"{run_id}.json"
            if not path.exists():
                raise HTTPException(404, "no such run")
            handle = runs.RunHandle(json.loads(path.read_text(encoding="utf-8")), path, redact)
            handle.done = True
        start = int(last_event_id) if (last_event_id or "").isdigit() else 0

        def sse(event):
            return (f"id: {event['seq']}\nevent: {event['type']}\n"
                    f"data: {json.dumps(event, default=str)}\n\n")

        async def stream():
            i = start
            while True:
                wake = handle.changed
                while i < len(handle.events):
                    yield sse(handle.events[i])
                    i += 1
                if handle.done:
                    yield f"event: end\ndata: {json.dumps({'status': handle.record.get('status')})}\n\n"
                    return
                if await request.is_disconnected():
                    return
                try:
                    await asyncio.wait_for(wake.wait(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    MEDIA = {".json": "application/json", ".md": "text/markdown; charset=utf-8",
             ".csv": "text/csv; charset=utf-8", ".txt": "text/plain; charset=utf-8"}

    @app.get("/api/files/{path:path}")
    async def files(path: str):
        rel = PurePosixPath(path)
        if not path or "\x00" in path or "\\" in path or rel.is_absolute() or ".." in rel.parts:
            raise HTTPException(403, "only files inside outputs/ can be read")
        base = ws.outputs.resolve()
        full = (base / rel).resolve()
        if full != base and base not in full.parents:
            raise HTTPException(403, "only files inside outputs/ can be read")
        if not full.exists():
            raise HTTPException(404, f"outputs/{rel} does not exist")
        if full.is_dir():
            return {"path": str(rel), "entries": sorted(
                p.name + ("/" if p.is_dir() else "") for p in full.iterdir() if not p.name.startswith("."))}
        return FileResponse(full, media_type=MEDIA.get(full.suffix.lower(), "application/octet-stream"),
                            headers={"X-Content-Type-Options": "nosniff"})

    @app.post("/api/gate1")
    async def gate1(body: Gate1Body, x_access_code: str | None = Header(default=None)):
        require_code(x_access_code)
        require_idle()
        try:
            result = gates.apply_decisions(ws.outputs / "auditor-comments.md",
                                           [d.model_dump() for d in body.decisions])
        except gates.GateError as e:
            raise gate_error(e)
        return {"ok": True, **result}

    @app.post("/api/signoff")
    async def signoff(body: SignoffBody, x_access_code: str | None = Header(default=None)):
        require_code(x_access_code)
        require_idle()
        try:
            result = gates.sign_off(ws.outputs / "review.md", body.auditor, body.decision,
                                    body.challenges_considered, body.qa_points_considered, body.comment)
        except gates.GateError as e:
            raise gate_error(e)
        return {"ok": True, "review": result}

    @app.post("/api/reset")
    async def reset(x_access_code: str | None = Header(default=None)):
        require_code(x_access_code)
        require_idle()
        try:
            ws.reset()
        except WorkspaceError as e:
            raise HTTPException(500, str(e))
        return {"ok": True, "workspace": ws.info()}

    @app.exception_handler(WorkspaceError)
    async def workspace_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=500)

    # Last, so every /api route above takes precedence.
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
