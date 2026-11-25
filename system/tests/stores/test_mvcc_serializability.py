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
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring
"""Exhaustive check that the MVCC store only commits serializable schedules of two or three transactions."""

from __future__ import annotations

import functools
import itertools
import os
import unittest
from collections.abc import Callable, Iterator
from typing import cast

from system.playground.mvcc_playground import StoreWithoutValidation
from system.playground.schedules import (
    DataOperation,
    Difference,
    ExecutedDataOperation,
    Row,
    Schedule,
    ScheduleCheck,
    ScheduleRun,
    ScheduleSpace,
    ScheduledOperation,
    StoredObject,
    Transaction,
    TransactionRecord,
    all_transactions,
    check_all_schedules,
    first_difference,
    number_of_schedules,
    overlapping_committed_writers,
    run_schedule,
    schedules,
    serializability_violation,
    two_commits_during_writer,
)
from system.stores.MVCC import TransactionalKeyValueStore

# the initial state: x is selected by a == 1, z is not, y does not exist yet:
INITIAL_STATE: tuple[StoredObject, ...] = (
    StoredObject("x", Row(1, 0)),
    StoredObject("z", Row(0, 0)),
)

# one representative per case of the validation (see TransactionalKeyValueStore._validate_transaction): whether
# a write changes what a read returns depends only on whether the object is selected by a == 1 before and after
# the write and on whether its content changes.
# There is no "delete y": deleting an object that was never stored raises KeyError. The nine data operations:
DATA_OPERATIONS: tuple[DataOperation, ...] = (
    DataOperation("read", a_equals=1),
    DataOperation("read"),
    # x stays selected by a == 1, content changes:
    DataOperation("update", "x", Row(1, 1)),
    # x stays selected by a == 1, content unchanged:
    DataOperation("update", "x", Row(1, 0)),
    # x drops out of a == 1:
    DataOperation("update", "x", Row(0, 0)),
    # x drops out of a == 1 by deletion:
    DataOperation("delete", "x"),
    # y is inserted into a == 1:
    DataOperation("update", "y", Row(1, 0)),
    # y is inserted outside of a == 1:
    DataOperation("update", "y", Row(0, 0)),
    # z moves into a == 1:
    DataOperation("update", "z", Row(1, 0)),
)


# all schedules of two transactions with one or two of the nine data operations each, run in the regular test job:
TWO_TRANSACTIONS: ScheduleSpace = ScheduleSpace(
    INITIAL_STATE, DATA_OPERATIONS, frozenset(itertools.product((1, 2), repeat=2))
)

# all schedules of three transactions, at most one of them with two data operations, the others with one; run
# nightly only (see NightlySerializabilityTest). To keep the run short, only six of the nine data operations are
# used. The other three are tested with two transactions only (TWO_TRANSACTIONS, TWO_TRANSACTIONS_WITH_ABORT):
# changing the content of x while it stays selected, rewriting x unchanged, and inserting y outside of a == 1:
THREE_TRANSACTIONS: ScheduleSpace = ScheduleSpace(
    INITIAL_STATE,
    (
        DataOperation("read", a_equals=1),
        DataOperation("read"),
        # x drops out of a == 1:
        DataOperation("update", "x", Row(0, 0)),
        # x drops out of a == 1 by deletion:
        DataOperation("delete", "x"),
        # y is inserted into a == 1:
        DataOperation("update", "y", Row(1, 0)),
        # z moves into a == 1:
        DataOperation("update", "z", Row(1, 0)),
    ),
    frozenset({(1, 1, 1), (2, 1, 1), (1, 2, 1), (1, 1, 2)}),
)

# all schedules of three transactions, two of them with two data operations and the third with one; run nightly
# only. Two transactions can thus both read and write, e.g. a write skew next to a third transaction. Each of the
# three writes changes what read a == 1 returns. "read all" and "delete x" are left out, as THREE_TRANSACTIONS
# covers them: with all six data operations the run would be about eight times longer.
THREE_TRANSACTIONS_TWO_READ_WRITE: ScheduleSpace = ScheduleSpace(
    INITIAL_STATE,
    (
        DataOperation("read", a_equals=1),
        # x drops out of a == 1:
        DataOperation("update", "x", Row(0, 0)),
        # y is inserted into a == 1:
        DataOperation("update", "y", Row(1, 0)),
        # z moves into a == 1:
        DataOperation("update", "z", Row(1, 0)),
    ),
    frozenset({(2, 2, 1), (2, 1, 2), (1, 2, 2)}),
)

