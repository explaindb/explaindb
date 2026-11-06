# Shared Scan

When many queries each need to scan the same large table, doing one independent pass per query wastes
bandwidth. A **shared scan** runs a *single* pass over the data and feeds every concurrent query from it:
each tuple read from storage is handed to all interested queries at once. The expensive I/O is paid once
and amortized across all of them.

The subtlety is that queries arrive at different times and start at different positions, so a shared scan
typically reads the table cyclically and lets each query consume tuples from wherever the shared cursor
currently is until it has seen the whole table.

## In this repo

- **Notebook:** [`Shared-Scan.ipynb`](../../../notebooks/Shared-Scan.ipynb) — starts from a simple
  `SELECT * FROM stuff WHERE a = 7`-style query, runs several such queries with one scan each, and then with
  one shared scan, once with a result list per query and once with a single list of tagged tuples. All
  queries are known before the scan starts, so the notebook shows a single plain pass, not the cyclic scan.

## The idea in one picture

```
        ┌────────── one cyclic pass over the table ──────────┐
 table ─┤  tup ─┬─► Q1                                        │
        │       ├─► Q2    each tuple is handed to every       │
        │       └─► Q3    active query → I/O paid once        │
        └─────────────────────────────────────────────────────┘
```

## Try it

In `Shared-Scan.ipynb`, count for *N* queries how many tuples Algorithm 2 (one scan per query) and
Algorithm 3 (shared scan) read, and how many predicates they test: the shared scan reads each tuple once
instead of *N* times, but tests just as many predicates.
