"""Shared paths, rules.json threshold derivation, PARAMETERS, supplier-name
normalisation, spend tagging and date helpers for the spend-analyst scripts.

Writes nothing. Every threshold and inclusive flag comes from outputs/rules.json
at run time. Money is handled in integer pence internally (the source amounts
are asserted to be whole pence, so the conversion is exact, not a rounding).
"""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SPEND_DIR = DATA / "spend"
CONTRACTS_CSV = DATA / "contracts.csv"
RULES_JSON = ROOT / "outputs" / "rules.json"
OUT = ROOT / "outputs"
FULL = OUT / "analytics-full"
ANALYTICS_JSON = OUT / "analytics.json"

SPEND_CLEAN = FULL / "spend-clean.csv"
EXCLUSIONS_CSV = FULL / "exclusions.csv"
NORMLOG_CSV = FULL / "normalisation-log.csv"
TAGLOG_CSV = FULL / "tag-log.csv"
NOTICE_SUPPLIERS = FULL / "notice-suppliers.csv"
SELFCHECK_JSON = FULL / "selfcheck.json"

SCRIPTS = ["scripts/common.py", "scripts/clean.py", "scripts/contracts.py",
           "scripts/analytics.py", "scripts/selfcheck.py"]


def rel(p: Path) -> str:
    return str(Path(p).resolve().relative_to(ROOT))


# ---------------------------------------------------------------- stop
class StopCondition(Exception):
    pass


def stop(msg: str):
    raise StopCondition(msg)


def run_main(fn):
    """Run a script's main(); on a stop condition print one line and exit 2."""
    try:
        fn()
    except StopCondition as e:
        print(f"STOP: {e}")
        sys.exit(2)


def spend_files() -> list[Path]:
    return sorted(SPEND_DIR.glob("*.xlsx"))


def check_inputs():
    """Stop if rules.json, contracts.csv or the spend workbooks are missing."""
    missing = [rel(p) if p.exists() else str(p.relative_to(ROOT))
               for p in (RULES_JSON, CONTRACTS_CSV) if not p.exists()]
    if missing:
        stop(f"missing input: {', '.join(missing)}")
    if not SPEND_DIR.exists() or not spend_files():
        stop("missing input: no data/spend/*.xlsx workbooks")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- parameters
PARAMETERS = {
    "split_window_days": 30,
    "duplicate_window_days": 7,
    "clustering_band_width": 0.10,
    "comparison_band_width": 0.10,
    "candidate_ratio_cutoff": 0.85,
    "candidate_containment_min_chars": 6,
    "annualisation_factor": 4,
    "award_ratio_flag": 1.25,
    "days_per_contract_year": 365.25,
    "export_cap_warning_rows": 950,
}

PARAMETER_DEFINITIONS = {
    "split_window_days": "last date - first date <= 30, dates without time of day",
    "duplicate_window_days": "dates at most 7 apart, dates without time of day",
    "clustering_band_width": "band below T: 0.9 x T to T",
    "comparison_band_width": "band above T: T to 1.1 x T",
    "candidate_ratio_cutoff": "difflib SequenceMatcher ratio",
    "candidate_containment_min_chars": "both normalised names at least this long for containment",
    "annualisation_factor": "3-month window x 4 = annualised estimate",
    "award_ratio_flag": "annualised estimate / (Awarded Value / contract years) at or above this",
    "days_per_contract_year": "contract years = (End - Start) days / 365.25",
    "export_cap_warning_rows": "warn of the Contracts Finder export cap at or above this many data rows",
}

EXPECTED_COLUMNS = ["Service", "Expenditure category", "Narrative", "Date",
                    "Net amount", "Supplier name"]
SHEET = "Data to publish"
HEADER_SEARCH_ROWS = 20

# Exact Narrative values excluded before anything else (CLAUDE.md).
EXCLUSIONS = {
    "statutory/inter-authority": [
        "Employers LGPS Deficit Contribution", "LGPS Employees Control",
        "LGPS Employers Control", "Teachers LGPS ERS Control",
        "Prudential AVC Teachers",
        "Joint Arrangements (with Other Local Authorities or NHS)",
        "Payments to Other Local Authorities (excl Joint Arrangements)",
        "Payments to NHS (excl Joint Arrangement)", "Council Tax Court Orders",
        "Court Order Control",
    ],
    "payments to individuals": [
        "Direct Payment", "Allowances for provision care",
        "Adult Placement Allowances", "Payments to Carers",
    ],
}
REDACTED_VALUE = "Redacted"
REDACTED_REASON = "redacted: left out of supplier-grouped tests"