# all schedules of TWO_TRANSACTIONS, but every transaction either commits or aborts on its own; run nightly only.
# The voluntary abort can come after writes, which the store has to undo:
TWO_TRANSACTIONS_WITH_ABORT: ScheduleSpace = ScheduleSpace(
    INITIAL_STATE,
    DATA_OPERATIONS,
    TWO_TRANSACTIONS.data_operation_counts,
    endings=("commit", "abort"),
)

# all schedules of two transactions with one to three data operations each, at most one of them with three, over
# the six data operations of THREE_TRANSACTIONS; run nightly only. A longer transaction can e.g. read, write and
# read again, so it sees its own writes and is validated against several read predicates. Two transactions with
# three data operations each would make the run about six times longer:
TWO_LONGER_TRANSACTIONS: ScheduleSpace = ScheduleSpace(
    INITIAL_STATE,
    THREE_TRANSACTIONS.data_operations,
    frozenset(itertools.product((1, 2, 3), repeat=2)) - {(3, 3)},
)


class StoreThatKeepsVersionsOfAbortedTransactions(TransactionalKeyValueStore):
    """A store whose abort leaves the work-in-progress versions of the aborted transaction in place."""

    def abort_transaction(self, TA_id: int) -> None:
        """See :meth:`TransactionalKeyValueStore.abort_transaction`.

        Only removes the transaction from the transaction dictionary.
        """
        del self.TD[TA_id]


class StoreWithoutCommitTimestamp(TransactionalKeyValueStore):
    """A store that commits transactions but leaves their commit timestamp unset."""

    def commit_transaction(self, TA_id: int) -> None:
        """See :meth:`TransactionalKeyValueStore.commit_transaction`.

        Afterwards resets the commit timestamp of the transaction to None.
        """
        super().commit_transaction(TA_id)
        self.TD[TA_id].committed_timestamp = None


class StoreThatCrashesOnDelete(TransactionalKeyValueStore):
    """A store whose delete always raises an exception other than TransactionAbortedException."""

    def delete_object(self, object_id: str, TA_id: int | None) -> None:
        """See :meth:`TransactionalKeyValueStore.delete_object`.

        Always raises RuntimeError.
        """
        raise RuntimeError(f"cannot delete {object_id}")


def all_ordered_interleavings(
    transactions: list[Transaction],
) -> Iterator[Schedule]:
    """Yields every interleaving of the transactions whose begins are in index order, by choosing positions.

    Used to check :func:`system.playground.schedules.interleavings` independently: each transaction in turn takes
    any of the positions left.
    """
    total_operations: int = sum(len(transaction) for transaction in transactions)

    def place(index: int, free: tuple[int, ...]) -> Iterator[list[tuple[int, ...]]]:
        """Yields the positions of transactions index, index + 1, ... among the free positions."""
        # all transactions are placed:
        if index == len(transactions):
            yield []
            return
        chosen: tuple[int, ...]
        # transaction index takes any of the free positions, in increasing order (its operations keep their order) ...
        for chosen in itertools.combinations(free, len(transactions[index])):
            rest: tuple[int, ...] = tuple(p for p in free if p not in chosen)
            # ... and the later transactions share the positions left:
            for placement in place(index + 1, rest):
                yield [chosen, *placement]

    for placement in place(0, tuple(range(total_operations))):
        # the begin of each transaction is at the first of its positions; keep only placements in begin order:
        begins: list[int] = [positions[0] for positions in placement]
        if begins != sorted(begins):
            continue
        # put every operation at its position:
        schedule: list[ScheduledOperation | None] = [None] * total_operations
        for index, positions in enumerate(placement):
            for position, operation in zip(positions, transactions[index]):
                schedule[position] = ScheduledOperation(index, operation)
        # every position was filled, as the placement uses all positions:
        assert None not in schedule
        yield cast(Schedule, tuple(schedule))


class ExhaustiveTestCase(unittest.TestCase):
    """Base class of the test classes that run all schedules of a schedule space."""

    def _assert_serializable(
        self,
        store_factory: Callable[[], TransactionalKeyValueStore],
        space: ScheduleSpace,
        expected_schedules: int,
    ) -> ScheduleCheck:
        """Asserts that every schedule commits a serializable history and that the run was not trivial.

        expected_schedules is fixed in the test, so a change of the schedule space is noticed. Returns the check,
        so that a test can assert more of its counters.
        """
        check: ScheduleCheck = check_all_schedules(store_factory, space)
        if check.violation is not None:
            self.fail(check.violation)
        self.assertEqual(expected_schedules, check.schedules_run)
        self.assertEqual(number_of_schedules(space), check.schedules_run)
        # in some schedules two concurrent writers both commit, and in some the validation aborts a transaction
        # (these checks only rule out a store that aborts all concurrent writers or never aborts at validation):
        self.assertGreater(check.overlapping_committed_writers, 0)
        self.assertGreater(check.validation_aborts, 0)
        return check


