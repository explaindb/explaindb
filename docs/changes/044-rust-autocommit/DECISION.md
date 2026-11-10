# 044 — Rust port of autocommit (042, 043)
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/238
---
## Context

Features 042 and 043 gave the Python MVCC store a switch `autocommit`: `put`, `bulkload`, `get` and `delete` without
a transaction id load the initial state before the first transaction (autocommit off) or run as a transaction of
their own (autocommit on), and `read_objects`, `update_object` and `delete_object` accept the transaction id `None`.
The generated Rust port in `generated/rust/` is out of date with these sources (8 files, together with small doc and
test changes). Rust has no inheritance, no `super()`, no default arguments and no exceptions, and the Rust `get` of
`VersionedStore` borrows the store immutably, so the port needs decisions that a plain regeneration does not make.
`check_generated.py --update` records the whole manifest at once, so all 8 files are regenerated in one MR.

## Decision

- The state gets a field `autocommit` (default `false`), set on a store with the builder method
  `with_autocommit(true)` after a constructor.
- `read_objects`, `update_object` and `delete_object` take the transaction id as `impl Into<Option<u64>>`: a call
  passes an id or `None`, as in Python, and existing calls stay unchanged. With `None`, the default function refuses
  without autocommit or runs the operation in a transaction of its own, calling the trait method with the new id, so
  an override runs once with that id.
- A new error `StoreError::AutocommitRequired` (operation, whether a transaction has begun) stands for Python's
  RuntimeError; its message is Python's, with Rust's `true`.
- The transactional store overrides `put`, `bulkload`, `get` and `delete` of `VersionedStore` through public free
  functions `*_transactional`; every other implementation of `TransactionalStore` must do the same. The bodies of the
  versioned store's methods become free functions `put_default`, `get_default`, `bulkload_default` (Python:
  `super()`), as for the `*_default` functions of `TransactionalStore`.
- `VersionedStore::get` takes `&mut self`, as `get` with autocommit begins and commits a transaction; it returns a
  reference to the version visible in that transaction's snapshot.
- `get` and `delete` with autocommit report a missing or not visible object as `KeyNotFound`, as Python raises one
  KeyError with that text.
- A panic inside an operation run as a transaction of its own is not caught; the transaction stays open (Python also
  aborts on an interrupt).
- The Python tests of autocommit are translated for the transactional store; the indexed store follows in step 2.
  Not ported: the test of the missing default transaction id (Rust has no default arguments), the bulkload whose
  input raises (a Rust iterator cannot fail) and the printed transaction dictionary (a Rust test cannot capture
  `println!`); the test of a get kept from the load phase is ported without the kept part (borrow checker).

## Consequences

**Positive:** the Rust port is up to date again and shows autocommit in the same names and calls as Python; no
existing call of the three transactional operations changes; committed versions stay ordered in Rust too.

**Negative:** `get` needs a mutable store, also for the versioned store; every store implementing
`TransactionalStore` needs four forwarding methods, and forgetting them keeps the non-transactional behaviour; two
generated files change without a change of their Python source (`versioned_key_value_store.rs`, `lib.rs`); an id
parameter of type `impl Into<Option<u64>>` hides a conversion.

## Out of scope & deferred

- The index parts of the autocommit tests and the autocommit tests of `test_indexing.py`: with the indexed store
  (step 2).
- Catching panics (`catch_unwind`) in a transaction of its own: closer to Python, but against the port's rule that a
  panic stops the program.
- `show_transaction_dictionary` writing to a given writer, so that a test can check its output.

## Alternatives rejected

- `ta_id: Option<u64>`: the plainest mapping of `int | None`, but every one of about 160 calls would read
  `Some(t_1)`.
- Separate methods such as `read_objects_autocommit`: names differ from Python, two methods per operation.
- Keeping `get(&self)` and adding a second `get` to `TransactionalStore`: two imported traits with a method `get`
  make every call ambiguous.
- A blanket implementation of `VersionedStore` for every `TransactionalStore`: removes the forwards, but conflicts
  with the supertrait and with the stores' own implementations; a large restructuring.
- Copying the body of `VersionedStore::put` into `mvcc.rs` instead of `put_default`: two copies of the same code.
- `NotVisible` for a deleted object under autocommit: a new deviation, as Python raises KeyError with the text of
  `KeyNotFound`.
- A parameter `autocommit` for `with_isolation_level`: breaks every call for a rarely used switch.

## Scope-shift 2026-11-10

Python's `_load` (the load-phase write of `put`) is an override point: the indexed store overrides it to index the
loaded objects. In Rust it becomes the trait method `TransactionalStore::load` with the public free function
`load_default`, as for the other override points, instead of a private helper; otherwise the indexed store (step 2)
could not index objects loaded before the first transaction. A panic inside an operation run as a transaction of its
own stays uncaught, as decided; the deviation is stated in the doc comments of the public functions concerned.

<!-- notes below: skill never overwrites past this marker -->
