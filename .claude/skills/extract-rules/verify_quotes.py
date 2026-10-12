#!/usr/bin/env python3
"""Verify outputs/rules.json against data/contract-rules.pdf.

Checks the schema, sequential rule ids, declared parameters, clause coverage,
value bands, and that every verbatim quote appears on its stated PDF page.

Usage:
    .venv/bin/python .claude/skills/extract-rules/verify_quotes.py \
        [RULES_JSON] [--pdf PDF]

Exit codes: 0 all checks pass, 1 errors found, 2 could not run.
Stdlib only; needs poppler's pdftotext on PATH.
"""

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

RULE_TYPES = {"threshold", "approval", "required-action", "anti-avoidance"}
SCOPES = {"goods_services", "works", "concession", "light_touch"}
EVIDENCE_SOURCES = {
    "spend_data", "contract_notices", "procurement_portal",
    "decision_records", "contract_documents", "contract_register",
}
NOTE_KINDS = {"contradiction", "gap", "drafting", "interpretation"}

TOP_KEYS = {"source", "parameters", "rules", "excluded", "notes"}
SOURCE_REQUIRED = {"file", "sha256", "pages"}
SOURCE_OPTIONAL = {"title"}
PARAM_KEYS = {"values", "printed_as", "defined_in", "description"}
DEFINED_IN_KEYS = {"clause", "page", "verbatim_quote"}
RULE_REQUIRED = {
    "rule_id", "clause", "page", "type", "scope", "condition", "band_printed",
    "threshold_low", "threshold_low_inclusive", "threshold_low_param",
    "threshold_high", "threshold_high_inclusive", "threshold_high_param",
    "required_action", "approver", "evidence_source", "verbatim_quote",
}
RULE_OPTIONAL = {"covers"}
EXCLUDED_REQUIRED = {"clause", "page", "reason"}
EXCLUDED_OPTIONAL = {"covers"}
NOTE_KEYS = {"kind", "clauses", "issue"}

MIN_FRAGMENT = 10
MAX_REASON = 250

BODY_ID = re.compile(r"^\d+(?:\.\d+)+$")
SECTION_ID = re.compile(r"^\d+$")
APP_ID = re.compile(r"^App([A-Z])-([A-Z]\d?|\d+|fn\d+|intro|closing)$")
APP_ROW_LABEL = re.compile(r"^[A-Z]\d?$")
PARAM_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
RULE_ID = re.compile(r"^CPR-(\d{2,})$")

# Layout-mode line patterns used to detect what the PDF actually numbers.
LINE_BODY_CLAUSE = re.compile(r"^\s*(\d+(?:\.\d+)+)\s+\S")
LINE_APPENDIX = re.compile(r"Appendix\s+([A-Z])\b")
# A row label is followed by wide spacing, or stands alone on its line.
LINE_APP_ROW = re.compile(r"^\s{0,10}([A-Z]\d?)(?:\s{2,}\S|\s*$)")
AMOUNT = re.compile(r"£\s?(\d[\d,]*(?:\.\d+)?)\s*(million|m\b)?", re.IGNORECASE)
PRIVATE_USE = re.compile(r"[-]")


class Report:
    def __init__(self):
        self.errors = []

    def add(self, code, where, msg):
        self.errors.append((code, where, msg))


# ---------------------------------------------------------------- PDF text

def pdftotext_pages(pdf, layout):
    cmd = ["pdftotext"] + (["-layout"] if layout else []) + [str(pdf), "-"]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout.decode("utf-8")
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def norm(text):
    """Whitespace-insensitive, otherwise exact: keeps quotes, dashes, case."""
    text = unicodedata.normalize("NFKC", text)
    text = PRIVATE_USE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def page_variants(plain_pages, layout_pages):
    """Per page, the normalised texts a quote may match against."""
    variants = []
    for plain, layout in zip(plain_pages, layout_pages):
        # Plain mode drops line-end hyphens ("Call-\nIn" -> "CallIn"); the
        # rejoined layout text keeps the printed form ("Call-In").
        rejoined = re.sub(r"-[ \t]*\n[ \t]*", "-", layout)
        variants.append({norm(plain), norm(layout), norm(rejoined)})
    return variants


