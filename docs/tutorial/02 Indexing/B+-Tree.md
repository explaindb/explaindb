# B⁺-Tree

A **B⁺-tree** is a balanced search tree kept shallow by giving every node many children. Keys live in
sorted order; inner nodes hold separator keys and child pointers, and all real entries sit in the leaf
level, which is linked left-to-right. That shape gives two things at once:

- **Point lookups** in `O(log n)` — descend from the root following separators.
- **Range scans** — locate the lower bound, then walk the linked leaves until the upper bound.

Because it stays balanced under insertion and deletion, it is the workhorse index of almost every
relational system.

## In this repo

- **Notebook:** [`B-tree.ipynb`](../../../notebooks/B-tree.ipynb) — builds a B⁺-tree step by step and visualizes
  splits and the leaf chain.
- **Implementation:** [`system/indexes/btree.py`](../../../system/indexes/btree.py) — `BPlusTree`
  (uses `graphviz` to render the tree).
- **Interface:** [`system/interfaces/indexing/Index.py`](../../../system/interfaces/indexing/Index.py).

## The idea in one picture

```
                 [ 13 | 30 ]                 inner node: separators
                /     |     \
        [3|7|11]  [13|17|23]  [30|41]        leaf nodes, sorted
           →─────────→──────────→            leaves linked for range scans
```

A lookup for `17` follows `13 ≤ 17 < 30` into the middle leaf. A range scan for `[7, 30)` starts at the
leaf holding `7` and follows the leaf links until it passes `30`.

## Try it

Open `B-tree.ipynb` and insert keys one at a time — watch a node **split** when it overflows and the
tree grow by one level only when the root splits.