class SerializabilityTest(ExhaustiveTestCase):
    """Runs all schedules of two transactions on the store and checks the oracle itself."""

    def test_validation_method_1_brute_force(self) -> None:
        """Every schedule committed under validation method 1 (checksums of read results) is serializable."""
        self._assert_serializable(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=True),
            TWO_TRANSACTIONS,
            255_960,
        )

    def test_validation_method_2_write_sets(self) -> None:
        """Every schedule committed under validation method 2 (write sets) is serializable."""
        self._assert_serializable(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=False),
            TWO_TRANSACTIONS,
            255_960,
        )

    def test_store_without_validation_is_caught(self) -> None:
        """A store that skips validation commits a schedule whose reads differ from the serial order."""
        check: ScheduleCheck = check_all_schedules(
            StoreWithoutValidation, TWO_TRANSACTIONS
        )
        assert check.violation is not None
        self.assertIn("in the serial order it returns", check.violation)

    def test_crash_of_store_is_reported_with_schedule(self) -> None:
        """An exception other than TransactionAbortedException is reported together with the schedule table."""
        check: ScheduleCheck = check_all_schedules(
            StoreThatCrashesOnDelete, TWO_TRANSACTIONS
        )
        assert check.violation is not None
        self.assertIn("delete x: raised RuntimeError: cannot delete x", check.violation)
        self.assertIn("serial order:", check.violation)

    def test_leftover_versions_are_reported(self) -> None:
        """A work-in-progress version left after all transactions ended is reported with the schedule table."""
        check: ScheduleCheck = check_all_schedules(
            StoreThatKeepsVersionsOfAbortedTransactions, TWO_TRANSACTIONS
        )
        assert check.violation is not None
        self.assertIn("work-in-progress versions left for", check.violation)
        self.assertIn(": aborted", check.violation)
        self.assertIn("serial order:", check.violation)

    def test_commit_without_timestamp_is_reported(self) -> None:
        """A commit that leaves the commit timestamp unset is reported with the schedule table."""
        check: ScheduleCheck = check_all_schedules(
            StoreWithoutCommitTimestamp, TWO_TRANSACTIONS
        )
        assert check.violation is not None
        self.assertIn(
            "commit: raised RuntimeError: commit left committed_timestamp None",
            check.violation,
        )
        self.assertIn("serial order:", check.violation)

    def test_voluntary_abort_leaves_no_trace(self) -> None:
        """Transactions that abort on their own, also after writing, leave every schedule serializable.

        A small space with two data operations runs in the regular test job; TWO_TRANSACTIONS_WITH_ABORT runs
        nightly.
        """
        space: ScheduleSpace = ScheduleSpace(
            INITIAL_STATE,
            (
                DataOperation("read", a_equals=1),
                DataOperation("update", "y", Row(1, 0)),
            ),
            TWO_TRANSACTIONS.data_operation_counts,
            endings=("commit", "abort"),
        )
        for use_brute_force_validation in (True, False):
            with self.subTest(use_brute_force_validation=use_brute_force_validation):
                check: ScheduleCheck = check_all_schedules(
                    functools.partial(
                        TransactionalKeyValueStore,
                        use_brute_force_validation=use_brute_force_validation,
                    ),
                    space,
                )
                if check.violation is not None:
                    self.fail(check.violation)
                self.assertEqual(number_of_schedules(space), check.schedules_run)

    def test_number_of_schedules(self) -> None:
        """The enumeration yields exactly the intended schedules.

        Their number matches the closed form, all of them are different, and each one is an interleaving of two
        transactions in which the first one begins first.
        """
        space: ScheduleSpace = ScheduleSpace(
            INITIAL_STATE, DATA_OPERATIONS[:2], TWO_TRANSACTIONS.data_operation_counts
        )
        candidates: list[Transaction] = all_transactions(space.data_operations, 2)
        generated: list[Schedule] = list(schedules(space))
        self.assertEqual(number_of_schedules(space), len(generated))
        self.assertEqual(len(generated), len(set(generated)))
        for schedule in generated:
            self.assertEqual(ScheduledOperation(0, "begin"), schedule[0])
            for transaction_index in (0, 1):
                transaction: Transaction = [
                    scheduled.operation
                    for scheduled in schedule
                    if scheduled.transaction_index == transaction_index
                ]
                self.assertIn(transaction, candidates)

    def test_schedules_of_three_transactions(self) -> None:
        """For three transactions, the enumeration yields the interleavings that begin in index order.

        The expected set is built independently of :func:`interleavings`: every interleaving of every choice of
        T1, T2, T3, by choosing the positions of each transaction's operations, filtered to those that begin in index
        order.
        """
        space: ScheduleSpace = ScheduleSpace(
            INITIAL_STATE, DATA_OPERATIONS[:2], THREE_TRANSACTIONS.data_operation_counts
        )
        expected: set[Schedule] = set()
        # the largest number of data operations of a transaction in space:
        max_operations: int = max(max(counts) for counts in space.data_operation_counts)
        transactions: tuple[Transaction, ...]
        for transactions in itertools.product(
            all_transactions(space.data_operations, max_operations), repeat=3
        ):
            # a transaction has two operations (begin, commit) besides its data operations:
            counts: tuple[int, ...] = tuple(
                len(transaction) - 2 for transaction in transactions
            )
            if counts not in space.data_operation_counts:
                continue
            expected.update(all_ordered_interleavings(list(transactions)))
        generated: list[Schedule] = list(schedules(space))
        self.assertEqual(len(generated), len(set(generated)))
        self.assertEqual(expected, set(generated))
        self.assertEqual(number_of_schedules(space), len(generated))

    def test_oracle_rejects_write_skew(self) -> None:
        """The oracle rejects write skew: no serial order explains both reads.

        Each transaction writes into what the other one read: T1 inserts y into a == 1, T2 deletes x.

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
        """
        x: Row = Row(1, 0)
        t_1: TransactionRecord = TransactionRecord(
            name="T1",
            TA_id=1,
            data_operations=[
                ExecutedDataOperation(
                    DataOperation("read", a_equals=1), (StoredObject("x", x),)
                ),
                ExecutedDataOperation(DataOperation("update", "y", Row(1, 0))),
            ],
            committed=True,
            commit_timestamp=3,
        )
        t_2: TransactionRecord = TransactionRecord(
            name="T2",
            TA_id=2,
            data_operations=[
                ExecutedDataOperation(
                    DataOperation("read", a_equals=1), (StoredObject("x", x),)
                ),
                ExecutedDataOperation(DataOperation("delete", "x")),
            ],
            committed=True,
            commit_timestamp=4,
        )
        violation: str | None = serializability_violation(
            {"x": x}, [t_1, t_2], {"y": Row(1, 0)}
        )
        assert violation is not None
        self.assertIn("T2: read a==1", violation)

    def test_oracle_accepts_serial_schedule(self) -> None:
        """The oracle accepts a serial schedule: T2 begins after T1 committed and sees T1's insert.

        ```text
        T1                          T2
        begin
        read a==1 → {x}
        update y ← (a=1, b=0)
        commit
                                    begin
                                    read a==1 → {x, y}
                                    delete x
                                    commit
        ```
        """
        x: Row = Row(1, 0)
        t_1: TransactionRecord = TransactionRecord(
            name="T1",
            TA_id=1,
            data_operations=[
                ExecutedDataOperation(
                    DataOperation("read", a_equals=1), (StoredObject("x", x),)
                ),
                ExecutedDataOperation(DataOperation("update", "y", Row(1, 0))),
            ],
            committed=True,
            commit_timestamp=2,
        )
        t_2: TransactionRecord = TransactionRecord(
            name="T2",
            TA_id=3,
            data_operations=[
                ExecutedDataOperation(
                    DataOperation("read", a_equals=1),
                    (StoredObject("x", x), StoredObject("y", Row(1, 0))),
                ),
                ExecutedDataOperation(DataOperation("delete", "x")),
            ],
            committed=True,
            commit_timestamp=4,
        )
        self.assertIsNone(
            serializability_violation({"x": x}, [t_1, t_2], {"y": Row(1, 0)})
        )

    def test_oracle_places_read_only_transaction_at_its_begin(self) -> None:
        """The oracle places a read-only transaction at its begin.

        So reading the snapshot of its begin is accepted even though a concurrent writer committed before it.

        ```text
        T1                          T2
        begin
                                    begin
                                    update x ← (a=0, b=0)
                                    commit
        read a==1 → {x}
        commit
        ```
        """
        x: Row = Row(1, 0)
        t_1: TransactionRecord = TransactionRecord(
            name="T1",
            TA_id=1,
            data_operations=[
                ExecutedDataOperation(
                    DataOperation("read", a_equals=1), (StoredObject("x", x),)
                )
            ],
            committed=True,
            commit_timestamp=4,
        )
        t_2: TransactionRecord = TransactionRecord(
            name="T2",
            TA_id=2,
            data_operations=[
                ExecutedDataOperation(DataOperation("update", "x", Row(0, 0)))
            ],
            committed=True,
            commit_timestamp=3,
        )
        self.assertIsNone(
            serializability_violation({"x": x}, [t_1, t_2], {"x": Row(0, 0)})
        )

    def test_oracle_rejects_wrong_final_state(self) -> None:
        """The oracle rejects a final state that lacks the update of the only committed transaction: the difference
        names no read and holds the final state of the run as observed and that of the serial replay as serial.

        Would fail if the wrong final state were accepted, the two final states were swapped, or a read were named
        although every read matches.
        """
        x: Row = Row(1, 0)
        t_1: TransactionRecord = TransactionRecord(
            name="T1",
            TA_id=1,
            data_operations=[
                ExecutedDataOperation(DataOperation("update", "x", Row(0, 0)))
            ],
            committed=True,
            commit_timestamp=2,
        )
        self.assertEqual(
            Difference(
                transaction=None,
                read=None,
                position=None,
                observed=(StoredObject("x", x),),
                serial=(StoredObject("x", Row(0, 0)),),
            ),
            first_difference({"x": x}, [t_1], {"x": x}),
        )
        self.assertEqual(
            "final state is {x: (a=1, b=0)}, in the serial order it is {x: (a=0, b=0)}",
            serializability_violation({"x": x}, [t_1], {"x": x}),
        )


