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

## Security checks

Besides the dependency audit above, the CI scans every merge request for secrets.

### Secret detection

The CI job `gitleaks_secret_detection` runs [Gitleaks](https://github.com/gitleaks/gitleaks)
on the commits of a merge request (not on older commits) and fails if one of them adds a
secret, such as a password, an API token or a private key. The job log lists each finding
with its file, line, rule and fingerprint, with the secret itself replaced by `REDACTED`;
the job's artifact `gitleaks-report.json` holds the same.

If a real secret was committed:

1. Revoke or replace it right away and treat it as public: it may already have been copied,
   and older versions of the merge request still show it.
2. Remove it from the commit that added it, e.g. with `git rebase -i`, and force-push the
   branch; removing it in a later commit is not enough, as the job scans every commit.
3. Tell a project owner: until they redact the secret from the repository (Settings > Repository >
   Repository maintenance > Redact text) or delete the merge request, the old commit stays visible
   by its ID and in the merge request's older versions.

If a finding is a false positive, accept it in one of two ways:

- add the comment `gitleaks:allow` on the same line (e.g. `# gitleaks:allow` in Python), in the
  commit that adds the line (amend or rewrite that commit; a later commit does not change the
  earlier one), or
- add the finding's `Fingerprint` from `gitleaks-report.json` as a line to the file
  `.gitleaksignore` in the repository root. The fingerprint contains the commit ID, so after
  a rebase, amend or squash, take the new fingerprint from the new report. (For a file that had
  a merge conflict, the path in the fingerprint starts with `b/`; copy it as it is.) Reviewers
  accept only entries that start with a commit ID: Gitleaks also accepts the short form
  `path:rule:line`, but that would hide every later secret at that place, too.

Reviewers check every new `gitleaks:allow` comment and `.gitleaksignore` entry. The job fails
on a merge of three or more branches ("octopus" merge), which it cannot scan; use normal merges
instead.

To run the check locally with [Gitleaks installed](https://github.com/gitleaks/gitleaks#installing)
and git 2.42 or newer, update `origin/main` (or the merge request's target branch) and scan the
commits that are not yet on it. Like the CI job, the commands use only Gitleaks' default rules and
ignore a `.gitleaks.toml` and the `.gitattributes` in the repository (`GIT_ATTR_SOURCE` points
to git's empty tree, a fixed ID that git uses for an empty directory):

```sh
git fetch origin
printf '[extend]\nuseDefault = true\n' > /tmp/gitleaks.toml
GIT_ATTR_SOURCE=4b825dc642cb6eb9a060e54bf8d69288fbee4904 gitleaks git . --log-opts="--remerge-diff origin/main..HEAD" --config /tmp/gitleaks.toml --redact --verbose
```

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
