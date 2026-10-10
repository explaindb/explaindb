# 007 — Secret detection in CI with Gitleaks
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/140
---
## Context

Nothing in the CI checks whether a commit adds a secret (password, API token, private key). Job logs of this
project are readable by every logged-in user of the GitLab instance, merging requires a green pipeline, and the
repository is meant to become public (AGPL, Binder). The sibling project mastersystem already gates merge requests
with a diff-aware Gitleaks job (its changes 056); this feature takes it over. A full scan of the history (all
branches, 265 commits, Gitleaks 8.30.1, default rules) found no secrets, so no allowlist is needed now.

## Decision

- A job `gitleaks_secret_detection` runs in merge-request pipelines only, in the pinned official image
  (`zricethezav/gitleaks:v8.30.1`), and scans only the merge request's own commits: from the merge base with the
  target branch to HEAD. The target branch is fetched explicitly first, so the merge base is up to date.
- It runs for every merge request, also for ones that only change Markdown, as secrets can be in any file.
- `--redact` keeps a found secret out of the job log and the report; the report (with the fingerprints needed to
  accept a false positive) is kept as an artifact for a week.
- Gitleaks' default rules apply, without a configuration file. A false positive is accepted with a `gitleaks:allow`
  comment on the same line or with its fingerprint in `.gitleaksignore`; CONTRIBUTING.md explains both.
- One retry on a script failure, as for the dependency audit, since the job fetches from GitLab.

## Consequences
**Positive:** A secret committed in a merge request blocks the merge, without being shown in the public job log.
Old commits never block a merge request.
**Negative:** Secrets already in the history before the merge base are not checked by the job (the full scan above
covers today's history). The job uses an image other than the project's default; if the runner does not allow it,
the configuration must change. Gitleaks' rules can miss secrets without a known format.

## Out of scope & deferred
- Semgrep static analysis (feature 008, separate merge request).
- A full-history scan in a nightly pipeline.
- A local script to run the same scan before pushing (mastersystem has one).

## Alternatives rejected
- GitLab's built-in Secret Detection template: blocking the merge on findings needs the Ultimate tier.
- Scanning the whole history in every merge request: old commits could block unrelated merge requests, and the
  full scan is already done once.
- Without `--redact`: a found secret would end up in the job log, which every logged-in user can read.

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-10 (verified in CI):** the runner pulls the Gitleaks image. The job passed on the merge request's
own commit (1 commit scanned) and failed on a throwaway commit with a fake GitHub token (rule `github-pat`, 2 commits
scanned), showing `REDACTED` instead of the token in the log; the throwaway commit was dropped again.

**Note 2026-10-10 (review):**
- Merge commits: plain `git log -p` shows no changes for merge commits, so a secret added while resolving a
  conflict was not scanned (reproduced locally). The job now passes `--remerge-diff` (git 2.36 or newer).
- The job passes a fixed configuration with only the default rules, so a `.gitleaks.toml` in a merge request
  cannot switch rules off; `gitleaks:allow` comments and `.gitleaksignore` entries still apply and are checked by
  reviewers.
- The image is pinned by tag and digest.
- The JSON report of the red run was checked as well: `Match` and `Secret` are `REDACTED`, the token appears
  nowhere in it.
- Known limits: secrets in commit messages or in the merge request description are not scanned. A merge request
  from a fork runs its pipeline in the fork (where no runner with the tag `test` exists); a maintainer runs it in
  this project.
- The sibling project's job is in mastersystem's `pipelines/base.yml` (`gitleaks-secret-detection`).

**Note 2026-10-10 (final job verified in CI):**
- Green: https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/547371 (as of d3a377b; gitleaks' own summary
  line: 3 commits scanned, no leaks).
- Red: https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/547400. Throwaway commits on top of 423e560:
  a `.gitleaks.toml` that allowlists every path, and a merge commit that adds a fake GitHub token (`ghp_` plus 36
  random letters and digits) while merging. The job found it anyway (rule `github-pat`, 7 commits scanned,
  `Secret: REDACTED`), so both `--remerge-diff` and the fixed configuration work. The throwaway commits were
  dropped again.
- This replaces "without a configuration file" in the Decision section: the job writes a fixed configuration with
  only the default rules. Job logs are not public on the internet but readable by every logged-in user of the
  instance (the "public job log" in the Consequences section).

**Note 2026-10-10 (stage):** the job runs in the stage `prepare` instead of `test`: it takes less than a minute, and
if it finds a secret the expensive test stage (`py_test`, `ipynb_test`) does not run at all. In exchange, a merge
request with a finding gets no test results until the finding is fixed.

**Note 2026-10-10 (final review):**
- `.gitattributes`: an entry such as `* -diff` (or a common `*.ipynb -diff`) in a merge request hides file contents
  from `git log -p`, so gitleaks skipped them and a token passed (reproduced locally). The job now sets
  `GIT_ATTR_SOURCE` to git's empty tree, so the repository's attributes are ignored (git 2.42 or newer; the image
  has 2.49.1); with it, the reproduced token is found again.
- Merges of three or more branches ("octopus" merges) fail the job, as `--remerge-diff` cannot show their changes.
- The red CI run above was checked locally on the same throwaway commits: without `--config`, the throwaway
  `.gitleaks.toml` in the checkout hides the token ("no leaks found"); with the fixed configuration it is found,
  in the merge commit 7f74760 (neither parent contains it).
- Merge trains and merged-results pipelines are off in this project; with them, HEAD would be a merge commit that
  GitLab creates anew for each pipeline.

**Note 2026-10-10 (final review, 2):**
- Green CI run at 79d4e92: https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/547463 (gitleaks'
  summary: 7 commits scanned, i.e. all commits of the merge request at that point; no leaks). The earlier "3
  commits scanned" at d3a377b was likewise the merge request's commit count then.
- The local checks above used git 2.45.0 and gitleaks 8.30.1. The octopus guard was run in its failing case on a
  throwaway three-parent merge: it printed its message and exited with status 1.
- Known limits of Gitleaks itself: files that git detects as binary (e.g. a text file with a NUL byte, or UTF-16
  text) are not scanned, and the default rules skip some paths entirely (e.g. `*.svg`, `node_modules/`,
  `venv/lib/`, `lib/python3.x/`).
