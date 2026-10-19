<!-- Code generated for the Rust port (no Python source). DO NOT EDIT. -->
# ExplainDB in Rust: the store core

This folder holds a port of the store core of ExplainDB from Python to Rust. Students can read the same
algorithms in both languages side by side: the Rust code keeps the names, comments and tests of the Python
original wherever Rust allows it. The port also makes benchmarks of the store possible.

## Generated code: change the Python, not this folder

The Rust code is **AI-generated**: a language model generates it from the Python code in
[`system/`](../../system), like a compiler's output. It is an image of the Python code, not a second implementation.
All changes are made in Python; the Rust code is then generated again. Therefore:

- Every file here says in its first line which Python files it is generated from (`// Code generated from ...
  DO NOT EDIT.`; only `Cargo.lock`, written by Cargo, and the manifest have none), and the folders mirror
  `system/`: e.g. `src/stores/versioned_key_value_store.rs` is generated
  from `system/stores/VersionedKeyValueStore.py`, and `tests/stores/test_stores_basics.rs` from
  `system/tests/stores/test_stores_basics.py`.
- [`GENERATED_FROM.json`](GENERATED_FROM.json) records a hash (the first 16 hex digits of the SHA-256) of every Python
  source and of every generated file at the time it was generated. The CI job `generated_rust_check` (script
  [`.ci/check_generated.py`](../../.ci/check_generated.py)) reports a generated file whose Python source changed
  since (out of date: regenerate it) and a generated file that changed although its sources did not (edited by hand).
  It fails on main and in the nightly pipeline and only warns in a merge request, so a Python change can be merged
  before its Rust image is regenerated. While main is red, the jobs of the deploy stage (e.g. publishing the API
  documentation) do not run.
- After regenerating, run `python3 .ci/check_generated.py --update` from the repository root to record the new
  hashes.
- One exception: a dependency or Rust version update may change `Cargo.toml`, `Cargo.lock` and
  `rust-toolchain.toml` directly (e.g. to fix a finding of the dependency audit). Record it with
  `python3 .ci/check_generated.py --update-dependencies`, which rewrites only the entries of these three files;
  `--update` would also record out-of-date or hand-edited Rust files as current. A later regeneration keeps the
  versions in these files.
- Hidden tool settings (`.cargo/`, `.rustfmt.toml`, `.clippy.toml`, in any folder) and symbolic links are not allowed
  here, as they could change the build or the checks unnoticed.
- GitLab folds the generated files in merge request diffs (`gitlab-generated` in
  [`.gitattributes`](../../.gitattributes)), so reviewers see the Python change first; `Cargo.toml`, `Cargo.lock` and
  `rust-toolchain.toml`, which control the build and its dependencies, stay unfolded.

The port is built in steps (see
[`docs/changes/011-rust-store-foundation`](../../docs/changes/011-rust-store-foundation/DECISION.md)):

| Step | Content | Status |
|---|---|---|
| 1a | WHERE-clause predicates, versioned key-value store | done |
| audit | blocking `cargo audit` of the Rust dependencies in CI | done |
| 1b | MVCC store (`TransactionalKeyValueStore`) with journal, both validation methods, both isolation levels | done |
| 2 | indexed MVCC store, serializability test | planned |
| 3 | benchmarks: Python against Rust | done: workloads, results and HTML report |

The notebooks and the query optimizer stay Python only.

## Installing Rust

Install `rustup`, the installer of the Rust tools, as described on <https://rustup.rs>: on macOS and Linux with the
command shown there, on Windows with `rustup-init.exe`. The first `cargo` command in this folder then installs the
Rust version given in [`rust-toolchain.toml`](rust-toolchain.toml) by itself. Rust also needs a linker: on macOS the
Xcode command line tools (`xcode-select --install`), on Windows the Visual Studio Build Tools, as `rustup-init.exe`
offers. The Binder environment of the notebooks has no Rust.

## Building and testing

Run these commands in this folder:

```sh
cargo test                                    # build and run all tests
cargo fmt                                     # format the code
cargo clippy --all-targets -- -D warnings     # lints, including missing doc comments
cargo doc --no-deps --open                    # API documentation in the browser
```

