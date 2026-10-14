#!/usr/bin/env python3
"""QA quote check: rules.json against the PDF, and the register's rule excerpts against rules.json.

    .venv/bin/python -I scripts/checks/check_quotes.py

1. Runs the extract-rules verifier (.claude/skills/extract-rules/verify_quotes.py)
   on outputs/rules.json against data/contract-rules.pdf; any error it reports
   is a failure.
2. Independently, finds every passage of every rule's verbatim_quote (a
   string or a list of passages) and of every parameters.*.defined_in quote on
   its stated page of the PDF (whitespace-insensitive, otherwise exact).
3. In outputs/risk-register.md: every rule citation names a rule in rules.json;
   every "rule CPR-nn: clause, page, type" source line matches rules.json; and
   every quoted passage in the risk and noted sections that is not a
   history.json quote is a verbatim_quote passage of a rule cited on the same
   line (or of a parameter bounding one).

Exit 0 when everything passes, 1 otherwise.
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_lib as Q  # noqa: E402

NAME = "check_quotes"
MIN_EXCERPT = 10
QUOTED = (r'"([^"\n]+)"', r"“([^”\n]+)”")
SOURCE_LINE = r"^\s*- rule (CPR-\d+): clause (\S+), page (\S+), (\S+)\s*$"


def passages(quote):
    """The passages of a verbatim_quote, or None if it is malformed."""
    if isinstance(quote, str) and quote.strip():
        return [quote]
    if isinstance(quote, list) and quote and all(isinstance(q, str) and q.strip() for q in quote):
        return quote
    return None


def run_verifier(root, res):
    rules, pdf = root / "outputs/rules.json", root / "data/contract-rules.pdf"
    res.count("verifier runs")
    try:
        p = subprocess.run([sys.executable, "-I", str(Q.VERIFIER), str(rules), "--pdf", str(pdf)],
                           capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        res.fail(f"verify_quotes.py could not run: {e}")
        return
    if p.returncode == 0:
        return
    lines = [ln.strip() for ln in (p.stdout + p.stderr).splitlines() if ln.strip().startswith(("[", "ERROR"))]
    if p.returncode == 2 or not lines:
        res.fail(f"verify_quotes.py exited {p.returncode}: {(p.stderr or p.stdout).strip()[:300]}")
    for ln in lines:
        res.fail(f"verify_quotes.py {ln}")


def check_pdf_passages(rules, pdf, res):
    try:
        pages = Q.pdf_pages(pdf)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
        res.fail(f"cannot read {pdf}: {e}")
        return
    items = []
    for r in rules.get("rules", []):
        items.append((r.get("rule_id"), "rule quote passages", r.get("page"), r.get("verbatim_quote")))
    for name, p in (rules.get("parameters") or {}).items():
        for i, d in enumerate((p or {}).get("defined_in") or []):
            items.append((f"parameters.{name}.defined_in[{i}]", "parameter quote passages", d.get("page"),
                          d.get("verbatim_quote")))
        if not (p or {}).get("defined_in"):
            res.fail(f"parameters.{name}: no defined_in quote")
    for where, label, page, quote in items:
        ps = passages(quote)
        if ps is None:
            res.fail(f"{where}: verbatim_quote must be a non-empty string or a list of non-empty passages")
            continue
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= len(pages):
            res.fail(f"{where}: page {page!r} is not a page of the PDF (1 to {len(pages)})")
            continue
        for i, text in enumerate(ps):
            res.count(label)
            w = f"{where} verbatim_quote[{i}]" if isinstance(quote, list) else f"{where} verbatim_quote"
            q = Q.norm(text)
            if any(q in v for v in pages[page - 1]):
                continue
            elsewhere = [n + 1 for n, vs in enumerate(pages) if any(q in v for v in vs)]
            hint = f"found on page(s) {elsewhere}" if elsewhere else "not found anywhere in the PDF"
            res.fail(f"{w}: not on page {page}; {hint}: {text[:80]!r}")


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def check_register(root, rules, history, res):
    text = Q.read_text(root / "outputs/risk-register.md", res, "risk-register.md")
    if text is None:
        return
    by_id = {r.get("rule_id"): r for r in rules.get("rules", [])}
    owned = []  # (owner, normalised passage)
    for r in rules.get("rules", []):
        for p in passages(r.get("verbatim_quote")) or []:
            owned.append((r["rule_id"], Q.norm(p)))
    for name, p in (rules.get("parameters") or {}).items():
        for d in (p or {}).get("defined_in") or []:
            for q in passages(d.get("verbatim_quote")) or []:
                owned.append((f"parameter {name}", Q.norm(q)))
    hist = [Q.norm(s) for s in strings(history)] if history else []

    lines = text.splitlines()
    for ln, line in enumerate(lines, 1):
        for rid in Q.rule_tags(line):
            res.count("register rule citations")
            if rid not in by_id:
                res.fail(f"risk-register.md line {ln}: cites rule {rid}, which is not in rules.json")
        m = re.match(SOURCE_LINE, line)
        if m:
            res.count("register rule source lines")
            rid, clause, page, typ = m.groups()
            r = by_id.get(rid)
            if r is None:
                res.fail(f"risk-register.md line {ln}: source line names {rid}, which is not in rules.json")
            elif (str(r.get("clause")), str(r.get("page")), str(r.get("type"))) != (clause, page, typ):
                res.fail(f"risk-register.md line {ln}: {rid} is clause {clause}, page {page}, {typ} in the register "
                         f"but clause {r.get('clause')}, page {r.get('page')}, {r.get('type')} in rules.json")

    sections = Q.md_sections(text, 2)
    for title in ("Risks", "Noted, not rated"):
        if title not in sections:
            res.fail(f"risk-register.md has no '## {title}' section")
            continue
        start, body = sections[title]
        for off, line in enumerate(body.splitlines(), 1):
            ln = start + off
            cited = set(Q.rule_tags(line))
            params = {r.get(k) for rid in cited if rid in by_id for r in [by_id[rid]]
                      for k in ("threshold_low_param", "threshold_high_param") if r.get(k)}
            for pat in QUOTED:
                for m in re.finditer(pat, line):
                    q = Q.norm(m.group(1))
                    if len(q) < MIN_EXCERPT:
                        continue
                    owners = sorted({o for o, p in owned if q in p})
                    if owners:
                        res.count("register rule excerpts")
                        ok = [o for o in owners if o in cited or (o.startswith("parameter ") and o[10:] in params)]
                        if not ok:
                            res.fail(f"risk-register.md line {ln}: quoted {m.group(1)[:80]!r} is from "
                                     f"{', '.join(owners)} in rules.json, but the line cites "
                                     f"{', '.join(sorted(cited)) or 'no rule'}")
                    elif any(q in h for h in hist):
                        res.count("register history excerpts (not rule quotes)")
                    else:
                        res.count("register rule excerpts")
                        res.fail(f"risk-register.md line {ln}: quoted {m.group(1)[:80]!r} matches no verbatim_quote "
                                 "in rules.json (and no history.json quote)")


def run(root=Q.ROOT_DEFAULT):
    root = Path(root).resolve()
    res = Q.Result(NAME)
    run_verifier(root, res)
    rules = Q.load_json(root / "outputs/rules.json", res, "rules.json")
    history = Q.load_json(root / "outputs/history.json", res, "history.json")
    if rules is not None:
        check_pdf_passages(rules, root / "data/contract-rules.pdf", res)
        check_register(root, rules, history, res)
    return res


def main(argv=None):
    a = Q.parse_args(__doc__, argv)
    return run(a.root).print()


if __name__ == "__main__":
    sys.exit(main())
