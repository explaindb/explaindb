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

## Try it

Open the MVCC playground notebook: load a scenario (lost update, write skew, blind write, ...) or build a schedule
of your own, and run it operation by operation: serializable with method 1 or 2, under snapshot isolation, or without
validation. It shows each key's versions, every transaction's snapshot plus its own writes, what it read and wrote,
and whether the result is serializable.

Then read `test_store_anomalies.py`: each test sets up two interleaved transactions that would trigger a
classic anomaly, and asserts what the versioned/MVCC store returns.