# ---------------------------------------------------------------- spend tags
PLACEMENT_SERVICES = ["Adult Social Care", "Children's Social Care",
                      "Education & SEND",
                      "Education (DSG Funded) & Other Education Grants"]
TAG_RULES = [
    (1, "grant", 'Narrative = "Grants"'),
    (2, "agency_staff", 'Narrative = "Agency & Temporary Staff"'),
    (3, "premises", 'Expenditure category = "Premises"'),
    (4, "placement", 'Expenditure category = "Third Party Payments" and Service in '
                     + "; ".join(PLACEMENT_SERVICES)),
    (5, "general_procurement", "everything else"),
]
TAGS = [t for _, t, _ in TAG_RULES]


def spend_tag(service, category, narrative) -> tuple[str, int]:
    """Exactly one tag per row, first matching rule wins. Returns (tag, rule)."""
    service = service if isinstance(service, str) else None
    category = category if isinstance(category, str) else None
    narrative = narrative if isinstance(narrative, str) else None
    if narrative == "Grants":
        return "grant", 1
    if narrative == "Agency & Temporary Staff":
        return "agency_staff", 2
    if category == "Premises":
        return "premises", 3
    if category == "Third Party Payments" and service in PLACEMENT_SERVICES:
        return "placement", 4
    return "general_procurement", 5


# ---------------------------------------------------------------- normalisation
NORM_RULES = [
    ("1", "uppercase"),
    ("2", "non-alphanumeric to space; collapse whitespace"),
    ("3", "trading name: keep text after last T A / T AS / TRADING AS"),
    ("4", "drop tokens LTD, LIMITED, PLC, LLP"),
    ("5", "drop payment tags (DD PAYMENTS ONLY, CHAPS ONLY, BACS; longest first)"),
    ("6", "collapse whitespace, strip"),
    ("6-fallback", "empty result: fall back to the rule-2 result"),
]
COMPANY_TOKENS = {"LTD", "LIMITED", "PLC", "LLP"}
# fixed list of token sequences, longest first (auditor decision); PAYMENTS alone is
# deliberately not a tag. Additions are for the human to decide.
PAYMENT_TAGS = [("DD", "PAYMENTS", "ONLY"), ("CHAPS", "ONLY"), ("BACS",)]
# tokens scanned for (not removed) to suggest further payment tags for review
PAYMENT_TAG_HINTS = {"BACS", "CHEQUE", "CHQ", "CHAPS", "PAYMENT", "PAYMENTS", "ONLY"}


def normalise_supplier(raw) -> tuple[str, list[str]]:
    """Return (normalised name, ids of rules that changed it)."""
    if not isinstance(raw, str):
        stop(f"supplier name is not text: {raw!r}")
    changed = []
    s1 = raw.upper()
    if s1 != raw:
        changed.append("1")
    s2 = " ".join("".join(c if c.isalnum() else " " for c in s1).split())
    if s2 != s1:
        changed.append("2")
    toks = s2.split()
    # rule 3: trading name after the last T A / T AS / TRADING AS, at token index >= 1
    end = None
    for i in range(1, len(toks) - 1):
        if (toks[i] == "T" and toks[i + 1] in ("A", "AS")) or \
           (toks[i] == "TRADING" and toks[i + 1] == "AS"):
            end = i + 2
    if end is not None:
        toks = toks[end:]
        changed.append("3")
    # rule 4
    t4 = [t for t in toks if t not in COMPANY_TOKENS]
    if t4 != toks:
        changed.append("4")
    toks = t4
    # rule 5
    t5 = list(toks)
    tags_hit = []
    for tag in PAYMENT_TAGS:  # longest first
        n = len(tag)
        out, i = [], 0
        while i < len(t5):
            if tuple(t5[i:i + n]) == tag:
                i += n
            else:
                out.append(t5[i])
                i += 1
        if out != t5:
            tags_hit.append("5:" + " ".join(tag))
        t5 = out
    if t5 != toks:
        changed.append("5")
        changed.extend(tags_hit)
    joined = " ".join(t5)  # tokens are already single-spaced
    s6 = " ".join(joined.split()).strip()
    if s6 != joined:
        changed.append("6")
    if not s6:
        s6 = s2
        changed.append("6-fallback")
    return s6, changed


