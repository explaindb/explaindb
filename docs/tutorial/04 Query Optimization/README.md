# 04 Query Optimization

Before a query runs, the optimizer decides *how* to run it — above all, in **what order to join** the
relations, since that choice can change the runtime by orders of magnitude. This section covers the join
search space, the algorithms that explore it, the cost model that scores plans, and one distributed
twist.

- [**Join Graphs & Problems**](<Join Graphs & Problems.md>) — modeling the relations and their join
  predicates as a graph, and subsets of relations as bit-set "problems".
- [**Plan Enumeration**](<Plan Enumeration.md>) — dynamic-programming enumeration of join orders (DPsize,
  DPsub, DPccp).
- [**Cost & Cardinality**](<Cost & Cardinality.md>) — estimating how big intermediate results are and
  what a plan costs.
- [**Distributed Joins**](<Distributed Joins.md>) — executing a join when the data lives on several
  nodes.
