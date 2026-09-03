# Recursive Model Index

A **Recursive Model Index (RMI)** is a *learned* index. Instead of navigating pointers, it **predicts**
where a key sits. Over sorted data, the cumulative distribution function (CDF) maps a key to its
relative position; if you can approximate that CDF, `position ≈ model(key) × n`. The RMI approximates it
with a small **hierarchy of models**: a top model routes the key to one of several second-level models,
each of which fits its own slice of the key space more precisely. The prediction lands near the true
position, and a small **local search** (bounded by the model's error) finds the exact slot.

The pay-off: a lookup is a couple of arithmetic evaluations plus a short search — often a flatter, more
cache-friendly path than walking a tree — and the "index" is just the model parameters.

The flip side: it assumes a (mostly) **read-only, sorted** dataset whose distribution the models can
capture; updates and adversarial distributions are where classical trees keep the edge.

## In this repo

- **Notebook:** [`Recursive-Model-Index.ipynb`](../../../notebooks/Recursive-Model-Index.ipynb) — fits a
  two-level RMI to a dataset, visualizes the learned CDF, and measures prediction error vs. lookup cost.
  The RMI here is developed in the notebook itself (it has no separate `system/indexes/` module).

## The idea in one picture

```
              key
               │
         ┌─────▼─────┐
         │ top model │   routes the key to a leaf model
         └─────┬─────┘
       ┌───────┼───────┐
    ┌──▼─┐  ┌──▼─┐  ┌──▼─┐   each leaf model fits its own
    │ L0 │  │ L1 │  │ L2 │   slice of the sorted key space
    └──┬─┘  └────┘  └────┘
       │  pos ≈ L0(key) × n
       ▼
    sorted data:  … | … | ? | … | …
                       └ pos ┘  local search in [pos ± error] → exact slot
```

Two arithmetic evaluations predict a position; a small bounded search
around it finds the key — no pointer chasing.

## Try it

In `Recursive-Model-Index.ipynb`, increase the number of second-level models and watch the prediction
error — and thus the local-search window — shrink, trading model size for lookup speed.
