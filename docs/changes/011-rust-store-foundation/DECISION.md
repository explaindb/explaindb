# 011 — Rust port of the store core: foundation
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/144
---
## Context

The Python code of ExplainDB is essentially an MVCC store; the query optimizer lives partly in the notebooks. A Rust
version of the store core allows benchmarks of the store and lets students read the same algorithms in a compiled,
statically typed language. The user chose the same repository (directory `rust/`, its own Cargo project and CI job),
no notebooks and no query optimizer, and a series of small merge requests:

| Part | Content |
|---|---|
| 1a (this feature) | Cargo project, CI job `rust_test`, predicates, `VersionedKeyValueStore`, their tests |
| audit | blocking `cargo audit` of the Rust dependencies, like `dependency_audit` (see 002) |
| 1b | `TransactionalKeyValueStore` (MVCC with journal), tests of `test_stores_basics.py` and `test_store_anomalies.py` |
| 2 | `IndexedTransactionalKeyValueStore`, port of the schedules of `system/playground/schedules.py`, serializability test |
| 3 | benchmarks: Python, Rust with a struct, Rust with a dynamic value enum, Rust with closure predicates |

Each part gets its own design and feature number when it is designed. This record holds the decisions that apply to
the whole series. The living material for readers of the code (mapping of Python to Rust, list of deviations, which
Python test became which Rust test) is in `rust/README.md`, not here.

## Decision

- **Generic value type.** The stores are generic over the value type, as Python's `KeyValueStore[Key, Value]` is;
  keys are `String`. The store traits use an associated type (`type Value`), since each store holds one value type;
  `Clause<V>` keeps a type parameter, since one clause type works for many value types. The user chose this over a
  dynamic value enum for performance (see *Alternatives rejected*).
- **Predicates.** `trait Clause<V>` with `WhereClause`, `Disjunction`, `TrueClause`, `FalseClause`.
  `WhereClause::new("a", "<", 0)` keeps Python's call shape and works for every value type that implements
  `Attributes`, which returns a field by name as a borrowed scalar (integer or string) without allocating.
  Comparisons behave as in Python: `==` and `!=` across types give false and true; ordering across types and a
  missing attribute panic, as Python raises. `Disjunction` stops at the first true clause, as Python's `any`.
- **Sanitizing.** The checks of `WHERE_Clause.sanitize` stay asserts with Python's messages and order. They are
  ASCII-only and reject empty names, which is stricter than Python's Unicode `isalpha`/`isalnum`: a deliberate
  deviation for a security check.
- **Errors.** Where Python raises, Rust returns `Result<_, StoreError>`; where Python asserts, Rust uses `assert!`.
  `get` of a key without a visible committed value (deleted, or its insert never committed) returns
  `StoreError::NotVisible`; Python crashes there. The key still exists for `put` and `size`, as in Python.
- **Inheritance becomes traits with default methods.** The methods a Python subclass inherits are default methods of
  a trait; a store implements only accessors to its state. Methods a later store overrides (abort, update, delete,
  validation) keep their default body also as a free function generic over the trait, because Rust has no `super()`,
  and so that an abort inside them reaches the override.
- **Internals are public.** The tests read and build the store's internals directly, as the Python tests do; the
  Rust tests are integration tests in `rust/tests/`, one file per Python test file.
- **Insertion order.** The store map is an `IndexMap`, so read results come out in Python's dict order.
- **Ownership.** Stores take values by move (Python deep-copies on write). Reads of the MVCC store will return owned
  copies, because `read_objects` changes the read set and borrowed results would lock the store; Python returns
  references. The benchmarks must state both.
- **Conventions enforced by the compiler and CI.** AGPL header in every `.rs` file; doc comments on every item,
  private ones included (`missing_docs`, clippy `missing_docs_in_private_items`); trait documents the contract, an
  implementation references it and states only its delta; `cargo fmt --check`, `cargo clippy -D warnings`,
  `cargo doc` with warnings as errors (broken links in doc comments), `cargo test`. Toolchain, image tag and
  `rust-version` are pinned to the same version and changed together.
- **CI.** One job `rust_test` in the test stage, for every merge request, from the official Rust image pinned by tag
  and digest. No cache and no coverage value.

## Consequences
**Positive:** Students can read the store in Python and Rust side by side, with the same names, tests and schedule
tables. The generic store makes fast benchmarks possible and still allows a dynamic value enum as one more value
type for comparison. The conventions of the Python code are checked for the Rust code by the compiler.
**Negative:** A second language to maintain: every later change to the Python store has to be ported or recorded as
a difference. Rust code has no coverage value and is barely covered by Semgrep (no Rust rule sets; its check of
suppression comments reads only Python files) and not by `stats_and_linting`. Type parameters and traits make the
Rust code harder to read for beginners than the Python original.

