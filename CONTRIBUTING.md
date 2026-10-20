# Contributing to ExplainDB

## Code formatting

All Python code is formatted with [black](https://black.readthedocs.io) using its
default settings. The CI pipeline runs `black --check .` and rejects unformatted
code, so run `black .` before every push.

## Tests

The unit tests live in `system/tests/`, whose folders mirror the packages of `system/`: the tests of
`system/stores/` are in `system/tests/stores/`, and the tests of modules directly in `system/` (e.g.
`system/DBMS.py`) are directly in `system/tests/`. Tests that check the repository itself (CI configuration,
notebooks and the README, the Javadoc hook of the API documentation in `docs/api/javadoc.py`) are in
`system/tests/repo/`. Every test folder below `system/tests/` needs an `__init__.py`; without it,
`unittest discover` silently skips its tests. Run all tests with:

```sh
uv run python -m unittest discover system/tests/
```

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

The CI job `rust_dependency_audit` does the same for the Rust code: it runs
[cargo-audit](https://crates.io/crates/cargo-audit) on the versions pinned in
`generated/rust/Cargo.lock` and fails if any of them has a known vulnerability in the
[RustSec advisory database](https://rustsec.org). Crates that are unmaintained (no longer
looked after) or unsound (can break Rust's memory safety when used in a certain way) are only
reported as warnings; yanked crates (withdrawn by their authors on crates.io) are not checked.
To fix a finding (the `cargo` commands run in `generated/rust/`): a dependency update is the one change
made directly in `generated/rust/`, in `Cargo.toml`, `Cargo.lock` and `rust-toolchain.toml`.

- For an indirect dependency, run `cargo update -p <crate>`; if `Cargo.lock` holds two
  versions of the crate, name the affected one: `cargo update -p <crate>@<version>`. If the
  fixed version is a new major version that the crate depending on it does not accept yet,
  update that crate instead.
- For a direct dependency, raise its version in `generated/rust/Cargo.toml`, then run
  `cargo update -p <crate>`.
- Finally, run `python3 .ci/check_generated.py --update-dependencies` from the repository root, so
  that the manifest `generated/rust/GENERATED_FROM.json` records the new hashes of these three files
  (and only of them). Otherwise `generated_rust_check` reports them as edited by hand and fails on
  main.

If no fixed version exists yet, or the finding is a false positive, append `--ignore <ID>`
(e.g. `--ignore RUSTSEC-2024-0001`) to the cargo-audit command in that job, with a comment
giving the reason and the date, and remove it again as soon as a fix is available. Besides
`--ignore <ID>`, the command may only take `--no-yanked`, `--file` with the lockfile and
`-D`/`--deny <kind>` (which makes it stricter); reviewers watch for any other option, as options
such as `--target-os`, `--url`, `--db` or `--no-fetch` can hide advisories, and
`system/tests/repo/test_ci_config.py` fails on them. Do not add a `.cargo/audit.toml` instead:
the job does not read it and fails if one exists, so that every ignored advisory is visible in
the job. If the job fails because cargo-audit cannot read the advisory database (a parse error,
not a finding), raise `CARGO_AUDIT_VERSION` and `CARGO_AUDIT_SHA256` in the job; the checksum is
listed on GitHub with the release asset `cargo-audit-x86_64-unknown-linux-musl-v<version>.tgz`.

To reproduce the check locally, install the version of `CARGO_AUDIT_VERSION` in the job and
run it from the repository root as below (add the job's `--ignore` options, if any):
cargo-audit then runs in an empty directory with an empty `CARGO_HOME`, so that, as in the
job, no `audit.toml` (of the repository, a shared `/tmp` or your own configuration) is read:

```sh
cargo install cargo-audit --version 0.22.2 --locked
( repo="$PWD"; cd "$(mktemp -d)" && CARGO_HOME="$(mktemp -d)" cargo-audit audit --no-yanked --file "$repo/generated/rust/Cargo.lock" )
```

## Security checks

Besides the dependency audit above, the CI scans every merge request for secrets and for
insecure code patterns.

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

### Static analysis

The CI job `semgrep_sast` runs [Semgrep](https://semgrep.dev) with the rulesets
`p/security-audit` and `p/python` and fails if the merge request introduces a new finding,
e.g. a call of `eval` or `pickle.load`, which can run arbitrary code on untrusted input.
Findings in older code do not fail the job. The job log lists each finding with its file,
line and rule. Code in `tests/` folders is not scanned, and the job is skipped when a merge
request only changes Markdown.

Semgrep cannot read notebooks, so the job writes the code cells of every notebook the merge
request changes to a Python file (`.ci/notebook_code.py`) and scans these in full: a finding
anywhere in a changed notebook fails the job, not only a new one. IPython syntax is turned into
Python first, keeping the Python code it runs (e.g. after `%time` or in a `%%time` cell). If
the result is still not valid Python, the job fails, as Semgrep would skip that code; the log
then names the notebook and shows the line that could not be read. For a finding, the log
names `/tmp/notebook_code/<path of the notebook>.py` and a line in that file; search the
notebook for the code shown in the log.

The code after `%timeit -s` and the bodies of cell magics such as `%%writefile` or
`%%script python3` are not scanned. A finding in `{...}` of a shell command or magic cannot be
suppressed, and a comment line above `%%timeit` makes the conversion fail; rewrite such code
as plain Python instead.

If the code is wrong, fix it. If it is intentional (as `eval` and `pickle` in the teaching
code of `system/` and of some notebooks), add `# nosemgrep: <rule>` on the line before the
finding, in the same file or notebook cell, with the rule ID from the job log, and above it a
comment that says why the code is safe:

```python
# the file was written by this program itself, so unpickling it is safe here:
# nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
for tup in pickle.load(f):
```

The job lists every added suppression in its log (for a changed notebook: all of its
suppressions), and reviewers check each one. Below that list it shows all findings, including
those the suppressions hide. The job fails if a suppression is not a comment line of its own
in exactly this form (e.g. a bare `nosemgrep` without a rule, or one at the end of a line of
code). It also fails if the merge request adds or changes a `.semgrepignore`, or changes a file
that matches a `.gitignore`, as both would remove files from the scan. Suppressions are checked
in Python files and notebooks only, not in other files Semgrep scans (e.g. YAML).

Semgrep has no rule set for Rust enabled, and its suppressions are not checked in `.rs` files:
the Rust code in [`generated/rust/`](generated/rust) is hardly scanned. This gap is accepted for now (see
[`docs/changes/011-rust-store-foundation`](docs/changes/011-rust-store-foundation/DECISION.md)).

To run the check locally, scan the changes that are not yet on `main`, then the notebooks you
changed:

```sh
git fetch origin
uv tool run --from semgrep==1.173.0 semgrep scan --metrics=off --config p/security-audit --config p/python --baseline-commit "$(git merge-base origin/main HEAD)"
rm -rf /tmp/notebook_code
uv run python .ci/notebook_code.py /tmp/notebook_code notebooks/<notebook>.ipynb
uv tool run --from semgrep==1.173.0 semgrep scan --metrics=off --config p/security-audit --config p/python /tmp/notebook_code
```

## Notebooks

The notebooks live in `notebooks/`. When you add, rename or remove one, also update:

- the notebook table in the README (section *Notebooks*): one row with the link, a
  one-line topic and the Binder badge. `system/tests/repo/test_readme_notebooks.py` fails if
  the table and `notebooks/` disagree.
- `.ci/notebook_weights.tsv` (the notebook's run time, used to balance the parallel CI
  jobs) and the expected packing and notebook count in
  `system/tests/repo/test_assign_notebooks.py`, which fails otherwise.

## Serializability test of the MVCC store

`system/tests/stores/test_mvcc_serializability.py` runs every schedule of a *schedule space*: a set of
schedules given by the initial state, the data operations, how many of them each transaction runs,
and how the transactions end. The regular test job runs every schedule of two short transactions
(one or two data operations each).

The larger spaces (three transactions, voluntary aborts, longer transactions) take about half an
hour locally (about two hours on CI). They run in the job `serializability_nightly` of the nightly
scheduled pipeline on main; in a merge request the job can be started by hand. Only this job,
`dependency_audit`, `rust_dependency_audit` and `generated_rust_check` run in scheduled pipelines:
every new CI job must extend `.not_in_scheduled_pipelines` (or start its own rules with the same
`schedule`/`never` rule), which `system/tests/repo/test_ci_config.py` checks. A job meant for
scheduled pipelines is added to `SCHEDULED_JOBS` in that test instead. To run the larger spaces
locally:

```sh
EXPLAINDB_NIGHTLY=1 uv run python -m unittest -v system.tests.stores.test_mvcc_serializability.NightlySerializabilityTest
```

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

## Rust code

The Rust port of the store core in [`generated/rust/`](generated/rust) is **generated** from the
Python code in `system/` and never edited by hand: change the Python code, then generate the Rust
code again (see
[`generated/rust/README.md`](generated/rust/README.md#generated-code-change-the-python-not-this-folder)).
Every generated file names its Python sources in its first line
(`// Code generated from ... DO NOT EDIT.`; only `Cargo.lock`, written by Cargo, and the manifest
have none), and its folders mirror `system/`. To see what changed in the Python sources of
out-of-date Rust files since they were generated, run
`python3 .ci/check_generated.py --diff [<file relative to generated/rust/> ...]`: it compares the
copies in [`generated/python_sources/`](generated/python_sources/README.md) with the current
sources. Regenerate every Rust file of a changed source, then record the new hashes with
`python3 .ci/check_generated.py --update`, which also stores a copy of each recorded source version
(copies are never deleted); commit the new copies with the Rust files. The CI job
`generated_rust_check` runs the check without `--update` and reports Rust files that are out of
date or were edited by hand, and missing or corrupt copies or other files in
`generated/python_sources/`; the job fails on main and in the nightly pipeline and
only warns in a merge request. A dependency or Rust version update is the one change made directly
in `Cargo.toml`, `Cargo.lock` and `rust-toolchain.toml`; record it with
`python3 .ci/check_generated.py --update-dependencies`, which rewrites only the entries of these
three files (`--update` would also record out-of-date or hand-edited Rust files as current). A later
regeneration keeps the versions in these files.

The generated code follows the same rules as the Python code, written the Rust way. The CI job
`rust_test` fails if one of these checks fails (run them in `generated/rust/`):

```sh
cargo fmt --check
cargo clippy --all-targets --locked -- -D warnings
RUSTDOCFLAGS="-D warnings" cargo doc --no-deps --locked
cargo test --locked
```

- **License header:** every `.rs` file starts, after its "Code generated" line, with the text of
  [`LICENSE header.txt`](LICENSE%20header.txt), with `//` instead of `#`.
- **Doc comments:** every item, private ones included, has a `///` doc comment, and every file a
  one-line `//!` module doc comment; the compiler rejects missing ones on public items, clippy
  (`missing_docs_in_private_items`) on private ones. Doc comments are Markdown,
  so instead of `@param` / `@return`, name the arguments in the text and use these sections:

  | Python docstring | Rust doc comment |
  | --- | --- |
  | `@param x: ...` | name `x` in the text |
  | `@return: ...` | say what the method returns in the text |
  | raises an exception | section `# Errors`, one line per error |
  | `assert` | section `# Panics` |
  | ``See :meth:`Index.put`.`` | ``See [`VersionedStore::put`].`` |

  clippy rejects a public function that returns a `Result`, or that calls e.g. `panic!`, `assert!`,
  `unwrap` or `expect` directly, without these sections; document other panics (e.g. of a
  called function) by hand. The contract lives on the trait; an implementation references it
  and states only its delta, as described in [Docstring conventions](#docstring-conventions).
- **Python names:** a Rust item whose name differs from the Python item it ports names it,
  e.g. "(Python: `WHERE_Clause`)", and every deviation from the Python behaviour is stated in its doc comment
  and listed in [`generated/rust/README.md`](generated/rust/README.md#deviations-from-python).
- **Tests:** one file per Python test file, at the mirrored place, e.g. `tests/stores/test_stores_basics.rs` for
  `system/tests/stores/test_stores_basics.py`, with the same test names in snake_case; each test folder in `tests/`
  has a `main.rs` that includes its test files (`tests/common/` only holds the shared `mod.rs`). The table in
  [`generated/rust/README.md`](generated/rust/README.md#which-python-test-became-which-rust-test) lists each Python
  test and its Rust counterpart.
- **Rust version:** the image tag of the job `rust_test`, the channel in
  [`generated/rust/rust-toolchain.toml`](generated/rust/rust-toolchain.toml) and `rust-version` in
  [`generated/rust/Cargo.toml`](generated/rust/Cargo.toml) name the same version; change all three together.
