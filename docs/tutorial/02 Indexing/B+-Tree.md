# B⁺-Tree

A **B⁺-tree** is a balanced search tree kept shallow by giving every node many children. Keys live in
sorted order; inner nodes hold separator keys and pointers to their children, and all entries sit in the
leaves, each linked to its left and right neighbour. That shape gives two things at once:

- **Point queries** in `O(log n)`: descend from the root, following the separators.
- **Range queries**: find the lower bound like a point query, then walk along the linked leaves until a
  key is greater than the upper bound.

A B⁺-tree stays balanced under inserts, and with merges also under deletes; that makes it the workhorse
index of almost every relational system. The B⁺-tree in this repo supports inserts, splits, point and
range queries, but no deletes and no merges (see *Limits* below).

## In this repo

- **Notebook:** [`B-tree.ipynb`](../../../notebooks/B-tree.ipynb) builds the example tree of lecture
  06a by hand, inserts four keys and shows the tree after each insert; two of the inserts split a leaf,
  and the last one splits an inner node as well. It then runs a point and a range query, and uses a
  B⁺-tree to partition data.
- **Implementation:** [`system/indexes/btree.py`](../../../system/indexes/btree.py) holds `BPlusTree`
  and its node classes `Inner` and `Leaf`; `show()` draws the tree with `graphviz`.
- **Interface:** in [`system/interfaces/indexing/Index.py`](../../../system/interfaces/indexing/Index.py),
  `AbstractBTree` is a `KeyValueStore` (`put`, `get`) that also answers range queries
  (`RangeQueryMixIn.get_all_in_range`).
- **Tests:** `BPlusTreeTest` in
  [`system/tests/indexes/test_indexing.py`](../../../system/tests/indexes/test_indexing.py) runs point
  and range queries on random trees, and
  [`system/tests/indexes/test_btree_invariants.py`](../../../system/tests/indexes/test_btree_invariants.py)
  checks the invariants below.

## The idea in one picture

```
                 [ 13 | 30 ]                 inner node: separators
                /     |     \
        [3|7|11]  [13|17|23]  [30|41]        leaves, sorted
           ↔─────────↔──────────↔            each leaf linked to its neighbours
```

A point query for `17` follows `13 ≤ 17 < 30` into the middle leaf: a key equal to a separator belongs to
the subtree right of it. A range query for `[7, 30]` (both bounds included) starts at the leaf holding
`7` and follows the leaf links: it returns the values of `7`, `11`, `13`, `17`, `23` and `30` and stops
at `41`, the first key greater than `30`.

## Using it

The following code builds exactly the tree of the picture above:

```python
from system.indexes.btree import BPlusTree

tree = BPlusTree[int, str](inner_capacity=3, leaf_capacity=3)
for key in [3, 7, 13, 17, 11, 30, 41, 23]:
    tree.put(key, f"value {key}")

list(tree.get(17))                  # ['value 17']
list(tree.get_all_in_range(7, 30))  # the values of 7, 11, 13, 17, 23 and 30
tree.show()                         # draws the tree (in a notebook)
```

- **Capacities:** `inner_capacity` is the maximum number of keys of an inner node, `leaf_capacity` the
  maximum number of entries of a leaf; they are the lecture's n<sub>capacity</sub> and
  n<sup>*</sup><sub>capacity</sub> (slide "B-Trees (Alternative Simplified Definition)"). The defaults
  are 3 and 4.
- **Splits:** when a key does not fit into its leaf, the leaf splits into two, and the first key of the
  new right leaf is **copied** up into the parent as a separator. When the parent is full as well, it
  first takes the key anyway, one more than fits, and then splits: the key between its two halves
  **moves** up. Each node's `put` reports this to its caller: `NoSplit`, or `SplitHappens` with the two
  new nodes and the key that goes up (`pivot`). When the root splits, `BPlusTree.put` creates a new root
  above the two halves: the tree grows at the top, so all leaves stay equally deep.

## Invariants

A valid B⁺-tree keeps the five invariants of lecture 06a:

1. **Inv1:** each node partitions the keys of its subtree: between the separators `a` and `b`, a pointer
   leads to a subtree that holds only keys `k` with `a ≤ k < b`.
2. **Inv2:** every node except the root is at least half full. For a leaf this counts its entries, for an
   inner node its pointers: after a split, an inner node of capacity 3 may hold only 1 key, but it still
   has 2 of its 4 pointers.
3. **Inv3:** all leaves lie at the same depth.
4. **Inv4:** the keys inside each node are sorted, which allows binary search inside a node.
5. **Inv5:** each leaf is linked to its left and right neighbour.

`BPlusTree.consistency_check()` checks all five and raises an `AssertionError` whose message starts with
the name of the broken invariant, e.g. `Inv2: the leaf [39] holds 1 of 4 entries, ...`.
`test_btree_invariants.py` calls it after every single insert into trees of several capacities, and
breaks each invariant on purpose, in one or more ways, to show that the check finds it.

## Limits of this implementation

- **No deletes:** `delete` raises `NotImplementedError`; there are no merges of nodes either.
- **One value per key:** `put` with a key that is already in the tree replaces its value, so the tree
  keeps only the last value of a key that is put twice. `PythonDictionaryIndex`, in contrast, keeps all
  values of a key; only such an index can index an attribute whose values repeat.
- **Missing keys:** `get` returns an iterator that raises `KeyError` when it is read for a key that is
  not in the tree.
- **No bulk loading:** `bulkload` inserts the pairs one by one with `put`.

## Try it

Open `B-tree.ipynb`. Its first part shows the trees of lecture 06a (slides 16 to 22). Change the keys of
the four `put` calls in that cell, or add more, to watch other splits, and see the tree grow by one level
only when the root splits.