# ---------------------------------------------------------------- rules.json
def load_rules() -> dict:
    if not RULES_JSON.exists():
        stop("missing input: outputs/rules.json")
    with open(RULES_JSON) as f:
        return json.load(f)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _single_value(rules: list[dict], label: str) -> dict:
    if not rules:
        stop(f"rules.json has no rule giving the {label} threshold")
    vals = {r["threshold_low"] for r in rules}
    incl = {bool(r["threshold_low_inclusive"]) for r in rules}
    ids = [r["rule_id"] for r in rules]
    if len(vals) != 1 or not _is_int(next(iter(vals))):
        stop(f"rules for the {label} threshold give different or non-integer values: "
             f"{ids} -> {sorted(map(str, vals))}")
    if len(incl) != 1:
        stop(f"rules for the {label} threshold give different inclusive flags: {ids}")
    return {"value": next(iter(vals)), "inclusive": next(iter(incl)), "rule_ids": ids}


def derive_thresholds(rules_doc: dict | None = None) -> dict:
    """Threshold list, publication floor and the two named thresholds."""
    rd = rules_doc or load_rules()
    rules = rd["rules"]
    spend_rules = [r for r in rules if "spend_data" in (r.get("evidence_source") or [])]

    # publication floor: the spend-data rule requiring publication of expenditure
    pub = [r for r in spend_rules
           if "transparency code" in (r.get("required_action") or "").lower()]
    if len(pub) != 1 or not _is_int(pub[0]["threshold_low"]):
        stop("rules.json: cannot identify exactly one spend-data publication rule "
             f"(found {[r['rule_id'] for r in pub]})")
    floor = {"value": pub[0]["threshold_low"],
             "inclusive": bool(pub[0]["threshold_low_inclusive"]),
             "rule_id": pub[0]["rule_id"], "band_printed": pub[0].get("band_printed")}

    lower = defaultdict(list)   # value -> [(rule_id, inclusive)]
    upper = defaultdict(list)   # value -> [(rule_id, derived inclusive = not high_inclusive)]
    scopes = defaultdict(set)
    param_edges = defaultdict(list)  # param -> [(rule_id, 'low'|'high')]
    for r in spend_rules:
        for side in ("low", "high"):
            v = r.get(f"threshold_{side}")
            p = r.get(f"threshold_{side}_param")
            if v is not None:
                if not _is_int(v):
                    stop(f"rules.json {r['rule_id']}: threshold_{side} is not an integer: {v!r}")
                flag = r.get(f"threshold_{side}_inclusive")
                if not isinstance(flag, bool):
                    stop(f"rules.json {r['rule_id']}: threshold_{side}_inclusive missing")
                if side == "low":
                    lower[v].append((r["rule_id"], flag))
                else:
                    upper[v].append((r["rule_id"], not flag))
                scopes[v].update(r.get("scope") or [])
            if p:
                param_edges[p].append((r["rule_id"], side))
                scopes[p].update(r.get("scope") or [])

    thresholds = []
    for v in sorted(set(lower) | set(upper)):
        lo_flags = {f for _, f in lower[v]}
        up_flags = {f for _, f in upper[v]}
        if len(lo_flags) > 1:
            stop(f"rules give threshold {v} different inclusive flags as a lower bound: "
                 f"{lower[v]}")
        note = None
        if lo_flags:
            inclusive = next(iter(lo_flags))
            source = "lower bound"
            if up_flags and up_flags != lo_flags:
                note = (f"upper bound in {[i for i, _ in upper[v]]} and lower bound in "
                        f"{[i for i, _ in lower[v]]} leave the value itself in neither band "
                        "(see rules.json notes); the lower-bound flag is used")
        else:
            if len(up_flags) > 1:
                stop(f"rules give threshold {v} different inclusive flags as an upper bound: "
                     f"{upper[v]}")
            inclusive = next(iter(up_flags))
            source = "opposite of upper-bound flag"
        ids = sorted({i for i, _ in lower[v]} | {i for i, _ in upper[v]})
        if v <= floor["value"]:
            status = "not run: at or below the publication floor of the spend data"
        else:
            status = "run"
        thresholds.append({"value": v, "inclusive": inclusive, "inclusive_from": source,
                           "rule_ids": ids, "scopes": sorted(scopes[v]),
                           "status": status, "note": note})

    params = rd.get("parameters") or {}
    for p, edges in sorted(param_edges.items()):
        if p not in params:
            stop(f"rules.json: parameter {p} referenced by {edges} is not defined")
        vals = (params[p] or {}).get("values") or {}
        if any(x is not None for x in vals.values()):
            stop(f"rules.json parameter {p} has values {vals}; this brief does not define "
                 "how per-scope parameter values are applied to spend rows")
        thresholds.append({"value": p, "inclusive": None, "inclusive_from": None,
                           "rule_ids": sorted({i for i, _ in edges}),
                           "scopes": sorted(scopes[p]),
                           "status": "not run: parameter not supplied", "note": None})

    appb = [r for r in rules if str(r.get("clause", "")).startswith("AppB")]
    tender_rules = [r for r in appb
                    if "contract_notices" in (r.get("evidence_source") or [])
                    and (r.get("required_action") or "").lower().startswith("publish a contract notice")]
    quote_rules = [r for r in appb
                   if re.search(r"invite quotes", (r.get("required_action") or ""), re.I)
                   and re.search(r"at least three", r.get("required_action") or "", re.I)
                   and re.search(r"procurement portal", r.get("required_action") or "", re.I)]
    named = {"tender_publication": _single_value(tender_rules, "tender/publication (Test 3)"),
             "quote": _single_value(quote_rules, "quote (Test 7)")}
    # a named threshold must agree with the threshold list
    for k, nt in named.items():
        match = [t for t in thresholds if t["value"] == nt["value"]]
        if match and match[0]["inclusive"] != nt["inclusive"]:
            stop(f"{k} threshold {nt['value']} inclusive flag disagrees with the threshold list")
    return {"thresholds": thresholds, "publication_floor": floor, "named": named}


