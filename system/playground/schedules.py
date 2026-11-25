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

"""Schedules of transactions on the MVCC store: model, enumeration, execution and a check against a serial replay."""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Literal, cast

from system.query_processing.predicates import WHERE_Clause
from system.stores.MVCC import TransactionAbortedException, TransactionalKeyValueStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore


@dataclass(frozen=True)
class Row:
    """The objects stored in a schedule run: ``a`` is filtered on, ``b`` only changes the content."""

    a: int
    b: int

    def __str__(self) -> str:
        """Shows the value stored under a key, e.g. ``(a=1, b=0)``."""
        return f"(a={self.a}, b={self.b})"


@dataclass(frozen=True)
class DataOperation:
    """One data operation of a transaction.

    A read returns the objects with ``a == a_equals``, or all objects if ``a_equals`` is None. An update stores
    ``row`` under ``key``, inserting ``key`` if it does not exist. A delete removes ``key``.
    """

    kind: Literal["read", "update", "delete"]
    key: str | None = None
    row: Row | None = None
    a_equals: int | None = None

    def __str__(self) -> str:
        """Shows the operation as in the schedule tables, e.g. ``update x ← (a=1, b=0)``."""
        if self.kind == "read":
            return "read all" if self.a_equals is None else f"read a=={self.a_equals}"
        if self.kind == "update":
            return f"update {self.key} ← {self.row}"
        if self.kind == "delete":
            return f"delete {self.key}"
        raise ValueError(f"unknown operation kind {self.kind}")


# how a transaction ends: it commits, or it aborts on its own (the store may also abort it earlier):
Ending = Literal["commit", "abort"]

# an operation of a transaction: begin, a data operation, commit or abort:
Operation = Literal["begin"] | Ending | DataOperation

# a transaction: begin, then its data operations, then commit or abort, e.g. begin, read a==1, update y ← (a=1, b=0),
# commit. A schedule interleaves several transactions and keeps the order of the operations within each transaction:
Transaction = list[Operation]


@dataclass(frozen=True)
class ScheduledOperation:
    """An operation of a schedule: the operation and the index of the transaction running it (0 is T1, 1 is T2, ...)."""

    transaction_index: int
    operation: Operation


# a schedule: the operations of all transactions in execution order:
Schedule = tuple[ScheduledOperation, ...]


@dataclass(frozen=True)
class StoredObject:
    """An object stored under an object id."""

    object_id: str
    row: Row


# the result of a read: the returned objects sorted by object_id:
ReadResult = tuple[StoredObject, ...]


@dataclass(slots=True)
class ExecutedDataOperation:
    """A data operation a transaction executed, with the result it observed if it is a read."""

    data_operation: DataOperation
    # None unless data_operation is a read:
    result: ReadResult | None = None
    # the operation's position in the schedule, from 0; None for one not run from a schedule (e.g. made in a test):
    position: int | None = None


@dataclass(slots=True)
class LogLine:
    """A line of the schedule table: what happened in an operation of the transaction with the given index."""

    transaction_index: int
    text: str


