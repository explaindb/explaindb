# Database Systems Tutorial

A guided learning path through this repository. The material itself lives in the **Jupyter notebooks**
in the `notebooks/` directory and in the **`system/` package** (a small, didactic DBMS). This tutorial does not
repeat that content — it orders it, explains how the pieces fit together, and points you at the notebook
and the source files for each topic.

## How to use it

Each section below groups related topics. For every topic you get:

- a short explanation of the idea,
- **In this repo** — the notebook that demonstrates it and the key `system/` files that implement it,
- where useful, a minimal snippet or the central formula.

Read a topic here first, then open its notebook and run it to see it in action:

```sh
uv run jupyter notebook
```

(See the repository [`README.md`](../../README.md) for environment setup.)

## Table of Contents

### [01 Storage & Data Layout](<01 Storage & Data Layout>)

How bytes are arranged and where they live.

- [Row vs. Column Layout](<01 Storage & Data Layout/Row vs Column Layout.md>)
- [The Storage Hierarchy](<01 Storage & Data Layout/The Storage Hierarchy.md>)
- [RAID Cost Modeling](<01 Storage & Data Layout/RAID Cost Modeling.md>)
- [MVCC & Versioned Stores](<01 Storage & Data Layout/MVCC & Versioned Stores.md>)

### [02 Indexing](<02 Indexing>)

Data structures that turn a full scan into a lookup.

- [B⁺-Tree](<02 Indexing/B+-Tree.md>)
- [Bitmaps & Bloom Filters](<02 Indexing/Bitmaps & Bloom Filters.md>)
- [Radix & Descriptor Tries](<02 Indexing/Radix & Descriptor Tries.md>)
- [Recursive Model Index](<02 Indexing/Recursive Model Index.md>)

### [03 Query Processing](<03 Query Processing>)

How a query actually runs, operator by operator.

- [Operators & the Push Model](<03 Query Processing/Operators & the Push Model.md>)
- [Code Generation](<03 Query Processing/Code Generation.md>)
- [Shared Scan](<03 Query Processing/Shared Scan.md>)
- [External Sorting & Queues](<03 Query Processing/External Sorting & Queues.md>)
- [Top-k & Online Aggregation](<03 Query Processing/Top-k & Online Aggregation.md>)

### [04 Query Optimization](<04 Query Optimization>)

How the best plan is chosen before it runs.

- [Join Graphs & Problems](<04 Query Optimization/Join Graphs & Problems.md>)
- [Plan Enumeration](<04 Query Optimization/Plan Enumeration.md>)
- [Cost & Cardinality](<04 Query Optimization/Cost & Cardinality.md>)
- [Distributed Joins](<04 Query Optimization/Distributed Joins.md>)

### [05 Multidimensional](<05 Multidimensional>)

Indexing more than one dimension at once.

- [Z-Order Curve](<05 Multidimensional/Z-Order Curve.md>)
