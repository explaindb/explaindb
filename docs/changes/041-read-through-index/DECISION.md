# 041 — Reads through the index in the indexed MVCC store
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/229
---
## Context

The indexed MVCC store keeps one equality index per attribute and maintains it on every write, but no read used
it: `read_objects` scanned all objects. Each index is a filter index: every version whose object has the indexed
attribute is in it (committed versions and the work-in-progress versions of running transactions), so for a value it
returns the ids of a superset of the objects whose visible version has that value, with one id per indexed version.
Which version a transaction sees is decided by the snapshot read of the store. The serializable validation relies on
the read set (the where clauses a transaction read with) and, for the brute-force method, on a checksum over the
repr of the read result, which depends on its order.

User decisions: a read uses the index by itself (no separate method), and the order of the results is not defined;
what matters is that a read through the index returns the same results as the scan.

## Decision

The indexed store overrides the internal scan that every read goes through (`read_objects`, the brute-force
checksum read and the re-read of validation method 1). If the where clause is `attribute == constant` and an index
on that attribute exists, it takes the distinct candidate ids from the index (an absent value means no candidates),
gets for each candidate the version visible to the reader and keeps it if the where clause holds for it: the index
names candidates, the snapshot decides. Otherwise it scans as before. The read set is recorded as before, so both
validation methods cover reads through the index. The candidates are visited in sorted id order; the order is still
undefined for callers, but a fixed order keeps the brute-force checksum independent of the order in which versions
entered the index.

The main test compares the index read with the scan on the same store state after every step of a seeded random
workload (several concurrent transactions, inserts, updates, deletes, commits, aborts, the index created part-way
through), for both validation methods and snapshot isolation.

## Consequences

**Positive:** an equality read on an indexed attribute visits only the candidates instead of all objects, with the
same results as the scan; validation and read set stay unchanged; students see the interplay of index and snapshot
read in one place.

**Negative:** equality reads on the indexed store return their results in sorted id order (strings, "10" before
"2"), not in the scan order. If a visible object lacks the attribute, the scan raises while the index path may not
(the object is no candidate); this is the only case where the two paths differ. If an index is created or dropped
while a transaction runs, its brute-force re-read may take another access path than its read; a different order of
at least two results then causes an unnecessary abort. The index assumes that attribute values hash consistently
with `==` and that callers do not change returned objects in place (reads return the stored versions, not copies).

## Out of scope & deferred

- The indexed store with an index in the exhaustive serializability oracle test (unblocked by #54).
- Existing anomaly tests that use `a == c`: a variant on the indexed store with an index on `a`.
- Range reads (`<`, `<=`, `>`, `>=`) through a B-tree index; index types in the index properties.
- Conjunctions and disjunctions (one index plus a residual predicate, union for OR).
- Use of the indexes by the optimizer / query execution plans.
- A playground or notebook view of "index candidates vs. visible versions".
- Port of the indexed store to the generated Rust code (Rust regeneration later, user decision).
- Garbage collection of old versions together with their index entries.

## Alternatives rejected

- A separate method that reads through an index: the user chose automatic use; it would duplicate the read-set
  bookkeeping.
- Overriding `read_objects` instead of the internal scan: duplicates the read-set and checksum logic and misses the
  re-read of validation method 1.
- Results in scan order: needs a walk over all keys of the store again.
- Results in order of first appearance in the index: depends on the write history (including aborted versions), so
  the brute-force checksum could change without a visible change and cause unnecessary aborts.
- Version-aware index entries (validity intervals, the index decides visibility): bigger change; visibility stays in
  one place, the store.

<!-- notes below: skill never overwrites past this marker -->

**Note (2026-11-09, POC review):** "the only case where the two paths differ" under *Consequences* is too narrow.
The scan raises whenever reading or checking the visible version of an object that is no candidate fails, e.g. for an
object without the attribute (the where clause cannot be checked), or for an object whose committed versions are out
of order after a non-transactional `put` and `delete` (both use the start timestamp 0; a separate fix follows). A
read through the index never looks at such objects. If an index is dropped while a transaction runs, its re-read in
validation method 1 goes through the scan and can then raise inside `commit_transaction`.
