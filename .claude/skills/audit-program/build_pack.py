#!/usr/bin/env python3
"""Build the audit planning pack from the planner's judgments.

    .venv/bin/python .claude/skills/audit-program/build_pack.py           build the pack
    .venv/bin/python .claude/skills/audit-program/build_pack.py --gate    gate check only; writes nothing
    .venv/bin/python .claude/skills/audit-program/build_pack.py --lists   the lists a sample can be drawn from

Gate: the approved scope is computed from outputs/auditor-comments.md and
outputs/risk-ratings.json. It fails if the register is not a revision (r1 or
later), if risk-ratings.json or the inputs changed after that revision was
built, if any register row is undecided, or if an Amend, Reject or Add to
scope decision has not been applied.

Build: reads outputs/audit-plan.json (the planner's judgments), resolves every
citation and {{$.path}} placeholder, draws every sample deterministically from
the general_procurement rows of the analytics-full lists, sized by the risk's
score, checks every sampled transaction against spend-clean.csv, checks that
every control has a test and that every rule in rules.json is cited by an
in-scope risk, a control or a test, or listed as not tested with a reason.
Writes:

    outputs/planning-memo.md
    outputs/risk-control-matrix.md
    outputs/audit-program.md          ends with the PBC list
    outputs/samples/T-nn.csv          the transactions each test pulls
    outputs/pack-figures.json         every figure the builder computed

Any error: nothing is written and the exit code is 1.

Options: --root DIR (repo root), --out-dir DIR (where the register, its
snapshots, auditor-comments.md and audit-plan.json are read and the pack is
written), --plan FILE, --analytics / --history / --rules FILE,
--analytics-full DIR.
"""

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT_DEFAULT = HERE.parents[2]
# Path syntax, citations, the decision table and the scoring method are the
# register builder's, so the register and the pack read them the same way.
sys.path.insert(0, str(HERE.parent / "risk-assessment"))
import build_register as BR  # noqa: E402

PRIMARY_TAG = BR.PRIMARY_TAG

# Items per test by risk score (likelihood x impact): (lowest score, items).
# 15 and over is the council's Extreme band; Medium High (8 to 12) is split
# at 10; 4 to 6 is Moderate; up to 3 is Low.
SAMPLE_SIZES = [(15, 25), (10, 20), (8, 15), (4, 10), (1, 5)]

# PBC items every pack requests, whatever the tests need. Each must cite the
# source that makes it necessary; the check names what that source is.
STANDING_PBC = {
    "contracts_register": "the council's contracts register",
    "contract_evidence": "contract evidence for the high_value_suppliers population, starting with the suppliers "
                         "marked no published notice found",
    "waiver_log": "the waiver and exception log",
    "threshold_values": "the Threshold values the Rules name but do not state",
    "audit_plan_appendices": "the Internal Audit Plan appendices missing from the published paper",
}
HVS_TEST = "high_value_suppliers"
NPNF = "no published notice found"

MEMO_FIELDS = ("objective", "background", "approach", "limitations")
PLAN_KEYS = {"register_revision", "memo", "risks", "pbc", "rules_not_tested"}
SAMPLE_KEYS = {"file", "where", "population_metric", "sort", "size", "transactions"}
SAMPLE_OPTIONAL = {"size_reason", "max_per_item"}
FILTER_OPS = ("eq", "ne", "in", "gt", "gte", "lt", "lte")

CONTROL_ID_RE = re.compile(r"^C-\d{2,}$")
TEST_ID_RE = re.compile(r"^T-\d{2,}$")
PBC_ID_RE = re.compile(r"^PBC-\d{2,}$")
ID_EXAMPLE = {"control": "C-01", "test": "T-01", "pbc": "PBC-01"}
# Words that state or imply wrongdoing rather than an indicator to investigate.
ACCUSATORY_RE = re.compile(r"\b(off[- ]contract|wrongdoing|fraudulent|corrupt\w*|misconduct|unlawful\w*|"
                           r"illegal\w*|breach(?:es|ed)?)\b", re.IGNORECASE)

SAMPLE_COLS = ["test_id", "risk_id", "item_rank", "item", "item_spend_tag", "transaction_id", "source_file",
               "excel_row", "date", "service", "expenditure_category", "narrative", "supplier_name",
               "supplier_norm", "net_amount", "spend_tag"]

INDICATOR_NOTE = ("> These are **risk indicators to investigate**, drawn from published data. They are not findings "
                  "and do not suggest wrongdoing by the council, any service or any supplier.")


class Stop(Exception):
    pass


