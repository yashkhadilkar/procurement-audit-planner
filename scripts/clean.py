"""Step 1: clean the spend workbooks.

Writes outputs/analytics-full/spend-clean.csv, exclusions.csv,
normalisation-log.csv (spend side) and tag-log.csv.
"""
from __future__ import annotations

import openpyxl
import pandas as pd

import common as C


def excel_row_numbers(path, header_row_pandas: int, n_rows: int, df: pd.DataFrame) -> list[int]:
    """Excel 1-based row numbers of the data rows, cross-checked against openpyxl."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[C.SHEET]
    want = set(C.EXPECTED_COLUMNS)
    header_excel = None
    rows = []
    col_idx = None
    for rnum, vals in enumerate(ws.iter_rows(min_row=1, values_only=True), start=1):
        if header_excel is None:
            names = [str(v).strip() if isinstance(v, str) else None for v in vals]
            if want <= set(n for n in names if n):
                header_excel = rnum
                col_idx = {n: i for i, n in enumerate(names) if n in want}
            elif rnum > C.HEADER_SEARCH_ROWS:
                break
            continue
        if any(v is not None and (not isinstance(v, str) or v.strip()) for v in vals):
            rows.append((rnum, vals[col_idx["Net amount"]], vals[col_idx["Supplier name"]]))
    wb.close()
    if header_excel is None:
        C.stop(f"{C.rel(path)}: openpyxl could not find the header row")
    if header_excel != header_row_pandas + 1:
        C.stop(f"{C.rel(path)}: header row mismatch (pandas {header_row_pandas}, Excel {header_excel})")
    if len(rows) != n_rows:
        C.stop(f"{C.rel(path)}: pandas read {n_rows} rows, openpyxl {len(rows)} non-empty rows")
    amounts = [r[1] for r in rows]
    names = [r[2] for r in rows]
    if [float(a) for a in amounts] != df["Net amount"].astype(float).tolist() or \
       names != df["Supplier name"].tolist():
        C.stop(f"{C.rel(path)}: row order differs between pandas and openpyxl")
    return [r[0] for r in rows]


def main():
    C.check_inputs()
    C.load_rules()  # presence/parse check only
    frames, file_info = [], []
    for path in C.spend_files():
        df, h = C.read_workbook(path)
        df["Net amount"] = C.parse_net_amount(df["Net amount"], path)
        df["Date"] = C.parse_spend_dates(df["Date"], path)
        for col in ("Service", "Narrative", "Supplier name"):
            blank = df[col].isna() | (df[col].astype(str).str.strip() == "")
            if blank.any():
                C.stop(f"{C.rel(path)}: {int(blank.sum())} blank '{col}' cell(s)")
        rows = excel_row_numbers(path, h, len(df), df)
        df["source_file"] = path.name
        df["excel_row"] = rows
        df["transaction_id"] = [f"{path.stem}:r{r}" for r in rows]
        df["date"] = df["Date"].dt.normalize()
        # file month = most common calendar month in the file
        per = df["date"].dt.to_period("M")
        file_month = per.mode().iloc[0]
        df["file_month"] = str(file_month)
        df["outside_file_month"] = per != file_month
        file_info.append({"file": C.rel(path), "header_row": h, "rows": len(df),
                          "net_total": round(float(df["Net amount"].sum()), 2),
                          "file_month": str(file_month),
                          "rows_dated_outside_file_month": int(df["outside_file_month"].sum())})
        frames.append(df)

    raw = pd.concat(frames, ignore_index=True)
    if raw["transaction_id"].duplicated().any():
        C.stop("duplicate transaction ids")
    raw["net_pence"] = (raw["Net amount"] * 100).round().astype("int64")
    window = C.spend_window(raw["date"])

    # exclusions by exact Narrative
    narr_group = {n: g for g, ns in C.EXCLUSIONS.items() for n in ns}
    raw["exclusion_group"] = raw["Narrative"].map(narr_group)
    excl = raw[raw["exclusion_group"].notna()]
    clean = raw[raw["exclusion_group"].isna()].copy()

    clean["redacted"] = clean["Supplier name"] == C.REDACTED_VALUE
    tags = [C.spend_tag(s, c, n) for s, c, n in
            zip(clean["Service"], clean["Expenditure category"], clean["Narrative"])]
    clean["spend_tag"] = [t for t, _ in tags]
    clean["tag_rule"] = [r for _, r in tags]

    norm_cache = {}
    for name in clean.loc[~clean["redacted"], "Supplier name"].unique():
        norm_cache[name] = C.normalise_supplier(name)
    clean["supplier_norm"] = [("" if red else norm_cache[n][0])
                              for n, red in zip(clean["Supplier name"], clean["redacted"])]

    out = pd.DataFrame({
        "transaction_id": clean["transaction_id"],
        "source_file": clean["source_file"],
        "excel_row": clean["excel_row"],
        "service": clean["Service"],
        "expenditure_category": clean["Expenditure category"].fillna(""),
        "narrative": clean["Narrative"],
        "datetime": clean["Date"].dt.strftime("%Y-%m-%dT%H:%M:%S.%f"),
        "date": clean["date"].dt.strftime("%Y-%m-%d"),
        "file_month": clean["file_month"],
        "outside_file_month": clean["outside_file_month"],
        "net_amount": clean["Net amount"],
        "net_pence": clean["net_pence"],
        "supplier_name": clean["Supplier name"],
        "supplier_norm": clean["supplier_norm"],
        "redacted": clean["redacted"],
        "spend_tag": clean["spend_tag"],
        "tag_rule": clean["tag_rule"],
    })

    ex_rows = pd.DataFrame({
        "transaction_id": excl["transaction_id"], "source_file": excl["source_file"],
        "reason_group": excl["exclusion_group"], "narrative": excl["Narrative"],
        "net_amount": excl["Net amount"], "net_pence": excl["net_pence"],
        "removed_from_clean": True})
    red = clean[clean["redacted"]]
    red_rows = pd.DataFrame({
        "transaction_id": red["transaction_id"], "source_file": red["source_file"],
        "reason_group": C.REDACTED_REASON, "narrative": red["Narrative"],
        "net_amount": red["Net amount"], "net_pence": red["net_pence"],
        "removed_from_clean": False})
    exclusions = pd.concat([ex_rows, red_rows], ignore_index=True)

    normlog = pd.DataFrame([{"source": "spend", "raw_name": n, "supplier_norm": v[0],
                             "rules_changed": ";".join(v[1]),
                             "fallback": "6-fallback" in v[1]}
                            for n, v in sorted(norm_cache.items())])

    # tag log: rows and £ per rule, plus top 10 narratives per tag
    tl = []
    for rule, tag, desc in C.TAG_RULES:
        sub = out[out["tag_rule"] == rule]
        tl.append({"kind": "rule", "rule": rule, "spend_tag": tag, "rule_text": desc,
                   "narrative": "", "rank": "", "rows": len(sub),
                   "net_total": C.gbp(sub["net_pence"].sum()),
                   "redacted_rows": int(sub["redacted"].sum())})
        top = (sub.groupby("narrative")["net_pence"].agg(["size", "sum"])
               .sort_values(["sum", "size"], ascending=False).head(10))
        for rank, (narr, r) in enumerate(top.iterrows(), start=1):
            tl.append({"kind": "top_narrative", "rule": rule, "spend_tag": tag, "rule_text": "",
                       "narrative": narr, "rank": rank, "rows": int(r["size"]),
                       "net_total": C.gbp(r["sum"]), "redacted_rows": ""})
    taglog = pd.DataFrame(tl)

    # in-script reconciliation before writing
    if len(out) + len(ex_rows) != len(raw) or \
       int(out["net_pence"].sum()) + int(ex_rows["net_pence"].sum()) != int(raw["net_pence"].sum()):
        C.stop("reconciliation failed: clean + excluded != raw")
    if taglog.loc[taglog["kind"] == "rule", "rows"].sum() != len(out):
        C.stop("reconciliation failed: tag rows != clean rows")

    C.FULL.mkdir(parents=True, exist_ok=True)
    out.to_csv(C.SPEND_CLEAN, index=False)
    exclusions.to_csv(C.EXCLUSIONS_CSV, index=False)
    # keep any notice-side log rows written by contracts.py
    if C.NORMLOG_CSV.exists():
        old = pd.read_csv(C.NORMLOG_CSV, dtype=str, keep_default_na=False)
        normlog = pd.concat([normlog.astype(str), old[old["source"] != "spend"]], ignore_index=True)
    normlog.to_csv(C.NORMLOG_CSV, index=False)
    taglog.to_csv(C.TAGLOG_CSV, index=False)

    # summary
    print(f"window {window['start']}..{window['end']} ({window['months']} months)")
    for fi in file_info:
        print(f"  {fi['file']}: header_row {fi['header_row']}, rows {fi['rows']}, "
              f"net £{fi['net_total']:,.2f}, outside file month {fi['rows_dated_outside_file_month']}")
    print(f"raw rows {len(raw)}  £{C.gbp(raw['net_pence'].sum()):,.2f}")
    for g in C.EXCLUSIONS:
        s = ex_rows[ex_rows["reason_group"] == g]
        print(f"excluded [{g}] rows {len(s)}  £{C.gbp(s['net_pence'].sum()):,.2f}")
    print(f"clean rows {len(out)}  £{C.gbp(out['net_pence'].sum()):,.2f}; redacted rows "
          f"{int(out['redacted'].sum())}  £{C.gbp(out.loc[out['redacted'], 'net_pence'].sum()):,.2f}")
    for r in tl:
        if r["kind"] == "rule":
            print(f"  tag {r['rule']} {r['spend_tag']}: rows {r['rows']}  £{r['net_total']:,.2f}")
    print(f"blank Expenditure category rows in clean data: "
          f"{int((out['expenditure_category'] == '').sum())}")
    print(f"distinct spend supplier names {len(norm_cache)} -> normalised "
          f"{len(set(v[0] for v in norm_cache.values()))}; fallbacks {int(normlog['fallback'].astype(str).eq('True').sum())}")


if __name__ == "__main__":
    C.run_main(main)
