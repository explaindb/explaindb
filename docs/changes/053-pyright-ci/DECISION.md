# 053 — Type check of system/ with pyright in CI
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/313
---
## Context

A series of merge requests brought the errors that pyright reports for `system/` from 705 to 0. Until now pyright ran
only by hand, as `uvx pyright --pythonpath .venv/bin/python system` (pyright 1.1.414 from PyPI, or whichever version
`uvx` picks), so new type errors could come back unnoticed. The user wants a CI job that fails on any error and gives
the same result as the developers' local run; a baseline that tolerates old errors was rejected.

Facts that shaped the decision (checked with pyright 1.1.414 on 2026-11-25):

- Without a configuration, pyright runs in its default mode `standard`, not `basic`. `basic` reports 31 errors fewer
  on the same code (`reportIncompatibleMethodOverride`, `reportIncompatibleVariableOverride`); the series worked in
  `standard`.
- The PyPI package `pyright` contains pyright itself but needs Node.js. It takes Node from the package
  `nodejs-wheel-binaries` if installed (the extra `pyright[nodejs]`), otherwise a `node` on the `PATH`, otherwise it
  downloads Node from nodejs.org on first use. The runners' image `materials-ci` (Python 3.12, uv) has no Node.
- pyright analyses the Python environment of the `python3` first on the `PATH`, which `uv run` sets to the project's
  environment. The packages in it change the result: without the group `browser-tests`, the imports of Playwright in
  `system/tests/repo/` cannot be resolved (6 more errors).
- pyright reads a `pyrightconfig.json` from the current folder or any folder above it in preference to
  `pyproject.toml`, and skips a `pyproject.toml` without a section `[tool.pyright]`.
- Several configurations make pyright report no error and exit with 0 although the code has errors: a misspelled
  path in `include`, an `exclude` or `ignore` that covers it, or the mode `off`.

## Decision

- **Tool and version:** `pyright[nodejs]==1.1.414` (the version the series used) in a new dependency group
  `type-check` in `pyproject.toml`, locked with hashes in `uv.lock`. Node comes from PyPI as a locked package, so the
  job downloads only from PyPI, like every other uv job, and local runs use the same pyright and Node. Like
  `browser-tests`, the group is not a default group: `uv sync` does not install it, the export for Binder leaves it
  out, and `dependency_audit` (`--all-groups`) audits its PyPI packages. pyright and `nodejs-wheel-binaries` are
  raised together at least once per semester, as the audit does not see Node's own security fixes.
