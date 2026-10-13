#!/usr/bin/env python3
"""Tests for scripts/verify_history.py against fixtures with planted errors.

    .venv/bin/python scripts/tests/test_verify_history.py

history-valid.json must pass. history-planted.json and
history-planted-scoring.json are copies of it with errors planted; each
planted error must be reported, and nothing else. The consistency checks are
also run directly on planted inconsistencies the real PDF does not contain.
Needs pdftotext and data/committee/.
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "scripts/tests/fixtures"

spec = importlib.util.spec_from_file_location("verify_history", ROOT / "scripts/verify_history.py")
vh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vh)

PLANTED = {
    # (code, where): planted error
    ("SOURCE_MISMATCH", "sources[1].sha256"): "P01 sha256 mismatch",
    ("SCHEMA", "audits[0]"): "P02 a score field added to an audit",
    ("QUOTE_NOT_FOUND", "audits[0].cites[0].quote[4]"): "P03 straight apostrophe where the PDF has a curly one",
    ("LAYOUT_QUOTE_NOT_FOUND", "audits[1].cites[0].layout_quote"): "P04 plain-only text given as layout_quote",
    ("FIELD_NOT_IN_QUOTE", "audits[1].directorate"): "P04 knock-on: the heading was only in the layout_quote",
    ("FIELD_NOT_IN_QUOTE", "audits[1].service"): "P04 knock-on",
    ("FIELD_NOT_IN_QUOTE", "audits[2].opinion"): "P05 opinion differs from its quote (though it is on the page)",
    ("LAYOUT_QUOTE_MISSING", "audits[2]"): "P06 table row without layout_quote",
    ("QUOTE_NOT_FOUND", "opinion_basis[0].cites[0].quote"): "P07 wrong pdf_page",
    ("QUOTE_NOT_FOUND", "risk_themes[0].cites[0].quote"): "P08 fabricated quote",
    ("FIELD_NOT_IN_QUOTE", "risk_themes[0].theme"): "P08 fabricated theme",
    ("SCHEMA", "risk_register_access.cites[1].pdf_page"): "P09 page beyond the PDF",
    ("FIELD_NOT_IN_QUOTE", "risk_register_access.name_in_papers"): "P09 knock-on",
    ("UNRECORDED_INCONSISTENCY", "impact.financial_pct:3-4"): "P10 computed inconsistency not recorded",
    ("SOURCE_UNKNOWN", "discrepancies[1].cites[2].file"): "P11 cite to a file that is not a source",
    ("ID_SEQUENCE", "discrepancies[2]"): "P12 id out of sequence",
    ("UNKNOWN_CHECK_REF", "discrepancies[2].check_ref"): "P13 check_ref the checks never produced",
    ("SCHEMA", "discrepancies[2].cites"): "P14 discrepancy without cites",
    ("GAP_MISSING", "agreed_actions"): "P15 empty agreed_actions with no gap",
    ("SOURCE_UNKNOWN", "gaps[0].searched"): "P16 searched a file that is not a source",
    ("QUOTE_FORMAT", "gaps[1].cites[0].quote"): "P17 ellipsis",
    ("SCHEMA", "top level"): "P18 unknown top-level key",
}

PLANTED_SCORING = {
    ("FIELD_NOT_IN_QUOTE", "risk_scoring_method.matrix.rows[1].scores"): "Q1 matrix cell mistyped",
    ("FIELD_NOT_IN_QUOTE", "risk_scoring_method.likelihood_scale[2].label"): "Q2 label not the printed one",
    ("SCHEMA", "risk_scoring_method.impact_scale"): "Q3 impact score missing",
    ("CONSISTENCY_SKIPPED", "risk_scoring_method"): "Q* consistency checks wait for a well-formed method",
}


def run(fixture):
    """Run the verifier; return (exit code, list of (code, where), output)."""
    errors = []
    real_add = vh.Report.add

    def spy(self, code, where, msg):
        errors.append((code, where))
        real_add(self, code, where, msg)

    vh.Report.add = spy
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = vh.main([str(FIX / fixture), "--committee", str(ROOT / "data/committee")])
    finally:
        vh.Report.add = real_add
    return rc, errors, out.getvalue()


def expect_exact(fixture, planted):
    rc, errors, out = run(fixture)
    got = set(errors)
    missed = [f"{k} ({v})" for k, v in planted.items() if k not in got]
    extra = sorted(got - set(planted))
    assert rc == 1, f"{fixture}: exit {rc}, expected 1\n{out}"
    assert not missed, f"{fixture}: planted errors not reported: {missed}\n{out}"
    assert not extra, f"{fixture}: unexpected errors: {extra}\n{out}"
    assert len(errors) == len(got), f"{fixture}: an error was reported twice\n{out}"


def test_valid_passes():
    rc, errors, out = run("history-valid.json")
    assert rc == 0 and not errors, f"valid fixture failed:\n{out}"
    assert "impact.financial_pct:3-4" in out and "matrix.label_name:High" in out, out


def test_planted():
    expect_exact("history-planted.json", PLANTED)


def test_planted_scoring():
    expect_exact("history-planted-scoring.json", PLANTED_SCORING)


def method():
    return copy.deepcopy(json.loads((FIX / "history-valid.json").read_text())["risk_scoring_method"])


def test_consistency_real_method():
    assert set(vh.consistency_findings(method())) == {"impact.financial_pct:3-4", "matrix.label_name:High"}


def test_consistency_planted():
    m = method()
    m["matrix"]["rows"][1]["scores"][4] = 21           # impact 4 x likelihood 5 is not 21
    m["bands"][3]["score_printed"] = "Up to 4"         # Low now overlaps Moderate 4-6
    m["matrix"]["impact_axis"][2]["label"] = "Moderate"  # axis label differs from Table 1 ("Medium")
    m["impact_scale"][1]["criteria"]["Financial loss to Council"] = "0.35% - 1% annual WBC budget £500k £2M"
    f = vh.consistency_findings(m)
    assert "matrix.product:I4L5" in f, f
    assert "bands.overlap:Moderate|Low" in f, f
    for cell in ("I4L1", "I2L2", "I1L4"):              # every cell scoring 4 now sits in two bands
        assert f"matrix.band:{cell}" in f, f
    assert "impact.axis:3" in f, f
    assert "gap between bands" in f["impact.financial_pct:3-4"], f
    assert "impact.financial_gbp:3-4" not in f, f


def test_parsers():
    assert vh.parse_band("15 -25") == (15, 25)
    assert vh.parse_band("Up to 3") == (1, 3)
    assert vh.parse_band("Score 9 or above") is None
    assert vh.parse_financial("> 1% annual WBC budget >£2m")[1][0] == 2_000_000
    assert vh.parse_financial("0.1% - 0.3% annual WBC budget £175k -500k") == ((0.1, 0.3), (175_000, 500_000))
    assert vh.parse_financial("Less than 0.01% annual WBC budget £17.5k") == ((0.0, 0.01), (0.0, 17_500))


def main():
    os.chdir(ROOT)                                     # history.json names files relative to the repo root
    tests =[v for k, v in globals().items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok    {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {t.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
