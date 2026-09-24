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

- The CI runner image installs `black[jupyter]` **unpinned**. A rebuild drifted it to black 26.5.1,
  which reformats several files differently and broke `black --check`. The repository was reformatted
  to 26.5.1 as a stopgap. Durable fix: pin black in the CI image so it can no longer drift (ties in
  with the deferred uv migration, MR !61).
- Caching the pipenv virtualenv in CI does **not** work with the current image: it pre-activates an
  external virtualenv (`ENV VIRTUAL_ENV /venv`), so `pipenv install` installs outside the project and a
  GitLab `cache` of `.venv/` captures nothing. The ~115s per-job install therefore cannot be cached away
  without changing the image (or migrating to uv, MR !61).
