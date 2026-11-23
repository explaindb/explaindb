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
- **Implementation:** [`system/query_processing/sorting.py`](../../../system/query_processing/sorting.py) and the
  queues in [`system/query_processing/queues/`](../../../system/query_processing/queues/) — `external_queues.py`
  (spill-to-disk), `list_queues.py` (in-memory), and `queue_factories.py`.
- **Interface:** [`system/interfaces/queues.py`](../../../system/interfaces/queues.py).
- **Tests:** [`system/tests/query_processing/test_sorting.py`](../../../system/tests/query_processing/test_sorting.py),
  [`system/tests/query_processing/queues/test_queues.py`](../../../system/tests/query_processing/queues/test_queues.py),
  [`system/tests/query_processing/queues/test_external_queues.py`](../../../system/tests/query_processing/queues/test_external_queues.py).

## The idea in one picture

```
input ─► [sort in-memory chunks] ─► run1 run2 run3 …  (on disk)
                                      \   |   /
                                       merge passes ─► fully sorted output
```

## Replacement selection

Run generation can also make runs longer than memory. **Replacement selection** keeps M elements in memory: a heap
for the current run and a list for the next one (|heap| + |list| ≤ M). It writes the heap's smallest element to the
current run and reads the next input element: if that is not smaller than the element just written, it still fits
into the current run and goes into the heap; otherwise it waits in the list. When the heap is empty, the list is
bulk-loaded into a heap (in linear time) and the next run starts. On random input the runs are about 2M long; on
sorted input there is a single run. Every run but the last holds at least M elements, so it never makes more runs
than sorting memory-sized chunks, and on such inputs far fewer.
In `sorting.py`, switch it on with `ExternalMergeSort(..., replacement_selection=True)` (or `RunGenerator`); the
iterator `ReplacementSelection` implements it with the heap functions `sift_down` and `bulkload`.

## Try it

In `External-Merge-Sort.ipynb`, shrink the in-memory budget and watch the number of runs (and merge
passes) grow — the whole point of doing it externally.