class OracleThreeTransactionsTest(unittest.TestCase):
    """Checks the oracle and the schedule runs with three transactions in the regular test job."""

    def test_oracle_rejects_inconsistent_read_of_third_transaction(self) -> None:
        """Only T3's read differs from the serial order T1, T3, T2, so the violation names T3.

        The records are made up to feed the oracle. T3's read is one the store must not produce: T3 begins after
        T1's commit, so it has to see y.

        ```text
        T1                     T2                          T3
        begin
        update y ← (a=1, b=0)
        commit
                               begin
                                                           begin
                               read all → {x, y, z}
                               update x ← (a=0, b=0)
                                                           read all → {x, z}
                                                           commit
                               commit
        ```

        Would fail if the violation named another transaction or read, or swapped what the read returned and what
        it returns in the serial order.
        """
        x: Row = Row(1, 0)
        y: Row = Row(1, 0)
        z: Row = Row(0, 0)
        t_1: TransactionRecord = TransactionRecord(
            name="T1",
            TA_id=1,
            data_operations=[ExecutedDataOperation(DataOperation("update", "y", y))],
            committed=True,
            commit_timestamp=2,
        )
        t_2: TransactionRecord = TransactionRecord(
            name="T2",
            TA_id=3,
            data_operations=[
                ExecutedDataOperation(
                    DataOperation("read"),
                    (StoredObject("x", x), StoredObject("y", y), StoredObject("z", z)),
                ),
                ExecutedDataOperation(DataOperation("update", "x", Row(0, 0))),
            ],
            committed=True,
            commit_timestamp=6,
        )
        # T3 is read-only and placed at its begin (4), after T1's commit: it should have seen y:
        t_3: TransactionRecord = TransactionRecord(
            name="T3",
            TA_id=4,
            data_operations=[
                ExecutedDataOperation(
                    DataOperation("read"), (StoredObject("x", x), StoredObject("z", z))
                )
            ],
            committed=True,
            commit_timestamp=5,
        )
        violation: str | None = serializability_violation(
            {"x": x, "z": z}, [t_1, t_2, t_3], {"x": Row(0, 0), "y": y, "z": z}
        )
        self.assertEqual(
            "T3: read all returned {x: (a=1, b=0), z: (a=0, b=0)}, in the serial order it returns "
            "{x: (a=1, b=0), y: (a=1, b=0), z: (a=0, b=0)}",
            violation,
        )

    def test_difference_of_a_run_has_the_read_s_position(self) -> None:
        """In a run of write skew via phantom on the store without validation, the first difference is T2's read
        a==1, with its position 3 in the schedule, what it returned and what it returns in the serial order T1, T2.

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
                                    read a==1 → {x}    <- position 3 (counted from 0)
        update y ← (a=1, b=0)
                                    delete x
        commit
                                    commit
        ```

        Would fail if run_schedule did not record a read's position in the schedule, or first_difference did not
        pass it on, so that the playground marked another operation.
        """
        x: Row = Row(1, 0)
        schedule: Schedule = (
            ScheduledOperation(0, "begin"),
            ScheduledOperation(1, "begin"),
            ScheduledOperation(0, DataOperation("read", a_equals=1)),
            ScheduledOperation(1, DataOperation("read", a_equals=1)),
            ScheduledOperation(0, DataOperation("update", "y", Row(1, 0))),
            ScheduledOperation(1, DataOperation("delete", "x")),
            ScheduledOperation(0, "commit"),
            ScheduledOperation(1, "commit"),
        )
        store: StoreWithoutValidation = StoreWithoutValidation()
        store.put("x", x)
        run: ScheduleRun = run_schedule(store, schedule)
        self.assertEqual(
            Difference(
                transaction="T2",
                read=DataOperation("read", a_equals=1),
                position=3,
                observed=(StoredObject("x", x),),
                serial=(StoredObject("x", x), StoredObject("y", Row(1, 0))),
            ),
            first_difference({"x": x}, run.records, run.final_state),
        )

    def test_store_without_validation_is_caught_with_three_transactions(self) -> None:
        """A store that skips validation is caught in a small three-transaction space.

        The space has two data operations, so it runs in the regular test job.
        """
        space: ScheduleSpace = ScheduleSpace(
            INITIAL_STATE,
            (
                DataOperation("read", a_equals=1),
                DataOperation("update", "x", Row(0, 0)),
            ),
            frozenset({(2, 1, 1), (1, 2, 1), (1, 1, 2)}),
        )
        check: ScheduleCheck = check_all_schedules(StoreWithoutValidation, space)
        assert check.violation is not None
        self.assertIn("in the serial order it returns", check.violation)

    def test_two_commits_during_writer_are_counted_on_the_store(self) -> None:
        """Blind writes of three transactions on the store give schedules with two commits during a writer.

        All of these schedules are serializable.
        """
        space: ScheduleSpace = ScheduleSpace(
            INITIAL_STATE,
            (
                DataOperation("update", "y", Row(1, 0)),
                DataOperation("update", "z", Row(1, 0)),
            ),
            frozenset({(1, 1, 1)}),
        )
        for use_brute_force_validation in (True, False):
            with self.subTest(use_brute_force_validation=use_brute_force_validation):
                check: ScheduleCheck = check_all_schedules(
                    functools.partial(
                        TransactionalKeyValueStore,
                        use_brute_force_validation=use_brute_force_validation,
                    ),
                    space,
                )
                if check.violation is not None:
                    self.fail(check.violation)
                self.assertGreater(check.two_commits_during_writer, 0)


