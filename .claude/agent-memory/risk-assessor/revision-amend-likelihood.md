---
name: revision-amend-likelihood
description: How to apply an auditor Amend that changes a likelihood score in a revision without tripping the builder's rubric or undeclared-change checks
metadata:
  type: feedback
---

When an Amend asks for a different likelihood, change only `likelihood.score`. Leave `rubric_row` and `signal` as the signal gives them, and declare `fields: ["likelihood.score"]`. In a revision the builder accepts the off-rubric score and marks it as an auditor override, showing the rubric's value. A Reject changes only `status` (set it to "rejected"). Approve and Leave out need no change entry.

**Why:** if you change `rubric_row` to match the new score, the builder fails it as a rubric mismatch. If you also edit the justification to explain the change, that is an extra field the auditor did not ask for.

**How to apply:** before you apply the change, check the Amend's factual premise against the inputs. The auditor's reason goes in the change `summary`, not in the risk's prose. See also [[builder-prose-and-paths]].
