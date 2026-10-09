# 005 — Exhaustive serializability test for the MVCC store
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/138
---
## Context

`TransactionalKeyValueStore` claims serializable transactions: reads run on a snapshot, writes go to
work-in-progress versions, and a validation phase at commit (method 1: re-evaluate read clauses with a
checksum; method 2: check the write sets of transactions that committed in between) aborts conflicting
transactions. The last five bug fixes were all in this area, and each was found by hand. Existing tests
check single hand-written schedules; nothing checks the store against the definition of serializability
over many schedules. A formal proof (e.g. in Lean) would only cover a model of the code, not the Python
code itself, so the code is tested first.

## Decision

A unit test runs the real store on every interleaving of a bounded set of transactions and checks each
history with an oracle:

- **Oracle:** the committed transactions are replayed one after another on a plain dictionary, ordered
  by their serialization point: the commit timestamp for a transaction that wrote something, the start id
  for a read-only one (read-only transactions read their start snapshot and are not validated). Every
  replayed read must return what the transaction read in the concurrent run, and the final dictionary
  must equal the store's committed state. Aborts are allowed; any other exception fails the test.
- **Schedules:** each transaction is `begin`, then one or two operations, then `commit`; all
  interleavings are enumerated. `begin` is an explicit step, so a transaction can start before another
  one commits and read afterwards.
- **Operations** are representatives of the cases of the validation (object selected by the read
  before/after, inserted, deleted, content changed, content unchanged), not the cross product of keys
  and values: values matter to the store only through the result of the read predicate and through
  equality, so one predicate (`a == 1`), a read without predicate, and one key that exists at the start
  plus one that does not suffice for two transactions.
- **Two transactions** run in the regular CI test job. **Three transactions** (needed e.g. for the
  read-only anomaly of Fekete et al.) run in a nightly scheduled GitLab pipeline only, with a smaller
  operation set, at most one transaction with two operations, and transactions numbered in order of
  their `begin` (each schedule is run once instead of once per renaming of its transactions).
- The test checks itself: the oracle rejects a hand-written write-skew history, and the exhaustive run
  finds a violation in a store whose validation always passes. It also asserts the number of
  enumerated schedules and that at least one schedule commits two concurrent writing transactions.
- No new dependency: the enumeration uses `itertools`, the test uses `unittest` like the rest of the
  suite.

A prototype of the two-transaction test comes first, to measure the runtime and see whether the test
finds bugs right away.

## Consequences
**Positive:** Every schedule within the bounds is checked against the definition of serializability,
on the real code, for both validation methods. A failure prints the schedule as a table, one column
per transaction.
**Negative:** The bounds are a choice: anomalies needing longer transactions, or more than three
transactions, are not covered, and the choice of representative operations rests on a symmetry
argument that is not proven. The CI test job gets slower (estimate: a few minutes under coverage, to
be measured with the prototype). Method 1 compares checksums built from Python hashes; a checksum
collision could hide a conflict, which the test does not address.

## Out of scope & deferred
- Random schedules with more transactions and operations via Hypothesis (new dependency).
- The indexed store (`IndexedTransactionalKeyValueStore`) and a check of its index contents.
- Checking that aborted transactions also saw a consistent snapshot.
- A Lean model of the validation with a proof of serializability.
- Bugs found by the test are fixed in separate `/fix-bug` merge requests, each with its own regression
  test, before this test lands.

## Alternatives rejected
- The full cross product of keys, values and predicates: about 1.6 million schedules per validation
  method for two transactions, too slow for CI.
- Skipping interleavings in which steps of different transactions should commute (e.g. a read after
  `begin`): this assumes exactly the behaviour under test.
- A check via a conflict graph: needs extra bookkeeping of reads and writes; replaying checks the
  outcome directly.
- Hypothesis now: a new dependency (also in the Binder image) that a first version does not need.
- pytest: the CI runs `unittest`.

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-09 (prototype results):**
- Measured: 255,960 schedules per validation method (9 operations, each schedule run once by letting transaction 1
  begin first); the test file runs in about 19 s, about 48 s under coverage.
- `delete y` is not an operation: deleting an object that was never stored raises `KeyError`.
- A third object z (not selected by a == 1 at the start) was added, so that an existing object can move into the
  read predicate.
- With the store state before the fixes of 2026-10-08/09, the test finds the bugs fixed in 0c6e65d, 25cb2d5 and
  9b7f7e9. The bug fixed in 1e33b45 is only found when the test runs on the indexed store, which is not part of
  this test yet (#54).
- The test found #63 (validation method 1 checksum collisions). Since its fix (!137) method 1 uses a SHA-256
  checksum over the repr of the read result, so the collision risk named under Consequences no longer applies and
  the test behaves the same under every PYTHONHASHSEED.
- Besides differences from the serial replay, the test reports exceptions of the store and work-in-progress
  versions left after all transactions ended, each with the schedule table.
- The three-transaction run in a nightly pipeline follows in a separate merge request.
