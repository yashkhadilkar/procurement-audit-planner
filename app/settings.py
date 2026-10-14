"""Paths, secrets and the per-stage model config.

ANTHROPIC_API_KEY and ACCESS_CODE come from the environment, or failing that
from the repo's .env. They are held in a Secrets object whose repr hides them;
nothing in the app prints, logs or returns them.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG_FILE = Path(__file__).resolve().parent / "config.json"
SECRET_NAMES = ("ANTHROPIC_API_KEY", "ACCESS_CODE")

# Stages in flow order. kind: "agent" runs through the Agent SDK, "team" is the
# harness-run agent team (app/team.py), "stub" is not built yet (501), "none"
# has no agent (its endpoint is /api/signoff).
STAGES = {
    "rules": "agent",
    "spend": "agent",
    "history": "agent",
    "register": "agent",
    "revise": "agent",
    "team": "team",
    "signoff": "none",
}
TEAM_DEFAULTS = {
    "planner_model": "claude-sonnet-5-5",
    "challenger_model": "claude-haiku-5-5",
    "max_cost_usd": 3.0,        # hard cap for the whole team stage, checked before every model call
    "challenges_round1": 4,
    "challenges_round2": 2,
    "qa_fix_attempts": 3,       # across the whole stage
    "fresh_plan": True,         # move the existing plan and pack to plan-backups/ first; false reuses the plan
}


@dataclass(frozen=True)
class Secrets:
    api_key: str | None = field(default=None, repr=False)
    access_code: str | None = field(default=None, repr=False)

    def __repr__(self):
        return (f"Secrets(api_key={'set' if self.api_key else 'missing'}, "
                f"access_code={'set' if self.access_code else 'missing'})")

    def values(self):
        return [v for v in (self.api_key, self.access_code) if v]


def _read_dotenv(path):
    """The SECRET_NAMES entries of a .env file; never echoes a line."""
    found = {}
    if not path.is_file():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        name, sep, value = line.partition("=")
        name = name.strip()
        if sep and name in SECRET_NAMES:
            value = value.strip().strip('"').strip("'")
            if value:
                found[name] = value
    return found


def load_secrets(environ=None, dotenv=REPO / ".env"):
    environ = os.environ if environ is None else environ
    file_values = _read_dotenv(Path(dotenv)) if dotenv else {}

    def pick(name):
        return environ.get(name) or file_values.get(name) or None

    return Secrets(api_key=pick("ANTHROPIC_API_KEY"), access_code=pick("ACCESS_CODE"))


def work_dir(environ=None):
    """WORK_DIR from the environment (default ./work); relative paths are taken from the repo root."""
    environ = os.environ if environ is None else environ
    p = Path(environ.get("WORK_DIR") or "work").expanduser()
    return (p if p.is_absolute() else REPO / p).resolve()


def team_config(raw, path):
    cfg = {**TEAM_DEFAULTS, **(raw or {})}
    unknown = set(cfg) - set(TEAM_DEFAULTS)
    if unknown:
        raise ValueError(f"{path}: unknown team settings {sorted(unknown)}")
    for k in ("planner_model", "challenger_model"):
        if not isinstance(cfg[k], str) or not cfg[k]:
            raise ValueError(f"{path}: team.{k} must be a model name")
    cap = cfg["max_cost_usd"]
    if not isinstance(cap, (int, float)) or isinstance(cap, bool) or cap <= 0:
        raise ValueError(f"{path}: team.max_cost_usd must be a positive number")
    cfg["max_cost_usd"] = float(cap)
    for k in ("challenges_round1", "challenges_round2", "qa_fix_attempts"):
        if not isinstance(cfg[k], int) or isinstance(cfg[k], bool) or cfg[k] < 0:
            raise ValueError(f"{path}: team.{k} must be a whole number, 0 or more")
    if not isinstance(cfg["fresh_plan"], bool):
        raise ValueError(f"{path}: team.fresh_plan must be true or false")
    return cfg


def load_config(path=CONFIG_FILE):
    """{"stages": {stage: {"model", "max_budget_usd"}}, "team": {...}, "forward_subagent_text": bool}."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    default = raw.get("default", {})
    overrides = raw.get("stages", {})
    unknown = set(overrides) - {s for s, k in STAGES.items() if k == "agent"}
    if unknown:
        raise ValueError(f"{path}: unknown or agentless stages {sorted(unknown)}")
    stages = {}
    for name, kind in STAGES.items():
        if kind != "agent":
            continue
        cfg = {**default, **overrides.get(name, {})}
        model, budget = cfg.get("model"), cfg.get("max_budget_usd")
        if not isinstance(model, str) or not model:
            raise ValueError(f"{path}: stage {name} has no model")
        if not isinstance(budget, (int, float)) or isinstance(budget, bool) or budget <= 0:
            raise ValueError(f"{path}: stage {name} needs a positive max_budget_usd")
        stages[name] = {"model": model, "max_budget_usd": float(budget)}
    return {"stages": stages, "team": team_config(raw.get("team"), path),
            "forward_subagent_text": bool(raw.get("forward_subagent_text", False))}