## Out of scope & deferred
- Blocking `cargo audit` of the Rust dependencies: its own merge request right after this one.
- MVCC store, indexed store, serializability test, benchmarks: later parts of the series (see *Context*).
- Coverage of the Rust code (e.g. `cargo llvm-cov`); instead `cargo mutants` runs once per merge request locally and
  its result is recorded in the merge request.
- Semgrep rules for Rust and checking suppression comments in `.rs` files.
- Publishing the Rust API documentation on GitLab Pages (changes the `pages` job).
- Calling the Rust store from Python (PyO3), running the Python tests against it, multithreading.

## Alternatives rejected
- **Dynamic value enum as the store's value type:** closer to Python's untyped objects, but every record is a map
  with heap-allocated fields, and every copy and comparison goes through it. Looking up a field by name is not the
  difference: `Attributes` on a struct does that too. It returns in the benchmarks as one value type.
- **Closures as the only predicate form:** fastest, but loses Python's `WHERE_Clause("a", "<", 0)`; added in the
  benchmarks as the baseline without a lookup by name.
- **A store that holds the versioned store as a field:** needs a delegating method for every inherited one, and an
  abort inside the inner store would bypass the override of the indexed store.
- **`HashMap` or `BTreeMap` for the store:** results and checksums would come out in a different order than in
  Python.
- **Unit tests inside `src/`:** would allow private fields, but Python exposes the internals anyway, and separate
  test files keep them parallel to the Python ones.
- **A separate repository:** the user chose the same repository.

## Scope-shift 2026-10-19

The Rust code is treated as **generated** from the Python code, like a compiler's output: all future changes are
made in Python, and the Rust code is generated again (the generator is a model, so "generated" means derived and
never edited by hand, not reproducible byte for byte). This applies to the whole series (011–016) and replaces the
folder `rust/`:

- The Rust project lives in `generated/rust/`, and its modules and tests mirror `system/`: e.g.
  `src/stores/versioned_key_value_store.rs` from `system/stores/VersionedKeyValueStore.py`,
  `tests/stores/test_stores_basics.rs` from `system/tests/stores/test_stores_basics.py`; each test folder has a
  `main.rs`, as Cargo builds test programs only from files directly in `tests/` or from `tests/<folder>/main.rs`.
- Every generated file names its Python sources in its first line (`// Code generated from ... DO NOT EDIT.`, or
  "no Python source" for Rust-only files such as `src/lib.rs`); `.gitattributes` marks the folder as generated, so
  GitLab folds it in merge request diffs.
- `generated/rust/GENERATED_FROM.json` records a hash (the first 16 hex digits of the SHA-256) of every Python source
  and of every generated file when it was generated; content hashes, not commit hashes, as squash merges remove the
  commits a generation was based on (the commit is recorded for information only). The CI job `generated_rust_check`
  (`.ci/check_generated.py`) reports out-of-date files (a source changed) and hand-edited files (the file changed, its
  sources did not). It fails on main and in the nightly pipeline and only warns in a merge request, so a Python change
  can be merged before its Rust image is regenerated; main may then be red until the regeneration lands, and the deploy
  stage (publishing the API documentation) waits until then.
- Exception: a dependency or Rust version update may change `Cargo.toml`, `Cargo.lock` and `rust-toolchain.toml`
  directly (a vulnerable dependency has nothing to do with the Python source), recorded with
  `--update-dependencies`, which rewrites only these three entries; a later regeneration keeps their versions.
  Hidden tool settings in `generated/rust/` (`.cargo/`, `.rustfmt.toml`, `.clippy.toml`) are rejected by the check,
  as Cargo, rustfmt and clippy would read them unnoticed.
- The port (011-016) was generated from the Python code at commit ffab2e8. The manifest records the sources as they
  were then, so the check reports every Rust file whose Python source changed since (e.g. the moved and re-documented
  tests, snapshot isolation of 017) as out of date until the regeneration.
- A skill that writes down how to regenerate follows in a separate MR; the port of snapshot isolation (017) to the
  Rust MVCC store follows as a regeneration at the end of the series.

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-15:** *Sanitizing* above says that rejecting empty names is stricter than Python. It is not: Python's
`"".isalpha()` and `"".isalnum()` are `False`, so Python rejects empty names too. Only the ASCII-only rule differs.