@dataclass(frozen=True)
class ScheduleSpace:
    """A set of schedules, given by its initial state, data operations, data operation counts and endings.

    Each element of data_operation_counts gives the number of data operations of T1, T2, ...; its length is the number
    of transactions. Transactions are numbered in the order of their begin, so every reordering of an element
    must be an element as well. For example, if a transaction with two data operations and one with one data
    operation run concurrently, either of them can begin first and become T1, giving the counts (2, 1) or (1, 2); so
    (1, 2) must be allowed whenever (2, 1) is.
    """

    # the objects in the store before the first transaction begins:
    initial_state: tuple[StoredObject, ...]
    # the data operations a transaction can run:
    data_operations: tuple[DataOperation, ...]
    # the allowed numbers of data operations of the transactions, e.g. (2, 1, 1):
    data_operation_counts: frozenset[tuple[int, ...]]
    # the ways a transaction can end; each transaction ends with one of them, and every choice is enumerated:
    endings: tuple[Ending, ...] = ("commit",)

    def __post_init__(self) -> None:
        """Checks that data_operation_counts is well-formed.

        It is not empty, its elements are not empty, all have the same length and give every transaction at least
        one data operation, and every reordering of an element is an element as well. Raises ValueError otherwise.
        """
        if not self.data_operation_counts:
            raise ValueError("data_operation_counts must not be empty")
        if len({len(counts) for counts in self.data_operation_counts}) != 1:
            raise ValueError(
                f"all elements of data_operation_counts must have the same length: {set(self.data_operation_counts)}"
            )
        for counts in self.data_operation_counts:
            if not counts:
                raise ValueError(
                    "the elements of data_operation_counts must not be empty: a schedule needs at least one transaction"
                )
            if min(counts) < 1:
                raise ValueError(
                    f"every transaction needs at least one data operation: {counts}"
                )
            for reordered in itertools.permutations(counts):
                if reordered not in self.data_operation_counts:
                    raise ValueError(
                        f"data_operation_counts contains {counts}, so it must contain {reordered} as well"
                    )

    @property
    def number_of_transactions(self) -> int:
        """The number of transactions in every schedule."""
        return len(next(iter(self.data_operation_counts)))


def all_transactions(
    data_operations: tuple[DataOperation, ...],
    max_operations: int,
    endings: tuple[Ending, ...] = ("commit",),
) -> list[Transaction]:
    """Returns all transactions ``begin, op_1, ..., op_k, ending`` with 1 <= k <= max_operations."""
    # for every number k of data operations, every sequence of k data operations (repetitions allowed), framed by
    # begin and each ending; transactions with fewer data operations come first:
    return [
        ["begin", *ops, ending]
        for k in range(1, max_operations + 1)
        for ops in itertools.product(data_operations, repeat=k)
        for ending in endings
    ]


def interleavings(transactions: list[Transaction]) -> Iterator[Schedule]:
    """Yields every interleaving of the transactions in which transaction i begins after transaction i - 1.

    The store numbers transactions in the order of their begin. So an interleaving in which a later transaction
    begins first is the same run as an interleaving with the transactions reordered by their begin. That one is
    enumerated when :func:`schedules` takes the transactions in that order.
    """
    n: int = len(transactions)
    total_operations: int = sum(len(transaction) for transaction in transactions)
    # the operations of each transaction, created once and shared by all interleavings:
    scheduled_operations: list[list[ScheduledOperation]] = [
        [ScheduledOperation(i, operation) for operation in transaction]
        for i, transaction in enumerate(transactions)
    ]
    # the position of the next operation to run in each transaction:
    next_operations: list[int] = [0] * n
    schedule: list[ScheduledOperation] = []

    def extend() -> Iterator[Schedule]:
        """Yields every complete schedule that starts with the operations already in ``schedule``.

        The transactions are tried in index order.
        """
        # all operations are placed: yield a copy, as schedule changes later:
        if len(schedule) == total_operations:
            yield tuple(schedule)
            return
        # every transaction that still has operations left may run its next operation at this position:
        for i in range(n):
            # transaction i already ran all its operations:
            if next_operations[i] == len(transactions[i]):
                continue
            # transaction i may begin only after transaction i - 1 has begun:
            if next_operations[i] == 0 and i > 0 and next_operations[i - 1] == 0:
                continue
            # run the next operation of transaction i, complete the schedule in every possible way, then undo the
            # operation to try the next transaction at this position:
            schedule.append(scheduled_operations[i][next_operations[i]])
            next_operations[i] += 1
            yield from extend()
            next_operations[i] -= 1
            schedule.pop()

    # start with the empty schedule:
    yield from extend()


