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
"""Exhaustive check that the MVCC store only commits serializable schedules of two transactions."""

from __future__ import annotations

import itertools
import math
import unittest
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Literal

from system.query_processing.predicates import WHERE_Clause
from system.stores.MVCC import TransactionAbortedException, TransactionalKeyValueStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore


@dataclass(frozen=True)
class Row:
    """The objects stored in the tests: ``a`` is filtered on, ``b`` only changes the content."""

    a: int
    b: int


@dataclass(frozen=True)
class Op:
    """One data operation of a transaction.

    A read returns the objects with ``a == a_equals``, or all objects if ``a_equals`` is None. An update stores
    ``row`` under ``key``, inserting ``key`` if it does not exist. A delete removes ``key``.
    """

    kind: Literal["read", "update", "delete"]
    key: str | None = None
    row: Row | None = None
    a_equals: int | None = None

    def __str__(self) -> str:
        """Shows the operation as in the schedule tables, e.g. ``update x=Row(1,0)``."""
        if self.kind == "read":
            return "read all" if self.a_equals is None else f"read a=={self.a_equals}"
        if self.kind == "update":
            return f"update {self.key}=Row({self.row.a},{self.row.b})"
        if self.kind == "delete":
            return f"delete {self.key}"
        raise ValueError(f"unknown operation kind {self.kind}")


# a step of a transaction's program: begin, commit or a data operation:
Step = Literal["begin", "commit"] | Op

# a schedule: the steps of both transactions in execution order, each with the index of its transaction
# (0 is T1, 1 is T2):
Schedule = list[tuple[int, Step]]

# the result of a read: (object_id, object)-pairs sorted by object_id:
ReadResult = tuple[tuple[str, Row], ...]

# the initial state: x is selected by a == 1, z is not, y does not exist yet:
INITIAL_STATE: dict[str, Row] = {"x": Row(1, 0), "z": Row(0, 0)}

# one representative per case of the validation (see TransactionalKeyValueStore._validate_transaction): whether
# a write changes what a read returns depends only on whether the object is selected by a == 1 before and after
# the write and on whether its content changes.
# There is no "delete y": deleting an object that was never stored raises KeyError.
OPERATIONS: list[Op] = [
    Op("read", a_equals=1),
    Op("read"),
    # x stays selected by a == 1, content changes:
    Op("update", "x", Row(1, 1)),
    # x stays selected by a == 1, content unchanged:
    Op("update", "x", Row(1, 0)),
    # x drops out of a == 1:
    Op("update", "x", Row(0, 0)),
    # x drops out of a == 1 by deletion:
    Op("delete", "x"),
    # y is inserted into a == 1:
    Op("update", "y", Row(1, 0)),
    # y is inserted outside of a == 1:
    Op("update", "y", Row(0, 0)),
    # z moves into a == 1:
    Op("update", "z", Row(1, 0)),
]

# every transaction runs 1 to MAX_OPERATIONS data operations:
MAX_OPERATIONS: int = 2


def programs(operations: list[Op], max_operations: int) -> list[list[Step]]:
    """Returns all programs ``begin, op_1, ..., op_k, commit`` with 1 <= k <= max_operations."""
    return [
        ["begin", *ops, "commit"]
        for k in range(1, max_operations + 1)
        for ops in itertools.product(operations, repeat=k)
    ]


def interleavings(program_1: list[Step], program_2: list[Step]) -> Iterator[Schedule]:
    """Yields every interleaving of two programs in which the first program begins first.

    The store numbers transactions in the order of their begin. So an interleaving in which the second program
    begins first is the same run as the mirrored interleaving with the two programs swapped. That one is enumerated
    when :func:`schedules` takes the pair of programs the other way round.
    """
    n: int = len(program_1) + len(program_2)
    rest: tuple[int, ...]
    # the first step (begin) of program_1 is at position 0, its other steps anywhere after it:
    for rest in itertools.combinations(range(1, n), len(program_1) - 1):
        positions_1: set[int] = {0, *rest}
        schedule: Schedule = []
        next_1: int = 0
        next_2: int = 0
        for i in range(n):
            if i in positions_1:
                schedule.append((0, program_1[next_1]))
                next_1 += 1
            else:
                schedule.append((1, program_2[next_2]))
                next_2 += 1
        yield schedule