def load_json(name, p):
    if not p.exists():
        raise Stop(f"{name} not found at {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise Stop(f"{name} is not valid JSON: {e}")


def gbp(pence):
    return f"£{pence / 100:,.2f}"


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- figures

class Figures:
    """Every figure the builder computes, and every placeholder it fills, for
    pack-figures.json and the QA number check."""

    def __init__(self):
        self.figures, self.placeholders = {}, {}

    def add(self, fid, value, basis, doc):
        f = self.figures.setdefault(fid, {"id": fid, "value": value, "basis": basis, "in": []})
        if doc not in f["in"]:
            f["in"].append(doc)
        return value

    def placeholder(self, canonical, value, doc):
        p = self.placeholders.setdefault(canonical, {"path": canonical, "value": value, "in": []})
        if doc not in p["in"]:
            p["in"].append(doc)


# ---------------------------------------------------------------- gate

def gate(out_dir, ratings, data_shas, ctx, method):
    """The approved scope, or (None, errors)."""
    errs = []
    _, snaps = BR.snapshots(out_dir)
    if not snaps:
        return None, ["no register snapshot in register-snapshots/: the register has not been built"]
    n = max(snaps)
    snap = json.loads(snaps[n].read_text(encoding="utf-8"))
    if n < 1:
        errs.append("the register is r0, not a revision: the auditor's decisions have not been applied. The auditor "
                    "completes auditor-comments.md and the risk-assessor builds the revision")
    rev = ratings.get("revision") or {}
    if n >= 1 and rev.get("number") != n:
        errs.append(f"risk-ratings.json carries revision {rev.get('number')}, but the latest register is r{n}; "
                    "re-run build_register.py")
    if BR.body(ratings) != snap.get("ratings"):
        errs.append(f"risk-ratings.json has changed since register r{n} was built; re-run build_register.py")
    if snap.get("inputs") != data_shas:
        changed = sorted(k for k in data_shas if (snap.get("inputs") or {}).get(k) != data_shas[k])
        errs.append(f"{', '.join(changed)} changed since register r{n} was built; the auditor decided on other evidence")
    reg = out_dir / "risk-register.md"
    first = reg.read_text(encoding="utf-8").split("\n", 1)[0] if reg.exists() else ""
    if first != f"# Procurement risk register (revision r{n})":
        errs.append(f"risk-register.md is not register r{n} (first line {first!r}); re-run build_register.py")

    comments = out_dir / "auditor-comments.md"
    decisions = {}
    if not comments.exists():
        errs.append("auditor-comments.md not found")
    else:
        if not re.search(rf"^Register revision: r{n}\s*$", comments.read_text(encoding="utf-8"), re.M):
            errs.append(f"auditor-comments.md is not the decision table for register r{n}; re-run build_register.py")
        try:
            decisions = BR.parse_comments(comments)
        except ValueError as e:
            errs.append(str(e))

    rows = list(snap.get("decision_rows", []))
    rows += [r["risk_id"] for r in ratings.get("risks", []) if r.get("status") != "rejected" and r["risk_id"] not in rows]
    rows += [x["history"] for x in ratings.get("noted_not_rated", []) if x["history"] not in rows]
    for k in rows:
        if not decisions.get(k, {}).get("decision"):
            errs.append(f"{k} has no decision in auditor-comments.md: the auditor decides every row before planning")
    for k, d in decisions.items():
        if d["decision"] not in BR.ACTING:
            continue
        m = re.fullmatch(r"r(\d+)", d["applied"])
        if not d["applied"]:
            errs.append(f"{k}: {d['decision']} not yet applied (Applied is blank); the risk-assessor applies it in "
                        "the next revision")
        elif not m or int(m.group(1)) > n:
            errs.append(f"{k}: Applied {d['applied']!r} names no revision up to r{n}")

    in_scope, out = [], []
    for r in ratings.get("risks", []):
        rid = r["risk_id"]
        d = decisions.get(rid, {})
        dec = d.get("decision", "")
        if r.get("status") == "rejected":
            if dec != "Reject":
                errs.append(f"{rid} is rejected in risk-ratings.json but its decision is {dec or 'blank'}")
            out.append({"id": rid, "title": r["title"], "decision": dec, "comment": d.get("comment", "")})
        elif dec == "Reject":
            errs.append(f"{rid}: rejected by the auditor but not marked rejected in risk-ratings.json")
        elif dec in ("Approve", "Amend"):
            in_scope.append((r, d))
    for x in ratings.get("noted_not_rated", []):
        d = decisions.get(x["history"], {})
        if d.get("decision") == "Add to scope" and d.get("applied"):
            errs.append(f"{x['history']}: Add to scope applied in {d['applied']} but still in noted_not_rated")
        elif d.get("decision") == "Leave out":
            a = ctx.audits.get(x["history"], {})
            out.append({"id": x["history"], "title": f"{a.get('title')} ({a.get('opinion')})",
                        "decision": d["decision"], "comment": d.get("comment", "")})
    if not in_scope and not errs:
        errs.append("no risk is approved: there is nothing to plan")
    if errs:
        return None, errs

    risks = []
    for r, d in in_scope:
        l, i = r["likelihood"]["score"], r["impact"]["score"]
        score, label, band = BR.rate(method, l, i)
        risks.append({"risk": r, "id": r["risk_id"], "l": l, "i": i, "score": score, "label": label, "band": band,
                      "decision": d, "override": (snap.get("overrides") or {}).get(r["risk_id"], {})})
    return {"n": n, "risks": risks, "out": out}, []


# ---------------------------------------------------------------- plan schema

def check_schema(plan, scope):
    errs = []
    if not isinstance(plan, dict):
        return ["audit-plan.json must be an object"]
    miss, extra = PLAN_KEYS - set(plan), set(plan) - PLAN_KEYS
    if miss:
        errs.append(f"audit-plan.json: missing {sorted(miss)}")
    if extra:
        errs.append(f"audit-plan.json: unknown top-level keys {sorted(extra)}")
    if plan.get("register_revision") != scope["n"]:
        errs.append(f"audit-plan.json: register_revision is {plan.get('register_revision')!r}; the approved register is "
                    f"r{scope['n']} (write the plan against it)")
    memo = plan.get("memo")
    if not isinstance(memo, dict) or set(memo) != set(MEMO_FIELDS):
        errs.append(f"memo: must be an object with exactly {list(MEMO_FIELDS)}")
    else:
        for f in MEMO_FIELDS:
            if not isinstance(memo[f], str) or not memo[f].strip():
                errs.append(f"memo.{f}: must be non-empty text")

    ids = {"control": set(), "test": set(), "pbc": set()}

    def unique(kind, value, where, rx):
        if not isinstance(value, str) or not rx.match(value):
            errs.append(f"{where}: {kind}_id must look like {ID_EXAMPLE[kind]}")
        elif value in ids[kind]:
            errs.append(f"{where}: {kind}_id {value} is used twice")
        ids[kind].add(value)

    risks = plan.get("risks")
    if not isinstance(risks, list):
        errs.append("risks: must be a list")
        risks = []
    for n, r in enumerate(risks):
        w = f"risks[{n}]"
        if not isinstance(r, dict) or set(r) != {"risk_id", "controls", "tests"}:
            errs.append(f"{w}: must be {{risk_id, controls, tests}}")
            continue
        w = r["risk_id"] if isinstance(r["risk_id"], str) else w
        for kind, key, rx, need in (("control", "controls", CONTROL_ID_RE, {"control_id", "control"}),
                                    ("test", "tests", TEST_ID_RE, {"test_id", "controls", "step", "sample", "pbc"})):
            items = r[key]
            if not isinstance(items, list) or not items:
                errs.append(f"{w}.{key}: must be a non-empty list")
                continue
            for m, x in enumerate(items):
                ww = f"{w}.{key}[{m}]"
                optional = {"no_sample_reason"} if kind == "test" else set()
                if not isinstance(x, dict) or not need <= set(x) or set(x) - need - optional:
                    errs.append(f"{ww}: keys must be {sorted(need)}" + (" (+ no_sample_reason)" if optional else ""))
                    continue
                unique(kind, x[f"{kind}_id"], ww, rx)
                text = x["control"] if kind == "control" else x["step"]
                if not isinstance(text, str) or not text.strip():
                    errs.append(f"{ww}: {'control' if kind == 'control' else 'step'} must be non-empty text")
                if kind == "test":
                    errs += check_test_schema(x, ww)
    pbc = plan.get("pbc")
    if not isinstance(pbc, list):
        errs.append("pbc: must be a list")
        pbc = []
    for n, p in enumerate(pbc):
        w = f"pbc[{n}]"
        if not isinstance(p, dict) or set(p) != {"pbc_id", "item", "standing"}:
            errs.append(f"{w}: must be {{pbc_id, item, standing}}")
            continue
        unique("pbc", p["pbc_id"], w, PBC_ID_RE)
        if not isinstance(p["item"], str) or not p["item"].strip():
            errs.append(f"{w}.item: must be non-empty text")
        if p["standing"] is not None and p["standing"] not in STANDING_PBC:
            errs.append(f"{w}.standing: must be null or one of {list(STANDING_PBC)}")
    nt = plan.get("rules_not_tested")
    if not isinstance(nt, list):
        errs.append("rules_not_tested: must be a list")
    else:
        for n, x in enumerate(nt):
            if not isinstance(x, dict) or set(x) != {"rule_id", "reason"} or not isinstance(x.get("reason"), str) \
                    or not x["reason"].strip():
                errs.append(f"rules_not_tested[{n}]: must be {{rule_id, reason}} with a reason")
    return errs


def check_test_schema(t, w):
    errs = []
    if not isinstance(t["controls"], list) or not t["controls"]:
        errs.append(f"{w}.controls: must name at least one control")
    if not isinstance(t["pbc"], list) or not t["pbc"]:
        errs.append(f"{w}.pbc: must name the PBC items the test needs")
    s = t["sample"]
    if s is None:
        if not isinstance(t.get("no_sample_reason"), str) or not t["no_sample_reason"].strip():
            errs.append(f"{w}: a test with no sample gives no_sample_reason")
        return errs
    if "no_sample_reason" in t:
        errs.append(f"{w}: no_sample_reason is only for a test with sample null")
    if not isinstance(s, dict) or not SAMPLE_KEYS <= set(s) or set(s) - SAMPLE_KEYS - SAMPLE_OPTIONAL:
        return errs + [f"{w}.sample: keys must be {sorted(SAMPLE_KEYS)} (+ {sorted(SAMPLE_OPTIONAL)})"]
    if not isinstance(s["file"], str) or "/" in s["file"]:
        errs.append(f"{w}.sample.file: a file name in outputs/analytics-full/")
    if not isinstance(s["where"], list):
        errs.append(f"{w}.sample.where: must be a list (empty for the whole list)")
    else:
        for n, c in enumerate(s["where"]):
            ww = f"{w}.sample.where[{n}]"
            if not isinstance(c, dict) or set(c) != {"field", "op", "value"} or c.get("op") not in FILTER_OPS:
                errs.append(f"{ww}: must be {{field, op, value}} with op one of {list(FILTER_OPS)}")
                continue
            v = c["value"]
            scalar = (str, int, float, bool)
            if c["op"] == "in" and not (isinstance(v, list) and v and all(isinstance(x, scalar) for x in v)):
                errs.append(f"{ww}: op in takes a non-empty list")
            elif c["op"] in ("eq", "ne") and not isinstance(v, scalar):
                errs.append(f"{ww}: op {c['op']} takes text, a number or true/false")
            elif c["op"] in ("gt", "gte", "lt", "lte") and (isinstance(v, bool) or not isinstance(v, (int, float))):
                errs.append(f"{ww}: op {c['op']} takes a number")
    if not isinstance(s["sort"], list) or not s["sort"] or not all(
            isinstance(k, dict) and set(k) == {"field", "order"} and k["order"] in ("asc", "desc") for k in s["sort"]):
        errs.append(f"{w}.sample.sort: a non-empty list of {{field, order: asc|desc}}")
    size = s["size"]
    if not (size in ("by_score", "all") or (isinstance(size, int) and not isinstance(size, bool) and size >= 1)):
        errs.append(f"{w}.sample.size: \"by_score\", \"all\" or a whole number of items")
    elif size != "by_score" and not (isinstance(s.get("size_reason"), str) and s["size_reason"].strip()):
        errs.append(f"{w}.sample.size: {size!r} departs from the score-based size, so give size_reason")
    mpi = s.get("max_per_item")
    if mpi is not None and (isinstance(mpi, bool) or not isinstance(mpi, int) or mpi < 1):
        errs.append(f"{w}.sample.max_per_item: null or a whole number")
    if not isinstance(s["population_metric"], str):
        errs.append(f"{w}.sample.population_metric: a $.path to the general_procurement count of the population")
    if not isinstance(s["transactions"], str):
        errs.append(f"{w}.sample.transactions: the column holding the item's transaction ids")
    return errs


# ---------------------------------------------------------------- prose

def prose(ctx, figs, text, where, docs, errs):
    """Rendered text and resolved tags. Unresolved citations, typed figures and
    accusatory words are errors."""
    rendered, tags, problems = BR.process_text(ctx, text)
    errs += [f"{where}: {p}" for p in problems]
    typed = BR.typed_figures(text)
    if typed:
        errs.append(f"{where}: figure typed in prose ({', '.join(typed[:5])}); use a {{{{$.path}}}} placeholder")
    m = ACCUSATORY_RE.search(text)
    if m:
        errs.append(f"{where}: {m.group(0)!r} is not indicator language; describe a risk indicator to investigate")
    for pm in BR.PLACEHOLDER_RE.finditer(text):
        try:
            toks = BR.parse_path(pm.group(1))
            value, _ = BR.resolve(ctx.analytics, toks)
            for doc in docs:
                figs.placeholder(BR.canonical(toks), value, doc)
        except BR.PathError:
            pass  # already reported by process_text
    return rendered, tags


def ok_tags(tags, kind=None):
    return [t for t in tags if t.get("ok") and (kind is None or t["kind"] == kind)]


# ---------------------------------------------------------------- samples

def list_files(analytics):
    """{file name: test} for every list a test publishes."""
    out = {}
    for name, t in analytics.get("tests", {}).items():
        for key in ("full_list", "candidates_list"):
            if isinstance(t.get(key), str):
                out[Path(t[key]).name] = name
    return out


def load_csv(path, cache):
    if path not in cache:
        if not path.exists():
            raise Stop(f"{path} not found")
        with path.open(newline="", encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            cache[path] = (list(rd.fieldnames or []), list(rd))
    return cache[path]


def matches(cell, op, value):
    if op == "in":
        return any(matches(cell, "eq", v) for v in value)
    cell = (cell or "").strip()
    if isinstance(value, bool):
        if cell.lower() not in ("true", "false"):
            return False
        same = (cell.lower() == "true") == value
        return same if op == "eq" else not same
    if isinstance(value, (int, float)):
        c = num(cell)
        if c is None:
            return op == "ne"
        return {"eq": c == value, "ne": c != value, "gt": c > value, "gte": c >= value,
                "lt": c < value, "lte": c <= value}[op]
    return (cell == value) if op == "eq" else (cell != value)


def sort_rows(rows, keys):
    """Stable multi-key sort; numeric where every filled value is a number;
    blanks last; ties keep the list's own order."""
    out = list(rows)
    for k in reversed(keys):
        f, desc = k["field"], k["order"] == "desc"
        filled = [r for r in out if (r[f] or "").strip()]
        blank = [r for r in out if not (r[f] or "").strip()]
        numeric = all(num(r[f]) is not None for r in filled)
        filled.sort(key=(lambda r: num(r[f])) if numeric else (lambda r: r[f]), reverse=desc)
        out = filled + blank
    return out


def score_size(score):
    return next(n for lo, n in SAMPLE_SIZES if score >= lo)


def where_text(where):
    if not where:
        return "all general_procurement rows"
    sym = {"eq": "=", "ne": "≠", "gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "in": "in"}
    return "general_procurement rows where " + " and ".join(
        f"{c['field']} {sym[c['op']]} {c['value'] if not isinstance(c['value'], list) else ', '.join(map(str, c['value']))}"
        for c in where)


def draw(ctx, test, rs, lists, af_dir, cache, spend, errs):
    s, tid = test["sample"], test["test_id"]
    w = f"{tid}.sample"
    name = s["file"]
    if name not in lists:
        errs.append(f"{w}.file: {name} is not a list published by a test in analytics.json ({', '.join(sorted(lists))})")
        return None
    cols, rows = load_csv(af_dir / name, cache)
    bad = False
    if "spend_tag" not in cols:
        errs.append(f"{w}: {name} has no spend_tag column, so its general_procurement rows cannot be found")
        bad = True
    for c in s["where"]:
        if c["field"] == "spend_tag":
            errs.append(f"{w}.where: samples are always drawn from general_procurement rows; do not filter spend_tag")
            bad = True
        elif c["field"] not in cols:
            errs.append(f"{w}.where: {name} has no column {c['field']!r}")
            bad = True
    for k in s["sort"]:
        if k["field"] not in cols:
            errs.append(f"{w}.sort: {name} has no column {k['field']!r}")
            bad = True
    col = s["transactions"]
    if col not in cols or not (col == "transaction_id" or col.endswith("_ids")):
        errs.append(f"{w}.transactions: {col!r} is not a transaction id column of {name} "
                    f"({', '.join(c for c in cols if c == 'transaction_id' or c.endswith('_ids'))})")
        bad = True
    if bad:
        return None

    pop = [r for r in rows if r["spend_tag"] == PRIMARY_TAG and all(matches(r[c["field"]], c["op"], c["value"])
                                                                      for c in s["where"])]
    try:
        toks = BR.parse_path(s["population_metric"])
        value, trail = BR.resolve(ctx.analytics, toks)
    except BR.PathError as e:
        errs.append(f"{w}.population_metric does not resolve in analytics.json: {e}")
        return None
    metric = BR.canonical(toks)
    cls, why = BR.classify_metric(ctx, toks, trail)
    if cls != "primary" or toks[-1] != ("key", "count") or isinstance(value, bool) or not isinstance(value, int):
        errs.append(f"{w}.population_metric {metric} must be a {PRIMARY_TAG} count ({cls}: {why})")
        return None
    if toks[1] != ("key", lists[name]):
        errs.append(f"{w}.population_metric is a {toks[1][1]} figure, but {name} is the {lists[name]} list")
        return None
    if value != len(pop):
        errs.append(f"{w}: {len(pop)} {PRIMARY_TAG} rows of {name} match the filter but {metric} = {value}: the "
                    "sample population is not the population the register rated")
        return None

    rule = score_size(rs["score"])
    size = s["size"]
    if size == "by_score":
        target = rule
    elif size == "all":
        target = len(pop)
    else:
        target = size
        if size < rule:
            errs.append(f"{w}.size: {size} items is below the {rule} that score {rs['score']} requires; a sample may "
                        "grow, never shrink")
            return None
    items = sort_rows(pop, s["sort"])[:target]
    out_rows, pence = [], 0
    for rank, item in enumerate(items, 1):
        label = item.get("supplier_norm") or item.get("transaction_id") or f"row {rank}"
        if item.get("threshold"):
            label += f" (tier {item['threshold']})"
        ids = [x.strip() for x in (item[col] or "").split(";") if x.strip()]
        if not ids:
            errs.append(f"{w}: item {rank} {label} lists no transactions in {col}")
        found = []
        for x in ids:
            sp = spend.get(x)
            if sp is None:
                errs.append(f"{w}: transaction {x} of item {rank} {label} is not in spend-clean.csv")
                continue
            if item.get("supplier_norm") and sp["supplier_norm"] != item["supplier_norm"]:
                errs.append(f"{w}: transaction {x} is to {sp['supplier_norm']}, not item {rank} {label}")
                continue
            if item.get("net") and num(item["net"]) != num(sp["net_amount"]):
                errs.append(f"{w}: transaction {x} is {sp['net_amount']} in spend-clean.csv, {item['net']} in {name}")
                continue
            found.append(sp)
        if s.get("max_per_item"):
            found = sorted(found, key=lambda r: (-int(r["net_pence"]), r["transaction_id"]))[:s["max_per_item"]]
        for sp in sorted(found, key=lambda r: (r["date"], r["transaction_id"])):
            out_rows.append({"test_id": tid, "risk_id": rs["id"], "item_rank": rank, "item": label,
                             "item_spend_tag": item["spend_tag"], **{k: sp[k] for k in SAMPLE_COLS[5:]}})
            pence += int(sp["net_pence"])
    return {"file": name, "population": len(pop), "metric": metric, "rule_size": rule, "size": size,
            "target": target, "items": len(items), "transactions": len(out_rows), "pence": pence, "rows": out_rows,
            "where": where_text(s["where"]), "transactions_col": col, "max_per_item": s.get("max_per_item"),
            "sort": ", then ".join(f"{k['field']} {'descending' if k['order'] == 'desc' else 'ascending'}"
                                   for k in s["sort"])}


# ---------------------------------------------------------------- plan evaluation

def standing_check(ctx, kind, tags):
    """None if the standing PBC item cites what makes it necessary, else what it must cite."""
    rules = [ctx.rules_by_id[t["ref"]] for t in ok_tags(tags, "rule")]
    if kind == "contracts_register":
        return None if any("contract_register" in (r.get("evidence_source") or []) for r in rules) else \
            "a rule whose evidence source is the contract register"
    if kind == "waiver_log":
        return None if any("waiver" in (str(r.get("condition")) + str(r.get("required_action"))).lower()
                           for r in rules) else "a rule on waivers"
    if kind == "threshold_values":
        return None if any(r.get("threshold_low_param") or r.get("threshold_high_param") for r in rules) else \
            "a rule bounded by a parameter the Rules name without a value"
    if kind == "audit_plan_appendices":
        return None if any(ctx.history_by_id[t["ref"]][0] == "gaps" for t in ok_tags(tags, "history")) else \
            "the history.json gap that records the missing appendices"
    if kind == "contract_evidence":
        return None if any(t["toks"][:2] == [("key", "tests"), ("key", HVS_TEST)] for t in ok_tags(tags, "metric")) \
            else f"a {HVS_TEST} metric"
    return None


def evaluate(ctx, plan, scope, lists, af_dir, spend, figs):
    """(errors, everything the render needs)."""
    errs = []
    in_scope = {rs["id"]: rs for rs in scope["risks"]}
    all_risks = {r["risk_id"]: r for r in ctx.ratings.get("risks", [])}
    planned, seen = [], set()
    for r in plan["risks"]:
        rid = r["risk_id"]
        if rid in seen:
            errs.append(f"{rid} is planned twice")
            continue
        seen.add(rid)
        if rid not in in_scope:
            why = "not in risk-ratings.json" if rid not in all_risks else "not approved by the auditor"
            errs.append(f"{rid} is in audit-plan.json but {why}: plan only the approved scope")
            continue
        planned.append((in_scope[rid], r))
    for rid in in_scope:
        if rid not in seen:
            errs.append(f"{rid} is in the approved scope but has no entry in audit-plan.json")

    pbc_ids = {p["pbc_id"] for p in plan["pbc"]}
    trace = {}  # rule_id -> [where cited]
    cache, out_risks, pbc_users = {}, [], {}

    def cite(tags, where):
        for t in ok_tags(tags, "rule"):
            trace.setdefault(t["ref"], [])
            if where not in trace[t["ref"]]:
                trace[t["ref"]].append(where)

    for rs, r in planned:
        rid = rs["id"]
        for f in BR.PROSE_FIELDS:
            text = BR.get_field(rs["risk"], f)
            if isinstance(text, str):
                cite([BR.resolve_tag(ctx, t) for t in BR.scan_tags(text)], rid)
        controls = []
        for c in r["controls"]:
            w = f"{rid}.{c['control_id']}"
            rendered, tags = prose(ctx, figs, c["control"], w, ("risk-control-matrix.md", "audit-program.md"), errs)
            if not ok_tags(tags, "rule"):
                errs.append(f"{w}: the expected control cites no rule; every control rests on a rule in rules.json")
            cite(tags, c["control_id"])
            controls.append({"id": c["control_id"], "text": rendered,
                             "rules": sorted({t["ref"] for t in ok_tags(tags, "rule")}), "tests": []})
        cids = {c["id"]: c for c in controls}
        tests = []
        for t in r["tests"]:
            w = f"{rid}.{t['test_id']}"
            rendered, tags = prose(ctx, figs, t["step"], w, ("audit-program.md",), errs)
            if not [x for x in ok_tags(tags) if x["kind"] == "rule" or x.get("cls") == "primary"]:
                errs.append(f"{w}: the test step cites no rule and no {PRIMARY_TAG} metric")
            cite(tags, t["test_id"])
            for c in t["controls"]:
                if c not in cids:
                    errs.append(f"{w}: tests {c}, which is not a control of {rid}")
                else:
                    cids[c]["tests"].append(t["test_id"])
            for p in t["pbc"]:
                if p not in pbc_ids:
                    errs.append(f"{w}: needs {p}, which is not in the pbc list")
                pbc_users.setdefault(p, []).append(t["test_id"])
            sample, reason = None, None
            if t["sample"] is not None:
                sample = draw(ctx, t, rs, lists, af_dir, cache, spend, errs)
                if t["sample"].get("size_reason"):
                    reason, _ = prose(ctx, figs, t["sample"]["size_reason"], f"{w}.sample.size_reason",
                                      ("audit-program.md",), errs)
            else:
                reason, _ = prose(ctx, figs, t["no_sample_reason"], f"{w}.no_sample_reason", ("audit-program.md",), errs)
            tests.append({"id": t["test_id"], "text": rendered, "controls": t["controls"], "pbc": t["pbc"],
                          "sample": sample, "reason": reason})
        for c in controls:
            if not c["tests"]:
                errs.append(f"{rid}.{c['id']}: no test covers this control")
        out_risks.append({"rs": rs, "controls": controls, "tests": tests})

    # PBC list
    pbc, kinds = [], {}
    for p in plan["pbc"]:
        w = p["pbc_id"]
        rendered, tags = prose(ctx, figs, p["item"], w, ("audit-program.md",), errs)
        if p["standing"]:
            kinds.setdefault(p["standing"], []).append(w)
            need = standing_check(ctx, p["standing"], tags)
            if need:
                errs.append(f"{w} ({p['standing']}): must cite {need}")
        elif not pbc_users.get(w):
            errs.append(f"{w}: no test needs it; the PBC list is derived from the test steps")
        pbc.append({"id": w, "text": rendered, "standing": p["standing"], "tests": pbc_users.get(w, [])})
    for kind, what in STANDING_PBC.items():
        if kind not in kinds:
            errs.append(f"pbc: no item with standing {kind!r} ({what}); every pack requests it")
        elif len(kinds[kind]) > 1:
            errs.append(f"pbc: standing {kind!r} is on {', '.join(kinds[kind])}; one item each")

    # rule accounting
    not_tested = {}
    for x in plan["rules_not_tested"]:
        rid = x["rule_id"]
        if rid not in ctx.rules_by_id:
            errs.append(f"rules_not_tested: {rid} is not in rules.json")
        elif rid in not_tested:
            errs.append(f"rules_not_tested: {rid} is listed twice")
        elif rid in trace:
            errs.append(f"rules_not_tested: {rid} is cited by {', '.join(trace[rid])}, so it is tested; remove it")
        else:
            not_tested[rid], _ = prose(ctx, figs, x["reason"], f"rules_not_tested {rid}", ("risk-control-matrix.md",), errs)
    for rid in ctx.rules_by_id:
        if rid not in trace and rid not in not_tested:
            errs.append(f"{rid} is neither cited by an in-scope risk, control or test nor listed in rules_not_tested")

    memo = {}
    for f in MEMO_FIELDS:
        memo[f], _ = prose(ctx, figs, plan["memo"][f], f"memo.{f}", ("planning-memo.md",), errs)
    return errs, {"risks": out_risks, "pbc": pbc, "trace": trace, "not_tested": not_tested, "memo": memo,
                  "memo_tags": [t for f in MEMO_FIELDS for t in BR.scan_tags(plan["memo"][f])]}


# ---------------------------------------------------------------- standing PBC detail

def standing_detail(ctx, kind, af_dir, cache, figs):
    if kind == "threshold_values":
        parts = []
        for name, p in ctx.rules.get("parameters", {}).items():
            missing = [k for k, v in (p.get("values") or {}).items() if v is None]
            if not missing:
                continue
            bound = sorted(r["rule_id"] for r in ctx.rules.get("rules", [])
                           if name in (r.get("threshold_low_param"), r.get("threshold_high_param")))
            where = " and ".join(f"clause {d.get('clause')} p{d.get('page')}" for d in p.get("defined_in", []))
            parts.append(f"{', '.join(p.get('printed_as') or [name])} ({', '.join(missing)}), defined in {where}, "
                         f"bounding {', '.join(bound) or 'no rule'}")
        return "Named in the Rules with no value stated: " + "; ".join(parts) + "." if parts else \
            "rules.json holds no parameter without a value."
    if kind == "contract_evidence":
        name = Path(ctx.analytics["tests"][HVS_TEST]["full_list"]).name
        cols, rows = load_csv(af_dir / name, cache)
        gp = [r for r in rows if r.get("spend_tag") == PRIMARY_TAG]
        npnf = sum(1 for r in gp if r.get("no_published_notice_class") == NPNF)
        figs.add("PBC.contract_evidence.suppliers", len(gp), f"{PRIMARY_TAG} rows of {name}", "audit-program.md")
        figs.add("PBC.contract_evidence.no_published_notice_found", npnf,
                 f"{PRIMARY_TAG} rows of {name} with no_published_notice_class = {NPNF}", "audit-program.md")
        return (f"Population: the {len(gp):,} {PRIMARY_TAG} suppliers in `outputs/analytics-full/{name}`. Request "
                f"first for the {npnf:,} marked {NPNF}, largest total first, then for the rest, largest total first.")
    return ""


# ---------------------------------------------------------------- rendering

def header(title, n, built):
    return [f"# {title} (register revision r{n})", "",
            f"Built {built} by `.claude/skills/audit-program/build_pack.py` from `outputs/audit-plan.json`, on the "
            f"risks the auditor approved in register r{n}. For auditor sign-off.", "", INDICATOR_NOTE, ""]


def l_text(method, rs):
    s = BR.l_label(method, rs["l"])
    if "likelihood" in rs["override"]:
        s += f" (auditor override; the rubric gives {BR.l_label(method, rs['override']['likelihood'])})"
    return s


def i_text(method, rs):
    return BR.i_label(method, rs["i"]) + (" (auditor override)" if rs["override"].get("impact") else "")


def escalation(ctx, method, scope, figs):
    """The Risk Management Strategy's two Corporate Risk Register thresholds,
    and the in-scope risks they disagree on."""
    c = next((c for c in method.get("conflicts", []) if c["kind"] == "crr_threshold"), None)
    if c is None:
        return None
    tab = min((b for b in method["bands"] if "corporate risk register" in (b.get("escalation") or "").lower()),
              key=lambda b: b["lo"])
    lo, hi = c["affects"]
    fig = lo if lo < tab["lo"] else hi + 1
    hits = [rs for rs in scope["risks"] if lo <= rs["score"] <= hi]
    doc = "planning-memo.md"
    figs.add("escalation.figure4_threshold", fig, "history.json risk_scoring_method.escalation: Figure 4", doc)
    figs.add("escalation.table4_band", tab["score_printed"], f"history.json risk_scoring_method.bands: {tab['level']}", doc)
    figs.add("escalation.disputed_scores", [lo, hi], "scores on which Figure 4 and Table 4 disagree", doc)
    figs.add("escalation.risks", [rs["id"] for rs in hits], f"in-scope risks scoring {lo} to {hi}", doc)
    dis = ", ".join(c["history"]) or "no history item"
    if fig < tab["lo"]:
        go = "would go to the Corporate Risk Register under Figure 4, though not under Table 4, which the register uses"
    else:
        go = "would go to the Corporate Risk Register under Table 4, which the register uses, though not under Figure 4"
    listed = ", ".join(f"{rs['id']} (score {rs['score']})" for rs in hits) or "none"
    return [
        f"The Risk Management Strategy contradicts itself on escalation (history {dis}): Figure 4 places risks "
        f"scoring {fig} or above on the Corporate Risk Register, while Table 4 adds a risk to it only in band "
        f"{tab['level']} (score {tab['score_printed']}). In-scope risks scoring {lo} to {hi} {go}: {listed}.",
        "",
        "This pack does not resolve the conflict; the auditor decides whether to raise it with the risk owner.",
    ], c["history"]


def sources(ctx, tags):
    seen, out = set(), []
    for t in tags:
        t = BR.resolve_tag(ctx, dict(t))
        key = t.get("canonical") or t["ref"]
        if t.get("ok") and key not in seen:
            seen.add(key)
            out.append(f"- {t['source']}")
    return out


def render_memo(ctx, method, scope, ev, inputs, built, figs, esc):
    n, doc = scope["n"], "planning-memo.md"
    L = header("Audit planning memo: procurement", n, built)
    L += ["## Objective", "", ev["memo"]["objective"], "", "## Background", "", ev["memo"]["background"], ""]
    count = figs.add("scope.risks", len(scope["risks"]), "risks approved or amended by the auditor", doc)
    L += ["## Scope", "",
          f"The auditor decided every row of register r{n} in `outputs/auditor-comments.md`. In scope: the {count} "
          "risks approved or amended.", "",
          "| Risk | Title | Likelihood | Impact | Score | Band | Decision | Tests | Sample items |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in ev["risks"]:
        rs = r["rs"]
        figs.add(f"{rs['id']}.score", rs["score"], f"likelihood {rs['l']} x impact {rs['i']} on the council's matrix", doc)
        items = sum(t["sample"]["items"] for t in r["tests"] if t["sample"])
        figs.add(f"{rs['id']}.sample_items", items, "items drawn across the risk's tests", doc)
        d = rs["decision"]
        dec = d["decision"] + (f": {d['comment']}" if d.get("comment") else "")
        L.append("| " + " | ".join(BR.md_cell(x) for x in [
            rs["id"], rs["risk"]["title"], l_text(method, rs), i_text(method, rs), rs["score"], BR.band_text(rs["band"]),
            dec, ", ".join(t["id"] for t in r["tests"]), items]) + " |")
    L += ["", "### Out of scope", ""]
    if scope["out"]:
        L += ["| Item | Title | Decision | Auditor's comment |", "| --- | --- | --- | --- |"]
        L += ["| " + " | ".join(BR.md_cell(x) for x in [o["id"], o["title"], o["decision"], o["comment"]]) + " |"
              for o in scope["out"]]
    else:
        L.append("None.")
    L += ["", "## Escalation under the Risk Management Strategy", ""]
    L += esc[0] if esc else ["history.json records no conflict between the Strategy's escalation thresholds."]
    L += ["", "## Approach", "", ev["memo"]["approach"], "", "### Sampling", "",
          f"Every sample is drawn by `build_pack.py` from the {PRIMARY_TAG} rows of the `outputs/analytics-full/` "
          "lists, the rows the register's ratings rest on; placement, grant, agency staff and premises rows are not "
          "sampled. Each test names its list, a filter, a sort order and a size. The draw is deterministic (a stable "
          "sort on the list as published, ties in list order), so the same inputs give the same sample, and every "
          "sampled transaction is checked against `spend-clean.csv`. A sample may be larger than its score gives, "
          "never smaller; where the population is smaller, all of it is taken.", "",
          "| Risk score | Items per test |", "| --- | --- |"]
    figs.add("sampling.size_table", [list(x) for x in SAMPLE_SIZES], "(lowest score, items per test); fixed in build_pack.py", doc)
    hi = BR.MAX_SCORE * BR.MAX_SCORE
    for lo, items in SAMPLE_SIZES:
        L.append(f"| {lo} to {hi} | {items} |")
        hi = lo - 1
    L += ["", "| Test | Risk | List | Population | Size | Items | Transactions | Value |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in ev["risks"]:
        for t in r["tests"]:
            s = t["sample"]
            if not s:
                L.append(f"| {t['id']} | {r['rs']['id']} | none | | | | | |")
                continue
            sample_figs(figs, t["id"], r["rs"], s, doc)
            L.append(f"| {t['id']} | {r['rs']['id']} | `{s['file']}` | {s['population']:,} | {size_text(r['rs'], s)} "
                     f"| {s['items']:,} | {s['transactions']:,} | {gbp(s['pence'])} |")
    L += ["", "## Limitations", "", ev["memo"]["limitations"], "", "## Inputs", "", "| File | sha256 |", "| --- | --- |"]
    L += [f"| `{k}` | `{v}` |" for k, v in inputs.items()]
    src = sources(ctx, ev["memo_tags"] + [{"kind": "history", "ref": h} for h in (esc[1] if esc else [])])
    L += ["", "## Sources", ""] + (src or ["None cited."])
    return "\n".join(L) + "\n"


def size_text(rs, s):
    if s["size"] == "by_score":
        txt = f"{s['rule_size']} items for score {rs['score']}"
    elif s["size"] == "all":
        txt = f"every item, at the planner's request (score {rs['score']} gives {s['rule_size']})"
    else:
        txt = f"{s['size']} items, at the planner's request (score {rs['score']} gives {s['rule_size']})"
    if s["population"] < s["target"]:
        txt += f"; the population is smaller, so all {s['population']:,} are taken"
    return txt


def sample_figs(figs, tid, rs, s, doc):
    figs.add(f"{tid}.population", s["population"], f"{s['where']} of {s['file']}; equals {s['metric']}", doc)
    figs.add(f"{tid}.size_rule", s["rule_size"], f"items for score {rs['score']} from the size table", doc)
    figs.add(f"{tid}.items", s["items"], f"items drawn: sorted by {s['sort']}", doc)
    figs.add(f"{tid}.transactions", s["transactions"], f"rows of outputs/samples/{tid}.csv", doc)
    figs.add(f"{tid}.value", round(s["pence"] / 100, 2), f"sum of net_amount over outputs/samples/{tid}.csv", doc)


def render_rcm(ctx, method, scope, ev, built, figs):
    doc = "risk-control-matrix.md"
    L = header("Risk-control matrix", scope["n"], built)
    L += ["Each in-scope risk, the controls expected to address it, the rules each control rests on and the tests "
          "that check it.", "",
          "| Risk | Score | Band | Control | Expected control | Rules | Tests |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in ev["risks"]:
        rs = r["rs"]
        figs.add(f"{rs['id']}.score", rs["score"], f"likelihood {rs['l']} x impact {rs['i']} on the council's matrix", doc)
        for c in r["controls"]:
            L.append("| " + " | ".join(BR.md_cell(x) for x in [
                f"{rs['id']} {rs['risk']['title']}", rs["score"], BR.band_text(rs["band"]), c["id"], c["text"],
                ", ".join(c["rules"]), ", ".join(c["tests"])]) + " |")
    total = figs.add("rules.total", len(ctx.rules_by_id), "rules in rules.json", doc)
    traced = figs.add("rules.traced", len(ev["trace"]), "rules cited by an in-scope risk, control or test", doc)
    nt = figs.add("rules.not_tested", len(ev["not_tested"]), "rules listed as not tested with a reason", doc)
    L += ["", "## Rule coverage", "",
          f"Every rule in `outputs/rules.json` ({total}): {traced} traced to the in-scope risk, control or test that "
          f"cites it, {nt} listed as not tested with the planner's reason.", "",
          "| Rule | Clause | Type | Traced to | Not tested: reason |", "| --- | --- | --- | --- | --- |"]
    for rid, rule in ctx.rules_by_id.items():
        L.append("| " + " | ".join(BR.md_cell(x) for x in [
            rid, rule.get("clause"), rule.get("type"), ", ".join(ev["trace"].get(rid, [])),
            ev["not_tested"].get(rid, "")]) + " |")
    return "\n".join(L) + "\n"


def render_program(ctx, method, scope, ev, built, figs, details):
    doc = "audit-program.md"
    L = header("Audit program", scope["n"], built)
    L += ["Per approved risk: the expected controls, the test steps, and the sample each test pulls. Sampled "
          "transactions are in `outputs/samples/`, one file per test. The PBC (request) list closes the program.", ""]
    for r in ev["risks"]:
        rs = r["rs"]
        d = rs["decision"]
        figs.add(f"{rs['id']}.score", rs["score"], f"likelihood {rs['l']} x impact {rs['i']} on the council's matrix", doc)
        ov = rs["override"]
        notes = ([f"Likelihood is an auditor override; the rubric gives {BR.l_label(method, ov['likelihood'])}."]
                 if "likelihood" in ov else []) + (["Impact is an auditor override."] if ov.get("impact") else [])
        L += [f"## {rs['id']} {rs['risk']['title']}", "",
              " ".join([f"Score {rs['score']}: likelihood {BR.l_label(method, rs['l'])} x impact "
                        f"{BR.i_label(method, rs['i'])}, band {BR.band_text(rs['band'])}.", *notes,
                        f"Auditor's decision: {d['decision']}."] + ([f"Comment: {d['comment']}"] if d.get("comment") else [])),
              "", "**Expected controls**", ""]
        L += [f"- **{c['id']}** {c['text']}" for c in r["controls"]]
        L += ["", "**Tests**", ""]
        for t in r["tests"]:
            L += [f"### {t['id']} (tests {', '.join(t['controls'])})", "", t["text"], ""]
            s = t["sample"]
            if s:
                tid = t["id"]
                sample_figs(figs, tid, rs, s, doc)
                per = f", at most {s['max_per_item']} per item (largest first)" if s["max_per_item"] else ""
                L += [f"- **Population:** `outputs/analytics-full/{s['file']}`, {s['where']}: {s['population']:,} "
                      f"(`metric:{s['metric']}`).",
                      f"- **Selection:** sorted by {s['sort']}; size {size_text(rs, s)}.",
                      f"- **Drawn:** {s['items']:,} items, {s['transactions']:,} transactions from "
                      f"{s['transactions_col']}{per}, {gbp(s['pence'])}: `outputs/samples/{tid}.csv`."]
                if t["reason"]:
                    L.append(f"- **Size reason:** {t['reason']}")
            else:
                L.append(f"- **No sample:** {t['reason']}")
            L += [f"- **Needs:** {', '.join(t['pbc'])}", ""]
    L += ["## PBC list", "",
          "Documents and records to request from the council before fieldwork.", "",
          "| PBC | Request | Needed for |", "| --- | --- | --- |"]
    for p in ev["pbc"]:
        text = p["text"] + (f" {details[p['standing']]}" if p["standing"] and details.get(p["standing"]) else "")
        need = ", ".join(p["tests"]) or "planning (standing request)"
        L.append("| " + " | ".join(BR.md_cell(x) for x in [p["id"], text, need]) + " |")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- main

def show_lists(analytics, af_dir):
    cache = {}
    for name, test in sorted(list_files(analytics).items()):
        p = af_dir / name
        if not p.exists():
            print(f"{name} ({test}): not found")
            continue
        cols, rows = load_csv(p, cache)
        gp = sum(1 for r in rows if r.get("spend_tag") == PRIMARY_TAG)
        ids = [c for c in cols if c == "transaction_id" or c.endswith("_ids")]
        print(f"{name} ({test}): {gp} {PRIMARY_TAG} rows of {len(rows)}; id columns: {', '.join(ids)}\n"
              f"  columns: {', '.join(cols)}")
    return 0


def fail(errs):
    print(f"FAIL: {len(errs)} error(s); nothing written", file=sys.stderr)
    for e in errs:
        print(f"  ERROR {e}", file=sys.stderr)
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT_DEFAULT)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--plan", type=Path)
    ap.add_argument("--analytics", type=Path)
    ap.add_argument("--history", type=Path)
    ap.add_argument("--rules", type=Path)
    ap.add_argument("--analytics-full", type=Path)
    ap.add_argument("--gate", action="store_true", help="run only the gate check; writes nothing")
    ap.add_argument("--lists", action="store_true", help="print the lists a sample can be drawn from; writes nothing")
    a = ap.parse_args(argv)
    root = a.root.resolve()
    out_dir = (a.out_dir or root / "outputs").resolve()
    af_dir = (a.analytics_full or root / "outputs/analytics-full").resolve()
    paths = {
        "analytics.json": a.analytics or root / "outputs/analytics.json",
        "history.json": a.history or root / "outputs/history.json",
        "rules.json": a.rules or root / "outputs/rules.json",
        "risk-ratings.json": out_dir / "risk-ratings.json",
    }
    try:
        if a.lists:
            return show_lists(load_json("analytics.json", paths["analytics.json"]), af_dir)
        data = {name: load_json(name, p) for name, p in paths.items()}
    except Stop as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 1
    shas = {name: BR.sha256(p) for name, p in paths.items()}
    ratings = data["risk-ratings.json"]
    ctx = BR.Ctx(data["analytics.json"], data["history.json"], data["rules.json"])
    ctx.ratings = ratings
    method = BR.build_method(ctx)
    if method is None:
        return fail(ctx.errors)

    scope, errs = gate(out_dir, ratings, {k: v for k, v in shas.items() if k != "risk-ratings.json"}, ctx, method)
    if errs:
        return fail(["gate: " + e for e in errs])
    if a.gate:
        print(f"GATE OK: register r{scope['n']}; {len(scope['risks'])} risks in scope: "
              + ", ".join(f"{rs['id']} ({rs['decision']['decision']}, score {rs['score']})" for rs in scope["risks"]))
        if scope["out"]:
            print("  out of scope: " + ", ".join(f"{o['id']} ({o['decision']})" for o in scope["out"]))
        return 0

    plan_path = a.plan or out_dir / "audit-plan.json"
    spend_path = af_dir / "spend-clean.csv"
    try:
        plan = load_json("audit-plan.json", plan_path)
        errs = check_schema(plan, scope)
        if errs:
            return fail(errs)
        cache = {}
        _, spend_rows = load_csv(spend_path, cache)
        spend = {r["transaction_id"]: r for r in spend_rows}
        figs = Figures()
        errs, ev = evaluate(ctx, plan, scope, list_files(ctx.analytics), af_dir, spend, figs)
        if errs:
            return fail(errs)
        esc = escalation(ctx, method, scope, figs)
        if esc is None:
            return fail(["the Risk Management Strategy's escalation conflict (Figure 4 against Table 4) was not found "
                         "in history.json, so the memo cannot state it"])
        details = {k: standing_detail(ctx, k, af_dir, cache, figs) for k in STANDING_PBC}
    except Stop as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 1

    inputs = {"audit-plan.json": BR.sha256(plan_path), **shas, "spend-clean.csv": BR.sha256(spend_path)}
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    samples = [(t["id"], t["sample"]) for r in ev["risks"] for t in r["tests"] if t["sample"]]
    program = render_program(ctx, method, scope, ev, built, figs, details)
    rcm = render_rcm(ctx, method, scope, ev, built, figs)
    memo = render_memo(ctx, method, scope, ev, inputs, built, figs, esc)

    sample_dir = out_dir / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    for old in sample_dir.glob("T-*.csv"):
        old.unlink()
    written = []
    for tid, s in samples:
        p = sample_dir / f"{tid}.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=SAMPLE_COLS)
            wr.writeheader()
            wr.writerows(s["rows"])
        written.append({"test_id": tid, "file": f"outputs/samples/{tid}.csv", "rows": len(s["rows"]),
                        "sha256": BR.sha256(p)})
    (out_dir / "planning-memo.md").write_text(memo, encoding="utf-8")
    (out_dir / "risk-control-matrix.md").write_text(rcm, encoding="utf-8")
    (out_dir / "audit-program.md").write_text(program, encoding="utf-8")
    (out_dir / "pack-figures.json").write_text(json.dumps({
        "built": built, "register_revision": scope["n"], "inputs": inputs,
        "figures": list(figs.figures.values()), "placeholders": list(figs.placeholders.values()),
        "samples": written}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"OK: pack for register r{scope['n']}: {len(ev['risks'])} risks, "
          f"{sum(len(r['controls']) for r in ev['risks'])} controls, {sum(len(r['tests']) for r in ev['risks'])} tests, "
          f"{len(samples)} samples ({sum(s['transactions'] for _, s in samples)} transactions), {len(ev['pbc'])} PBC items; "
          f"rules: {len(ev['trace'])} traced, {len(ev['not_tested'])} not tested")
    print(f"  wrote {out_dir / 'planning-memo.md'}, {out_dir / 'risk-control-matrix.md'}, "
          f"{out_dir / 'audit-program.md'}, {out_dir / 'pack-figures.json'}, {len(written)} files in {sample_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
