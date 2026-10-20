# 017 — Snapshot isolation for the MVCC store
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/155
---
## Context

`TransactionalKeyValueStore` is serializable: every transaction reads the snapshot of its begin plus its own writes,
a write is aborted while another transaction holds an uncommitted version of the same object, and at commit the
reads are validated against the writes of transactions that committed meanwhile (method 1: checksums, method 2:
write sets). Students should also see the isolation level most systems actually run, snapshot isolation (SI), and
compare it with serializable: SI prevents lost updates but allows write skew. The MVCC playground already offers
"no validation", whose docstring describes it as weaker than SI (a lost update passes there that SI would abort).

## Decision

- A store-wide constructor parameter `isolation_level: Literal["serializable", "snapshot isolation"]` on the store
  itself, default `"serializable"`, so existing behaviour and callers are unchanged. `IndexedMVCC` forwards it.
  An unknown level and SI combined with `use_brute_force_validation=True` raise `ValueError` (two parameters are
  kept; the validation method only applies to serializable).
- Under SI, a write-write conflict is detected at the write (first updater wins, as in PostgreSQL): a transaction
  that writes an object is aborted at once if another transaction changed that object and committed after the
  writer began. Together with the existing check (another transaction is still writing the object) the later
  writer always loses. The check is a small private helper ("committed after begin?") called from `update_object`
  and `delete_object` before anything is written to the journal; transaction ids and commit timestamps share one
  counter, so it compares the newest committed version's timestamp with the writer's id.
- Under SI, `_validate_transaction` passes at once: reads are not validated, so write skew can happen.
- The check applies only under SI. Serializable stays as it is: a blind write after a concurrent commit commits
  there (it can be serialized after the other transaction), while SI aborts it. Docs state this explicitly, as
  students expect a weaker level to abort less.
