"""The two human gates: auditor decisions (auditor-comments.md) and sign-off (review.md).

Both edit only the cells a person fills in, write through a temporary file and
replace the original only once the result validates, so a refused request
leaves the file byte for byte as it was.
"""

import importlib.util
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from .settings import REPO

BUILDER = REPO / ".claude/skills/risk-assessment/build_register.py"
CELL_SPLIT = re.compile(r"(?<!\\)\|")


class GateError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


@lru_cache(maxsize=1)
def builder():
    """build_register.py from the repo's risk-assessment skill (its parser and decision vocabulary)."""
    spec = importlib.util.spec_from_file_location("build_register", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cells(line):
    return [c.strip() for c in CELL_SPLIT.split(line.strip().strip("|"))]


def _row(cells):
    return "| " + " | ".join(cells) + " |"


def _check_cell(field, value):
    if "|" in value or "\n" in value or "\r" in value:
        raise GateError(422, f"{field} may not contain | or a line break")


def _atomic_write(path, text, validate=None):
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        if validate:
            validate(tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- gate 1

def gate_status(path):
    """Summary of auditor-comments.md as build_register.py parses it."""
    path = Path(path)
    if not path.exists():
        return {"exists": False}
    try:
        rows = builder().parse_comments(path)
    except ValueError as e:
        return {"exists": True, "error": str(e)}
    acting = builder().ACTING
    undecided = [k for k, r in rows.items() if not r["decision"]]
    return {
        "exists": True,
        "rows": len(rows),
        "decided": len(rows) - len(undecided),
        "undecided": undecided,
        "closed": bool(rows) and not undecided,
        "pending": [k for k, r in rows.items() if r["decision"] in acting and not r["applied"]],
        "decisions": rows,
    }


def apply_decisions(path, decisions):
    """Write auditor decisions into auditor-comments.md.

    decisions: [{"id", "decision", "comment" (optional; omitted keeps the existing
    comment), "clear_applied" (optional)}]. Returns gate_status() afterwards.
    """
    path = Path(path)
    if not path.exists():
        raise GateError(404, "outputs/auditor-comments.md does not exist: run the register stage first")
    if not decisions:
        raise GateError(422, "no decisions given")
    b = builder()
    try:
        current = b.parse_comments(path)
    except ValueError as e:
        raise GateError(409, f"auditor-comments.md does not parse as it stands: {e}")

    wanted = {}
    for d in decisions:
        rid = str(d.get("id", "")).strip()
        if rid not in current:
            raise GateError(422, f"{rid or '(blank)'} is not a row in auditor-comments.md")
        if rid in wanted:
            raise GateError(422, f"{rid} is given twice")
        vocab = b.RATED_DECISIONS if current[rid]["table"] == "rated" else b.NOTED_DECISIONS
        raw = str(d.get("decision", "")).strip()
        if raw.lower() not in vocab:
            raise GateError(422, f"decision {raw!r} for {rid} is not one of {', '.join(vocab.values())}")
        comment = d.get("comment")
        comment = current[rid]["comment"] if comment is None else str(comment).strip()
        _check_cell(f"comment for {rid}", comment)
        decision = vocab[raw.lower()]
        if decision == "Amend" and not comment:
            raise GateError(422, f"Amend for {rid} needs a comment saying exactly what to change")
        wanted[rid] = {"decision": decision, "comment": comment, "clear_applied": bool(d.get("clear_applied"))}

    lines = path.read_text(encoding="utf-8").split("\n")
    table, header = None, None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("## "):
            title = s[3:].strip().lower()
            table = "rated" if title.startswith("rated") else "noted" if title.startswith("noted") else None
            header = None
            continue
        if table is None or not s.startswith("|"):
            continue
        cells = _cells(s)
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        key = cells[header.index("risk" if table == "rated" else "item")]
        if key not in wanted:
            continue
        w = wanted[key]
        cells[header.index("decision")] = w["decision"]
        cells[header.index("comment")] = w["comment"]
        if w["clear_applied"]:
            cells[header.index("applied")] = ""
        lines[i] = _row(cells)

    def validate(tmp):
        try:
            parsed = b.parse_comments(tmp)
        except ValueError as e:
            raise GateError(422, f"the result does not parse: {e}")
        for rid, w in wanted.items():
            got = parsed.get(rid, {})
            if got.get("decision") != w["decision"] or got.get("comment") != w["comment"]:
                raise GateError(500, f"{rid} did not round-trip through the parser; nothing written")

    _atomic_write(path, "\n".join(lines), validate)
    return gate_status(path)


# ---------------------------------------------------------------- sign-off

READY = "READY FOR SIGN-OFF"
YES_NO = {"yes": "Yes", "no": "No"}
SIGN_DECISIONS = {"signed off": "Signed off", "not signed off": "Not signed off"}
SIGNOFF_ROWS = {  # field -> how its Item cell starts
    "verdict": "QA verdict",
    "version": "Pack version",
    "challenges": "Challenges marked",
    "qa_points": "QA points answered",
    "decision": "Decision",
    "auditor": "Auditor",
    "date": "Date",
    "comment": "Comment",
}


def _section(lines, title):
    """(start, end) line indexes of a '## title' section's body."""
    start = next((i + 1 for i, l in enumerate(lines) if l.strip() == f"## {title}"), None)
    if start is None:
        return None
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, end


def _signoff_table(lines):
    sec = _section(lines, "Auditor sign-off")
    if sec is None:
        return {}
    found = {}
    for i in range(*sec):
        s = lines[i].strip()
        if not s.startswith("|"):
            continue
        cells = _cells(s)
        if len(cells) != 2:
            continue
        for field, label in SIGNOFF_ROWS.items():
            if field not in found and (cells[0] == label if field in ("decision", "auditor", "date", "comment", "verdict")
                                       else cells[0].startswith(label)):
                found[field] = (i, cells)
    return found


def review_status(path):
    path = Path(path)
    if not path.exists():
        return {"exists": False}
    lines = path.read_text(encoding="utf-8").split("\n")
    verdict = None
    sec = _section(lines, "Verdict")
    if sec:
        verdict = next((lines[i].strip().strip("*").strip() for i in range(*sec) if lines[i].strip()), None)
    table = _signoff_table(lines)
    cell = {f: c[1] for f, (_, c) in table.items()}
    return {
        "exists": True,
        "verdict": verdict,
        "table_verdict": cell.get("verdict"),
        "pack_version": cell.get("version"),
        "decision": cell.get("decision"),
        "auditor": cell.get("auditor") or None,
        "date": cell.get("date") or None,
        "signed": bool(cell.get("auditor")),
    }


def sign_off(path, auditor, decision, challenges_considered, qa_points_considered, comment="", on=None):
    """Fill the auditor's sign-off block in review.md; only when the verdict is READY FOR SIGN-OFF."""
    path = Path(path)
    if not path.exists():
        raise GateError(404, "outputs/review.md does not exist: the agent team has not produced a review")
    lines = path.read_text(encoding="utf-8").split("\n")
    status = review_status(path)
    if status["verdict"] != READY or status["table_verdict"] != READY:
        raise GateError(409, f"sign-off refused: the QA verdict is {status['verdict'] or 'missing'}, "
                             f"not {READY}")
    table = _signoff_table(lines)
    missing = [SIGNOFF_ROWS[f] for f in SIGNOFF_ROWS if f not in table]
    if missing:
        raise GateError(409, f"review.md has no sign-off row for: {', '.join(missing)}")
    if status["signed"]:
        raise GateError(409, f"review.md is already signed: {status['decision']} by {status['auditor']} "
                             f"on {status['date']}")

    auditor = str(auditor or "").strip()
    if not auditor:
        raise GateError(422, "auditor is required")
    _check_cell("auditor", auditor)
    comment = str(comment or "").strip()
    _check_cell("comment", comment)
    d = SIGN_DECISIONS.get(str(decision or "").strip().lower())
    if not d:
        raise GateError(422, f"decision must be one of {', '.join(SIGN_DECISIONS.values())}")

    def yes_no(field, v):
        if isinstance(v, bool):
            return "Yes" if v else "No"
        out = YES_NO.get(str(v or "").strip().lower())
        if not out:
            raise GateError(422, f"{field} must be Yes or No")
        return out

    challenges = yes_no("challenges_considered", challenges_considered)
    qa_points = yes_no("qa_points_considered", qa_points_considered)
    if d == "Signed off" and "No" in (challenges, qa_points):
        raise GateError(422, "a pack cannot be signed off before the challenges and QA points "
                             "marked for the auditor have been considered")
    values = {"challenges": challenges, "qa_points": qa_points, "decision": d, "auditor": auditor,
              "date": (on or date.today()).isoformat(), "comment": comment}
    for field, value in values.items():
        i, cells = table[field]
        lines[i] = _row([cells[0], value])

    def validate(tmp):
        after = review_status(tmp)
        if not (after["signed"] and after["decision"] == d and after["auditor"] == auditor
                and after["verdict"] == READY):
            raise GateError(500, "the sign-off did not round-trip; nothing written")

    _atomic_write(path, "\n".join(lines), validate)
    return review_status(path)
