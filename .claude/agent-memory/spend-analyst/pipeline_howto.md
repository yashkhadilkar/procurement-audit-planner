---
name: spend-pipeline-howto
description: How-to lessons for reading the WBC spend workbooks and Contracts Finder export with pandas 3 (dtypes, date parsing, row ids, JSON size)
metadata:
  type: feedback
---

Technical lessons from building scripts/clean.py, contracts.py, analytics.py, selfcheck.py.

- pandas 3 reads the spend `Date` column as datetime64[us] and text columns as StringDtype; `header=None` keeps leading blank rows, so the header-row index + 1 = Excel row. Cross-check Excel row numbers with openpyxl (`iter_rows(min_row=1, values_only=True)`) before building transaction ids.
- Spend Net amounts are whole pence: convert to integer pence (assert exactness) and do all sums/comparisons in pence, so threshold edges and penny-equal duplicates are exact.
- contracts.csv `Published Date` mixes `Z` and `+01:00`: `pd.to_datetime(format="%Y-%m-%dT%H:%M:%S%z", utc=True)`, otherwise pandas 3 raises on mixed offsets.
- contracts.csv has two date pairs (`Start Date`/`End Date` and `Contract start date`/`Contract end date`) that differ on a few notices. Auditor decided: use `Contract start date`/`Contract end date` only (per CLAUDE.md); no alternate-column comparison.
- Payment tags in normalise_supplier rule 5 are a fixed, auditor-decided list applied longest first; `PAYMENTS` alone is deliberately not a tag. Never add tags; only report candidates.
- Merged split-purchase groups are contiguous runs in date order (amounts are all positive), so a group = all under-T rows of that supplier between first and last date. Put dates + counts in analytics.json top20 rather than full id lists (full ids made the JSON ~300 KB); the self-check re-derives membership from the dates.

**Why:** these cost time to discover and affect correctness of ids, thresholds and self-check.
**How to apply:** on re-runs or new spend months, keep these patterns; re-verify if pandas or the export format changes.
