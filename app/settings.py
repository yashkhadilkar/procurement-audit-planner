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

# Stages in flow order. kind: "agent" runs through the Agent SDK, "stub" is not
# built yet (501), "none" has no agent (its endpoint is /api/signoff).
STAGES = {
    "rules": "agent",
    "spend": "agent",
    "history": "agent",
    "register": "agent",
    "revise": "agent",
    "team": "stub",
    "signoff": "none",
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


def load_config(path=CONFIG_FILE):
    """{"stages": {stage: {"model", "max_budget_usd"}}, "forward_subagent_text": bool}."""
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
    return {"stages": stages, "forward_subagent_text": bool(raw.get("forward_subagent_text", False))}
