# MVCC & Versioned Stores

**Multi-Version Concurrency Control (MVCC)** lets readers and writers proceed without blocking each
other by keeping **multiple versions** of each value. A write creates a *new* version rather than
overwriting the old one; each transaction reads the version consistent with its own snapshot. Readers
never wait for writers (and vice versa), and a transaction sees a stable view of the data even while
others commit.

The building block is a **versioned key/value store**: a mapping from key to a *history* of versioned
values, with visibility decided by version/timestamp. On top of it, an MVCC store enforces transaction
isolation and detects the anomalies a weaker scheme would allow.

## In this repo

- **Implementation:**
  [`system/stores/VersionedKeyValueStore.py`](../../../system/stores/VersionedKeyValueStore.py) (the
  versioned base), [`system/stores/MVCC.py`](../../../system/stores/MVCC.py) (the MVCC store), and
  [`system/stores/IndexedMVCC.py`](../../../system/stores/IndexedMVCC.py) (an indexed variant).
- **Interface:** [`system/interfaces/stores.py`](../../../system/interfaces/stores.py).
- **Tests:** [`system/tests/stores/test_stores_basics.py`](../../../system/tests/stores/test_stores_basics.py) and
  [`system/tests/stores/test_store_anomalies.py`](../../../system/tests/stores/test_store_anomalies.py) — the latter
  drives concurrency anomalies (dirty read, lost update, …) and checks how the store handles them.
- **Notebook:** [`MVCC-Playground.ipynb`](../../../notebooks/MVCC-Playground.ipynb) — build schedules by
  clicking and run them on the MVCC store, operation by operation.
- **Visualization:** [`validation-interval-to-point.html`](../../../visualizations/validation-interval-to-point.html)
  — an animation of the serializable check (open it in a browser): a transaction that passes it shrinks from its
  interval [begin, commit] to a single point in time, a read-only transaction to its begin, and the points form the
  equivalent serial order.
- **Visualization:** [`call-through-dbms.html`](../../../visualizations/call-through-dbms.html) — the DBMS as a
  factory building whose floors are its layers (open it in a browser): the MVCC store and its versioned base share
  one floor, as they are one object, not two layers.

## The idea in one picture

```
key "x":   v1@t1 ──── v2@t5 ──── v3@t9        (version history, newest on the right)
                         ▲            ▲
   reader snapshot @t7 ──┘            └── writer appends v3@t9
   reads v2 (newest committed ≤ t7)       without blocking the reader
```

## Isolation levels

The MVCC store supports two isolation levels, chosen when the store is created with
`TransactionalKeyValueStore(isolation_level=...)`. In both, a transaction reads the snapshot of its begin plus its own
writes (snapshot read), and a transaction that writes an object which another transaction is still writing is
aborted. They differ in what else aborts a transaction:

- **serializable** (default): at the commit of a transaction that wrote something, the store checks whether a
  transaction that committed in the meantime changed something it read; if so, it is aborted. Because of this check,
  and as commits are installed one at a time, the committed transactions have the same effect as if they had run one
  after another.
- **snapshot isolation**: reads are not checked. Instead, a transaction that writes an object is aborted at once if
  another transaction changed that object and committed after the writer began (*first updater wins*).

Under snapshot isolation, *lost updates* cannot happen. In a lost update, two transactions read x and both write x,
so the second write overwrites the first without having seen it; under snapshot isolation the second writer is
aborted instead. *Write skew* can happen: two transactions read the same objects, and each changes a different one
based on what it read. Take two doctors s and t and the rule "at least one of them stays on call": both transactions
see both on call, and each takes a different one off; afterwards neither is on call.

```text
t_i                         t_j
begin
                            begin
read s, t
                            read s, t
update s
commit -> succeeds
                            update t
                            commit -> succeeds under snapshot isolation,
                                      aborts under serializable
```

Snapshot isolation does not always abort less often than serializable: a *blind write* (one that does not read the
object first) commits under serializable, as the result is the same as if t_j had run completely before t_i, but is
aborted under snapshot isolation:

```text
t_i                         t_j
begin
                            begin
                            update x
                            commit
update x -> serializable: passes, snapshot isolation: t_i is aborted
commit   -> succeeds (serializable only)
```

## Operations without a transaction id

`put`, `bulkload`, `get` and `delete` take no transaction id. What they do depends on the switch `autocommit`, set
when the store is created with `TransactionalKeyValueStore(autocommit=...)`, and mirrors autocommit in SQL:

- **autocommit off** (default): before the first transaction begins (also one that is aborted later), `put`,
  `bulkload` and `get` load and inspect the initial state. Its versions get the timestamp 0, so every transaction
  sees them, and no transaction id is used up. Once a transaction has begun, these calls raise an error, and `delete`
  always does: changes then need a transaction.
- **autocommit on**: each call runs as a transaction of its own (begin, operation, commit), like an SQL statement
  outside an explicit transaction; `bulkload` loads all its objects in one transaction. Explicit transactions can
  still be used, like `BEGIN` in SQL.

## Indexes over versions

In the indexed store, an index that you create on an attribute (`create_index`) maps a value to the ids of the
objects that have it. With versions, which objects have a value depends on the snapshot: one transaction may see an
older version of an object than another. The index stores no snapshots. Every version that carries the object goes
into the index under its value, committed versions as well as those a running transaction is writing; a delete is
stored as a version without an object (a delete marker) and is not indexed. A newer committed version does not
remove the entries of the older ones; an entry leaves the index only when the transaction that wrote it aborts or
writes the object again:

```text
object X:  a=1 @t1 ──── a=2 @t5 ──── a=3 @t9

index a:   1 -> [X]
           2 -> [X]
           3 -> [X]
```

So the index is a *filter*: for a value, it names every object that had that value in some version, a superset of
the right answer. A read `a == 2` that uses the index filters these candidates afterwards, in two steps:

1. **visibility:** it reads the version of the candidate that its snapshot sees; if the object is deleted or not
   inserted yet in that snapshot, the candidate is dropped;
2. **condition:** it checks `a == 2` again on that version; if the version has another value, the candidate is
   dropped.

A transaction with the snapshot t7 sees `a=2` and finds X; one with the snapshot t10 sees `a=3` and does not find X,
as X has the value 3 in its snapshot. The read through the index returns the same objects as a scan of all objects:
none is missing, as every version a snapshot can see is in the index, and none is wrong, as the snapshot decides.

The index could also store when each version is valid, e.g. under the key (value, from, to), and answer for a
snapshot directly. But then every commit would have to change the entry of the version it replaces (its "to"), and a
version that is still being written has no commit timestamp yet, so its "from" is not known. Real systems filter too:
PostgreSQL's index entries point to row versions without saying which snapshots see them, so it checks each row
version it reads, and InnoDB's secondary indexes do not store which versions are visible either. Unlike this store,
they remove the entries of versions that no snapshot can see any more (PostgreSQL with `VACUUM`, InnoDB with its
purge); here no committed version is ever removed, so the lists of candidates keep growing.

## Try it

Open the MVCC playground notebook: load a scenario (lost update, write skew, blind write, ...) or build a schedule
of your own, and run it operation by operation: serializable with method 1 or 2, under snapshot isolation, or without
validation. It shows each key's versions, every transaction's snapshot plus its own writes, what it read and wrote,
and whether the result is serializable.

Then read `test_store_anomalies.py`: each test sets up two interleaved transactions that would trigger a
classic anomaly, and asserts what the versioned/MVCC store returns.
