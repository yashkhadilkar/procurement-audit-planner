---
name: typed-figures-in-officer-titles
description: build_pack.py flags digits inside words such as "S151 Officer" as typed figures; write "statutory finance officer" instead
metadata:
  type: feedback
---

The builder's typed-figure check strips citations, placeholders, years and IDs, then flags any remaining digits, so "S151 Officer" in audit-plan.json prose fails the build.

**Why:** the check is digit-based, not context-aware; the register already uses "statutory finance officer" for the same reason.

**How to apply:** in controls, test steps, PBC items, reasons and memo prose, write "statutory finance officer" and avoid any other digit-bearing wording (amounts, "3-month", clause numbers such as "clause 6.15": describe the clause instead, e.g. "the Rules' definition of Total Contract Value") outside `[rule:]` tags and `{{$.path}}` placeholders. Years are allowed. See [[audit-plan-recipe-tips]].
