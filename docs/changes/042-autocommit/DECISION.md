# 042 — Operations without a transaction id: load phase and autocommit
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/231
---
## Context

The MVCC stores (`TransactionalKeyValueStore`, `IndexedTransactionalKeyValueStore`) inherit `put`, `get`, `delete`
and `bulkload` from the non-transactional versioned store. These calls bypass transactions: they write committed
versions with the start timestamp 0, and `get` returns the newest committed version regardless of snapshots (it
raises AttributeError if that version is a delete marker). A `delete` after a `put` (both 0) or after a commit (start
= commit timestamp) appends a version that is not newer than the last one, and the next snapshot read raises
"committed object versions are not ordered by their validity start".

All 83 calls of these operations on transactional stores in the repository (tests, playground, widgets, the schedules
check, benchmarks, notebooks) load a fresh store before the first transaction begins. Many tests, the playground and
the benchmark fingerprints pin the transaction ids and timestamps that follow such a load.

SQL distinguishes two modes. With autocommit on, a statement outside an explicit transaction runs as a transaction
of its own, and an explicit `BEGIN` is still allowed. With autocommit off, there is no statement outside a
transaction. Loading the initial data (an import or restore) is the starting state of the database.

## Decision

The stores get a switch `autocommit` (constructor argument, default off). An operation without a transaction id
means:

- **autocommit off**: before the first transaction begins (load phase), `put`, `bulkload` and `get` load and inspect
  the initial state as before: start timestamp 0, visible to every transaction, no transaction id used up. Once a
  transaction has begun, they raise RuntimeError. `delete` always raises RuntimeError: loading needs no delete, and a
  delete marker at timestamp 0 behind a version at timestamp 0 would break the order of the versions.
- **autocommit on**: each call runs as a transaction of its own (begin, operation, commit), from the first call on.
  `put` inserts (KeyError if the object is visible; a deleted object may be inserted again), `delete` deletes (KeyError
  if the object is not visible), `get` returns the newest committed version (KeyError if missing or deleted), and
  `bulkload` loads all objects in one transaction, all or nothing. Such a transaction fails only if an open transaction
  is writing one of its objects (TransactionAbortedException); open transactions treat it like any other committed
  transaction (validation under serializable, first updater wins under snapshot isolation).
- Calls with an explicit transaction id are unchanged in both modes.

The indexed store indexes loaded objects in the load-phase write; under autocommit, the writes go through
`update_object` and `delete_object`, which maintain the indexes already.

## Consequences

**Positive:** committed versions always stay ordered, so the read crash cannot happen any more. A misuse (writing
without a transaction after transactions have run) fails at the call with a message naming `autocommit`. No existing
caller changes, and the transaction ids and timestamps of the playground, the tests and the benchmarks stay the same.
Students can use the store like an SQL database with autocommit.

**Negative:** the load phase is an extra rule (operations without a transaction id behave differently before and
after the first transaction). Under autocommit, every call uses up two counter values, a `get` too, and an empty
`bulkload` still runs an empty transaction. An aborted insert leaves an empty entry in the dictionary of the store, as
every aborted insert does.

## Out of scope & deferred

- Autocommit for `read_objects`, `update_object` and `delete_object` without a transaction id (own MR; `read_objects`
  takes the transaction id as its first parameter, so its signature would change).
- The Rust port (`generated/rust/`) follows with the next regeneration.
- If maintaining an index raises inside an autocommit transaction (an attribute value that cannot be hashed), the
  abort that follows hits the same error, and the transaction stays open (as for explicit transactions today).

## Alternatives rejected

- Every operation without a transaction id runs with autocommit, always: the initial loads would use up transaction
  ids and shift the pinned ids and timestamps in 33 tests, the playground, the widgets and the benchmark results.
- Autocommit off by default without a load phase: every one of the 83 loads would have to switch autocommit on, with
  the same shifts.
- Only give a non-transactional delete a fresh counter value: fixes the crash, but writes without a transaction stay
  possible at any time and bypass validation and the snapshot rules.
- Refuse an explicit transaction id under autocommit: a store with autocommit could then not run a transaction with
  several operations; SQL allows `BEGIN` under autocommit too.
- Allow `delete` in the load phase by removing the entry: no caller needs it.

<!-- notes below: skill never overwrites past this marker -->

Note (review): "every call uses up two counter values" holds for a call that succeeds; a call that fails inside its
transaction uses up one (the begin), as an abort takes no counter value.

Note (second review): an interrupt (Ctrl-C) is handled between two objects of a bulkload. An interrupt during the
commit, or in the indexed store between storing a version and indexing it, can leave the transaction open: the abort
of the indexed store removes index entries the version never got (same cause as the unhashable value above).
