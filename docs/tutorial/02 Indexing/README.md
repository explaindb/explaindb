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

The B⁺-tree, the bitmap indexes and the radix trie share the common key/value index interface in
[`system/interfaces/indexing/Index.py`](../../../system/interfaces/indexing/Index.py); the Bloom filter
is a membership filter of its own. They differ in what they support: none of them supports deletes, the
bitmap indexes can only be bulkloaded, and unlike the others the B⁺-tree keeps only one value per key.
The indexed MVCC store uses none of them yet: its indexes are `PythonDictionaryIndex`es, which map a key
to all of its values.