def schedules(space: ScheduleSpace) -> Iterator[Schedule]:
    """Yields every schedule of space."""
    # all transactions that space allows:
    max_operations: int = max(max(counts) for counts in space.data_operation_counts)
    candidates: list[Transaction] = all_transactions(
        space.data_operations, max_operations, space.endings
    )
    transactions: tuple[Transaction, ...]
    # every choice of T1, ..., Tn among them ...
    for transactions in itertools.product(
        candidates, repeat=space.number_of_transactions
    ):
        # a transaction has two operations (begin and its ending) besides its data operations:
        counts: tuple[int, ...] = tuple(
            len(transaction) - 2 for transaction in transactions
        )
        # ... whose numbers of data operations are allowed in space, in every interleaving:
        if counts in space.data_operation_counts:
            yield from interleavings(list(transactions))


def number_of_schedules(space: ScheduleSpace) -> int:
    """Returns how many schedules :func:`schedules` yields.

    For data operation counts k_1, ..., k_n there are A ** (k_1 + ... + k_n) * E ** n choices of T1, ..., Tn (A data
    operations, E endings), with L_i = k_i + 2 operations per transaction and (L_1 + ... + L_n)! / (L_1! ... L_n!)
    interleavings. The sum of choices times interleavings over all data operation counts counts every run n! times,
    once for each way of naming its transactions T1, ..., Tn, but only the naming in begin order is enumerated.
    Because the data operation counts are closed under reordering, all n! namings are in the sum, so the total is
    divided by n! once at the end; a single term need not be divisible by n!.
    """
    total: int = 0
    for counts in space.data_operation_counts:
        # each transaction has its data operations plus begin and its ending:
        lengths: list[int] = [k + 2 for k in counts]
        # the multinomial coefficient (L_1 + ... + L_n)! / (L_1! ... L_n!), computed one factor at a time:
        interleaving_count: int = math.factorial(sum(lengths))
        for length in lengths:
            interleaving_count //= math.factorial(length)
        # every data operation can be any of the A data operations, every ending any of the E endings:
        total += (
            len(space.data_operations) ** sum(counts)
            * len(space.endings) ** len(counts)
            * interleaving_count
        )
    n_factorial: int = math.factorial(space.number_of_transactions)
    # exact, as argued above (ScheduleSpace ensures that the data operation counts are closed under reordering):
    assert total % n_factorial == 0
    return total // n_factorial


@dataclass
class TransactionRecord:  # pylint: disable=too-many-instance-attributes
    """What one transaction did in a concurrent run."""

    # the name used in messages and tables, e.g. T1:
    name: str
    # the transaction id assigned by the store at begin:
    TA_id: int | None = None
    # the executed data operations in the transaction's order, each with the observed result for reads:
    data_operations: list[ExecutedDataOperation] = field(default_factory=list)
    # True if the transaction committed:
    committed: bool = False
    # True if the transaction was aborted: by the store, in a data operation or in its validation phase, or by its
    # own abort operation:
    aborted: bool = False
    # True if the store aborted the transaction in its validation phase:
    aborted_at_commit: bool = False
    # the commit timestamp assigned by the store, None unless committed:
    commit_timestamp: int | None = None
    # the positions of the first and last executed operation of this transaction in the schedule:
    first_position: int | None = None
    last_position: int | None = None

    @property
    def wrote(self) -> bool:
        """True if the transaction executed an update or delete."""
        return any(
            executed.data_operation.kind != "read" for executed in self.data_operations
        )

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
    # one line per operation for the schedule table: the transaction index and what happened:
    log: list[LogLine]
    # a description of the exception, other than TransactionAbortedException, that stopped the run (raised by the
    # store or by execute_operation); None if there was none:
    error: str | None = None


def format_read_result(result: ReadResult) -> str:
    """Shows a read result as keys and values, e.g. ``{x: (a=1, b=0)}``."""
    return (
        "{" + ", ".join(f"{stored.object_id}: {stored.row}" for stored in result) + "}"
    )


def evaluate_read(state: dict[str, Row], a_equals: int | None) -> ReadResult:
    """Returns what a read with ``a == a_equals`` (or of all objects if a_equals is None) returns on state."""
    # the matching objects, sorted by object_id like the observed read results, so that both can be compared:
    return tuple(
        sorted(
            (
                StoredObject(object_id, row)
                for object_id, row in state.items()
                if a_equals is None or row.a == a_equals
            ),
            key=lambda stored: stored.object_id,
        )
    )


