#!/usr/bin/env python3
"""Build the risk register from the risk-assessor's judgments.

    .venv/bin/python .claude/skills/risk-assessment/build_register.py

Reads outputs/risk-ratings.json (the agent's judgments), outputs/analytics.json,
outputs/history.json and outputs/rules.json. Resolves every citation, fills
every {{$.path}} placeholder from analytics.json, applies the likelihood
rubric, and computes score, matrix label and band from the council's matrix
in history.json. Writes:

    outputs/risk-register.md
    outputs/auditor-comments.md          decisions already in it are kept
    outputs/register-snapshots/rN.json   the ratings the auditor decides on

Exclusion: a risk whose likelihood or impact justification has no resolvable
primary citation, or that carries any citation or placeholder that does not
resolve, is left out of the rating and listed under "Excluded".

Errors (schema, rubric, uplift, scoring method, revision rules): nothing is
written and the exit code is 1. Typed figures in prose are warnings.

Options: --root DIR (repo root), --ratings FILE, --out-dir DIR,
--analytics / --history / --rules FILE (default <root>/outputs/<name>.json).
"""

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DEFAULT = Path(__file__).resolve().parents[3]

# Likelihood rubric. The signal is the general_procurement count of the one
# analytics test (or threshold tier) the risk rests on; the builder computes
# the row from it, so the same evidence always gets the same base score.
S1_MAX = 4
S2_MAX = 19
RUBRIC = {
    "NT": ("No analytics test measures the risk, or its test or tier did not run", 2),
    "S0": ("Signal count is 0", 1),
    "S1": (f"Signal count 1 to {S1_MAX}; or a threshold_clustering tier whose "
           "below-band count does not exceed its comparison band", 2),
    "S2": (f"Signal count {S1_MAX + 1} to {S2_MAX}", 3),
    "S3": (f"Signal count {S2_MAX + 1} or more", 4),
}
UPLIFT = 1
MAX_SCORE = 5
PRIMARY_TAG = "general_procurement"
ADVERSE_OPINIONS = ("limited", "weak", "no assurance")
NOT_SIGNAL_TESTS = {"high_value_suppliers": "a population to request contract evidence for, not an indicator"}
FALLBACK_LABELS = {1: "Very low", 2: "Low", 3: "Medium", 4: "High", 5: "Very high"}

RATED_DECISIONS = {"approve": "Approve", "amend": "Amend", "reject": "Reject"}
NOTED_DECISIONS = {"add to scope": "Add to scope", "leave out": "Leave out"}
ACTING = {"Amend", "Reject", "Add to scope"}  # decisions that require a change

RISK_FIELDS = [
    "title", "description",
    "likelihood.score", "likelihood.rubric_row", "likelihood.signal",
    "likelihood.justification", "likelihood.repeat_uplift",
    "impact.score", "impact.category", "impact.justification",
    "evidence", "proposed_focus", "status",
]
PROSE_FIELDS = [
    "description", "likelihood.justification", "likelihood.repeat_uplift.justification",
    "impact.justification", "evidence", "proposed_focus",
]
# Sections of the Risk Management Strategy that make up the scoring method.
SCORING_SECTION_RE = re.compile(r"Table [1-4]\b|Figure [14]\b|^4\.[1-4]\b|^5\.(?:8|9|10|11|13)\b")

RISK_ID_RE = re.compile(r"^R-\d{2,}$")
TAG_START_RE = re.compile(r"\[(rule|metric|history):")
PLACEHOLDER_RE = re.compile(r"\{\{(.*?)\}\}")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}(?:\s?[/–-]\s?\d{2,4})?\b")
ID_RE = re.compile(r"\b[A-Z][A-Za-z]{0,5}-\d+\b")
DIGITS_RE = re.compile(r"[£$]?\d[\d,.]*(?:%|(?:k|m|bn)\b)?", re.IGNORECASE)


class PathError(Exception):
    pass


# ---------------------------------------------------------------- paths

PATH_TOKEN_RE = re.compile(
    r"\.([A-Za-z_][A-Za-z0-9_]*)"            # .key
    r"|\[(\d+)\]"                             # [0]
    r"|\['([^']*)'\]"                         # ['key with spaces']
    r"|\[([A-Za-z_][A-Za-z0-9_]*)=([^\]]+)\]"  # [field=value]
)


def parse_literal(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        raise PathError(f"filter value {s!r} is neither a number nor a 'quoted string'")


def parse_path(path):
    path = path.strip()
    if not path.startswith("$"):
        raise PathError("path must start with $")
    toks, pos = [], 1
    while pos < len(path):
        m = PATH_TOKEN_RE.match(path, pos)
        if not m:
            raise PathError(f"bad path syntax at {path[pos:]!r}")
        if m.group(1) is not None:
            toks.append(("key", m.group(1)))
        elif m.group(2) is not None:
            toks.append(("index", int(m.group(2))))
        elif m.group(3) is not None:
            toks.append(("key", m.group(3)))
        else:
            toks.append(("filter", m.group(4), parse_literal(m.group(5))))
        pos = m.end()
    if not toks:
        raise PathError("empty path")
    return toks


def canonical(toks):
    out = "$"
    for t in toks:
        if t[0] == "key":
            out += f".{t[1]}" if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t[1]) else f"['{t[1]}']"
        elif t[0] == "index":
            out += f"[{t[1]}]"
        else:
            v = f"'{t[2]}'" if isinstance(t[2], str) else t[2]
            out += f"[{t[1]}={v}]"
    return out


def resolve(data, toks):
    """Follow toks into data. Returns (value, trail of every value visited)."""
    cur, trail = data, [data]
    for t in toks:
        if t[0] == "key":
            if not isinstance(cur, dict) or t[1] not in cur:
                raise PathError(f"no key {t[1]!r}")
            cur = cur[t[1]]
        elif t[0] == "index":
            if not isinstance(cur, list) or t[1] >= len(cur):
                raise PathError(f"no index [{t[1]}]")
            cur = cur[t[1]]
        else:
            if not isinstance(cur, list):
                raise PathError(f"filter [{t[1]}=...] on a non-list")
            hits = [x for x in cur if isinstance(x, dict) and t[1] in x
                    and not isinstance(x[t[1]], bool) and x[t[1]] == t[2]]
            if len(hits) != 1:
                raise PathError(f"filter [{t[1]}={t[2]}] matched {len(hits)} items, needs exactly 1")
            cur = hits[0]
        trail.append(cur)
    return cur, trail


