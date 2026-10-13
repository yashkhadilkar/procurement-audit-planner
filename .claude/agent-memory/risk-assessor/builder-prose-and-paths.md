---
name: builder-prose-and-paths
description: How-to for build_register.py prose and --resolve paths: officer titles with digits trip the typed-figure check; string filters need quotes
metadata:
  type: feedback
---

The builder's typed-figure check flags any digit in prose, including officer titles such as "S151" / "S.151 Officer". Refer to the role in words (e.g. "the statutory finance officer") and keep the `[rule:CPR-nn]` tag that names it.

**Why:** a first build left five "figure typed in prose (151)" warnings that were only the title; the finishing bar requires 0 warnings.

**How to apply:** before the first build, scan prose for officer titles, section numbers or dates written with digits and reword them or move them into a rule tag.

Path filters on string fields need a quoted value: `[narrative='Direct Payment']`, `[value='THRESHOLD']`. Unquoted strings fail with "neither a number nor a 'quoted string'". Numeric filters stay bare: `[threshold=25000]`.
