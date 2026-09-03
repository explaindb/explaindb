# Join Graphs & Problems

A query that joins several relations is modeled as a **join graph**: one node per relation, one edge per
join predicate between two relations. The *shape* of this graph — chain, cycle, star, clique — determines
how many valid join orders exist and which enumeration algorithm is efficient.

During enumeration the optimizer reasons about **subsets of relations**. This repo represents such a
subset as a **bit sequence** called a `Problem`: bit *i* is set iff relation *i* is in the subset. That
turns set operations into cheap bit arithmetic — union, intersection, subset enumeration, "is this a
single relation (singleton)?", and mapping a set bit back to a relation id — which is exactly what the
enumeration algorithms need.

## In this repo

- **Implementation:**
  [`system/query_optimization/join_graph.py`](../../../system/query_optimization/join_graph.py)
  (`JoinGraph` and the `ChainQueryFactory` / `CycleQueryFactory` / `StarQueryFactory` /
  `CliqueQueryFactory` topologies) and
  [`system/query_optimization/problems.py`](../../../system/query_optimization/problems.py) (the bit-set
  `Problem` and its subset enumeration).
- **Notebook:** [`PlanEnumeration.ipynb`](../../../notebooks/PlanEnumeration.ipynb).
- **Tests:** [`system/tests/test_plan_enumeration.py`](../../../system/tests/test_plan_enumeration.py).

## The idea in one picture

```
join graph — one node per relation, one edge per join predicate:
        R0 ── R1 ── R2 ── R3
   a subset of relations is a bitmask (a `Problem`):
        {0, 2, 3}  →  bit  3 2 1 0
                           1 1 0 1   = 13
   union = |   ·   intersection = &   ·   "contains relation i?" = one bit test
```

Set operations on subsets become plain bit operations: union is `|`, intersection is `&`, and "does this
subset contain relation *i*?" is a single bit test — which is exactly what the enumeration and
connectivity checks need.

## Try it

In `test_plan_enumeration.py`, look at the neighbour/connectivity tests for the chain, cycle, star, and
clique topologies — they assert the exact bit-sets, which is the clearest way to see how `Problem`
encodes a subset of relations.
