# Bitmaps & Bloom Filters

Two different structures that both boil down to **bits**.

## The idea in one picture

```
Bitmap index — one bit per row, per distinct value:
                 row:  0 1 2 3 4 5
    color = "red"      1 0 0 1 0 1
    color = "blue"     0 1 0 0 1 0     "red AND size=S"  ─►  1 0 0 0 0 1
    size  = "S"        1 1 0 0 0 1     answered by bitwise AND, no row scan

Bloom filter — k hash functions into one small bit array:
    insert key ─h1,h2,h3─►  [ . 1 . . 1 . . 1 . ]   sets k bits
    lookup key ─h1,h2,h3─►   all k bits set? ─► "maybe"
                             any bit is 0?   ─► "definitely not"
```

A bitmap answers exactly by set algebra; a Bloom filter is a cheap
"maybe / definitely-not" pre-filter before the real lookup.

## Bitmap index

For a column with few distinct values, keep one **bit sequence per value**: bit `i` is set when row `i`
has that value. A predicate over such columns then becomes cheap bitwise algebra — `AND`, `OR`, `NOT`
across bitmaps — instead of a row-by-row scan. Long runs of equal bits compress well; this repo
implements **Word-Aligned Hybrid (WAH)** run-length compression so a sparse bitmap stays small and can
still be iterated and combined without decompressing it fully.

## Bloom filter

A **Bloom filter** answers *"is this key possibly in the set?"* using one small bit array and several
hash functions: a key sets `k` bits; a lookup checks those `k` bits. It has **no false negatives** (a
"no" is always true) but allows **false positives** (a "maybe" might be wrong). That makes it a perfect
cheap pre-filter — skip an expensive lookup when the filter says "definitely not here".

## In this repo

- **Notebooks:**
  [`Bitmaps-and-Bloom-Filters.ipynb`](../../../notebooks/Bitmaps-and-Bloom-Filters.ipynb) — bitmap indexes, WAH
  compression, and Bloom-filter membership; and
  [`Bit-Sequences-in-Pandas.ipynb`](../../../notebooks/Bit-Sequences-in-Pandas.ipynb) — the bit-sequence view of
  a column.
- **Implementation:**
  [`system/indexes/bitmap_indexes.py`](../../../system/indexes/bitmap_indexes.py),
  [`system/indexes/bloom_filters.py`](../../../system/indexes/bloom_filters.py), and the bit-sequence
  types (uncompressed, WAH) in [`system/bit_sequences.py`](../../../system/bit_sequences.py).
- **Interfaces:** [`system/interfaces/bit_sequence.py`](../../../system/interfaces/bit_sequence.py),
  [`system/interfaces/indexing/bitmap_indexes.py`](../../../system/interfaces/indexing/bitmap_indexes.py).

## The trade-off in one line

- **Bitmap:** exact, great for low-cardinality columns and set-algebra predicates; costs one bit per row
  per distinct value (mitigated by WAH compression).
- **Bloom filter:** tiny and fast, but only a probabilistic *pre*-filter — a "maybe" still needs the
  real lookup.

## Try it

In `Bitmaps-and-Bloom-Filters.ipynb`, compare answering a query with a bitmap index against a Bloom
filter, and watch how WAH keeps a sparse bitmap compact while still iterating its set bits.