def get_field(obj, dotted):
    for part in dotted.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def fmt_value(v):
    if isinstance(v, bool) or v is None:
        return json.dumps(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def md_cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- context

class Ctx:
    def __init__(self, analytics, history, rules):
        self.analytics, self.history, self.rules = analytics, history, rules
        self.errors, self.warnings = [], []
        self.rules_by_id = {r["rule_id"]: r for r in rules.get("rules", [])}
        self.history_by_id = {}
        for key, val in history.items():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and "id" in item:
                        self.history_by_id[item["id"]] = (key, item)
        self.audits = {i["id"]: i for i in history.get("audits", [])}
        floor = (analytics.get("publication_floor") or {}).get("value")
        tiers = [b["threshold"] for b in analytics.get("tests", {}).get("split_purchases", {}).get("by_threshold", [])]
        # A split tier at or below twice the publication floor flags by
        # construction: any two published payments under it already reach it.
        self.publication_floor = floor
        self.noise_tiers = sorted(t for t in tiers if isinstance(floor, (int, float)) and t <= 2 * floor)


def is_adverse(opinion):
    return isinstance(opinion, str) and opinion.strip().lower().startswith(ADVERSE_OPINIONS)


def history_label(ctx, hid):
    key, item = ctx.history_by_id[hid]
    if key == "audits":
        return f"{item.get('title')} ({item.get('opinion') or item.get('kind')})"
    text = item.get("theme") or item.get("description") or item.get("detail") or item.get("summary") or ""
    return text if len(text) <= 90 else text[:87] + "..."


def first_cite(item):
    cites = item.get("cites") or []
    if cites:
        return f"{cites[0].get('file')} p{cites[0].get('pdf_page')}"
    return "no cite"


def classify_metric(ctx, toks, trail):
    """primary | context | noise | reference, with the reason."""
    if not toks or toks[0] != ("key", "tests"):
        return "reference", "not a test result"
    test = toks[1][1] if len(toks) > 1 and toks[1][0] == "key" else None
    if test == "split_purchases" and ctx.noise_tiers:
        tier = None
        for obj in trail[3:]:
            if isinstance(obj, dict) and isinstance(obj.get("threshold"), (int, float)):
                tier = obj["threshold"]
        if tier is None:
            return "context", "split_purchases aggregate that includes the noise tier"
        if tier in ctx.noise_tiers:
            return "noise", f"split_purchases tier {fmt_value(tier)} flags by construction"
    tag = None
    for a, b in zip(toks, toks[1:]):
        if a == ("key", "by_tag") and b[0] == "key":
            tag = b[1]
    if tag is None:
        for obj in trail:
            if isinstance(obj, dict) and isinstance(obj.get("spend_tag"), str):
                tag = obj["spend_tag"]
    if tag == PRIMARY_TAG:
        return "primary", PRIMARY_TAG
    if tag:
        return "context", f"{tag} tag"
    return "context", "all tags combined"


# ---------------------------------------------------------------- text

def scan_tags(text):
    tags, i = [], 0
    while True:
        m = TAG_START_RE.search(text, i)
        if not m:
            return tags
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += {"[": 1, "]": -1}.get(text[j], 0)
            j += 1
        if depth:
            tags.append({"kind": m.group(1), "ref": text[m.end():].strip(),
                         "span": (m.start(), len(text)), "error": "citation is not closed"})
            return tags
        tags.append({"kind": m.group(1), "ref": text[m.end():j - 1].strip(), "span": (m.start(), j)})
        i = j


def resolve_tag(ctx, tag):
    """Adds ok, cls, why, source (and value for metrics) to tag."""
    if tag.get("error"):
        tag.update(ok=False)
        return tag
    kind, ref = tag["kind"], tag["ref"]
    if kind == "rule":
        r = ctx.rules_by_id.get(ref)
        if not r:
            tag.update(ok=False, error=f"rule {ref} is not in rules.json")
        else:
            tag.update(ok=True, cls="primary", why="rule",
                       source=f"rule {ref}: clause {r.get('clause')}, page {r.get('page')}, {r.get('type')}")
    elif kind == "history":
        if ref not in ctx.history_by_id:
            tag.update(ok=False, error=f"history item {ref} is not in history.json")
        else:
            _, item = ctx.history_by_id[ref]
            tag.update(ok=True, cls="primary", why="history",
                       source=f"history {ref}: {history_label(ctx, ref)}, {first_cite(item)}")
    else:
        try:
            toks = parse_path(ref)
            value, trail = resolve(ctx.analytics, toks)
        except PathError as e:
            tag.update(ok=False, error=f"metric {ref} does not resolve in analytics.json: {e}")
            return tag
        if value is None:
            tag.update(ok=False, error=f"metric {ref} is null in analytics.json")
            return tag
        cls, why = classify_metric(ctx, toks, trail)
        shown = fmt_value(value) if not isinstance(value, (dict, list)) else f"{type(value).__name__} of {len(value)}"
        tag.update(ok=True, cls=cls, why=why, toks=toks, canonical=canonical(toks), value=value,
                   source=f"metric {canonical(toks)} = {shown} ({cls}: {why})")
    return tag


def typed_figures(text):
    spans = [t["span"] for t in scan_tags(text)] + [m.span() for m in PLACEHOLDER_RE.finditer(text)]
    chars = list(text)
    for a, b in spans:
        chars[a:b] = " " * (b - a)
    t = "".join(chars)
    t = YEAR_RE.sub(" ", t)
    t = ID_RE.sub(" ", t)
    return DIGITS_RE.findall(t)


def process_text(ctx, text):
    """Returns (rendered markdown, resolved tags, problems)."""
    problems = []
    tags = [resolve_tag(ctx, t) for t in scan_tags(text)]
    for t in tags:
        if not t["ok"]:
            problems.append(t["error"])
    pieces = []
    for t in tags:
        pieces.append((t["span"][0], t["span"][1], f"`{t['kind']}:{t.get('canonical', t['ref'])}`"))
    for m in PLACEHOLDER_RE.finditer(text):
        a, b = m.span()
        if any(x[0] < b and a < x[1] for x in pieces):
            problems.append(f"placeholder {m.group(0)} overlaps a citation")
            continue
        try:
            value, _ = resolve(ctx.analytics, parse_path(m.group(1)))
        except PathError as e:
            problems.append(f"placeholder {m.group(0)} does not resolve in analytics.json: {e}")
            continue
        if value is None or isinstance(value, (dict, list, bool)):
            problems.append(f"placeholder {m.group(0)} is not a number or text")
            continue
        pieces.append((a, b, fmt_value(value)))
    pieces.sort()
    out, pos = "", 0
    for a, b, rep in pieces:
        out += text[pos:a] + rep
        pos = b
    out += text[pos:]
    stray = PLACEHOLDER_RE.sub("", text)
    if "{{" in stray or "}}" in stray:
        problems.append("unbalanced {{ or }} in text")
    return out, tags, problems


# ---------------------------------------------------------------- scoring method

def parse_band_range(printed):
    s = (printed or "").strip()
    m = re.fullmatch(r"(?i)up\s+to\s*(\d+)", s)
    if m:
        return 1, int(m.group(1))
    m = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.fullmatch(r"(?i)(\d+)\s*(?:\+|or\s+(?:above|more))", s)
    if m:
        return int(m.group(1)), MAX_SCORE * MAX_SCORE
    return None


def pct_range(cell):
    nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", cell or "")]
    if not nums:
        return None
    low = cell.strip().lower()
    if low.startswith("less than") and len(nums) == 1:
        return 0.0, nums[0]
    if low.startswith(">") and len(nums) == 1:
        return nums[0], math.inf
    if len(nums) >= 2:
        return nums[0], nums[1]
    return None


def build_method(ctx):
    h = ctx.history
    m = h.get("risk_scoring_method") or {}
    errs = ctx.errors
    if m.get("status") != "found":
        return {"fallback": True, "reason": m.get("not_found_reason") or "history.json reports no usable scoring method",
                "L": FALLBACK_LABELS, "I": FALLBACK_LABELS, "categories": [], "conflicts": [], "other_dis": []}
    L = {x["score"]: x["label"] for x in m.get("likelihood_scale", [])}
    I = {x["score"]: x["label"] for x in m.get("impact_scale", [])}
    if set(L) != set(range(1, 6)) or set(I) != set(range(1, 6)):
        errs.append("scoring method: likelihood and impact scales must each have scores 1 to 5")
        return None
    rows = {r.get("impact"): r for r in m.get("matrix", {}).get("rows", [])}
    for i in range(1, 6):
        r = rows.get(i)
        if not r or len(r.get("scores", [])) != 5 or len(r.get("labels", [])) != 5:
            errs.append(f"scoring method: matrix row for impact {i} is missing or not 5 cells")
            return None
        for l in range(1, 6):
            if r["scores"][l - 1] != l * i:
                errs.append(f"scoring method: matrix cell L{l} x I{i} prints {r['scores'][l - 1]}, not likelihood x impact")
                return None
    bands = []
    for b in m.get("bands", []):
        rng = parse_band_range(b.get("score_printed"))
        if not rng:
            errs.append(f"scoring method: band {b.get('level')!r} score {b.get('score_printed')!r} cannot be read as a range")
            return None
        bands.append(dict(b, lo=rng[0], hi=rng[1]))
    for i in range(1, 6):
        for l in range(1, 6):
            s = l * i
            hits = [b for b in bands if b["lo"] <= s <= b["hi"]]
            if len(hits) != 1:
                errs.append(f"scoring method: score {s} falls in {len(hits)} bands, needs exactly 1")
                return None
    cats = list((m["impact_scale"][0].get("criteria") or {}).keys())
    method = {"fallback": False, "L": L, "I": I, "rows": rows, "bands": bands, "categories": cats,
              "impact_scale": {x["score"]: x for x in m["impact_scale"]}, "raw": m}
    method["conflicts"], method["other_dis"] = find_conflicts(ctx, method)
    method["sources"] = method_sources(m)
    return method


def method_sources(m):
    out = []
    for name, item in [("likelihood scale", (m.get("likelihood_scale") or [{}])[0]),
                       ("impact scale", (m.get("impact_scale") or [{}])[0]),
                       ("matrix", (m.get("matrix", {}).get("rows") or [{}])[0]),
                       ("bands", (m.get("bands") or [{}])[0])]:
        c = (item.get("cites") or [{}])[0]
        if c:
            out.append(f"{name}: {c.get('section')} ({c.get('file')} p{c.get('pdf_page')})")
    return out


def dis_text(d):
    parts = [d.get("description") or ""]
    for c in d.get("cites", []):
        q = c.get("quote")
        parts.extend(q if isinstance(q, list) else [q or ""])
        parts.append(c.get("layout_quote") or "")
    return "\n".join(parts)


def find_conflicts(ctx, method):
    """Detect conflicting thresholds in the scoring method. Each conflict says
    what is used and what is marked; nothing is resolved silently."""
    dis = ctx.history.get("discrepancies", [])
    raw = method["raw"]
    conflicts = []

    # 1. Corporate Risk Register threshold: Figure 4 vs Table 4.
    fig = None
    for e in raw.get("escalation", []):
        if "corporate" in (e.get("register") or "").lower():
            mm = re.search(r"[Ss]core (\d+) or above", e.get("criterion") or "")
            if mm:
                fig = int(mm.group(1))
    tab = [b for b in method["bands"] if "corporate risk register" in (b.get("escalation") or "").lower()]
    if fig is not None and tab:
        tlo = min(b["lo"] for b in tab)
        if fig != tlo:
            band = min(tab, key=lambda b: b["lo"])
            conflicts.append({
                "kind": "crr_threshold",
                "used": f"Table 4: a risk goes to the Corporate Risk Register in band {band['level']} "
                        f"(score {band['score_printed']}), the table the Band column comes from",
                "marked": f"Figure 4: Corporate Risk Register \"Score {fig} or above\". Risks scoring "
                          f"{min(fig, tlo)} to {max(fig, tlo) - 1} are marked ‡ in the register",
                "affects": (min(fig, tlo), max(fig, tlo) - 1),
                "history": [d["id"] for d in dis if f"Score {fig} or above" in dis_text(d)],
            })

    # 2. Matrix label names that differ from the band names for the same scores.
    pairs = {}
    for i, r in method["rows"].items():
        for l in range(1, 6):
            s, label = l * i, r["labels"][l - 1]
            band = next(b for b in method["bands"] if b["lo"] <= s <= b["hi"])
            if label != band["level"]:
                pairs.setdefault((label, band["level"]), set()).add(s)
    for (label, level), scores in sorted(pairs.items()):
        conflicts.append({
            "kind": "band_name",
            "used": f"Band column: Table 4 name \"{level}\"",
            "marked": f"Matrix label column keeps Figure 1's \"{label}\" for scores "
                      f"{', '.join(str(s) for s in sorted(scores))}; Table 4 has no band named \"{label}\"",
            "history": [d["id"] for d in dis if (d.get("check_ref") or "") == f"matrix.label_name:{label}"],
        })

    # 3. Impact level numbers printed differently in the prose.
    labels = method["I"]
    by_label = {v: k for k, v in labels.items()}
    lab_re = re.compile(r"\b(" + "|".join(re.escape(v) for v in labels.values()) + r")\b(?:\s+impact)?\s*\((\d)\)")
    seen = set()
    for d in dis:
        for c in d.get("cites", []):
            q = c.get("quote")
            for text in (q if isinstance(q, list) else [q or ""]):
                for mm in lab_re.finditer(text):
                    key = (mm.group(1), mm.group(2), c.get("section"))
                    if int(mm.group(2)) != by_label[mm.group(1)] and key not in seen:
                        seen.add(key)
                        conflicts.append({
                            "kind": "impact_numbering",
                            "used": f"{mm.group(1)} = {by_label[mm.group(1)]}, as numbered in Table 1 and Figure 1",
                            "marked": f"\"{mm.group(1)} ({mm.group(2)})\" printed in {c.get('section')} (p{c.get('pdf_page')})",
                            "history": [d["id"]],
                        })

    # 4. Overlapping percentage ranges in the impact Financial column.
    fin_key = next((k for k in method["categories"] if "financial" in k.lower()), None)
    if fin_key:
        sc = method["impact_scale"]
        for s in range(1, 5):
            a, b = pct_range(sc[s]["criteria"].get(fin_key)), pct_range(sc[s + 1]["criteria"].get(fin_key))
            if a and b and a[1] > b[0]:
                conflicts.append({
                    "kind": "impact_financial_pct",
                    "used": f"the £ figures printed in the same Table 1 cells (listed under Impact below); where two "
                            f"£ ranges share an end point the higher level takes it, unless that level is printed with '>'",
                    "marked": f"the percentage ranges for {labels[s]} ({sc[s]['criteria'][fin_key]}) and "
                              f"{labels[s + 1]} ({sc[s + 1]['criteria'][fin_key]}) overlap",
                    "history": [d["id"] for d in dis if (d.get("check_ref") or "").startswith("impact.financial_pct")],
                })

    linked = {h for c in conflicts for h in c["history"]}
    method_files = set(re.findall(r'"file": "([^"]+)"', json.dumps(raw)))  # every file the method cites
    other = []
    for d in dis:
        if d["id"] in linked:
            continue
        if any(c.get("file") in method_files and SCORING_SECTION_RE.search(c.get("section") or "")
               for c in d.get("cites", [])):
            other.append(d)
    return conflicts, other


def rate(method, l, i):
    """score, matrix label, band dict (None in fallback)."""
    if method["fallback"]:
        return l * i, None, None
    s = method["rows"][i]["scores"][l - 1]
    label = method["rows"][i]["labels"][l - 1]
    band = next(b for b in method["bands"] if b["lo"] <= s <= b["hi"])
    return s, label, band


# ---------------------------------------------------------------- ratings schema

def check_schema(ratings):
    errs = []
    if not isinstance(ratings, dict):
        return ["risk-ratings.json must be an object"]
    extra = set(ratings) - {"risks", "noted_not_rated", "revision"}
    if extra:
        errs.append(f"risk-ratings.json: unknown top-level keys {sorted(extra)}")
    risks = ratings.get("risks")
    if not isinstance(risks, list):
        errs.append("risk-ratings.json: risks must be a list")
        risks = []
    seen = set()
    for n, r in enumerate(risks):
        w = f"risks[{n}]"
        if not isinstance(r, dict):
            errs.append(f"{w}: must be an object")
            continue
        need = {"risk_id", "title", "description", "likelihood", "impact", "evidence", "proposed_focus"}
        miss, extra = need - set(r), set(r) - need - {"status"}
        if miss:
            errs.append(f"{w}: missing {sorted(miss)}")
        if extra:
            errs.append(f"{w}: unknown keys {sorted(extra)}")
        rid = r.get("risk_id")
        if not isinstance(rid, str) or not RISK_ID_RE.match(rid):
            errs.append(f"{w}.risk_id: must look like R-01")
        elif rid in seen:
            errs.append(f"{w}.risk_id: {rid} is used twice")
        seen.add(rid)
        if r.get("status") not in (None, "rejected"):
            errs.append(f"{w}.status: only \"rejected\" is allowed")
        for f in ("title", "description", "evidence", "proposed_focus"):
            if f in r and (not isinstance(r[f], str) or not r[f].strip()):
                errs.append(f"{w}.{f}: must be non-empty text")
        lk, im = r.get("likelihood"), r.get("impact")
        if isinstance(lk, dict):
            if set(lk) != {"score", "rubric_row", "signal", "justification", "repeat_uplift"}:
                errs.append(f"{w}.likelihood: keys must be score, rubric_row, signal, justification, repeat_uplift")
            if not (isinstance(lk.get("score"), int) and not isinstance(lk.get("score"), bool) and 1 <= lk["score"] <= MAX_SCORE):
                errs.append(f"{w}.likelihood.score: must be an integer 1 to {MAX_SCORE}")
            if lk.get("rubric_row") not in RUBRIC:
                errs.append(f"{w}.likelihood.rubric_row: must be one of {list(RUBRIC)}")
            if lk.get("signal") is not None and not isinstance(lk.get("signal"), str):
                errs.append(f"{w}.likelihood.signal: must be a $.path or null")
            if not isinstance(lk.get("justification"), str) or not lk.get("justification", "").strip():
                errs.append(f"{w}.likelihood.justification: must be non-empty text")
            up = lk.get("repeat_uplift")
            if up is not None and (not isinstance(up, dict) or set(up) != {"history", "justification"}
                                   or not isinstance(up.get("justification"), str) or not up["justification"].strip()):
                errs.append(f"{w}.likelihood.repeat_uplift: must be null or {{history, justification}}")
        elif "likelihood" in r:
            errs.append(f"{w}.likelihood: must be an object")
        if isinstance(im, dict):
            if set(im) != {"score", "category", "justification"}:
                errs.append(f"{w}.impact: keys must be score, category, justification")
            if not (isinstance(im.get("score"), int) and not isinstance(im.get("score"), bool) and 1 <= im["score"] <= MAX_SCORE):
                errs.append(f"{w}.impact.score: must be an integer 1 to {MAX_SCORE}")
            if not isinstance(im.get("justification"), str) or not im.get("justification", "").strip():
                errs.append(f"{w}.impact.justification: must be non-empty text")
        elif "impact" in r:
            errs.append(f"{w}.impact: must be an object")
    noted = ratings.get("noted_not_rated", [])
    if not isinstance(noted, list):
        errs.append("risk-ratings.json: noted_not_rated must be a list")
    else:
        hs = set()
        for n, x in enumerate(noted):
            if not isinstance(x, dict) or set(x) != {"history", "reason"} or not str(x.get("reason", "")).strip():
                errs.append(f"noted_not_rated[{n}]: must be {{history, reason}} with a reason")
            elif x["history"] in hs:
                errs.append(f"noted_not_rated[{n}]: {x['history']} listed twice")
            else:
                hs.add(x["history"])
    rev = ratings.get("revision")
    if rev is not None:
        if not isinstance(rev, dict) or set(rev) != {"number", "changes"} \
                or not isinstance(rev.get("number"), int) or rev["number"] < 1 or not isinstance(rev.get("changes"), list):
            errs.append("revision: must be null or {number (1 or more), changes: [...]}")
        else:
            for n, c in enumerate(rev["changes"]):
                if not isinstance(c, dict) or set(c) != {"target", "decision_ref", "fields", "summary"} \
                        or not isinstance(c.get("fields"), list) or not c["fields"] \
                        or not isinstance(c.get("summary"), str) or not c["summary"].strip():
                    errs.append(f"revision.changes[{n}]: must be {{target, decision_ref, fields (non-empty list), summary}}")
                    continue
                bad = set(c["fields"]) - set(RISK_FIELDS) - {"added", "removed", "reason"}
                if bad:
                    errs.append(f"revision.changes[{n}].fields: unknown {sorted(bad)}")
    return errs


# ---------------------------------------------------------------- auditor comments

def parse_comments(path):
    """{id: {table, decision, comment, applied}} or raises ValueError."""
    out = {}
    if not path.exists():
        return out
    table, header = None, None
    for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if s.startswith("## "):
            title = s[3:].strip().lower()
            table = "rated" if title.startswith("rated") else "noted" if title.startswith("noted") else None
            header = None
            continue
        if table is None or not s.startswith("|"):
            continue
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s.strip("|"))]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) != len(header):
            raise ValueError(f"auditor-comments.md line {ln}: {len(cells)} cells, header has {len(header)} "
                             "(a comment may not contain |)")
        row = dict(zip(header, cells))
        key = row.get("risk") if table == "rated" else row.get("item")
        raw = row.get("decision", "")
        vocab = RATED_DECISIONS if table == "rated" else NOTED_DECISIONS
        if raw and raw.lower() not in vocab:
            raise ValueError(f"auditor-comments.md line {ln}: decision {raw!r} for {key} is not one of "
                             f"{', '.join(vocab.values())}")
        out[key] = {"table": table, "decision": vocab.get(raw.lower(), "") if raw else "",
                    "comment": row.get("comment", ""), "applied": row.get("applied", "")}
    return out