def committed_state(store: TransactionalKeyValueStore) -> dict[str, Row]:
    """Returns the most recent committed version of every object, read directly from the store's versions."""
    state: dict[str, Row] = {}
    object_id: str
    entry: VersionedKeyValueStore.KVStoreEntry
    for object_id, entry in store.key_value_store.items():
        # the last committed version is the most recent one (versions are appended in commit order);
        # an aborted insert leaves an entry without committed versions, a deleted object ends with a delete marker:
        if entry.committed and isinstance(
            entry.committed[-1], VersionedKeyValueStore.UpdateEntry
        ):
            # a schedule stores only Rows (the store's versions hold any object):
            state[object_id] = cast(Row, entry.committed[-1].value)
    return state


def execute_operation(
    store: TransactionalKeyValueStore,
    record: TransactionRecord,
    operation: Operation,
    position: int,
) -> str:
    """Executes one operation of a transaction on store, records it in record, and returns the line for the table.

    Exceptions of the store, including TransactionAbortedException, are passed on to the caller. If the validation
    phase aborts a commit, record.aborted_at_commit is set before the exception is passed on. Raises RuntimeError
    if a commit leaves the commit timestamp unset.

    @param position: the operation's position in the schedule, recorded with a data operation
    """
    if operation == "begin":
        # the store assigns the transaction id, which is also the begin of its snapshot:
        record.TA_id = store.begin_transaction()
        return f"begin (ts {record.TA_id})"
    if operation == "abort":
        # the transaction's begin set TA_id:
        assert record.TA_id is not None, f"{record.name} has not begun"
        # the transaction gives up on its own: the store removes its work-in-progress versions; like any aborted
        # transaction it is left out of the serial replay:
        store.abort_transaction(record.TA_id)
        record.aborted = True
        return "abort"
    if operation == "commit":
        # the transaction's begin set TA_id:
        assert record.TA_id is not None, f"{record.name} has not begun"
        try:
            # runs the validation phase; on a conflict the store aborts the transaction:
            store.commit_transaction(record.TA_id)
        except TransactionAbortedException:
            # remember that the abort happened in the validation phase; run_schedule handles the abort:
            record.aborted_at_commit = True
            raise
        # commit_transaction does not return the commit timestamp, the transaction dictionary has it:
        commit_timestamp: int | None = store.TD[record.TA_id].committed_timestamp
        if commit_timestamp is None:
            raise RuntimeError("commit left committed_timestamp None")
        record.commit_timestamp = commit_timestamp
        record.committed = True
        return f"commit (ts {record.commit_timestamp})"
    if operation.kind == "read":
        # a read with a == a_equals, or of all objects:
        where: WHERE_Clause | None = (
            None
            if operation.a_equals is None
            else WHERE_Clause("a", "==", operation.a_equals)
        )
        # the store returns (object_id, object)-pairs in its own order (a schedule stores only Rows); sorted, they can
        # be compared with the result of the same read in the serial replay:
        result: ReadResult = tuple(
            sorted(
                (
                    StoredObject(object_id, cast(Row, row))
                    for object_id, row in store.read_objects(record.TA_id, where)
                ),
                key=lambda stored: stored.object_id,
            )
        )
        # record what the transaction saw, the oracle checks it later:
        record.data_operations.append(
            ExecutedDataOperation(operation, result, position)
        )
        return f"{operation} → {format_read_result(result)}"
    # a write creates a work-in-progress version, visible to other transactions only after the commit (an update
    # always names its key and row, a delete its key):
    if operation.kind == "update":
        assert (
            operation.key is not None and operation.row is not None
        ), f"{operation} needs a key and a row"
        store.update_object(operation.key, operation.row, record.TA_id)
    elif operation.kind == "delete":
        assert operation.key is not None, f"{operation} needs a key"
        store.delete_object(operation.key, record.TA_id)
    else:
        raise ValueError(f"unknown operation {operation}")
    # record the write, the oracle applies it in the serial replay:
    record.data_operations.append(ExecutedDataOperation(operation, position=position))
    return str(operation)