# ---------------------------------------------------------------- comparisons (pence)
def to_pence(x: float) -> int:
    return int(round(x * 100))


def at_or_above(amount_p, t_pounds: int, inclusive: bool):
    """True where the stricter band applies: >= T if inclusive, > T otherwise."""
    tp = t_pounds * 100
    return amount_p >= tp if inclusive else amount_p > tp


def below(amount_p, t_pounds: int, inclusive: bool):
    """True where a single amount stays under the band: < T if inclusive, <= T otherwise."""
    tp = t_pounds * 100
    return amount_p < tp if inclusive else amount_p <= tp


def band_edges_pence(t_pounds: int, width: float) -> tuple[int, int]:
    """(lower edge of band below T, upper edge of band above T) in pence."""
    return int(round(t_pounds * (1 - width) * 100)), int(round(t_pounds * (1 + width) * 100))


def gbp(pence) -> float:
    return round(int(pence) / 100, 2)


# ---------------------------------------------------------------- dates / window
SPEND_TEXT_DATE_FMT = "%m/%d/%y"
CONTRACT_DATE_FMT = "%d/%m/%Y"
PUBLISHED_DATE_FMT = "%Y-%m-%dT%H:%M:%S%z"


def spend_window(dates: pd.Series) -> dict:
    """First and last date; stop unless it is exactly three whole calendar months."""
    start, end = dates.min(), dates.max()
    if pd.isna(start) or pd.isna(end):
        stop("spend window: no dates")
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    last_day = calendar.monthrange(end.year, end.month)[1]
    if start.day != 1 or end.day != last_day or months != 3:
        stop(f"spend window {start}..{end} does not cover exactly three whole calendar "
             f"months (months spanned {months}); the x4 annualisation needs three")
    return {"start": start.isoformat(), "end": end.isoformat(), "months": months,
            "annualisation_factor": PARAMETERS["annualisation_factor"]}


def read_spend_clean() -> pd.DataFrame:
    if not SPEND_CLEAN.exists():
        stop("outputs/analytics-full/spend-clean.csv missing: run scripts/clean.py first")
    df = pd.read_csv(SPEND_CLEAN, dtype={"transaction_id": str, "supplier_name": str,
                                         "supplier_norm": str, "service": str,
                                         "expenditure_category": str, "narrative": str,
                                         "spend_tag": str, "source_file": str},
                     keep_default_na=False, na_values=[])
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
    df["redacted"] = df["redacted"].map({"True": True, "False": False, True: True, False: False})
    df["net_pence"] = df["net_pence"].astype("int64")
    return df