def detect_clauses(layout_pages):
    """Map every clause number / lettered appendix row printed in the PDF to
    the page it first appears on. Also return the appendices seen."""
    found, appendices = {}, set()
    current_app = None
    for pageno, page in enumerate(layout_pages, start=1):
        for line in page.splitlines():
            head = LINE_APPENDIX.search(line)
            if head and line.strip().startswith("Contract Rules"):
                current_app = head.group(1)
                appendices.add(current_app)
                continue
            if current_app is None:
                m = LINE_BODY_CLAUSE.match(line)
                if m:
                    found.setdefault(m.group(1), pageno)
            else:
                m = LINE_APP_ROW.match(line)
                if m:
                    found.setdefault(f"App{current_app}-{m.group(1)}", pageno)
    return found, appendices


# ---------------------------------------------------------------- helpers

def check_keys(rep, where, obj, required, optional=frozenset()):
    if not isinstance(obj, dict):
        rep.add("SCHEMA", where, "must be an object")
        return False
    missing = required - obj.keys()
    unknown = obj.keys() - required - optional
    if missing:
        rep.add("SCHEMA", where, f"missing keys: {sorted(missing)}")
    if unknown:
        rep.add("SCHEMA", where, f"unknown keys: {sorted(unknown)}")
    return not missing


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def nonempty_str(v):
    return isinstance(v, str) and v.strip() != ""


def check_page(rep, where, page, n_pages):
    if not is_int(page) or not 1 <= page <= n_pages:
        rep.add("SCHEMA", where, f"page must be an integer 1..{n_pages}, got {page!r}")
        return False
    return True


def check_clause_id(rep, where, cid, detected, appendices, allow_section=False):
    """Format check plus existence check against what the PDF prints."""
    if not isinstance(cid, str):
        rep.add("SCHEMA", where, f"clause id must be a string, got {cid!r}")
        return False
    if BODY_ID.match(cid):
        if cid not in detected:
            rep.add("CLAUSE_UNKNOWN", where, f"clause {cid} is not printed in the PDF")
            return False
        return True
    if allow_section and SECTION_ID.match(cid):
        return True
    m = APP_ID.match(cid)
    if not m:
        rep.add("SCHEMA", where, f"bad clause id {cid!r} (expected e.g. 6.16, AppB-B1, AppA-2, AppB-fn3)")
        return False
    app, label = m.groups()
    if app not in appendices:
        rep.add("CLAUSE_UNKNOWN", where, f"Appendix {app} is not in the PDF")
        return False
    if APP_ROW_LABEL.match(label) and cid not in detected:
        rep.add("CLAUSE_UNKNOWN", where, f"row {label} is not printed in Appendix {app}")
        return False
    return True


def quote_fragments(rep, where, quote):
    if isinstance(quote, str):
        frags = [quote]
    elif isinstance(quote, list) and quote and all(isinstance(q, str) for q in quote):
        frags = quote
    else:
        rep.add("SCHEMA", where, "verbatim_quote must be a string or a non-empty list of strings")
        return []
    ok = []
    for i, frag in enumerate(frags):
        w = f"{where}[{i}]" if isinstance(quote, list) else where
        if "..." in frag or "…" in frag:
            rep.add("QUOTE_FORMAT", w, "contains an ellipsis; use a list of contiguous passages instead")
        elif len(norm(frag)) < MIN_FRAGMENT:
            rep.add("QUOTE_FORMAT", w, f"shorter than {MIN_FRAGMENT} characters: {frag!r}")
        else:
            ok.append((w, frag))
    return ok


def check_quote(rep, where, quote, page, variants):
    """Every fragment must appear on the stated page; say where it is if not."""
    for w, frag in quote_fragments(rep, where, quote):
        q = norm(frag)
        if any(q in v for v in variants[page - 1]):
            continue
        elsewhere = [i + 1 for i, vs in enumerate(variants) if any(q in v for v in vs)]
        hint = f"found on page(s) {elsewhere} instead" if elsewhere else "not found anywhere in the PDF"
        rep.add("QUOTE_NOT_FOUND", w, f"not on page {page}; {hint}: {frag[:80]!r}")