- **Configuration:** a section `[tool.pyright]` in `pyproject.toml` with `include = ["system"]`,
  `typeCheckingMode = "standard"` (the mode in which the series reached 0, stated so that a new pyright version
  cannot change it unnoticed; the user had asked for `basic` and chose `standard` once the difference was shown) and
  `pythonPlatform = "Linux"` (the runners' platform, so that a run on macOS gives the CI result). The Python version
  comes from the environment, which uv builds for `requires-python`; no `venv` is configured, as `uv run` already
  selects the environment.
- **One command, locally and in CI:**
  `uv run --locked --isolated --all-groups pyright --project pyproject.toml --stats`, from the repository root.
  `--locked` stops with an error instead of updating an out-of-date `uv.lock`; `--isolated` runs pyright in a fresh
  environment built from `uv.lock`, as in CI, and leaves the developer's `.venv` as it is; `--all-groups` installs
  every group, so that every package that `system/` imports resolves. `--project pyproject.toml` makes pyright read
  only this file, never a `pyrightconfig.json` above the checkout; `--stats` prints the pyright and Python versions
  and the number of files checked. CONTRIBUTING.md documents the command in a section "Type check", together with
  how to fix an error, how to suppress a wrong one (preferably `# pyright: ignore[<rule>]`, naming the rule;
  `# type: ignore[...]` only where black would split the line so that a `pyright: ignore` comment no longer sits on
  the reported line) and how to raise the version.
- **CI job `type_check`:** in stage `test`, in the default image, extends `.not_in_scheduled_pipelines` (so
  `system/tests/repo/test_ci_config.py` accepts it without a change), skips Markdown-only merge requests
  (`DOCS_ONLY`) and runs the command. Unlike the jobs that install with `--frozen`, it uses `--locked`, to run exactly
  the developers' command; for an out-of-date `uv.lock` it thus fails together with `binder_requirements`.
  `PYRIGHT_PYTHON_IGNORE_WARNINGS=1` stops the query for a newer version on PyPI. Any error fails the job; warnings do
  not. No cache, no retry, no `allow_failure`, interruptible.
- **Tests:** a repository test checks `[tool.pyright]`: it holds only `include`, `typeCheckingMode` and
  `pythonPlatform` (so no `exclude`, `ignore`, `extends` or switched-off rule), `include` names `system`, every path
  in it is a folder with Python files and not a hidden folder (which pyright skips), the mode is `standard` or
  `strict`, and the repository root has no `pyrightconfig.json`. Its checks are also run on hand-written
  configurations, one for each kind of problem. A second test checks that the section "Type check" of
  CONTRIBUTING.md shows the very command the job runs, and a third that the group `type-check` pins
  `pyright[nodejs]` to one exact version. As the second test reads CONTRIBUTING.md, a merge request that
  changes only CONTRIBUTING.md no longer counts as docs-only (like one that changes README.md).
- `.claude/CLAUDE.md` asks to run the type check before every push, as it does for black.
- Job, group, configuration, tests and documentation come in one merge request, merged after the last merge request
  of the series; its own pipeline shows 0 errors.

## Consequences
**Positive:** A type error in `system/` blocks the merge request, and the log names file, line and rule. Developers
run the same command as the job, in an environment like the job's, and get its result. The version is raised in one
place, and Binder is unchanged.
**Negative:** Each pipeline runs one job more on the runner's four job slots (an estimated minute; to be measured in
the first pipeline), and it downloads about 100 MB more than `formatting` (Node and Playwright's Python package).
A merge request that changes only CONTRIBUTING.md now runs all test jobs. Raising pyright can bring new errors that
must be fixed in the same merge request. Node's own vulnerabilities are not reported by `dependency_audit`, which
knows only advisories for PyPI packages; Node 24.19.0, the newest build on PyPI on 2026-11-25, already misses two
security releases of Node (TODO.md). A file-level `# pyright: basic` or a
`# type: ignore` can still weaken the check, which only reviewers catch. The local run also checks untracked files
in `system/`. VS Code with Pylance reads the section too and then shows standard-mode errors, also in open notebooks,
with its own pyright version and extra stubs, so its errors can differ from the job's.

## Out of scope & deferred
- Notebooks (`nbqa pyright`; 64 errors and 8 warnings on 2026-11-25).
- More folders: `docs/api` (0 errors), `.ci` (0 errors; pyright 1.1.414 skips hidden folders even when they are
  included), `tools` (6 errors).
- Failing on warnings (`--warnings`; 3 warnings on 2026-11-25).
- A GitLab Code Quality report from `pyright --outputjson`.
- Stricter suppressions: `reportUnnecessaryTypeIgnoreComment`, ignore comments that must name a rule, and the three
  older mypy-style `# type: ignore[...]` comments in `system/tests/` (not needed for black) turned into
  `# pyright: ignore[<rule>]`.

## Alternatives rejected
- basedpyright: its defaults differ (mode `recommended`, platform `All`, `.venv` picked automatically) and it reports
  some rules differently even in `standard`, so it cannot reproduce the result of pyright.
- `npx pyright@<version>` in a Node image: the image has neither Python nor the project's packages, so imports do not
  resolve; a second registry and image.
- The PyPI package without the extra `nodejs`, as `uvx pyright` today: it downloads an unpinned Node from nodejs.org
  on every CI run.
- `uv tool run --from 'pyright[nodejs]==…'`, as for pip-audit: Node is neither locked nor audited.
- pyright in `[project].dependencies` or in the default group `dev`: it would reach Binder or every job's `uv sync`.
- Node in the runner image `materials-ci` or from Debian: manual rebuilds, version not pinned with the project.
- Running in the developer's `.venv` (`uv run --exact`): it would remove packages from the `.venv` that git worktrees
  share, and installing all groups there leaves Playwright behind, so that the browser tests no longer skip.
- Command-line flags instead of `[tool.pyright]`: the settings would be repeated in the job and in CONTRIBUTING.md,
  and editors would not see them.
- `typeCheckingMode = "basic"`: weaker than the local run the series used.
- mypy: another checker with other errors; the series reached 0 under pyright.
- A unit test that runs pyright inside `py_test`: every test environment would need pyright and Node.
- A step in the job `formatting`: a type error would read as a formatting failure.
- A baseline that tolerates old errors: rejected by the user.

<!-- notes below: skill never overwrites past this marker -->
