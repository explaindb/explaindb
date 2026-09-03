# The Storage Hierarchy

Storage is a hierarchy: small and fast at the top (DRAM), large and slow at the bottom (SSD, disk, tape,
a CDN…). Each layer acts as a **cache** for the one below it: a lookup that misses in this layer asks the
layer below, and the fetched value is kept here for next time. When a layer is full, it must **evict**
something to make room. This is the same idea whether the layers are CPU caches, a buffer pool over
disk, or a web cache over origin servers.

A twist this repo demonstrates is **prefix addressing**: an upper layer can use a different address space
than the layer below. An `AddressConversionStrategy` splits an address into *(address for the layer
below, offset within the fetched unit)* — e.g. a page id plus an offset inside that page — so the upper
layer caches individual sub-units of the pages held below it.

## In this repo

- **Implementation:** [`system/storage/storage_layer.py`](../../../system/storage/storage_layer.py) —
  `StorageLayer` (get/put, capacity, `fix`/eviction) and `AddressConversionStrategy` for prefix
  addressing.
- **Interface:** [`system/interfaces/stores.py`](../../../system/interfaces/stores.py) and the key/value
  contract in [`system/interfaces/indexing/Index.py`](../../../system/interfaces/indexing/Index.py).
- **Tests:** [`system/tests/test_storage.py`](../../../system/tests/test_storage.py) — including the
  prefix-addressing and eviction behaviour.

## The idea in one picture

```
   DRAM [fast, small] ── miss ──► SSD [slow, large, authoritative]
      ▲                              │
      └──── cache the fetched unit ──┘        evict when full (just drop locally)
   prefix address "21" = page 2, offset 1 ──► fetch SSD page 2, cache offset 1 in DRAM
```

Under a conversion strategy the upper layer is a **read cache**: the layer below is authoritative, so
eviction just drops the cached sub-unit locally without writing it back.

## Try it

Read `test_storage_layer_prefix_addressing` in `test_storage.py`: a two-layer DRAM-over-SSD hierarchy
where a DRAM address `"21"` means "offset 1 of page 2", fetched from the SSD page and cached in DRAM.