def schedules(operations: list[Op], max_operations: int) -> Iterator[Schedule]:
    """Yields every schedule of two transactions with 1 to max_operations data operations each."""
    all_programs: list[list[Step]] = programs(operations, max_operations)
    for program_1, program_2 in itertools.product(all_programs, repeat=2):
        yield from interleavings(program_1, program_2)


def number_of_schedules(number_of_operations: int, max_operations: int) -> int:
    """Returns how many schedules :func:`schedules` yields.

    There are number_of_operations ** k programs with k data operations, each with L = k + 2 steps. For each pair
    of programs, the first program begins at position 0 and its other L_1 - 1 steps take any of the remaining
    L_1 + L_2 - 1 positions; with L = k + 2 this is comb(k_1 + k_2 + 3, k_1 + 1).
    """
    return sum(
        number_of_operations ** (k_1 + k_2) * math.comb(k_1 + k_2 + 3, k_1 + 1)
        for k_1 in range(1, max_operations + 1)
        for k_2 in range(1, max_operations + 1)
    )


@dataclass
class TransactionRecord:  # pylint: disable=too-many-instance-attributes
    """What one transaction did in a concurrent run."""

    # the name used in messages and tables, e.g. T1:
    name: str
    # the transaction id assigned by the store at begin:
    TA_id: int | None = None
    # the executed data operations in program order, each with the observed result for reads:
    operations: list[tuple[Op, ReadResult | None]] = field(default_factory=list)
    # True if the transaction committed:
    committed: bool = False
    # True if the store aborted the transaction, in a data operation or in its validation phase:
    aborted: bool = False
    # True if the store aborted the transaction in its validation phase:
    aborted_at_commit: bool = False
    # the commit timestamp assigned by the store, None unless committed:
    commit_timestamp: int | None = None
    # the positions of the first and last executed step of this transaction in the schedule:
    first_position: int | None = None
    last_position: int | None = None

    @property
    def wrote(self) -> bool:
        """True if the transaction executed an update or delete."""
        return any(op.kind != "read" for op, _ in self.operations)

    @property
    def serialization_point(self) -> int:
        """The position of a committed transaction in the equivalent serial order.

        A transaction that wrote is validated against the state at its commit, so it is placed at its commit
        timestamp. A read-only transaction is not validated; it reads the snapshot of its begin and is placed
        at its TA_id. Both come from the same counter, so they can be compared.
        """
        assert self.committed and self.TA_id is not None
        assert self.commit_timestamp is not None
        return self.commit_timestamp if self.wrote else self.TA_id


@dataclass
class ScheduleRun:
    """The outcome of running one schedule on a store."""

    # what each transaction did, in the order of their transaction index:
    records: list[TransactionRecord]
    # the most recent committed version of every object after the run (empty if the run stopped with an error):
    final_state: dict[str, Row]
    # one line per step for the schedule table: the transaction index and what happened:
    log: list[tuple[int, str]]
    # the exception the store raised other than TransactionAbortedException, None if there was none:
    error: str | None = None


def format_read_result(result: ReadResult) -> str:
    """Shows a read result compactly, e.g. ``{x=Row(1,0)}``."""
    return "{" + ", ".join(f"{key}=Row({row.a},{row.b})" for key, row in result) + "}"


def evaluate_read(state: dict[str, Row], a_equals: int | None) -> ReadResult:
    """Returns what a read with ``a == a_equals`` (or without predicate) returns on state."""
    return tuple(
        sorted(
            (
                (key, row)
                for key, row in state.items()
                if a_equals is None or row.a == a_equals
            ),
            key=lambda pair: pair[0],
        )
    )


