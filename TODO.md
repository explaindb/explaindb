# TODO

Living list of known issues and technical debt in this repository.

## Broken notebooks (excluded from CI)

Notebooks that currently fail when executed are renamed with a `.broken` suffix so the CI `*.ipynb`
glob (see `.gitlab-ci.yml`, `ipynb_test`) and `black --check` skip them. Fix the underlying issue,
then rename the file back to `.ipynb`.

- **`Bitmaps and Bloom Filters.ipynb.broken`** — `RecursionError: maximum recursion depth exceeded`,
  raised in `system/interfaces/bit_sequence.py` (`_out_of_bounds` calls `len(self)`, which cycles back
  through `get_bit_sequence_for_range`). Reproducible locally with the pinned dependency versions
  (numpy 2.1.3, pandas 2.2.3, Python 3.12), so it is a genuine code bug, not dependency drift. The last
  green pipeline for this notebook was in January 2025; the bug should be fixed via `/fix-bug`
  (reproduce, add a red regression test, fix, verify green).

## CI / tooling debt

- The CI runner image installs `black[jupyter]` **unpinned**. A rebuild drifted it to black 26.5.1,
  which reformats several files differently and broke `black --check`. The repository was reformatted
  to 26.5.1 as a stopgap. Durable fix: pin black in the CI image so it can no longer drift (ties in
  with the deferred uv migration, MR !61).
- The **pipenv → uv** migration is prepared but deferred (MR !61, Draft). It is blocked on a manual
  rebuild of the CI runner image (`docker compose build materials-ci`), which needs the runner-host
  admin.
- The committed **`Pipfile.lock` is stale** relative to `Pipfile` (the CI log shows
  `Pipfile.lock (...) out of date, updating to (...)`). As a result `pipenv install` re-resolves and
  re-locks on every CI run, which is slower and non-reproducible. Fix: regenerate and commit a fresh
  `Pipfile.lock` (`pipenv lock`) so installs use the committed lock as-is. Superseded anyway once the uv
  migration (MR !61) lands, where `uv.lock` is the checked lock.
- Caching the pipenv virtualenv in CI does **not** work with the current image: it pre-activates an
  external virtualenv (`ENV VIRTUAL_ENV /venv`), so `pipenv install` installs outside the project and a
  GitLab `cache` of `.venv/` captures nothing. The ~115s per-job install therefore cannot be cached away
  without changing the image (or migrating to uv, MR !61).