The CI job `rust_test` runs the checks of [CONTRIBUTING.md](../../CONTRIBUTING.md#rust-code), which are stricter: e.g.
`cargo doc` there fails on a broken link in a doc comment of the library. The CI job `rust_dependency_audit` checks
the crates in `Cargo.lock` for known vulnerabilities, see [CONTRIBUTING.md](../../CONTRIBUTING.md#security-audit).

## A first example

```rust
use explaindb::{StoreError, VersionedKeyValueStore, VersionedStore};

fn main() -> Result<(), StoreError> {
    let mut store: VersionedKeyValueStore<String> = VersionedKeyValueStore::new();
    store.put("A", "hello".to_string())?;
    assert_eq!(store.get("A")?, "hello");
    store.delete("A")?;
    assert_eq!(store.get("A"), Err(StoreError::NotVisible("A".to_string())));
    Ok(())
}
```

All methods of the store except `new`, e.g. `put`, `get`, `delete` and `bulkload`, belong to the trait
`VersionedStore`. Rust only finds them if the trait is imported (`use explaindb::VersionedStore;`); without it, the
compiler reports that the method does not exist. The same holds for `evaluate` and the trait `Clause`.

## Benchmarks

The same seven workloads run on the Python store and on this Rust store (see
[`docs/changes/015-store-benchmarks`](../../docs/changes/015-store-benchmarks/DECISION.md)):

| Workload | What is timed |
|---|---|
| `bulkload` | loading n objects, per object |
| `get` | one non-transactional `get` of every object, per get |
| `read` | 100 `read_objects` with `a == 42` in one transaction, per read; each read scans all n objects; the first object with `a == 42` is object 434, so with n = 100 the reads return nothing |
| `update_commit` | 1 000 transactions of one update and a commit, per transaction |
| `read_only` | 1 000 transactions reading `a < 100`, per transaction |
| `read_write_disjoint` | 1 000 transactions reading one object and updating it, without conflicts, per transaction |
| `read_write_contention` | 500 pairs of transactions where the second fails validation, per transaction (committed or aborted) |

The first four run with n = 100, 1 000 and 10 000 objects and validation method 2; the last three with n = 1 000
and both validation methods. Run all of them from the repository root, on an otherwise idle machine on mains power
(about three minutes; `--quick` for a short trial):

```sh
uv run python -m system.benchmarks.run
```

It builds [`examples/benchmarks/workloads.rs`](examples/benchmarks/workloads.rs) in release mode, runs every workload
in its own process with [`system/benchmarks/workloads.py`](../../system/benchmarks/workloads.py) and with the Rust
program, and stops if the two did different work: both report a fingerprint of each run (commits, aborts, objects read,
final transaction counter, committed versions, and a weighted sum over the objects' values). It writes
[`benchmarks/results.json`](../../benchmarks/results.json) with the machine, the Rust and Python versions and the git
commit. One workload alone:

```sh
# arguments: workload, method, objects, operations, repetitions
(cd generated/rust && cargo run --release --example workloads -- read 2 1000 100 3)
uv run python -m system.benchmarks.workloads read 2 1000 100 3
```

The comparison measures the two implementations of the same algorithm, not the languages alone: Python also pays
for pydantic version and journal objects, deep copies on writes and the generator of `get`, and runs with its
garbage collector switched off while timing; Rust pays for copies of the objects and ids it returns from
`read_objects` and of the values it puts into the journal on updates.

The results of a full run are shown in [`benchmarks/index.html`](../../benchmarks/index.html), a single static page
with charts, a table of all numbers and the text on what is measured and how fair it is; it needs no scripts or
other files, so it can be put on any web site. After a new full run, write it again:

```sh
uv run python -m system.benchmarks.report
```

[`system/benchmarks/report.py`](../../system/benchmarks/report.py) fills the template
[`report_template.html`](../../system/benchmarks/report_template.html) (the page's text and style) with the charts
drawn by [`charts.py`](../../system/benchmarks/charts.py); a test fails if the committed page does not match the
committed results.

## Where to find what

| Python | Rust |
|---|---|
| [`system/query_processing/predicates.py`](../../system/query_processing/predicates.py) | [`src/query_processing/predicates.rs`](src/query_processing/predicates.rs) |
| [`system/stores/VersionedKeyValueStore.py`](../../system/stores/VersionedKeyValueStore.py) | [`src/stores/versioned_key_value_store.rs`](src/stores/versioned_key_value_store.rs) |
| [`system/stores/MVCC.py`](../../system/stores/MVCC.py) | [`src/stores/mvcc.rs`](src/stores/mvcc.rs) |
| [`system/indexes/indexes.py`](../../system/indexes/indexes.py) (`PythonDictionaryIndex`) | [`src/indexes/indexes.rs`](src/indexes/indexes.rs) (`DictionaryIndex`) |
| exceptions raised by the stores (`KeyError`, `RuntimeError`, `ValueError`, `TransactionAbortedException`) | [`src/error.rs`](src/error.rs) |
| [`system/benchmarks/workloads.py`](../../system/benchmarks/workloads.py) (benchmark workloads) and its tests [`system/tests/benchmarks/test_store_benchmark.py`](../../system/tests/benchmarks/test_store_benchmark.py) | [`examples/benchmarks/workloads.rs`](examples/benchmarks/workloads.rs) |
| [`system/tests/query_processing/test_query_processing.py`](../../system/tests/query_processing/test_query_processing.py) | [`tests/query_processing/test_query_processing.rs`](tests/query_processing/test_query_processing.rs) |
| [`system/tests/stores/test_stores_basics.py`](../../system/tests/stores/test_stores_basics.py) | [`tests/stores/test_stores_basics.rs`](tests/stores/test_stores_basics.rs) |
| [`system/tests/stores/test_store_anomalies.py`](../../system/tests/stores/test_store_anomalies.py) | [`tests/stores/test_store_anomalies.rs`](tests/stores/test_store_anomalies.rs) |
| [`system/tests/indexes/test_indexing.py`](../../system/tests/indexes/test_indexing.py) (`test_indexing_basics_with_duplicates` only) | [`tests/indexes/test_indexing.rs`](tests/indexes/test_indexing.rs) |
| (no Python test file; tests of [`system/stores/MVCC.py`](../../system/stores/MVCC.py), with `StoreWithoutValidation` of [`system/playground/mvcc_playground.py`](../../system/playground/mvcc_playground.py)) | [`tests/stores/mvcc.rs`](tests/stores/mvcc.rs): error paths, the read set without duplicates, overriding of the MVCC store, what tells the two validation methods apart, the behaviour of method 1 and the settings of the isolation level |
| [`system/tests/abstract_unit_test.py`](../../system/tests/abstract_unit_test.py), `Named` (stands in for the `Stuff` with a string attribute in [`test_query_processing.py`](../../system/tests/query_processing/test_query_processing.py)) and the value type `Account` of [`test_store_anomalies.py`](../../system/tests/stores/test_store_anomalies.py) | [`tests/common/mod.rs`](tests/common/mod.rs) |

Cargo builds one test program per folder in `tests/` that has a `main.rs` (e.g. `tests/stores/main.rs`); it
includes the test files of that folder and the shared `tests/common/mod.rs`.

## How Python becomes Rust

| Python | Rust | Why |
|---|---|---|
| a store holds any `object` | a store is generic over its value type `V`, e.g. `VersionedKeyValueStore<Stuff>` | the compiler checks the type of every value; no type checks at run time |
| `WHERE_Clause` reads attributes with `getattr` | the value type implements the trait `Attributes`, which returns an attribute by name | Rust has no `getattr` |
| subclasses inherit methods of `VersionedKeyValueStore` | the methods are default methods of the trait `VersionedStore`; a store only gives access to its map | Rust has no inheritance |
| `UpdateEntry` and `DeleteEntry`, subclasses of `VersionEntry` | `Version::Update(value)` and `Version::Delete` inside `VersionEntry` | an enum lists all kinds of versions in one place |
| `dict` of the store | `IndexMap` | it keeps the order in which keys were inserted, as Python's `dict` does |
| `raise KeyError(...)` | returns `Err(StoreError::...)` | errors are values in Rust |
| `assert ...` | `assert!(...)`, the program stops (panics) | both mark programming errors |
| `put` copies the value (`deepcopy`) | `put` takes ownership of the value | for plain value types such as numbers, strings and structs made of them, nobody else can change it afterwards, so no copy is needed |
| `get` returns an iterator over one value | `get` returns a reference to the value | there is only one value |
| attributes of `TransactionalKeyValueStore` (`TA_id`, `TD`, `journal`, ...) | fields of `MvccState` (`ta_id`, `td`, `journal`, ...), reached as `store.state` | the trait methods need one place for all state |
| subclasses of `TransactionalKeyValueStore` override methods and call `super()` | a store overrides a method of the trait `TransactionalStore` and calls the free function `*_default` of the same name | Rust has no `super()` |
| `TDEntry.last_committed_TA_index_in_TA_trace` (starts at -1) | `TdEntry::committed_transactions_at_begin`, the length of the trace (one more) | an unsigned index cannot be -1 |
| read clauses in a `set` of `HashableDict` | a `Vec<ReadClause>` without duplicates (same clause object and checksum) | clause objects (`Rc<dyn Clause>`) have no hash; Python's clauses compare by identity |
| `use_brute_force_validation=True` / `False` | `Validation::BruteForce` / `Validation::WriteSets` (method 1 / method 2), set with `with_validation` or `with_isolation_level` | an enum names the two methods |
| `isolation_level="serializable"` / `"snapshot isolation"` | `IsolationLevel::Serializable` / `IsolationLevel::SnapshotIsolation`, set with `with_isolation_level` (of the store or of `MvccState`), which returns `Err(StoreError::InvalidConfiguration)` for snapshot isolation with method 1 where Python raises a `ValueError` | an enum names the two levels; an unknown level cannot be written |
| checksum: SHA-256 of `repr` of the read result | [`checksum`](src/stores/mvcc.rs): SHA-256 of the `Debug` text of the read result (crate `sha2`) | Rust has no `repr`; the `Debug` text of a derived `Debug` shows all fields |
| `raise TransactionAbortedException` | the transaction is aborted and the method returns `Err(StoreError::TransactionAborted)` | errors are values in Rust |

## Deviations from Python

- `WhereClause::new` accepts attribute names of ASCII letters only and string constants of ASCII letters and digits
  only; Python's `isalpha` and `isalnum` also accept other letters such as `ä` and other digits such as `²`. Its
  fields are private, so every clause passes these checks.
- Two clauses with the same fields are equal (`==`); Python's clauses define no equality, so two clauses are equal
  only if they are the same object. The read set of the MVCC store compares clauses by identity, as Python's.
- Python's `HashableDict` (in `VersionedKeyValueStore.py`) becomes the struct `ReadClause` of the MVCC store.
- `get` of an object whose last committed version is a delete marker, or that has no committed version, returns
  `Err(StoreError::NotVisible)`; Python crashes there.
- `get` reports a missing key at once; Python's iterator raises the error only when it is used.
- `put` takes ownership of the value instead of copying it.
- Python's unused parameters `persistence_layer` (of the store) and `_object` (of `delete`) are dropped.
- Integers are `i64`; Python's have no size limit. Python also accepts `True` as an integer constant; Rust does not.
- `show` and `show_transaction_dictionary` print all levels; Python's `pprint` stops at depth 3.
- Validation method 2 returns `Err(StoreError::TransactionNotFound)` for a transaction that committed meanwhile and
  was aborted afterwards; Python raises a `KeyError` there.
- `read_objects` returns copies of the objects; Python returns the stored objects themselves.
- `DictionaryIndex` has no `flush` without a key (in Python it raises a `KeyError`); dropping a key takes time
  proportional to the number of keys after it, as it keeps their order like Python's dict. Its `delete` needs the
  value (Python's default `None` fails unless `None` is stored), its `get` reports a missing key at once, and its
  error message for a missing value shows the value as Rust's `Debug` text, e.g. `"value4"` with quotes.
- The error for snapshot isolation with validation method 1 (`InvalidConfiguration`, Python: `ValueError`) names
  the Rust settings `Validation::BruteForce` and `IsolationLevel::Serializable` instead of Python's parameters.
- Under serializable, `validate_transaction` panics for an unknown transaction; Python raises a `KeyError`. Under
  snapshot isolation, both return `true` without looking the transaction up.
- The error for committed versions out of order also names the object.
- The journal field `nev_value` of Python's `Update` is called `new_value`.
- Validation method 1 hashes the `Debug` text of a read result instead of Python's `repr`, so the checksums differ
  from Python's and cannot be compared across languages. Python's default `repr` of an object shows its memory
  address, so Python treats an equal but new object as changed and aborts; Rust's `Debug` text shows only the
  content.

## Which Python test became which Rust test

| Python test | Rust test |
|---|---|
| `test_query_processing.py::test_where_clause` | `test_query_processing.rs::test_where_clause`, with an integer (`Stuff`) and a string (`Named`) attribute, as a Rust field cannot hold both |
| `test_query_processing.py::test_disjunction` | `test_query_processing.rs::test_disjunction` |
| `test_stores_basics.py::test_KeyValueStore_basics` | `test_stores_basics.rs::test_key_value_store_basics`, for the versioned and the transactional store; the indexed store follows in step 2 |
| `test_stores_basics.py::test_TransactionalKeyValueStore` | `test_stores_basics.rs::test_transactional_key_value_store` |
| `test_stores_basics.py::test_begin_transaction` | `test_stores_basics.rs::test_begin_transaction`, checking the length of the trace (0) where Python checks the index -1 |
| `test_stores_basics.py::test_journaling` | `test_stores_basics.rs::test_journaling` |
| `test_stores_basics.py::test_IndexedTransactionalKeyValueStore_basics` | step 2 |
| `test_store_anomalies.py`: all tests not listed below | `test_store_anomalies.rs`, same names in snake case; a test that Python runs with both validation methods runs once per method (`..._with_method_1`, `..._with_method_2`); the indexed store follows in step 2 |
| `test_store_anomalies.py::test_validation_detects_write_skew_on_objects_with_equal_hash` | ported without its precondition on CPython's `hash()` |
| `test_store_anomalies.py::test_validation_accepts_unhashable_objects`, `..._detects_conflict_on_unhashable_objects` | ported with the value type `Account`, which has no `Hash`, unlike `Stuff` |
| `test_store_anomalies.py::test_checksums_on_self_updates` | `test_store_anomalies.rs::test_checksums_on_self_updates` (method 1 only, as in Python) |
| `test_store_anomalies.py::test_snapshot_isolation_level_aborts_write_to_object_committed_after_begin` | `test_store_anomalies.rs::test_snapshot_isolation_level_aborts_write_to_object_committed_after_begin`; its variant with the indexed store follows in step 2 |
| `test_store_anomalies.py::test_snapshot_isolation_level_rejects_invalid_configuration` | `test_store_anomalies.rs::test_snapshot_isolation_level_rejects_invalid_configuration`, without the unknown level, which cannot be written in Rust |
| (no Python test file) | `tests/stores/mvcc.rs`: Rust-only tests of the MVCC store (`system/stores/MVCC.py`, with `StoreWithoutValidation` of `system/playground/mvcc_playground.py`): the errors and panics of each operation, the read set without duplicates, stores that override `abort_transaction` or `validate_transaction`, what tells the two validation methods apart, the behaviour of validation method 1, and the settings of the isolation level |
| `test_indexing.py::test_indexing_basics_with_duplicates` | `test_indexing.rs::test_indexing_basics_with_duplicates`; the other tests of `test_indexing.py` (B-trees, radix tries, ...) are not ported; those of the indexed transactional store follow in step 2 |
| `test_mvcc_serializability.py` | step 2 |
| `test_DBMS.py` (uses the versioned store) | not ported: the DBMS is not part of the port |
| `test_store_benchmark.py` (tests of the benchmarks) | the tests at the end of `examples/benchmarks/workloads.rs`: the same fingerprints of the same small runs, plus the Rust program's own argument parsing and the fingerprints of the runs the runner measures, with 1 000 objects and 100 reads or 1 000 transactions (`fingerprints_of_realistic_runs`, Rust only, too slow for the Python tests); the runner (`system/benchmarks/run.py`) is tested in Python only |
| `test_benchmark_report.py`, `test_benchmark_charts.py` (tests of the HTML report and its charts) | none: the report is Python only |

The other tests in the Rust files have no Python counterpart; they check the behaviour of each operator, the errors,
several of the deviations listed above and further edge cases of the stores, the index and the predicates.
