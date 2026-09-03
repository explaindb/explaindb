# Cost & Cardinality

Enumeration needs a way to *score* each candidate plan — otherwise "best" has no meaning. Two ingredients:

- **Cardinality estimation:** how many rows an intermediate result has. Join sizes are estimated from
  base-table sizes and selectivities; the estimate for a subset of relations drives both the cost and the
  estimates for larger subsets built on top of it. Errors here compound, which is why cardinality
  estimation is famously the hard part of optimization.
- **Cost function:** turns a plan (and its estimated cardinalities) into a comparable number. A simple,
  popular choice is **C_out** — the sum of the sizes of all intermediate results — which rewards plans
  that keep intermediates small (the essence of good join ordering).

The enumerator asks the cost function to score each candidate split and keeps the cheapest.

## In this repo

- **Implementation:**
  [`system/query_optimization/cardinality_table.py`](../../../system/query_optimization/cardinality_table.py)
  (`CardinalityTable`) and
  [`system/query_optimization/cost_function.py`](../../../system/query_optimization/cost_function.py)
  (`C_Out`).
- **Interface:** [`system/interfaces/cost_functions.py`](../../../system/interfaces/cost_functions.py).
- **Tests:** [`system/tests/test_plan_enumeration.py`](../../../system/tests/test_plan_enumeration.py) —
  asserts exact cost and plan-table values.

## The idea in one picture

```
        ⋈             C_out(plan) = Σ |intermediate result|  over every join
       / \
      ⋈   C           |A⋈B|  +  |(A⋈B)⋈C|  + …
     / \              cardinalities estimated bottom-up; errors compound upward
    A   B
```

## Try it

In `test_plan_enumeration.py`, the `test_enumeration_utilities` test checks exact cost values — trace one
join order by hand and confirm its C_out matches.
