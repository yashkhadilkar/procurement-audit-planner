#!/usr/bin/env python3
"""Run the four QA checks on the audit planning pack and print one table and a verdict.

    .venv/bin/python -I scripts/checks/run_checks.py            each PACK READY version
    .venv/bin/python -I scripts/checks/run_checks.py --final    before review.md (adds challenges.md)

Runs check_quotes, check_numbers, check_trace and check_samples. Prints the
pack fingerprint (pack-figures.json build time and the sha256 of the plan,
the three documents, pack-figures.json, the sample files and, in the final
run, challenges.md), the results table, the verdict (PASS only when all four
pass) and every failure as a numbered point, "#n <check>: <item>", in the
form the qa-reviewer sends them. Numbers restart on every run.

Exit 0 on PASS, 1 on FAIL.
"""

import hashlib
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_lib as Q  # noqa: E402
import check_numbers  # noqa: E402
import check_quotes  # noqa: E402
import check_samples  # noqa: E402
import check_trace  # noqa: E402

CHECKS = [("check_quotes", check_quotes.run), ("check_numbers", check_numbers.run),
          ("check_trace", check_trace.run), ("check_samples", check_samples.run)]


def fingerprint(root, final):
    out = root / "outputs"
    parts = []
    try:
        pf = json.loads((out / "pack-figures.json").read_text(encoding="utf-8"))
        parts.append(f"built {pf.get('built')}, register r{pf.get('register_revision')}")
    except (OSError, json.JSONDecodeError):
        parts.append("pack-figures.json unreadable")
    names = ["audit-plan.json", *Q.PACK_DOCS, "pack-figures.json"] + (["challenges.md"] if final else [])
    for name in names:
        p = out / name
        parts.append(f"{name} {Q.sha256(p)[:12] if p.is_file() else 'missing'}")
    samples = sorted((out / "samples").glob("T-*.csv"))
    h = hashlib.sha256()
    for p in samples:
        h.update(p.name.encode() + b"\0" + p.read_bytes())
    parts.append(f"samples ({len(samples)} files) {h.hexdigest()[:12] if samples else 'missing'}")
    return "; ".join(parts)


def main(argv=None):
    a = Q.parse_args(__doc__, argv, final=True)
    root = a.root.resolve()
    results = []
    for name, fn in CHECKS:
        try:
            res = fn(root, a.final) if name == "check_trace" else fn(root)
        except Exception:  # noqa: BLE001 - a check that crashes fails
            res = Q.Result(name)
            res.fail("the check crashed: " + traceback.format_exc().strip().splitlines()[-1])
        results.append(res)

    mode = "final run" if a.final else "version run; challenges.md is checked in the final run"
    print(f"QA checks ({mode})")
    print(f"Pack: {fingerprint(root, a.final)}")
    print()
    print("| Check | Result | Checked | Failures |")
    print("| --- | --- | --- | --- |")
    for r in results:
        print(f"| {r.name} | {'PASS' if r.passed else 'FAIL'} | {r.checked()} | {len(r.failures)} |")
    failed = [r.name for r in results if not r.passed]
    print()
    print("VERDICT: PASS" if not failed else f"VERDICT: FAIL ({', '.join(failed)})")
    n = 0
    if failed:
        print()
        for r in results:
            for f in r.failures:
                n += 1
                print(f"#{n} {r.name}: {f}")
    notes = [(r.name, x) for r in results for x in r.notes]
    if notes:
        print()
        for name, x in notes:
            print(f"note ({name}): {x}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