def read_notice_suppliers() -> pd.DataFrame:
    if not NOTICE_SUPPLIERS.exists():
        stop("outputs/analytics-full/notice-suppliers.csv missing: run scripts/contracts.py first")
    ns = pd.read_csv(NOTICE_SUPPLIERS, dtype=str, keep_default_na=False)
    for c in ("start_date", "end_date", "awarded_date"):
        ns[c] = pd.to_datetime(ns[c].replace("", None), format="%Y-%m-%d")
    ns["awarded_value"] = pd.to_numeric(ns["awarded_value"], errors="raise")
    ns["n_blocks"] = ns["n_blocks"].astype(int)
    ns["active"] = ns["active"].map({"True": True, "False": False})
    return ns


# ---------------------------------------------------------------- raw readers (shared)
def find_header_row(raw: pd.DataFrame) -> int | None:
    want = set(EXPECTED_COLUMNS)
    for i in range(min(HEADER_SEARCH_ROWS, len(raw))):
        vals = {str(v).strip() for v in raw.iloc[i].tolist() if isinstance(v, str)}
        if want <= vals:
            return i
    return None


def read_workbook(path: Path) -> tuple[pd.DataFrame, int]:
    """Read one workbook's 'Data to publish' sheet. Returns (frame, header_row)."""
    xl = pd.ExcelFile(path)
    if SHEET not in xl.sheet_names:
        stop(f"{rel(path)}: no sheet '{SHEET}' (sheets: {xl.sheet_names})")
    raw = pd.read_excel(xl, sheet_name=SHEET, header=None, nrows=HEADER_SEARCH_ROWS)
    h = find_header_row(raw)
    if h is None:
        stop(f"{rel(path)}: no row in the first {HEADER_SEARCH_ROWS} holds all of {EXPECTED_COLUMNS}")
    df = pd.read_excel(xl, sheet_name=SHEET, header=h)
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        stop(f"{rel(path)}: missing expected column(s) {missing}")
    return df[EXPECTED_COLUMNS].copy(), h


def parse_net_amount(s: pd.Series, path: Path) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        out = s.astype(float)
    else:
        out = pd.to_numeric(s, errors="coerce")
    bad = out.isna()
    if bad.any():
        stop(f"{rel(path)}: {int(bad.sum())} Net amount value(s) do not parse as a number "
             f"(first: {s[bad].iloc[0]!r})")
    pence = (out * 100).round()
    if ((out * 100 - pence).abs() > 1e-6).any():
        stop(f"{rel(path)}: Net amount values not in whole pence")
    return out


def parse_spend_dates(s: pd.Series, path: Path) -> pd.Series:
    """datetime kept; text parsed as M/D/YY; anything else stops. Returns datetime64."""
    if pd.api.types.is_datetime64_any_dtype(s):
        out = s
    else:
        vals = []
        for v in s.tolist():
            if isinstance(v, (pd.Timestamp, dt.datetime)):
                vals.append(pd.Timestamp(v))
            elif isinstance(v, str):
                try:
                    vals.append(pd.Timestamp(dt.datetime.strptime(v.strip(), SPEND_TEXT_DATE_FMT)))
                except ValueError:
                    stop(f"{rel(path)}: Date text {v!r} is not M/D/YY")
            else:
                stop(f"{rel(path)}: Date cell {v!r} is neither a datetime nor M/D/YY text")
        out = pd.Series(vals, index=s.index)
    if out.isna().any():
        stop(f"{rel(path)}: {int(out.isna().sum())} blank Date cell(s)")
    return out


def org_kept(name: str) -> bool:
    return name.strip().lower() in ("west berkshire council", "west berkshire")


SUPPLIER_COL = "Supplier [Name|Address|Ref type|Ref Number|Is SME|Is VCSE]"
# a notice's start and end (CLAUDE.md); the export's Start Date/End Date are not used
NOTICE_START_COL = "Contract start date"
NOTICE_END_COL = "Contract end date"


def read_contracts_raw() -> pd.DataFrame:
    if not CONTRACTS_CSV.exists():
        stop("missing input: data/contracts.csv")
    return pd.read_csv(CONTRACTS_CSV, dtype=str, keep_default_na=False)
