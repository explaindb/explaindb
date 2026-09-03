# Operators & the Push Model

A query plan is a **tree of operators** — scans/relations at the leaves, then filters, joins,
projections, and a sink at the root. Tuples flow through this tree. Two dual disciplines exist:

- **Pull (Volcano/iterator):** the root calls `next()` on its child, which calls `next()` on its child…
  data is *pulled* down-to-up on demand.
- **Push:** the leaves drive the loop and *push* each tuple to their parent via `interpret_next(tup)`;
  each operator reacts and pushes onward. This engine uses the push model.

Each operator implements three phases: `interpret_open` (start; leaves run their loop and push tuples),
`interpret_next` (react to an incoming tuple), and `interpret_close` (tear down / free resources). A
simple-hash join (`SHJ`), for example, builds a hash table from one input, then probes it with the
other.

## In this repo

- **Implementation:** [`system/query_processing/operators.py`](../../../system/query_processing/operators.py)
  (`Relation`, `Scan`, `Filter`, `SHJ`, `SemiJ`, `Print`, `Collect`, `Count`) and
  [`system/query_processing/predicates.py`](../../../system/query_processing/predicates.py).
- **Interfaces:**
  [`system/interfaces/query_processing/operators.py`](../../../system/interfaces/query_processing/operators.py),
  [`system/interfaces/query_processing/query_processing.py`](../../../system/interfaces/query_processing/query_processing.py).
- **Notebook:** [`Result-DB.ipynb`](../../../notebooks/Result-DB.ipynb) — executes a two-join query
  (`persons ⋈ orders ⋈ books WHERE price < 10`) by assembling and running the operator pipeline.
- **Tests:** [`system/tests/test_query_processing.py`](../../../system/tests/test_query_processing.py),
  [`system/tests/test_code_gen.py`](../../../system/tests/test_code_gen.py).

## The idea in one picture

```
Collect                         open() flows down; tuples are pushed up:
   └─ SHJ (build ⋈ probe)         Relation.interpret_open → parent.interpret_next(tup) → … → Collect
        ├─ Relation persons       close() propagates down to the leaves to free resources
        └─ Filter price<10
             └─ Relation books
```

## Try it

Open `Result-DB.ipynb` and follow one tuple from a leaf `Relation` up through the join to the `Collect`
sink; then compare with the *compiled* version in [Code Generation](<Code Generation.md>).
