# 02 Indexing

An **index** is an auxiliary data structure that lets a query find matching rows without scanning the
whole relation. Different indexes make different trade-offs — the shape of the data, the kind of
predicate (equality, range, set membership), and the read/write mix all decide which one wins.

This section walks through four index families. Three are implemented in `system/indexes/`; the
Recursive Model Index is developed in its notebook only:

- [**B⁺-Tree**](<B+-Tree.md>) — the ordered, balanced default; equality *and* range lookups.
- [**Bitmaps & Bloom Filters**](<Bitmaps & Bloom Filters.md>) — one bit per row for set-style
  predicates, and a probabilistic membership pre-filter.
- [**Radix & Descriptor Tries**](<Radix & Descriptor Tries.md>) — digit-by-digit trees over the key's
  representation.
- [**Recursive Model Index**](<Recursive Model Index.md>) — a "learned index": models that *predict*
  a key's position instead of navigating pointers.

The three implemented families share the common key/value index interface in
[`system/interfaces/indexing/Index.py`](../../../system/interfaces/indexing/Index.py), so they are
interchangeable from the query engine's point of view.
