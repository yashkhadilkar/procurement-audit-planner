---
name: pdf-table-extraction-lessons
description: How-to lessons for rebuilding committee-paper tables from pdftotext and passing verify_history.py (merged vs blank cells, page-spanning cells, integer token binding)
metadata:
  type: feedback
---

Rules learned while building history.json from the committee PDFs:

- Neither text mode shows whether a first-column cell is merged across rows or blank. Render the page
  (`pdftoppm -r 70 -png`, into the scratchpad) and look before giving a row a `service`; a blank cell
  is recorded as null.
  **Why:** layout text prints a cell like "Primary" only on the first row, so it looks the same as a
  merged cell.
  **How to apply:** for any table where a column value appears on one row only, check the image.
- A table cell that runs across a page break cannot be bound as one field value: the verifier needs
  each field inside a single page's quote. Record the part printed on the first page, cite the
  continuation on the next page in the same item, and explain it in a gap with topic "other".
- Integer fields are matched as whole tokens (`(?<![\d.])N(?![\d.])`), so an axis label printed "2."
  does not satisfy score 2. Put a passage in the same item's cites where the bare number appears
  (e.g. the likelihood axis line, or the row's score cells).
- Plain mode prints each cell in one piece for Table 1, Table 3 and the 6.7 table; -layout is
  needed only for row membership (layout_quote). Building the JSON from a generator script kept in
  the scratchpad (run with `python3 -I`) made fixes cheap; nothing goes in the repo except outputs/history.json.

Related: [[verify-history-workflow]]