def run_schedule(
    store: TransactionalKeyValueStore,
    schedule: Schedule,
    operation_count: int | None = None,
) -> ScheduleRun:
    """Runs schedule on store and records what each transaction did.

    A transaction aborted by the store skips its remaining operations. If the store raises any other exception, the run
    stops and the exception is recorded in error. Every transaction of the whole schedule gets a record, also one that
    has not begun yet.

    @param operation_count: run only the first operation_count operations; None runs all of them
    """
    # the transactions are numbered 0, 1, ..., so the largest index gives their number (none in an empty schedule):
    number_of_transactions: int = 1 + max(
        (scheduled.transaction_index for scheduled in schedule), default=-1
    )
    # one record per transaction, filled while its operations run (T1 for index 0, T2 for index 1, ...):
    records: list[TransactionRecord] = [
        TransactionRecord(name=f"T{index + 1}")
        for index in range(number_of_transactions)
    ]
    # one line per operation for the schedule table (shown by the playground, and by the tests if a run violates
    # serializability):
    log: list[LogLine] = []
    position: int
    scheduled: ScheduledOperation
    # run the operations in the order of the schedule; position is the operation's time in the schedule table:
    for position, scheduled in enumerate(schedule[:operation_count]):
        transaction_index: int = scheduled.transaction_index
        operation: Operation = scheduled.operation
        record: TransactionRecord = records[transaction_index]
        # the store already aborted this transaction (and removed it), so its remaining operations cannot run:
        if record.aborted:
            log.append(LogLine(transaction_index, f"({operation}: skipped)"))
            continue
        # remember when the transaction ran, to find out later which transactions overlapped in time:
        if record.first_position is None:
            record.first_position = position
        record.last_position = position
        try:
            # run the operation on the store and record its outcome (e.g. the result of a read) in record:
            log.append(
                LogLine(
                    transaction_index,
                    execute_operation(store, record, operation, position),
                )
            )
        except TransactionAbortedException:
            # the store aborted the transaction, in a data operation or in its validation phase; this is
            # allowed, the oracle only checks committed transactions:
            record.aborted = True
            log.append(LogLine(transaction_index, f"{operation}: aborted"))
        except Exception as error:  # pylint: disable=broad-exception-caught
            # any other exception is a bug of the store, it is reported with the schedule table; the state of the
            # store is undefined now, so the run stops here:
            description: str = f"{operation}: raised {type(error).__name__}: {error}"
            log.append(LogLine(transaction_index, description))
            return ScheduleRun(records, {}, log, error=description)

    # the operations ran without an error: read the committed state, which the oracle compares with the serial replay:
    return ScheduleRun(records, committed_state(store), log)


def serial_order(records: list[TransactionRecord]) -> list[TransactionRecord]:
    """Returns the committed transactions ordered by their serialization points."""
    return sorted(
        (record for record in records if record.committed),
        key=lambda record: record.serialization_point,
    )


@dataclass(frozen=True)
class Difference:
    """The first difference between a concurrent run and a serial replay: a read that returned something else, or,
    if all reads match, the final state.
    """

    # the transaction and the read that differ, None if only the final state differs:
    transaction: str | None
    read: DataOperation | None
    # the read's position in the schedule, None if only the final state differs or the read was not run from one:
    position: int | None
    # what the concurrent run gave (the read's result or the final state), and what the serial replay gives:
    observed: ReadResult
    serial: ReadResult

    def description(self) -> str:
        """Returns the difference as a sentence, e.g. ``T2: read a==1 returned {x: (a=1, b=0)}, in the serial order
        it returns {}``.
        """
        if self.read is None:
            return (
                f"final state is {format_read_result(self.observed)}, "
                f"in the serial order it is {format_read_result(self.serial)}"
            )
        return (
            f"{self.transaction}: {self.read} returned {format_read_result(self.observed)}, "
            f"in the serial order it returns {format_read_result(self.serial)}"
        )


