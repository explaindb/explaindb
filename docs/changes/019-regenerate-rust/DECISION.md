# 019 — Regenerate the Rust port from the current Python
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/162
---
## Context

The Rust code in `generated/rust/` is generated from the Python code in `system/` (see "Scope-shift 2026-10-19" in
[011's DECISION.md](../011-rust-store-foundation/DECISION.md)). The store core (features 011-014) was generated from
the Python at commit ffab2e8. Since then the Python changed: snapshot isolation in the MVCC store (017), the
playground mode for it (018, the playground itself is not ported), and the tests moved to `system/tests/<package>/`
and got docstrings with schedule tables. The CI job `generated_rust_check` therefore reports 7 Rust files as out of
date, and main is red since the first merge request of the series was merged. The user chose one regeneration merge
request on top of the series (after 016) rather than regenerating in each merge request.

## Decision

- Regenerate the 7 out-of-date files from the current Python and record all hashes with a plain
  `python3 .ci/check_generated.py --update`, so that the check passes with no file out of date.
- Snapshot isolation in Rust as in Python: an enum `IsolationLevel { Serializable, SnapshotIsolation }`
  (serializable by default) next to the validation method in `MvccState`. The configuration is checked in
  `MvccState` (user decision), so the indexed store of step 2 reuses the check: snapshot isolation with validation
  method 1 returns a new error `InvalidConfiguration` (Python: `ValueError`); an unknown level cannot be written in
  Rust. The existing constructors keep the level serializable.
- Under snapshot isolation, `update_object` and `delete_object` abort a transaction that writes an object another
  transaction committed after it began, after the existing check for another transaction's work-in-progress version
  and through the overridable `abort_transaction`, as in Python. `validate_transaction` returns `Ok(true)` at once
  under snapshot isolation, before it looks up the transaction, as Python does (user decision); for an unknown
  transaction it panics under serializable only.
- Port all tests Python added since ffab2e8 with all their variants, building the stores with the new constructor as
  Python does and checking the abort message; doc comments follow the current Python docstrings and their schedule
  tables. Rust-only tests cover the default level, the valid and invalid configurations, the error message, an
  overridden `abort_transaction` under snapshot isolation and an unknown transaction under snapshot isolation.

## Consequences

**Positive:** The Rust port matches the current Python again; `generated_rust_check` passes, so main turns green
when this merge request is merged. Students can compare snapshot isolation in both languages.

**Negative:** No failing-first test run is possible: the ported tests do not compile before `IsolationLevel` exists.
Of the ported tests, only the abort of a write to an object committed after begin, the write skew under snapshot
isolation and the invalid configuration fail without the feature; the others would also pass if snapshot isolation
did nothing. The benchmarks are not measured again: the added work is one comparison per write and per validation.

## Out of scope & deferred

- Skill `/regenerate-rust` that describes how to regenerate (next merge request, user decision).
- The indexed-store variant of the test of the write abort under snapshot isolation follows with the indexed store
  (step 2), which must forward the isolation level as `IndexedMVCC.py` does.
- The playground (including its snapshot isolation mode) stays Python only.
- A repository test that resolves relative links in Markdown files.
- Raising `sha2` to 0.11.1 from about 2026-10-26 (see 014).
- Dropping the duplicate test of 013 in `tests/stores/mvcc.rs`; the performance notes of the 013/014 reviews.

## Alternatives rejected

- One enum `Isolation { Serializable(Validation), SnapshotIsolation }` that cannot express the invalid combination:
  further from Python's two parameters and a larger change of the API used by 014 and 015.
- A constructor that panics on the invalid combination: Python raises a `ValueError`, not an assertion error.
- Checking the configuration only in `TransactionalKeyValueStore`: the indexed store of step 2 would have to repeat
  it.
- Keeping the panic of `validate_transaction` for an unknown transaction under snapshot isolation: Python returns
  `True` there.
- Regenerating in each merge request 013-016: the user chose one merge request on top of the series.

<!-- notes below: skill never overwrites past this marker -->

**Note 2026-10-19 (POC review):** A further Rust-only test checks that a committed transaction that writes is
reported as committed before the snapshot isolation check applies. A test that pins the order of the two write
checks (another transaction's work-in-progress version is reported before the snapshot isolation reason) follows in
its own merge request, first in Python, then regenerated (user decision). The doc comments of the older tests in
`tests/stores/test_store_anomalies.rs` follow the current Python docstrings, too; `tests/common/mod.rs` and
`tests/indexes/test_indexing.rs` needed no change, as the parts of their Python sources they port did not change.
