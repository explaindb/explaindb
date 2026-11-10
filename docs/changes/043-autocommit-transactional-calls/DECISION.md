# 043 — Autocommit for read_objects, update_object and delete_object
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/233
---
## Context

042 gave the MVCC stores (`TransactionalKeyValueStore`, `IndexedTransactionalKeyValueStore`) a switch `autocommit`
for the operations that take no transaction id (`put`, `bulkload`, `get`, `delete`): with autocommit on, each call
runs as a transaction of its own, like an SQL statement outside an explicit transaction. It deferred the same for the
transactional operations `read_objects`, `update_object` and `delete_object`, which always need a transaction id; a
call with `None` raises KeyError or AssertionError today.

`read_objects` takes the transaction id as its first parameter, `update_object` and `delete_object` as their last.
Every caller in the repository (tests, playground, benchmarks) passes an explicit id positionally. The indexed store
overrides `update_object` and `delete_object` to maintain its indexes.

## Decision

The three operations accept `None` as transaction id. It has to be passed explicitly (`read_objects(None, where)`,
`update_object(object_id, new_object, None)`, `delete_object(object_id, None)`); there is no default, so a forgotten
id stays a TypeError.

- **autocommit off**: `None` raises RuntimeError ("... needs autocommit=True"), also before the first transaction:
  loading and inspecting the initial state is what `put`, `bulkload` and `get` do.
- **autocommit on**: the call is the same operation as with an explicit id, run in a transaction of its own (begin,
  operation, commit). `update_object` inserts a missing object or writes a new version of an existing or deleted
  one; `delete_object` raises KeyError only for an object id that was never stored and writes another delete marker
  on an object deleted already; `read_objects` returns what it reads. Conflicts with open transactions behave as for
  any other transaction (the own transaction is aborted on a concurrent writer; open transactions validate against
  it, or first updater wins under snapshot isolation).
- The public method calls itself with the id of the new transaction, so an override that hands `None` straight to
  the base class (as the indexed store does) runs its own logic, e.g. index maintenance, once with that id.
- The interface `ACIDStore` stays unchanged; autocommit belongs to the MVCC store.

## Consequences

**Positive:** with autocommit, every read and write can be one statement, as in SQL, and the three transactional
operations behave alike. No existing call changes. The id `None` in a call shows that it runs on its own.

**Negative:** two writes and two deletes with different rules sit side by side under autocommit: `put` only inserts
(KeyError if the object is visible) while `update_object` inserts or overwrites, and `delete` raises KeyError if the
object is not visible while `delete_object` does not. The documentation has to spell this out. Each call uses up
two counter values, as in 042.

## Out of scope & deferred

- Changing the interface `ACIDStore` (types and docstrings) for autocommit.
- `commit_transaction` / `abort_transaction` with `None` (no meaning).
- The Rust port (`generated/rust/`) follows with the next regeneration.

## Alternatives rejected

- A default `None` for the transaction id: shorter calls, but a forgotten id would silently run as a transaction of
  its own under autocommit (a later abort of the intended transaction would not undo it).
- `update_object` / `delete_object` with `None` following the rules of `put` / `delete` (insert or update only,
  KeyError if not visible): the same method would follow different rules depending on the id; `put` and `delete`
  already offer these rules.
- Leaving `delete_object` out (only `delete` deletes under autocommit): no two deletes with different rules, but the
  three transactional operations would no longer behave alike.
- Making the transaction id keyword-only or moving it in `read_objects`: breaks every positional call.
- A load-phase meaning for these calls with autocommit off: a transactional read needs a snapshot, and `get` / `put`
  cover the load phase.
- Moving the bodies of the indexed overrides to private methods so that only the base class handles `None`: a larger
  refactor for two lines of dispatch.

<!-- notes below: skill never overwrites past this marker -->
