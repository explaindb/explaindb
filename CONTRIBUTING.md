# Contributing to ExplainDB

## Code formatting

All Python code is formatted with [black](https://black.readthedocs.io) using its
default settings. The CI pipeline runs `black --check .` and rejects unformatted
code, so run `black .` before every push.

## Dependencies

Dependencies are managed with [uv](https://docs.astral.sh/uv/) in `pyproject.toml`
and `uv.lock`. mybinder.org cannot read `uv.lock`, so `.binder/requirements.txt` is
an export of it. After every dependency change, regenerate it (the CI job
`binder_requirements` fails if you forget):

```sh
uv export --frozen --no-dev --no-hashes --no-header --no-annotate --format requirements.txt -o .binder/requirements.txt
```

### Security audit

The CI job `dependency_audit` runs [pip-audit](https://pypi.org/project/pip-audit/) on
the versions pinned in `uv.lock` and fails if any of them has a known vulnerability.
To fix a finding, move the affected package to a fixed version:

- If the package is an indirect dependency (not listed in `pyproject.toml`), run
  `uv lock --upgrade-package <package>`.
- If it is listed in `pyproject.toml` with an exact `==` pin, raise the pin there and
  run `uv lock`. Do the same if such a pin prevents an indirect dependency from moving
  to its fixed version.

Then regenerate `.binder/requirements.txt` with the command above. To reproduce the
check locally, run the `uv export` and `uv tool run` commands of the `dependency_audit`
job in `.gitlab-ci.yml`.

If no fixed version exists yet, or the finding is a false positive, append
`--ignore-vuln <ID>` to the pip-audit command in that job, where `<ID>` is the
vulnerability ID from the job log (for example `GHSA-…` or `PYSEC-…`). Put a comment
above the command giving the reason and the date, and remove the entry again as soon
as a fixed version is available. (A failing job blocks merging because the GitLab project
setting "Pipelines must succeed" is enabled.)

## Notebooks

The notebooks live in `notebooks/`. When you add, rename or remove one, also update:

- the notebook table in the README (section *Notebooks*): one row with the link, a
  one-line topic and the Binder badge. `system/tests/test_readme_notebooks.py` fails if
  the table and `notebooks/` disagree.
- `.ci/notebook_weights.tsv` (the notebook's run time, used to balance the parallel CI
  jobs) and the expected packing and notebook count in
  `system/tests/test_assign_notebooks.py`, which fails otherwise.

## API documentation

An HTML API reference is generated from the source docstrings with
[Sphinx](https://www.sphinx-doc.org). On every push to the default branch the CI
pipeline publishes it to GitLab Pages; the published site is reachable via the
project's **Deploy → Pages** page and is restricted to project members. The public
copy is at <https://bigdata.uni-saarland.de/software/explaindb/index.html>.

To build it locally:
```sh
uv run sphinx-apidoc --implicit-namespaces --no-toc --force --separate -o docs/api system system/tests
uv run sphinx-build -W -b html docs/api docs/api/_build
```
Then open `docs/api/_build/index.html`. The `sphinx-apidoc`-generated stubs and
the `_build/` output are git-ignored; the CI check (`docs_build`, run on every
merge request) builds with `-W` so any documentation warning fails the pipeline.

## Docstring conventions

We document code so that the *contract* lives in one place and implementations
only describe what they add. This keeps overrides free of redundant copies of
the interface documentation.

### Where the contract lives

- **Interfaces and abstract base classes** carry the full contract. Use Javadoc
  style with `@param` and `@return`, as in
  [`system/interfaces/indexing/Index.py`](system/interfaces/indexing/Index.py).
- The docstring on the abstract method is the single source of truth for what
  the method promises.

### Implementations document the delta

- An **override that follows the interface contract exactly** gets a short
  reference only — do *not* repeat the contract:

  ```python
  def put(self, key, value):
      """See :meth:`Index.put`."""
      ...
  ```

- An **override that specializes or changes behaviour** references the contract
  and then states what is special or different in this implementation:

  ```python
  def get_equal(self, key):
      """See :meth:`BitmapIndex.get_equal`.

      Equality-encoded variant: returns the stored bit sequence for the key
      directly instead of OR-ing a range.
      """
      ...
  ```

### Dunder methods

- Document only the **non-trivial** dunder methods — those with real logic or
  special rules:

  ```python
  def __eq__(self, other):
      """Equal iff same bits AND same represented length."""
      ...
  ```

- Skip trivial delegating dunders where Python's semantics are self-explanatory.

### Modules

- Every module gets a one-line module docstring describing its purpose.

### Summary

| Kind | Docstring |
| --- | --- |
| Interface / abstract method | Full contract (`@param` / `@return`) |
| Override, no behaviour change | `See :meth:`...`` reference only |
| Override with a delta | Reference + what is special / changed |
| Non-trivial dunder | Short description of the logic |
| Trivial dunder | None |
| Module | One-line purpose |
