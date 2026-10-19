#
#    This is ExplainDB, educational database systems materials.
#
#    Copyright (C) 2026 Prof. Dr. Jens Dittrich, Saarland University
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
#

# Test modules use self-documenting method/class names and module-level
# fixtures, so pylint's naming and docstring checks are relaxed here.
# This module's schedules resemble the scenarios on purpose (duplicate-code).
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring,duplicate-code
"""Tests for the MVCC playground: running schedules operation by operation, showing the store, judging the outcome."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from system.playground.mvcc_playground import (
    MAX_ORDER_LINES,
    MODES,
    Mode,
    ObjectState,
    RunState,
    StoreWithoutValidation,
    TransactionState,
    Verdict,
    abort_explanation,
    Version,
    WorkInProgress,
    make_store,
    more_orders,
    order_line,
    run_to,
)
from system.playground.mvcc_scenarios import SCENARIOS, Scenario, schedule_of
from system.playground.schedules import (
    DataOperation,
    Difference,
    Row,
    Schedule,
    StoredObject,
    TransactionRecord,
)
from system.stores.MVCC import TransactionalKeyValueStore

# x is selected by a == 1:
INITIAL_X: tuple[StoredObject, ...] = (StoredObject("x", Row(1, 0)),)


def scenario_named(name: str) -> Scenario:
    """Returns the scenario of SCENARIOS with the given name."""
    return next(s for s in SCENARIOS if s.name == name)


def statuses(result: RunState) -> tuple[str, ...]:
    """Returns the status of every transaction, e.g. ``("committed", "aborted")`` for T1, T2."""
    return tuple(t.status for t in result.transactions)


class MakeStoreTest(unittest.TestCase):
    """Creating the store for a mode."""

    def test_store_per_mode(self) -> None:
        """Method 1 re-runs every read at the commit, method 2 checks the reads against the objects written by
        transactions that committed meanwhile, both at the isolation level serializable; "snapshot isolation" uses
        the store's isolation level snapshot isolation, and "no validation" does not validate.

        Would fail if a mode were mapped to the wrong store or isolation level, so the playground showed another
        mode than the one selected.
        """
        # per mode: the class of the store, whether it re-runs every read at the commit (None: the store does not
        # validate), and its isolation level:
        expected: dict[Mode, tuple[type, bool | None, str]] = {
            "method 1": (TransactionalKeyValueStore, True, "serializable"),
            "method 2": (TransactionalKeyValueStore, False, "serializable"),
            "snapshot isolation": (
                TransactionalKeyValueStore,
                False,
                "snapshot isolation",
            ),
            "no validation": (StoreWithoutValidation, None, "serializable"),
        }
        self.assertEqual(set(MODES), set(expected))
        for mode, (store_class, brute_force, isolation_level) in expected.items():
            with self.subTest(mode=mode):
                store: TransactionalKeyValueStore = make_store(mode)
                self.assertIs(store_class, type(store))
                if brute_force is not None:
                    self.assertEqual(brute_force, store.use_brute_force_validation)
                self.assertEqual(isolation_level, store.isolation_level)


@dataclass(frozen=True)
class ExpectedOutcome:
    """The outcome of a scenario run to the end in one mode: the statuses of the transactions and the verdict kind."""

    statuses: tuple[str, ...]
    verdict: str


# the statuses of the transactions, and the verdict kinds: serializable in the order of the serialization points
# (SAME), only in another order (OTHER), or not at all (NOT). The serialization point of a transaction that wrote
# is its commit timestamp: methods 1 and 2 check its reads against the state at that timestamp, so every run they
# let commit is serializable in this order. Under snapshot isolation and without validation the reads are not
# checked, so a run may be serializable only in another order or not at all. A read-only transaction also gets a
# commit timestamp, but it reads only the snapshot of its begin (no mode checks its reads), so its serialization
# point is its begin (its TA_id). Commit timestamps and TA_ids come from the same counter, so they can be compared.
# The verdict first replays the committed transactions in this order; aborted transactions are left out (see
# TransactionRecord.serialization_point and serial_order):
C: str = "committed"
A: str = "aborted"
SAME: str = "serializable"
OTHER: str = "serializable in another order"
NOT: str = "not serializable"

# the outcome of every scenario in every mode:
EXPECTED_OUTCOMES: dict[str, dict[Mode, ExpectedOutcome]] = {
    "serial": {
        "method 1": ExpectedOutcome((C, C), SAME),
        "method 2": ExpectedOutcome((C, C), SAME),
        "snapshot isolation": ExpectedOutcome((C, C), SAME),
        "no validation": ExpectedOutcome((C, C), SAME),
    },
    "lost update": {
        "method 1": ExpectedOutcome((C, A), SAME),
        "method 2": ExpectedOutcome((C, A), SAME),
        "snapshot isolation": ExpectedOutcome((C, A), SAME),
        "no validation": ExpectedOutcome((C, C), NOT),
    },
    "write skew": {
        "method 1": ExpectedOutcome((C, A), SAME),
        "method 2": ExpectedOutcome((C, A), SAME),
        "snapshot isolation": ExpectedOutcome((C, C), NOT),
        "no validation": ExpectedOutcome((C, C), NOT),
    },
    "write skew via phantom (insert and delete)": {
        "method 1": ExpectedOutcome((C, A), SAME),
        "method 2": ExpectedOutcome((C, A), SAME),
        "snapshot isolation": ExpectedOutcome((C, C), NOT),
        "no validation": ExpectedOutcome((C, C), NOT),
    },
    "phantom insert": {
        "method 1": ExpectedOutcome((A, C), SAME),
        "method 2": ExpectedOutcome((A, C), SAME),
        "snapshot isolation": ExpectedOutcome((C, C), OTHER),
        "no validation": ExpectedOutcome((C, C), OTHER),
    },
    "concurrent delete": {
        "method 1": ExpectedOutcome((A, C), SAME),
        "method 2": ExpectedOutcome((A, C), SAME),
        "snapshot isolation": ExpectedOutcome((C, C), OTHER),
        "no validation": ExpectedOutcome((C, C), OTHER),
    },
    "blind write": {
        "method 1": ExpectedOutcome((C, C), SAME),
        "method 2": ExpectedOutcome((C, C), SAME),
        "snapshot isolation": ExpectedOutcome((A, C), SAME),
        "no validation": ExpectedOutcome((C, C), SAME),
    },
    "read-only transaction": {
        "method 1": ExpectedOutcome((C, C), SAME),
        "method 2": ExpectedOutcome((C, C), SAME),
        "snapshot isolation": ExpectedOutcome((C, C), SAME),
        "no validation": ExpectedOutcome((C, C), SAME),
    },
    "read-only anomaly (Fekete et al.)": {
        "method 1": ExpectedOutcome((C, A, C), SAME),
        "method 2": ExpectedOutcome((C, A, C), SAME),
        "snapshot isolation": ExpectedOutcome((C, C, C), NOT),
        "no validation": ExpectedOutcome((C, C, C), NOT),
    },
}


class ScenarioOutcomeTest(unittest.TestCase):
    """Every scenario run to the end in every mode."""

    def test_outcome_and_verdict_per_mode(self) -> None:
        """Each scenario has a pinned outcome for every mode, and ends with its pinned transaction statuses and
        verdict kind in each mode.

        Would fail if a mode were added without pinning its outcomes, if methods 1 and 2 let an anomaly commit or
        aborted a transaction needlessly, if snapshot isolation stopped aborting the second of two writers of an
        object (lost update, blind write) or started to abort write skew, if the store without validation stopped
        showing the anomalies, or if the verdict misjudged a run.
        """
        # every scenario has a row, and every row belongs to a scenario:
        self.assertEqual({s.name for s in SCENARIOS}, set(EXPECTED_OUTCOMES))
        for s in SCENARIOS:
            expected: dict[Mode, ExpectedOutcome] = EXPECTED_OUTCOMES[s.name]
            with self.subTest(scenario=s.name):
                self.assertEqual(set(MODES), set(expected))
            for mode in MODES:
                with self.subTest(scenario=s.name, mode=mode):
                    result: RunState = run_to(
                        s.schedule, s.initial_state, mode, len(s.schedule)
                    )
                    self.assertEqual(expected[mode].statuses, statuses(result))
                    self.assertEqual(expected[mode].verdict, result.verdict.kind)


class VerdictTest(unittest.TestCase):
    """The verdict for the anomalies the store without validation lets through: its sentence, one line per serial
    order replayed, and the read to mark in the schedule."""

    def test_serializable_in_another_order(self) -> None:
        """The phantom insert without validation is serializable, but in the order T1|T2, not T2|T1; the lines stop
        at the order that matches, and T1's read (position 1) is marked.

        ```text
        T1                          T2
        begin
        read a==1 → {x}
                                    begin
                                    update y ← (a=1, b=0)
                                    commit
        update z ← (a=0, b=1)
        commit
        ```

        Would fail if the verdict stopped after the order of the serialization points, did not name the order
        that matches and why the other one does not, or marked another operation than the read that differs.
        """
        s: Scenario = scenario_named("phantom insert")
        result: RunState = run_to(
            s.schedule, s.initial_state, "no validation", len(s.schedule)
        )
        self.assertEqual(
            Verdict(
                "serializable in another order",
                "Serializable, but not in the order of the serialization points.",
                (
                    "Order T2|T1: T1's read a==1 would return {x: (a=1, b=0), y: (a=1, b=0)}, but returned "
                    "{x: (a=1, b=0)}.",
                    "Order T1|T2: same read results and final state.",
                ),
                1,
                "in the order T2|T1 this read would return {x: (a=1, b=0), y: (a=1, b=0)}",
            ),
            result.verdict,
        )

    def test_not_serializable(self) -> None:
        """Write skew via phantom without validation is not serializable; the verdict names the first difference of
        each order and marks T2's read (position 3), which differs in the order of the serialization points.

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
                                    read a==1 → {x}
        update y ← (a=1, b=0)
                                    delete x
        commit
                                    commit
        ```

        Would fail if some order were wrongly accepted, the verdict left out the difference of an order, or marked
        another operation than the read that differs.
        """
        s: Scenario = scenario_named("write skew via phantom (insert and delete)")
        result: RunState = run_to(
            s.schedule, s.initial_state, "no validation", len(s.schedule)
        )
        self.assertEqual(
            Verdict(
                "not serializable",
                "Not serializable: no serial order gives the same read results and final state.",
                (
                    "Order T1|T2: T2's read a==1 would return {x: (a=1, b=0), y: (a=1, b=0)}, but returned "
                    "{x: (a=1, b=0)}.",
                    "Order T2|T1: T1's read a==1 would return {}, but returned {x: (a=1, b=0)}.",
                ),
                3,
                "in the order T1|T2 this read would return {x: (a=1, b=0), y: (a=1, b=0)}",
            ),
            result.verdict,
        )

    def test_at_most_six_orders_are_shown(self) -> None:
        """Four lost updates without validation are not serializable in any of the 4! = 24 orders; the verdict shows
        the first six and counts the other 18.

        ```text
        T1              T2              T3              T4
        begin
                        begin
                                        begin
                                                        begin
        read all
                        read all
                                        read all
                                                        read all
        update x
        commit
                        update x
                        commit
                                        update x
                                        commit
                                                        update x
                                                        commit
        ```

        Would fail if the verdict listed all 24 orders, counted the orders not shown wrongly, or marked and explained
        another read than T2's, the first one that differs in the order T1|T2|T3|T4.
        """
        transactions: tuple[int, ...] = (1, 2, 3, 4)
        schedule: Schedule = schedule_of(
            *((n, "begin") for n in transactions),
            *((n, DataOperation("read")) for n in transactions),
            *(
                operation
                for n in transactions
                for operation in (
                    (n, DataOperation("update", "x", Row(1, n))),
                    (n, "commit"),
                )
            ),
        )
        result: RunState = run_to(schedule, INITIAL_X, "no validation", len(schedule))
        self.assertEqual("not serializable", result.verdict.kind)
        self.assertEqual(MAX_ORDER_LINES + 1, len(result.verdict.details))
        self.assertEqual(
            "Order T1|T2|T3|T4: T2's read all would return {x: (a=1, b=1)}, but returned {x: (a=1, b=0)}.",
            result.verdict.details[0],
        )
        self.assertEqual(
            "… and 18 more orders that differ.",
            result.verdict.details[-1],
        )
        # T2's read all, after the four begins and T1's read, is marked and explained:
        self.assertEqual(5, result.verdict.marked_position)
        self.assertEqual(
            {5: "in the order T1|T2|T3|T4 this read would return {x: (a=1, b=1)}"},
            result.explanations,
        )

    def test_one_more_order(self) -> None:
        """A single order not shown is counted in the singular.

        Would fail if the counting line said "1 more orders that differ".
        """
        lines: list[str] = ["Order T1|T2: ...", "Order T2|T1: ..."]
        self.assertEqual(
            lines + ["… and 1 more order that differs."], more_orders(lines, 3)
        )

    def test_order_line_of_a_final_state(self) -> None:
        """An order in which every read matches but the final state differs gets a line about the final state.

        Would fail if the line mixed up the final state of the run and that of the serial replay.
        """
        t_1: TransactionRecord = TransactionRecord("T1")
        t_2: TransactionRecord = TransactionRecord("T2")
        difference: Difference = Difference(
            transaction=None,
            read=None,
            position=None,
            observed=(StoredObject("x", Row(1, 2)),),
            serial=(StoredObject("x", Row(1, 1)),),
        )
        self.assertEqual(
            "Order T2|T1: the final state would be {x: (a=1, b=1)}, but is {x: (a=1, b=2)}.",
            order_line([t_2, t_1], difference),
        )


class ExplanationTest(unittest.TestCase):
    """Why an operation went wrong, by its position in the schedule."""

    def test_write_while_another_transaction_writes(self) -> None:
        """T2's update of x fails while T1 holds an uncommitted version of x; the explanation names T1.

        ```text
        T1                          T2
        begin
                                    begin
        update x ← (a=1, b=1)
                                    update x ← (a=1, b=2) -> aborted
        commit
                                    (commit: skipped)
        ```

        Would fail if the explanation named the wrong transaction or object, or stood at another operation.
        """
        schedule: Schedule = schedule_of(
            (1, "begin"),
            (2, "begin"),
            (1, DataOperation("update", "x", Row(1, 1))),
            (2, DataOperation("update", "x", Row(1, 2))),
            (1, "commit"),
            (2, "commit"),
        )
        result: RunState = run_to(schedule, INITIAL_X, "no validation", len(schedule))
        self.assertEqual(
            {3: "T1 is writing x and has not committed yet"}, result.explanations
        )

    def test_validation_per_method(self) -> None:
        """T2's commit fails the validation: method 1 names the read whose result changed, method 2 the object a
        transaction committed meanwhile and whether the read returned it before (lost update) or returns it now
        (phantom insert, where T1 aborts).

        Lost update, with method 1 and with method 2:

        ```text
        T1                          T2
        begin
                                    begin
        read all → {x}
                                    read all → {x}
        update x ← (a=1, b=1)
        commit
                                    update x ← (a=1, b=2)
                                    commit -> aborted <- position 7 (counted from 0)
        ```

        Phantom insert, with method 2:

        ```text
        T1                          T2
        begin
        read a==1 → {x}
                                    begin
                                    update y ← (a=1, b=0)
                                    commit
        update z ← (a=0, b=1)
        commit -> aborted                             <- position 6 (counted from 0)
        ```

        Would fail if the explanation did not follow the check of the selected method, or confused the results at
        the read and now.
        """
        for name, mode, expected in (
            (
                "lost update",
                "method 1",
                {
                    7: "validation: read all now returns {x: (a=1, b=1)}, but in the snapshot of T2's begin it returns "
                    "{x: (a=1, b=0)}"
                },
            ),
            (
                "lost update",
                "method 2",
                {
                    7: "validation: T1 changed x, which read all returns in the snapshot of T2's begin"
                },
            ),
            (
                "phantom insert",
                "method 2",
                {6: "validation: T2 changed y, which read a==1 returns now"},
            ),
        ):
            with self.subTest(scenario=name, mode=mode):
                s: Scenario = scenario_named(name)
                result: RunState = run_to(
                    s.schedule, s.initial_state, mode, len(s.schedule)
                )
                self.assertEqual(expected, result.explanations)

    def test_validation_of_a_read_that_saw_own_writes(self) -> None:
        """With method 1, a read that returned the transaction's own write is compared without it, as the checksum is;
        the explanation names the read that changed, a==0, not a==1, which returned T2's own y.

        ```text
        T1                          T2
        begin
                                    begin
                                    update y ← (a=1, b=0)
                                    read a==1 → {x, y}
                                    read a==0 → {}
        update z ← (a=0, b=0)
        commit
                                    commit -> aborted
        ```

        Would fail if the explanation compared the read with its result including the transaction's own writes, and
        so blamed a read that did not change.
        """
        schedule: Schedule = schedule_of(
            (1, "begin"),
            (2, "begin"),
            (2, DataOperation("update", "y", Row(1, 0))),
            (2, DataOperation("read", a_equals=1)),
            (2, DataOperation("read", a_equals=0)),
            (1, DataOperation("update", "z", Row(0, 0))),
            (1, "commit"),
            (2, "commit"),
        )
        result: RunState = run_to(schedule, INITIAL_X, "method 1", len(schedule))
        self.assertEqual(
            {
                7: "validation: read a==0 now returns {z: (a=0, b=0)}, but in the snapshot of T2's begin it returns {}"
            },
            result.explanations,
        )

    def test_validation_skips_writes_unchanged_reads_and_unchanged_objects(
        self,
    ) -> None:
        """The explanation of a failed validation passes over the transaction's own writes, its reads whose result
        did not change (method 1) and the objects that a transaction committed meanwhile without changing them
        (method 2); it names read a==1 and y, which T1 changed, not read a==2 or x, which T1 rewrote unchanged.

        Initially x = (a=1, b=0) and y = (a=1, b=1):

        ```text
        T1                          T2
        begin
                                    begin
                                    update z ← (a=0, b=0)
                                    read a==2 → {}
                                    read a==1 → {x, y}
        update x ← (a=1, b=0)
        update y ← (a=1, b=2)
        commit
                                    commit -> aborted
        ```

        Would fail if the explanation stopped at T2's update of z, at read a==2, whose result is the same at the
        commit, or at x, whose committed version did not change, instead of going on to the read and the object
        that made the validation fail.
        """
        initial_state: tuple[StoredObject, ...] = (
            StoredObject("x", Row(1, 0)),
            StoredObject("y", Row(1, 1)),
        )
        schedule: Schedule = schedule_of(
            (1, "begin"),
            (2, "begin"),
            (2, DataOperation("update", "z", Row(0, 0))),
            (2, DataOperation("read", a_equals=2)),
            (2, DataOperation("read", a_equals=1)),
            (1, DataOperation("update", "x", Row(1, 0))),
            (1, DataOperation("update", "y", Row(1, 2))),
            (1, "commit"),
            (2, "commit"),
        )
        for mode, expected in (
            (
                "method 1",
                "validation: read a==1 now returns {x: (a=1, b=0), y: (a=1, b=2)}, but in the snapshot of T2's begin "
                "it returns {x: (a=1, b=0), y: (a=1, b=1)}",
            ),
            (
                "method 2",
                "validation: T1 changed y, which read a==1 returns in the snapshot of T2's begin",
            ),
        ):
            with self.subTest(mode=mode):
                result: RunState = run_to(schedule, initial_state, mode, len(schedule))
                self.assertEqual({8: expected}, result.explanations)

    def test_marked_read_is_explained(self) -> None:
        """Without validation, the read the verdict marks gets the verdict's explanation: in the phantom insert, T1's
        read (position 1) and what it would return in the order of the serialization points T2|T1.

        ```text
        T1                          T2
        begin
        read a==1 → {x}
                                    begin
                                    update y ← (a=1, b=0)
                                    commit
        update z ← (a=0, b=1)
        commit
        ```

        Would fail if run_to did not copy the marked read's explanation into the explanations, or put it at
        another position.
        """
        s: Scenario = scenario_named("phantom insert")
        result: RunState = run_to(
            s.schedule, s.initial_state, "no validation", len(s.schedule)
        )
        self.assertEqual(
            {
                1: "in the order T2|T1 this read would return {x: (a=1, b=0), y: (a=1, b=0)}"
            },
            result.explanations,
        )

    def test_skipped_operation_before_the_marked_read(self) -> None:
        """Without validation, a skipped operation before the read that differs still counts as a position: T2's read
        a==1 is marked at its position 7 in the schedule, and both the abort of T3's update and the read are
        explained at their positions.

        ```text
        T1                          T2                          T3
        begin
                                    begin
                                                                begin
        read a==1 → {x}
        update y ← (a=1, b=0)
                                                                update y ← (a=1, b=5) -> aborted (T1 writes y)
                                                                commit -> skipped
                                    read a==1 → {x}
                                    delete x
        commit
                                    commit
        ```

        Would fail if the marked position counted only the operations that ran, so that the mark and the
        explanation stood one row too early, or if the aborted T3 were replayed in the verdict.
        """
        schedule: Schedule = schedule_of(
            (1, "begin"),
            (2, "begin"),
            (3, "begin"),
            (1, DataOperation("read", a_equals=1)),
            (1, DataOperation("update", "y", Row(1, 0))),
            (3, DataOperation("update", "y", Row(1, 5))),
            (3, "commit"),
            (2, DataOperation("read", a_equals=1)),
            (2, DataOperation("delete", "x")),
            (1, "commit"),
            (2, "commit"),
        )
        result: RunState = run_to(schedule, INITIAL_X, "no validation", len(schedule))
        self.assertEqual("(commit: skipped)", result.log[6].text)
        self.assertEqual(
            Verdict(
                "not serializable",
                "Not serializable: no serial order gives the same read results and final state.",
                (
                    "Order T1|T2: T2's read a==1 would return {x: (a=1, b=0), y: (a=1, b=0)}, but returned "
                    "{x: (a=1, b=0)}.",
                    "Order T2|T1: T1's read a==1 would return {}, but returned {x: (a=1, b=0)}.",
                ),
                7,
                "in the order T1|T2 this read would return {x: (a=1, b=0), y: (a=1, b=0)}",
            ),
            result.verdict,
        )
        self.assertEqual(
            {
                5: "T1 is writing y and has not committed yet",
                7: "in the order T1|T2 this read would return {x: (a=1, b=0), y: (a=1, b=0)}",
            },
            result.explanations,
        )

    def test_transaction_that_aborts_itself_is_not_explained(self) -> None:
        """Without validation, a transaction T3 that aborts on its own next to write skew changes neither the verdict
        nor its lines, only the marked position, and its abort gets no explanation, as the store did not abort it.

        ```text
        T1                          T2                          T3
        begin
                                    begin
                                                                begin
                                                                update z ← (a=0, b=0)
                                                                abort
        read a==1 → {x}
        read a==2 → {y}
                                    read a==1 → {x}
                                    read a==2 → {y}
        update x ← (a=1, b=100)
                                    update y ← (a=2, b=200)
        commit
                                    commit
        ```

        Would fail if an abort of the transaction itself were explained like one by the store, or if the aborted
        T3 were replayed in the verdict.
        """
        s: Scenario = scenario_named("write skew")
        schedule: Schedule = (
            s.schedule[:2]
            + schedule_of(
                (3, "begin"), (3, DataOperation("update", "z", Row(0, 0))), (3, "abort")
            )
            + s.schedule[2:]
        )
        with_t_3: RunState = run_to(
            schedule, s.initial_state, "no validation", len(schedule)
        )
        without_t_3: RunState = run_to(
            s.schedule, s.initial_state, "no validation", len(s.schedule)
        )
        self.assertEqual(
            (without_t_3.verdict.kind, without_t_3.verdict.details),
            (with_t_3.verdict.kind, with_t_3.verdict.details),
        )
        self.assertEqual(
            {7: "in the order T1|T2 this read would return {x: (a=1, b=100)}"},
            with_t_3.explanations,
        )

    def test_writer_that_blocks_is_named(self) -> None:
        """T1's update of x fails while T2, which began after T1, holds an uncommitted version of x; the explanation
        names T2.

        ```text
        T1                          T2
        begin
                                    begin
                                    update x ← (a=1, b=2)
        update x ← (a=1, b=1) -> aborted
                                    commit
        ```

        Would fail if the explanation named the transaction that began first instead of the one writing x.
        """
        schedule: Schedule = schedule_of(
            (1, "begin"),
            (2, "begin"),
            (2, DataOperation("update", "x", Row(1, 2))),
            (1, DataOperation("update", "x", Row(1, 1))),
            (2, "commit"),
        )
        result: RunState = run_to(schedule, INITIAL_X, "no validation", len(schedule))
        self.assertEqual(
            {3: "T2 is writing x and has not committed yet"}, result.explanations
        )

    def test_method_2_leaves_out_own_writes(self) -> None:
        """With method 2, T1 wrote x itself before its read a==1, which returned {}; as in the store's check, the read
        is taken without T1's own write: in the snapshot of T1's begin it returns the initial x, and T2 committed a
        new version of x since.

        Initially x = (a=1, b=0):

        ```text
        T1                          T2
        begin
                                    begin
                                    update x ← (a=1, b=1)
                                    commit
        update x ← (a=2, b=0)
        read a==1 → {}
        commit -> aborted
        ```

        Would fail if the explanation took the read with T1's own write, with which it returns x neither in the
        snapshot nor now, or reported that the read returns T2's x now (also true) instead of the snapshot reason,
        which the store's check finds first.
        """
        schedule: Schedule = schedule_of(
            (1, "begin"),
            (2, "begin"),
            (2, DataOperation("update", "x", Row(1, 1))),
            (2, "commit"),
            (1, DataOperation("update", "x", Row(2, 0))),
            (1, DataOperation("read", a_equals=1)),
            (1, "commit"),
        )
        result: RunState = run_to(schedule, INITIAL_X, "method 2", len(schedule))
        self.assertEqual(
            {
                6: "validation: T2 changed x, which read a==1 returns in the snapshot of T1's begin"
            },
            result.explanations,
        )

    def test_method_2_names_the_writer_of_the_committed_version(self) -> None:
        """Two transactions committed x after T1's begin; the explanation names T3, whose version a==1 returns now,
        not T2, whose version it does not return.

        Initially x = (a=0, b=0):

        ```text
        T1                          T2                          T3
        begin
        read a==1 → {}
                                    begin
                                    update x ← (a=2, b=0)
                                    commit
                                                                begin
                                                                update x ← (a=1, b=0)
                                                                commit
        update y ← (a=0, b=0)
        commit -> aborted
        ```

        Would fail if the explanation named the first transaction that wrote x instead of the one whose version is
        committed now.
        """
        schedule: Schedule = schedule_of(
            (1, "begin"),
            (1, DataOperation("read", a_equals=1)),
            (2, "begin"),
            (2, DataOperation("update", "x", Row(2, 0))),
            (2, "commit"),
            (3, "begin"),
            (3, DataOperation("update", "x", Row(1, 0))),
            (3, "commit"),
            (1, DataOperation("update", "y", Row(0, 0))),
            (1, "commit"),
        )
        result: RunState = run_to(
            schedule, (StoredObject("x", Row(0, 0)),), "method 2", len(schedule)
        )
        self.assertEqual(
            {9: "validation: T3 changed x, which read a==1 returns now"},
            result.explanations,
        )

    def test_snapshot_isolation_names_the_committing_writer(self) -> None:
        """Under snapshot isolation, T2's update of x in the lost update fails, as T1 changed x and committed after
        T2 began; the explanation names T1 and stands at T2's update.

        ```text
        T1                          T2
        begin
                                    begin
        read all → {x}
                                    read all → {x}
        update x ← (a=1, b=1)
        commit
                                    update x ← (a=1, b=2) -> aborted
                                    (commit: skipped)
        ```

        Would fail if the explanation of a write abort assumed another transaction's uncommitted version (there is
        none here), named the wrong transaction, or stood at another operation.
        """
        s: Scenario = scenario_named("lost update")
        result: RunState = run_to(
            s.schedule, s.initial_state, "snapshot isolation", len(s.schedule)
        )
        self.assertEqual(
            {6: "snapshot isolation: T1 changed x and committed after T2 began"},
            result.explanations,
        )

    def test_snapshot_isolation_names_the_writer_of_the_object(self) -> None:
        """Under snapshot isolation, T2 and then T3 commit after T1's begin, T2 a change of x and T3 a change of y;
        T1's update of x fails, and the explanation names T2, which changed x, not T3, which committed last.

        ```text
        T1                          T2                          T3
        begin
                                    begin
                                                                begin
                                    update x ← (a=1, b=2)
                                    commit
                                                                update y ← (a=1, b=3)
                                                                commit
        update x ← (a=1, b=1) -> aborted
        ```

        Would fail if the explanation named the transaction that committed last instead of the one whose version of
        x is committed now.
        """
        schedule: Schedule = schedule_of(
            (1, "begin"),
            (2, "begin"),
            (3, "begin"),
            (2, DataOperation("update", "x", Row(1, 2))),
            (2, "commit"),
            (3, DataOperation("update", "y", Row(1, 3))),
            (3, "commit"),
            (1, DataOperation("update", "x", Row(1, 1))),
        )
        result: RunState = run_to(
            schedule, INITIAL_X, "snapshot isolation", len(schedule)
        )
        self.assertEqual(("aborted", "committed", "committed"), statuses(result))
        self.assertEqual(
            {7: "snapshot isolation: T2 changed x and committed after T1 began"},
            result.explanations,
        )

    def test_snapshot_isolation_with_a_delete(self) -> None:
        """Under snapshot isolation, a delete is stopped like an update, and a delete marker counts as a change:
        T1's delete of x fails after T2 updated x and committed, and T1's update of x fails after T2 deleted x and
        committed; both explanations name T2.

        ```text
        T1                          T2
        begin
                                    begin
                                    update x ← (a=1, b=2)   (or: delete x)
                                    commit
        delete x -> aborted         (or: update x ← (a=1, b=1) -> aborted)
        ```

        Would fail if the explanation of a write abort handled only updates, or could not find the writer of a
        newest committed version that is a delete marker.
        """
        cases: dict[str, tuple[DataOperation, DataOperation]] = {
            "T1 deletes": (
                DataOperation("update", "x", Row(1, 2)),
                DataOperation("delete", "x"),
            ),
            "T2 deletes": (
                DataOperation("delete", "x"),
                DataOperation("update", "x", Row(1, 1)),
            ),
        }
        for case, (write_of_t_2, write_of_t_1) in cases.items():
            with self.subTest(case=case):
                schedule: Schedule = schedule_of(
                    (1, "begin"),
                    (2, "begin"),
                    (2, write_of_t_2),
                    (2, "commit"),
                    (1, write_of_t_1),
                )
                result: RunState = run_to(
                    schedule, INITIAL_X, "snapshot isolation", len(schedule)
                )
                self.assertEqual(("aborted", "committed"), statuses(result))
                self.assertEqual(
                    {
                        4: "snapshot isolation: T2 changed x and committed after T1 began"
                    },
                    result.explanations,
                )

    def test_uncommitted_writer_is_checked_before_snapshot_isolation(self) -> None:
        """Under snapshot isolation, T2 changed x and committed after T1's begin, and T3 holds an uncommitted
        version of x when T1 updates x; both reasons apply, and the explanation gives T3's uncommitted version, as
        the store checks for it first.

        ```text
        T1                          T2                          T3
        begin
                                    begin
                                    update x ← (a=1, b=2)
                                    commit
                                                                begin
                                                                update x ← (a=1, b=3)
        update x ← (a=1, b=1) -> aborted
        ```

        Would fail if the explanation checked the two reasons in another order than the store, and so gave the
        commit of T2 as the reason.
        """
        schedule: Schedule = schedule_of(
            (1, "begin"),
            (2, "begin"),
            (2, DataOperation("update", "x", Row(1, 2))),
            (2, "commit"),
            (3, "begin"),
            (3, DataOperation("update", "x", Row(1, 3))),
            (1, DataOperation("update", "x", Row(1, 1))),
        )
        result: RunState = run_to(
            schedule, INITIAL_X, "snapshot isolation", len(schedule)
        )
        self.assertEqual(("aborted", "committed", "running"), statuses(result))
        self.assertEqual(
            {6: "T3 is writing x and has not committed yet"}, result.explanations
        )

    def test_commit_that_succeeds_raises(self) -> None:
        """Asked to explain a commit that the store does not abort, abort_explanation raises an AssertionError.

        The serial scenario, with method 1:

        ```text
        T1                          T2
        begin
        read a==1 → {x}
        update y ← (a=1, b=0)
        commit                                        <- position 3 (counted from 0): the commit to explain
                                    begin
                                    read a==1 → {x, y}
                                    delete x
                                    commit
        ```

        Would fail if the explanation invented a reason for a commit that passed the validation.
        """
        s: Scenario = scenario_named("serial")
        # position 3 is T1's commit, which succeeds:
        with self.assertRaisesRegex(AssertionError, "no reason found"):
            abort_explanation(s.schedule, s.initial_state, "method 1", 3)

    def test_write_that_succeeds_raises(self) -> None:
        """Asked to explain a write that the store does not abort, abort_explanation raises an AssertionError, also
        if snapshot isolation would abort the write.

        The scenario "blind write", with method 2:

        ```text
        T1                          T2
        begin
                                    begin
                                    update x ← (a=1, b=2)
                                    commit
        update x ← (a=1, b=1)                         <- position 4 (counted from 0): the write to explain
        commit
        ```

        Would fail if the explanation gave the snapshot isolation reason (T2 changed x and committed after T1 began)
        in a mode other than snapshot isolation, where the store does not abort for it.
        """
        s: Scenario = scenario_named("blind write")
        # position 4 is T1's update of x, which succeeds:
        with self.assertRaisesRegex(AssertionError, "no reason found"):
            abort_explanation(s.schedule, s.initial_state, "method 2", 4)

    def test_insert_that_succeeds_raises(self) -> None:
        """Asked to explain an insert of a new key that the store does not abort, abort_explanation raises an
        AssertionError, as for any other write that the store does not abort.

        The scenario "serial", whose T1 inserts y, which is not in the store yet:

        ```text
        T1                          T2
        begin
        read a==1 → {x}
        update y ← (a=1, b=0)                         <- position 2 (counted from 0): the insert to explain
        commit
                                    begin
                                    read a==1 → {x, y}
                                    delete x
                                    commit
        ```

        Would fail if the explanation looked up the store's entry of y, which does not exist before the insert, and
        raised a KeyError instead. Checked with method 1 and with snapshot isolation.
        """
        s: Scenario = scenario_named("serial")
        for mode in ["method 1", "snapshot isolation"]:
            with self.subTest(mode=mode):
                # position 2 is T1's insert of y, which succeeds:
                with self.assertRaisesRegex(AssertionError, "no reason found"):
                    abort_explanation(s.schedule, s.initial_state, mode, 2)

    def test_nothing_to_explain(self) -> None:
        """The serial scenario has no explanations, before and after its end.

        With method 2, the first run stops after operation 3, the second one runs to the end:

        ```text
        T1                          T2
        begin
        read a==1 → {x}
        update y ← (a=1, b=0)                         <- operation 3 (counted from 1): the first run stops here
        commit
                                    begin
                                    read a==1 → {x, y}
                                    delete x
                                    commit
        ```

        Would fail if an operation that went fine got an explanation.
        """
        s: Scenario = scenario_named("serial")
        for count in (3, len(s.schedule)):
            with self.subTest(operations=count):
                self.assertEqual(
                    {},
                    run_to(s.schedule, s.initial_state, "method 2", count).explanations,
                )


class RunToTest(unittest.TestCase):
    """Running the first operations of a schedule."""

    def test_empty_schedule(self) -> None:
        """An empty schedule shows the initial objects, no transactions and the verdict "pending".

        Would fail if the empty schedule got a final verdict before a transaction was added.
        """
        empty: RunState = run_to((), INITIAL_X, "method 2", 0)
        self.assertEqual("pending", empty.verdict.kind)
        self.assertEqual(
            (ObjectState("x", (Version(0, Row(1, 0), "initial"),)),), empty.objects
        )
        self.assertEqual((), empty.transactions)

    def test_transaction_that_aborts_on_its_own(self) -> None:
        """A transaction that aborts on its own leaves no version behind; with nothing committed, the verdict says
        so.

        ```text
        T1
        begin
        update x ← (a=2, b=0)
        abort
        ```

        Would fail if the abort left the work-in-progress version in the store, or if a run in which every
        transaction aborted were judged as serializable or kept pending.
        """
        schedule: Schedule = schedule_of(
            (1, "begin"), (1, DataOperation("update", "x", Row(2, 0))), (1, "abort")
        )
        after_update: RunState = run_to(schedule, INITIAL_X, "method 2", 2)
        self.assertEqual(
            ObjectState(
                "x",
                (Version(0, Row(1, 0), "initial"),),
                WorkInProgress("T1", Row(2, 0)),
            ),
            after_update.objects[0],
        )
        at_end: RunState = run_to(schedule, INITIAL_X, "method 2", len(schedule))
        self.assertEqual(
            (ObjectState("x", (Version(0, Row(1, 0), "initial"),)),), at_end.objects
        )
        self.assertEqual(
            Verdict("nothing committed", "Nothing committed."), at_end.verdict
        )

    def test_verdict_is_final_once_every_transaction_has_ended(self) -> None:
        """The verdict is final as soon as every transaction has ended, even if skipped operations follow.

        ```text
        T1                          T2
        begin
                                    begin
        update x ← (a=2, b=0)
                                    update x ← (a=3, b=0) -> aborted
        commit                                        <- operation 5 (counted from 1): every transaction has ended
                                    commit -> skipped
        ```

        Would fail if the verdict waited for the last operation of the schedule instead of the end of the last
        transaction, or if it were given while T1 is still running after operation 4.
        """
        schedule: Schedule = schedule_of(
            (1, "begin"),
            (2, "begin"),
            (1, DataOperation("update", "x", Row(2, 0))),
            (2, DataOperation("update", "x", Row(3, 0))),
            (1, "commit"),
            (2, "commit"),
        )
        after_4: RunState = run_to(schedule, INITIAL_X, "method 2", 4)
        after_5: RunState = run_to(schedule, INITIAL_X, "method 2", 5)
        at_end: RunState = run_to(schedule, INITIAL_X, "method 2", len(schedule))
        self.assertEqual("pending", after_4.verdict.kind)
        self.assertEqual(
            Verdict(
                "serializable",
                "Serializable: same read results and final state as the serial order T1.",
            ),
            after_5.verdict,
        )
        self.assertEqual(at_end.verdict, after_5.verdict)

    def test_object_states_of_concurrent_delete(self) -> None:
        """After T2's delete, while T2 is still running, x has a work-in-progress delete marker; after T2's commit,
        a committed delete marker.

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
                                    delete x          <- operation 4 (counted from 1)
                                    commit
        update z ← (a=0, b=1)
        commit -> aborted
        ```

        Would fail if a work-in-progress delete were shown as an update or without its owner, or if a committed
        delete were not shown as a version of its own.
        """
        s: Scenario = scenario_named("concurrent delete")
        at_delete: RunState = run_to(s.schedule, s.initial_state, "method 2", 4)
        self.assertEqual(
            ObjectState(
                "x", (Version(0, Row(1, 0), "initial"),), WorkInProgress("T2", None)
            ),
            at_delete.objects[0],
        )
        at_end: RunState = run_to(
            s.schedule, s.initial_state, "method 2", len(s.schedule)
        )
        self.assertEqual(
            ObjectState(
                "x", (Version(0, Row(1, 0), "initial"), Version(3, None, "T2"))
            ),
            at_end.objects[0],
        )


class ChecksumTest(unittest.TestCase):
    """Validation method 1's checksums of the reads."""

    def test_checksums_of_write_skew(self) -> None:
        """After T1's commit, T2's read a==1 would return another result, so its checksum now differs.

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
                                    read a==1 → {x}
        update y ← (a=1, b=0)
                                    delete x
        commit                                        <- operation 7 (counted from 1)
                                    commit -> aborted
        ```

        Would fail if the checksum now were computed on another state than the one the commit validates against,
        if a committed transaction still showed a checksum now, if an aborted one kept its checksums, or if a mode
        without checksums showed them.
        """
        s: Scenario = scenario_named("write skew via phantom (insert and delete)")
        after_7: RunState = run_to(s.schedule, s.initial_state, "method 1", 7)
        t_1, t_2 = after_7.transactions
        self.assertEqual("a==1", t_1.checksums[0].clause)
        self.assertIsNone(t_1.checksums[0].now)
        self.assertEqual(t_1.checksums[0].at_read, t_2.checksums[0].at_read)
        self.assertNotEqual(t_2.checksums[0].at_read, t_2.checksums[0].now)
        at_end: RunState = run_to(s.schedule, s.initial_state, "method 1", 8)
        self.assertEqual((), at_end.transactions[1].checksums)
        after_6: RunState = run_to(s.schedule, s.initial_state, "method 2", 6)
        self.assertEqual((), after_6.transactions[0].checksums)


