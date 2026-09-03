# External Sorting & Queues

Sorting is everywhere in a database (ORDER BY, sort-merge joins, grouping). When the data does not fit in
memory, you need **external sorting**. The classic algorithm is **external merge sort**:

1. **Run generation:** read as much as fits in memory, sort it in memory, write the sorted **run** to
   disk. Repeat until the input is consumed.
2. **Merge:** merge the sorted runs together — reading a bit from each — into longer runs, repeating in
   passes until a single sorted output remains.

The workhorse underneath is an **external queue**: a FIFO that transparently spills to disk when it grows
beyond memory, so the algorithm can be written as if everything were in memory.

## In this repo

- **Notebook:** [`External-Merge-Sort.ipynb`](../../../notebooks/External-Merge-Sort.ipynb) — starts from a
  main-memory sort and builds up to the external, run-and-merge version.
- **Implementation:** [`system/sorting.py`](../../../system/sorting.py) and the queues in
  [`system/queues/`](../../../system/queues/) — `external_queues.py` (spill-to-disk), `list_queues.py`
  (in-memory), and `queue_factories.py`.
- **Interface:** [`system/interfaces/queues.py`](../../../system/interfaces/queues.py).
- **Tests:** [`system/tests/test_sorting.py`](../../../system/tests/test_sorting.py),
  [`system/tests/test_queues.py`](../../../system/tests/test_queues.py).

## The idea in one picture

```
input ─► [sort in-memory chunks] ─► run1 run2 run3 …  (on disk)
                                      \   |   /
                                       merge passes ─► fully sorted output
```

## Try it

In `External-Merge-Sort.ipynb`, shrink the in-memory budget and watch the number of runs (and merge
passes) grow — the whole point of doing it externally.
