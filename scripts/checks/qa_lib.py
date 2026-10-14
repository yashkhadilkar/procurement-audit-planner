"""Shared helpers for the QA checks in scripts/checks/.

The checks read the pack and its inputs directly and never import
build_pack.py or build_register.py, so the pack is checked independently of
the code that built it. Everything here is written for the checks alone.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

CHECKS_DIR = Path(__file__).resolve().parent
ROOT_DEFAULT = CHECKS_DIR.parents[1]
VERIFIER = ROOT_DEFAULT / ".claude/skills/extract-rules/verify_quotes.py"

PACK_DOCS = ("planning-memo.md", "risk-control-matrix.md", "audit-program.md")
SPEND_SHEET = "Data to publish"
SPEND_COLUMNS = ("Service", "Expenditure category", "Narrative", "Date", "Net amount", "Supplier name")
HEADER_SEARCH_ROWS = 20
PRIMARY_TAG = "general_procurement"

# Prose fields of a rated risk in risk-ratings.json whose citations count as
# "cited by the risk".
RISK_PROSE_FIELDS = ("description", "likelihood.justification", "likelihood.repeat_uplift.justification",
                     "impact.justification", "evidence", "proposed_focus")
IN_SCOPE_DECISIONS = ("Approve", "Amend")
# Figure 1 labels and Table 4 bands that make a risk "High" for the scope check.
HIGH_LABELS = ("High", "Extreme")
HIGH_BANDS = ("Medium High", "Extreme")

TX_ID_RE = re.compile(r"[A-Za-z0-9_\-]+:r\d+\b")
RULE_TAG_RE = re.compile(r"\[rule:\s*([^\]\s]+)\s*\]|`rule:([^`\s]+)`")
CLOSED_STATUSES = ("resolved", "declined", "for the auditor")


class Result:
    def __init__(self, name):
        self.name = name
        self.counts = {}     # what was checked: label -> number
        self.failures = []   # one line per failing item
        self.notes = []      # informational lines (never a pass or a fail)

    def count(self, label, n=1):
        self.counts[label] = self.counts.get(label, 0) + n

    def fail(self, item):
        self.failures.append(item)

    @property
    def passed(self):
        return not self.failures

    def checked(self):
        return ", ".join(f"{v:,} {k}" for k, v in self.counts.items()) or "nothing"

    def print(self):
        print(f"{self.name}: {'PASS' if self.passed else 'FAIL'} ({self.checked()}; "
              f"{len(self.failures)} failure{'s' if len(self.failures) != 1 else ''})")
        for f in self.failures:
            print(f"  FAIL {f}")
        for n in self.notes:
            print(f"  note: {n}")
        return 0 if self.passed else 1


def parse_args(doc, argv, final=False):
    ap = argparse.ArgumentParser(description=doc.strip().splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT_DEFAULT,
                    help="repo root holding data/ and outputs/ (tests only; QA runs without it)")
    if final:
        ap.add_argument("--final", action="store_true",
                        help="final run before review.md: also check challenges.md")
    return ap.parse_args(argv)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path, res, label=None):
    """The parsed file, or None after recording a failure."""
    label = label or Path(path).name
    if not Path(path).is_file():
        res.fail(f"{label} not found at {path}")
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        res.fail(f"{label} is not valid JSON: {e}")
        return None


def read_text(path, res, label=None):
    label = label or Path(path).name
    if not Path(path).is_file():
        res.fail(f"{label} not found at {path}")
        return None
    return Path(path).read_text(encoding="utf-8")


def get_field(obj, dotted):
    for part in dotted.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def rule_tags(text):
    return [a or b for a, b in RULE_TAG_RE.findall(text or "")]


# ---------------------------------------------------------------- citations

def scan_citations(text):
    """[(kind, ref)] for every [rule:..], [metric:..], [history:..] tag
    (brackets nested inside a metric path are allowed) and every backticked
    `kind:ref`."""
    out, i = [], 0
    start = re.compile(r"\[(rule|metric|history):")
    while True:
        m = start.search(text, i)
        if not m:
            break
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += {"[": 1, "]": -1}.get(text[j], 0)
            j += 1
        if depth:
            out.append((m.group(1), None))  # not closed
            break
        out.append((m.group(1), text[m.end():j - 1].strip()))
        i = j
    for m in re.finditer(r"`(rule|metric|history):([^`]+)`", text):
        out.append((m.group(1), m.group(2).strip()))
    return out


PATH_TOKEN_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]|\['([^']*)'\]|\[([A-Za-z_][A-Za-z0-9_]*)=([^\]]+)\]")


def resolve_path(data, path):
    """Value at a $.path in data; raises ValueError if it does not resolve to
    exactly one non-null value."""
    path = path.strip()
    if not path.startswith("$"):
        raise ValueError("path must start with $")
    cur, pos = data, 1
    while pos < len(path):
        m = PATH_TOKEN_RE.match(path, pos)
        if not m:
            raise ValueError(f"bad path syntax at {path[pos:]!r}")
        key, idx, qkey, field, lit = m.groups()
        if key is not None or qkey is not None:
            k = key if key is not None else qkey
            if not isinstance(cur, dict) or k not in cur:
                raise ValueError(f"no key {k!r}")
            cur = cur[k]
        elif idx is not None:
            if not isinstance(cur, list) or int(idx) >= len(cur):
                raise ValueError(f"no index [{idx}]")
            cur = cur[int(idx)]
        else:
            lit = lit.strip()
            if len(lit) >= 2 and lit[0] == lit[-1] == "'":
                want = lit[1:-1]
            else:
                try:
                    want = int(lit)
                except ValueError:
                    try:
                        want = float(lit)
                    except ValueError:
                        raise ValueError(f"filter value {lit!r} is neither a number nor a 'quoted string'")
            if not isinstance(cur, list):
                raise ValueError(f"filter [{field}=...] on a non-list")
            hits = [x for x in cur if isinstance(x, dict) and field in x and not isinstance(x[field], bool)
                    and x[field] == want]
            if len(hits) != 1:
                raise ValueError(f"filter [{field}={lit}] matched {len(hits)} items, needs exactly 1")
            cur = hits[0]
        pos = m.end()
    if cur is None:
        raise ValueError("value is null")
    return cur


def history_ids(history):
    ids = set()
    for v in (history or {}).values():
        if isinstance(v, list):
            ids.update(x["id"] for x in v if isinstance(x, dict) and isinstance(x.get("id"), str))
    return ids


# ---------------------------------------------------------------- markdown

def md_cells(line):
    s = line.strip()
    if not s.startswith("|"):
        return None
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s.strip().strip("|"))]


def md_tables(text):
    """[(heading, header cells, [(line number, row cells)])] for every table;
    heading is the last ## or ### heading above it."""
    tables, heading, cur = [], None, None
    for ln, line in enumerate(text.splitlines(), 1):
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            cur = None
            continue
        cells = md_cells(line)
        if cells is None:
            cur = None
            continue
        if cur is None:
            cur = (heading, cells, [])
            tables.append(cur)
        elif all(set(c) <= set("-: ") for c in cells):
            continue
        else:
            cur[2].append((ln, cells))
    return tables


