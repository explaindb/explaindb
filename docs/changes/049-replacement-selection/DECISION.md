# 049 — Replacement selection for run generation
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/285
---
## Context

External merge sort in `system/query_processing/sorting.py` makes its runs by sorting chunks of M elements in memory;
a `TODO` marks the place for replacement selection. The lecture (slides 09b, 24–44) teaches replacement selection
with M = 4 elements: the root of a heap goes to the output run, the next input element goes into the heap if it is
not smaller than the last output, else into a list for the next run; an empty heap is bulk-loaded from the list and a
new run starts. Runs become about 2M long on random input, one run on sorted input, which can save a merge pass. A
playground notebook (050, 051) is to show this step by step, swap by swap, including the linear bulk load of the
heap, using this code rather than a second implementation.

## Decision

- A lazy iterator `ReplacementSelection` in `sorting.py`, in the style of `SingleStreamMerge`: it yields
  (run number, element); its heap, its list and its run number can be read between steps. A public
  `start_next_run()` bulk-loads the list into the heap when the heap is empty, so that a caller can see the new
  heap before the next output. Only `<` is used on elements; an element equal to the last output stays in the
  current run.
- The heap of replacement selection is spelled out in `sorting.py` instead of using `heapq`: `sift_down` (the
  textbook sift, stopping above an equal child, as the slides and the external sorting film do) and `bulkload`
  (Floyd's linear method: `sift_down` for every inner node, from the last to the root). The linear bulk load is part
  of what is taught, and `heapq.heapify` (C) cannot be followed node by node. The merges keep using `heapq`.
- `RunGenerator` and `ExternalMergeSort` get `replacement_selection: bool = False`; the default keeps the current
  chunk sorting. `create_runs` keeps its name and signature.
- Docs: the module docstring explains the two run generations and the two heaps; the README bullet on sorting, the
  tutorial page on external sorting and the External-Merge-Sort notebook name replacement selection.

## Consequences
**Positive:** The code teaches what the slides teach (textbook heap, linear bulk load) and is the single source for
the playground and a possible later film. Existing callers are unchanged.
**Negative:** `sorting.py` holds a second heap next to `heapq`'s. Memory is counted in elements of heap and list
only, as on the slides; the input and output buffers are not counted.

## Out of scope & deferred
- The playground notebook (050) and its comparison with runs sorted in memory (051).
- A film on replacement selection.
- Pages and variable record sizes.

## Alternatives rejected
- `heapq` for the heap of replacement selection: `heapify` cannot be followed node by node, and heapq's sift moves an
  element below equal children (leaf first, then up), unlike the slides and the film.
- Bulk load at the end of the step that empties the heap: the run number would then mean the run of the next
  output, which reads worse than an explicit `start_next_run()`.
- Events or callbacks for a view in `sorting.py`: visualisation concerns in production code; readable state is enough.
- `heappushpop`: returns the new element when it equals the root, so the output would not be the root.

<!-- notes below: skill never overwrites past this marker -->
