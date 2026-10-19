# 014 — Rust port of the MVCC store, part 2: checksum validation
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/147
---
## Context

Part 1b-2 of the Rust port of the store core (series decisions: 011; the MVCC store with validation method 2:
013). Python's `TransactionalKeyValueStore` has a second validation method, chosen by `use_brute_force_validation`:
method 1 keeps a checksum of the result of each read and, at commit, runs every read again at the commit timestamp
and compares the checksums. `read_objects` then reads twice: once without the transaction's own changes for the
checksum, once with them for the result. The user chose SHA-256 checksums as in Python, over the `Debug` text of
the result instead of Python's `repr`.

## Decision

- **Choosing the method.** An enum `Validation { BruteForce, WriteSets }` (method 1 / method 2) replaces Python's
  flag; it is a field of the store's state, `WriteSets` by default as in Python, set by `with_validation`
  constructors.
- **Checksum.** A function `checksum` hashes the `Debug` text of the list of `(object id, object)` pairs with
  SHA-256 (crate `sha2`) and writes it as lowercase hex, byte by byte. `read_snapshot` computes it whenever method 1
  is chosen, as Python's `_read_snapshot` does. The `Debug` text must show the full content of a value: a value
  type whose `Debug` hides fields can hide a change, and validation would then pass where it should abort; equal
  content with different text only causes unnecessary aborts. `Debug` output may differ between Rust versions,
  which does not matter, as checksums are only compared within one process.
- **Same steps as Python.** `read_objects` computes the checksum over the committed snapshot (without the
  transaction's own changes), then reads with them; the where clause is evaluated twice per object, as in Python.
  Validation keeps the short-cut for a transaction that wrote nothing; method 1 then runs each read again at the
  commit timestamp and fails on the first changed checksum; it does not look at the write sets of other
  transactions.
- **Dependencies.** `sha2` is held at 0.11.0, as 0.11.1 was only days old; the crates it brings were checked on
  2026-10-16 (digest 0.11.3, block-buffer 0.12.1, crypto-common 0.2.2, hybrid-array 0.4.15, cpufeatures 0.3.1,
  cfg-if 1.0.5, typenum 1.20.1), all at least two weeks old. The audit job of 012 checks them.
- **Tests.** Each anomaly test that Python runs with both methods becomes two tests, one per method, so a failure
  names the method. Python's tests of method 1 alone are ported. Further tests tell the methods apart: how often
  validation evaluates the where clauses at commit, an error that only method 2 can return, and whether a snapshot
  carries a checksum. The expected checksum in a test is a fixed hex literal.

## Consequences
**Positive:** Both validation methods of Python run in Rust, with the same tests; students can compare the two in
both languages, and the benchmarks can measure both.
**Negative:** One more dependency with its crates. Checksums differ from Python's (`Debug` text instead of `repr`),
so they cannot be compared across languages; the soundness of method 1 depends on the value type's `Debug`.

## Out of scope & deferred
- The indexed store and the serializability test (step 2), benchmarks (step 3).
- Computing a checksum only where it is used (Python also computes one in the second read and discards it).

## Alternatives rejected
- **Storing the read results and comparing them with `==`:** exact and without a dependency, but the user chose
  SHA-256 checksums as in Python.
- **Rust's `Hash`:** needs the value type to implement `Hash`, and is not collision-resistant.
- **A boolean flag as in Python:** an enum names the two methods at every call site.
- **A test trait for constructing a store with a method:** the tests set the method in the store's state, which
  needs no extra trait.

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-16 (POC review):**
- `sha2` is held at 0.11.0 in `Cargo.toml` itself (`=0.11.0`, user decision), so `cargo update` does not move it.
  0.11.1 (2026-10-12) fixes how the AArch64 backend loads its round constants, to satisfy Rust's Stacked Borrows
  model; there is no advisory, and the x86_64 CI runners do not use that backend. Raise it to 0.11.1 from about
  2026-10-26, when it is two weeks old.
- Two more crates come with `sha2`: `const-oid` 0.10.2 (via `digest`) and `libc` 0.2.190 (via `cpufeatures`, used
  on AArch64; published 2026-10-02, exactly two weeks old on 2026-10-16).
- The audit job of 012 is not part of this stack (it branches from 011): it checks these crates once 012 is merged,
  which should happen before this feature.

**Note 2026-10-16 (Phase 3):** The tests that tell the methods apart also include: a transaction that wrote
nothing skips validation with method 1 (no where clause evaluated at commit), and a non-transactional `put` of a
matching object between a read and the commit aborts the transaction only with method 1 (method 2 sees no
concurrent write). `cargo mutants`: 150 mutants, 105 caught, 41 do not compile, 4 missed — all print or `Debug`
output only.

**Note 2026-10-16 (final review):** Tests pin exact checksums as hex literals. As they depend on the `Debug` text of
the Rust version in `rust-toolchain.toml`, a Rust upgrade that changes that text makes them fail, although the
store still works; the expected values then have to be computed again.

**Note 2026-10-16 (review of the MR stack):**
- The branches 013 to 016 now build on 012, so the audit job checks the new crates in this merge request already.
- The tests in `tests/mvcc.rs` that tell the two methods apart are named `..._by_method_with_method_1` and
  `..._by_method_with_method_2`.
- `rust/README.md` also lists that Python's default `repr` shows an object's memory address, so Python treats an
  equal but new object as changed; Rust's `Debug` text shows only the content.

**Note 2026-10-19 (rebase):** The paths moved from `rust/` to `generated/rust/`, whose modules and tests mirror
`system/`: `src/mvcc.rs` is now `src/stores/mvcc.rs`, `tests/mvcc.rs` is `tests/stores/mvcc.rs` and
`tests/store_anomalies.rs` is `tests/stores/test_store_anomalies.rs`; see "Scope-shift 2026-10-19" in
[011's DECISION.md](../011-rust-store-foundation/DECISION.md). The `rust/...` paths above are the old paths, as they
were when the decision was made. Pinned checksums that a Rust upgrade breaks are computed again by regenerating the
tests, not by editing them.

**Note 2026-10-19 (review of the rebase):** A new Rust-only test, `validation_checks_every_read_with_method_1` in
`tests/stores/mvcc.rs`, checks that method 1 runs every read of a transaction again, not only the first one.