def committed_state(store: TransactionalKeyValueStore) -> dict[str, Row]:
    """Returns the most recent committed version of every object, read directly from the store's versions."""
    state: dict[str, Row] = {}
    object_id: str
    entry: VersionedKeyValueStore.KVStoreEntry
    for object_id, entry in store.key_value_store.items():
        # an aborted insert leaves an entry without committed versions, a deleted object ends with a delete marker:
        if entry.committed and isinstance(
            entry.committed[-1], VersionedKeyValueStore.UpdateEntry
        ):
            state[object_id] = entry.committed[-1].value
    return state


def execute_step(
    store: TransactionalKeyValueStore, record: TransactionRecord, step: Step
) -> str:
    """Executes one step of a transaction on store, records it in record, and returns the line for the table.

    Exceptions of the store, including TransactionAbortedException, are passed on to the caller. If the validation
    phase aborts a commit, record.aborted_at_commit is set before the exception is passed on. Raises RuntimeError
    if a commit leaves the commit timestamp unset.
    """
    if step == "begin":
        record.TA_id = store.begin_transaction()
        return f"begin (TA_id {record.TA_id})"
    if step == "commit":
        try:
            store.commit_transaction(record.TA_id)
        except TransactionAbortedException:
            record.aborted_at_commit = True
            raise
        # commit_transaction does not return the commit timestamp, the transaction dictionary has it:
        commit_timestamp: int | None = store.TD[record.TA_id].committed_timestamp
        if commit_timestamp is None:
            raise RuntimeError("commit left committed_timestamp None")
        record.commit_timestamp = commit_timestamp
        record.committed = True
        return f"commit (timestamp {record.commit_timestamp})"
    if step.kind == "read":
        where: WHERE_Clause | None = (
            None if step.a_equals is None else WHERE_Clause("a", "==", step.a_equals)
        )
        result: ReadResult = tuple(
            sorted(store.read_objects(record.TA_id, where), key=lambda pair: pair[0])
        )
        record.operations.append((step, result))
        return f"{step} -> {format_read_result(result)}"
    if step.kind == "update":
        store.update_object(step.key, step.row, record.TA_id)
    elif step.kind == "delete":
        store.delete_object(step.key, record.TA_id)
    else:
        raise ValueError(f"unknown step {step}")
    record.operations.append((step, None))
    return str(step)


def run_schedule(store: TransactionalKeyValueStore, schedule: Schedule) -> ScheduleRun:
    """Runs schedule on store and records what each transaction did.

    A transaction aborted by the store skips its remaining steps. If the store raises any other exception, the run
    stops and the exception is recorded in error.
    """
    records: list[TransactionRecord] = [
        TransactionRecord(name="T1"),
        TransactionRecord(name="T2"),
    ]
    log: list[tuple[int, str]] = []
    position: int
    transaction_index: int
    step: Step
    for position, (transaction_index, step) in enumerate(schedule):
        record: TransactionRecord = records[transaction_index]
        if record.aborted:
            log.append((transaction_index, f"({step}: skipped)"))
            continue
        if record.first_position is None:
            record.first_position = position
        record.last_position = position
        try:
            log.append((transaction_index, execute_step(store, record, step)))
        except TransactionAbortedException:
            record.aborted = True
            log.append((transaction_index, f"{step}: aborted"))
        except Exception as error:  # pylint: disable=broad-exception-caught
            # any other exception is a bug of the store, it is reported with the schedule table:
            description: str = f"{step}: raised {type(error).__name__}: {error}"
            log.append((transaction_index, description))
            return ScheduleRun(records, {}, log, error=description)

    return ScheduleRun(records, committed_state(store), log)


def serial_order(records: list[TransactionRecord]) -> list[TransactionRecord]:
    """Returns the committed transactions ordered by their serialization points."""
    return sorted(
        (record for record in records if record.committed),
        key=lambda record: record.serialization_point,
    )