def parse_amounts(text):
    amounts = []
    for num, million in AMOUNT.findall(text):
        value = Decimal(num.replace(",", ""))
        if million:
            value *= 1_000_000
        amounts.append(value)
    return amounts


# ---------------------------------------------------------------- sections

def check_source(rep, data, pdf, n_pages):
    src = data.get("source")
    if not check_keys(rep, "source", src, SOURCE_REQUIRED, SOURCE_OPTIONAL):
        return
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if src["sha256"] != digest:
        rep.add("SOURCE_MISMATCH", "source.sha256", f"does not match {pdf} ({digest})")
    if src["pages"] != n_pages:
        rep.add("SOURCE_MISMATCH", "source.pages", f"{src['pages']!r} but the PDF has {n_pages}")


def check_parameters(rep, data, n_pages, variants, detected, appendices):
    params = data.get("parameters")
    if not isinstance(params, dict):
        rep.add("SCHEMA", "parameters", "must be an object")
        return {}
    for name, p in params.items():
        where = f"parameters.{name}"
        if not PARAM_NAME.match(name):
            rep.add("SCHEMA", where, "name must be UPPER_SNAKE_CASE")
        if not check_keys(rep, where, p, PARAM_KEYS):
            continue
        values = p["values"]
        if not isinstance(values, dict) or not values:
            rep.add("SCHEMA", f"{where}.values", "must be a non-empty object")
        else:
            bad = set(values) - SCOPES - {"all"}
            if bad:
                rep.add("SCHEMA", f"{where}.values", f"unknown keys {sorted(bad)}")
            if "all" in values and len(values) > 1:
                rep.add("SCHEMA", f"{where}.values", "'all' must be the only key")
            for k, v in values.items():
                if v is not None:
                    rep.add("PARAM_VALUE_SET", f"{where}.values.{k}",
                            f"is {v!r}; the PDF does not state it, so it must be null")
        if not (isinstance(p["printed_as"], list) and p["printed_as"]
                and all(nonempty_str(t) for t in p["printed_as"])):
            rep.add("SCHEMA", f"{where}.printed_as", "must be a non-empty list of strings")
        if not nonempty_str(p["description"]):
            rep.add("SCHEMA", f"{where}.description", "must be a non-empty string")
        defs = p["defined_in"]
        if not isinstance(defs, list) or not defs:
            rep.add("SCHEMA", f"{where}.defined_in", "must be a non-empty list")
            continue
        for i, d in enumerate(defs):
            dw = f"{where}.defined_in[{i}]"
            if not check_keys(rep, dw, d, DEFINED_IN_KEYS):
                continue
            check_clause_id(rep, f"{dw}.clause", d["clause"], detected, appendices)
            if check_page(rep, f"{dw}.page", d["page"], n_pages):
                check_quote(rep, f"{dw}.verbatim_quote", d["verbatim_quote"], d["page"], variants)
    return params


def check_bound(rep, where, rule, side, params):
    """Validate one side of the band; return ('int', n) / ('param', name) / None."""
    value = rule[f"threshold_{side}"]
    incl = rule[f"threshold_{side}_inclusive"]
    param = rule[f"threshold_{side}_param"]
    if value is not None and param is not None:
        rep.add("SCHEMA", where, f"threshold_{side} and threshold_{side}_param are both set")
        return None
    if value is not None and (not is_int(value) or value < 0):
        rep.add("SCHEMA", where, f"threshold_{side} must be a non-negative GBP integer, got {value!r}")
        return None
    if param is not None:
        if not isinstance(param, str):
            rep.add("SCHEMA", where, f"threshold_{side}_param must be a string")
            return None
        if param not in params:
            rep.add("PARAM_UNDECLARED", where, f"threshold_{side}_param {param!r} is not in parameters")
            return None
    bounded = value is not None or param is not None
    if bounded and not isinstance(incl, bool):
        rep.add("SCHEMA", where, f"threshold_{side}_inclusive must be true/false when the bound is set")
    if not bounded and incl is not None:
        rep.add("SCHEMA", where, f"threshold_{side}_inclusive must be null for an open end")
    if value is not None:
        return ("int", value)
    if param is not None:
        return ("param", param)
    return None