def write_comments(path, n, ratings_sha, built, rated_rows, noted_rows):
    L = [
        "# Auditor comments: risk register decisions",
        "",
        f"Register revision: r{n}  ",
        f"Built: {built} from outputs/risk-ratings.json (sha256 {ratings_sha[:12]})",
        "",
        "Fill in a Decision for every row, and a Comment where needed. Edit only the Decision and",
        "Comment cells; build_register.py rewrites the other columns and keeps what you wrote.",
        "Do not use the | character in a comment.",
        "",
        "- Rated risks: **Approve**, **Amend** (say in Comment exactly what to change) or **Reject**.",
        "- Noted, not rated: **Add to scope** (it will be rated in the next revision) or **Leave out**.",
        "- Applied names the revision in which an Amend, Reject or Add to scope was carried out. To ask",
        "  for a further change to the same row, set the Decision again and clear Applied.",
        "",
        "## Rated risks",
        "",
        "| Risk | Title | Likelihood | Impact | Score | Band | Decision | Comment | Applied |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rated_rows:
        L.append("| " + " | ".join(md_cell(x) for x in r) + " |")
    L += ["", "## Noted, not rated", "", "| Item | Area | Opinion | Decision | Comment | Applied |",
          "| --- | --- | --- | --- | --- | --- |"]
    for r in noted_rows:
        L.append("| " + " | ".join(md_cell(x) for x in r) + " |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- revision

def snapshots(out_dir):
    d = out_dir / "register-snapshots"
    found = {}
    if d.exists():
        for p in d.glob("r*.json"):
            m = re.fullmatch(r"r(\d+)\.json", p.name)
            if m:
                found[int(m.group(1))] = p
    return d, found


def body(ratings):
    return {"risks": ratings.get("risks", []), "noted_not_rated": ratings.get("noted_not_rated", [])}


def check_revision(ctx, rev, prev, prev_rows, cur, decisions, n):
    """prev_rows: the rows the auditor was asked to decide on. Returns (actual
    diff {target: fields}, amend fields {target: fields}, pending decisions)."""
    errs = ctx.errors
    pending = {k: d for k, d in decisions.items()
               if d["decision"] in ACTING and d["applied"] in ("", f"r{n}")}
    prev_r = {r["risk_id"]: r for r in prev["risks"]}
    cur_r = {r["risk_id"]: r for r in cur["risks"]}
    prev_n = {x["history"]: x for x in prev["noted_not_rated"]}
    cur_n = {x["history"]: x for x in cur["noted_not_rated"]}

    for k in prev_rows:
        if not decisions.get(k, {}).get("decision"):
            errs.append(f"auditor-comments.md: {k} has no decision; a revision is built only after the auditor "
                        "has decided every row")

    actual = {}
    for rid, r in cur_r.items():
        if rid not in prev_r:
            actual[rid] = {"added"}
        else:
            ch = {f for f in RISK_FIELDS if get_field(prev_r[rid], f) != get_field(r, f)}
            if ch:
                actual[rid] = ch
    for rid in prev_r:
        if rid not in cur_r:
            errs.append(f"{rid} was deleted from risk-ratings.json; risks are never deleted (a Reject sets status "
                        "\"rejected\")")
    for hid, x in cur_n.items():
        if hid not in prev_n:
            actual[hid] = {"added"}
        elif x["reason"] != prev_n[hid]["reason"]:
            actual[hid] = {"reason"}
    for hid in prev_n:
        if hid not in cur_n:
            actual[hid] = {"removed"}

    declared, amend, used = {}, {}, {}
    for i, c in enumerate(rev["changes"]):
        ref, tgt, fields = c["decision_ref"], c["target"], set(c["fields"])
        if ref not in pending:
            d = decisions.get(ref, {})
            state = (f"{d['decision']}, applied in {d['applied']}" if d.get("applied")
                     else d.get("decision") or "no decision")
            errs.append(f"revision.changes[{i}]: {tgt} changed under {ref}, but {ref} has no pending Amend, Reject "
                        f"or Add to scope decision ({state}): a change the auditor did not ask for")
            continue
        dec = pending[ref]["decision"]
        if dec == "Reject" and (tgt != ref or fields != {"status"}):
            errs.append(f"revision.changes[{i}]: a Reject of {ref} changes only {ref}.status")
        if dec == "Add to scope" and not ((tgt == ref and fields == {"removed"}) or (tgt != ref and fields == {"added"})):
            errs.append(f"revision.changes[{i}]: Add to scope of {ref} removes {ref} from noted_not_rated and adds "
                        "a new risk; nothing else")
        if dec == "Amend" and "status" in fields:
            errs.append(f"revision.changes[{i}]: an Amend cannot change status; the auditor rejects with Reject")
        declared.setdefault(tgt, set()).update(fields)
        used.setdefault(ref, set()).add(tgt)
        if dec == "Amend":
            amend.setdefault(tgt, set()).update(fields)

    for tgt in sorted(set(actual) | set(declared)):
        a, d = actual.get(tgt, set()), declared.get(tgt, set())
        for f in sorted(a - d):
            errs.append(f"{tgt}: {f} changed but no revision change declares it: a change the auditor did not ask for")
        for f in sorted(d - a):
            errs.append(f"{tgt}: {f} is declared in the revision block but did not change: decision left unapplied")
    for ref, d in sorted(pending.items()):
        if ref not in used:
            errs.append(f"{ref}: {d['decision']} decision left unapplied (no revision change references it)")
        elif d["decision"] == "Reject" and get_field(cur_r.get(ref, {}), "status") != "rejected":
            errs.append(f"{ref}: Reject decision left unapplied (status is not \"rejected\")")
        elif d["decision"] == "Add to scope":
            if ref in cur_n:
                errs.append(f"{ref}: Add to scope left unapplied (still in noted_not_rated)")
            if not any("added" in declared.get(t, set()) for t in used[ref] if t != ref):
                errs.append(f"{ref}: Add to scope left unapplied (no risk added for it)")
    return actual, amend, pending


# ---------------------------------------------------------------- evaluation

def signal_row(ctx, risk, lk):
    """Computes the rubric row from the signal. Returns (row, value, note) or None after an error."""
    rid, sig = risk["risk_id"], lk["signal"]
    if sig is None:
        return "NT", None, "no signal"
    try:
        toks = parse_path(sig)
        value, trail = resolve(ctx.analytics, toks)
    except PathError as e:
        ctx.errors.append(f"{rid}: likelihood.signal {sig} does not resolve: {e}")
        return None
    c = canonical(toks)
    if toks[0] != ("key", "tests") or len(toks) < 2:
        ctx.errors.append(f"{rid}: likelihood.signal must point into $.tests")
        return None
    test = toks[1][1]
    if test in NOT_SIGNAL_TESTS:
        ctx.errors.append(f"{rid}: likelihood.signal cannot use {test}: {NOT_SIGNAL_TESTS[test]}")
        return None
    if trail[2].get("status") != "run":
        ctx.errors.append(f"{rid}: likelihood.signal points at {test}, which did not run; use rubric row NT")
        return None
    if [t[1] for t in toks[-3:]] != ["by_tag", PRIMARY_TAG, "count"]:
        ctx.errors.append(f"{rid}: likelihood.signal must end in .by_tag.{PRIMARY_TAG}.count (decision: ratings rest "
                          "on general procurement figures)")
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        ctx.errors.append(f"{rid}: likelihood.signal {c} is not a count")
        return None
    cls, why = classify_metric(ctx, toks, trail)
    if cls != "primary":
        ctx.errors.append(f"{rid}: likelihood.signal {c} cannot be the signal ({why})")
        return None
    if test in ("split_purchases", "threshold_clustering") and (
            toks[2] != ("key", "by_threshold") or toks[3][0] not in ("index", "filter")):
        ctx.errors.append(f"{rid}: likelihood.signal for {test} must name one tier: $.tests.{test}.by_threshold[threshold=T]...")
        return None
    note = f"signal {c} = {fmt_value(value)}"
    if test == "threshold_clustering":
        if toks[4] != ("key", "below"):
            ctx.errors.append(f"{rid}: likelihood.signal for threshold_clustering must be the tier's below band")
            return None
        comp = (trail[4].get("comparison", {}).get("by_tag", {}).get(PRIMARY_TAG) or {}).get("count")
        if isinstance(comp, int) and value > 0 and value <= comp:
            return "S1", value, note + f"; comparison band = {fmt_value(comp)}, no excess (capped at S1)"
        note += f"; comparison band = {fmt_value(comp)}"
    row = "S0" if value == 0 else "S1" if value <= S1_MAX else "S2" if value <= S2_MAX else "S3"
    return row, value, note


def evaluate(ctx, method, risk, lk_override_ok, im_override_prev):
    """Returns a result dict. Errors go to ctx.errors; exclusion reasons to result['excluded']."""
    rid = risk["risk_id"]
    res = {"risk": risk, "id": rid, "excluded": [], "rendered": {}, "tags": []}
    for f in PROSE_FIELDS:
        text = get_field(risk, f)
        if text is None:
            continue
        rendered, tags, problems = process_text(ctx, text)
        res["rendered"][f] = rendered
        res["tags"] += tags
        res["excluded"] += [f"{f}: {p}" for p in problems]
        figs = typed_figures(text)
        if figs:
            ctx.warnings.append(f"{rid}.{f}: figure typed in prose ({', '.join(figs[:5])}); use a {{{{$.path}}}} placeholder")
    figs = typed_figures(risk["title"])
    if figs:
        ctx.warnings.append(f"{rid}.title: figure typed in prose ({', '.join(figs[:5])})")
    if risk.get("status") == "rejected":
        res["excluded"] = []
        return res

    def primary_ok(field):
        tags = [resolve_tag(ctx, t) for t in scan_tags(get_field(risk, field) or "")]
        good = [t for t in tags if t["ok"] and t["cls"] == "primary"]
        if not good:
            seen = "; ".join(t.get("source") or t.get("error") for t in tags) or "no citations"
            res["excluded"].append(f"{field}: no resolvable primary citation (rule, history, or a "
                                   f"{PRIMARY_TAG} metric) [{seen}]")
        return tags
    ltags = primary_ok("likelihood.justification")
    primary_ok("impact.justification")
    if res["excluded"]:
        return res

    lk, im = risk["likelihood"], risk["impact"]
    sr = signal_row(ctx, risk, lk)
    if sr is None:
        return res
    row, value, note = sr
    if lk["signal"] is not None:
        cited = {t.get("canonical") for t in ltags if t["ok"] and t["kind"] == "metric"}
        if canonical(parse_path(lk["signal"])) not in cited:
            ctx.errors.append(f"{rid}: likelihood.justification must cite its signal as [metric:{lk['signal']}]")
    elif any(t["ok"] and t["kind"] == "metric" and t["cls"] == "primary" and t["toks"][0] == ("key", "tests")
             for t in ltags):
        ctx.warnings.append(f"{rid}: rubric row NT but the likelihood justification cites a {PRIMARY_TAG} test "
                            "metric; check whether a test measures this risk")
    if lk["rubric_row"] != row:
        ctx.errors.append(f"{rid}: likelihood.rubric_row is {lk['rubric_row']} but the signal gives {row} ({note})")
    uplift = 0
    up = lk["repeat_uplift"]
    if up is not None:
        a = ctx.audits.get(up["history"])
        if a is None:
            ctx.errors.append(f"{rid}: repeat_uplift cites {up['history']}, which is not an audit in history.json")
        elif not is_adverse(a.get("opinion")):
            ctx.errors.append(f"{rid}: repeat_uplift cites {up['history']} ({a.get('title')}), whose opinion "
                              f"{a.get('opinion')!r} is not adverse (Limited Assurance or worse)")
        else:
            uplift = UPLIFT
    expected = min(MAX_SCORE, RUBRIC[row][1] + uplift)
    res["override_l"] = None
    if lk["score"] != expected:
        if lk_override_ok:
            res["override_l"] = expected
        else:
            ctx.errors.append(f"{rid}: likelihood.score is {lk['score']} but rubric row {row} "
                              f"(base {RUBRIC[row][1]}{f' + uplift {uplift}' if uplift else ''}) gives {expected}")
    res["override_i"] = im_override_prev
    if not method["fallback"] and im["category"] not in method["categories"]:
        ctx.errors.append(f"{rid}: impact.category {im['category']!r} is not a Table 1 column: {method['categories']}")
        return res
    score, label, band = rate(method, lk["score"], im["score"])
    res.update(row=row, signal_value=value, signal_note=note, uplift=uplift, expected=expected,
               score=score, label=label, band=band, rated=True)
    if not any(t["kind"] == "rule" and t["ok"] for t in res["tags"]):
        ctx.warnings.append(f"{rid}: cites no rule; the planner traces rule -> risk -> control -> test")
    return res


# ---------------------------------------------------------------- rendering

def band_text(band):
    if not band:
        return "n/a (fallback scale)"
    return f"{band['level']}" + (f" ({band['rag']})" if band.get("rag") else "")


def l_label(method, s):
    return f"{s} {method['L'][s]}"


def i_label(method, s):
    return f"{s} {method['I'][s]}"


def render_register(ctx, method, results, noted, n, rev_info, decisions_rows, inputs, built, crr):
    M = method
    out = [f"# Procurement risk register (revision r{n})", "",
           f"Built {built} by `.claude/skills/risk-assessment/build_register.py` from `outputs/risk-ratings.json`. "
           + ("Draft for the auditor's decision at the gate." if n == 0 else f"Revision r{n} for auditor sign-off."),
           "",
           "> These are **risk indicators to investigate**, drawn from published data. They are not findings "
           "and do not suggest wrongdoing by the council, any service or any supplier.", ""]

    if n >= 1:
        out += [f"## Revision r{n}", ""]
        out += rev_info or ["No changes: every decision was Approve or Leave out."]
        out.append("")

    out += ["## How this register was built", "", "**Inputs**", "", "| File | sha256 |", "| --- | --- |"]
    out += [f"| `{k}` | `{v}` |" for k, v in inputs.items()]
    out.append("")
    if M["fallback"]:
        out += ["**Scoring method: FALLBACK.** history.json reports no usable council method "
                f"({M['reason']}), so likelihood and impact use 1 to 5, Very low to Very high, and the score is "
                "likelihood x impact. There is no matrix label or band.", ""]
    else:
        out += ["**Scoring method:** the council's own, from the Risk Management Strategy 2024-27 as recorded in "
                "`outputs/history.json`: score = likelihood x impact on the 5x5 matrix; Matrix label from Figure 1; "
                "Band from Table 4.", ""]
        out += [f"- {s}" for s in M["sources"]]
        out.append("")
        out += ["**Conflicting thresholds in the scoring method.** Each is resolved one way here, and the other "
                "reading is marked:", ""]
        if not M["conflicts"]:
            out.append("- None detected.")
        for c in M["conflicts"]:
            hist = f" (history: {', '.join(c['history'])})" if c["history"] else " (not recorded in history.json)"
            out.append(f"- **Used:** {c['used']}. **Marked:** {c['marked']}.{hist}")
        out.append("")
        if M["other_dis"]:
            out += ["**Other scoring-method discrepancies in history.json**, not used in any computation here:", ""]
            out += [f"- {d['id']}: {d['description']}" for d in M["other_dis"]]
            out.append("")

    tier_txt = ", ".join(f"£{fmt_value(t)}" for t in ctx.noise_tiers)
    out += ["**Evidence basis.**", "",
            f"- Likelihood and impact rest on the `{PRIMARY_TAG}` figures in analytics.json. Placement, grant, "
            "agency staff and premises figures, and figures for all tags combined, are cited as context only: "
            "placements recur by design.",
            ]
    if ctx.noise_tiers:
        out.append(f"- The split_purchases tier at {tier_txt} cannot raise a rating on its own. Every published "
                   f"payment exceeds the £{fmt_value(ctx.publication_floor)} publication floor, so any two published "
                   f"payments under {tier_txt} already add up to more than {tier_txt}: the tier flags by construction. "
                   "Its figures, and split_purchases totals that include it, are context only.")
    out += [f"- Repeat finding: a cited audit with an adverse opinion (Limited Assurance or worse) on the same "
            f"theme raises likelihood by {UPLIFT}, stated in the risk. The papers do not define the opinion scale"
            + (" (history: " + ", ".join(g["id"] for g in ctx.history.get("gaps", []) if g.get("topic") == "opinion_scale") + ")"
               if any(g.get("topic") == "opinion_scale" for g in ctx.history.get("gaps", [])) else "")
            + "; Weak is read as worse than Limited Assurance.",
            "- Every likelihood and impact justification cites at least one rule, history item or "
            f"`{PRIMARY_TAG}` metric that resolves. A risk without one, or with any citation or figure that does "
            "not resolve, is excluded and listed below.", ""]

    out += ["**Likelihood rubric.** The signal is the `general_procurement` count of the one test or threshold tier "
            "the risk rests on; the builder computes the row from it.", "",
            "| Row | Evidence | Base likelihood |", "| --- | --- | --- |"]
    for k, (ev, base) in RUBRIC.items():
        out.append(f"| {k} | {ev} | {l_label(M, base)} |")
    out += ["", f"Likelihood = base + {UPLIFT} for a repeat finding, at most {MAX_SCORE}. "
            f"{l_label(M, MAX_SCORE)} is reached only through that uplift.", ""]
    if not M["fallback"]:
        fin_key = next((k for k in M["categories"] if "financial" in k.lower()), None)
        out += ["**Impact** is chosen from Table 1: each risk names the column it is judged on.", ""]
        if fin_key:
            out += [f"- {fin_key}, as printed: " + "; ".join(
                f"{i_label(M, s)}: {M['impact_scale'][s]['criteria'][fin_key]}" for s in range(1, 6))]
        out.append("")

    rated = [r for r in results if r.get("rated")]
    out += ["## Risk summary", "", "| Risk | Title | Likelihood | Impact | Score | Matrix label | Band |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rated:
        mark = " ‡" if crr and crr[0] <= r["score"] <= crr[1] else ""
        ov = " (auditor override)" if r.get("override_l") is not None or r.get("override_i") else ""
        out.append(f"| {r['id']} | {md_cell(r['risk']['title'])}{ov} | {l_label(M, r['risk']['likelihood']['score'])} "
                   f"| {i_label(M, r['risk']['impact']['score'])} | {r['score']}{mark} | {r['label'] or 'n/a'} "
                   f"| {band_text(r['band'])} |")
    if not rated:
        out.append("| none | | | | | | |")
    if crr:
        out += ["", f"‡ Score {crr[0]} to {crr[1]}: Figure 4 would place this risk on the Corporate Risk Register; "
                "Table 4, which is used here, does not. See the conflicting thresholds above."]
    out.append("")

    out += ["## Risks", ""]
    for r in rated:
        risk, lk, im = r["risk"], r["risk"]["likelihood"], r["risk"]["impact"]
        rd = r["rendered"]
        out += [f"### {r['id']} {risk['title']}", "", rd["description"], ""]
        lline = (f"- **Likelihood: {l_label(M, lk['score'])}.** Rubric row {r['row']} ({r['signal_note']}), "
                 f"base {l_label(M, RUBRIC[r['row']][1])}")
        if r["uplift"]:
            lline += f"; repeat finding +{r['uplift']} (history {lk['repeat_uplift']['history']}: " \
                     f"{rd['likelihood.repeat_uplift.justification']})"
        lline += f". {rd['likelihood.justification']}"
        if r.get("override_l") is not None:
            lline += f" **Auditor override:** the rubric gives {l_label(M, r['override_l'])}."
        out.append(lline)
        crit = ""
        if not M["fallback"]:
            crit = f" Table 1, {im['category']}: \"{M['impact_scale'][im['score']]['criteria'][im['category']]}\""
        iline = f"- **Impact: {i_label(M, im['score'])}.**{crit} {rd['impact.justification']}"
        if r.get("override_i"):
            iline += " **Auditor override.**"
        out.append(iline)
        mark = " ‡" if crr and crr[0] <= r["score"] <= crr[1] else ""
        out.append(f"- **Score:** {r['score']}{mark}; matrix label {r['label'] or 'n/a'}; band {band_text(r['band'])}"
                   + (f": {r['band'].get('response')}" if r["band"] and r["band"].get("response") else ""))
        out.append(f"- **Evidence:** {rd['evidence']}")
        out.append(f"- **Proposed focus:** {rd['proposed_focus']}")
        out += ["- **Sources:**"]
        seen = set()
        for t in r["tags"]:
            if t["ok"] and t["source"] not in seen:
                seen.add(t["source"])
                out.append(f"  - {t['source']}")
        out.append("")

    out += ["## Noted, not rated", "",
            "Audits with a Limited (or worse) opinion on areas the spend tests exclude. They are not rated "
            "because no test measures them; they are not dropped either. The auditor decides at the gate.", ""]
    if noted:
        out += ["| Item | Area | Opinion | Source | Why not rated |", "| --- | --- | --- | --- | --- |"]
        for x, reason in noted:
            a = ctx.audits[x["history"]]
            out.append(f"| {x['history']} | {md_cell(a.get('title'))} ({md_cell(a.get('service') or a.get('directorate') or '')}) "
                       f"| {a.get('opinion')} | {first_cite(a)} | {md_cell(reason)} |")
    else:
        out.append("None.")
    out.append("")

    excl = [r for r in results if r["excluded"]]
    out += ["## Excluded: no resolvable citation", ""]
    if excl:
        for r in excl:
            out.append(f"- **{r['id']} {r['risk']['title']}**")
            out += [f"  - {e}" for e in r["excluded"]]
    else:
        out.append("None.")
    out.append("")

    rej = [r for r in results if r["risk"].get("status") == "rejected"]
    if rej:
        out += ["## Rejected by the auditor", ""]
        out += [f"- {r['id']} {r['risk']['title']}" for r in rej]
        out.append("")

    out += ["## Build warnings", ""]
    out += [f"- {w}" for w in ctx.warnings] or ["None."]
    out.append("")

    out += ["## Auditor decisions", "",
            "Record decisions in `outputs/auditor-comments.md`; this section is regenerated from it on every build.", "",
            "| Item | Decision | Comment | Applied |", "| --- | --- | --- | --- |"]
    for item, dec, com, app in decisions_rows:
        out.append(f"| {item} | {md_cell(dec) or '(undecided)'} | {md_cell(com)} | {md_cell(app)} |")
    if not decisions_rows:
        out.append("| none | | | |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT_DEFAULT)
    ap.add_argument("--ratings", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--analytics", type=Path)
    ap.add_argument("--history", type=Path)
    ap.add_argument("--rules", type=Path)
    ap.add_argument("--resolve", action="append", metavar="PATH",
                    help="print what a $.path resolves to in analytics.json, and how it counts as evidence; writes nothing")
    a = ap.parse_args(argv)
    root = a.root.resolve()
    out_dir = (a.out_dir or root / "outputs").resolve()
    if a.resolve:
        return show_paths(a.analytics or root / "outputs/analytics.json", root, a.resolve)
    paths = {
        "risk-ratings.json": a.ratings or out_dir / "risk-ratings.json",
        "analytics.json": a.analytics or root / "outputs/analytics.json",
        "history.json": a.history or root / "outputs/history.json",
        "rules.json": a.rules or root / "outputs/rules.json",
    }
    data = {}
    for name, p in paths.items():
        if not p.exists():
            print(f"STOP: {name} not found at {p}", file=sys.stderr)
            return 1
        try:
            data[name] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"STOP: {name} is not valid JSON: {e}", file=sys.stderr)
            return 1
    inputs = {name: sha256(p) for name, p in paths.items()}
    ratings = data["risk-ratings.json"]

    errs = check_schema(ratings)
    if errs:
        return fail(errs)
    ctx = Ctx(data["analytics.json"], data["history.json"], data["rules.json"])
    method = build_method(ctx)
    if method is None:
        return fail(ctx.errors)
    crr = next((c["affects"] for c in method["conflicts"] if c["kind"] == "crr_threshold"), None)

    comments_path = out_dir / "auditor-comments.md"
    try:
        decisions = parse_comments(comments_path)
    except ValueError as e:
        return fail([str(e)])

    snap_dir, snaps = snapshots(out_dir)
    latest = max(snaps) if snaps else None
    rev = ratings.get("revision")
    cur = body(ratings)
    data_inputs = {k: v for k, v in inputs.items() if k != "risk-ratings.json"}
    lk_ok, im_prev, rev_info, pending, prev_overrides = set(), set(), [], {}, {}
    if rev is None:
        n = 0
        if latest is not None and latest >= 1:
            return fail([f"the register is already at r{latest}; a further change needs a revision block "
                         f"(number {latest + 1})"])
        if latest == 0 and any(d["decision"] for d in decisions.values()):
            snap = json.loads(snaps[0].read_text(encoding="utf-8"))
            if snap["ratings"] != cur or snap["inputs"] != data_inputs:
                return fail(["auditor decisions are recorded against r0, but the ratings or inputs have changed "
                             "since; changes after the gate go in a revision block"])
    else:
        n = rev["number"]
        if latest is None:
            return fail(["revision block present but no r0 snapshot exists; build r0 first"])
        if n not in (latest, latest + 1):
            return fail([f"revision.number is {n}; the latest snapshot is r{latest}, so it must be {latest + 1}"])
        prev = json.loads(snaps[n - 1].read_text(encoding="utf-8"))
        if prev["inputs"] != data_inputs:
            changed = [k for k in data_inputs if prev["inputs"].get(k) != data_inputs[k]]
            return fail([f"inputs changed since r{n - 1}, which the auditor decided on: {changed}. The auditor did "
                         "not ask for this; rebuild from r0 with the auditor"])
        actual, amend, pending = check_revision(ctx, rev, prev["ratings"], prev["decision_rows"], cur, decisions, n)
        prev_overrides = prev.get("overrides", {})
        cur_ids = {r["risk_id"] for r in cur["risks"]}
        for rid in cur_ids:
            changed = actual.get(rid, set())
            if "likelihood.score" in amend.get(rid, set()) or (
                    "likelihood" in prev_overrides.get(rid, {}) and "likelihood.score" not in changed):
                lk_ok.add(rid)
            if "impact.score" in amend.get(rid, set()) or (
                    prev_overrides.get(rid, {}).get("impact") and "impact.score" not in changed):
                im_prev.add(rid)
        by_ref = {}
        for c in rev["changes"]:
            by_ref.setdefault(c["target"], []).append(c)
        for tgt in sorted(actual):
            cs = by_ref.get(tgt, [])
            refs = sorted({c["decision_ref"] for c in cs})
            why = "; ".join(f"{ref} {decisions[ref]['decision']}" + (f" (\"{decisions[ref]['comment']}\")"
                            if decisions[ref]["comment"] else "") for ref in refs if ref in decisions)
            summ = " ".join(c["summary"] for c in cs)
            rev_info.append(f"- **{tgt}**: {', '.join(sorted(actual[tgt]))}. {summ} Asked for by: {why or 'nothing'}.")

    if ctx.errors:
        return fail(ctx.errors)

    # adverse audits and noted items
    noted = []
    for x in cur["noted_not_rated"]:
        a = ctx.audits.get(x["history"])
        if a is None:
            ctx.errors.append(f"noted_not_rated: {x['history']} is not an audit in history.json")
            continue
        if not is_adverse(a.get("opinion")):
            ctx.errors.append(f"noted_not_rated: {x['history']} has opinion {a.get('opinion')!r}; only Limited "
                              "Assurance or worse is noted")
            continue
        rendered, _, problems = process_text(ctx, x["reason"])
        if problems:
            ctx.errors.append(f"noted_not_rated {x['history']}.reason: {'; '.join(problems)}")
        if typed_figures(x["reason"]):
            ctx.warnings.append(f"noted_not_rated {x['history']}: figure typed in prose")
        noted.append((x, rendered))
    if rev is not None:
        for c in rev["changes"]:
            if typed_figures(c["summary"]):
                ctx.warnings.append(f"revision change for {c['target']}: figure typed in the summary")

    results = []
    for risk in cur["risks"]:
        results.append(evaluate(ctx, method, risk, risk["risk_id"] in lk_ok, risk["risk_id"] in im_prev))
    if ctx.errors:
        return fail(ctx.errors)

    cited = {t["ref"] for r in results for t in r["tags"] if t["kind"] == "history" and t.get("ok")}
    cited |= {r["risk"]["likelihood"]["repeat_uplift"]["history"] for r in results
              if r["risk"]["likelihood"]["repeat_uplift"]}
    noted_ids = {x["history"] for x, _ in noted}
    for aid, a in ctx.audits.items():
        if is_adverse(a.get("opinion")) and aid not in cited and aid not in noted_ids:
            ctx.warnings.append(f"{aid} ({a.get('title')}, {a.get('opinion')}) is neither cited by a risk nor noted")

    # overrides to carry forward
    overrides = {}
    for r in results:
        o = {}
        if r.get("override_l") is not None:
            o["likelihood"] = r["override_l"]
        if r.get("override_i"):
            o["impact"] = True
        if o:
            overrides[r["id"]] = o
    if rev is not None:
        scores = {r["id"]: r["risk"] for r in results}
        ov = []
        for rid, o in overrides.items():
            if "likelihood" in o:
                ov.append(f"- {rid}: likelihood {l_label(method, scores[rid]['likelihood']['score'])} at the "
                          f"auditor's request; the rubric gives {l_label(method, o['likelihood'])}")
            if o.get("impact"):
                ov.append(f"- {rid}: impact {i_label(method, scores[rid]['impact']['score'])} at the auditor's request")
        if ov:
            rev_info += ["", "**Auditor overrides** (marked on the risk):"] + ov

    # decisions: keep everything already written; Applied for what this revision carried out
    for ref in pending:
        decisions[ref]["applied"] = f"r{n}"
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rated_rows, noted_rows, dec_rows = [], [], []
    shown = set()
    for r in results:
        if not (r.get("rated") or r["risk"].get("status") == "rejected" or decisions.get(r["id"], {}).get("decision")):
            continue
        d = decisions.get(r["id"], {"decision": "", "comment": "", "applied": ""})
        title = r["risk"]["title"] + (" (rejected)" if r["risk"].get("status") == "rejected" else "") \
            + (" (excluded: no resolvable citation)" if r["excluded"] else "")
        if r.get("rated"):
            lk, im = r["risk"]["likelihood"]["score"], r["risk"]["impact"]["score"]
            rated_rows.append([r["id"], title, l_label(method, lk), i_label(method, im), r["score"],
                               band_text(r["band"]), d["decision"], d["comment"], d["applied"]])
        else:
            rated_rows.append([r["id"], title, "", "", "", "", d["decision"], d["comment"], d["applied"]])
        dec_rows.append((r["id"], d["decision"], d["comment"], d["applied"]))
        shown.add(r["id"])
    for x, _ in noted:
        d = decisions.get(x["history"], {"decision": "", "comment": "", "applied": ""})
        a = ctx.audits[x["history"]]
        noted_rows.append([x["history"], a.get("title"), a.get("opinion"), d["decision"], d["comment"], d["applied"]])
        dec_rows.append((x["history"], d["decision"], d["comment"], d["applied"]))
        shown.add(x["history"])
    for k, d in decisions.items():
        if k in shown or not d["decision"]:
            continue
        if d["table"] == "rated":
            rated_rows.append([k, "(no longer in risk-ratings.json)", "", "", "", "", d["decision"], d["comment"], d["applied"]])
        else:
            a = ctx.audits.get(k, {})
            noted_rows.append([k, a.get("title", ""), a.get("opinion", ""), d["decision"], d["comment"], d["applied"]])
        dec_rows.append((k, d["decision"], d["comment"], d["applied"]))

    register = render_register(ctx, method, results, noted, n, rev_info, dec_rows,
                               {k: inputs[k] for k in inputs}, built, crr)
    out_dir.mkdir(parents=True, exist_ok=True)
    snap_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "risk-register.md").write_text(register, encoding="utf-8")
    write_comments(comments_path, n, inputs["risk-ratings.json"], built, rated_rows, noted_rows)
    (snap_dir / f"r{n}.json").write_text(json.dumps(
        {"revision": n, "built": built, "inputs": data_inputs, "ratings": cur, "overrides": overrides,
         "decision_rows": [row[0] for row in rated_rows + noted_rows]},
        indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    rated = [r for r in results if r.get("rated")]
    print(f"OK: register r{n}: {len(rated)} rated, {len(noted)} noted, "
          f"{sum(1 for r in results if r['excluded'])} excluded, {len(ctx.warnings)} warnings")
    for r in results:
        if r["excluded"]:
            print(f"  EXCLUDED {r['id']}: " + "; ".join(r["excluded"]))
    for w in ctx.warnings:
        print(f"  WARNING {w}")
    print(f"  wrote {out_dir / 'risk-register.md'}, {comments_path}, {snap_dir / f'r{n}.json'}")
    return 0


def show_paths(analytics_path, root, paths):
    analytics = json.loads(Path(analytics_path).read_text(encoding="utf-8"))
    ctx = Ctx(analytics, {}, {})
    code = 0
    for p in paths:
        try:
            toks = parse_path(p)
            value, trail = resolve(analytics, toks)
        except PathError as e:
            print(f"{p}: does not resolve: {e}")
            code = 1
            continue
        cls, why = classify_metric(ctx, toks, trail)
        if isinstance(value, dict):
            shown = "object with keys " + ", ".join(list(value)[:30])
        elif isinstance(value, list):
            shown = f"list of {len(value)}" + (f"; [0] keys: {', '.join(value[0])}" if value and isinstance(value[0], dict) else "")
        else:
            shown = fmt_value(value)
        print(f"{canonical(toks)} = {shown}  [{cls}: {why}]")
    return code


def fail(errs):
    print(f"FAIL: {len(errs)} error(s); nothing written", file=sys.stderr)
    for e in errs:
        print(f"  ERROR {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