- Docs: class docstring with the rules of both levels (plus one bridge sentence that older comments saying "under
  snapshot isolation" mean the snapshot read both levels use), and a new tutorial section "Isolation levels" with
  the write-skew and the blind-write schedules.
- Tests: a minimal set where every test catches a distinct wrong implementation (see the notes below).

## Consequences

**Positive:** students can run the same schedule under both levels and see lost update prevented and write skew
allowed under SI; the change is small and leaves the default behaviour untouched.
**Negative:** SI aborts some blind writes that serializable accepts; the term "snapshot isolation" now names both a
level and (in older comments) the read rule, bridged by one sentence instead of a rename.

## Out of scope & deferred

- Playground mode "snapshot isolation" in addition to "no validation", with a notebook exercise, a second branch in
  `abort_explanation` (it reads the wip entry, which is None for the new abort), expected outcomes per mode, and a
  test fixing which abort message wins when both checks apply — next MR.
- Isolation level per transaction (`begin_transaction(level)`).
- Serializable snapshot isolation (SSI; it allows schedules this store aborts, e.g. "serializable in another
  order", and aborts blind writes this store accepts).
- READ COMMITTED.
- Nightly schedule-space test that the oracle catches SI (only write skew remains).
- Parity in the Rust port.
- Renaming the older "under snapshot isolation" comments to "snapshot read" (cleanup backlog).

## Alternatives rejected

- Commit-time check (first committer wins): the same transactions abort, only later; the write-time check matches
  PostgreSQL and the playground's existing description.
- A subclass `SnapshotIsolationStore`: the store itself should learn the level, like `use_brute_force_validation`.
- One merged parameter (`"method 1" | "method 2" | "snapshot isolation"`): changes the existing interface.
- Level per transaction: mixing levels is hard to explain.
- Applying the write-time check under serializable too: needless aborts and changed existing behaviour.

<!-- notes below: skill never overwrites past this marker -->

## Notes: detailed plan (parked 2026-10-19, implemented 2026-10-19)

Agreed step by step with the maintainer and challenged by 8 parallel reviewers (tests, over-engineering, docs) plus
a final round; all findings are applied below. Implemented as planned in MR !155.

### Step 1: constructor parameter (MVCC.py)

- Add `Literal` to the `typing` import; module-level
  `IsolationLevel = Literal["serializable", "snapshot isolation"]` and
  `ISOLATION_LEVELS: tuple[IsolationLevel, ...] = ("serializable", "snapshot isolation")` with a `#` comment (same
  pattern as `Mode`/`MODES` in the playground).
- `__init__(..., isolation_level: IsolationLevel = "serializable")` as last parameter, stored as
  `self.isolation_level`.
- `ValueError` for an unknown level (message lists the allowed levels) and for SI + brute force (message:
  `snapshot isolation does not validate reads, so use_brute_force_validation=True requires
  isolation_level='serializable'`). No comment on the order of the two checks (not observable).
- Docstring: the `ValueError` cases go into the description text ABOVE the `@param` lines (the javadoc hook knows no
  `@raise`, and any line after a `@param` is appended to it). New `@param isolation_level` placed between
  `@param use_brute_force_validation` and `@param persistence_layer`, so the old `TODO: DISCUSS` / `@param journal`
  lines stay attached to `persistence_layer` as today; `@param use_brute_force_validation` gains "only applies to the
  isolation level serializable".

### Step 2: write-time check (MVCC.py)

```python
def _committed_after_begin(self, object_id: str, TA_id: int) -> bool:
    """Returns True if another transaction committed a version of object <object_id> after TA <TA_id> began.

    @param object_id: the object id of the object to be written
    @param TA_id: the transaction id of the writing transaction, i.e. its begin timestamp
    @return: True if the newest committed version of the object is newer than the begin of TA <TA_id>, False
    otherwise, in particular if there is no committed version
    """
    if object_id not in self.key_value_store:
        return False
    committed: list[VersionedKeyValueStore.VersionEntry] = self.key_value_store[object_id].committed
    # transaction ids and commit timestamps come from the same counter (non-transactional puts use 0), so a larger
    # timestamp means "committed after TA <TA_id> began":
    return len(committed) > 0 and committed[-1].start_validity > TA_id
```

In `update_object` and `delete_object`, directly after the existing wip check, before the first journal write:

```python
# snapshot isolation does not validate reads, so it cannot tell whether TA <TA_id> read the object; to rule out lost
# updates, it aborts every write to an object committed after TA <TA_id> began, even a blind one:
if self.isolation_level == "snapshot isolation" and self._committed_after_begin(object_id, TA_id):
    self.abort_transaction(TA_id)
    raise TransactionAbortedException(
        f"transaction {TA_id} aborted under snapshot isolation: another transaction changed object {object_id} "
        f"and committed after transaction {TA_id} began"
    )
```

`delete_object`'s `KeyError` for a missing key still comes from the existing wip check, before the journal.

### Step 3: validation (MVCC.py)

At the top of `_validate_transaction`: `# snapshot isolation does not validate reads (write skew can happen):` and
`if self.isolation_level == "snapshot isolation": return True`. `commit_transaction` and `read_objects` unchanged
(the serial-commit requirement holds for both levels: a commit must be installed in one go).

### Step 4: docstrings (MVCC.py)

- Class docstring replaces "Those changes are SERIALIZABLE. The write skew anomaly is detected and avoided." with:
  two levels chosen in `__init__`; in both, a transaction reads the snapshot of its begin plus its own writes
  (snapshot read; older comments saying "under snapshot isolation" mean this snapshot read, used by both levels);
  in both, a transaction that writes an object another transaction is still writing is aborted. In addition:
  serializable checks at commit whether a transaction that committed meanwhile changed something this one read
  (write skew detected); SI does not check reads, but aborts a writing transaction at once if another transaction
  changed the object and committed after the writer began — together "first updater wins"; lost updates cannot
  happen, write skew can. One sentence: a blind write after a concurrent commit is aborted under SI but commits
  under serializable; pointer to the tutorial page for both schedules. No schedule table here (if one is ever
  added to an MVCC.py docstring, introduce it with `::`, as Sphinx runs with `-W`).
- `update_object` / `delete_object`: add "Under snapshot isolation, also aborts the transaction if another
  transaction changed the object and committed after the transaction began."
- `_validate_transaction`: add "Under snapshot isolation, always passes, as reads are not validated (conflicting
  writes are refused in update_object / delete_object)."
- Say "the writing transaction is aborted", never "a write is aborted".

### Step 5: IndexedMVCC.py

Constructor gets `isolation_level: IsolationLevel = "serializable"`, forwards both parameters to `super().__init__`,
`:param` style of that file (continuation indented 4 spaces, pointing to `TransactionalKeyValueStore` for the
allowed values); import `IsolationLevel`. Nothing else changes (update/delete call super first, so the abort comes
before any indexing; `abort_transaction` de-indexes wip entries).

### Step 6: tests (system/tests/stores/test_store_anomalies.py, one block at the end of StoreTestAnomalies)

Prefixes `test_snapshot_isolation_level_` / `test_serializable_level_` (existing `test_snapshot_isolation_*` tests
mean the read rule). Docstrings with schedule tables, `t_i` (began first) and `t_j` (concurrent writer), current
behaviour only. A private method of `StoreTestAnomalies`, `_write(kind, store, object_id, TA_id)` with docstring,
removes the update/delete branching in A1 and A2 (an update writes a new `Stuff` value that differs from the old
one).

- A1 `test_snapshot_isolation_level_aborts_write_to_object_committed_after_begin` (SI only): t_i and t_j begin, t_j
  writes x and commits, t_i writes x -> aborted. Variants: t_j update|delete x t_i update|delete (4), on both store
  classes; plus t_j inserts a new key and t_i inserts the same key (TransactionalKeyValueStore only, IndexedMVCC
  asserts on inserts). `assertRaises` wraps only the write call; then t_i not in `TD`, journal of t_i exactly
  `[Begin, Abort]`, no wip entry left on x. Docstring: the indexed store checks that the parameter is forwarded.
- A2 `test_serializable_level_commits_blind_write_after_concurrent_commit` (serializable only): same schedule, t_j
  update|delete x t_i update|delete (4) -> t_i commits, its version is the newest. Docstring points to A1 and to
  `test_validation_detects_lost_update_on_read_object` (same schedule plus a read -> aborts under serializable);
  one sentence that an update after a committed delete re-inserts the object.
- B `test_snapshot_isolation_level_allows_write_skew`: both begin, both read s and t, t_i updates s and commits, then
  t_j updates t and commits -> both succeed, final state checked (values differ from the originals). Shows the SI
  check looks only at the written object; proves step 3. Contrast: `test_write_skew_anomaly`.
- C `test_snapshot_isolation_level_allows_write_to_object_committed_before_begin` (SI only): t_j updates x and
  commits, then t_i begins, updates x, commits -> succeeds.
- D `test_snapshot_isolation_level_rejects_invalid_configuration`: `ValueError` for an unknown level and for SI +
  brute force (subTests).
- E `test_snapshot_isolation_level_allows_reinsert_after_aborted_insert` (SI only): a key whose insert was aborted
  (no committed version) can be inserted again and committed.
- All existing tests unchanged (default serializable).

### Step 7: tutorial (docs/tutorial/01 Storage & Data Layout/MVCC & Versioned Stores.md)

New section "## Isolation levels" between "The idea in one picture" and "Try it", plain language, fenced `text`
schedule blocks (not indented under a bullet), one column per transaction, time down, outcome line at the end,
lines <= 120 chars:

- Two levels, chosen with `TransactionalKeyValueStore(isolation_level=...)`; in both, a transaction reads the
  snapshot of its begin plus its own writes, and a transaction that writes an object another transaction is still
  writing is aborted.
- serializable (default): at commit, the store checks whether a transaction that committed in the meantime changed
  something this transaction read; if so, it is aborted. As commits run one after another, the committed
  transactions have the same effect as if they had run one after another.
- snapshot isolation: reads are not checked; a transaction that writes an object is aborted at once if another
  transaction changed it and committed after the writer began (first updater wins). Lost updates (two transactions
  read x and both write x; the second overwrites the first without having seen it) cannot happen; write skew can,
  explained with the rule "at least one of s, t stays on call". Schedule: both begin, both read s and t, t_i updates
  s and commits, t_j updates t and commits -> succeeds under snapshot isolation, aborts under serializable.
- Blind write: "Snapshot isolation does not always abort less often than serializable: a blind write (one that does
  not read the object first) commits under serializable, as the result is the same as if t_j had run completely
  before t_i, but is aborted under snapshot isolation." Schedule: both begin, t_j updates x and commits, t_i updates
  x -> serializable: passes, snapshot isolation: t_i is aborted; t_i commit -> succeeds (serializable only).
- Existing lines 10-11 and "Try it" unchanged (the playground mode comes in the follow-up MR).

Re-checked against main on 2026-10-19 after the test-folder refactor (!156), the guard test (!158) and the module
moves (!157, !160): only the test path in Step 6 changed; the `isolation_level` parameter docstring placement and the
test helper were made precise. Stage files by explicit path (untracked `rust/` stays out).

Review of MR !155 (2026-10-19): the snapshot isolation check of `update_object` and `delete_object` moved into one
private method, `_abort_if_committed_after_begin`, built on `_committed_after_begin`; behaviour unchanged.

Rust port (2026-10-19): the parity in the Rust port, listed above as out of scope, is feature 019
([docs/changes/019-regenerate-rust](../019-regenerate-rust/DECISION.md)).

Snapshot read (2026-10-20): the older comments that said "under snapshot isolation" for reading now say "snapshot read",
and the class docstring of `TransactionalKeyValueStore` no longer explains them (deferred above).
