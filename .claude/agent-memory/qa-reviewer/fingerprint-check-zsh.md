---
name: fingerprint-check-zsh
description: How to verify the Step 0 fingerprint in this repo's zsh shell without losing the exit status
metadata:
  type: feedback
---

The Bash tool runs zsh here, so `${PIPESTATUS[0]}` is empty after a pipe. Check the fingerprint with `shasum -a 256 -c "$FP" | grep -vc ': OK$'` (prints 0 when every line is OK), or run `shasum -a 256 -c "$FP"` alone and read the `exit` code.

**Why:** a piped check with PIPESTATUS printed a blank exit status and had to be re-run.
**How to apply:** use one of these forms before every verdict and before review.md.