class ErrorTest(unittest.TestCase):
    """A run that cannot continue."""

    def test_delete_of_key_whose_update_was_skipped(self) -> None:
        """A delete of a key whose only update was skipped stops the run with the store's KeyError as its verdict.

        ```text
        T1                          T2
        begin
                                    begin
        update x ← (a=2, b=0)
                                    update x ← (a=3, b=0) -> aborted
                                    update y ← (a=1, b=0) -> skipped
                                    commit -> skipped
        delete y -> error
        commit -> not run
        ```

        Would fail if the store's KeyError escaped run_to, the error did not name y, the failed delete were not the
        last line of the table, the verdict were judged on the unfinished run, or the error dropped the explanation
        of T2's aborted update.
        """
        schedule: Schedule = schedule_of(
            (1, "begin"),
            (2, "begin"),
            (1, DataOperation("update", "x", Row(2, 0))),
            (2, DataOperation("update", "x", Row(3, 0))),
            (2, DataOperation("update", "y", Row(1, 0))),
            (2, "commit"),
            (1, DataOperation("delete", "y")),
            (1, "commit"),
        )
        for mode in MODES:
            with self.subTest(mode=mode):
                result: RunState = run_to(schedule, INITIAL_X, mode, len(schedule))
                self.assertEqual(7, len(result.log))
                self.assertEqual("delete y: raised KeyError: 'y'", result.log[-1].text)
                self.assertEqual(
                    Verdict(
                        "error", "The run stopped: delete y: raised KeyError: 'y'."
                    ),
                    result.verdict,
                )
                # the abort of T2's update is still explained; the error has no marked read:
                self.assertEqual(
                    {3: "T1 is writing x and has not committed yet"},
                    result.explanations,
                )