def made_up_writer(
    name: str,
    first_position: int,
    last_position: int,
    committed: bool = True,
    aborted_at_commit: bool = False,
) -> TransactionRecord:
    """Returns a made-up record of a transaction that wrote x and ran from first_position to last_position."""
    return TransactionRecord(
        name=name,
        data_operations=[
            ExecutedDataOperation(DataOperation("update", "x", Row(0, 0)))
        ],
        committed=committed,
        aborted=aborted_at_commit,
        aborted_at_commit=aborted_at_commit,
        first_position=first_position,
        last_position=last_position,
    )


def made_up_reader(
    name: str, first_position: int, last_position: int
) -> TransactionRecord:
    """Returns a made-up record of a committed read-only transaction that ran from first_position to last_position."""
    return TransactionRecord(
        name=name,
        data_operations=[ExecutedDataOperation(DataOperation("read"), ())],
        committed=True,
        first_position=first_position,
        last_position=last_position,
    )


class ScheduleSpaceTest(unittest.TestCase):
    """Checks that a schedule space rejects data operation counts that the enumeration cannot handle."""

    def test_rejects_transaction_without_data_operation(self) -> None:
        """Every transaction needs at least one data operation."""
        with self.assertRaisesRegex(ValueError, "at least one data operation"):
            ScheduleSpace(INITIAL_STATE, DATA_OPERATIONS, frozenset({(0, 1), (1, 0)}))

    def test_rejects_operation_counts_not_closed_under_reordering(self) -> None:
        """With (2, 1) allowed, (1, 2) must be allowed as well, as transactions are numbered in begin order."""
        with self.assertRaisesRegex(ValueError, r"must contain \(1, 2\)"):
            ScheduleSpace(INITIAL_STATE, DATA_OPERATIONS, frozenset({(2, 1)}))

    def test_rejects_different_numbers_of_transactions(self) -> None:
        """All schedules of a space have the same number of transactions."""
        with self.assertRaisesRegex(ValueError, "same length"):
            ScheduleSpace(
                INITIAL_STATE, DATA_OPERATIONS, frozenset({(1, 1), (1, 1, 1)})
            )

    def test_rejects_empty_operation_counts(self) -> None:
        """A space without any data operation counts has no schedules and no number of transactions."""
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            ScheduleSpace(INITIAL_STATE, DATA_OPERATIONS, frozenset())

    def test_rejects_schedules_without_transactions(self) -> None:
        """A schedule has at least one transaction."""
        with self.assertRaisesRegex(ValueError, "at least one transaction"):
            ScheduleSpace(INITIAL_STATE, DATA_OPERATIONS, frozenset({()}))


