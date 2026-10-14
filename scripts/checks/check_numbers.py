#!/usr/bin/env python3
"""QA number check: every figure in the three pack documents is a value in the pack's sources.

    .venv/bin/python -I scripts/checks/check_numbers.py

A figure is a number of three or more digits, or any number with a £ sign, in
outputs/planning-memo.md, outputs/risk-control-matrix.md or
outputs/audit-program.md. Each must equal (to the penny) a number in
outputs/analytics.json, outputs/pack-figures.json, outputs/rules.json (its
numbers and the £ amounts its text prints) or the net_amount column of
outputs/samples/*.csv.

Skipped, and counted as skipped: row IDs (Over500_..._published:r123), rule,
risk, control, test, PBC and history IDs (CPR-12, R-01, C-01, T-01, PBC-01,
AUD-16), dates and timestamps, years and year ranges, clause, section, table,
figure and page references (clause 5.2.1, page 12, p12), $.paths, file paths,
citations and sha256 hashes.

Also checks that pack-figures.json was built from the current files: its
recorded sha256 for audit-plan.json, analytics.json, history.json, rules.json,
risk-ratings.json and spend-clean.csv must match the files on disk.

Exit 0 when everything passes, 1 otherwise.
"""

import csv
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_lib as Q  # noqa: E402

NAME = "check_numbers"