class TransactionStateTest(unittest.TestCase):
    """What each transaction did so far and what it sees, in write skew via phantom (insert and delete) with
    method 2.

    ```text
    T1                          T2
    begin
                                begin
    read a==1 → {x}
                                read a==1 → {x}
    update y ← (a=1, b=0)
                                delete x
    commit
                                commit -> aborted
    ```
    """

    def test_transaction_not_begun_yet(self) -> None:
        """After T1's begin, T2 has not begun: it has no id and shows nothing.

        ```text
        T1                          T2
        begin                                         <- operation 1 (counted from 1): the run stops here
                                    begin
        read a==1 → {x}
                                    read a==1 → {x}
        update y ← (a=1, b=0)
                                    delete x
        commit
                                    commit -> aborted
        ```

        Would fail if a transaction that has not begun were left out, or shown with an id or a snapshot.
        """
        s: Scenario = scenario_named("write skew via phantom (insert and delete)")
        result: RunState = run_to(s.schedule, s.initial_state, "method 2", 1)
        self.assertEqual(
            TransactionState("T2", None, "not begun", (), (), ()),
            result.transactions[1],
        )

    def test_work_in_progress_insert_and_running_writer(self) -> None:
        """While T1's insert of y runs (after operation 5), y has no committed version, and T1 sees y and lists its
        read and write.

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
                                    read a==1 → {x}
        update y ← (a=1, b=0)                         <- operation 5 (counted from 1): the run stops here
                                    delete x
        commit
                                    commit -> aborted
        ```

        Would fail if an object without committed version were left out, if the work-in-progress version did not
        name its writer, or if a running transaction did not see its own write.
        """
        s: Scenario = scenario_named("write skew via phantom (insert and delete)")
        result: RunState = run_to(s.schedule, s.initial_state, "method 2", 5)
        self.assertEqual(
            ObjectState("y", (), WorkInProgress("T1", Row(1, 0))), result.objects[1]
        )
        self.assertEqual(
            TransactionState(
                "T1",
                1,
                "running",
                (StoredObject("x", Row(1, 0)), StoredObject("y", Row(1, 0))),
                ("a==1",),
                ("y",),
            ),
            result.transactions[0],
        )

    def test_aborted_transaction_keeps_its_read_and_write(self) -> None:
        """T2 aborts at its commit and still lists what it read and wrote, but sees nothing any more.

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
                                    read a==1 → {x}
        update y ← (a=1, b=0)
                                    delete x
        commit
                                    commit -> aborted
        ```

        Would fail if the read and the write that made T2 abort disappeared with the abort (the store forgets an
        aborted transaction).
        """
        s: Scenario = scenario_named("write skew via phantom (insert and delete)")
        result: RunState = run_to(
            s.schedule, s.initial_state, "method 2", len(s.schedule)
        )
        self.assertEqual(
            TransactionState("T2", 2, "aborted", (), ("a==1",), ("x",)),
            result.transactions[1],
        )


if __name__ == "__main__":
    unittest.main()
