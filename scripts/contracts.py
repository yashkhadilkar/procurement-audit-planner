"""Step 2: parse the Contracts Finder notice export.

Writes outputs/analytics-full/notice-suppliers.csv (one row per notice x
supplier block) and adds the notice-side rows to normalisation-log.csv.
"""
from __future__ import annotations

import pandas as pd

import common as C


def parse_dates(s: pd.Series, fmt: str, label: str, allow_blank: bool, utc: bool = False) -> pd.Series:
    blank = s.str.strip() == ""
    if blank.any() and not allow_blank:
        C.stop(f"contracts.csv: {int(blank.sum())} blank '{label}' value(s)")
    try:
        out = pd.to_datetime(s.where(~blank, None), format=fmt, errors="raise", utc=utc)
    except (ValueError, TypeError) as e:
        C.stop(f"contracts.csv: '{label}' does not parse with format {fmt}: {e}")
    return out


def split_blocks(packed: str, notice_id: str) -> list[list[str]]:
    v = packed.strip()
    if not v:
        return []
    if not (v.startswith("[") and v.endswith("]")):
        C.stop(f"contracts.csv notice {notice_id}: supplier field not bracketed")
    blocks = [b.split("|") for b in v[1:-1].split("][")]
    for b in blocks:
        if len(b) != 6:
            C.stop(f"contracts.csv notice {notice_id}: supplier block has {len(b)} elements, not 6")
    return blocks


def main():
    C.check_inputs()
    spend = C.read_spend_clean()
    window = C.spend_window(spend["date"])
    w_start, w_end = pd.Timestamp(window["start"]), pd.Timestamp(window["end"])

    c = C.read_contracts_raw()
    need = ["Notice Identifier", "Organisation Name", C.NOTICE_START_COL, C.NOTICE_END_COL,
            "Awarded Date", "Published Date", "Awarded Value", C.SUPPLIER_COL]
    miss = [x for x in need if x not in c.columns]
    if miss:
        C.stop(f"contracts.csv: missing column(s) {miss}")
    n_read = len(c)
    keep = c["Organisation Name"].map(C.org_kept)
    kept, dropped = c[keep].copy(), c[~keep]
    if len(kept) + len(dropped) != n_read:
        C.stop("reconciliation failed: notices kept + dropped != read")

    # a notice's start/end are the Contract start date / Contract end date columns
    kept["start"] = parse_dates(kept[C.NOTICE_START_COL], C.CONTRACT_DATE_FMT,
                                C.NOTICE_START_COL, False)
    kept["end"] = parse_dates(kept[C.NOTICE_END_COL], C.CONTRACT_DATE_FMT, C.NOTICE_END_COL, True)
    kept["awarded"] = parse_dates(kept["Awarded Date"], C.CONTRACT_DATE_FMT, "Awarded Date", True)
    kept["published"] = parse_dates(kept["Published Date"], C.PUBLISHED_DATE_FMT,
                                    "Published Date", True, utc=True)
    av = pd.to_numeric(kept["Awarded Value"].str.strip(), errors="coerce")
    if av.isna().any():
        C.stop(f"contracts.csv: Awarded Value does not parse as a number "
               f"(first: {kept.loc[av.isna(), 'Awarded Value'].iloc[0]!r})")
    kept["awarded_value"] = av

    kept["active"] = (kept["end"].isna() | (kept["end"] >= w_start)) & (kept["start"] <= w_end)

    rows, norm_cache = [], {}
    for _, r in kept.iterrows():
        blocks = split_blocks(r[C.SUPPLIER_COL], r["Notice Identifier"])
        for i, b in enumerate(blocks, start=1):
            name = b[0].strip()
            if not name:
                C.stop(f"contracts.csv notice {r['Notice Identifier']}: blank supplier name in block {i}")
            if name not in norm_cache:
                norm_cache[name] = C.normalise_supplier(name)
            ref_type, ref_no = b[2].strip(), b[3].strip()
            rows.append({
                "notice_id": r["Notice Identifier"],
                "organisation": r["Organisation Name"],
                "title": r.get("Title", ""),
                "block_no": i, "n_blocks": len(blocks),
                "raw_name": name, "supplier_norm": norm_cache[name][0],
                "norm_rules": ";".join(norm_cache[name][1]),
                "ref_type": ref_type,
                "ch_number": ref_no if ref_type == "COMPANIES_HOUSE" and ref_no else "",
                "start_date": r["start"].strftime("%Y-%m-%d"),
                "end_date": "" if pd.isna(r["end"]) else r["end"].strftime("%Y-%m-%d"),
                "awarded_date": "" if pd.isna(r["awarded"]) else r["awarded"].strftime("%Y-%m-%d"),
                "published_utc": "" if pd.isna(r["published"]) else r["published"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "awarded_value": r["awarded_value"],
                "active": bool(r["active"]),
            })
    ns = pd.DataFrame(rows)
    blank_supplier_notices = int((kept[C.SUPPLIER_COL].str.strip() == "").sum())

    C.FULL.mkdir(parents=True, exist_ok=True)
    ns.to_csv(C.NOTICE_SUPPLIERS, index=False)
    nl = pd.DataFrame([{"source": "notices", "raw_name": n, "supplier_norm": v[0],
                        "rules_changed": ";".join(v[1]), "fallback": "6-fallback" in v[1]}
                       for n, v in sorted(norm_cache.items())]).astype(str)
    if C.NORMLOG_CSV.exists():
        old = pd.read_csv(C.NORMLOG_CSV, dtype=str, keep_default_na=False)
        nl = pd.concat([old[old["source"] != "notices"], nl], ignore_index=True)
    nl.to_csv(C.NORMLOG_CSV, index=False)

    print(f"contracts.csv rows {n_read}; kept {len(kept)}; dropped {len(dropped)}")
    print("  dropped orgs:", dropped["Organisation Name"].value_counts().head(5).to_dict())
    print(f"supplier blocks {len(ns)}; notices without supplier {blank_supplier_notices}; "
          f"ref types {ns['ref_type'].value_counts().to_dict()}")
    print(f"active notices {int(kept['active'].sum())} of {len(kept)} "
          f"(window {window['start']}..{window['end']}; dates from "
          f"'{C.NOTICE_START_COL}'/'{C.NOTICE_END_COL}')")
    print(f"Awarded Value 0: {int((kept['awarded_value'] == 0).sum())} notices")
    if n_read >= C.PARAMETERS["export_cap_warning_rows"]:
        print(f"WARNING: {n_read} data rows: export may have hit the 1,000-row cap")


if __name__ == "__main__":
    C.run_main(main)
