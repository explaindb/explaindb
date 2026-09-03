# 03 Query Processing

Once a plan is chosen, it has to *execute*. This section is about how a query actually runs: the shape of
the execution engine, and a set of classic execution techniques for specific query patterns.

- [**Operators & the Push Model**](<Operators & the Push Model.md>) — the operator tree and how tuples
  flow through it (this engine *pushes* tuples from the leaves up).
- [**Code Generation**](<Code Generation.md>) — compiling a plan into straight-line code instead of
  interpreting an operator tree.
- [**Shared Scan**](<Shared Scan.md>) — letting many concurrent queries share one pass over the data.
- [**External Sorting & Queues**](<External Sorting & Queues.md>) — sorting data far larger than memory,
  built on external (spill-to-disk) queues.
- [**Top-k & Online Aggregation**](<Top-k & Online Aggregation.md>) — returning the best *k* rows, and
  producing running estimates before the full scan finishes.
