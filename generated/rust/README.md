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
| 1b | MVCC store (`TransactionalKeyValueStore`) with journal | validation method 2 done; method 1 planned |
| 2 | indexed MVCC store, serializability test | planned |
| 3 | benchmarks: Python against Rust | planned |

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

## Where to find what

| Python | Rust |
|---|---|
| [`system/query_processing/predicates.py`](../../system/query_processing/predicates.py) | [`src/query_processing/predicates.rs`](src/query_processing/predicates.rs) |
| [`system/stores/VersionedKeyValueStore.py`](../../system/stores/VersionedKeyValueStore.py) | [`src/stores/versioned_key_value_store.rs`](src/stores/versioned_key_value_store.rs) |
| [`system/stores/MVCC.py`](../../system/stores/MVCC.py) | [`src/stores/mvcc.rs`](src/stores/mvcc.rs) |
| [`system/indexes/indexes.py`](../../system/indexes/indexes.py) (`PythonDictionaryIndex`) | [`src/indexes/indexes.rs`](src/indexes/indexes.rs) (`DictionaryIndex`) |
| exceptions raised by the stores (`KeyError`, `RuntimeError`, `TransactionAbortedException`) | [`src/error.rs`](src/error.rs) |
| [`system/tests/query_processing/test_query_processing.py`](../../system/tests/query_processing/test_query_processing.py) | [`tests/query_processing/test_query_processing.rs`](tests/query_processing/test_query_processing.rs) |
| [`system/tests/stores/test_stores_basics.py`](../../system/tests/stores/test_stores_basics.py) | [`tests/stores/test_stores_basics.rs`](tests/stores/test_stores_basics.rs) |
| [`system/tests/stores/test_store_anomalies.py`](../../system/tests/stores/test_store_anomalies.py) | [`tests/stores/test_store_anomalies.rs`](tests/stores/test_store_anomalies.rs) |
| [`system/tests/indexes/test_indexing.py`](../../system/tests/indexes/test_indexing.py) (`test_indexing_basics_with_duplicates` only) | [`tests/indexes/test_indexing.rs`](tests/indexes/test_indexing.rs) |
| (no Python test file; tests of [`system/stores/MVCC.py`](../../system/stores/MVCC.py), with `StoreWithoutValidation` of [`system/playground/mvcc_playground.py`](../../system/playground/mvcc_playground.py)) | [`tests/stores/mvcc.rs`](tests/stores/mvcc.rs): error paths, the read set without duplicates and overriding of the MVCC store |
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
- Validation returns `Err(StoreError::TransactionNotFound)` for a transaction that committed meanwhile and was
  aborted afterwards; Python raises a `KeyError` there.
- `read_objects` returns copies of the objects; Python returns the stored objects themselves.
- `DictionaryIndex` has no `flush` without a key (in Python it raises a `KeyError`); dropping a key takes time
  proportional to the number of keys after it, as it keeps their order like Python's dict. Its `delete` needs the
  value (Python's default `None` fails unless `None` is stored), its `get` reports a missing key at once, and its
  error message for a missing value shows the value as Rust's `Debug` text, e.g. `"value4"` with quotes.
- `validate_transaction` panics for an unknown transaction; Python raises a `KeyError`.
- The error for committed versions out of order also names the object.
- The journal field `nev_value` of Python's `Update` is called `new_value`.
- The transactional store has validation method 2 only for now; method 1 (`use_brute_force_validation`) follows.
- The transactional store has the isolation level `"serializable"` only; Python's `isolation_level` with the level
  `"snapshot isolation"` follows in a regeneration at the end of the series.

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
| `test_store_anomalies.py`: all tests not listed below | `test_store_anomalies.rs`, same names in snake case; with validation method 2 only, also where Python loops over both methods; the indexed store follows in step 2 |
| `test_store_anomalies.py::test_validation_detects_write_skew_on_objects_with_equal_hash` | ported without its precondition on CPython's `hash()` |
| `test_store_anomalies.py::test_validation_accepts_unhashable_objects`, `..._detects_conflict_on_unhashable_objects` | ported with the value type `Account`, which has no `Hash`, unlike `Stuff` |
| `test_store_anomalies.py::test_checksums_on_self_updates` | follows with validation method 1 |
| `test_store_anomalies.py::test_read_only_transaction_commits_despite_concurrent_change_of_read_object` and the tests of the isolation levels (`test_snapshot_isolation_level_*`, `test_serializable_level_*`) | follow in a regeneration at the end of the series |
| (no Python test file) | `tests/stores/mvcc.rs`: Rust-only tests of the MVCC store (`system/stores/MVCC.py`, with `StoreWithoutValidation` of `system/playground/mvcc_playground.py`): the errors and panics of each operation, the read set without duplicates, and stores that override `abort_transaction` or `validate_transaction` |
| `test_indexing.py::test_indexing_basics_with_duplicates` | `test_indexing.rs::test_indexing_basics_with_duplicates`; the other tests of `test_indexing.py` (B-trees, radix tries, ...) are not ported; those of the indexed transactional store follow in step 2 |
| `test_DBMS.py` (uses the versioned store) | not ported: the DBMS is not part of the port |

The other tests in the Rust files have no Python counterpart; they check the behaviour of each operator, the errors,
several of the deviations listed above and further edge cases of the stores, the index and the predicates.
