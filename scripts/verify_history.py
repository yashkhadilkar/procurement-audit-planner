#!/usr/bin/env python3
"""Verify outputs/history.json against the committee papers in data/committee/.

Checks the schema (records only: no keys beyond the schema, so no scores or
ratings of its own), sequential ids, that every source PDF is listed with its
sha256, that every quote is on its stated pdf_page, that each recorded field
is copied from its quote, and runs consistency checks on the scoring method
(matrix products, score bands, impact bands). Every inconsistency those checks
find must be recorded in `discrepancies` with a matching `check_ref`.

Usage:
    .venv/bin/python scripts/verify_history.py [HISTORY_JSON] [--committee DIR]
    .venv/bin/python scripts/verify_history.py --find PDF "text"   # locate text

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
from pathlib import Path

MIN_FRAGMENT = 4      # shortest quote fragment (table cells such as "Weak")
MIN_ANCHOR = 10       # every cite needs one fragment at least this long

TOP_KEYS = {"generated", "sources", "audits", "opinion_basis", "agreed_actions",
            "risk_themes", "risk_register_access", "risk_scoring_method",
            "discrepancies", "gaps"}
SOURCE_KEYS = {"file", "sha256", "pages", "title"}
CITE_REQUIRED = {"file", "pdf_page", "section", "quote"}
CITE_OPTIONAL = {"layout_quote"}
AUDIT_KEYS = {"id", "kind", "report_period", "directorate", "service", "title",
              "opinion", "implementation_progress", "cites"}
AUDIT_KINDS = {"completed_audit", "follow_up", "advisory_review"}
OPB_KEYS = {"id", "summary", "cites"}
ACTION_KEYS = {"id", "audit_ref", "theme", "due_date", "status", "cites"}
THEME_KEYS = {"id", "kind", "theme", "cites"}
THEME_KINDS = {"internal_context", "external_context", "risk_source_prompt",
               "audit_plan_reference", "audit_finding"}
RRA_KEYS = {"status", "name_in_papers", "note", "cites"}
RSM_KEYS = {"status", "not_found_reason", "evaluation_levels", "likelihood_scale",
            "impact_scale", "matrix", "bands", "appetite", "escalation"}
LEVEL_KEYS = {"level", "definition", "cites"}
LIKELIHOOD_KEYS = {"score", "label", "incidents", "probability", "cites"}
IMPACT_KEYS = {"score", "label", "criteria", "cites"}
MATRIX_KEYS = {"title", "likelihood_axis", "impact_axis", "axis_cites", "rows"}
AXIS_KEYS = {"score", "label"}
ROW_KEYS = {"impact", "labels", "scores", "cites"}
BAND_KEYS = {"level", "rag", "score_printed", "escalation", "response", "cites"}
APPETITE_KEYS = {"levels", "levels_cites", "categories", "statements"}
APP_CAT_KEYS = {"category", "cells", "cites"}
APP_STMT_KEYS = {"category", "appetite", "statement", "cites"}
ESCALATION_KEYS = {"register", "criterion", "cites"}
DISC_KEYS = {"id", "kind", "description", "check_ref", "cites"}
DISC_KINDS = {"internal_inconsistency", "cross_reference", "numbering",
              "terminology", "drafting"}
GAP_KEYS = {"id", "topic", "detail", "searched", "cites"}
GAP_TOPICS = {"audits", "opinion_scale", "agreed_actions", "risk_themes",
              "risk_scoring_method", "risk_register", "source_document", "other"}

ID_PREFIX = {"audits": "AUD", "opinion_basis": "OPB", "agreed_actions": "ACT",
             "risk_themes": "THM", "discrepancies": "DIS", "gaps": "GAP"}

PRIVATE_USE = re.compile(r"[-]")
FOLD = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


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


class Pdf:
    """Per page: normalised plain text, layout text, and layout text with
    line-end hyphens rejoined (plain mode drops them: "de-\\nescalated")."""

    def __init__(self, path):
        self.path = path
        plain, layout = pdftotext_pages(path, False), pdftotext_pages(path, True)
        if len(plain) != len(layout) or not plain:
            raise RuntimeError(f"page split mismatch in {path} (plain {len(plain)}, layout {len(layout)})")
        self.n_pages = len(plain)
        self.plain = [norm(p) for p in plain]
        self.layout = [norm(p) for p in layout]
        self.rejoined = [norm(re.sub(r"-[ \t]*\n[ \t]*", "-", p)) for p in layout]
        self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    def variants(self, page, layout_only=False):
        i = page - 1
        return (self.layout[i], self.rejoined[i]) if layout_only else \
            (self.plain[i], self.layout[i], self.rejoined[i])

    def find(self, text, layout_only=False):
        q = norm(text)
        return [p for p in range(1, self.n_pages + 1)
                if any(q in v for v in self.variants(p, layout_only))]

    def find_folded(self, text, layout_only=False):
        q = norm(text).translate(FOLD)
        return [p for p in range(1, self.n_pages + 1)
                if any(q in v.translate(FOLD) for v in self.variants(p, layout_only))]


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
        rep.add("SCHEMA", where, f"unknown keys: {sorted(unknown)} (history.json records; it never adds fields)")
    return not missing


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def nonempty_str(v):
    return isinstance(v, str) and v.strip() != ""


def opt_str(rep, where, v):
    if v is not None and not nonempty_str(v):
        rep.add("SCHEMA", where, "must be a non-empty string or null")


def as_list(rep, where, v, allow_empty=True):
    if not isinstance(v, list) or (not allow_empty and not v):
        rep.add("SCHEMA", where, "must be a list" if allow_empty else "must be a non-empty list")
        return []
    return v


class Ctx:
    def __init__(self, rep, pdfs, listed):
        self.rep = rep
        self.pdfs = pdfs          # file string -> Pdf
        self.listed = listed      # files named in history.json sources


def check_cites(ctx, where, cites, bound=(), min_cites=1):
    """Check every cite and that each bound field value is copied from one of
    its quotes. `bound` is a list of (field_name, value) pairs; a value is a
    string, an int (matched as a whole token) or a list (matched joined by
    single spaces)."""
    rep = ctx.rep
    cites = as_list(rep, f"{where}.cites", cites)
    if len(cites) < min_cites:
        rep.add("SCHEMA", f"{where}.cites", f"needs at least {min_cites} cite(s)")
    texts = []                    # normalised fragments and layout quotes
    for i, c in enumerate(cites):
        cw = f"{where}.cites[{i}]"
        if not check_keys(rep, cw, c, CITE_REQUIRED, CITE_OPTIONAL):
            continue
        texts += check_cite(ctx, cw, c)
    for name, value in bound:
        if value is None:
            continue
        if isinstance(value, list):
            needle = " ".join(str(v) for v in value)
        else:
            needle = str(value)
        n = norm(needle)
        if is_int(value):
            hit = any(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d.])", t) for t in texts)
        else:
            hit = any(n in t for t in texts)
        if not hit:
            rep.add("FIELD_NOT_IN_QUOTE", f"{where}.{name}",
                    f"{needle!r} does not appear in any quote or layout_quote of this item")


def check_cite(ctx, where, c):
    rep = ctx.rep
    f, page = c["file"], c["pdf_page"]
    if not nonempty_str(c["section"]):
        rep.add("SCHEMA", f"{where}.section", "must name the section, table or heading")
    k = path_key(f)
    if k not in ctx.listed or k not in ctx.pdfs:
        rep.add("SOURCE_UNKNOWN", f"{where}.file", f"{f!r} is not a listed source PDF in the committee folder")
        return []
    pdf = ctx.pdfs[k]
    if not is_int(page) or not 1 <= page <= pdf.n_pages:
        rep.add("SCHEMA", f"{where}.pdf_page", f"must be an integer 1..{pdf.n_pages}, got {page!r}")
        return []

    quote = c["quote"]
    frags = [quote] if isinstance(quote, str) else quote
    if not isinstance(frags, list) or not frags or not all(isinstance(q, str) for q in frags):
        rep.add("SCHEMA", f"{where}.quote", "must be a string or a non-empty list of strings")
        frags = []
    found, longest = [], 0
    for i, frag in enumerate(frags):
        fw = f"{where}.quote[{i}]" if isinstance(quote, list) else f"{where}.quote"
        q = norm(frag)
        if "..." in frag or "…" in frag:
            rep.add("QUOTE_FORMAT", fw, "contains an ellipsis; use a list of contiguous passages instead")
            continue
        if len(q) < MIN_FRAGMENT:
            rep.add("QUOTE_FORMAT", fw, f"shorter than {MIN_FRAGMENT} characters: {frag!r}")
            continue
        longest = max(longest, len(q))
        if any(q in v for v in pdf.variants(page)):
            found.append(q)
            continue
        rep.add("QUOTE_NOT_FOUND", fw, f"not on page {page}; {hint(pdf, frag)}: {frag[:80]!r}")

    lq = c.get("layout_quote")
    if lq is not None:
        lw = f"{where}.layout_quote"
        if not isinstance(lq, str) or len(norm(lq)) < MIN_ANCHOR:
            rep.add("QUOTE_FORMAT", lw, f"must be a string of at least {MIN_ANCHOR} characters")
        elif "..." in lq or "…" in lq:
            rep.add("QUOTE_FORMAT", lw, "contains an ellipsis")
        elif any(norm(lq) in v for v in pdf.variants(page, layout_only=True)):
            found.append(norm(lq))
            longest = max(longest, len(norm(lq)))
        else:
            rep.add("LAYOUT_QUOTE_NOT_FOUND", lw,
                    f"not in the -layout text of page {page}; {hint(pdf, lq, layout_only=True)}: {lq[:80]!r}")
    if frags and longest and longest < MIN_ANCHOR:
        rep.add("QUOTE_FORMAT", where, f"needs at least one fragment of {MIN_ANCHOR}+ characters")
    return found


def hint(pdf, text, layout_only=False):
    pages = pdf.find(text, layout_only)
    if pages:
        return f"found on page(s) {pages} instead"
    folded = pdf.find_folded(text, layout_only)
    if folded:
        return (f"matches page(s) {folded} only after folding curly quotes/dashes; "
                f"copy the printed characters")
    return "not found anywhere in this PDF"


def check_ids(rep, name, items):
    prefix = ID_PREFIX[name]
    for n, item in enumerate(items, start=1):
        rid = item.get("id") if isinstance(item, dict) else None
        expected = f"{prefix}-{n:02d}"
        if rid != expected:
            rep.add("ID_SEQUENCE", f"{name}[{n - 1}]", f"id {rid!r}; expected {expected}")


# ---------------------------------------------------------------- sections

def check_sources(rep, data, pdfs):
    listed = set()
    for i, s in enumerate(as_list(rep, "sources", data.get("sources"), allow_empty=False)):
        where = f"sources[{i}]"
        if not check_keys(rep, where, s, SOURCE_KEYS):
            continue
        f, k = s["file"], path_key(s["file"])
        if k not in pdfs:
            rep.add("SOURCE_UNKNOWN", f"{where}.file", f"{f!r} is not a PDF in the committee folder")
            continue
        listed.add(k)
        if s["sha256"] != pdfs[k].sha256:
            rep.add("SOURCE_MISMATCH", f"{where}.sha256", f"does not match {f} ({pdfs[k].sha256})")
        if s["pages"] != pdfs[k].n_pages:
            rep.add("SOURCE_MISMATCH", f"{where}.pages", f"{s['pages']!r} but the PDF has {pdfs[k].n_pages}")
        if not nonempty_str(s["title"]):
            rep.add("SCHEMA", f"{where}.title", "must be a non-empty string")
    for k in sorted(set(pdfs) - listed):
        rep.add("SOURCE_COVERAGE", "sources", f"{pdfs[k].path} is in the committee folder but not listed")
    return listed


def check_audits(ctx, data):
    items = as_list(ctx.rep, "audits", data.get("audits"))
    check_ids(ctx.rep, "audits", items)
    for i, a in enumerate(items):
        where = f"audits[{i}]"
        if not check_keys(ctx.rep, where, a, AUDIT_KEYS):
            continue
        if a["kind"] not in AUDIT_KINDS:
            ctx.rep.add("SCHEMA", f"{where}.kind", f"{a['kind']!r} not in {sorted(AUDIT_KINDS)}")
        for k in ("report_period", "title"):
            if not nonempty_str(a[k]):
                ctx.rep.add("SCHEMA", f"{where}.{k}", "must be a non-empty string")
        for k in ("directorate", "service", "opinion", "implementation_progress"):
            opt_str(ctx.rep, f"{where}.{k}", a[k])
        cites = a["cites"] if isinstance(a["cites"], list) else []
        if not any(isinstance(c, dict) and c.get("layout_quote") for c in cites):
            ctx.rep.add("LAYOUT_QUOTE_MISSING", where,
                        "table rows need a layout_quote showing the row's cells side by side")
        check_cites(ctx, where, a["cites"], [(k, a[k]) for k in (
            "report_period", "directorate", "service", "title", "opinion", "implementation_progress")])


def check_simple(ctx, data, name, keys, kinds_key=None, kinds=None, bound=()):
    items = as_list(ctx.rep, name, data.get(name))
    check_ids(ctx.rep, name, items)
    for i, it in enumerate(items):
        where = f"{name}[{i}]"
        if not check_keys(ctx.rep, where, it, keys):
            continue
        if kinds_key and it[kinds_key] not in kinds:
            ctx.rep.add("SCHEMA", f"{where}.{kinds_key}", f"{it[kinds_key]!r} not in {sorted(kinds)}")
        for k in keys - {"id", "cites", "audit_ref"}:
            opt_str(ctx.rep, f"{where}.{k}", it[k])
        check_cites(ctx, where, it["cites"], [(k, it[k]) for k in bound])
    return items


def check_register_access(ctx, data):
    r = data.get("risk_register_access")
    if not check_keys(ctx.rep, "risk_register_access", r, RRA_KEYS):
        return
    if r["status"] not in {"not public", "public"}:
        ctx.rep.add("SCHEMA", "risk_register_access.status", "must be 'not public' or 'public'")
    if not nonempty_str(r["note"]):
        ctx.rep.add("SCHEMA", "risk_register_access.note", "must be a non-empty string")
    check_cites(ctx, "risk_register_access", r["cites"], [("name_in_papers", r["name_in_papers"])])


def check_scoring(ctx, data):
    """Schema and quotes for the scoring method. Returns it if usable for the
    consistency checks, else None."""
    rep = ctx.rep
    m = data.get("risk_scoring_method")
    W = "risk_scoring_method"
    if not check_keys(rep, W, m, RSM_KEYS):
        return None
    if m["status"] not in {"found", "not found"}:
        rep.add("SCHEMA", f"{W}.status", "must be 'found' or 'not found'")
        return None
    if m["status"] == "not found":
        if not nonempty_str(m["not_found_reason"]):
            rep.add("SCHEMA", f"{W}.not_found_reason", "required when status is 'not found'")
        return None
    if m["not_found_reason"] is not None:
        rep.add("SCHEMA", f"{W}.not_found_reason", "must be null when status is 'found'")

    for i, lv in enumerate(as_list(rep, f"{W}.evaluation_levels", m["evaluation_levels"])):
        w = f"{W}.evaluation_levels[{i}]"
        if check_keys(rep, w, lv, LEVEL_KEYS):
            check_cites(ctx, w, lv["cites"], [("level", lv["level"])])

    for name, keys, fields in (("likelihood_scale", LIKELIHOOD_KEYS, ("score", "label", "incidents", "probability")),
                               ("impact_scale", IMPACT_KEYS, ("score", "label"))):
        items = as_list(rep, f"{W}.{name}", m[name], allow_empty=False)
        for i, it in enumerate(items):
            w = f"{W}.{name}[{i}]"
            if not check_keys(rep, w, it, keys):
                continue
            if not is_int(it["score"]):
                rep.add("SCHEMA", f"{w}.score", "must be the printed integer score")
            bound = [(k, it[k]) for k in fields]
            if name == "impact_scale":
                if not isinstance(it["criteria"], dict) or not it["criteria"]:
                    rep.add("SCHEMA", f"{w}.criteria", "must map each printed column heading to its cell text")
                else:
                    bound += [(f"criteria.{k}", v) for k, v in it["criteria"].items()]
            check_cites(ctx, w, it["cites"], bound)
        scores = sorted(it["score"] for it in items if isinstance(it, dict) and is_int(it.get("score")))
        if scores and scores != list(range(1, len(scores) + 1)):
            rep.add("SCHEMA", f"{W}.{name}", f"scores {scores} are not 1..n without gaps")

    matrix = m["matrix"]
    if check_keys(rep, f"{W}.matrix", matrix, MATRIX_KEYS):
        axis_bound = []
        for axis in ("likelihood_axis", "impact_axis"):
            for i, ax in enumerate(as_list(rep, f"{W}.matrix.{axis}", matrix[axis], allow_empty=False)):
                if check_keys(rep, f"{W}.matrix.{axis}[{i}]", ax, AXIS_KEYS):
                    if not is_int(ax["score"]):
                        rep.add("SCHEMA", f"{W}.matrix.{axis}[{i}].score", "must be the printed integer")
                    axis_bound += [(f"{axis}[{i}].score", ax["score"]), (f"{axis}[{i}].label", ax["label"])]
        if nonempty_str(matrix["title"]):
            axis_bound.append(("title", matrix["title"]))
        check_cites(ctx, f"{W}.matrix", matrix["axis_cites"], axis_bound)
        n_cols = len(matrix["likelihood_axis"]) if isinstance(matrix["likelihood_axis"], list) else 0
        for i, row in enumerate(as_list(rep, f"{W}.matrix.rows", matrix["rows"], allow_empty=False)):
            w = f"{W}.matrix.rows[{i}]"
            if not check_keys(rep, w, row, ROW_KEYS):
                continue
            for k in ("labels", "scores"):
                if not isinstance(row[k], list) or len(row[k]) != n_cols:
                    rep.add("SCHEMA", f"{w}.{k}", f"must list {n_cols} cells, one per likelihood column")
            if isinstance(row["scores"], list) and not all(is_int(s) for s in row["scores"]):
                rep.add("SCHEMA", f"{w}.scores", "must be the printed integer cell scores")
            check_cites(ctx, w, row["cites"], [("impact", row["impact"]), ("labels", row["labels"]),
                                               ("scores", row["scores"])])

    for i, b in enumerate(as_list(rep, f"{W}.bands", m["bands"], allow_empty=False)):
        w = f"{W}.bands[{i}]"
        if check_keys(rep, w, b, BAND_KEYS):
            check_cites(ctx, w, b["cites"], [(k, b[k]) for k in
                                             ("level", "rag", "score_printed", "escalation", "response")])

    app = m["appetite"]
    if app is not None and check_keys(rep, f"{W}.appetite", app, APPETITE_KEYS):
        levels = as_list(rep, f"{W}.appetite.levels", app["levels"])
        check_cites(ctx, f"{W}.appetite", app["levels_cites"], [("levels", levels)])
        for i, c in enumerate(as_list(rep, f"{W}.appetite.categories", app["categories"])):
            w = f"{W}.appetite.categories[{i}]"
            if not check_keys(rep, w, c, APP_CAT_KEYS):
                continue
            cells = c["cells"] if isinstance(c["cells"], dict) else {}
            if set(cells) - set(levels):
                rep.add("SCHEMA", f"{w}.cells", f"keys {sorted(set(cells) - set(levels))} are not appetite levels")
            check_cites(ctx, w, c["cites"], [("category", c["category"])] +
                        [(f"cells.{k}", v) for k, v in cells.items()])
        for i, s in enumerate(as_list(rep, f"{W}.appetite.statements", app["statements"])):
            w = f"{W}.appetite.statements[{i}]"
            if check_keys(rep, w, s, APP_STMT_KEYS):
                check_cites(ctx, w, s["cites"], [(k, s[k]) for k in ("category", "appetite", "statement")])

    for i, e in enumerate(as_list(rep, f"{W}.escalation", m["escalation"])):
        w = f"{W}.escalation[{i}]"
        if check_keys(rep, w, e, ESCALATION_KEYS):
            check_cites(ctx, w, e["cites"], [("register", e["register"]), ("criterion", e["criterion"])])
    return m


# ---------------------------------------------------------------- consistency

def parse_band(printed):
    """'15 -25' -> (15, 25); 'Up to 3' -> (1, 3); '9 or above' -> (9, 25)."""
    s = norm(printed)
    m = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.fullmatch(r"(?i)up to (\d+)", s)
    if m:
        return 1, int(m.group(1))
    m = re.fullmatch(r"(?i)(\d+) or (?:above|more)", s)
    if m:
        return int(m.group(1)), math.inf
    return None


def name_key(text):
    return re.sub(r"[^a-z]", "", re.sub(r"\(.*?\)", "", text.lower()))


GBP = re.compile(r"£?\s*(\d+(?:\.\d+)?)\s*([kKmM])\b")
PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_financial(text):
    """Printed financial-loss cell -> ((pct_lo, pct_hi), (gbp_lo, gbp_hi));
    either part None if it cannot be read."""
    s = norm(text)
    less = re.match(r"(?i)less than", s) is not None
    pct_part, _, gbp_part = s.partition("budget")
    pct = [float(x) for x in PCT.findall(pct_part)]
    pct_range = (pct[0], pct[1]) if len(pct) == 2 else \
        ((pct[0], math.inf) if len(pct) == 1 and ">" in pct_part else
         ((0.0, pct[0]) if len(pct) == 1 and less else None))
    gbp = [float(n) * (1_000 if u.lower() == "k" else 1_000_000) for n, u in GBP.findall(gbp_part)]
    gbp_range = (gbp[0], gbp[1]) if len(gbp) == 2 else \
        ((gbp[0], math.inf) if len(gbp) == 1 and ">" in gbp_part else
         ((0.0, gbp[0]) if len(gbp) == 1 and less else None))
    return pct_range, gbp_range


def consistency_findings(m):
    """Every inconsistency the recorded scoring method shows, keyed by a
    stable check_ref. Python computes these; the agent only records them."""
    out = {}
    lik = {a["score"]: a["label"] for a in m["matrix"]["likelihood_axis"]}
    imp = {a["score"]: a["label"] for a in m["matrix"]["impact_axis"]}
    l_order = [a["score"] for a in m["matrix"]["likelihood_axis"]]

    for it in m["likelihood_scale"]:
        if it["score"] in lik and name_key(lik[it["score"]]) != name_key(it["label"]):
            out[f"likelihood.axis:{it['score']}"] = \
                f"likelihood {it['score']} is {it['label']!r} in the scale but {lik[it['score']]!r} on the matrix axis"
    for it in m["impact_scale"]:
        if it["score"] in imp and name_key(imp[it["score"]]) != name_key(it["label"]):
            out[f"impact.axis:{it['score']}"] = \
                f"impact {it['score']} is {it['label']!r} in the scale but {imp[it['score']]!r} on the matrix axis"

    bands = []
    for b in m["bands"]:
        rng = parse_band(b["score_printed"])
        if rng is None:
            out[f"bands.unparsed:{b['level']}"] = f"score range {b['score_printed']!r} cannot be read as a range"
        else:
            bands.append((b["level"], rng))
    for i, (la, (a0, a1)) in enumerate(bands):
        for lb, (b0, b1) in bands[i + 1:]:
            if a0 <= b1 and b0 <= a1:
                out[f"bands.overlap:{la}|{lb}"] = f"bands {la!r} and {lb!r} overlap"

    label_bands = {}
    for row in m["matrix"]["rows"]:
        for l_score, label, score in zip(l_order, row["labels"], row["scores"]):
            cell = f"I{row['impact']}L{l_score}"
            if score != row["impact"] * l_score:
                out[f"matrix.product:{cell}"] = \
                    f"cell {cell} prints {score}; impact {row['impact']} x likelihood {l_score} is {row['impact'] * l_score}"
            hits = [lv for lv, (lo, hi) in bands if lo <= score <= hi]
            if len(hits) != 1:
                out[f"matrix.band:{cell}"] = f"cell {cell} score {score} falls in {len(hits)} bands {hits}"
            else:
                label_bands.setdefault(label, set()).add(hits[0])
    for label, levels in sorted(label_bands.items()):
        if len(levels) > 1:
            out[f"matrix.label:{label}"] = f"cells labelled {label!r} fall in different bands {sorted(levels)}"
        elif name_key(next(iter(levels))) != name_key(label):
            out[f"matrix.label_name:{label}"] = \
                f"matrix cells labelled {label!r} fall in the band named {next(iter(levels))!r}"

    fin = {}
    for it in m["impact_scale"]:
        crit = it["criteria"] if isinstance(it["criteria"], dict) else {}
        key = next((k for k in crit if "financial" in k.lower()), None)
        if key:
            fin[it["score"]] = parse_financial(crit[key])
    for part, idx, unit in (("pct", 0, "%"), ("gbp", 1, "£")):
        for s in sorted(fin):
            if fin[s][idx] is None:
                out[f"impact.financial_{part}.unparsed:{s}"] = f"impact {s} financial cell has no readable {unit} range"
        scored = sorted(s for s in fin if fin[s][idx] is not None)
        for s, t in zip(scored, scored[1:]):
            hi, lo = fin[s][idx][1], fin[t][idx][0]
            if hi > lo:
                out[f"impact.financial_{part}:{s}-{t}"] = \
                    f"impact {s} upper bound {hi:g}{unit} is above impact {t} lower bound {lo:g}{unit} (bands overlap)"
            elif hi < lo:
                out[f"impact.financial_{part}:{s}-{t}"] = \
                    f"impact {s} upper bound {hi:g}{unit} is below impact {t} lower bound {lo:g}{unit} (gap between bands)"
    return out


def check_discrepancies(ctx, data, findings):
    items = check_simple(ctx, data, "discrepancies", DISC_KEYS, "kind", DISC_KINDS)
    refs = {}
    for i, d in enumerate(items):
        if not isinstance(d, dict):
            continue
        ref = d.get("check_ref")
        if ref is not None:
            refs[ref] = i
            if findings is not None and ref not in findings:
                ctx.rep.add("UNKNOWN_CHECK_REF", f"discrepancies[{i}].check_ref",
                            f"{ref!r} is not a finding of the consistency checks")
    if findings:
        for ref, msg in sorted(findings.items()):
            if ref not in refs:
                ctx.rep.add("UNRECORDED_INCONSISTENCY", ref, f"{msg}; record it in discrepancies with check_ref {ref!r}")


def check_gaps(ctx, data):
    items = as_list(ctx.rep, "gaps", data.get("gaps"))
    check_ids(ctx.rep, "gaps", items)
    topics = set()
    for i, g in enumerate(items):
        where = f"gaps[{i}]"
        if not check_keys(ctx.rep, where, g, GAP_KEYS):
            continue
        topics.add(g["topic"])
        if g["topic"] not in GAP_TOPICS:
            ctx.rep.add("SCHEMA", f"{where}.topic", f"{g['topic']!r} not in {sorted(GAP_TOPICS)}")
        if not nonempty_str(g["detail"]):
            ctx.rep.add("SCHEMA", f"{where}.detail", "must be a non-empty string")
        searched = as_list(ctx.rep, f"{where}.searched", g["searched"], allow_empty=False)
        for f in searched:
            if path_key(f) not in ctx.listed:
                ctx.rep.add("SOURCE_UNKNOWN", f"{where}.searched", f"{f!r} is not a listed source")
        check_cites(ctx, where, g["cites"], min_cites=0)
    return topics


def check_required_gaps(rep, data, topics):
    """An empty collection or a missing method must be explained by a gap."""
    for name, topic in (("audits", "audits"), ("agreed_actions", "agreed_actions"),
                        ("risk_themes", "risk_themes")):
        if data.get(name) == [] and topic not in topics:
            rep.add("GAP_MISSING", name, f"is empty; add a gap with topic {topic!r} saying what was searched")
    m = data.get("risk_scoring_method")
    if isinstance(m, dict) and m.get("status") == "not found" and "risk_scoring_method" not in topics:
        rep.add("GAP_MISSING", "risk_scoring_method", "status is 'not found'; add a gap with topic 'risk_scoring_method'")


# ---------------------------------------------------------------- main

def path_key(f):
    """Source files are named relative to the repo root (the working
    directory); compare them by resolved path."""
    return str(Path(f).resolve()) if isinstance(f, str) and f else None


def load_pdfs(committee):
    return {path_key(str(p)): Pdf(p) for p in sorted(committee.glob("*.pdf"))}


def run_find(pdf_path, text):
    pdf = Pdf(Path(pdf_path))
    q = norm(text)
    for p in range(1, pdf.n_pages + 1):
        modes = [n for n, v in zip(("plain", "layout", "layout-rejoined"), pdf.variants(p)) if q in v]
        if modes:
            print(f"page {p}: {', '.join(modes)}")
    if not pdf.find(text):
        folded = pdf.find_folded(text)
        print(f"not found; after folding curly quotes/dashes: pages {folded}" if folded else "not found")
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("history", nargs="?", default="outputs/history.json")
    ap.add_argument("--committee", default="data/committee")
    ap.add_argument("--find", nargs=2, metavar=("PDF", "TEXT"), help="print the pages TEXT is on, and in which mode")
    args = ap.parse_args(argv)

    if shutil.which("pdftotext") is None:
        print("ERROR: pdftotext not found on PATH (install poppler)", file=sys.stderr)
        return 2
    if args.find:
        return run_find(*args.find)

    hist, committee = Path(args.history), Path(args.committee)
    if not hist.is_file():
        print(f"ERROR: {hist} not found", file=sys.stderr)
        return 2
    try:
        data = json.loads(hist.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: {hist} is not valid JSON: {exc}", file=sys.stderr)
        return 2
    try:
        pdfs = load_pdfs(committee)
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"ERROR: could not read the committee PDFs: {exc}", file=sys.stderr)
        return 2
    if not pdfs:
        print(f"ERROR: no PDFs in {committee}", file=sys.stderr)
        return 2

    rep = Report()
    findings = None
    if not isinstance(data, dict):
        rep.add("SCHEMA", "top level", "must be an object")
    else:
        check_keys(rep, "top level", data, TOP_KEYS)
        ctx = Ctx(rep, pdfs, check_sources(rep, data, pdfs))
        check_audits(ctx, data)
        check_simple(ctx, data, "opinion_basis", OPB_KEYS)
        check_simple(ctx, data, "agreed_actions", ACTION_KEYS, bound=("theme", "due_date", "status"))
        check_simple(ctx, data, "risk_themes", THEME_KEYS, "kind", THEME_KINDS, bound=("theme",))
        check_register_access(ctx, data)
        n_errors = len(rep.errors)
        m = check_scoring(ctx, data)
        if m is not None and len(rep.errors) == n_errors:
            findings = consistency_findings(m)
        elif m is not None:
            rep.add("CONSISTENCY_SKIPPED", "risk_scoring_method",
                    "fix the errors above first; consistency checks need a well-formed method")
        check_discrepancies(ctx, data, findings)
        check_required_gaps(rep, data, check_gaps(ctx, data))

    counts = {k: len(data.get(k) or []) for k in ("audits", "opinion_basis", "agreed_actions",
                                                   "risk_themes", "discrepancies", "gaps")} \
        if isinstance(data, dict) else {}
    print(f"verify_history: {hist} against {committee} ({len(pdfs)} PDFs)")
    print("  " + ", ".join(f"{k}: {v}" for k, v in counts.items()))
    if findings is not None:
        print(f"  consistency findings: {len(findings)}" +
              "".join(f"\n    {ref}: {msg}" for ref, msg in sorted(findings.items())))
    if not rep.errors:
        print("PASS: all checks passed")
        return 0
    for code, where, msg in rep.errors:
        print(f"  [{code}] {where}: {msg}")
    print(f"FAIL: {len(rep.errors)} error(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