class CountersTest(unittest.TestCase):
    """Checks the helpers that count interesting schedules on made-up records."""

    def test_overlapping_committed_writers(self) -> None:
        """Two committed writers overlap if each one begins before the other one ends.

        Positions are indexes in the schedule; the made-up records use only the positions listed. Each record also
        contains a write of x (a read for a read-only transaction); it has no position of its own and is not shown.
        T1 and T2 overlap:

        ```text
        position    T1                T2
        0           begin
        2                             begin
        5           commit
        7                             commit
        ```

        They do not overlap if T2 begins after T1 ended:

        ```text
        position    T1                T2
        0           begin
        3           commit
        4                             begin
        7                             commit
        ```

        With the positions of the first schedule, they do not count as overlapping committed writers if T2 does not
        commit (its record has committed=False), or if T2 only reads.
        """
        self.assertTrue(
            overlapping_committed_writers(
                [made_up_writer("T1", 0, 5), made_up_writer("T2", 2, 7)]
            )
        )
        # T2 begins after T1 ended:
        self.assertFalse(
            overlapping_committed_writers(
                [made_up_writer("T1", 0, 3), made_up_writer("T2", 4, 7)]
            )
        )
        # a writer that did not commit does not count:
        self.assertFalse(
            overlapping_committed_writers(
                [
                    made_up_writer("T1", 0, 5),
                    made_up_writer("T2", 2, 7, committed=False),
                ]
            )
        )
        # a read-only transaction does not count:
        self.assertFalse(
            overlapping_committed_writers(
                [made_up_writer("T1", 0, 5), made_up_reader("T2", 2, 7)]
            )
        )

    def test_two_commits_during_writer(self) -> None:
        """Two writers that commit between the begin and the commit of a third writer are counted.

        Each record also contains a write of x; it has no position of its own and is not shown.

        ```text
        T1                T2                T3
        begin
                          begin
                                            begin
                          commit
                                            commit
        commit
        ```
        """
        self.assertTrue(
            two_commits_during_writer(
                [
                    made_up_writer("T1", 0, 5),
                    made_up_writer("T2", 1, 3),
                    made_up_writer("T3", 2, 4),
                ]
            )
        )

    def test_two_commits_during_writer_aborted_at_commit(self) -> None:
        """A writer aborted in its validation phase counts as well, as its validation saw the two commits.

        Each record also contains a write of x; it has no position of its own and is not shown.

        ```text
        T1                T2                T3
        begin
                          begin
                                            begin
                          commit
                                            commit
        commit -> aborted
        ```
        """
        self.assertTrue(
            two_commits_during_writer(
                [
                    made_up_writer("T1", 0, 5, committed=False, aborted_at_commit=True),
                    made_up_writer("T2", 1, 3),
                    made_up_writer("T3", 2, 4),
                ]
            )
        )

    def test_one_commit_during_each_writer_is_not_counted(self) -> None:
        """Each writer sees at most one other commit during its run.

        Each record also contains a write of x; it has no position of its own and is not shown.

        ```text
        T1                T2                T3
        begin
                          begin
                          commit
                                            begin
        commit
                                            commit
        ```
        """
        self.assertFalse(
            two_commits_during_writer(
                [
                    made_up_writer("T1", 0, 4),
                    made_up_writer("T2", 1, 2),
                    made_up_writer("T3", 3, 5),
                ]
            )
        )

    def test_commits_of_readers_or_around_a_reader_are_not_counted(self) -> None:
        """A read-only transaction neither counts as a commit nor as the transaction that sees the commits.

        Each record also contains a write of x, or a read for the read-only transaction; it has no position of its own
        and is not shown. In the first case T3 is read-only:

        ```text
        T1                T2                T3 (read-only)
        begin
                          begin
                                            begin
                          commit
                                            commit
        commit
        ```

        In the second case T1 is read-only:

        ```text
        T1 (read-only)    T2                T3
        begin
                          begin
                                            begin
                          commit
                                            commit
        commit
        ```
        """
        # T3 is read-only, so only one writer commits during T1:
        self.assertFalse(
            two_commits_during_writer(
                [
                    made_up_writer("T1", 0, 5),
                    made_up_writer("T2", 1, 3),
                    made_up_reader("T3", 2, 4),
                ]
            )
        )
        # T1 is read-only, so the two commits during it do not count:
        self.assertFalse(
            two_commits_during_writer(
                [
                    made_up_reader("T1", 0, 5),
                    made_up_writer("T2", 1, 3),
                    made_up_writer("T3", 2, 4),
                ]
            )
        )


