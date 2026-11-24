# 052 — Replacement selection in one memory array
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/290
---
## Context

`ReplacementSelection` (049) keeps the heap and the list as two separate Python lists. The textbook method, and the
lecture's point that main memory holds M elements, is one array of M places: the heap at its front, the list behind
it; each element that has to wait for the next run takes the place the heap gives up, so the heap shrinks and the list
grows in the same memory, and an empty heap leaves an array that is bulk-loaded in place into the next run's heap. The
user found the playground's two separate areas misleading ("eigentlich ist es ja nur eine Liste oder ein Array") and
chose to make the code itself work in place, so that the playground can show the array as it is.

## Decision

- `ReplacementSelection` keeps one array `memory` of min(M, n) places (None marks an empty place) and `heap_size`: the
  heap is `memory[:heap_size]`, the list the places behind it. The constructor fills the array with the first
  min(M, n) elements in reading order as the list; the first `start_next_run` bulk-loads them in place.
- Each step outputs the root and draws the next element x. If x is not smaller than the output, it takes the root's
  place and sinks within the heap. If it is smaller, the heap's last element takes the root's place, the heap gives up
  its last place, x goes into that place as the list's newest element (the list grows towards the front, newest
  first), and the new root sinks. If the input is empty, the heap's last element takes the root's place and the freed
  place stays empty. When the heap is empty, the list's elements move to the front in their memory order, closing the
  empty places, and are bulk-loaded in place.
- `sift_down` and `bulkload` take an optional `size`, so that they work on the heap at the front of the array.
- Read-only views stay for callers: `heap`, `pending` (the list in memory order, newest first), `run`, and new
  `memory` (a copy) and `heap_size`. `RunGenerator` and `ExternalMergeSort` are unchanged.
- The justification is the textbook method and exact memory use (M places, nothing else), not a view: the code stays
  free of visualisation concerns, as 049 decided.

## Consequences
**Positive:** The code is the textbook's in-place replacement selection; memory use is exactly the array; the
playground (050) can show memory as one array without a second model.
**Negative:** The list is newest first, so the heap of every later run differs in layout from the old code and from
the slides (on the slides' input run 1's heap is 16 33 26 50 instead of 16 26 33 50), and equal values may leave a
run in another order; the runs themselves hold the same elements as before (the sequence of outputs is the same, and
whether an element joins the current run depends only on its value and that output).

## Out of scope & deferred
- The playground's array view (050, scope shift there).
- Reversing the list before the bulk load to match the slides' order (not part of the textbook method).

## Alternatives rejected
- Keeping two lists and drawing one array only in the playground: the view would show a layout the code does not have.
- A list that grows from the array's end in arrival order: every new element would shift the list by one place.

<!-- notes below: skill never overwrites past this marker -->

**2026-11-24, implementation:** as None marks an empty place of the array, a None input element is rejected with a
ValueError (in the constructor and in `__next__`), so that it cannot vanish from the runs unnoticed. On the slides'
input the bulk load of run 1 (the list 50 33 26 16) takes three swaps.
