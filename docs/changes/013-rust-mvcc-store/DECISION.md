# 013 — Rust port of the MVCC store, part 1: write-set validation
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/146
---
## Context

Part 1b of the Rust port of the store core (series decisions: 011). It ports `TransactionalKeyValueStore`
(`system/stores/MVCC.py`): transactions under snapshot isolation with a journal, a transaction dictionary and a
validation phase at commit, in two methods (1: brute force with checksums of re-run reads; 2: write sets of the
transactions that committed meanwhile). Later parts must build on it without a redesign: the indexed store (MR 2)
overrides abort, update and delete, and the serializability test (MR 2) uses stores that override validation and
commit. The user split part 1b in two: this feature ports the store with method 2 and all its tests; method 1
(with SHA-256 checksums, as in Python) follows in its own merge request.

## Decision

- **State and trait.** All state lives in one struct `MvccState<V>` (store map, journal, transaction dictionary,
  transaction counter, trace of committed transactions; fields public, as Python's). `TransactionalKeyValueStore<V>`
  holds it and implements `VersionedStore`, so `put`, `get` and `bulkload` work as in Python. The methods live in a
  trait `TransactionalStore` with a single accessor to the state (so `commit` can borrow the transaction dictionary
  and the store map separately); the bounds `Clone + PartialEq + Debug` on the value type are stated once on it.
- **Overriding.** Every trait method with a body keeps it also in a free function `*_default`, generic over the
  trait, so an overriding store can call the original (Rust has no `super()`); conflict paths call
  `abort_transaction` through the trait, so an override of it is used, as with Python's `self.abort_transaction`.
- **Reads.** `get_visible_object_version` and `read_snapshot` (Python `_read_snapshot`, returning a `Snapshot` with
  the objects and the checksum) are methods of `MvccState`, so an overriding store can read while changing its own
  fields. Reads return owned copies of the values.
- **Journal.** A port of `PythonDictionaryIndex` (key → list of values; `size` counts keys; missing keys and values
  are errors with Python's messages), used for the journal and later for the indexes.
- **Same order of steps as Python** in every method, including `commit`: the commit timestamp is drawn before
  validation, so the counter advances even if validation fails; an error inside validation (versions out of order)
  is passed up without aborting.
- **Errors**, by the series rule (raise → `Err`, assert → panic): unknown transaction in `read_objects` and
  `update_object` → `TransactionNotFound`; committed transaction → `AlreadyCommitted`; conflict → abort and
  `TransactionAborted`; versions out of order → `VersionsNotOrdered`; unknown transaction in `delete_object`,
  `commit_transaction` and `abort_transaction` → panic; committing twice → panic (Python crashes).
- **Read set.** A list of (where clause or none, checksum or none), deduplicated on insert by the identity of the
  clause and the checksum, as Python's set of `HashableDict` (clauses compare by identity there).
- **Python's index -1** (index of the last committed transaction at begin) becomes the length of the trace at
  begin; method 2 takes the transactions committed after that position.
- **Tests one to one with Python**: a test loops over validation methods or store types only where the Python test
  does; the store types are parameters of generic test functions, so MR 2 adds its store with one call. The tests
  for unhashable objects are ported with a value type without `Hash`; the test of equal Python hashes is ported
  without its CPython precondition. Extra Rust tests cover each error path, the deduplication of the read set and
  that conflicts reach an overridden abort.

## Consequences
**Positive:** The MVCC store runs in Rust with the same algorithm, names and tests as in Python; MR 2 can add the
indexed store and the test stores of the serializability test by overriding trait methods.
**Negative:** Overriding needs a trait method plus a free function per method, more ceremony than Python's
inheritance; stores are used through generics, not as `dyn` objects (the trait has generic methods), so choosing a
store type at run time needs an enum. Clauses are shared with `Rc`, so the store cannot move between threads.

## Out of scope & deferred
- Validation method 1 (brute force with SHA-256 checksums of the reads, crate `sha2`) and the tests that loop over
  both methods: next merge request (part 1b-2).
- The indexed store, the serializability test and its stores: MR 2. Benchmarks: MR 3.
- `_read_more_recent_committed_versions_iterable` (unused in Python; reads an attribute that does not exist):
  not ported.
- Multithreading, a Python binding (PyO3).

## Alternatives rejected
- **A struct with methods only:** the indexed store and the test stores could not override anything.
- **Accessors per field:** the borrow checker rejects `commit` changing the store while reading the write set.
- **A hash set for the read set:** clause objects (`Rc<dyn Clause>`) have no hash; a list with deduplication keeps
  Python's semantics.
- **Storing -1:** an unsigned index cannot hold it, and method 2 needs the position after it anyway.
- **Panicking on versions out of order:** Python raises there, so Rust returns an error.
- **Comparing stored reads instead of checksums (method 1):** the user chose SHA-256 as in Python.

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-15 (POC review):**
- The free functions `*_default` exist for the methods a store may override: `begin_transaction`, `read_objects`,
  `update_object`, `delete_object`, `validate_transaction`, `commit_transaction` and `abort_transaction`; not for
  the accessors and small helpers (`next_ta_id`, `show_transaction_dictionary`). They call the other methods,
  including the reads `get_visible_object_version` and `read_snapshot`, through the trait, as Python's `self.`;
  `read_snapshot` itself reads through `MvccState` (corrected in the mini-review of Phase 3: an override of only
  `get_visible_object_version` is not seen by `read_snapshot`; no Python store overrides it).
- Validation returns `TransactionNotFound` for a transaction that committed meanwhile and was aborted afterwards
  (allowed, as in Python), where Python raises a `KeyError`.
- As in Python, aborting a committed transaction removes the work-in-progress versions of the objects it wrote,
  whoever holds them now.
- `DictionaryIndex` keeps the order of the keys when one is dropped, as Python's dict; this takes time proportional
  to the number of keys (user decision; relevant for the indexes of MR 2 and the benchmarks).

**Note 2026-10-16 (review of the MR stack):**
- *Errors* above says "committing twice → panic": only a transaction that wrote something panics; one that wrote
  nothing commits again, as in Python.
- *Overriding* above says every trait method with a body keeps it in a free function `*_default`: this holds for
  the operations a store may override (see the POC note), not for the reads and helpers.
- The index's error message for a missing value shows the value as Rust's `Debug` text; `rust/README.md` lists it
  with the other deviations.

**Note 2026-10-19 (rebase):** The paths moved from `rust/` to `generated/rust/`, whose modules and tests mirror
`system/`: `src/stores/mvcc.rs`, `src/indexes/indexes.rs`, `tests/stores/...` and `tests/indexes/...`; see
"Scope-shift 2026-10-19" in [011's DECISION.md](../011-rust-store-foundation/DECISION.md). The `rust/...` paths above
are the old paths, as they were when the decision was made.

**Note 2026-10-19 (review of the rebase):** Dropping a key from `DictionaryIndex` takes time proportional to the
number of keys *after* it (`shift_remove`), not to the number of all keys as the POC note above says. The note of
2026-10-16 says that of the transactions committed twice only one that wrote something panics: such a transaction
panics, or is aborted if one of its reads selects an object it wrote, as validation then sees its own first commit.
