"""The team stage: planner, challenger and qa-reviewer, run by the harness.

The Agent SDK has no agent teams, so this module plays the lead and runs the
protocol of .claude/agents/planner.md, challenger.md and qa-reviewer.md and
CLAUDE.md "Agent team" in Python:

    gate        build_pack.py --gate; a failure stops the stage and writes nothing
    planner     one SDK session per task (build, fix QA points, answer challenges),
                replying in a JSON schema; the harness then runs build_pack.py
                itself, and that build's OK: line is the version vN
    qa-reviewer no model: run_checks.py, its Pack:, VERDICT: and #n lines as printed;
                at most qa_fix_attempts fixes in the whole stage, then BLOCKED
    challenger  one SDK session per round, replying in a JSON schema; the harness
                checks every challenge (type, risk, citations resolve, indicator
                language), numbers it, and writes challenges.md from the record
    final       fingerprint, gate, run_checks.py --final, the pack unchanged since
                its QA PASS; then review.md with READY FOR SIGN-OFF or BLOCKED

Every protocol message (GATE, PACK READY vN, QA vN, CHALLENGE #n, RESPONSE #n,
PLANNER DONE, CHALLENGER DONE, QA DONE) is emitted as a "protocol" event
({from, to, kind, text, version?, n?}), so the UI can show the conversation.

Guardrails: the cost cap is checked before every model call and the call gets
only the budget that is left; the protected inputs are fingerprinted at the
start and checked after every model call and before every verdict; each role
may change only its own files (checked after each call); the checks and the
builder run with the secrets removed from their environment.
"""

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .settings import SECRET_NAMES

BUILD = ".claude/skills/audit-program/build_pack.py"
CHECKS = "scripts/checks/run_checks.py"
PLAN = "outputs/audit-plan.json"
PACK = ["outputs/audit-plan.json", "outputs/planning-memo.md", "outputs/risk-control-matrix.md",
        "outputs/audit-program.md", "outputs/pack-figures.json", "outputs/samples"]
OWNED = ["outputs/challenges.md", "outputs/review.md"]  # written by this module only
BACKUPS = "plan-backups"  # WORK_DIR/plan-backups/<stamp>/: the plan and pack a fresh run moved aside
# What no role may change: the planner's and the qa-reviewer's Step 0 lists, all of data/ and .claude/.
PROTECTED = ["outputs/rules.json", "outputs/analytics.json", "outputs/history.json", "outputs/risk-ratings.json",
             "outputs/risk-register.md", "outputs/auditor-comments.md", "outputs/register-snapshots",
             "outputs/analytics-full", "data", "CLAUDE.md", ".claude/skills", ".claude/agents",
             ".claude/settings.json", "scripts/checks"]
SKIP_PARTS = {"__pycache__", ".DS_Store"}

TYPES = ("rating", "scope", "sample", "control", "test", "coverage")
AUDITOR_TYPES = ("rating", "scope")
ANSWERS = ("accepted", "declined", "for the auditor")
QA_ANSWERS = ("fixed", "for the auditor")
READY, BLOCKED = "READY FOR SIGN-OFF", "BLOCKED"
TEAMMATES = ["planner", "challenger", "qa-reviewer"]
# The builder's list of words that state wrongdoing rather than an indicator.
ACCUSATORY_RE = re.compile(r"\b(off[- ]contract|wrongdoing|fraudulent|corrupt\w*|misconduct|unlawful\w*|"
                           r"illegal\w*|breach(?:es|ed)?)\b", re.IGNORECASE)
ROW_ID_RE = re.compile(r"\b(?:R|AUD)-\d+\b")


class Blocked(Exception):
    """The stage stops and the pack goes back to the team; the reason goes into review.md."""


@dataclass
class Call:
    role: str
    purpose: str
    prompt: str
    schema: dict
    max_budget_usd: float
    model: str = ""


@dataclass
class Reply:
    data: dict | None
    cost_usd: float | None
    subtype: str = "success"
    is_error: bool = False


@dataclass
class TeamOutcome:
    verdict: str  # READY FOR SIGN-OFF, BLOCKED, or GATE FAILED (nothing ran, nothing written)
    version: int
    cost_usd: float
    reasons: list = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------- schemas

def _obj(props, required=None):
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


STR = {"type": "string"}


def planner_schema():
    return _obj({
        "status": {"type": "string", "enum": ["built", "blocked"]},
        "ok_line": STR,
        "changes": {"type": "array", "items": _obj({"change": STR, "because": STR})},
        "responses": {"type": "array", "items": _obj(
            {"n": {"type": "integer"}, "answer": {"type": "string", "enum": list(ANSWERS)}, "detail": STR})},
        "qa_responses": {"type": "array", "items": _obj(
            {"n": {"type": "integer"}, "answer": {"type": "string", "enum": list(QA_ANSWERS)}, "detail": STR})},
        "blocked_reason": STR,
    })


def challenger_schema(max_challenges):
    return _obj({
        "verified": {"type": "array", "items": _obj({"n": {"type": "integer"}, "found": {"type": "boolean"},
                                                     "note": STR})},
        "challenges": {"type": "array", "maxItems": max_challenges, "items": _obj(
            {"type": {"type": "string", "enum": list(TYPES)}, "risk": STR, "citation": STR, "point": STR,
             "ask": STR})},
    })