def check_band(rep, where, rule, bounds, params, notes_by_clause):
    band = rule["band_printed"]
    if not any(bounds):
        if band is not None:
            rep.add("SCHEMA", where, "band_printed is set but no threshold bound is")
        return
    if not nonempty_str(band):
        rep.add("SCHEMA", where, "band_printed is required when a threshold bound is set")
        return

    frags = rule["verbatim_quote"]
    frags = [frags] if isinstance(frags, str) else frags if isinstance(frags, list) else []
    if not any(isinstance(f, str) and norm(band) in norm(f) for f in frags):
        rep.add("BAND_NOT_IN_QUOTE", where, f"band_printed {band!r} is not inside the quote")

    printed = parse_amounts(band)
    used = set()
    for side, b in zip(("low", "high"), bounds):
        if b is None:
            continue
        kind, val = b
        if kind == "param":
            terms = params[val].get("printed_as") or []
            if not any(isinstance(t, str) and t.lower() in band.lower() for t in terms):
                rep.add("BAND_AMOUNT", where,
                        f"threshold_{side}_param {val} but band_printed has none of {terms}")
            continue
        exact = [i for i, a in enumerate(printed) if a == val]
        if exact:
            used.add(exact[0])
            continue
        # Only allowed conversion: a pence amount to its whole-pound
        # equivalent, made inclusive ("more than £24,999.99" -> 25000 incl.).
        pence = [i for i, a in enumerate(printed)
                 if a != a.to_integral_value() and math.ceil(a) == val]
        if pence and rule[f"threshold_{side}_inclusive"] is True:
            used.add(pence[0])
            if not any(n.get("kind") == "interpretation" for n in notes_by_clause.get(rule["clause"], [])):
                rep.add("PENCE_NOTE_MISSING", where,
                        f"threshold_{side} {val} converted from a pence amount needs an "
                        f"'interpretation' note naming clause {rule['clause']}")
            continue
        rep.add("BAND_AMOUNT", where, f"threshold_{side} {val} is not printed in band_printed {band!r}")
    for i, a in enumerate(printed):
        if i not in used:
            rep.add("BAND_AMOUNT", where, f"£{a} in band_printed is not used as a bound")

    low, high = bounds
    if low and high and low[0] == high[0] == "int" and low[1] >= high[1]:
        rep.add("BAND_ORDER", where, f"threshold_low {low[1]} is not below threshold_high {high[1]}")