@unittest.skipUnless(
    os.environ.get("EXPLAINDB_NIGHTLY") == "1",
    "takes about half an hour locally; set EXPLAINDB_NIGHTLY=1 (the nightly CI pipeline does)",
)
class NightlySerializabilityTest(ExhaustiveTestCase):
    """Runs all schedules of the larger schedule spaces on the store (nightly)."""

    def _assert_serializable_three(
        self,
        store_factory: Callable[[], TransactionalKeyValueStore],
        space: ScheduleSpace,
        expected_schedules: int,
    ) -> None:
        """Asserts that all schedules of space are serializable.

        Also asserts that in some of them two writers commit while a third writer runs.
        """
        check: ScheduleCheck = self._assert_serializable(
            store_factory, space, expected_schedules
        )
        self.assertGreater(check.two_commits_during_writer, 0)

    def test_three_transactions_method_1_brute_force(self) -> None:
        """Every schedule of THREE_TRANSACTIONS committed under validation method 1 is serializable."""
        self._assert_serializable_three(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=True),
            THREE_TRANSACTIONS,
            2_782_080,
        )

    def test_three_transactions_method_2_write_sets(self) -> None:
        """Every schedule of THREE_TRANSACTIONS committed under validation method 2 is serializable."""
        self._assert_serializable_three(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=False),
            THREE_TRANSACTIONS,
            2_782_080,
        )

    def test_two_read_write_transactions_method_1_brute_force(self) -> None:
        """Every schedule of THREE_TRANSACTIONS_TWO_READ_WRITE committed under method 1 is serializable."""
        self._assert_serializable_three(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=True),
            THREE_TRANSACTIONS_TWO_READ_WRITE,
            5_913_600,
        )

    def test_two_read_write_transactions_method_2_write_sets(self) -> None:
        """Every schedule of THREE_TRANSACTIONS_TWO_READ_WRITE committed under method 2 is serializable."""
        self._assert_serializable_three(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=False),
            THREE_TRANSACTIONS_TWO_READ_WRITE,
            5_913_600,
        )

    def test_two_transactions_with_abort_method_1_brute_force(self) -> None:
        """Every schedule of TWO_TRANSACTIONS_WITH_ABORT committed under method 1 is serializable."""
        self._assert_serializable(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=True),
            TWO_TRANSACTIONS_WITH_ABORT,
            1_023_840,
        )

    def test_two_transactions_with_abort_method_2_write_sets(self) -> None:
        """Every schedule of TWO_TRANSACTIONS_WITH_ABORT committed under method 2 is serializable."""
        self._assert_serializable(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=False),
            TWO_TRANSACTIONS_WITH_ABORT,
            1_023_840,
        )

    def test_two_longer_transactions_method_1_brute_force(self) -> None:
        """Every schedule of TWO_LONGER_TRANSACTIONS committed under method 1 is serializable."""
        self._assert_serializable(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=True),
            TWO_LONGER_TRANSACTIONS,
            1_105_632,
        )

    def test_two_longer_transactions_method_2_write_sets(self) -> None:
        """Every schedule of TWO_LONGER_TRANSACTIONS committed under method 2 is serializable."""
        self._assert_serializable(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=False),
            TWO_LONGER_TRANSACTIONS,
            1_105_632,
        )


if __name__ == "__main__":
    unittest.main()
