"""Run records: the live event list a run streams, and WORK_DIR/runs/<id>.json.

Every event passes through redact() before it is stored or streamed, so a
secret that turns up in agent output (an `env` dump, say) never leaves the
process.
"""

import asyncio
import json
import os
import re
import secrets as _secrets
import time
from datetime import datetime, timezone
from pathlib import Path

RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[a-z]+-[0-9a-f]{6}$")
FLUSH_SECONDS = 2.0


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id(stage):
    return f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{stage}-{_secrets.token_hex(3)}"


def make_redactor(values):
    values = sorted({v for v in values if v and len(v) >= 4}, key=len, reverse=True)

    def redact(obj):
        if isinstance(obj, str):
            for v in values:
                obj = obj.replace(v, "[redacted]")
            return obj
        if isinstance(obj, dict):
            return {k: redact(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [redact(v) for v in obj]
        return obj

    return redact


def write_json(path, data):
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def summary(record):
    return {k: v for k, v in record.items() if k != "events"}


class RunHandle:
    """One run: its record, its events, and a wake-up for event-stream subscribers."""

    def __init__(self, record, path, redact):
        self.record = record
        self.path = Path(path)
        self.redact = redact
        self.events = record.setdefault("events", [])
        self.done = False
        self.changed = asyncio.Event()
        self._flushed = 0.0

    @property
    def id(self):
        return self.record["id"]

    def emit(self, event):
        event = self.redact(dict(event))
        event = {"seq": len(self.events) + 1, "t": now_iso(), **event}
        self.events.append(event)
        old, self.changed = self.changed, asyncio.Event()
        old.set()
        if time.monotonic() - self._flushed > FLUSH_SECONDS:
            self.flush()

    def update(self, **fields):
        self.record.update(self.redact(fields))

    def finish(self):
        self.done = True
        self.flush()
        old, self.changed = self.changed, asyncio.Event()
        old.set()

    def flush(self):
        self._flushed = time.monotonic()
        write_json(self.path, self.record)


def load_summaries(runs_dir):
    """{id: summary} for every run file; a run left 'running' by a stopped server becomes 'interrupted'."""
    out = {}
    for p in sorted(Path(runs_dir).glob("*.json")):
        if not RUN_ID_RE.match(p.stem):
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if rec.get("status") == "running":
            rec["status"] = "interrupted"
            rec["error"] = "the server stopped while this run was in progress"
            write_json(p, rec)
        out[rec.get("id", p.stem)] = summary(rec)
    return out