def check_rules(rep, data, n_pages, variants, detected, appendices, params, notes_by_clause):
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        rep.add("SCHEMA", "rules", "must be a non-empty list")
        return [], set()
    covered, used_params, ids = [], set(), []
    for i, r in enumerate(rules):
        where = f"rules[{i}]"
        if isinstance(r, dict) and isinstance(r.get("rule_id"), str):
            where = f"rules[{i}] {r['rule_id']}"
        ids.append(r.get("rule_id") if isinstance(r, dict) else None)
        if not check_keys(rep, where, r, RULE_REQUIRED, RULE_OPTIONAL):
            continue

        if check_clause_id(rep, f"{where}.clause", r["clause"], detected, appendices):
            covered.append((r["clause"], where))
        for c in r.get("covers", []) if isinstance(r.get("covers", []), list) else []:
            if check_clause_id(rep, f"{where}.covers", c, detected, appendices):
                covered.append((c, where))
        if "covers" in r and not isinstance(r["covers"], list):
            rep.add("SCHEMA", f"{where}.covers", "must be a list of clause ids")

        if r["type"] not in RULE_TYPES:
            rep.add("SCHEMA", f"{where}.type", f"{r['type']!r} not in {sorted(RULE_TYPES)}")
        scope = r["scope"]
        if not isinstance(scope, list) or not scope:
            rep.add("SCHEMA", f"{where}.scope", "must be a non-empty list")
            scope = []
        elif "all" in scope and len(scope) > 1:
            rep.add("SCHEMA", f"{where}.scope", "'all' must appear alone")
        elif set(scope) - SCOPES - {"all"}:
            rep.add("SCHEMA", f"{where}.scope", f"unknown values {sorted(set(scope) - SCOPES - {'all'})}")
        for f in ("condition", "required_action"):
            if not nonempty_str(r[f]):
                rep.add("SCHEMA", f"{where}.{f}", "must be a non-empty string")
        if r["approver"] is not None and not nonempty_str(r["approver"]):
            rep.add("SCHEMA", f"{where}.approver", "must be a non-empty string or null")
        if r["type"] == "approval" and r["approver"] is None:
            rep.add("SCHEMA", f"{where}.approver", "type 'approval' needs an approver")
        ev = r["evidence_source"]
        if not isinstance(ev, list) or not ev or set(ev) - EVIDENCE_SOURCES:
            rep.add("SCHEMA", f"{where}.evidence_source",
                    f"must be a non-empty list from {sorted(EVIDENCE_SOURCES)}")

        bounds = (check_bound(rep, where, r, "low", params), check_bound(rep, where, r, "high", params))
        if r["type"] == "threshold" and not any(bounds):
            rep.add("SCHEMA", f"{where}.type", "type 'threshold' needs at least one bound")
        for b in bounds:
            if b and b[0] == "param":
                used_params.add(b[1])
                pvals = params[b[1]].get("values") if isinstance(params[b[1]], dict) else None
                if isinstance(pvals, dict) and "all" not in pvals:
                    need = SCOPES if scope == ["all"] else set(scope)
                    missing = need - set(pvals)
                    if missing:
                        rep.add("PARAM_SCOPE", where,
                                f"parameter {b[1]} has no value key for scope {sorted(missing)}")
        check_band(rep, where, r, bounds, params, notes_by_clause)

        if check_page(rep, f"{where}.page", r["page"], n_pages):
            check_quote(rep, f"{where}.verbatim_quote", r["verbatim_quote"], r["page"], variants)
            home = detected.get(r["clause"])
            # The quote may continue onto the page after the clause number.
            if home and not home <= r["page"] <= home + 1:
                rep.add("CLAUSE_PAGE", where,
                        f"clause {r['clause']} is printed on page {home}, rule says page {r['page']}")

    # Rule ids: CPR-01, CPR-02, ... in array order, one width throughout.
    widths = set()
    for n, rid in enumerate(ids, start=1):
        m = RULE_ID.match(rid) if isinstance(rid, str) else None
        if not m:
            rep.add("RULE_ID", f"rules[{n - 1}]", f"rule_id {rid!r} is not of the form CPR-01")
            continue
        widths.add(len(m.group(1)))
        if int(m.group(1)) != n:
            rep.add("RULE_ID", f"rules[{n - 1}]", f"{rid} out of sequence; expected number {n}")
    if len(widths) > 1:
        rep.add("RULE_ID", "rules", f"rule_id numbers use mixed widths {sorted(widths)}")

    if not any(isinstance(r, dict) and r.get("type") == "anti-avoidance" for r in rules):
        rep.add("ANTI_AVOIDANCE_MISSING", "rules", "no rule has type 'anti-avoidance'")
    for name in params:
        if name not in used_params:
            rep.add("PARAM_UNUSED", f"parameters.{name}", "declared but no rule uses it")
    return covered, used_params


def check_excluded(rep, data, n_pages, detected, appendices):
    excluded = data.get("excluded")
    if not isinstance(excluded, list):
        rep.add("SCHEMA", "excluded", "must be a list")
        return []
    covered = []
    for i, e in enumerate(excluded):
        where = f"excluded[{i}]"
        if not check_keys(rep, where, e, EXCLUDED_REQUIRED, EXCLUDED_OPTIONAL):
            continue
        reason = e["reason"]
        if not nonempty_str(reason) or "\n" in reason or len(reason) > MAX_REASON:
            rep.add("SCHEMA", f"{where}.reason", f"must be one non-empty line of at most {MAX_REASON} chars")
        if check_clause_id(rep, f"{where}.clause", e["clause"], detected, appendices):
            covered.append((e["clause"], where))
            home = detected.get(e["clause"])
            if check_page(rep, f"{where}.page", e["page"], n_pages) and home and e["page"] != home:
                rep.add("CLAUSE_PAGE", where, f"clause {e['clause']} is printed on page {home}, not {e['page']}")
        covers = e.get("covers", [])
        if not isinstance(covers, list):
            rep.add("SCHEMA", f"{where}.covers", "must be a list of clause ids")
            continue
        for c in covers:
            if check_clause_id(rep, f"{where}.covers", c, detected, appendices):
                covered.append((c, where))
    return covered


