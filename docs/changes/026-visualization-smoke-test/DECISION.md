# 026 — Browser smoke test for the visualizations
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/190
---
## Context

The pages in `visualizations/` are single HTML files whose logic is an inline script; they are opened directly in a
browser, with no build and no web server. No test ran them: a change that breaks a page (a JavaScript error, a
control that no longer works) was only noticed by opening it by hand. The elasticity page already sets `data-testid`
and `data-*` state attributes for tests; the page on MVCC validation had test ids on its controls only. The CI
runners use the docker executor with the default image `materials-ci` (Python 3.12 on Debian, uv, root). They should
not pull or keep large images from further registries, so the official Playwright image (about 1 GB to download,
about 3 GB on disk, from mcr.microsoft.com) is not an option. All Python packages so far are in
`[project].dependencies`, exported for Binder and audited by `dependency_audit`.

## Decision

- A browser test in `system/tests/repo/`, written with unittest and Playwright's sync API, opens every page from its
  file in a headless Chromium. Each test starts a fresh browser context that asks for reduced motion, so a page
  starts paused at time 0 instead of playing on its own; only the test of autoplay leaves this out.
- The tests record uncaught exceptions and console errors from before the page loads, and block and record every
  request (and WebSocket) to anything but a local file, so a page must work offline. They select elements only by
  `data-testid` and read the state of a page mainly from `data-*` attributes set by its script; besides these, from
  the slider's value and the state of buttons (pressed, enabled).
- Generic tests run on every page in the folder, so a new page is covered without tests of its own: it loads
  without errors and paused, with `narration[data-stop-type]=start` (set by the script, which proves that it ran);
  Next, clicked until `play[data-state]=ended` (at most 300 times), moves the slider on with every click up to its
  end, where `data-stop-type` is `end`; Play and Pause toggle `play[data-state]`; without reduced motion, the page
  starts playing on its own. This hook convention is documented in CONTRIBUTING.md.
- Page tests: on the elasticity page, Next shows the minute of the stop it narrates, switching the model while paused
  keeps the minute, the end stop carries the results of the day as whole numbers, and every model and size steps to
  the end without errors. On the validation page, Next and Back move between the start and the begin of T1, and the
  narration passes through begins, validations, commits, an abort and the end.
- The validation page gets the hooks the elasticity page has: `play[data-state]`, `data-testid` on the narration's
  time and text, and `narration[data-stop-type]` (the type of the current step; `start` and `end` as on every page).
- Playwright 1.64.1 is an exact pin in a dependency group `browser-tests`, which is not a default group: `uv sync`
  (and so `py_test`, where the tests are skipped) does not install it, and the Binder export (`--no-dev`) leaves it
  out. `dependency_audit` exports `--all-groups` instead of `--no-dev`, so the group is audited.
- A CI job `visualization_test` in the default image installs only the group (`uv sync --only-group`), then
  Chromium's headless shell and the system libraries it needs (`playwright install --with-deps --only-shell`), and
  runs the test module; `python -m playwright --version` before the tests fails loudly if Playwright is missing, so
  the tests cannot be skipped there. Because the pages are self-contained, the job runs only when a page, the test,
  `.gitlab-ci.yml`, `pyproject.toml` or `uv.lock` changes (`rules: changes`), never in scheduled pipelines, with a
  timeout of 10 minutes. It has no cache and no retry.

## Consequences
**Positive:** A merge request that breaks a page, or makes it load something from the network, fails, and the log
names the page, the step and the error. New pages get the generic checks for free. Merge requests that do not touch
the pages pay nothing, and the other jobs install nothing more. Binder is unchanged.
**Negative:** Every run downloads Playwright from PyPI, Chromium from Playwright's servers and the system libraries
from the Debian mirrors (about a minute), so a network problem fails the job and it has to be retried by hand. The
Chromium build and the Debian packages are not pinned by a checksum in the repository, and `dependency_audit` does
not check them; Playwright's Python package is audited, and bumping it (at least once per semester, like the other
pinned tools) moves Chromium along. `rules: changes` is a second way of skipping a job, next to `DOCS_ONLY`; on
main, the job runs only when a push touches the listed files. Pages must keep the hooks the generic tests use.

## Out of scope & deferred
- Checking that the validation page's verdicts and serial order equal the store's (a `data-serial-order` hook).
- Keyboard controls, Restart and the hover values of the elasticity page.
- Firefox and WebKit.
- A screenshot of the page as a job artifact when a test fails.
- Retrying only the download steps of the job.
- Visual comparison of screenshots.

## Alternatives rejected
- The official Playwright image, pinned by digest: the runners should not pull from mcr.microsoft.com or keep an
  image of about 3 GB.
- A GitLab cache for the downloaded browser (it would save about 15–30 s): GitLab shares caches between the
  branches of merge requests, so a browser planted by one merge request would run in the job of another, and
  `playwright install` does not check it again. A cache key per branch does not help, as a merge request controls
  `.gitlab-ci.yml` and so its key.
- Playwright in `[project].dependencies`: it would reach Binder, and every job would install it.
- Baking Chromium into the runner image `materials-ci`: it needs a manual rebuild on the runner, and its version
  would drift from the one in `uv.lock`.
- pytest-playwright: the repository uses unittest.
- Playwright for Node (`@playwright/test`): adds an npm toolchain, a lockfile and an npm audit.
- jsdom: no real layout or SVG; Selenium: heavier and more prone to timing failures.
- A syntax check of the scripts only: misses runtime errors and broken controls.
- Retrying the whole job on a failure: it would also run a failing test a second time.

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-28 (verified in CI):** In the first pipeline of MR !190 (155950), `visualization_test` passed in 52 s
(https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/jobs/558129). Installing took about 30 s, half the
estimate under Consequences: the group (Playwright, 46 MiB) in about a second; `playwright install --with-deps`
installed 65 Debian packages (82 MB) in `materials-ci` (python:3.12.6) and downloaded the headless Chromium (120
MiB) and FFmpeg. The 10 tests of the POC took 15 s. The job waited in `pending` until one of the runners' job slots
was free. In the same pipeline, `dependency_audit` audited playwright, pyee and greenlet without a finding (job
558120), `binder_requirements` passed with `.binder/requirements.txt` unchanged (558119), `semgrep_sast` scanned the
script of the changed validation page with no finding (558117), and `py_test` skipped the browser tests (558122).