def serializability_violation(
    initial_state: dict[str, Row],
    records: list[TransactionRecord],
    final_state: dict[str, Row],
) -> str | None:
    """Replays the committed transactions serially and returns a description of the first difference, or None.

    The transactions are replayed one after another in the order of their serialization points. Every read
    must return what the transaction read in the concurrent run, and the final state must be the same.
    """
    state: dict[str, Row] = dict(initial_state)
    for record in serial_order(records):
        for op, observed in record.operations:
            if op.kind == "read":
                expected: ReadResult = evaluate_read(state, op.a_equals)
                if observed != expected:
                    return (
                        f"{record.name}: {op} returned {format_read_result(observed)}, "
                        f"in the serial order it returns {format_read_result(expected)}"
                    )
            elif op.kind == "update":
                state[op.key] = op.row
            elif op.kind == "delete":
                state.pop(op.key, None)
            else:
                raise ValueError(f"unknown operation {op}")
    if state != final_state:
        return (
            f"final state is {format_read_result(evaluate_read(final_state, None))}, "
            f"in the serial order it is {format_read_result(evaluate_read(state, None))}"
        )
    return None


def format_schedule(run: ScheduleRun) -> str:
    """Shows a run as a table with one column per transaction and time pointing down."""
    # the column width fits the longest line of the first transaction:
    width: int = 2 + max(
        [len(text) for transaction_index, text in run.log if transaction_index == 0]
        + [len(record.name) for record in run.records]
    )
    lines: list[str] = [
        "".join(record.name.ljust(width) for record in run.records).rstrip()
    ]
    for transaction_index, text in run.log:
        lines.append(" " * (width * transaction_index) + text)
    order: str = ", ".join(
        f"{record.name} ({'commit' if record.wrote else 'begin'} {record.serialization_point})"
        for record in serial_order(run.records)
    )
    lines.append(f"\nserial order: {order or '(nothing committed)'}")
    return "\n".join(lines)


@dataclass
class ScheduleCheck:
    """The result of checking all schedules on one kind of store."""

    # the number of schedules run (all of them unless a violation stopped the check early):
    schedules_run: int = 0
    # the number of schedules in which two transactions that both wrote ran concurrently and both committed:
    concurrent_writers: int = 0
    # the number of schedules in which the store aborted a transaction in its validation phase:
    validation_aborts: int = 0
    # the description of the first violation, including the schedule table; None if there is none:
    violation: str | None = None


def leftover_wip_versions(store: TransactionalKeyValueStore) -> list[str]:
    """Returns the ids of all objects that have a work-in-progress version."""
    return [
        object_id
        for object_id, entry in store.key_value_store.items()
        if entry.wip is not None
    ]


def check_all_schedules(
    store_factory: Callable[[], TransactionalKeyValueStore],
) -> ScheduleCheck:
    """Runs every schedule, each on a fresh store filled with INITIAL_STATE, and stops at the first violation.

    A violation is an exception of the store other than TransactionAbortedException, a work-in-progress version
    left after all transactions ended, or a difference from the serial replay. The check also counts the schedules
    in which two concurrent writers both committed and those with an abort in the validation phase.
    """
    check: ScheduleCheck = ScheduleCheck()
    schedule: Schedule
    for schedule in schedules(OPERATIONS, MAX_OPERATIONS):
        check.schedules_run += 1
        store: TransactionalKeyValueStore = store_factory()
        for key, row in INITIAL_STATE.items():
            store.put(key, row)
        run: ScheduleRun = run_schedule(store, schedule)
        violation: str | None = run.error
        if violation is None:
            # every transaction ended, so no work-in-progress version may be left:
            leftover: list[str] = leftover_wip_versions(store)
            if leftover:
                violation = f"work-in-progress versions left for {leftover}"
        if violation is None:
            violation = serializability_violation(
                INITIAL_STATE, run.records, run.final_state
            )
        if violation is not None:
            check.violation = f"{violation}\n\n{format_schedule(run)}"
            return check
        t_1, t_2 = run.records
        if t_1.aborted_at_commit or t_2.aborted_at_commit:
            check.validation_aborts += 1
        # the two transactions overlapped in time if each one started before the other one ended:
        overlapped: bool = (
            t_1.first_position < t_2.last_position
            and t_2.first_position < t_1.last_position
        )
        if overlapped and t_1.committed and t_2.committed and t_1.wrote and t_2.wrote:
            check.concurrent_writers += 1
    return check


