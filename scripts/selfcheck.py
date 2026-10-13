"""Step 6: independent self-check of analytics.json.

Reads only spend-clean.csv, notice-suppliers.csv and analytics.json (for
thresholds and parameters). Does not import analytics.py; uses common.py for
paths only. Re-derives the top-ranked item of every test that flagged anything
with plain pandas and compares: money to the penny, counts exactly.
Writes outputs/analytics-full/selfcheck.json; exits non-zero on any mismatch.
"""
from __future__ import annotations

import datetime as dt
import json
import sys

import pandas as pd

from common import ANALYTICS_JSON, NOTICE_SUPPLIERS, SELFCHECK_JSON, SPEND_CLEAN

results = []


def record(test, item, check, expected, recomputed, ok=None):
    if ok is None:
        ok = expected == recomputed
    results.append({"test": test, "item": item, "check": check,
                    "expected": expected, "recomputed": recomputed, "pass": bool(ok)})


def pence(x) -> int:
    return int(round(float(x) * 100))


def main():
    for p in (SPEND_CLEAN, NOTICE_SUPPLIERS, ANALYTICS_JSON):
        if not p.exists():
            print(f"STOP: missing {p}")
            sys.exit(2)
    a = json.load(open(ANALYTICS_JSON))
    P = a["parameters"]
    sp = pd.read_csv(SPEND_CLEAN, dtype=str, keep_default_na=False)
    sp["p"] = sp["net_amount"].map(pence)
    sp["d"] = pd.to_datetime(sp["date"], format="%Y-%m-%d")
    named = sp[sp["redacted"] != "True"]
    ns = pd.read_csv(NOTICE_SUPPLIERS, dtype=str, keep_default_na=False)
    w_start = pd.Timestamp(a["window"]["start"])
    record("window", "spend window", "start/end from spend-clean.csv",
           [a["window"]["start"], a["window"]["end"]],
           [sp["d"].min().strftime("%Y-%m-%d"), sp["d"].max().strftime("%Y-%m-%d")])
    tests = a["tests"]
    nothing = []

    def ran_and_flagged(name, flagged):
        t = tests.get(name, {})
        if t.get("status") != "run":
            nothing.append({"test": name, "result": f"not checked: {t.get('status')}"})
            return False
        if not flagged:
            nothing.append({"test": name, "result": "nothing to check"})
            return False
        return True

    # ---- 1 threshold_clustering
    t = tests["threshold_clustering"]
    if ran_and_flagged("threshold_clustering", t["counts"]["below_band_payments"] > 0):
        th = next(x for x in a["thresholds"] if x["status"] == "run")
        T, inc = th["value"], th["inclusive"]
        Tp = T * 100
        lo = round(T * (1 - P["clustering_band_width"]) * 100)
        hi = round(T * (1 + P["comparison_band_width"]) * 100)
        if inc:
            b = sp[(sp["p"] >= lo) & (sp["p"] < Tp)]
            c = sp[(sp["p"] >= Tp) & (sp["p"] < hi)]
        else:
            b = sp[(sp["p"] >= lo) & (sp["p"] <= Tp)]
            c = sp[(sp["p"] > Tp) & (sp["p"] <= hi)]
        bt = next(x for x in t["by_threshold"] if x["threshold"] == T)
        item = f"T={T}"
        record("threshold_clustering", item, "below-band count", bt["below"]["count"], len(b))
        record("threshold_clustering", item, "below-band £", pence(bt["below"]["total"]), int(b["p"].sum()))
        record("threshold_clustering", item, "comparison-band count", bt["comparison"]["count"], len(c))
        record("threshold_clustering", item, "comparison-band £", pence(bt["comparison"]["total"]), int(c["p"].sum()))

    # ---- 2 split_purchases
    t = tests["split_purchases"]
    if ran_and_flagged("split_purchases", bool(t["top20"])):
        g = t["top20"][0]
        T = g["threshold"]
        inc = next(x["inclusive"] for x in a["thresholds"] if x["value"] == T)
        item = f"{g['supplier']} T={T}"
        sample = sp[sp["transaction_id"].isin(g["transaction_ids_first10"])]
        record("split_purchases", item, "listed transaction ids exist",
               len(g["transaction_ids_first10"]), len(sample))
        record("split_purchases", item, "listed ids belong to one supplier", [g["supplier"]],
               sorted(sample["supplier_norm"].unique()))
        under_all = (named["p"] < T * 100) if inc else (named["p"] <= T * 100)
        cand = named[(named["supplier_norm"] == g["supplier"]) & under_all]
        rows = cand[(cand["d"] >= pd.Timestamp(g["first_date"])) & (cand["d"] <= pd.Timestamp(g["last_date"]))]
        record("split_purchases", item, "listed ids inside the re-derived group", True,
               set(g["transaction_ids_first10"]) <= set(rows["transaction_id"]))
        under = (rows["p"] < T * 100) if inc else (rows["p"] <= T * 100)
        record("split_purchases", item, "each payment under T", True, bool(under.all()))
        record("split_purchases", item, "group total £", pence(g["total"]), int(rows["p"].sum()))
        record("split_purchases", item, "group rows", g["rows"], len(rows))
        record("split_purchases", item, "group rows = transaction id count", g["transaction_ids_count"], len(rows))
        record("split_purchases", item, "group span days", g["span_days"],
               int((rows["d"].max() - rows["d"].min()).days))
        bw = cand[(cand["d"] >= pd.Timestamp(g["best_window_first_date"]))
                  & (cand["d"] <= pd.Timestamp(g["best_window_last_date"]))]
        record("split_purchases", item, "best window rows", g["best_window_rows"], len(bw))
        span = int((bw["d"].max() - bw["d"].min()).days)
        record("split_purchases", item, "best window span <= split_window_days",
               f"<= {P['split_window_days']}", span, span <= P["split_window_days"])
        record("split_purchases", item, "best window total £", pence(g["best_window_total"]), int(bw["p"].sum()))
        tot = int(bw["p"].sum())
        crosses = tot >= T * 100 if inc else tot > T * 100
        record("split_purchases", item, "best window total crosses T", True, crosses)
        record("split_purchases", item, "best window has >= 2 payments", True, len(bw) >= 2)

    # ---- 3 no_published_notice
    t = tests["no_published_notice"]
    if ran_and_flagged("no_published_notice", bool(t["top20"])):
        s = t["top20"][0]
        name = s["supplier"]
        rows = named[named["supplier_norm"] == name]
        tot = int(rows["p"].sum())
        record("no_published_notice", name, "3-month total £", pence(s["three_month_total"]), tot)
        record("no_published_notice", name, "annualised estimate £", pence(s["annualised_estimate"]),
               tot * P["annualisation_factor"])
        record("no_published_notice", name, "rows", s["rows"], len(rows))
        act = ns[(ns["active"] == "True") & (ns["supplier_norm"] == name)]
        record("no_published_notice", name, "active notices with same supplier_norm", 0, len(act))
        th = t["threshold"]
        ann = tot * P["annualisation_factor"]
        at = ann >= th["value"] * 100 if th["inclusive"] else ann > th["value"] * 100
        record("no_published_notice", name, "annualised estimate at/above tender threshold", True, at)

    # ---- 4 duplicates
    t = tests["duplicates"]
    if ran_and_flagged("duplicates", bool(t["top20"])):
        g = t["top20"][0]
        item = f"{g['supplier']} £{g['amount']}"
        rows = sp[sp["transaction_id"].isin(g["transaction_ids"])].sort_values("d")
        record("duplicates", item, "all transaction ids exist", len(g["transaction_ids"]), len(rows))
        record("duplicates", item, "one supplier", [g["supplier"]], sorted(rows["supplier_norm"].unique()))
        record("duplicates", item, "one amount (pence)", [pence(g["amount"])], sorted(rows["p"].unique().tolist()))
        gaps = rows["d"].diff().dt.days.dropna()
        mx = int(gaps.max()) if len(gaps) else 0
        record("duplicates", item, "each date within duplicate_window_days of the next",
               f"<= {P['duplicate_window_days']}", mx, mx <= P["duplicate_window_days"])
        record("duplicates", item, "group total £", pence(g["total"]), int(rows["p"].sum()))

    # ---- 5 expired_notice_spend
    t = tests["expired_notice_spend"]
    if ran_and_flagged("expired_notice_spend", bool(t["top20"])):
        s = t["top20"][0]
        name = s["supplier"]
        m = ns[ns["supplier_norm"] == name].drop_duplicates("notice_id")
        record("expired_notice_spend", name, "exact-match notices", sorted(s["notices"]), sorted(m["notice_id"]))
        ends = pd.to_datetime(m["end_date"].replace("", None), format="%Y-%m-%d")
        ok = len(m) > 0 and ends.notna().all() and bool((ends < w_start).all())
        record("expired_notice_spend", name, "every exact-match notice ended before window start", True, ok)
        rows = named[named["supplier_norm"] == name]
        record("expired_notice_spend", name, "3-month total £", pence(s["three_month_total"]), int(rows["p"].sum()))

    # ---- 6 spend_vs_award
    t = tests["spend_vs_award"]
    if ran_and_flagged("spend_vs_award", bool(t["top20"])):
        s = t["top20"][0]
        name = s["supplier"]
        rows = named[named["supplier_norm"] == name]
        ann_p = int(rows["p"].sum()) * P["annualisation_factor"]
        record("spend_vs_award", name, "annualised estimate £", pence(s["annualised_estimate"]), ann_p)
        act = ns[(ns["active"] == "True") & (ns["supplier_norm"] == name)].drop_duplicates("notice_id")
        record("spend_vs_award", name, "exactly one active exact-match notice", [s["notice_id"]],
               sorted(act["notice_id"]))
        n = ns[ns["notice_id"] == s["notice_id"]].iloc[0]
        record("spend_vs_award", name, "single supplier block", 1, int(n["n_blocks"]))
        award = float(n["awarded_value"])
        record("spend_vs_award", name, "Awarded Value £", pence(s["awarded_value"]), pence(award))
        days = (dt.date.fromisoformat(n["end_date"]) - dt.date.fromisoformat(n["start_date"])).days
        years = days / P["days_per_contract_year"]
        record("spend_vs_award", name, "contract years (4 dp)", s["contract_years"], round(years, 4))
        ratio = (ann_p / 100) / (award / years)
        record("spend_vs_award", name, "ratio (4 dp)", s["ratio"], round(ratio, 4))
        record("spend_vs_award", name, "ratio at/above award_ratio_flag", True, ratio >= P["award_ratio_flag"])

    # ---- 7 high_value_suppliers
    t = tests["high_value_suppliers"]
    if ran_and_flagged("high_value_suppliers", bool(t["top20"])):
        s = t["top20"][0]
        name = s["supplier"]
        rows = named[named["supplier_norm"] == name]
        tot = int(rows["p"].sum())
        record("high_value_suppliers", name, "3-month total £", pence(s["three_month_total"]), tot)
        record("high_value_suppliers", name, "annualised estimate £", pence(s["annualised_estimate"]),
               tot * P["annualisation_factor"])
        q = t["threshold"]
        ann = named.groupby("supplier_norm")["p"].sum() * P["annualisation_factor"]
        n = int((ann >= q["value"] * 100).sum()) if q["inclusive"] else int((ann > q["value"] * 100).sum())
        record("high_value_suppliers", "population", "suppliers at/above quote threshold",
               t["counts"]["suppliers"], n)
        record("high_value_suppliers", name, "ranked first by £", name,
               ann.sort_values(ascending=False).index[0])

    passed = all(r["pass"] for r in results)
    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "inputs": ["outputs/analytics-full/spend-clean.csv",
                      "outputs/analytics-full/notice-suppliers.csv", "outputs/analytics.json"],
           "passed": passed, "checks": len(results),
           "failed": [r for r in results if not r["pass"]],
           "results": results, "not_checked": nothing}
    with open(SELFCHECK_JSON, "w") as f:
        json.dump(out, f, indent=2, default=str)
    by_test = {}
    for r in results:
        by_test.setdefault(r["test"], [0, 0])
        by_test[r["test"]][0 if r["pass"] else 1] += 1
    for k, (ok, bad) in by_test.items():
        print(f"{k}: {ok} passed, {bad} failed")
    for x in nothing:
        print(f"{x['test']}: {x['result']}")
    if not passed:
        f0 = out["failed"][0]
        print(f"STOP: self-check mismatch: {f0['test']} {f0['item']} {f0['check']}: "
              f"expected {f0['expected']}, recomputed {f0['recomputed']}")
        sys.exit(3)
    print(f"self-check passed ({len(results)} checks)")


if __name__ == "__main__":
    main()