def find_table(text, first_col, heading=None):
    """Rows of the first table whose header starts with first_col (and whose
    heading starts with heading, if given), as [(line, {header: cell})]."""
    for h, header, rows in md_tables(text):
        if header and header[0] == first_col and (heading is None or (h or "").startswith(heading)):
            return [(ln, dict(zip(header, cells + [""] * (len(header) - len(cells))))) for ln, cells in rows], header
    return None, None


def md_sections(text, level):
    """{heading text: (first line number, body)} for headings of exactly level #s."""
    out, cur, start, body = {}, None, 0, []
    for ln, line in enumerate(text.splitlines(), 1):
        depth = len(line) - len(line.lstrip("#")) if line.startswith("#") else 0
        if depth and depth <= level:  # a heading at this level or above ends the section
            if cur is not None:
                out[cur] = (start, "\n".join(body))
            cur, start, body = (line[depth:].strip(), ln, []) if depth == level else (None, 0, [])
            continue
        if cur is not None:
            body.append(line)
    if cur is not None:
        out[cur] = (start, "\n".join(body))
    return out


# ---------------------------------------------------------------- decisions

def parse_comments(text):
    """{id: {table, decision, comment, applied, line}} from auditor-comments.md."""
    out, table, header = {}, None, None
    for ln, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("## "):
            t = s[3:].strip().lower()
            table = "rated" if t.startswith("rated") else "noted" if t.startswith("noted") else None
            header = None
            continue
        cells = md_cells(s) if table else None
        if cells is None:
            continue
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        row = dict(zip(header, cells))
        key = row.get("risk") if table == "rated" else row.get("item")
        out[key] = {"table": table, "decision": row.get("decision", ""), "comment": row.get("comment", ""),
                    "applied": row.get("applied", ""), "line": ln}
    return out


def scope(ratings, decisions):
    """(in-scope risk ids, rejected risk ids, left-out noted ids, undecided ids)."""
    in_scope, rejected, left_out, undecided = [], [], [], []
    for r in ratings.get("risks", []):
        rid, dec = r["risk_id"], decisions.get(r["risk_id"], {}).get("decision", "")
        if r.get("status") == "rejected":
            rejected.append(rid)
        elif dec in IN_SCOPE_DECISIONS:
            in_scope.append(rid)
        elif not dec:
            undecided.append(rid)
    for x in ratings.get("noted_not_rated", []):
        dec = decisions.get(x["history"], {}).get("decision", "")
        if dec == "Leave out":
            left_out.append(x["history"])
        elif not dec:
            undecided.append(x["history"])
    return in_scope, rejected, left_out, undecided


# ---------------------------------------------------------------- PDF text

PRIVATE_USE = re.compile("[-]")


def norm(text):
    """Whitespace-insensitive, otherwise exact."""
    text = unicodedata.normalize("NFKC", text)
    text = PRIVATE_USE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def pdf_pages(pdf):
    """Per page, the normalised texts a quote may match (plain, layout, and
    layout with line-end hyphens rejoined). Raises RuntimeError."""
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext not found on PATH (install poppler)")
    texts = []
    for layout in (False, True):
        cmd = ["pdftotext"] + (["-layout"] if layout else []) + [str(pdf), "-"]
        out = subprocess.run(cmd, capture_output=True, check=True).stdout.decode("utf-8")
        pages = out.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        texts.append(pages)
    plain, layout = texts
    if len(plain) != len(layout) or not plain:
        raise RuntimeError(f"pdftotext page split mismatch (plain {len(plain)}, layout {len(layout)})")
    return [{norm(p), norm(l), norm(re.sub(r"-[ \t]*\n[ \t]*", "-", l))} for p, l in zip(plain, layout)]