class StoreWithoutValidation(TransactionalKeyValueStore):
    """A store whose validation never finds a conflict, so it commits non-serializable schedules."""

    def _validate_transaction(
        self, TA_id: int, commit_timestamp_for_this_TA: int
    ) -> bool:
        """See :meth:`TransactionalKeyValueStore._validate_transaction`.

        Always passes, so no conflict is ever detected.
        """
        return True


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

    def delete_object(self, object_id: str, TA_id: int) -> None:
        """See :meth:`TransactionalKeyValueStore.delete_object`.

        Always raises RuntimeError.
        """
        raise RuntimeError(f"cannot delete {object_id}")


class SerializabilityTest(unittest.TestCase):
    """Runs all schedules of two transactions on the store and checks the oracle itself."""

    def _assert_serializable(
        self, store_factory: Callable[[], TransactionalKeyValueStore]
    ) -> None:
        """Asserts that every schedule commits a serializable history and that the run was not trivial."""
        check: ScheduleCheck = check_all_schedules(store_factory)
        if check.violation is not None:
            self.fail(check.violation)
        # 255,960 = number_of_schedules(9, 2); fixed here so a change of OPERATIONS is noticed:
        self.assertEqual(255_960, check.schedules_run)
        self.assertEqual(
            number_of_schedules(len(OPERATIONS), MAX_OPERATIONS), check.schedules_run
        )
        # in some schedules two concurrent writers both commit, and in some the validation aborts a transaction
        # (these checks only rule out a store that aborts all concurrent writers or never aborts at validation):
        self.assertGreater(check.concurrent_writers, 0)
        self.assertGreater(check.validation_aborts, 0)

    def test_validation_method_1_brute_force(self) -> None:
        """Every schedule committed under validation method 1 (checksums of read results) is serializable."""
        self._assert_serializable(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=True)
        )

    def test_validation_method_2_write_sets(self) -> None:
        """Every schedule committed under validation method 2 (write sets) is serializable."""
        self._assert_serializable(
            lambda: TransactionalKeyValueStore(use_brute_force_validation=False)
        )

    def test_store_without_validation_is_caught(self) -> None:
        """A store that skips validation commits a schedule whose reads differ from the serial order."""
        check: ScheduleCheck = check_all_schedules(StoreWithoutValidation)
        self.assertIsNotNone(check.violation)
        self.assertIn("in the serial order it returns", check.violation)

    def test_crash_of_store_is_reported_with_schedule(self) -> None:
        """An exception other than TransactionAbortedException is reported together with the schedule table."""
        check: ScheduleCheck = check_all_schedules(StoreThatCrashesOnDelete)
        self.assertIsNotNone(check.violation)
        self.assertIn("delete x: raised RuntimeError: cannot delete x", check.violation)
        self.assertIn("serial order:", check.violation)

    def test_leftover_versions_are_reported(self) -> None:
        """A work-in-progress version left after all transactions ended is reported with the schedule table."""
        check: ScheduleCheck = check_all_schedules(
            StoreThatKeepsVersionsOfAbortedTransactions
        )
        self.assertIsNotNone(check.violation)
        self.assertIn("work-in-progress versions left for", check.violation)
        self.assertIn(": aborted", check.violation)
        self.assertIn("serial order:", check.violation)

    def test_commit_without_timestamp_is_reported(self) -> None:
        """A commit that leaves the commit timestamp unset is reported with the schedule table."""
        check: ScheduleCheck = check_all_schedules(StoreWithoutCommitTimestamp)
        self.assertIsNotNone(check.violation)
        self.assertIn(
            "commit: raised RuntimeError: commit left committed_timestamp None",
            check.violation,
        )
        self.assertIn("serial order:", check.violation)

    def test_number_of_schedules(self) -> None:
        """The enumeration yields exactly the intended schedules.

        Their number matches the closed form, all of them are different, and each one is an interleaving of two
        programs in which the first one begins first.
        """
        operations: list[Op] = OPERATIONS[:2]
        all_programs: list[list[Step]] = programs(operations, 2)
        generated: list[tuple[tuple[int, Step], ...]] = [
            tuple(schedule) for schedule in schedules(operations, 2)
        ]
        self.assertEqual(number_of_schedules(len(operations), 2), len(generated))
        self.assertEqual(len(generated), len(set(generated)))
        for schedule in generated:
            self.assertEqual((0, "begin"), schedule[0])
            for transaction_index in (0, 1):
                program: list[Step] = [
                    step for index, step in schedule if index == transaction_index
                ]
                self.assertIn(program, all_programs)

    def test_oracle_rejects_write_skew(self) -> None:
        """The oracle rejects write skew: no serial order explains both reads.

        Each transaction writes into what the other one read: T1 inserts y into a == 1, T2 deletes x.

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 -> {x}
                                    read a==1 -> {x}
        update y=Row(1,0)
                                    delete x
        commit
                                    commit
        ```
        """
        x: Row = Row(1, 0)
        t_1: TransactionRecord = TransactionRecord(
            name="T1",
            TA_id=1,
            operations=[
                (Op("read", a_equals=1), (("x", x),)),
                (Op("update", "y", Row(1, 0)), None),
            ],
            committed=True,
            commit_timestamp=3,
        )
        t_2: TransactionRecord = TransactionRecord(
            name="T2",
            TA_id=2,
            operations=[
                (Op("read", a_equals=1), (("x", x),)),
                (Op("delete", "x"), None),
            ],
            committed=True,
            commit_timestamp=4,
        )
        violation: str | None = serializability_violation(
            {"x": x}, [t_1, t_2], {"y": Row(1, 0)}
        )
        self.assertIsNotNone(violation)
        self.assertIn("T2: read a==1", violation)

    def test_oracle_accepts_serial_schedule(self) -> None:
        """The oracle accepts a serial schedule: T2 begins after T1 committed and sees T1's insert.

        ```text
        T1                          T2
        begin
        read a==1 -> {x}
        update y=Row(1,0)
        commit
                                    begin
                                    read a==1 -> {x, y}
                                    delete x
                                    commit
        ```
        """
        x: Row = Row(1, 0)
        t_1: TransactionRecord = TransactionRecord(
            name="T1",
            TA_id=1,
            operations=[
                (Op("read", a_equals=1), (("x", x),)),
                (Op("update", "y", Row(1, 0)), None),
            ],
            committed=True,
            commit_timestamp=2,
        )
        t_2: TransactionRecord = TransactionRecord(
            name="T2",
            TA_id=3,
            operations=[
                (Op("read", a_equals=1), (("x", x), ("y", Row(1, 0)))),
                (Op("delete", "x"), None),
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
                                    update x=Row(0,0)
                                    commit
        read a==1 -> {x}
        commit
        ```
        """
        x: Row = Row(1, 0)
        t_1: TransactionRecord = TransactionRecord(
            name="T1",
            TA_id=1,
            operations=[(Op("read", a_equals=1), (("x", x),))],
            committed=True,
            commit_timestamp=4,
        )
        t_2: TransactionRecord = TransactionRecord(
            name="T2",
            TA_id=2,
            operations=[(Op("update", "x", Row(0, 0)), None)],
            committed=True,
            commit_timestamp=3,
        )
        self.assertIsNone(
            serializability_violation({"x": x}, [t_1, t_2], {"x": Row(0, 0)})
        )

    def test_oracle_rejects_wrong_final_state(self) -> None:
        """All reads match the serial order, but the store lost the update of the only transaction."""
        x: Row = Row(1, 0)
        t_1: TransactionRecord = TransactionRecord(
            name="T1",
            TA_id=1,
            operations=[(Op("update", "x", Row(0, 0)), None)],
            committed=True,
            commit_timestamp=2,
        )
        violation: str | None = serializability_violation({"x": x}, [t_1], {"x": x})
        self.assertIsNotNone(violation)
        self.assertIn("final state", violation)


if __name__ == "__main__":
    unittest.main()
