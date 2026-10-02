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

_None currently._ Both earlier items were resolved by the migration to uv: black is pinned via
`pyproject.toml` / `uv.lock` and run with `uv run black`, and the pipenv caching limitation no longer
applies because uv installs into the project's own `.venv/`.
