# 002 — Audit locked dependencies for known vulnerabilities in CI
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/114
---
## Context

Before the Binder launch (001-binder-launch), a manual `pip-audit` run found 10 known
vulnerabilities in four indirect dependencies pinned in `uv.lock` (jupyterlab, notebook,
tornado, urllib3). Nothing in CI would have noticed them. Since Binder exposes the Jupyter
server publicly, known vulnerabilities in the locked versions should be caught automatically.
The GitLab project has "Pipelines must succeed" enabled, so a failing job blocks merging.

## Decision

A CI job `dependency_audit` exports the locked dependency set from `uv.lock` (with
`--frozen`: it audits exactly what `uv.lock` pins; detecting a lockfile that is out of date
with `pyproject.toml` stays the job of `binder_requirements`) and runs
`pip-audit==2.10.1 --strict --no-deps --disable-pip` on it via `uv tool run`. Any finding,
and any package that cannot be audited (`--strict`), fails the job and thereby the
pipeline. This was the user's explicit choice over a warning-only job. There is no scheduled
run; the job runs in every pipeline except Markdown-only merge requests.

pip-audit is not added as a project dependency, so it stays out of `uv.lock` and the Binder
image. For advisories without a fix or false positives, the escape hatch is an
`--ignore-vuln <ID>` flag in the job with reason and date, to be removed as soon as a fixed
version exists. `CONTRIBUTING.md` explains how to fix a finding: `uv lock --upgrade-package`
for indirect dependencies, raising the `==` pin in `pyproject.toml` for direct ones, then
re-exporting `.binder/requirements.txt`.

## Consequences
**Positive:** Known vulnerabilities in the locked versions block merging instead of being
found by chance; the job takes seconds.
**Negative:** A newly published advisory turns every pipeline red, including merge requests
unrelated to dependencies, until a bump is merged. On `main` this also skips the GitLab
Pages deploy of the API docs until then (accepted by the user). An outage of the PyPI
vulnerability service can cause a spurious failure (retry the job). Platform markers are
evaluated on the Linux runner, so Windows- or macOS-only packages are not audited in CI.
pip-audit's own dependencies are resolved fresh on each run, so the tool itself is not
fully reproducible. Without a schedule, advisories published during quiet phases are only
noticed with the next pipeline.

## Out of scope & deferred
- Scheduled (e.g. weekly) audit pipeline — declined for now by the user.
- Minimum versions via `[tool.uv] constraint-dependencies` to prevent falling back to
  vulnerable versions.
- Hashes in the exported requirements.
- Decoupling the `pages` deploy from the audit job via `needs`.

## Alternatives rejected
- Warning only (`allow_failure`): the user wants findings to block merging.
- pip-audit as a project dependency: it would land in `uv.lock` and the Binder image.
- Auditing `.binder/requirements.txt` instead of an export of `uv.lock`: couples the audit
  to Binder; both are kept identical by `binder_requirements` anyway.
- GitLab Dependency Scanning: tied to a higher GitLab tier and heavier to set up.
- osv-scanner: an additional non-Python binary; pip-audit is already proven on this project.
- safety: requires an account and has its own licence terms.

## Scope-shift 2026-10-02

After review, two hardening steps were added to the job. First, pip-audit's own
dependencies are pinned by date with `uv tool run --exclude-newer <date>`, so the tool
setup is reproducible; this replaces the earlier "resolved fresh on each run" trade-off.
The date has to be moved deliberately (together with the pip-audit pin) to pick up fixes
in those dependencies. Second, the job retries once on a script failure, so a short
outage of the download or vulnerability service no longer fails the pipeline by itself;
a real finding fails both attempts, so the retry cannot hide it.

<!-- notes below: skill never overwrites past this marker -->

Note 2026-10-02 (evidence): with the pre-bump `uv.lock` from commit 1f3de9c pushed as a
temporary commit (since dropped from the branch), the real GitLab job failed as intended:
https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/543187 — uv 0.11.25,
pip-audit 2.10.1, "Found 10 known vulnerabilities in 4 packages" (jupyterlab, notebook,
tornado, urllib3); `binder_requirements` failed too, as expected. The red result is
reproducible at any time; a green result only holds for the day it ran.

Note 2026-10-02: the revised script (with `--exclude-newer` and the retry) was re-checked
locally against the `uv.lock` from 1f3de9c (exit 1, the same 10 findings) and against
current `main` (exit 0).
Green on the MR head 35b2934 (same job script as the final one, later commits only touch
comments and docs): https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/543215

Note 2026-10-02: after 35b2934 the job script changed once more, but only the format of
the `--exclude-newer` cutoff (from a bare date to the UTC timestamp `2026-10-01T00:00:00Z`).
Green with the final script on commit 5543cae (the last change to the job script; full
pipeline green): https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/543254
