#!/usr/bin/env python3
"""QA sample check: every sampled transaction exists in the cleaned spend data and in the council's workbook.

    .venv/bin/python -I scripts/checks/check_samples.py

For every row of outputs/samples/T-*.csv and every row ID
(<workbook>:r<row>) written in outputs/audit-program.md:
- the transaction is in outputs/analytics-full/spend-clean.csv, with the same
  source file, sheet row, supplier name and net amount as the sample row;
- its ID names the same workbook and row (<workbook stem>:r<excel_row>);
- at that row of sheet "Data to publish" in data/spend/<source_file>, the
  Supplier name and Net amount are the ones in spend-clean.csv.
Also: each sample file's test_id matches its file name, every sampled item is
a general_procurement row, and the sample files on disk are exactly those
pack-figures.json lists, with the same row counts and sha256.

The workbook is read with openpyxl directly; the header row is located by
its column names, independently of scripts/clean.py.

Exit 0 when everything passes, 1 otherwise.
"""

import csv
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_lib as Q  # noqa: E402

NAME = "check_samples"
SAMPLE_NEEDS = ("test_id", "item_rank", "item_spend_tag", "transaction_id", "source_file", "excel_row",
                "supplier_name", "net_amount", "spend_tag")


def amount(v):
    try:
        return Decimal(str(v).strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


class Workbooks:
    """Sheet rows of the council's workbooks, read on first use."""

    def __init__(self, spend_dir, res):
        self.dir, self.res, self.books = spend_dir, res, {}

    def row(self, source_file, excel_row):
        """(supplier name, net amount) at the sheet row, or None after recording why."""
        if source_file not in self.books:
            self.books[source_file] = self._load(source_file)
        book = self.books[source_file]
        if book is None:
            return None
        ws, cols, header_row = book
        if excel_row <= header_row or excel_row > ws.max_row:
            return ("", None, f"row {excel_row} is not a data row of {source_file} (header row {header_row}, "
                              f"last row {ws.max_row})")
        sup = ws.cell(row=excel_row, column=cols["Supplier name"]).value
        net = ws.cell(row=excel_row, column=cols["Net amount"]).value
        return (str(sup).strip() if sup is not None else "", amount(net) if net is not None else None, None)

    def _load(self, source_file):
        p = self.dir / source_file
        if "/" in source_file or not p.is_file():
            self.res.fail(f"workbook {source_file} not found in {self.dir}")
            return None
        try:
            import openpyxl
            wb = openpyxl.load_workbook(p, data_only=True)
        except Exception as e:  # noqa: BLE001 - any read failure is a check failure
            self.res.fail(f"workbook {source_file} cannot be read: {e}")
            return None
        if Q.SPEND_SHEET not in wb.sheetnames:
            self.res.fail(f"workbook {source_file} has no sheet {Q.SPEND_SHEET!r}")
            return None
        ws = wb[Q.SPEND_SHEET]
        for r in range(1, Q.HEADER_SEARCH_ROWS + 1):
            names = {str(ws.cell(row=r, column=c).value).strip(): c for c in range(1, ws.max_column + 1)
                     if isinstance(ws.cell(row=r, column=c).value, str)}
            if all(c in names for c in Q.SPEND_COLUMNS):
                return ws, names, r
        self.res.fail(f"workbook {source_file}: no header row with {list(Q.SPEND_COLUMNS)} in the first "
                      f"{Q.HEADER_SEARCH_ROWS} rows")
        return None


def check_one(where, tx, sample, spend, books, res):
    """sample: the sample row (or None for an ID named in the program)."""
    sp = spend.get(tx)
    if sp is None:
        res.fail(f"{where}: transaction {tx} is not in spend-clean.csv")
        return
    m = re.fullmatch(r"(.+):r(\d+)", tx)
    if not m or f"{m.group(1)}.xlsx" != sp["source_file"] or m.group(2) != str(sp["excel_row"]).strip():
        res.fail(f"{where}: transaction {tx} does not name its row ({sp['source_file']} row {sp['excel_row']} in "
                 "spend-clean.csv)")
    if sample is not None:
        for col in ("source_file", "excel_row", "supplier_name"):
            if (sample.get(col) or "").strip() != (sp.get(col) or "").strip():
                res.fail(f"{where}: {tx} {col} is {sample.get(col)!r} in the sample but {sp.get(col)!r} in "
                         "spend-clean.csv")
        if amount(sample.get("net_amount")) is None or amount(sample.get("net_amount")) != amount(sp["net_amount"]):
            res.fail(f"{where}: {tx} net_amount is {sample.get('net_amount')!r} in the sample but "
                     f"{sp['net_amount']!r} in spend-clean.csv")
        if (sample.get("spend_tag") or "") != (sp.get("spend_tag") or ""):
            res.fail(f"{where}: {tx} spend_tag is {sample.get('spend_tag')!r} in the sample but "
                     f"{sp.get('spend_tag')!r} in spend-clean.csv")
    try:
        excel_row = int(str(sp["excel_row"]).strip())
    except ValueError:
        res.fail(f"{where}: {tx} has excel_row {sp['excel_row']!r} in spend-clean.csv")
        return
    got = books.row(sp["source_file"], excel_row)
    if got is None:
        return
    sup, net, problem = got
    if problem:
        res.fail(f"{where}: {tx}: {problem}")
        return
    if sup != (sp.get("supplier_name") or "").strip():
        res.fail(f"{where}: {tx}: {sp['source_file']} row {excel_row} has supplier {sup!r}, spend-clean.csv "
                 f"{sp.get('supplier_name')!r}")
    if net is None or net != amount(sp["net_amount"]):
        res.fail(f"{where}: {tx}: {sp['source_file']} row {excel_row} has net amount {net}, spend-clean.csv "
                 f"{sp['net_amount']}")


def check_listing(root, files, res):
    pf = Q.load_json(root / "outputs/pack-figures.json", res, "pack-figures.json")
    if pf is None:
        return
    listed = {Path(s.get("file", "")).name: s for s in pf.get("samples", [])}
    on_disk = {p.name: p for p in files}
    for name in sorted(set(listed) - set(on_disk)):
        res.fail(f"pack-figures.json lists outputs/samples/{name}, which is not on disk")
    for name in sorted(set(on_disk) - set(listed)):
        res.fail(f"outputs/samples/{name} is not listed in pack-figures.json")
    for name in sorted(set(listed) & set(on_disk)):
        p, s = on_disk[name], listed[name]
        with p.open(newline="", encoding="utf-8") as fh:
            rows = sum(1 for _ in csv.DictReader(fh))
        if rows != s.get("rows"):
            res.fail(f"outputs/samples/{name} has {rows} rows; pack-figures.json records {s.get('rows')}")
        if Q.sha256(p) != s.get("sha256"):
            res.fail(f"outputs/samples/{name} sha256 {Q.sha256(p)[:12]} differs from the {str(s.get('sha256'))[:12]} "
                     "pack-figures.json records: the file changed after the build")


def run(root=Q.ROOT_DEFAULT):
    root = Path(root).resolve()
    res = Q.Result(NAME)
    spend_path = root / "outputs/analytics-full/spend-clean.csv"
    if not spend_path.is_file():
        res.fail(f"spend-clean.csv not found at {spend_path}")
        return res
    with spend_path.open(newline="", encoding="utf-8") as fh:
        spend = {r["transaction_id"]: r for r in csv.DictReader(fh)}
    books = Workbooks(root / "data/spend", res)

    files = sorted((root / "outputs/samples").glob("T-*.csv"))
    if not files:
        res.fail("no sample files in outputs/samples/")
    for p in files:
        res.count("sample files")
        with p.open(newline="", encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            missing = [c for c in SAMPLE_NEEDS if c not in (rd.fieldnames or [])]
            if missing:
                res.fail(f"outputs/samples/{p.name}: missing columns {missing}")
                continue
            rows = list(rd)
        if not rows:
            res.fail(f"outputs/samples/{p.name} has no rows")
        for n, row in enumerate(rows, 2):
            res.count("sampled transactions")
            where = f"samples/{p.name} line {n}"
            if row["test_id"] != p.stem:
                res.fail(f"{where}: test_id {row['test_id']!r} in the file for {p.stem}")
            if row["item_spend_tag"] != Q.PRIMARY_TAG:
                res.fail(f"{where}: item {row['item_rank']} is a {row['item_spend_tag']!r} item; samples are drawn "
                         f"only from {Q.PRIMARY_TAG} rows")
            check_one(where, row["transaction_id"].strip(), row, spend, books, res)
    check_listing(root, files, res)

    prog = Q.read_text(root / "outputs/audit-program.md", res, "audit-program.md")
    if prog is not None:
        for ln, line in enumerate(prog.splitlines(), 1):
            for m in Q.TX_ID_RE.finditer(line):
                res.count("row IDs in audit-program.md")
                check_one(f"audit-program.md line {ln}", m.group(0), None, spend, books, res)
        if "row IDs in audit-program.md" not in res.counts:
            res.counts["row IDs in audit-program.md"] = 0
    return res


def main(argv=None):
    a = Q.parse_args(__doc__, argv)
    return run(a.root).print()


if __name__ == "__main__":
    sys.exit(main())
