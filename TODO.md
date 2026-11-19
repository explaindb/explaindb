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

- **No static type check in CI.** No type checker (e.g. pyright or mypy) runs in the pipeline, and none is listed
  in `pyproject.toml` or `CONTRIBUTING.md`. Type hints that contradict the code therefore go unnoticed, e.g. a
  method annotated to return a tuple that returns `None`. Before a type check can become a CI job for `system/`,
  the errors it reports today have to be fixed or recorded as a baseline.

The two earlier items were resolved by the migration to uv: black is pinned via `pyproject.toml` / `uv.lock` and
run with `uv run black`, and the pipenv caching limitation no longer applies because uv installs into the project's
own `.venv/`.

## Follow-ups waiting for other changes

- **MVCC playground and issue #53** (a delete of an object that is not visible to the transaction raises
  `KeyError`): once #53 is merged, revisit the error verdict of `run_to` in `system/playground/mvcc_playground.py`
  and its test, and the serial-replay oracle and schedule spaces of the serializability test, which replay a delete
  of an absent object as a no-op.
