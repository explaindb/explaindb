# 038 — visualization_test in three jobs, split by page
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/215
---
## Context

The CI job `visualization_test` (system/tests/repo/test_visualizations.py, 41 tests in a headless Chromium with
software WebGL) takes 6½–7 minutes: about 50 s to install Playwright and Chromium, the rest for the tests. It runs in
every merge request that changes a page, the page test, `.gitlab-ci.yml`, `pyproject.toml` or `uv.lock`, and it is
then the last job of the pipeline, about 2 minutes after `py_test` (5½ minutes). Most of the time goes to the pages
with a voice: locally about 60 s for the House DBMS page, 59 s for clock-scan, 48 s for row-or-column, and 7 s and 2 s
for the two pages without one; on the CI runner everything takes about twice as long. The runner runs at most four
jobs at a time.

## Decision

- **`visualization_test` runs as `parallel: 3`**, as `ipynb_test` does. Each of the three jobs runs the whole test
  module, but only on its own pages.
- **Each page is tested in exactly one job.** The pages with a sound button come first, then the others, each group
  sorted by its path in `visualizations/`; page k of this order, counted from 0, goes to job k mod 3 + 1. A new page
  is assigned without a list to keep up to date.
- **The job names its share in a variable of its own**, `VISUALIZATION_JOB="$CI_NODE_INDEX/$CI_NODE_TOTAL"`. Without
  it (a local run or any other CI job) one job tests every page. A value that is not "i/n" with
  1 ≤ i ≤ n is an error, so that no page can drop out silently. GitLab's own variables are not read directly: GitLab
  sets `CI_NODE_TOTAL` in every job, and another parallel job that ran the module would then skip pages.
- **A test class of one page is skipped only when its page belongs to another job**; a page that is not found at all
  is an error. Tests that run on every page run on the job's pages; a job without a page with sound skips the sound
  tests and says why. Tests without a page run in every job.
- **Tests without a browser** check how the variable is read and how the pages are assigned, also on the real folder.

## Consequences

**Positive:** each job takes about 3–3½ minutes instead of 7; a pipeline that changes a page ends at about the time
`py_test` ends. A new page without sound is covered without a change to the CI configuration.
**Negative:** three installations of Playwright and Chromium instead of one (about 50 s each of runner time); the
test module carries the rule that assigns pages to jobs; job names show a number, not the pages.

## Out of scope & deferred

- Weights per page measured from the CI runs (as `.ci/notebook_weights.tsv` for the notebooks): a better balance once
  there are many pages; today the longest job (House DBMS and elasticity, about 70 s locally) takes about 40 %
  longer than the shortest (row-or-column, about 50 s).
- Shorter sound tests (less waiting for the film's time): changes what the tests do; a separate analysis.

## Alternatives rejected

- One job per page with `parallel: matrix` (5 jobs): five installations on a runner with four slots, and a list of
  pages that a new page could miss.
- `parallel: 5` with the same rule: the longest job is one page with sound either way; it saves about 15 s and costs
  two more installations for pages whose tests take seconds.
- Several processes in one job: the pages draw with software WebGL on the runner's CPU, which the processes share; a
  new dependency.
- Fewer tests: changes what is checked.
- Reusing `assign()` of `.ci/assign_notebooks.py`: the test module would load a script from `.ci/`; the rule is a few
  lines.

## Scope-shift 2026-11-05

Decided at the checkpoint after the first version:

- **The CI side is checked as well.** `CI_JOBS` in the test module holds the number of jobs; a test in
  `test_ci_config.py` (which runs in `py_test`, where PyYAML is installed; the job `visualization_test` has only
  Playwright) checks that `parallel` of `visualization_test` equals it and that the job's script sets
  `VISUALIZATION_JOB="$CI_NODE_INDEX/$CI_NODE_TOTAL"` on the line that runs the module. A wrong but valid value, e.g. a
  fixed "1/3", would otherwise skip the pages of the other jobs and leave the pipeline green.
- **The pages with sound are spread evenly over the CI jobs.** A test checks that each job tests at least one page
  with sound and that no two jobs differ by more than one such page. The number of jobs stays three: a new page, with
  or without sound, needs no change to the CI configuration, and all jobs grow evenly. (Until 2026-11-10 the test
  demanded exactly one page with sound per job, so that every new page with sound needed a change of `parallel` and
  `CI_JOBS`; the fourth page with sound, Yannakakis, showed that this does not scale.) If the jobs get too long,
  weights per page (deferred above) or a fourth job are the next step.

<!-- notes below: skill never overwrites past this marker -->
