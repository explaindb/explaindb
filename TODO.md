# TODO

Living list of known issues and technical debt in this repository.

## Broken notebooks (excluded from CI)

Notebooks live in the `notebooks/` directory. A notebook that currently fails when executed is renamed
with a `.broken` suffix so the CI `*.ipynb` glob (see `.ci/assign_notebooks.py`, run from `notebooks/`
by the `ipynb_test` job) and `black --check` skip it. Fix the underlying issue, then rename the file
back to `.ipynb`.

_None currently._ (`Bitmaps-and-Bloom-Filters.ipynb` was fixed — the WAH iterator no longer recurses
per 0-fill word; see the regression test `test_iterating_sparse_wah_does_not_overflow_recursion`.)

## CI / tooling debt

- **Node.js of the type check lags behind its security releases.** pyright runs on Node.js from the package
  `nodejs-wheel-binaries`, locked at 24.19.0, the newest build on PyPI on 2026-11-25; Node 24.22.1 (2026-10-20) and
  24.22.3 (2026-11-10) fix security issues. pyright uses none of the affected parts (TLS, DNS, HTTP, Brotli), and
  `dependency_audit` cannot report them, as it knows only advisories for PyPI packages. Once PyPI has a build with
  Node 24.22.3 or newer, run `uv lock --upgrade-package nodejs-wheel-binaries` (see `CONTRIBUTING.md`, section Type
  check).

Resolved earlier: the static type check is now the CI job `type_check` (see `CONTRIBUTING.md`, section Type
check); with the migration to uv, black is pinned via `pyproject.toml` / `uv.lock` and run with `uv run black`, and
the pipenv caching limitation no longer applies because uv installs into the project's own `.venv/`.

## Follow-ups waiting for other changes

- **MVCC playground and issue #53** (a delete of an object that is not visible to the transaction raises
  `KeyError`): once #53 is merged, revisit the error verdict of `run_to` in `system/playground/mvcc_playground.py`
  and its test, and the serial-replay oracle and schedule spaces of the serializability test, which replay a delete
  of an absent object as a no-op.
