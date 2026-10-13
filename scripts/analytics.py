"""Steps 3-5: the seven risk-indicator tests, analytics.json and reconciliation.

Reads outputs/rules.json, outputs/analytics-full/spend-clean.csv,
notice-suppliers.csv, exclusions.csv, normalisation-log.csv, and re-reads the
raw workbooks and contracts.csv for reconciliation. Writes
outputs/analytics.json and one CSV per test in outputs/analytics-full/.

All money is integer pence until output. Results are risk indicators to
investigate, not conclusions.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json

import numpy as np
import pandas as pd

import common as C

P = C.PARAMETERS
FACTOR = P["annualisation_factor"]


# ---------------------------------------------------------------- helpers
def by_tag_counts(tags: pd.Series, pence: pd.Series) -> dict:
    out = {t: {"count": 0, "pence": 0} for t in C.TAGS}
    for t, p in zip(tags, pence):
        out[t]["count"] += 1
        out[t]["pence"] += int(p)
    return out


def by_tag_json(bt: dict) -> dict:
    return {t: {"count": v["count"], "total": C.gbp(v["pence"])} for t, v in bt.items()}


def majority_tag(tag_pence: dict) -> str:
    """Tag holding most £; ties go to the earlier tag rule."""
    order = {t: i for i, t in enumerate(C.TAGS)}
    return sorted(tag_pence.items(), key=lambda kv: (-kv[1], order[kv[0]]))[0][0]


def tag_split_text(tag_pence: dict, tag_rows: dict) -> str:
    if len(tag_pence) < 2:
        return ""
    items = sorted(tag_pence.items(), key=lambda kv: -kv[1])
    return "; ".join(f"{t} £{C.gbp(p):,.2f} ({tag_rows[t]} rows)" for t, p in items)


def group_tag(rows: pd.DataFrame) -> tuple[str, str]:
    tp = rows.groupby("spend_tag")["net_pence"].sum().to_dict()
    tr = rows.groupby("spend_tag").size().to_dict()
    return majority_tag(tp), tag_split_text(tp, tr)


def params_for(*keys) -> dict:
    return {k: P[k] for k in keys}


def candidates_for(name: str, pool: list[str]) -> list[tuple[str, str, float]]:
    """Non-exact candidate notice names: difflib ratio >= cutoff, or containment
    with both names at least the minimum length. Never a match."""
    out = []
    mn = P["candidate_containment_min_chars"]
    for b in pool:
        if b == name:
            continue
        sm = difflib.SequenceMatcher(None, name, b)
        r = sm.ratio()
        methods = []
        if r >= P["candidate_ratio_cutoff"]:
            methods.append(f"difflib ratio {r:.3f}")
        if len(name) >= mn and len(b) >= mn and (name in b or b in name):
            methods.append("containment")
        if methods:
            out.append((b, " + ".join(methods), r))
    out.sort(key=lambda x: -x[2])
    return out


def write_csv(df: pd.DataFrame, name: str) -> str:
    path = C.FULL / f"{name}.csv"
    df.to_csv(path, index=False)
    return C.rel(path)


def money_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        df[c.replace("_pence", "")] = df[c].map(C.gbp)
    return df.drop(columns=cols)


# ---------------------------------------------------------------- main
def main():
    C.check_inputs()
    rd = C.load_rules()
    TH = C.derive_thresholds(rd)
    run_th = [t for t in TH["thresholds"] if t["status"] == "run"]
    sp = C.read_spend_clean()
    ns = C.read_notice_suppliers()
    window = C.spend_window(sp["date"])
    w_start = pd.Timestamp(window["start"])
    rules_by_clause = {}
    for r in rd["rules"]:
        rules_by_clause.setdefault(r["clause"], []).append(r["rule_id"])
    anti_avoid = [r["rule_id"] for r in rd["rules"] if r["type"] == "anti-avoidance"]

    named = sp[~sp["redacted"]].copy()
    red = sp[sp["redacted"]]
    tests, lists_ids = {}, {}

    # ---- supplier table (named rows only)
    g = named.groupby("supplier_norm")
    supp = pd.DataFrame({"rows": g.size(), "total_pence": g["net_pence"].sum()})
    supp["annualised_pence"] = supp["total_pence"] * FACTOR
    tp = named.groupby(["supplier_norm", "spend_tag"])["net_pence"].sum()
    tr = named.groupby(["supplier_norm", "spend_tag"]).size()
    tags, splits = {}, {}
    for s in supp.index:
        d = tp.loc[s].to_dict()
        tags[s] = majority_tag(d)
        splits[s] = tag_split_text(d, tr.loc[s].to_dict())
    supp["spend_tag"] = pd.Series(tags)
    supp["tag_split"] = pd.Series(splits)
    svc = named.groupby(["supplier_norm", "service"])["net_pence"].sum().reset_index()
    supp["top_services"] = (svc.sort_values("net_pence", ascending=False)
                            .groupby("supplier_norm")
                            .apply(lambda x: "; ".join(f"{a} (£{C.gbp(b):,.2f})" for a, b in
                                                       zip(x["service"].head(3), x["net_pence"].head(3))),
                                   include_groups=False))
    supp["raw_names"] = named.groupby("supplier_norm")["supplier_name"].agg(
        lambda x: "; ".join(sorted(set(x))))
    supp["transaction_ids"] = g["transaction_id"].agg(lambda x: ";".join(x))
    supp = supp.sort_values("total_pence", ascending=False)

    # notice pools
    active_ns = ns[ns["active"]]
    all_names = sorted(ns["supplier_norm"].unique())
    active_names = sorted(active_ns["supplier_norm"].unique())

    # ================================================================ Test 1
    t1_rows, t1_by_th = [], []
    for t in run_th:
        T, inc = t["value"], t["inclusive"]
        lo, hi = C.band_edges_pence(T, P["clustering_band_width"])[0], \
            C.band_edges_pence(T, P["comparison_band_width"])[1]
        tp_ = T * 100
        p = sp["net_pence"]
        if inc:
            below_m = (p >= lo) & (p < tp_)
            comp_m = (p >= tp_) & (p < hi)
            bands = (f"[{lo/100:.2f}, {T})", f"[{T}, {hi/100:.2f})")
        else:
            below_m = (p >= lo) & (p <= tp_)
            comp_m = (p > tp_) & (p <= hi)
            bands = (f"[{lo/100:.2f}, {T}]", f"({T}, {hi/100:.2f}]")
        b, c = sp[below_m], sp[comp_m]
        sup_lbl = b["supplier_norm"].where(~b["redacted"], "(Redacted)")
        t1_by_th.append({
            "threshold": T, "inclusive": inc, "rule_ids": t["rule_ids"], "scopes": t["scopes"],
            "band_below": bands[0], "band_comparison": bands[1],
            "below": {"count": len(b), "total": C.gbp(b["net_pence"].sum()),
                      "by_tag": by_tag_json(by_tag_counts(b["spend_tag"], b["net_pence"]))},
            "comparison": {"count": len(c), "total": C.gbp(c["net_pence"].sum()),
                           "by_tag": by_tag_json(by_tag_counts(c["spend_tag"], c["net_pence"]))},
            "below_top_services_by_count": b["service"].value_counts().head(5).to_dict(),
            "below_top_suppliers_by_count": sup_lbl.value_counts().head(5).to_dict(),
            "_bt_below": by_tag_counts(b["spend_tag"], b["net_pence"]),
            "_bt_comp": by_tag_counts(c["spend_tag"], c["net_pence"]),
            "_below_pence": int(b["net_pence"].sum()), "_comp_pence": int(c["net_pence"].sum()),
        })
        for band, d in (("below", b), ("comparison", c)):
            x = d[["transaction_id", "date", "net_pence", "service", "supplier_name",
                   "supplier_norm", "spend_tag", "redacted"]].copy()
            x.insert(0, "band", band)
            x.insert(0, "threshold", T)
            t1_rows.append(x)
    t1 = pd.concat(t1_rows, ignore_index=True) if t1_rows else pd.DataFrame()
    if len(t1):
        t1 = t1.sort_values(["net_pence", "transaction_id"], ascending=[False, True])
        t1["date"] = t1["date"].dt.strftime("%Y-%m-%d")
    t1_below = t1[t1["band"] == "below"] if len(t1) else t1
    bt1 = by_tag_counts(t1_below["spend_tag"], t1_below["net_pence"]) if len(t1) else \
        by_tag_counts([], [])
    lists_ids["threshold_clustering"] = set(t1["transaction_id"]) if len(t1) else set()
    tests["threshold_clustering"] = {
        "status": "run" if run_th else "not run: no threshold could be run",
        "description": "Payments in the band just below each threshold, beside the comparison "
                       "band just above it: a risk indicator to investigate, not a conclusion.",
        "population": "all clean rows, Redacted included",
        "rule_ids": sorted({i for t in run_th for i in t["rule_ids"]}),
        "parameters": params_for("clustering_band_width", "comparison_band_width"),
        "thresholds_not_run": [{"value": t["value"], "rule_ids": t["rule_ids"], "status": t["status"]}
                               for t in TH["thresholds"] if t["status"] != "run"],
        "counts": {"below_band_payments": int(len(t1_below)),
                   "comparison_band_payments": int((t1["band"] == "comparison").sum()) if len(t1) else 0},
        "totals": {"flagged": C.gbp(sum(x["_below_pence"] for x in t1_by_th)),
                   "comparison_band": C.gbp(sum(x["_comp_pence"] for x in t1_by_th))},
        "flagged_definition": "payments in the band below T, summed over thresholds run",
        "by_tag": by_tag_json(bt1),
        "by_threshold": [{k: v for k, v in x.items() if not k.startswith("_")} for x in t1_by_th],
        "top20": [{"transaction_id": r.transaction_id, "threshold": int(r.threshold),
                   "date": r.date, "amount": C.gbp(r.net_pence), "service": r.service,
                   "supplier": r.supplier_norm if not r.redacted else "(Redacted)",
                   "spend_tag": r.spend_tag}
                  for r in t1_below.head(20).itertuples()] if len(t1) else [],
        "full_list": write_csv(money_cols(t1, ["net_pence"]) if len(t1) else t1, "threshold_clustering"),
    }

    # ================================================================ Test 2
    day0 = named["date"].min()
    split_groups = []
    for t in run_th:
        T, inc = t["value"], t["inclusive"]
        cand = named[C.below(named["net_pence"], T, inc)].sort_values(
            ["supplier_norm", "date", "transaction_id"])
        for s, rows in cand.groupby("supplier_norm", sort=False):
            if len(rows) < 2:
                continue
            d = ((rows["date"] - day0).dt.days).to_numpy()
            pz = rows["net_pence"].to_numpy()
            ids = rows["transaction_id"].to_numpy()
            cs = np.concatenate([[0], np.cumsum(pz)])
            wins = []
            j = 0
            for i in range(len(rows)):
                if j < i:
                    j = i
                while j + 1 < len(rows) and d[j + 1] - d[i] <= P["split_window_days"]:
                    j += 1
                if j > i and C.at_or_above(int(cs[j + 1] - cs[i]), T, inc):
                    wins.append((i, j))
            merged = []
            for (i, j) in wins:
                if merged and i <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], j)
                    merged[-1][2].append((i, j))
                else:
                    merged.append([i, j, [(i, j)]])
            for (i, j, ws) in merged:
                best = max(ws, key=lambda w: (int(cs[w[1] + 1] - cs[w[0]]), -w[0]))
                sub = rows.iloc[i:j + 1]
                gt, gs = group_tag(sub)
                split_groups.append({
                    "threshold": T, "supplier_norm": s, "rows": j - i + 1,
                    "first_date": sub["date"].min().strftime("%Y-%m-%d"),
                    "last_date": sub["date"].max().strftime("%Y-%m-%d"),
                    "span_days": int(d[j] - d[i]),
                    "total_pence": int(cs[j + 1] - cs[i]),
                    "max_single_pence": int(pz[i:j + 1].max()),
                    "windows_merged": len(ws),
                    "best_window_ids": ";".join(ids[best[0]:best[1] + 1]),
                    "best_window_rows": int(best[1] - best[0] + 1),
                    "best_window_first_date": sub["date"].iloc[best[0] - i].strftime("%Y-%m-%d"),
                    "best_window_last_date": sub["date"].iloc[best[1] - i].strftime("%Y-%m-%d"),
                    "best_window_span_days": int(d[best[1]] - d[best[0]]),
                    "best_window_total_pence": int(cs[best[1] + 1] - cs[best[0]]),
                    "spend_tag": gt, "tag_split": gs,
                    "services": "; ".join(sub["service"].value_counts().index[:3]),
                    "transaction_ids": ";".join(ids[i:j + 1]),
                    "dates": ";".join(sub["date"].dt.strftime("%Y-%m-%d")),
                })
    t2 = pd.DataFrame(split_groups)
    if len(t2):
        t2 = t2.sort_values(["total_pence", "threshold", "supplier_norm"], ascending=[False, True, True])
    t2_by_th = []
    for t in run_th:
        x = t2[t2["threshold"] == t["value"]] if len(t2) else t2
        bt = by_tag_counts(x["spend_tag"], x["total_pence"]) if len(x) else by_tag_counts([], [])
        t2_by_th.append({"threshold": t["value"], "inclusive": t["inclusive"], "rule_ids": t["rule_ids"],
                         "groups": int(len(x)),
                         "suppliers": int(x["supplier_norm"].nunique()) if len(x) else 0,
                         "rows": int(x["rows"].sum()) if len(x) else 0,
                         "total": C.gbp(x["total_pence"].sum()) if len(x) else 0.0,
                         "by_tag": by_tag_json(bt), "_bt": bt,
                         "_pence": int(x["total_pence"].sum()) if len(x) else 0})
    bt2 = by_tag_counts(t2["spend_tag"], t2["total_pence"]) if len(t2) else by_tag_counts([], [])
    lists_ids["split_purchases"] = set(";".join(t2["transaction_ids"]).split(";")) if len(t2) else set()
    tests["split_purchases"] = {
        "status": "run" if run_th else "not run: no threshold could be run",
        "description": "Same normalised supplier, two or more payments each under T within the "
                       "window whose combined total reaches T: an indicator of possible split "
                       "purchases to investigate. Overlapping windows are merged into one group, "
                       "so a group's full span can exceed the window; best_window_* gives the "
                       "highest-total single window inside the group. A group is every payment "
                       "under T to that supplier dated first_date..last_date; full transaction "
                       "ids are in the CSV.",
        "population": "named rows (Redacted left out)",
        "rule_ids": sorted(set(anti_avoid) | {i for t in run_th for i in t["rule_ids"]}),
        "parameters": params_for("split_window_days"),
        "thresholds_not_run": tests["threshold_clustering"]["thresholds_not_run"],
        "counts": {"groups": int(len(t2)),
                   "rows": int(t2["rows"].sum()) if len(t2) else 0},
        "totals": {"flagged": C.gbp(t2["total_pence"].sum()) if len(t2) else 0.0},
        "flagged_definition": "group totals summed over thresholds run; a payment can sit in "
                              "groups for more than one threshold",
        "by_tag": by_tag_json(bt2),
        "by_threshold": [{k: v for k, v in x.items() if not k.startswith("_")} for x in t2_by_th],
        "top20": [{"threshold": int(r.threshold), "supplier": r.supplier_norm, "rows": int(r.rows),
                   "first_date": r.first_date, "last_date": r.last_date, "span_days": int(r.span_days),
                   "total": C.gbp(r.total_pence), "spend_tag": r.spend_tag,
                   "best_window_first_date": r.best_window_first_date,
                   "best_window_last_date": r.best_window_last_date,
                   "best_window_rows": int(r.best_window_rows),
                   "best_window_span_days": int(r.best_window_span_days),
                   "best_window_total": C.gbp(r.best_window_total_pence),
                   "transaction_ids_count": len(r.transaction_ids.split(";")),
                   "transaction_ids_first10": r.transaction_ids.split(";")[:10]}
                  for r in t2.head(20).itertuples()] if len(t2) else [],
        "full_list": write_csv(money_cols(t2, ["total_pence", "max_single_pence",
                                              "best_window_total_pence"]) if len(t2) else t2,
                               "split_purchases"),
    }

    # ================================================================ Test 3
    tender = TH["named"]["tender_publication"]
    tested = supp[C.at_or_above(supp["annualised_pence"], tender["value"], tender["inclusive"])].copy()

    def classify(sname: str, pool_df: pd.DataFrame, pool_names: list[str]):
        ex = pool_df[pool_df["supplier_norm"] == sname]
        if len(ex):
            return "exact match", ";".join(sorted(ex["notice_id"].unique())), "", ""
        cands = candidates_for(sname, pool_names)
        if cands:
            return ("candidate", "", cands[0][0], cands[0][1] +
                    (f" (+{len(cands) - 1} more)" if len(cands) > 1 else ""))
        return "no published notice found", "", "", ""

    cls = {s: classify(s, active_ns, active_names) for s in tested.index}
    cls_all = {s: classify(s, ns, all_names) for s in tested.index}
    tested["class_active"] = [cls[s][0] for s in tested.index]
    tested["exact_notice_ids_active"] = [cls[s][1] for s in tested.index]
    tested["candidate_notice_supplier"] = [cls[s][2] for s in tested.index]
    tested["candidate_method"] = [cls[s][3] for s in tested.index]
    tested["class_all_notices"] = [cls_all[s][0] for s in tested.index]
    tested["exact_notice_ids_all"] = [cls_all[s][1] for s in tested.index]
    tested["candidate_notice_supplier_all"] = [cls_all[s][2] for s in tested.index]
    classes = ["exact match", "candidate", "no published notice found"]
    tot_tested = int(tested["total_pence"].sum())

    def class_summary(col):
        out = {}
        for k in classes:
            x = tested[tested[col] == k]
            out[k] = {"suppliers": int(len(x)), "three_month_total": C.gbp(x["total_pence"].sum()),
                      "annualised_estimate": C.gbp(x["annualised_pence"].sum()),
                      "share_of_tested_three_month_total_pct":
                          round(100 * int(x["total_pence"].sum()) / tot_tested, 1) if tot_tested else 0.0}
        return out

    npnf = tested[tested["class_active"] == "no published notice found"]
    bt3 = by_tag_counts(npnf["spend_tag"], npnf["total_pence"])
    t3 = tested.reset_index().rename(columns={"index": "supplier_norm"})
    t3 = t3[["supplier_norm", "class_active", "candidate_notice_supplier", "candidate_method",
             "exact_notice_ids_active", "class_all_notices", "exact_notice_ids_all",
             "candidate_notice_supplier_all", "spend_tag", "tag_split", "rows", "total_pence",
             "annualised_pence", "top_services", "raw_names", "transaction_ids"]]
    lists_ids["no_published_notice"] = set(";".join(t3["transaction_ids"]).split(";")) if len(t3) else set()
    tests["no_published_notice"] = {
        "status": "run",
        "label": "no published notice found",
        "description": "A list of suppliers to request contract evidence for, not a finding. "
                       "Suppliers whose annualised estimate (3-month total x 4) is at or above "
                       "the tender/publication threshold and whose normalised name has no exact "
                       "match among active Contracts Finder notices. The council's contracts "
                       "register is not an input. Contracts Finder lists only contracts above "
                       "about £25k, so suppliers below the threshold are never tested and never "
                       "listed. A candidate is a possible name match for the auditor to confirm; "
                       "it is never treated as a match.",
        "population": "named suppliers (Redacted left out)",
        "rule_ids": tender["rule_ids"],
        "threshold": tender,
        "parameters": params_for("annualisation_factor", "candidate_ratio_cutoff",
                                 "candidate_containment_min_chars"),
        "companies_house_matching": "spend data carries no Companies House numbers; matching is by "
                                    "normalised name only",
        "counts": {"suppliers_tested": int(len(tested)),
                   **{k: int((tested["class_active"] == k).sum()) for k in classes}},
        "totals": {"tested_three_month_total": C.gbp(tot_tested),
                   "flagged": C.gbp(npnf["total_pence"].sum()),
                   "flagged_annualised_estimate": C.gbp(npnf["annualised_pence"].sum())},
        "flagged_definition": "suppliers classed 'no published notice found' against active "
                              "notices; totals are 3-month £",
        "by_class_active_notices": class_summary("class_active"),
        "by_class_all_notices": class_summary("class_all_notices"),
        "by_tag": by_tag_json(bt3),
        "top20": [{"supplier": r.supplier_norm, "rows": int(r.rows),
                   "three_month_total": C.gbp(r.total_pence),
                   "annualised_estimate": C.gbp(r.annualised_pence), "spend_tag": r.spend_tag,
                   "tag_split": r.tag_split, "class_all_notices": r.class_all_notices}
                  for r in t3[t3["class_active"] == "no published notice found"].head(20).itertuples()],
        "top20_candidates": [{"supplier": r.supplier_norm, "candidate_notice_supplier":
                              r.candidate_notice_supplier, "method": r.candidate_method,
                              "three_month_total": C.gbp(r.total_pence)}
                             for r in t3[t3["class_active"] == "candidate"].head(20).itertuples()],
        "full_list": write_csv(money_cols(t3, ["total_pence", "annualised_pence"]),
                               "no_published_notice"),
    }

    # ================================================================ Test 4
    dup_groups = []
    for (s, amt), rows in named.sort_values(["date", "transaction_id"]).groupby(
            ["supplier_norm", "net_pence"], sort=False):
        if len(rows) < 2:
            continue
        rows = rows.sort_values(["date", "transaction_id"])
        d = rows["date"].to_numpy()
        gaps = np.diff(d).astype("timedelta64[D]").astype(int)
        comp = np.concatenate([[0], np.cumsum(gaps > P["duplicate_window_days"])])
        for _, sub in rows.groupby(comp):
            if len(sub) < 2:
                continue
            gt, gs = group_tag(sub)
            dup_groups.append({
                "supplier_norm": s, "amount_pence": int(amt), "rows": len(sub),
                "first_date": sub["date"].min().strftime("%Y-%m-%d"),
                "last_date": sub["date"].max().strftime("%Y-%m-%d"),
                "span_days": int((sub["date"].max() - sub["date"].min()).days),
                "total_pence": int(sub["net_pence"].sum()),
                "repeat_value_pence": int(sub["net_pence"].sum() - amt),
                "spend_tag": gt, "tag_split": gs,
                "services": "; ".join(sub["service"].unique()[:3]),
                "narratives": "; ".join(sub["narrative"].unique()[:3]),
                "transaction_ids": ";".join(sub["transaction_id"]),
                "dates": ";".join(sub["date"].dt.strftime("%Y-%m-%d")),
            })
    t4 = pd.DataFrame(dup_groups)
    if len(t4):
        t4 = t4.sort_values(["total_pence", "supplier_norm"], ascending=[False, True])
    bt4 = by_tag_counts(t4["spend_tag"], t4["total_pence"]) if len(t4) else by_tag_counts([], [])
    lists_ids["duplicates"] = set(";".join(t4["transaction_ids"]).split(";")) if len(t4) else set()
    tests["duplicates"] = {
        "status": "run",
        "description": "Same normalised supplier, same Net amount to the penny, each payment no "
                       "more than the window apart from the next (connected rows grouped): "
                       "possible duplicate payments to investigate. Regular fixed-fee payments "
                       "(e.g. weekly placements) also produce this pattern.",
        "population": "named rows (Redacted left out)",
        "rule_ids": [],
        "parameters": params_for("duplicate_window_days"),
        "counts": {"groups": int(len(t4)), "rows": int(t4["rows"].sum()) if len(t4) else 0},
        "totals": {"flagged": C.gbp(t4["total_pence"].sum()) if len(t4) else 0.0,
                   "repeat_value": C.gbp(t4["repeat_value_pence"].sum()) if len(t4) else 0.0},
        "flagged_definition": "group totals (all rows in each group); repeat_value = total less "
                              "one payment per group",
        "by_tag": by_tag_json(bt4),
        "top20": [{"supplier": r.supplier_norm, "amount": C.gbp(r.amount_pence), "rows": int(r.rows),
                   "first_date": r.first_date, "last_date": r.last_date,
                   "total": C.gbp(r.total_pence), "spend_tag": r.spend_tag,
                   "transaction_ids": r.transaction_ids.split(";")}
                  for r in t4.head(20).itertuples()] if len(t4) else [],
        "full_list": write_csv(money_cols(t4, ["amount_pence", "total_pence", "repeat_value_pence"])
                               if len(t4) else t4, "duplicates"),
    }

    # ================================================================ Test 5
    exp_rows, exp_cand = [], []
    ns_by_name = {k: v for k, v in ns.groupby("supplier_norm")}
    for s in supp.index:
        if s in ns_by_name:
            m = ns_by_name[s]
            ends = m.drop_duplicates("notice_id")["end_date"]
            if ends.notna().all() and (ends < w_start).all():
                exp_rows.append({"supplier_norm": s, "notices": ";".join(sorted(m["notice_id"].unique())),
                                 "n_notices": int(m["notice_id"].nunique()),
                                 "latest_notice_end": ends.max().strftime("%Y-%m-%d")})
        else:
            cands = candidates_for(s, all_names)
            if cands:
                cn = ns[ns["supplier_norm"].isin([c[0] for c in cands])].drop_duplicates("notice_id")
                if cn["end_date"].notna().all() and (cn["end_date"] < w_start).all():
                    exp_cand.append({"supplier_norm": s, "candidate_notice_supplier": cands[0][0],
                                     "candidate_method": cands[0][1],
                                     "candidate_notices": ";".join(sorted(cn["notice_id"])),
                                     "latest_candidate_notice_end": cn["end_date"].max().strftime("%Y-%m-%d")})

    def attach(df):
        if not len(df):
            return df
        cols = ["rows", "total_pence", "annualised_pence", "spend_tag", "tag_split",
                "top_services", "transaction_ids"]
        df = df.join(supp[cols], on="supplier_norm")
        return df.sort_values(["total_pence", "supplier_norm"], ascending=[False, True])

    t5 = attach(pd.DataFrame(exp_rows))
    t5c = attach(pd.DataFrame(exp_cand))
    bt5 = by_tag_counts(t5["spend_tag"], t5["total_pence"]) if len(t5) else by_tag_counts([], [])
    lists_ids["expired_notice_spend"] = set(";".join(t5["transaction_ids"]).split(";")) if len(t5) else set()
    lists_ids["expired_notice_spend_candidates"] = \
        set(";".join(t5c["transaction_ids"]).split(";")) if len(t5c) else set()
    tests["expired_notice_spend"] = {
        "status": "run",
        "description": "Suppliers paid in the window whose every exact-match notice ended before "
                       "the window start: an indicator of spend after expiry without an approved "
                       "extension (App C row D) to investigate; a newer contract may exist with no "
                       "notice. Candidate-only name matches are listed separately and are never "
                       "treated as matches.",
        "population": "named suppliers (Redacted left out), any amount",
        "rule_ids": rules_by_clause.get("AppC-D", []),
        "parameters": params_for("candidate_ratio_cutoff", "candidate_containment_min_chars"),
        "counts": {"suppliers": int(len(t5)), "candidate_only_suppliers": int(len(t5c))},
        "totals": {"flagged": C.gbp(t5["total_pence"].sum()) if len(t5) else 0.0,
                   "flagged_annualised_estimate": C.gbp(t5["annualised_pence"].sum()) if len(t5) else 0.0,
                   "candidate_only_three_month_total": C.gbp(t5c["total_pence"].sum()) if len(t5c) else 0.0},
        "flagged_definition": "exact-match suppliers; 3-month £",
        "by_tag": by_tag_json(bt5),
        "top20": [{"supplier": r.supplier_norm, "notices": r.notices.split(";"),
                   "latest_notice_end": r.latest_notice_end, "rows": int(r.rows),
                   "three_month_total": C.gbp(r.total_pence), "spend_tag": r.spend_tag}
                  for r in t5.head(20).itertuples()] if len(t5) else [],
        "full_list": write_csv(money_cols(t5, ["total_pence", "annualised_pence"]) if len(t5) else t5,
                               "expired_notice_spend"),
        "candidates_list": write_csv(money_cols(t5c, ["total_pence", "annualised_pence"])
                                     if len(t5c) else t5c, "expired_notice_spend_candidates"),
    }

    # ================================================================ Test 6
    sva, skips = [], {"more_than_one_active_exact_notice": 0, "multi_supplier_notice": 0,
                      "awarded_value_not_positive": 0, "no_end_date": 0,
                      "contract_years_not_positive": 0}
    act_by_name = {k: v for k, v in active_ns.groupby("supplier_norm")}
    for s in supp.index:
        if s not in act_by_name:
            continue
        m = act_by_name[s].drop_duplicates("notice_id")
        if len(m) != 1:
            skips["more_than_one_active_exact_notice"] += 1
            continue
        n = m.iloc[0]
        if n["n_blocks"] != 1:
            skips["multi_supplier_notice"] += 1
            continue
        if not n["awarded_value"] > 0:
            skips["awarded_value_not_positive"] += 1
            continue
        if pd.isna(n["end_date"]):
            skips["no_end_date"] += 1
            continue
        days = (n["end_date"] - n["start_date"]).days
        years = days / P["days_per_contract_year"]
        if years <= 0:
            skips["contract_years_not_positive"] += 1
            continue
        ann = int(supp.at[s, "annualised_pence"]) / 100
        annual_award = float(n["awarded_value"]) / years
        ratio = ann / annual_award
        sva.append({"supplier_norm": s, "notice_id": n["notice_id"],
                    "awarded_value": float(n["awarded_value"]),
                    "start_date": n["start_date"].strftime("%Y-%m-%d"),
                    "end_date": n["end_date"].strftime("%Y-%m-%d"),
                    "contract_days": int(days), "contract_years": years,
                    "award_per_year": annual_award, "ratio": ratio,
                    "flag": ratio >= P["award_ratio_flag"]})
    t6 = attach(pd.DataFrame(sva))
    if len(t6):
        t6 = t6.sort_values(["total_pence", "supplier_norm"], ascending=[False, True])
    t6f = t6[t6["flag"]] if len(t6) else t6
    bt6 = by_tag_counts(t6f["spend_tag"], t6f["total_pence"]) if len(t6f) else by_tag_counts([], [])
    lists_ids["spend_vs_award"] = set(";".join(t6["transaction_ids"]).split(";")) if len(t6) else set()
    tests["spend_vs_award"] = {
        "status": "run",
        "description": "Suppliers with exactly one exact-match active single-supplier notice with "
                       "Awarded Value > 0: ratio = annualised estimate / (Awarded Value / contract "
                       "years). A ratio at or above the flag is an indicator of spend beyond the "
                       "award without an approved variation (App C row E) to investigate; award "
                       "values may be estimates or maxima.",
        "population": "named suppliers (Redacted left out)",
        "rule_ids": rules_by_clause.get("AppC-E", []),
        "parameters": params_for("annualisation_factor", "days_per_contract_year", "award_ratio_flag"),
        "counts": {"suppliers_evaluated": int(len(t6)), "flagged": int(len(t6f)), "skipped": skips},
        "totals": {"flagged": C.gbp(t6f["total_pence"].sum()) if len(t6f) else 0.0,
                   "flagged_annualised_estimate": C.gbp(t6f["annualised_pence"].sum()) if len(t6f) else 0.0},
        "flagged_definition": "suppliers with ratio at or above award_ratio_flag; 3-month £",
        "by_tag": by_tag_json(bt6),
        "top20": [{"supplier": r.supplier_norm, "notice_id": r.notice_id,
                   "awarded_value": round(r.awarded_value, 2), "contract_years": round(r.contract_years, 4),
                   "annualised_estimate": C.gbp(r.annualised_pence), "ratio": round(r.ratio, 4),
                   "three_month_total": C.gbp(r.total_pence), "spend_tag": r.spend_tag}
                  for r in t6f.head(20).itertuples()] if len(t6f) else [],
        "full_list": write_csv(money_cols(t6, ["total_pence", "annualised_pence"]) if len(t6) else t6,
                               "spend_vs_award"),
    }

    # ================================================================ Test 7
    quote = TH["named"]["quote"]
    hv = supp[C.at_or_above(supp["annualised_pence"], quote["value"], quote["inclusive"])].copy()
    hv["no_published_notice_class"] = [
        cls[s][0] if s in cls else "not tested: below the tender/publication threshold" for s in hv.index]
    t7 = hv.reset_index().rename(columns={"index": "supplier_norm"})[
        ["supplier_norm", "spend_tag", "tag_split", "rows", "total_pence", "annualised_pence",
         "top_services", "no_published_notice_class", "raw_names", "transaction_ids"]]
    bt7 = by_tag_counts(t7["spend_tag"], t7["total_pence"])
    lists_ids["high_value_suppliers"] = set(";".join(t7["transaction_ids"]).split(";")) if len(t7) else set()
    tests["high_value_suppliers"] = {
        "status": "run",
        "description": "Every normalised supplier whose annualised estimate is at or above the quote "
                       "threshold, sorted by £: the population to request contract evidence for.",
        "population": "named suppliers (Redacted left out)",
        "rule_ids": quote["rule_ids"],
        "threshold": quote,
        "parameters": params_for("annualisation_factor"),
        "counts": {"suppliers": int(len(t7)),
                   "by_no_published_notice_class": t7["no_published_notice_class"].value_counts().to_dict()},
        "totals": {"flagged": C.gbp(t7["total_pence"].sum()),
                   "flagged_annualised_estimate": C.gbp(t7["annualised_pence"].sum()),
                   "share_of_named_three_month_total_pct":
                       round(100 * int(t7["total_pence"].sum()) / int(named["net_pence"].sum()), 1)},
        "flagged_definition": "all listed suppliers; 3-month £",
        "redacted_not_attributable": {"rows": int(len(red)), "net_total": C.gbp(red["net_pence"].sum()),
                                      "note": "Redacted £ cannot be attributed to a supplier"},
        "by_tag": by_tag_json(bt7),
        "top20": [{"supplier": r.supplier_norm, "spend_tag": r.spend_tag, "tag_split": r.tag_split,
                   "rows": int(r.rows), "three_month_total": C.gbp(r.total_pence),
                   "annualised_estimate": C.gbp(r.annualised_pence), "top_services": r.top_services,
                   "no_published_notice_class": r.no_published_notice_class}
                  for r in t7.head(20).itertuples()],
        "full_list": write_csv(money_cols(t7, ["total_pence", "annualised_pence"]), "high_value_suppliers"),
    }

    # ================================================================ reconciliation
    checks = []

    def check(name, ok, detail=""):
        checks.append({"name": name, "passed": bool(ok), **({"detail": detail} if detail else {})})

    excl = pd.read_csv(C.EXCLUSIONS_CSV, dtype={"transaction_id": str, "source_file": str},
                       keep_default_na=False)
    excl["removed_from_clean"] = excl["removed_from_clean"].astype(str) == "True"
    excl["net_pence"] = excl["net_pence"].astype("int64")
    removed = excl[excl["removed_from_clean"]]
    inputs_spend, raw_rows, raw_pence, outside_raw = [], 0, 0, 0
    for path in C.spend_files():
        df, h = C.read_workbook(path)
        amt = C.parse_net_amount(df["Net amount"], path)
        dts = C.parse_spend_dates(df["Date"], path).dt.normalize().dt.to_period("M")
        outside_raw += int((dts != dts.mode().iloc[0]).sum())
        pen = int((amt * 100).round().astype("int64").sum())
        raw_rows += len(df)
        raw_pence += pen
        cl = sp[sp["source_file"] == path.name]
        ex = removed[removed["source_file"] == path.name]
        check(f"file {path.name}: rows read = clean + excluded",
              len(df) == len(cl) + len(ex), f"{len(df)} = {len(cl)} + {len(ex)}")
        check(f"file {path.name}: net total read = clean + excluded",
              pen == int(cl["net_pence"].sum()) + int(ex["net_pence"].sum()))
        inputs_spend.append({"file": C.rel(path), "sha256": C.sha256(path), "header_row": h,
                             "rows": len(df), "net_total": C.gbp(pen)})
    check("clean rows = Redacted + named (count)", len(sp) == len(red) + len(named))
    check("clean rows = Redacted + named (£)",
          int(sp["net_pence"].sum()) == int(red["net_pence"].sum()) + int(named["net_pence"].sum()))
    bt_clean = by_tag_counts(sp["spend_tag"], sp["net_pence"])
    check("clean rows = sum over spend_tags (count)", sum(v["count"] for v in bt_clean.values()) == len(sp))
    check("clean rows = sum over spend_tags (£)",
          sum(v["pence"] for v in bt_clean.values()) == int(sp["net_pence"].sum()))
    check("each row has exactly one spend_tag in the five tags", sp["spend_tag"].isin(C.TAGS).all())

    def bt_ok(name, bt, count, pence):
        check(f"{name}: by_tag sums to total (count)", sum(v["count"] for v in bt.values()) == count,
              f"{sum(v['count'] for v in bt.values())} vs {count}")
        check(f"{name}: by_tag sums to total (£)", sum(v["pence"] for v in bt.values()) == pence)

    bt_ok("threshold_clustering", bt1, len(t1_below), sum(x["_below_pence"] for x in t1_by_th))
    for x in t1_by_th:
        bt_ok(f"threshold_clustering T={x['threshold']} below", x["_bt_below"], x["below"]["count"], x["_below_pence"])
        bt_ok(f"threshold_clustering T={x['threshold']} comparison", x["_bt_comp"], x["comparison"]["count"], x["_comp_pence"])
    bt_ok("split_purchases", bt2, len(t2), int(t2["total_pence"].sum()) if len(t2) else 0)
    for x in t2_by_th:
        bt_ok(f"split_purchases T={x['threshold']}", x["_bt"], x["groups"], x["_pence"])
    bt_ok("no_published_notice", bt3, len(npnf), int(npnf["total_pence"].sum()))
    bt_ok("duplicates", bt4, len(t4), int(t4["total_pence"].sum()) if len(t4) else 0)
    bt_ok("expired_notice_spend", bt5, len(t5), int(t5["total_pence"].sum()) if len(t5) else 0)
    bt_ok("spend_vs_award", bt6, len(t6f), int(t6f["total_pence"].sum()) if len(t6f) else 0)
    bt_ok("high_value_suppliers", bt7, len(t7), int(t7["total_pence"].sum()))
    check("no_published_notice classes sum to suppliers tested",
          sum(tests["no_published_notice"]["counts"][k] for k in classes) == len(tested))

    clean_ids = set(sp["transaction_id"])
    for k, ids in lists_ids.items():
        miss = ids - clean_ids
        check(f"{k}: every transaction id exists in spend-clean.csv", not miss,
              f"{len(miss)} missing" if miss else "")
    red_log = set(excl.loc[~excl["removed_from_clean"], "transaction_id"])
    check("exclusions.csv redacted entries exist in spend-clean.csv", red_log <= clean_ids)
    check("exclusions.csv redacted entries = Redacted rows in spend-clean.csv",
          red_log == set(red["transaction_id"]))
    check("excluded rows are not in spend-clean.csv", not (set(removed["transaction_id"]) & clean_ids))
    check("raw rows = clean + excluded (all files)", raw_rows == len(sp) + len(removed))
    check("raw £ = clean + excluded (all files)",
          raw_pence == int(sp["net_pence"].sum()) + int(removed["net_pence"].sum()))

    craw = C.read_contracts_raw()
    keep_mask = craw["Organisation Name"].map(C.org_kept)
    n_kept, n_drop = int(keep_mask.sum()), int((~keep_mask).sum())
    check("notice rows kept + dropped = rows read", n_kept + n_drop == len(craw))
    kept_ids = set(craw.loc[keep_mask & (craw[C.SUPPLIER_COL].str.strip() != ""), "Notice Identifier"])
    check("notice-suppliers.csv covers every kept notice with suppliers",
          set(ns["notice_id"]) == kept_ids)

    failed = [c for c in checks if not c["passed"]]
    if failed:
        C.stop(f"reconciliation failed: {failed[0]['name']} {failed[0].get('detail', '')}")

    # ================================================================ cleaning summary
    exc_summary = []
    for grp, narrs in C.EXCLUSIONS.items():
        for n in narrs:
            x = removed[removed["narrative"] == n]
            exc_summary.append({"group": grp, "narrative": n, "rows": int(len(x)),
                                "net_total": C.gbp(x["net_pence"].sum())})
    nl = pd.read_csv(C.NORMLOG_CSV, dtype=str, keep_default_na=False)
    norm_rules = []
    for rid, desc in C.NORM_RULES:
        cnt = {}
        for src in ("spend", "notices"):
            x = nl[nl["source"] == src]["rules_changed"].str.split(";")
            cnt[src] = int(x.map(lambda l: rid in l).sum())
        norm_rules.append({"rule": f"{rid}: {desc}", "spend_names_changed": cnt["spend"],
                           "notice_names_changed": cnt["notices"]})
    # rule 5, per payment tag: names changed and rows affected on each side
    payment_tags = []
    for tag in C.PAYMENT_TAGS:
        tid = "5:" + " ".join(tag)
        hit = nl[nl["rules_changed"].str.split(";").map(lambda l: tid in l)]
        sp_names = set(hit.loc[hit["source"] == "spend", "raw_name"])
        nt_names = set(hit.loc[hit["source"] == "notices", "raw_name"])
        payment_tags.append({
            "tag": " ".join(tag),
            "spend_names_changed": len(sp_names),
            "spend_rows_affected": int(named["supplier_name"].isin(sp_names).sum()),
            "notice_names_changed": len(nt_names),
            "notice_blocks_affected": int(ns["raw_name"].isin(nt_names).sum())})
    # possible further payment tags, for the human to decide (nothing removed)
    hints = []
    for src, df_names in (("spend", named.groupby("supplier_norm")["net_pence"].agg(["size", "sum"])),
                          ("notices", ns.groupby("supplier_norm").size().to_frame("size").assign(sum=0))):
        for nm, r in df_names.iterrows():
            toks = set(nm.split())
            if toks & C.PAYMENT_TAG_HINTS:
                hints.append({"source": src, "supplier_norm": nm,
                              "tokens": sorted(toks & C.PAYMENT_TAG_HINTS),
                              "rows": int(r["size"]), "net_total": C.gbp(r["sum"])})
    hints.sort(key=lambda h: -h["net_total"])
    red_svc = red.groupby("service")["net_pence"].sum().sort_values(ascending=False).head(5)

    ns_notice = ns.drop_duplicates("notice_id")

    analytics = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "scripts": C.SCRIPTS,
        "language_note": "All results are risk indicators to investigate, not findings or conclusions.",
        "parameters": P,
        "parameter_definitions": C.PARAMETER_DEFINITIONS,
        "inputs": {"rules": {"file": C.rel(C.RULES_JSON), "sha256": C.sha256(C.RULES_JSON)},
                   "spend": inputs_spend,
                   "contracts": {"file": C.rel(C.CONTRACTS_CSV), "sha256": C.sha256(C.CONTRACTS_CSV),
                                 "rows": int(len(craw))}},
        "window": {**window, "rows_dated_outside_file_month": outside_raw,
                   "rows_dated_outside_file_month_clean": int(sp["outside_file_month"].astype(str).eq("True").sum()),
                   "file_month_definition": "most common calendar month of the file's dates"},
        "cleaning": {
            "exclusions": exc_summary,
            "excluded_total": {"rows": int(len(removed)), "net_total": C.gbp(removed["net_pence"].sum())},
            "redacted": {"rows": int(len(red)), "net_total": C.gbp(red["net_pence"].sum()),
                         "by_service_top5": {k: C.gbp(v) for k, v in red_svc.items()}},
            "spend_tags": [{"tag": t, "rule": rn, "rows": bt_clean[t]["count"],
                            "net_total": C.gbp(bt_clean[t]["pence"]),
                            "redacted_rows": int(red["spend_tag"].eq(t).sum())}
                           for rn, t, _ in C.TAG_RULES],
            "blank_expenditure_category_rows": int((sp["expenditure_category"] == "").sum()),
            "normalisation_rules": norm_rules,
            "payment_tags": payment_tags,
            "distinct_supplier_names": {"spend_raw": int(named["supplier_name"].nunique()),
                                        "spend_normalised": int(named["supplier_norm"].nunique()),
                                        "notices_raw": int(ns["raw_name"].nunique()),
                                        "notices_normalised": int(ns["supplier_norm"].nunique())},
            "possible_payment_tags_for_review": {"count": len(hints), "top20": hints[:20]},
        },
        "contracts": {
            "rows": int(len(craw)), "kept": n_kept, "dropped": n_drop,
            "dropped_top_orgs": craw.loc[~keep_mask, "Organisation Name"].value_counts().head(10).to_dict(),
            "supplier_blocks": int(len(ns)),
            "ref_types": ns["ref_type"].value_counts().to_dict(),
            "companies_house_numbers": int((ns["ch_number"] != "").sum()),
            "active_notices": int(ns_notice["active"].sum()),
            "active_supplier_blocks": int(ns["active"].sum()),
            "awarded_value_zero_notices": int((ns_notice["awarded_value"] == 0).sum()),
            "date_columns_used": {"start": C.NOTICE_START_COL, "end": C.NOTICE_END_COL,
                                  "used_for": ["active in window", "expired_notice_spend",
                                               "spend_vs_award contract years"]},
            "active_definition": f"'{C.NOTICE_END_COL}' on or after window start (blank = active) "
                                 f"and '{C.NOTICE_START_COL}' on or before window end",
            "cap_warning": (f"{len(craw)} data rows: the export may have hit the 1,000-row cap"
                            if len(craw) >= P["export_cap_warning_rows"] else None),
        },
        "thresholds": TH["thresholds"],
        "publication_floor": TH["publication_floor"],
        "named_thresholds": TH["named"],
        "tests": tests,
        "reconciliation": {"raw_rows": raw_rows, "raw_net_total": C.gbp(raw_pence), "checks": checks},
    }
    with open(C.ANALYTICS_JSON, "w") as f:
        json.dump(analytics, f, indent=2, default=str)

    # ---- summary
    print(f"window {window['start']}..{window['end']}; raw rows {raw_rows} £{C.gbp(raw_pence):,.2f}")
    print(f"reconciliation: {len(checks)} checks passed")
    for k, v in tests.items():
        print(f"{k}: {v['status']}; counts {json.dumps(v['counts'])}; totals {json.dumps(v['totals'])}")
    for x in t1_by_th:
        print(f"  clustering T={x['threshold']}: below {x['below']['count']} £{x['below']['total']:,.2f} | "
              f"comparison {x['comparison']['count']} £{x['comparison']['total']:,.2f}")
    for x in t2_by_th:
        print(f"  split T={x['threshold']}: groups {x['groups']} suppliers {x['suppliers']} £{x['total']:,.2f}")
    print(f"possible payment tags for review: {len(hints)}")


if __name__ == "__main__":
    C.run_main(main)
