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
- **Tests:** [`system/tests/test_stores_basics.py`](../../../system/tests/test_stores_basics.py) and
  [`system/tests/test_store_anomalies.py`](../../../system/tests/test_store_anomalies.py) — the latter
  drives concurrency anomalies (dirty read, lost update, …) and checks how the store handles them.

*This topic is developed in the `system/` code and its tests rather than in a notebook — the anomaly
tests double as the worked examples.*

## The idea in one picture

```
key "x":   v1@t1 ──── v2@t5 ──── v3@t9        (version history, newest on the right)
                         ▲            ▲
   reader snapshot @t7 ──┘            └── writer appends v3@t9
   reads v2 (newest committed ≤ t7)       without blocking the reader
```

## Try it

Read `test_store_anomalies.py`: each test sets up two interleaved transactions that would trigger a
classic anomaly, and asserts what the versioned/MVCC store returns.
