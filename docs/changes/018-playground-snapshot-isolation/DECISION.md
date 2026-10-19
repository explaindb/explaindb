# 018 — Playground mode snapshot isolation
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/161
---
## Context

Feature 017 gave `TransactionalKeyValueStore` the isolation level snapshot isolation (SI): a writing transaction is
aborted at once if another transaction changed the object and committed after it began (first updater wins), and
reads are not validated. The MVCC playground lets students run schedules in the modes "method 1", "method 2" and "no
validation"; its "no validation" store is described as weaker than SI. Students should be able to run the same
schedule under SI and compare. Run under SI, the eight scenarios end as under "no validation" except lost update,
where the second writer is aborted at its write — and the playground's abort explanation crashes there today, as it
assumes every write abort comes from another transaction's uncommitted version. Write skew (both variants) and the
read-only anomaly of Fekete et al. commit under SI and are not serializable. No scenario yet shows SI aborting where
methods 1 and 2 commit.

## Decision

- A fourth mode "snapshot isolation" next to the kept "no validation"; the modes are ordered method 1, method 2,
  snapshot isolation, no validation (by the anomalies they prevent). The mode builds the store of 017 with
  `isolation_level="snapshot isolation"`. Button label "snapshot isolation (first updater wins)"; the mode buttons
  get their own row, as four buttons beside the scenario dropdown get too wide.
- The abort explanation mirrors the store's two write checks in the store's order: another transaction's uncommitted
  version (existing text), then — under SI only — a commit of the object after the transaction began (new text naming
  the committing transaction); anything else is an internal error, like the commit branch.
- A ninth scenario "blind write": a transaction writes an object without reading it after another transaction
  committed it; methods 1 and 2 commit it, SI aborts it at the write — so students see that SI does not simply abort
  less.
- Notebook, tutorial "Try it" and the README notebook row describe the new mode; the notebook's mode text says when
  each mode decides (methods 1 and 2 at the commit, SI at the write, no validation never) and its exercises compare
  the modes on lost update, write skew, the read-only anomaly and the blind write.
- Tests pin each scenario's outcome per mode for all four modes (the mapping's keys must equal the modes), the SI
  abort explanation (naming the right writer when another transaction commits later on another key) and the order of
  the two checks when both apply.

## Consequences

**Positive:** the playground shows all three protection levels side by side (no protection, SI, serializable) and the
anomalies SI still allows; the abort explanation works for every abort the store can make.
**Negative:** one more mode and scenario to maintain in the outcome tables; the verdict's "order of the serialization
points" is a serializable notion that SI does not promise (the notebook says so).

## Out of scope & deferred

- Nightly schedule-space test that the serializability oracle catches SI (like `StoreWithoutValidation`).
- Per-mode notes in the verdict box (e.g. "snapshot isolation allows write skew").
- Making "no validation" an alias of something else or removing it.

## Alternatives rejected

- Replacing "no validation" by "snapshot isolation": the maintainer wants both, to show three protection levels.
- A playground subclass for SI: the store has the level since 017.
- A generic SI explanation ("aborted under snapshot isolation") without naming the committing transaction: the
  existing explanations name the other transaction.
- The blind write only as a build-your-own exercise: a scenario loads with one click and its outcome is tested.

## Scope-shift 2026-10-19

Review of MR !161: the button labels name the isolation level first, so methods 1 and 2 read as two implementations
of the isolation level serializable: "serializable - method 1 (re-run reads, checksums)", "serializable - method 2
(write sets)", "snapshot isolation - first updater wins" and "no validation". This replaces the label "snapshot
isolation (first updater wins)" named in Decision. The mode values stay unchanged.

<!-- notes below: skill never overwrites past this marker -->

## Notes: plan details (agreed 2026-10-19)

- Mode comment: "how the store decides which transactions to abort"; wording that assumes "validation" is updated
  (comment above `MODE_LABELS`, `test_mode_labels` docstring, `@param mode` of `abort_explanation` and `run_to`, the
  test comment on serialization points, `ExpectedOutcome` and test docstrings). `StoreWithoutValidation`'s docstring
  refers to the mode "snapshot isolation" for the comparison.
- `abort_explanation` write branch: (1) `wip is not None and wip.start_validity != record.TA_id` -> "<writer> is writing
  <key> and has not committed yet"; (2) `store.isolation_level == "snapshot isolation" and
  store._committed_after_begin(key, record.TA_id)` -> e.g. "snapshot isolation: <writer> changed <key> and committed
  after <name> began"; else `raise AssertionError`. The lookup "transaction whose commit timestamp is the newest
  committed version's start_validity" becomes a helper shared with the method-2 branch.
- Scenario "blind write" in `mvcc_scenarios.py` (initial state with x; T1 and T2 begin, T2 updates x and commits, T1
  updates x without reading it, T1 commits): methods 1/2 and no validation C,C; SI A,C (T1 aborted). Exact outcomes
  and verdicts are pinned by running the scenario.
- Tests: `EXPECTED_OUTCOMES[scenario]` maps every mode to (statuses, verdict kind), keys checked against `MODES` for
  every scenario. Writer lookup:

  ```text
  T1            T2            T3
  begin
                begin
                              begin
                update x
                commit
                              update y
                              commit
  update x -> aborted, explanation names T2
  ```

  Check order (passes already before the change, as a guard):

  ```text
  T1            T2            T3
  begin
                begin
                update x
                commit
                              begin
                              update x
  update x -> aborted, explanation "T3 is writing x and has not committed yet"
  ```

- Stacked on 017 (branch `feat/017-snapshot-isolation`, MR !155): the 018 branch starts from it and is rebased onto main
  once !155 is merged (fast-forward merges).
