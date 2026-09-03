# Radix & Descriptor Tries

A **trie** indexes keys by their *representation* rather than by comparing whole keys: each level
consumes one piece of the key (a digit, a byte, a group of bits) and branches on it. Keys that share a
prefix share a path, so a lookup costs one step per key-piece — independent of how many keys are stored.

- A **radix trie** collapses chains of single-child nodes, so each edge can stand for several key-pieces
  at once — fewer nodes, shorter paths.
- A **descriptor trie** stores, at each node, a compact descriptor of which branches exist, so sparse
  fan-out does not waste a full slot array per node.

Tries shine for keys with structure (strings, multi-field keys, bit-decomposable values) and give
ordered traversal for free.

## In this repo

- **Notebook:** [`Christmas-Tree.ipynb`](../../../notebooks/Christmas-Tree.ipynb) — builds radix and descriptor
  tries (and related buffered / filtered-node variants) from the "Christmas lecture".
- **Implementation:** [`system/indexes/radix_trie.py`](../../../system/indexes/radix_trie.py) and
  [`system/indexes/christmas_tree.py`](../../../system/indexes/christmas_tree.py).
- **Interface:** [`system/interfaces/indexing/Index.py`](../../../system/interfaces/indexing/Index.py).

## The idea in one picture

```
insert "CAR", "CAT", "CATS", "DOG"

        (root)
        /     \
      C         D
      |         |
      A         O
     / \        |
    R   T       G
        |
        S
```

`CAR` and `CAT` share the `C-A` prefix and split only at the third character; `CATS` extends `CAT`.
A radix trie would merge the single-child `D-O-G` chain into one edge.

## Try it

Open `Christmas-Tree.ipynb` and insert keys with shared prefixes — see paths merge, and compare the node
count of a plain trie against the radix-compressed one.
