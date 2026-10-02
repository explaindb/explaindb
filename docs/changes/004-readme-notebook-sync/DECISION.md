# 004 — Keep the README notebook table in sync with notebooks/
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/121
---
## Context

The README lists every notebook in a table (grouped by tutorial chapter) with a link to the
file and a Binder badge that opens it directly. The table is maintained by hand, so it can
drift when a notebook is added, renamed or removed, or when a row or Binder link is edited
by mistake. Nothing noticed such drift so far.

## Decision

A unit test in `system/tests/` (run by the existing `py_test` job) parses the README section
`## Notebooks` up to the next `## ` heading and compares it with the notebooks directly in
`notebooks/` (non-recursive, so Jupyter's `.ipynb_checkpoints/` is ignored). It fails when
a notebook is missing from the table or the table lists one that does not exist, when a
notebook is listed twice, when any table row does not have the exact expected form, when a
row's label, file link and Binder target disagree, when the Binder link does not use the
expected host, repository (`explaindb/explaindb`) and branch (`main`), and when the section
is missing or has no rows. Requiring every row to match the expected form ensures a
malformed row fails loudly instead of being skipped. `CONTRIBUTING.md` gets a short
`Notebooks` section listing what to update when a notebook is added or renamed: the README
table (enforced by this test) and `.ci/notebook_weights.tsv` (enforced by the existing
notebook-assignment test).

## Consequences
**Positive:** Drift between the README table and the notebooks is caught by the test suite,
with a message naming the notebook or row to fix.
**Negative:** Merge requests that only change Markdown skip `py_test`, so a README-only edit
that breaks the table is only caught by the next `main` pipeline (addressed by a separate
follow-up MR). The test fixes the table layout; changing the layout means adapting the test.

## Out of scope & deferred
- Running the tests for merge requests that change `README.md` (follow-up MR, approved).
- Checking that the topic cells are non-empty and that the badge alt text names the notebook.
- Checking that the tutorial pages reference every notebook.

## Alternatives rejected
- Generating the table from notebook metadata: a bigger change that would lose the
  hand-written topics.
- A shell/grep check in CI instead of a unit test: less readable, and the project's checks
  of this kind are unittest tests.

<!-- notes below: skill never overwrites past this marker -->