def check_notes(rep, data, detected, appendices):
    notes = data.get("notes")
    by_clause = {}
    if not isinstance(notes, list):
        rep.add("SCHEMA", "notes", "must be a list")
        return by_clause
    for i, n in enumerate(notes):
        where = f"notes[{i}]"
        if not check_keys(rep, where, n, NOTE_KEYS):
            continue
        if n["kind"] not in NOTE_KINDS:
            rep.add("SCHEMA", f"{where}.kind", f"{n['kind']!r} not in {sorted(NOTE_KINDS)}")
        if not nonempty_str(n["issue"]):
            rep.add("SCHEMA", f"{where}.issue", "must be a non-empty string")
        clauses = n["clauses"]
        if not isinstance(clauses, list) or not clauses:
            rep.add("SCHEMA", f"{where}.clauses", "must be a non-empty list of clause ids")
            continue
        for c in clauses:
            if check_clause_id(rep, f"{where}.clauses", c, detected, appendices, allow_section=True):
                by_clause.setdefault(c, []).append(n)
    return by_clause


def check_coverage(rep, detected, appendices, covered):
    ids = {c for c, _ in covered}
    for cid, page in sorted(detected.items(), key=lambda kv: (kv[1], kv[0])):
        if cid not in ids:
            rep.add("CLAUSE_UNCOVERED", cid, f"printed on page {page} but in neither rules nor excluded")
    # Unlabelled appendix tables (e.g. Appendix A) cannot be detected row by
    # row; at least require that the appendix is represented.
    for app in sorted(appendices):
        if not any(c.startswith(f"App{app}-") for c in ids):
            rep.add("CLAUSE_UNCOVERED", f"Appendix {app}", "no rule or exclusion refers to this appendix")


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("rules", nargs="?", default="outputs/rules.json")
    ap.add_argument("--pdf", default="data/contract-rules.pdf")
    args = ap.parse_args(argv)

    rules_path, pdf = Path(args.rules), Path(args.pdf)
    if shutil.which("pdftotext") is None:
        print("ERROR: pdftotext not found on PATH (install poppler)", file=sys.stderr)
        return 2
    for p in (rules_path, pdf):
        if not p.is_file():
            print(f"ERROR: {p} not found", file=sys.stderr)
            return 2
    try:
        data = json.loads(rules_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: {rules_path} is not valid JSON: {exc}", file=sys.stderr)
        return 2
    try:
        plain, layout = pdftotext_pages(pdf, False), pdftotext_pages(pdf, True)
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: pdftotext failed on {pdf}: {exc.stderr.decode(errors='replace')}", file=sys.stderr)
        return 2
    if len(plain) != len(layout) or not plain:
        print(f"ERROR: page split mismatch (plain {len(plain)}, layout {len(layout)})", file=sys.stderr)
        return 2

    n_pages = len(plain)
    variants = page_variants(plain, layout)
    detected, appendices = detect_clauses(layout)
    rep = Report()

    if not isinstance(data, dict):
        rep.add("SCHEMA", "top level", "must be an object")
    else:
        check_keys(rep, "top level", data, TOP_KEYS)
        check_source(rep, data, pdf, n_pages)
        notes_by_clause = check_notes(rep, data, detected, appendices)
        params = check_parameters(rep, data, n_pages, variants, detected, appendices)
        covered, _ = check_rules(rep, data, n_pages, variants, detected, appendices, params, notes_by_clause)
        covered += check_excluded(rep, data, n_pages, detected, appendices)
        check_coverage(rep, detected, appendices, covered)

    counts = {k: len(data.get(k) or []) for k in ("rules", "excluded", "parameters", "notes")} \
        if isinstance(data, dict) else {}
    print(f"verify_quotes: {rules_path} against {pdf} ({n_pages} pages, "
          f"{len(detected)} clause ids detected, appendices {sorted(appendices)})")
    print("  " + ", ".join(f"{k}: {v}" for k, v in counts.items()))
    if not rep.errors:
        print("PASS: all checks passed")
        return 0
    for code, where, msg in rep.errors:
        print(f"  [{code}] {where}: {msg}")
    print(f"FAIL: {len(rep.errors)} error(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