def first_difference(
    initial_state: dict[str, Row],
    records: list[TransactionRecord],
    final_state: dict[str, Row],
    order: list[TransactionRecord] | None = None,
) -> Difference | None:
    """Replays the committed transactions serially and returns the first difference from the concurrent run, or None.

    The transactions are replayed one after another in the order of their serialization points, or in the given
    order. Every read in the replay must return what it returned in the concurrent run, and the final state must be
    the same.

    @param initial_state: the objects before the first operation
    @param records: what each transaction did in the concurrent run
    @param final_state: the committed objects after the concurrent run
    @param order: the committed transactions in the order to replay them; None for the serialization points
    @return: the first read that returns something else in the replay, or the final state if only it differs; None
        if the run behaved like this serial order
    """
    # the state of the serial replay, a plain dictionary from object id to object:
    state: dict[str, Row] = dict(initial_state)
    # run the committed transactions one after another (aborted ones had no effect and are left out) ...
    for record in serial_order(records) if order is None else order:
        # ... each with its data operations in the order it ran them:
        for executed in record.data_operations:
            data_operation: DataOperation = executed.data_operation
            if data_operation.kind == "read":
                # in a serial execution, the read sees exactly the current state, including the transaction's
                # own earlier writes:
                expected: ReadResult = evaluate_read(state, data_operation.a_equals)
                # a read always records its result:
                assert executed.result is not None
                if executed.result != expected:
                    return Difference(
                        transaction=record.name,
                        read=data_operation,
                        position=executed.position,
                        observed=executed.result,
                        serial=expected,
                    )
            elif data_operation.kind == "update":
                # an update inserts the object if it does not exist; it always names its key and row:
                assert data_operation.key is not None and data_operation.row is not None
                state[data_operation.key] = data_operation.row
            elif data_operation.kind == "delete":
                # deleting an object that does not exist (any more) changes nothing; a delete always names its key:
                assert data_operation.key is not None
                state.pop(data_operation.key, None)
            else:
                raise ValueError(f"unknown data operation {data_operation}")
    # all reads matched; the store must end in the state of the serial replay as well:
    if state != final_state:
        return Difference(
            transaction=None,
            read=None,
            position=None,
            observed=evaluate_read(final_state, None),
            serial=evaluate_read(state, None),
        )
    return None


def serializability_violation(
    initial_state: dict[str, Row],
    records: list[TransactionRecord],
    final_state: dict[str, Row],
    order: list[TransactionRecord] | None = None,
) -> str | None:
    """Replays the committed transactions serially and returns a description of the first difference, or None.

    This check is the oracle of the tests: it decides for every run whether the store behaved like the serial order
    (see :func:`first_difference`, which takes the same parameters).
    """
    difference: Difference | None = first_difference(
        initial_state, records, final_state, order
    )
    return None if difference is None else difference.description()


