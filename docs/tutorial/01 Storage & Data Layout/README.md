# 01 Storage & Data Layout

Before a query can run, the data has to be *arranged* and *stored* somewhere. The choices made at this
level — how a record's fields are laid out, which storage medium holds them, how redundancy is added,
and how concurrent versions are kept — shape everything above.

- [**Row vs. Column Layout**](<Row vs Column Layout.md>) — storing records field-after-field vs.
  column-after-column, and why analytics prefers columns.
- [**The Storage Hierarchy**](<The Storage Hierarchy.md>) — caching across layers (DRAM → SSD → …),
  eviction, and prefix addressing.
- [**RAID Cost Modeling**](<RAID Cost Modeling.md>) — combining devices for throughput and resilience,
  and reasoning about the trade-offs with a cost model.
- [**MVCC & Versioned Stores**](<MVCC & Versioned Stores.md>) — keeping multiple versions of a value so
  readers and writers do not block each other.
