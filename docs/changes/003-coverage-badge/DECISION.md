# 003 — Show test coverage as a GitLab badge
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/116
---
## Context

The project measures test coverage in the `py_test` CI job, but only as an HTML report
artifact; GitLab does not know the number, so it can be neither shown as a badge nor
compared in merge requests. The GitLab project is `internal`: badge images are only
served to logged-in users, and anonymous requests are redirected to the login page. The
README is mirrored to a public GitHub repository, where a GitLab badge would therefore
appear as a broken image. The coverage measurement excludes the test files (separate
change before this one), so the number reflects the system code only.

## Decision

`py_test` additionally prints `coverage report`, and the job's `coverage:` keyword
extracts the total from the `TOTAL` line. The regex has exactly one capture group for the
percentage; GitLab uses the last capture group, whereas without a group it would take the
first number on the line (the statement count). The badges are GitLab project badges
(project settings), not README badges: a coverage badge (image filtered to `py_test`,
linking to the latest HTML coverage report artifact on the default branch) and a pipeline
badge (linking to the pipeline list). They are created via the GitLab API after the merge,
once a `main` pipeline has recorded a value.

## Consequences
**Positive:** Coverage is visible at a glance on the GitLab project page and in every
merge request, where GitLab shows the change in coverage.
**Negative:** The badges are only visible to logged-in GitLab users, not on GitHub. Merge
requests that only change Markdown skip `py_test` and therefore report no coverage value.
The regex depends on the default `coverage report` columns; enabling branch coverage
changes the `TOTAL` line and would silently stop the value from being recorded. The report
link relies on GitLab keeping the artifacts of the latest successful job (the default) and
points to the last successful run if `py_test` fails on `main`.

## Out of scope & deferred
- Codecov (or similar) for a public coverage badge on GitHub.
- Cobertura `coverage_report` artifact for line-level coverage annotations in MR diffs.
- A minimum coverage threshold (`fail_under`) that fails the pipeline.

## Alternatives rejected
- Badge in the README: broken image on GitHub and for anonymous GitLab visitors.
- Writing the coverage number into the repository from CI for a shields.io badge: CI
  would have to commit to the repository.

<!-- notes below: skill never overwrites past this marker -->

Note 2026-10-02 (evidence): on the MR pipeline for 5365932 (rebased onto the `.coveragerc`
change of !115), GitLab recorded coverage 91.0 for `py_test` and 91.00 for the pipeline:
https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/543335
