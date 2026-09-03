# Plan Enumeration

The number of possible join orders explodes with the number of relations, so the optimizer uses **dynamic
programming**: compute the best plan for every subset of relations from smaller subsets up, reusing
sub-results. The best plan for a subset *S* is the cheapest way to split *S* into two connected pieces,
join their (already-optimal) plans, and combine the cost.

Several enumeration strategies fill that DP table differently:

- **DPsize** — enumerate subsets by increasing size.
- **DPsub** — for each subset, enumerate its subset partitions directly (Knuth's increasing-order subset
  walk on the bit-set).
- **DPccp** — enumerate only *connected complement pairs*, skipping splits that are not connected in the
  join graph, which is far fewer for sparse graphs.

They all share the same DP table and cost model; they differ only in *which* subproblems they visit and
in what order.

## In this repo

- **Notebook:** [`PlanEnumeration.ipynb`](../../../notebooks/PlanEnumeration.ipynb) — builds the enumeration
  algorithms and runs them over the different join-graph topologies.
- **Implementation:** [`system/query_optimization/plan_table.py`](../../../system/query_optimization/plan_table.py)
  (`StandardPlanTable`, `SizeBasedPlanTable`), the subset walk in
  [`system/query_optimization/problems.py`](../../../system/query_optimization/problems.py), and helpers
  in [`system/query_optimization/utils.py`](../../../system/query_optimization/utils.py).
- **Interface:** [`system/interfaces/query_optimization/planning.py`](../../../system/interfaces/query_optimization/planning.py).

## The idea in one picture

```
best[S] = min over connected splits S = S1 ∪ S2 of  join( best[S1], best[S2] )

   {A}{B}{C}{D} ─► {AB}{BC}{CD}… ─► {ABC}{BCD}… ─► {ABCD}
   dynamic programming: build each subset's best plan from optimal smaller ones
```

## Try it

In `PlanEnumeration.ipynb`, run DPsub and DPccp on a chain vs. a clique and compare how many subproblems
each visits — the gap is the whole point of DPccp.