# ---------------------------------------------------------------- files

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_hashes(root, rels):
    """{relative path: sha256} for every file under rels (a missing path is simply absent)."""
    out = {}
    for rel in rels:
        p = root / rel
        files = [p] if p.is_file() else sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else []
        for f in files:
            if not SKIP_PARTS & set(f.relative_to(root).parts):
                out[f.relative_to(root).as_posix()] = sha256(f)
    return out


def changed_files(before, after):
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def cell(s):
    """One markdown table cell: no | and no line break inside it."""
    return re.sub(r"\s*\n\s*", " ", str(s)).replace("|", "/").strip()


def pack_parts(line):
    return set((line or "").removeprefix("Pack: ").split("; "))


def clean_env():
    return {k: v for k, v in os.environ.items() if k not in SECRET_NAMES and not k.startswith("ANTHROPIC_")}


@dataclass
class QARun:
    output: str
    pack: str
    verdict: str
    points: list
    passed: bool


# ---------------------------------------------------------------- the team

class Team:
    def __init__(self, root, cfg, agents, emit, env=None, python=None):
        self.root = Path(root).resolve()
        self.out = self.root / "outputs"
        self.cfg = cfg
        self.agents = agents
        self.emit = emit
        self.env = env if env is not None else clean_env()
        venv = self.root / ".venv/bin/python"
        self.python = python or (str(venv) if venv.exists() else sys.executable)
        self.cap = float(cfg["max_cost_usd"])
        self.spent = 0.0
        self.version = 0
        self.versions = []      # {n, ok_line, changes, pack, verdict, points}
        self.challenges = []    # one dict per numbered challenge
        self.refused = []       # challenges the harness did not pass on, with the reason
        self.qa_for_auditor = []
        self.fix_attempts = 0
        self.gate_line = None
        self.round_on = {1: None, 2: None}
        self.round2_note = None
        self.last_verified = None
        self.planner_line = "not received"
        self.challenger_line = "not received"
        self.owned = {}
        self.fp = {}
        self.plan_sha = None
        self.pack_hashes = {}

    # ------------------------------------------------------------ plumbing

    def say(self, sender, to, kind, text, **extra):
        self.emit({"type": "protocol", "from": sender, "to": to if isinstance(to, list) else [to], "kind": kind,
                   "text": text, **extra})

    async def py(self, *args):
        def run():
            r = subprocess.run([self.python, "-I", *args], cwd=self.root, env=self.env, capture_output=True,
                               text=True, timeout=900)
            return r.returncode, (r.stdout + r.stderr).strip()
        return await asyncio.to_thread(run)

    def write_owned(self, rel, text):
        p = self.root / rel
        p.write_text(text, encoding="utf-8")
        self.owned[rel] = sha256(p)

    def owned_state(self):
        return {rel: (sha256(self.root / rel) if (self.root / rel).is_file() else None) for rel in OWNED}

    def check_fingerprint(self, when):
        changed = changed_files(self.fp, tree_hashes(self.root, PROTECTED))
        if changed:
            raise Blocked(f"inputs changed: {', '.join(changed[:8])}{' ...' if len(changed) > 8 else ''} ({when})")

    def check_ownership(self, role, purpose, pack_before):
        now = self.owned_state()
        bad = [rel for rel in OWNED if now[rel] != self.owned.get(rel)]
        if role == "challenger":
            bad += changed_files(pack_before, tree_hashes(self.root, PACK))
        if bad:
            raise Blocked(f"the {role} changed {', '.join(bad[:8])} during its call ({purpose}), "
                          "which it does not own")

    def budget_left(self, role, purpose):
        left = round(self.cap - self.spent, 6)
        if left <= 0:
            raise Blocked(f"cost cap reached: ${self.spent:.2f} spent of the ${self.cap:.2f} cap, so the {role} "
                          f"call ({purpose}) was not made")
        return left

    async def call(self, role, purpose, prompt, schema, validate=None):
        """One model call, with the cap checked before it; retried once if the reply does not validate."""
        model = self.cfg["planner_model" if role == "planner" else "challenger_model"]
        for attempt in (1, 2):
            left = self.budget_left(role, purpose)
            pack_before = tree_hashes(self.root, PACK)
            self.emit({"type": "call", "role": role, "purpose": purpose, "attempt": attempt, "model": model,
                       "max_budget_usd": left})

            def tagged(ev, role=role, purpose=purpose):
                agent = ev.get("agent")
                self.emit({**ev, "agent": role if agent in (None, "main") else agent, "role": role,
                           "purpose": purpose})

            try:
                reply = await self.agents(Call(role, purpose, prompt, schema, left, model), tagged)
            except Blocked:
                raise
            except Exception as e:  # the cost of a crashed call is not known
                raise Blocked(f"the {role} call ({purpose}) failed: {type(e).__name__}: {str(e)[:500]}")
            if reply.cost_usd is None:
                raise Blocked(f"the {role} call ({purpose}) reported no cost, so the cap cannot be enforced")
            self.spent += reply.cost_usd
            self.emit({"type": "cost", "role": role, "purpose": purpose, "call_usd": round(reply.cost_usd, 4),
                       "spent_usd": round(self.spent, 4), "cap_usd": self.cap})
            self.check_fingerprint(f"after the {role} call: {purpose}")
            self.check_ownership(role, purpose, pack_before)
            if reply.subtype == "error_max_budget_usd":
                raise Blocked(f"cost cap reached: the {role} call ({purpose}) stopped at the ${left:.2f} left "
                              f"under the cap; ${self.spent:.2f} spent of ${self.cap:.2f}")
            if reply.is_error or not isinstance(reply.data, dict):
                raise Blocked(f"the {role} call ({purpose}) ended with {reply.subtype} and no structured reply")
            errs = validate(reply.data, attempt == 2) if validate else []
            if not errs:
                return reply.data
            self.emit({"type": "reply_refused", "role": role, "purpose": purpose, "errors": errs})
            if attempt == 2:
                raise Blocked(f"the {role} reply ({purpose}) could not be used twice: {'; '.join(errs[:5])}")
            prompt += ("\n\n## Your last reply could not be used\n\n" + "\n".join(f"- {e}" for e in errs)
                       + "\n\nCheck the workspace as it now stands and reply again, complete, in the schema.")

    # ------------------------------------------------------------ the record, for each fresh session

    def record_text(self):
        L = [f"Gate: {self.gate_line}"]
        for v in self.versions:
            L.append(f"- v{v['n']}: {v['ok_line']} QA: {v['verdict'] or 'not yet run'}."
                     + "".join(f"\n  - change: {c}" for c in v["changes"]))
        for c in self.challenges:
            L.append(f"- CHALLENGE #{c['n']} [{c['type']}] {c['risk']} (round {c['round']} on v{c['on']}): "
                     f"{c['point']} Ask: {c['ask']} Response: {c['response'] or 'none yet'}. Status: {c['status']}.")
        for q in self.qa_for_auditor:
            L.append(f"- QA v{q['version']} {q['point']}: RESPONSE #{q['n']}: for the auditor: {q['detail']}")
        return "\n".join(L)

    def task(self, title, body):
        return (f"# Task: {title}\n\nTeam stage of the procurement audit, run by the web app harness. "
                f"The pack is at v{self.version} (the next build announced will be v{self.version + 1})."
                f"\n\n## Record so far\n\n{self.record_text()}\n\n## What to do\n\n{body}\n")

    # ------------------------------------------------------------ planner

    def planner_validator(self, challenge_ns=(), qa_ns=()):
        def validate(d, final):
            errs = []
            if d.get("status") == "blocked":
                return [] if d.get("blocked_reason", "").strip() else ["status is blocked but blocked_reason is empty"]
            got = [r["n"] for r in d.get("responses", [])]
            if sorted(got) != sorted(challenge_ns):
                errs.append(f"responses must answer exactly CHALLENGE {', '.join(f'#{n}' for n in challenge_ns) or 'none'}"
                            f"; got {', '.join(f'#{n}' for n in got) or 'none'}")
            by_n = {c["n"]: c for c in self.challenges}
            for r in d.get("responses", []):
                c = by_n.get(r["n"])
                if c and c["type"] in AUDITOR_TYPES and r["answer"] != "for the auditor":
                    errs.append(f"CHALLENGE #{r['n']} is a {c['type']} challenge: the answer is always for the auditor")
                if not r.get("detail", "").strip():
                    errs.append(f"RESPONSE #{r['n']} has no detail")
            got = [r["n"] for r in d.get("qa_responses", [])]
            if sorted(got) != sorted(qa_ns):
                errs.append(f"qa_responses must answer exactly points {', '.join(f'#{n}' for n in qa_ns) or 'none'}"
                            f"; got {', '.join(f'#{n}' for n in got) or 'none'}")
            for text in [d.get("ok_line", "")] + [r["detail"] for r in d.get("responses", []) + d.get("qa_responses", [])]:
                m = ACCUSATORY_RE.search(text)
                if m:
                    errs.append(f"{m.group(0)!r} is not indicator language")
            return errs
        return validate

    async def planner(self, purpose, body, challenge_ns=(), qa_ns=()):
        d = await self.call("planner", purpose, self.task(purpose, body), planner_schema(),
                            self.planner_validator(challenge_ns, qa_ns))
        if d["status"] == "blocked":
            self.planner_line = f"PLANNER BLOCKED v{self.version}"
            self.say("planner", "lead", "PLANNER BLOCKED", f"PLANNER BLOCKED v{self.version}\n{d['blocked_reason']}",
                     version=self.version)
            raise Blocked(f"PLANNER BLOCKED v{self.version}: {d['blocked_reason']}")
        return d

    async def build(self):
        code, out = await self.py(BUILD)
        ok = next((l for l in out.splitlines() if l.startswith("OK: ")), None)
        return (ok if code == 0 else None), out

    async def publish(self, reply):
        """The harness's own build of the plan on disk; on OK it is the next version, announced to the
        challenger and the qa-reviewer. The caller runs QA on it."""
        changes = [f"{c['change']} ({c['because']})" for c in reply.get("changes", [])]
        ok, out = await self.build()
        if ok is None:
            self.say("lead", "planner", "BUILD FAILED", out)
            fix = await self.planner("fix the build",
                                     "You replied that the build printed OK, but the harness's own run of "
                                     f"build_pack.py printed this:\n\n```text\n{out}\n```\n\nFix every ERROR "
                                     "legitimately and rebuild until it prints OK:.")
            changes += [f"{c['change']} ({c['because']})" for c in fix.get("changes", [])]
            ok, out = await self.build()
            if ok is None:
                raise Blocked("build_pack.py printed FAIL after the planner twice reported OK: "
                              + next((l.strip() for l in out.splitlines() if "ERROR" in l), out[:300]))
        self.version += 1
        self.plan_sha = sha256(self.root / PLAN)
        self.pack_hashes = tree_hashes(self.root, PACK)
        n = self.version
        self.versions.append({"n": n, "ok_line": ok, "changes": changes or ["no change to audit-plan.json"],
                              "pack": None, "verdict": None, "points": []})
        lines = "\n".join(f"- {c}" for c in changes) if changes else "- no change to audit-plan.json"
        self.say("planner", ["challenger", "qa-reviewer"], "PACK READY",
                 f"PACK READY v{n}\n{ok}\nChanges since v{n - 1}:" + (" first build" if n == 1 and not changes
                                                                      else "\n" + lines), version=n)

    # ------------------------------------------------------------ qa-reviewer (no model)

    async def run_checks(self, final=False):
        code, out = await self.py(CHECKS, *(["--final"] if final else []))
        lines = out.splitlines()
        pack = next((l for l in lines if l.startswith("Pack: ")), None)
        verdict = next((l for l in lines if l.startswith("VERDICT: ")), None)
        if pack is None or verdict is None:
            raise Blocked(f"run_checks.py printed no Pack: or VERDICT: line (exit {code}): {out[-500:]}")
        points = [l for l in lines if re.match(r"#\d+ \S+: ", l)]
        return QARun(out, pack, verdict, points, verdict == "VERDICT: PASS" and code == 0)

    async def qa_until_pass(self):
        while True:
            v = self.versions[-1]
            r = await self.run_checks()
            self.check_fingerprint(f"before the QA v{v['n']} verdict")
            v.update(pack=r.pack, verdict="PASS" if r.passed else "FAIL", points=r.points)
            head = f"QA v{v['n']}: {'PASS' if r.passed else 'FAIL'}"
            self.say("qa-reviewer", "planner", "QA", "\n".join([head, *r.points, r.pack]), version=v["n"],
                     verdict=v["verdict"])
            if r.passed:
                return
            if self.fix_attempts >= self.cfg["qa_fix_attempts"]:
                raise Blocked(f"QA v{v['n']}: FAIL, and the {self.cfg['qa_fix_attempts']} QA fix attempts "
                              "for the stage are used up")
            self.fix_attempts += 1
            nums = [int(p[1:p.index(" ")]) for p in r.points]
            reply = await self.planner(
                f"fix QA v{v['n']} (attempt {self.fix_attempts} of {self.cfg['qa_fix_attempts']})",
                f"The qa-reviewer sent:\n\n```text\n{head}\n" + "\n".join(r.points) + f"\n{r.pack}\n```\n\n"
                "Take each point in turn (your instructions, Fix QA points). Answer every point by its number "
                "in qa_responses, then rebuild once for all the fixes.", qa_ns=nums)
            fixed = False
            for q in sorted(reply["qa_responses"], key=lambda q: q["n"]):
                point = r.points[nums.index(q["n"])]
                if q["answer"] == "for the auditor":
                    self.qa_for_auditor.append({"version": v["n"], "n": q["n"], "point": point, "detail": q["detail"]})
                    self.say("planner", "qa-reviewer", "RESPONSE",
                             f"RESPONSE #{q['n']}: for the auditor\n{q['detail']}", version=v["n"], n=q["n"])
                else:
                    fixed = True
            if not fixed:
                raise Blocked(f"every point of QA v{v['n']} went to the auditor; a version passes only when "
                              "run_checks.py prints VERDICT: PASS")
            await self.publish(reply)  # the loop checks the new version

    # ------------------------------------------------------------ challenger

    def evidence(self):
        """qa_lib (the checks' own parsers, from the protected copy) and what a citation may resolve to."""
        if not hasattr(self, "_evidence"):
            sys.path.insert(0, str(self.root / "scripts/checks"))
            try:
                import qa_lib as Q
            finally:
                sys.path.pop(0)

            def load(name):
                return json.loads((self.out / name).read_text(encoding="utf-8"))

            self._evidence = (Q, {"rules": {r.get("rule_id") for r in load("rules.json").get("rules", [])},
                                  "history": Q.history_ids(load("history.json")), "analytics": load("analytics.json"),
                                  "rows": Q.parse_comments((self.out / "auditor-comments.md").read_text(encoding="utf-8"))})
        return self._evidence

    def challenge_problems(self, c):
        """Why a challenge cannot be passed on, as check_trace --final would see it, or []."""
        Q, ev = self.evidence()
        probs = []
        if c["risk"] not in ev["rows"]:
            probs.append(f"{c['risk']!r} is not a risk or noted item in auditor-comments.md")
        for k in ("citation", "point", "ask"):
            if not c[k].strip():
                probs.append(f"{k} is empty")
            m = ACCUSATORY_RE.search(c[k])
            if m:
                probs.append(f"{m.group(0)!r} in the {k} is not indicator language")
        good = 0
        for kind, ref in Q.scan_citations(c["citation"]):
            if ref is None:
                probs.append(f"an unclosed {kind} citation")
            elif kind in ("rule", "history"):
                if ref in ev["rules" if kind == "rule" else "history"]:
                    good += 1
                else:
                    probs.append(f"{kind} {ref} is not in {'rules' if kind == 'rule' else 'history'}.json")
            else:
                try:
                    Q.resolve_path(ev["analytics"], ref)
                    good += 1
                except ValueError as e:
                    probs.append(f"metric {ref} does not resolve ({e})")
        if "auditor-comments" in c["citation"]:
            if any(k in ev["rows"] for k in ROW_ID_RE.findall(c["citation"])):
                good += 1
            else:
                probs.append("the auditor-comments.md row it names is not a row there")
        if not good:
            probs.append("it cites no evidence that resolves (a rule, metric, history item or auditor-comments.md row)")
        return probs

    def challenger_validator(self, limit, verify_ns):
        def validate(d, final):
            errs = []
            got = [v["n"] for v in d.get("verified", [])]
            if sorted(got) != sorted(verify_ns):
                errs.append(f"verified must cover exactly {', '.join(f'#{n}' for n in verify_ns) or 'none'}; "
                            f"got {', '.join(f'#{n}' for n in got) or 'none'}")
            for v in d.get("verified", []):
                if not v["found"] and not v.get("note", "").strip():
                    errs.append(f"#{v['n']} not found needs a note saying what is missing")
            chs = d.get("challenges", [])
            if len(chs) > limit and not final:
                errs.append(f"{len(chs)} challenges raised; at most {limit} are allowed in this round")
            if not final:
                for i, c in enumerate(chs[:limit], 1):
                    errs += [f"challenge {i} ([{c['type']}] {c['risk']}): {p}" for p in self.challenge_problems(c)]
            return errs
        return validate

    async def challenger(self, rnd, purpose, body, limit, verify=()):
        verify_ns = [c["n"] for c in verify]
        d = await self.call("challenger", purpose, self.task(purpose, body), challenger_schema(limit),
                            self.challenger_validator(limit, verify_ns))
        v = self.version
        self.last_verified = v
        for item in d["verified"]:
            c = next(c for c in self.challenges if c["n"] == item["n"])
            c["checked_in"] = v
            if item["found"]:
                c.update(status="resolved", verified=f"v{v}", note="")
                self.say("challenger", "lead", "VERIFIED", f"#{c['n']} accepted for v{c['carry']}, found in v{v}: "
                         "resolved", n=c["n"], version=v)
            else:
                c["note"] = f"accepted for v{c['carry']}, not found in v{v}: {cell(item['note'])}"
                self.say("challenger", "planner", "NOT FOUND", f"#{c['n']} {c['note']}", n=c["n"], version=v)
        new = []
        for i, raw in enumerate(d["challenges"], 1):
            raw = {k: cell(raw[k]) for k in ("type", "risk", "citation", "point", "ask")}
            probs = ([f"over the round limit of {limit}"] if i > limit else []) or self.challenge_problems(raw)
            if probs:
                self.refused.append({**raw, "reason": "; ".join(probs)})
                self.emit({"type": "challenge_refused", "challenge": raw, "reasons": probs})
                continue
            c = {**raw, "n": len(self.challenges) + 1, "round": rnd, "on": v, "answer": None, "detail": "", "response": "", "status": "open", "verified": "",
                 "carry": None, "note": "", "checked_in": None}
            self.challenges.append(c)
            new.append(c)
            self.say("challenger", "planner", "CHALLENGE",
                     f"CHALLENGE #{c['n']} [{c['type']}] {c['risk']}\nCitation: {c['citation']}\n"
                     f"Point: {c['point']}\nAsk: {c['ask']}", n=c["n"], version=v)
        self.write_challenges()
        return new

    def challenge_block(self, cs):
        return "\n\n".join(f"CHALLENGE #{c['n']} [{c['type']}] {c['risk']}\nCitation: {c['citation']}\n"
                           f"Point: {c['point']}\nAsk: {c['ask']}" for c in cs)

    async def answer(self, purpose, cs, not_found=()):
        """The planner answers cs and makes any missing accepted change; rebuild and QA if the plan changed."""
        body = ""
        if cs:
            body += ("The challenger sent these challenges. Answer every one by number in responses "
                     f"(your instructions, Answer challenges):\n\n```text\n{self.challenge_block(cs)}\n```\n\n")
        if not_found:
            body += ("The challenger checked these accepted changes and did not find them:\n\n```text\n"
                     + "\n".join(f"#{c['n']} {c['note']}" for c in not_found) + "\n```\n\nMake each missing "
                     "change you accepted, and record it in changes.\n\n")
        body += f"If audit-plan.json changes, rebuild until build_pack.py prints OK:; that build will be v{self.version + 1}."
        reply = await self.planner(purpose, body, challenge_ns=[c["n"] for c in cs])
        for r in sorted(reply["responses"], key=lambda r: r["n"]):
            c = next(c for c in self.challenges if c["n"] == r["n"])
            c.update(answer=r["answer"], detail=cell(r["detail"]),
                     status={"accepted": "open", "declined": "declined"}.get(r["answer"], "for the auditor"))
            self.say("planner", "challenger", "RESPONSE", f"RESPONSE #{c['n']}: {r['answer']}\n{r['detail']}",
                     n=c["n"], version=self.version)
        # Any change to the plan or the pack (a rebuild alone rewrites pack-figures.json) is a new version,
        # so the pack QA passed is never left changed behind QA's back.
        changed = sha256(self.root / PLAN) != self.plan_sha or tree_hashes(self.root, PACK) != self.pack_hashes
        for c in cs:
            if c["answer"] == "accepted":
                c["carry"] = self.version + 1 if changed else self.version
        for c in cs:
            c["response"] = f"{c['answer']}: {c['detail']}" + (f" (v{c['carry']})" if c["answer"] == "accepted" else "")
        self.write_challenges()
        if changed:
            await self.publish(reply)
            await self.qa_until_pass()

    async def challenge_rounds(self):
        n1 = self.cfg["challenges_round1"]
        self.round_on[1] = self.version
        r1 = []
        if n1:
            r1 = await self.challenger(
                1, "round 1", f"PACK READY v{self.version} has passed QA. Read the pack and the record (your "
                f"instructions, Reading) and raise at most {n1} challenges on v{self.version}.", n1)
        if r1:
            await self.answer("answer round 1", r1)
        accepted = [c for c in r1 if c["answer"] == "accepted"]
        if not r1:
            self.round2_note = "not run: round 1 raised nothing"
        elif not accepted:
            self.round2_note = "not run: no round 1 challenge was accepted"
        if self.round2_note:
            self.write_challenges()
            return
        n2 = self.cfg["challenges_round2"]
        self.round_on[2] = self.version
        r2 = await self.challenger(
            2, "verify and round 2", f"PACK READY v{self.version}. First verify the accepted round 1 challenges "
            f"{', '.join('#' + str(c['n']) for c in accepted)} in v{self.version} (your instructions, Verifying "
            f"accepted changes); then raise at most {n2} round 2 challenges on v{self.version}, numbered on by the "
            "harness. Raise nothing already in the record." if n2 else
            f"Verify the accepted round 1 challenges in v{self.version}; raise nothing.", n2, verify=accepted)
        if n2 == 0:
            self.round2_note = "not run: the round 2 limit is 0"
        missing = [c for c in accepted if c["status"] == "open"]
        if r2 or missing:
            await self.answer("answer round 2" if r2 else "make missing changes", r2, missing)
        pending = [c for c in self.challenges if c["answer"] == "accepted" and c["status"] == "open"
                   and (c["checked_in"] is None or c["checked_in"] < self.version)]
        if pending:
            await self.challenger(
                2, f"verify v{self.version}", f"PACK READY v{self.version}. Verify the accepted challenges "
                f"{', '.join('#' + str(c['n']) for c in pending)} in v{self.version}. Raise no new challenge: "
                "round 2 is over.", 0, verify=pending)

    def close_rows(self, why_open):
        for c in self.challenges:
            if c["status"] == "open":
                c["status"] = "for the auditor"
                if not c["note"]:
                    c["note"] = why_open if c["answer"] == "accepted" else "no response: the stage stopped first"

    def challenger_done(self):
        self.close_rows(f"accepted, not verified in v{self.version}")
        self.write_challenges()
        cs = self.challenges
        count = {s: sum(c["status"] == s for c in cs) for s in ("resolved", "declined", "for the auditor")}
        text = (f"CHALLENGER DONE\nLast version verified: v{self.last_verified or self.version}. Challenges: "
                f"{len(cs)} (round 1: {sum(c['round'] == 1 for c in cs)}, round 2: {sum(c['round'] == 2 for c in cs)});"
                f" resolved {count['resolved']}, declined {count['declined']}, for the auditor {count['for the auditor']}.")
        fa = [f"- #{c['n']} [{c['type']}] {c['risk']}: {c['note'] or c['detail']}" for c in cs
              if c["status"] == "for the auditor"]
        dec = [f"- #{c['n']} [{c['type']}] {c['risk']} declined: {c['detail']}" for c in cs if c["status"] == "declined"]
        self.challenger_line = "CHALLENGER DONE"
        self.say("challenger", ["planner", "qa-reviewer", "lead"], "CHALLENGER DONE", "\n".join([text, *fa, *dec]))

    def planner_done(self):
        v = self.versions[-1]
        self.planner_line = f"PLANNER DONE v{v['n']}"
        fa = [c for c in self.challenges if c["status"] == "for the auditor"]
        rest = [c for c in self.challenges if c["status"] != "for the auditor"]
        lines = [f"PLANNER DONE v{v['n']}", self.gate_line, v["ok_line"]]
        lines += [f"- CHALLENGE #{c['n']} [{c['type']}] {c['risk']}: {c['response']}" for c in fa + rest]
        lines += [f"- QA v{q['version']} #{q['n']}: for the auditor: {q['detail']}" for q in self.qa_for_auditor]
        lines.append("- the inputs, the register, the skill and the builder are unchanged (fingerprint checked)")
        self.say("planner", ["lead", "challenger", "qa-reviewer"], "PLANNER DONE", "\n".join(lines), version=v["n"])

    # ------------------------------------------------------------ challenges.md and review.md

    def write_challenges(self):
        rev = re.search(r"register r(\d+)", self.gate_line or "")
        r1 = f"v{self.round_on[1]}" if self.round_on[1] else "pending"
        r2 = self.round2_note or (f"v{self.round_on[2]}" if self.round_on[2] else "pending")
        L = ["# Challenges: audit planning pack", "",
             f"Register revision: r{rev.group(1) if rev else '?'} (gate: {self.gate_line})",
             f"Round 1 on: {r1} · Round 2 on: {r2} · Last version verified: "
             f"{'v' + str(self.last_verified) if self.last_verified else 'none'}", "",
             "The ratings and the scope are the auditor's. Rows marked *for the auditor*",
             "are put to the auditor without a recommendation.", "",
             "| # | Round | Type | Risk | Challenge | Citation | Ask | Response | Status | Verified |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for c in self.challenges:
            resp = c["response"] + (f"; {c['note']}" if c["note"] and c["status"] != "resolved" else "")
            L.append("| " + " | ".join(cell(x) for x in [
                c["n"], f"{c['round']} (v{c['on']})", c["type"], c["risk"], c["point"], c["citation"], c["ask"],
                resp, c["status"], c["verified"]]) + " |")
        fa = [c for c in self.challenges if c["status"] == "for the auditor"]
        L += ["", "## For the auditor", ""]
        L += [f"- #{c['n']} [{c['type']}] {c['risk']}: {cell(c['note'] or c['detail'])}" for c in fa] or ["None."]
        if self.refused:
            L += ["", "## Not raised", "", "Challenges the harness did not pass to the planner, with the reason:", ""]
            L += [f"- [{c['type']}] {c['risk']}: {cell(c['point'])} Refused: {cell(c['reason'])}" for c in self.refused]
        self.write_owned("outputs/challenges.md", "\n".join(L) + "\n")

    def write_review(self, verdict, reasons, final, gate_final):
        rev = re.search(r"register r(\d+)", self.gate_line or "")
        v = self.versions[-1]["n"] if self.versions else None
        vtext = f"v{v}" if v else "none"
        if verdict == READY:
            why = [f"Every check passed in the final run on v{v}, the version the planner finished on; the pack is "
                   f"unchanged since QA v{v}: PASS."]
        else:
            why = reasons
        rows = []
        for x in self.versions:
            pts = (f"{len(x['points'])} point{'s' if len(x['points']) != 1 else ''}: "
                   + ", ".join(p.split(":", 1)[0] for p in x["points"])) if x["points"] else ""
            rows.append(f"| v{x['n']} | {cell(x['pack'] or 'not checked')} | {x['verdict'] or 'not checked'} | {pts} |")
        L = ["# QA review: audit planning pack", "",
             f"Register revision: r{rev.group(1) if rev else '?'} (gate: {gate_final or self.gate_line})",
             f"Version reviewed: {vtext} · Planner: {self.planner_line} · Challenger: {self.challenger_line}",
             f"Reviewed: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}", "",
             "## Verdict", "", f"**{verdict}**", "", *why, "",
             "## Final check run (as printed)", "", "```text", final, "```", "",
             "## Versions checked", "", "| Version | Pack | Verdict | Points |", "| --- | --- | --- | --- |",
             *(rows or ["| none | | | |"]), "",
             "## QA points answered for the auditor", ""]
        L += [f"- v{q['version']} {q['point']}. Planner: RESPONSE #{q['n']}: for the auditor: {cell(q['detail'])}"
              for q in self.qa_for_auditor] or ["None."]
        L += ["", "## Auditor sign-off", "",
              "To be completed by the auditor. QA does not sign off."
              + (" Not for signature: the verdict is BLOCKED and the pack goes back to the team."
                 if verdict != READY else ""), "",
              "| Item | Entry |", "| --- | --- |",
              f"| QA verdict | {verdict} |",
              f"| Pack version | {vtext} |",
              "| Challenges marked *for the auditor* in `outputs/challenges.md` considered | Yes / No |",
              "| QA points answered *for the auditor* considered | Yes / No |",
              "| Decision | Signed off / Not signed off |",
              "| Auditor | |", "| Date | |", "| Comment | |"]
        self.write_owned("outputs/review.md", "\n".join(L) + "\n")

    # ------------------------------------------------------------ the run

    async def run(self):
        self.fp = tree_hashes(self.root, PROTECTED)
        self.emit({"type": "team_started", "cap_usd": self.cap, "planner_model": self.cfg["planner_model"],
                   "challenger_model": self.cfg["challenger_model"],
                   "challenges": [self.cfg["challenges_round1"], self.cfg["challenges_round2"]],
                   "qa_fix_attempts": self.cfg["qa_fix_attempts"], "protected_files": len(self.fp)})
        code, out = await self.py(BUILD, "--gate")
        gate = next((l for l in out.splitlines() if l.startswith("GATE OK")), None)
        self.say("lead", TEAMMATES, "GATE", out)
        if code != 0 or gate is None:
            return TeamOutcome("GATE FAILED", 0, 0.0, [out], "The gate is closed: nothing was run or written. "
                               "The auditor completes auditor-comments.md and the risk-assessor builds the revision.")
        self.gate_line = gate
        if self.cfg.get("fresh_plan", True):
            self.back_up_plan()
        self.owned = self.owned_state()
        self.plan_sha = sha256(self.root / PLAN) if (self.root / PLAN).exists() else None
        self.write_challenges()  # a fresh record: the previous run's no longer applies
        self.write_owned("outputs/review.md", "# QA review: audit planning pack\n\nThe team stage is running; "
                         "this review is written when it finishes.\n")
        reasons = []
        start = ("There is no outputs/audit-plan.json: the previous plan and pack were moved out of the workspace "
                 "for this run. Write a new plan from the register and the evidence."
                 if not (self.root / PLAN).exists() else
                 "outputs/audit-plan.json exists from the previous run; start from it.")
        try:
            first = await self.planner("build v1", f"Plan and build the pack (your instructions, Build). {start} "
                                       f"The gate printed:\n\n```text\n{out}\n```")
            await self.publish(first)
            await self.qa_until_pass()
            await self.challenge_rounds()
            self.challenger_done()
            self.planner_done()
        except Blocked as e:
            reasons.append(f"closed by the harness: {e}")
            self.say("lead", TEAMMATES, "STOPPED", str(e), version=self.version)
        return await self.close(reasons)

    def back_up_plan(self):
        """Move the existing plan and pack to plan-backups/<stamp>/ (same relative paths), so the planner
        writes a new plan. Neither role may read the backups (team_agents)."""
        found = [rel for rel in PACK if (self.root / rel).exists()]
        if not found:
            self.emit({"type": "plan_backup", "folder": None, "files": []})
            return
        stamp = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        dest, k = self.root / BACKUPS / stamp, 1
        while dest.exists():
            k += 1
            dest = self.root / BACKUPS / f"{stamp}-{k}"
        moved = sorted(tree_hashes(self.root, found))
        for rel in found:
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            os.replace(self.root / rel, dest / rel)
        folder = dest.relative_to(self.root).as_posix()
        self.emit({"type": "plan_backup", "folder": folder, "files": moved})
        self.say("lead", TEAMMATES, "PLAN BACKUP", f"Fresh plan: moved {len(moved)} files of the previous plan and "
                 f"pack to {folder}/ (audit-plan.json, the three documents, pack-figures.json, samples/).")

    async def close(self, reasons):
        """The qa-reviewer's final run (Step 5) and review.md."""
        reasons = list(reasons)
        self.close_rows(f"accepted, not verified: the stage stopped at v{self.version}")
        self.write_challenges()
        changed = changed_files(self.fp, tree_hashes(self.root, PROTECTED))
        if changed:
            reasons.append(f"inputs changed: {', '.join(changed)}")
        code, gate_out = await self.py(BUILD, "--gate")
        gate_final = next((l for l in gate_out.splitlines() if l.startswith("GATE OK")), None)
        if code != 0 or gate_final is None:
            reasons.append("the gate did not print GATE OK")
        try:
            final = await self.run_checks(final=True)
            final_text = final.output
            if not final.passed:
                reasons.append(f"the final run printed {final.verdict}:")
                reasons += final.points
        except Blocked as e:
            final, final_text = None, str(e)
            reasons.append(str(e))
        last = self.versions[-1] if self.versions else None
        if last is None or last["verdict"] != "PASS":
            if not any("closed by the harness" in r for r in reasons):
                reasons.append("closed by the harness before a version passed")
        elif final is not None and not pack_parts(last["pack"]) <= pack_parts(final.pack):
            reasons.append(f"the pack changed after QA v{last['n']}: PASS")
        verdict = READY if not reasons else BLOCKED
        self.write_review(verdict, reasons, final_text, gate_final)
        v = f"v{last['n']}" if last else "none"
        text = ["QA DONE", f"Verdict: {verdict}", f"Version: {v}; {final.verdict if final else 'no final run'}"]
        if verdict == BLOCKED:
            text += [f"- {r}" for r in reasons]
        else:
            text.append("The auditor's sign-off block is at the end of outputs/review.md.")
        text += [f"- QA v{q['version']} #{q['n']} answered for the auditor" for q in self.qa_for_auditor]
        self.say("qa-reviewer", ["lead", "planner"], "QA DONE", "\n".join(text), verdict=verdict)
        fa = [c for c in self.challenges if c["status"] == "for the auditor"]
        summary = (f"{verdict} on {v}. Challenges: {len(self.challenges)}, for the auditor: "
                   + (", ".join(f"#{c['n']} [{c['type']}] {c['risk']}" for c in fa) or "none")
                   + f". Spent ${self.spent:.2f} of the ${self.cap:.2f} cap."
                   + ("" if verdict == READY else " Reasons: " + " ".join(reasons)))
        return TeamOutcome(verdict, last["n"] if last else 0, round(self.spent, 6), reasons, summary)


async def run_team(root, cfg, agents, emit, env=None):
    return await Team(root, cfg, agents, emit, env=env).run()