def format_schedule(run: ScheduleRun) -> str:
    """Shows a run as a table with one column per transaction and time pointing down."""
    # the column width fits the longest line of all transactions but the last one (the last column is not padded, so
    # it can be as wide as needed):
    last: int = len(run.records) - 1
    width: int = 2 + max(
        [len(line.text) for line in run.log if line.transaction_index < last]
        + [len(record.name) for record in run.records]
    )
    # the header names the transactions, one column each:
    lines: list[str] = [
        "".join(record.name.ljust(width) for record in run.records).rstrip()
    ]
    # one line per operation, indented to the column of its transaction:
    for line in run.log:
        lines.append(" " * (width * line.transaction_index) + line.text)
    # the order of the serial replay, with the serialization point that put each transaction there:
    order: str = ", ".join(
        f"{record.name} ({'commit' if record.wrote else 'begin'} ts {record.serialization_point})"
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
    overlapping_committed_writers: int = 0
    # the number of schedules in which two writers committed between the begin and the commit of a third
    # writer, so that its validation checks the writes of two transactions:
    two_commits_during_writer: int = 0
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


def overlapping_committed_writers(records: list[TransactionRecord]) -> bool:
    """True if two transactions that both wrote and committed overlapped in time."""
    writers: list[TransactionRecord] = [
        record for record in records if record.committed and record.wrote
    ]
    for t_i, t_j in itertools.combinations(writers, 2):
        # both committed, so both ran operations and have their first and last position set:
        assert t_i.first_position is not None and t_i.last_position is not None
        assert t_j.first_position is not None and t_j.last_position is not None
        # two transactions overlapped in time if each one started before the other one ended:
        if (
            t_i.first_position < t_j.last_position
            and t_j.first_position < t_i.last_position
        ):
            return True
    return False


def two_commits_during_writer(records: list[TransactionRecord]) -> bool:
    """True if two writers committed between the begin and the commit of a third writer.

    The third writer reached its commit, i.e. it committed or was aborted in its validation phase; the commit
    operation is the last operation it ran. With fewer than three transactions this is never the case.
    """
    # a writer and two other writers are needed:
    if len(records) < 3:
        return False
    # look for a writer during whose run two others committed:
    for record in records:
        # only a writer that reached its commit was validated:
        if record.wrote and (record.committed or record.aborted_at_commit):
            # it ran operations, so its first and last position are set:
            assert (
                record.first_position is not None and record.last_position is not None
            )
            # the other committed writers whose commit (their last operation) falls into record's run (a committed
            # transaction ran operations, so its last position is set; the `is not None` test is only there for the
            # type checker):
            intervening: int = sum(
                1
                for other in records
                if other is not record
                and other.committed
                and other.wrote
                and other.last_position is not None
                and record.first_position < other.last_position < record.last_position
            )
            # its validation had to take (at least) two other commits into account:
            if intervening >= 2:
                return True
    return False


def check_all_schedules(
    store_factory: Callable[[], TransactionalKeyValueStore], space: ScheduleSpace
) -> ScheduleCheck:
    """Runs every schedule of space, each on a fresh store, and stops at the first violation.

    A violation is an exception of the store other than TransactionAbortedException, a work-in-progress version
    left after all transactions ended, or a difference from the serial replay. The check also counts the schedules
    in which two concurrent writers both committed, those with an abort in the validation phase, and those in which
    two writers committed while a third writer ran (see :func:`two_commits_during_writer`).
    """
    check: ScheduleCheck = ScheduleCheck()
    # the initial state as a dictionary, for filling the store and for the serial replay:
    initial_state: dict[str, Row] = {
        stored.object_id: stored.row for stored in space.initial_state
    }
    schedule: Schedule
    # run the schedules one by one; schedules() creates them lazily, so they never all exist at once:
    for schedule in schedules(space):
        check.schedules_run += 1
        # a fresh store per schedule, so that schedules cannot influence each other:
        store: TransactionalKeyValueStore = store_factory()
        for key, row in initial_state.items():
            store.put(key, row)
        run: ScheduleRun = run_schedule(store, schedule)
        # the first problem found, from the most basic to the oracle: a crash of the store ...
        violation: str | None = run.error
        if violation is None:
            # ... a leftover version: every transaction ended, so no work-in-progress version may be left ...
            leftover: list[str] = leftover_wip_versions(store)
            if leftover:
                violation = f"work-in-progress versions left for {leftover}"
        if violation is None:
            # ... or a difference from the serial replay:
            violation = serializability_violation(
                initial_state, run.records, run.final_state
            )
        # report the first problem with the schedule table and stop; one counterexample shows that the store is wrong:
        if violation is not None:
            check.violation = f"{violation}\n\n{format_schedule(run)}"
            return check
        # the schedule is fine; count what makes it interesting, so that a test can rule out trivial runs:
        # the validation of some transaction found a conflict:
        if any(record.aborted_at_commit for record in run.records):
            check.validation_aborts += 1
        # concurrent writers both committed, i.e. the validation let them through:
        if overlapping_committed_writers(run.records):
            check.overlapping_committed_writers += 1
        # a validation had to take two commits into account:
        if two_commits_during_writer(run.records):
            check.two_commits_during_writer += 1
    # every schedule passed:
    return check
