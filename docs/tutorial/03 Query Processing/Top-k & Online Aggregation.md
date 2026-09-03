# Top-k & Online Aggregation

Two techniques that avoid doing more work than a query really needs.

## Top-k

`ORDER BY … LIMIT k` does **not** require fully sorting the input. Keep a bounded structure of size *k*
(a heap) while scanning: for each row, if it beats the current *k*-th best, insert it and drop the worst.
Cost is `O(n log k)` and memory `O(k)`, instead of sorting all *n* rows just to discard all but *k*.

## Online aggregation

For an aggregate like `SELECT max(b) FROM stuff` (or an average over a huge table), you do not have to
wait for the full scan to say something useful. **Online aggregation** produces a *running* result — and,
for averages/sums, a confidence interval — that tightens as more rows are read, so the user sees an
answer early and can stop when it is good enough.

## In this repo

- **Notebooks:** [`Top-k.ipynb`](../../../notebooks/Top-k.ipynb) — `ORDER BY title LIMIT 10` without a full
  sort; and [`Online-Aggregation.ipynb`](../../../notebooks/Online-Aggregation.ipynb) — a running estimate for
  an aggregate before the scan completes.

## The idea in one picture

```
Top-k:    scan ─► size-k heap [ best_1 … best_k ]   drop the worst on overflow
                  never full-sort → O(n log k) time, O(k) memory
Online:   answer ──coarse estimate now────────► refines as more rows arrive ──► exact
```

## Try it

In `Top-k.ipynb`, compare the work done by a full sort + limit against the heap-based top-k. In
`Online-Aggregation.ipynb`, watch the estimate converge as the fraction of scanned rows grows.