# Spans masked before figures are read, in this order: (kind, pattern).
MASKS = [
    ("citations, paths and hashes", re.compile(r"`[^`]*`")),  # only some backtick spans; see code_span_kind
    ("row IDs", Q.TX_ID_RE),
    ("$.paths", re.compile(r"\$\.[^\s`|)]+")),
    ("file paths", re.compile(r"[\w./-]*/[\w./-]+|[\w-]+\.(?:pdf|csv|json|md|xlsx|py)\b")),
    ("IDs", re.compile(r"\b[A-Z][A-Za-z]{0,5}-\d+\b")),
    ("dates", re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?\b"
                         r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b")),
    ("years", re.compile(r"(?<![£\d.,])\b(?:19|20)\d{2}(?:\s?[/–-]\s?\d{2,4})?\b(?![.,]\d|%)")),
    ("clause and page references", re.compile(
        r"(?i)\b(?:clauses?|sections?|para(?:graph)?s?|pages?|pp?\.|tables?|figures?|appendix|appendices)"
        r"\s+\d+(?:\.\d+)*(?:\s*(?:-|–|to|and|,)\s*\d+(?:\.\d+)*)*"
        r"|\b\d+(?:\.\d+){2,}\b")),
]
FIGURE_RE = re.compile(r"(?<![\w.£-])(-?£\s?-?\d[\d,]*(?:\.\d+)?|-?\d[\d,]*(?:\.\d+)?)(?![\w£])")
HASH_RE = re.compile(r"^[0-9a-f]{32,}$")
REF_COLUMNS = ("clause", "clauses", "page", "pages", "section")


def code_span_kind(span):
    """A backtick span is masked only when it is a citation, a path or a hash."""
    inner = span.strip("`").strip()
    if re.match(r"(rule|metric|history):", inner) or inner.startswith("$.") or HASH_RE.match(inner) \
            or "/" in inner or re.search(r"\.(pdf|csv|json|md|xlsx|py)$", inner):
        return True
    return False


def dec(v):
    try:
        return Decimal(v)
    except (InvalidOperation, ValueError, TypeError):
        return None


def add_value(values, v):
    if isinstance(v, bool) or v is None:
        return
    if isinstance(v, (int, float)):
        values.add(Decimal(f"{v:.2f}"))
        values.add(Decimal(repr(v)) if isinstance(v, float) else Decimal(v))


def numbers_in(obj, values):
    if isinstance(obj, dict):
        for v in obj.values():
            numbers_in(v, values)
    elif isinstance(obj, list):
        for v in obj:
            numbers_in(v, values)
    else:
        add_value(values, obj)


def strings_in(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings_in(v)


def source_values(root, pf, res):
    out = root / "outputs"
    values = set()
    for name in ("analytics.json", "pack-figures.json", "rules.json"):
        data = pf if name == "pack-figures.json" else Q.load_json(out / name, res, name)
        if data is None:
            continue
        if name == "pack-figures.json":
            for key in ("figures", "placeholders"):
                for f in data.get(key, []):
                    numbers_in(f.get("value"), values)
                    v = f.get("value")
                    if isinstance(v, str) and dec(v.replace(",", "")) is not None:
                        values.add(dec(v.replace(",", "")))
        else:
            numbers_in(data, values)
        if name == "rules.json":
            for s in strings_in(data):
                for m in re.finditer(r"£\s?(\d[\d,]*(?:\.\d+)?)\s*(million|m\b)?", s, re.I):
                    v = dec(m.group(1).replace(",", ""))
                    if v is not None:
                        values.add(v * 1_000_000 if m.group(2) else v)
    files = sorted((out / "samples").glob("T-*.csv"))
    for p in files:
        with p.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                v = dec((row.get("net_amount") or "").strip())
                if v is not None:
                    values.add(v)
    return values


def check_provenance(root, pf, res):
    files = {"audit-plan.json": root / "outputs/audit-plan.json", "analytics.json": root / "outputs/analytics.json",
             "history.json": root / "outputs/history.json", "rules.json": root / "outputs/rules.json",
             "risk-ratings.json": root / "outputs/risk-ratings.json",
             "spend-clean.csv": root / "outputs/analytics-full/spend-clean.csv"}
    recorded = pf.get("inputs") or {}
    for name, p in files.items():
        res.count("pack inputs fingerprinted")
        if name not in recorded:
            res.fail(f"pack-figures.json records no sha256 for {name}")
        elif not p.is_file():
            res.fail(f"{name} not found at {p}")
        elif Q.sha256(p) != recorded[name]:
            res.fail(f"pack-figures.json was built from a different {name} (recorded {recorded[name][:12]}, on disk "
                     f"{Q.sha256(p)[:12]}): the pack is stale")


def figures_in_line(line, skipped, header=None):
    chars = list(line)

    def blank(a, b):
        chars[a:b] = " " * (b - a)

    if header:  # a table row: the cells of a Clause, Page or Section column are references
        pos = [m.start() for m in re.finditer(r"(?<!\\)\|", line)]
        for n, (a, b) in enumerate(zip(pos, pos[1:])):
            if n < len(header) and header[n].lower() in REF_COLUMNS and re.search(r"\d", line[a + 1:b]):
                skipped["clause and page references"] = skipped.get("clause and page references", 0) + 1
                blank(a + 1, b)
    for kind, rx in MASKS:
        cur = "".join(chars)
        for m in rx.finditer(cur):
            if kind == "citations, paths and hashes" and not code_span_kind(m.group(0)):
                continue
            if re.search(r"\d", m.group(0)):
                skipped[kind] = skipped.get(kind, 0) + 1
            blank(*m.span())
    out = []
    for m in FIGURE_RE.finditer("".join(chars)):
        tok = m.group(1).rstrip(",")
        digits = sum(c.isdigit() for c in tok)
        if "£" in tok or digits >= 3:
            out.append(tok)
    return out


def run(root=Q.ROOT_DEFAULT):
    root = Path(root).resolve()
    res = Q.Result(NAME)
    pf = Q.load_json(root / "outputs/pack-figures.json", res, "pack-figures.json")
    if pf is not None:
        check_provenance(root, pf, res)
    values = source_values(root, pf, res)
    skipped = {}
    for doc in Q.PACK_DOCS:
        text = Q.read_text(root / "outputs" / doc, res, doc)
        if text is None:
            continue
        res.count("documents")
        header = None
        for ln, line in enumerate(text.splitlines(), 1):
            cells = Q.md_cells(line)
            if cells is None:
                header = None
            elif header is None:
                header = cells
            for tok in figures_in_line(line, skipped, header if cells is not None else None):
                res.count("figures")
                v = dec(tok.replace("£", "").replace(",", "").replace(" ", ""))
                if v is None:
                    res.fail(f"{doc} line {ln}: {tok!r} is not a readable number")
                elif v not in values:
                    res.fail(f"{doc} line {ln}: {tok} is not a value in analytics.json, pack-figures.json, "
                             "rules.json or outputs/samples/*.csv")
    if skipped:
        res.notes.append("skipped: " + ", ".join(f"{k} {v:,}" for k, v in skipped.items()))
    return res


def main(argv=None):
    a = Q.parse_args(__doc__, argv)
    return run(a.root).print()


if __name__ == "__main__":
    sys.exit(main())
