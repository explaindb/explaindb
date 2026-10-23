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

"""A playground for schedules on the MVCC store: run them operation by operation, show the store, judge the outcome.

The model runs a schedule (see :mod:`system.playground.schedules`) on the real store and shows, after any operation,
the versions in the store and, for each transaction, its snapshot plus its own writes, what it read and what it wrote.
"""

# The model reads the store's internals (versions, snapshots) on purpose, to show them.
# pylint: disable=protected-access

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast

from system.playground.schedules import (
    DataOperation,
    Difference,
    LogLine,
    Operation,
    ReadResult,
    Row,
    Schedule,
    ScheduleRun,
    StoredObject,
    TransactionRecord,
    first_difference,
    format_read_result,
    run_schedule,
    serial_order,
)
from system.query_processing.predicates import WHERE_Clause
from system.stores.MVCC import TransactionalKeyValueStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore

# how the store decides which transactions to abort, ordered from the mode that prevents the most anomalies to the
# one that prevents the fewest:
Mode = Literal["method 1", "method 2", "snapshot isolation", "no validation"]
# where a transaction is in its life:
Status = Literal["not begun", "running", "committed", "aborted"]
MODES: tuple[Mode, ...] = (
    "method 1",
    "method 2",
    "snapshot isolation",
    "no validation",
)
# the verdict shows the differences of at most this many serial orders (all of them for up to 3 transactions):
MAX_ORDER_LINES: int = 6


class StoreWithoutValidation(TransactionalKeyValueStore):
    """A store that never validates, so anomalies such as write skew happen.

    Each transaction reads the snapshot of its begin plus its own writes. A write is stopped only while another
    transaction holds an uncommitted version of the same object (see :meth:`TransactionalKeyValueStore.update_object`).
    This is weaker than snapshot isolation (the mode "snapshot isolation"), which also stops a write to an object that
    another transaction committed after the writer's begin::

        T1                          T2
        begin
                                    begin
        read x
                                    read x
        update x
        commit
                                    update x -> passes here, aborts under snapshot isolation
                                    commit   -> T1's update is lost

    Write skew happens under both, as the two transactions write different objects.
    """

    def _validate_transaction(
        self, TA_id: int, commit_timestamp_for_this_TA: int
    ) -> bool:
        """See :meth:`TransactionalKeyValueStore._validate_transaction`.

        Always passes, so no conflict is ever detected.
        """
        return True


def make_store(mode: Mode) -> TransactionalKeyValueStore:
    """Returns an empty store that decides which transactions to abort according to ``mode``.

    @param mode: one of :data:`MODES`
    @return: a serializable store with validation method 1 or 2, a store with the isolation level snapshot isolation,
        or a :class:`StoreWithoutValidation`
    """
    if mode == "no validation":
        return StoreWithoutValidation()
    if mode == "snapshot isolation":
        return TransactionalKeyValueStore(isolation_level="snapshot isolation")
    return TransactionalKeyValueStore(use_brute_force_validation=mode == "method 1")


# ---------------------------------------------------------------------------------------------------------------
# the state after some operations


@dataclass(frozen=True)
class Version:
    """A committed version of an object: its commit timestamp, its value (None for a delete marker) and who wrote it
    (a transaction's name, or "initial" for an object in the store before the first transaction).
    """

    commit_timestamp: int
    row: Row | None
    writer: str

    def __str__(self) -> str:
        """Shows the version with its commit timestamp (the start of its validity in the store), its value and its
        writer, e.g. ``ts 3: (a=1, b=1) T1`` or ``ts 4: deleted T2``; an initial object has no writer:
        ``ts 0: (a=1, b=0)``.
        """
        value: str = "deleted" if self.row is None else str(self.row)
        writer: str = "" if self.writer == "initial" else f" {self.writer}"
        return f"ts {self.commit_timestamp}: {value}{writer}"


@dataclass(frozen=True)
class WorkInProgress:
    """The work-in-progress version of an object: the transaction id of its writer, which the store keeps as the
    start of its validity until the commit, the value (None for a delete) and the transaction writing it.
    """

    TA_id: int
    row: Row | None
    owner: str

    def __str__(self) -> str:
        """Shows the version with its writer's transaction id and its writer, e.g. ``ts 2: deleted T2``."""
        return f"ts {self.TA_id}: {'deleted' if self.row is None else self.row} {self.owner}"


@dataclass(frozen=True)
class ObjectState:
    """The versions of one object in the store."""

    object_id: str
    committed: tuple[Version, ...]
    # the version a running transaction is writing, None if there is none:
    work_in_progress: WorkInProgress | None = None


@dataclass(frozen=True)
class Checksum:
    """Validation method 1's check of one read: the checksum of its result when it ran, and the checksum the same read
    gives if the transaction commits now (None once the transaction has committed). They differ if a transaction
    that committed meanwhile changed what the read returns; then the transaction aborts at its commit, unless it
    wrote nothing (the store does not validate such a transaction).
    """

    clause: str
    at_read: str
    now: str | None


@dataclass(frozen=True)
class TransactionState:
    """What one transaction did so far and what it sees."""

    name: str
    # the transaction id the store gave it at its begin, None before its begin:
    TA_id: int | None
    status: Status
    # what a read of all objects returns for the transaction (its snapshot plus its own writes); empty unless running:
    sees: tuple[StoredObject, ...]
    # the where clauses of its reads, e.g. a==1 or all, and the ids of the objects it wrote, each once and sorted
    # (an aborted transaction keeps them, so that one can see what it did):
    read_clauses: tuple[str, ...]
    write_set: tuple[str, ...]
    # validation method 1 only, one per where clause: empty in the other modes and once aborted (the store forgets
    # an aborted transaction):
    checksums: tuple[Checksum, ...] = ()


@dataclass(frozen=True)
class Verdict:
    """The judgement of a run, as a kind and as a sentence: pending, error, nothing committed, or whether the
    committed transactions behaved like some serial order.
    """

    kind: Literal[
        "pending",
        "error",
        "nothing committed",
        "serializable",
        "serializable in another order",
        "not serializable",
    ]
    # the verdict in one sentence:
    text: str
    # unless the order of the serialization points matches: one line per serial order replayed, with its first
    # difference or that it matches (at most MAX_ORDER_LINES differences, then a line that counts the others); the
    # first line is the one of the order of the serialization points:
    details: tuple[str, ...] = ()
    # the position in the schedule of the read that returns something else in the order of the serialization points,
    # to mark it in the schedule (details[0] says what it would return there); None if no read differs there:
    marked_position: int | None = None
    # what the marked read would return in the order of the serialization points, shown next to it in the schedule:
    marked_explanation: str | None = None


@dataclass(frozen=True)
class RunState:
    """The state after running the first operations of a schedule."""

    objects: tuple[ObjectState, ...]
    transactions: tuple[TransactionState, ...]
    # the schedule table's lines, one per operation run (also a skipped one and, after an error, the one that failed):
    log: tuple[LogLine, ...]
    verdict: Verdict
    # why an operation went wrong, by its position in the schedule: why the store aborted a transaction there, or
    # what the marked read would return in the order of the serialization points (see Verdict.marked_position):
    explanations: dict[int, str]


def object_states(
    store: TransactionalKeyValueStore, names: dict[int, str], writers: dict[int, str]
) -> tuple[ObjectState, ...]:
    """Returns the versions of every object in the store, sorted by object id.

    @param names: the names of the transactions (T1, T2, ...) by their transaction id
    @param writers: the names of the committed transactions by their commit timestamp
    """
    states: list[ObjectState] = []
    # sorted, so that the objects appear in the same order in every run:
    for object_id in sorted(store.key_value_store.keys()):
        entry: VersionedKeyValueStore.KVStoreEntry = store.key_value_store[object_id]
        # the committed versions in commit order; a committed version starts at its commit timestamp (0 for an
        # initial object), and a delete marker has no value:
        committed: tuple[Version, ...] = tuple(
            Version(
                version.start_validity,
                (
                    None
                    if isinstance(version, VersionedKeyValueStore.DeleteEntry)
                    else version.value
                ),
                # the initial objects are put at timestamp 0, before any transaction:
                writers.get(version.start_validity, "initial"),
            )
            for version in entry.committed
        )
        wip: VersionedKeyValueStore.VersionEntry | None = entry.wip
        work_in_progress: WorkInProgress | None = None
        if wip is not None:
            # a work-in-progress version carries the transaction id of its writer as its start:
            work_in_progress = WorkInProgress(
                wip.start_validity,
                (
                    wip.value
                    if isinstance(wip, VersionedKeyValueStore.UpdateEntry)
                    else None
                ),
                names[wip.start_validity],
            )
        states.append(ObjectState(object_id, committed, work_in_progress))
    return tuple(states)


def format_where(a_equals: int | None) -> str:
    """Writes a read's where clause as the transactions' read clauses show it: ``all`` or e.g. ``a==1``.

    @param a_equals: the constant the read compares a with, None for a read of all objects
    """
    return "all" if a_equals is None else f"a=={a_equals}"


def checksums(
    store: TransactionalKeyValueStore,
    TA_id: int,
    status: Status,
) -> tuple[Checksum, ...]:
    """Returns validation method 1's checksums of the reads of transaction ``TA_id``, sorted by where clause.

    @param status: the transaction's status; only a running one gets the checksum it would get now
    @return: empty in the other modes and for an aborted transaction
    """
    # the store keeps a transaction's read set until it aborts; only method 1 computes checksums:
    entry: TransactionalKeyValueStore.TDEntry | None = store.TD.get(TA_id)
    if entry is None or not store.use_brute_force_validation:
        return ()
    found: set[Checksum] = set()
    for read_clause in entry.read_clauses:
        now: str | None = None
        if status == "running":
            # the read again on the state a commit now would validate against: the next value of the store's counter
            # becomes the commit timestamp (as in TransactionalKeyValueStore.commit_transaction); [1]: the checksum:
            now = store._read_snapshot(store.TA_id, read_clause["where_clause"])[1]
        # a read that ran twice is in the read set twice, with the same checksum; the set keeps it once:
        found.add(
            Checksum(
                # the playground's reads compare a with a constant (see execute_operation):
                format_where(
                    None
                    if read_clause["where_clause"] is None
                    else cast(int, read_clause["where_clause"].constant)
                ),
                read_clause["checksum"],
                now,
            )
        )
    return tuple(sorted(found, key=lambda checksum: checksum.clause))


def transaction_states(
    store: TransactionalKeyValueStore, records: list[TransactionRecord]
) -> tuple[TransactionState, ...]:
    """Returns the state of every transaction of the schedule."""
    states: list[TransactionState] = []
    for record in records:
        # a transaction that has not begun has no transaction id and nothing to show yet:
        if record.TA_id is None:
            states.append(TransactionState(record.name, None, "not begun", (), (), ()))
            continue
        status: Status
        if record.committed:
            status = "committed"
        elif record.aborted:
            status = "aborted"
        else:
            status = "running"
        # the record keeps every read and every write that ran, also after an abort (a write the store refused
        # did not run and is not in it); a read that ran twice is listed once:
        read_clauses: tuple[str, ...] = tuple(
            sorted(
                {
                    format_where(done.data_operation.a_equals)
                    for done in record.data_operations
                    if done.data_operation.kind == "read"
                }
            )
        )
        write_set: tuple[str, ...] = tuple(
            sorted(
                {
                    done.data_operation.key
                    for done in record.data_operations
                    if done.data_operation.kind != "read"
                }
            )
        )
        sees: tuple[StoredObject, ...] = ()
        if status == "running":
            # what a read of all objects returns ([0]: the (object_id, object)-pairs, without the checksum); unlike
            # the store's read_objects, this does not add a read to the transaction's read set:
            sees = tuple(
                StoredObject(object_id, row)
                for object_id, row in sorted(store._read_snapshot(record.TA_id)[0])
            )
        states.append(
            TransactionState(
                record.name,
                record.TA_id,
                status,
                sees,
                read_clauses,
                write_set,
                checksums(store, record.TA_id, status),
            )
        )
    return tuple(states)


# ---------------------------------------------------------------------------------------------------------------
# judging


def order_names(order: Sequence[TransactionRecord]) -> str:
    """Returns a serial order as the verdict writes it, e.g. ``T1|T3|T2``."""
    return "|".join(record.name for record in order)


def order_line(
    order: Sequence[TransactionRecord], difference: Difference | None
) -> str:
    """Returns the line of the verdict for one serial order.

    E.g. ``Order T1|T2: T2's read a==1 would return {x: (a=1, b=100)}, but returned {x: (a=1, b=0)}.``

    @param order: the committed transactions in the order they were replayed
    @param difference: the first difference of the replay in this order, None if it matches
    @return: the line, a sentence
    """
    names: str = order_names(order)
    if difference is None:
        return f"Order {names}: same read results and final state."
    if difference.read is None:
        return (
            f"Order {names}: the final state would be {format_read_result(difference.serial)}, "
            f"but is {format_read_result(difference.observed)}."
        )
    return (
        f"Order {names}: {difference.transaction}'s {difference.read} would return "
        f"{format_read_result(difference.serial)}, but returned {format_read_result(difference.observed)}."
    )


def more_orders(lines: list[str], differing_orders: int) -> list[str]:
    """Returns the lines of the orders that differ, followed by a line that counts the orders not shown, if any,
    e.g. ``… and 18 more orders that differ.``

    @param lines: the lines of the first orders that differ, at most :data:`MAX_ORDER_LINES`
    @param differing_orders: how many orders differ in all
    @return: the lines, and the counting line if some orders are not shown
    """
    hidden: int = differing_orders - len(lines)
    if hidden == 0:
        return lines
    return lines + [
        (
            "… and 1 more order that differs."
            if hidden == 1
            else f"… and {hidden} more orders that differ."
        )
    ]


def serializability_verdict(
    initial_state: dict[str, Row],
    records: list[TransactionRecord],
    final_state: dict[str, Row],
) -> Verdict:
    """Judges whether the committed transactions behaved like some serial order.

    Compares the read results and the final state with a serial replay, first in the order of the serialization
    points (the commit timestamp of a transaction that wrote, the begin of a read-only one), then in every other
    order of the committed transactions (n! orders for n committed transactions), until one matches.

    @param initial_state: the objects before the first operation
    @param records: what each transaction did in the run, every one of them committed or aborted
    @param final_state: the committed objects after the run
    @return: the verdict; unless the order of the serialization points matches, with one line per order replayed
        and, if a read differs in the order of the serialization points, its position in the schedule (also when
        another order matches)
    """
    # the committed transactions in the order of their serialization points (aborted ones had no effect):
    committed: list[TransactionRecord] = serial_order(records)
    if not committed:
        return Verdict("nothing committed", "Nothing committed.")
    # first the order of the serialization points, the order validation methods 1 and 2 aim for:
    difference: Difference | None = first_difference(
        initial_state, records, final_state
    )
    if difference is None:
        return Verdict(
            "serializable",
            "Serializable: same read results and final state as the serial order "
            f"{order_names(committed)}.",
        )
    marked_position: int | None = difference.position
    marked_explanation: str | None = (
        None
        if difference.read is None
        else f"in the order {order_names(committed)} this read would return "
        f"{format_read_result(difference.serial)}"
    )
    # the lines of the orders that differ, starting with the order of the serialization points:
    lines: list[str] = [order_line(committed, difference)]
    differing_orders: int = 1
    # otherwise the schedule may still be serializable in some other order:
    for order in itertools.permutations(committed):
        # the order of the serialization points was already replayed above:
        if list(order) == committed:
            continue
        difference = first_difference(initial_state, records, final_state, list(order))
        if difference is None:
            return Verdict(
                "serializable in another order",
                "Serializable, but not in the order of the serialization points.",
                tuple(more_orders(lines, differing_orders) + [order_line(order, None)]),
                marked_position,
                marked_explanation,
            )
        differing_orders += 1
        if len(lines) < MAX_ORDER_LINES:
            lines.append(order_line(order, difference))
    # no serial order explains what the transactions read and what the store holds at the end:
    return Verdict(
        "not serializable",
        "Not serializable: no serial order gives the same read results and final state.",
        tuple(more_orders(lines, differing_orders)),
        marked_position,
        marked_explanation,
    )


# ---------------------------------------------------------------------------------------------------------------
# running


def fresh_store(
    mode: Mode, initial_state: tuple[StoredObject, ...]
) -> TransactionalKeyValueStore:
    """Returns a new store for ``mode`` that holds the initial objects as committed versions with timestamp 0."""
    store: TransactionalKeyValueStore = make_store(mode)
    # put writes the initial objects as committed versions with timestamp 0, before any transaction:
    for stored in initial_state:
        store.put(stored.object_id, stored.row)
    return store


def returned_by(where: WHERE_Clause | None, row: Row | None) -> bool:
    """Returns True if a read with the where clause ``where`` (None: all objects) returns the object ``row`` (None: the
    object does not exist), as in validation method 2 of the store."""
    return row is not None and (where is None or where.evaluate(row))


def snapshot_read(
    store: TransactionalKeyValueStore, timestamp: int, where: WHERE_Clause | None
) -> ReadResult:
    """Returns what a read with ``where`` returns from the committed versions visible at ``timestamp``, without any
    work-in-progress version, sorted by object id."""
    # [0]: the (object_id, object)-pairs, without the checksum:
    pairs: list[tuple[str, Row]] = store._read_snapshot(
        timestamp, where, ignore_wip=True
    )[0]
    return tuple(
        sorted(
            (StoredObject(object_id, row) for object_id, row in pairs),
            key=lambda stored: stored.object_id,
        )
    )


def newest_writer(store: TransactionalKeyValueStore, run: ScheduleRun, key: str) -> str:
    """Returns the name of the transaction that wrote the newest committed version of object ``key``.

    @param store: the store the schedule ran on
    @param run: the run of the schedule, with a record per transaction
    @param key: an object whose newest committed version was written by a transaction of the schedule
    @return: the name of the transaction whose commit timestamp is the start of that version
    """
    return next(
        other.name
        for other in run.records
        if other.commit_timestamp
        == store.key_value_store[key].committed[-1].start_validity
    )


def abort_explanation(
    schedule: Schedule,
    initial_state: tuple[StoredObject, ...],
    mode: Mode,
    position: int,
) -> str:
    """Explains why the store aborted the transaction of the operation at ``position`` of ``schedule``.

    The schedule runs again up to just before that operation; then the store's state is checked the way the store
    decided: a write fails while another transaction holds an uncommitted version of the object, and under snapshot
    isolation also if another transaction committed the object after this one began; a commit fails if the
    validation finds that a read changed (method 1: the read run again at the commit timestamp returns something
    different from what it returns in the snapshot of the transaction's begin; method 2: another transaction that
    committed after this one began changed an object the read returns in that snapshot or returns now). Like the
    store, both commit checks leave out the transaction's own writes.

    @param schedule: the schedule, as for :func:`run_to`
    @param initial_state: the objects in the store before the first operation
    @param mode: how the store decides which transactions to abort
    @param position: the position of an operation at which the store aborted its transaction
    @return: e.g. ``T1 is writing x and has not committed yet``, ``snapshot isolation: T1 changed x and committed
        after T2 began`` or ``validation: read a==1 now returns {}, but in the snapshot of T2's begin it returns
        {x: (a=1, b=0)}``
    """
    store: TransactionalKeyValueStore = fresh_store(mode, initial_state)
    run: ScheduleRun = run_schedule(store, schedule, position)
    transaction_index: int = schedule[position].transaction_index
    operation: Operation = schedule[position].operation
    record: TransactionRecord = run.records[transaction_index]
    assert record.TA_id is not None
    if operation != "commit":
        # an update or a delete; the store checks for another transaction's work-in-progress version first:
        key: str = cast(DataOperation, operation).key
        # (an insert of a new key has no entry in the store yet):
        wip: VersionedKeyValueStore.VersionEntry | None = (
            store.key_value_store[key].wip if key in store.key_value_store else None
        )
        if wip is not None and wip.start_validity != record.TA_id:
            writer: str = next(
                other.name for other in run.records if other.TA_id == wip.start_validity
            )
            return f"{writer} is writing {key} and has not committed yet"
        # then, under snapshot isolation only, for a version of the object that another transaction committed after
        # this one began:
        if (
            store.isolation_level == "snapshot isolation"
            and store._committed_after_begin(key, record.TA_id)
        ):
            return (
                f"snapshot isolation: {newest_writer(store, run, key)} changed {key} and committed after "
                f"{record.name} began"
            )
        # the store aborted the write, so one of the two checks above, which follow the store's, found the reason:
        raise AssertionError(f"no reason found for the abort at position {position}")
    # the commit timestamp the commit gets: the next value of the store's counter (see commit_transaction):
    commit_timestamp: int = store.TA_id
    # the objects written by the transactions that committed after the transaction began (method 2 checks them):
    written_meanwhile: list[str] = sorted(
        {
            written.data_operation.key
            for other in run.records
            if other.commit_timestamp is not None
            and other.commit_timestamp > record.TA_id
            for written in other.data_operations
            if written.data_operation.kind != "read"
        }
    )
    for executed in record.data_operations:
        read: DataOperation = executed.data_operation
        if read.kind != "read":
            continue
        where: WHERE_Clause | None = (
            None if read.a_equals is None else WHERE_Clause("a", "==", read.a_equals)
        )
        if store.use_brute_force_validation:
            # method 1 compares the read's result in the committed snapshot of the begin (without the transaction's
            # own writes, as the checksum at the read) with its result at the commit timestamp:
            in_snapshot: ReadResult = snapshot_read(store, record.TA_id, where)
            now: ReadResult = snapshot_read(store, commit_timestamp, where)
            if now != in_snapshot:
                return (
                    f"validation: {read} now returns {format_read_result(now)}, "
                    f"but in the snapshot of {record.name}'s begin it returns {format_read_result(in_snapshot)}"
                )
            continue
        # method 2 checks the objects written by the transactions that committed after the transaction began:
        for key in written_meanwhile:
            before: Row | None = store._get_visible_object_version(
                key, record.TA_id, ignore_wip=True
            )
            after: Row | None = store._get_visible_object_version(
                key, commit_timestamp, ignore_wip=True
            )
            if before == after:
                continue
            writer = newest_writer(store, run, key)
            if returned_by(where, before):
                return (
                    f"validation: {writer} wrote {key} and committed after {record.name} began, and "
                    f"{record.name}'s {read} returned {key} (without {record.name}'s own writes)"
                )
            if returned_by(where, after):
                return (
                    f"validation: {writer} wrote {key} and committed after {record.name} began, and "
                    f"{record.name}'s {read} would now return {key} (without {record.name}'s own writes)"
                )
    # the store aborted the commit, so one of the checks above, which follow the store's validation, found the reason:
    raise AssertionError(f"no reason found for the abort at position {position}")


def run_to(
    schedule: Schedule,
    initial_state: tuple[StoredObject, ...],
    mode: Mode,
    operation_count: int,
) -> RunState:
    """Runs the first ``operation_count`` operations of ``schedule`` on a fresh store and returns the state after them.

    The state after any operation is found by running the schedule again from its start, as the store cannot return
    to an earlier state; runs are deterministic, so this gives the same state every time.

    @param schedule: a well-formed schedule (not checked): transactions T1, T2, ... without gaps, each of which
        begins before its other operations and runs nothing after its commit or abort; with n transactions, the
        verdict may replay n! orders
    @param initial_state: the objects in the store before the first operation, each object id once
    @param mode: how the store decides which transactions to abort
    @param operation_count: how many operations to run, from 0; a larger number runs the whole schedule
    @return: the state after the operations, with the verdict ("pending" until every transaction has ended, "error"
        if the store raised an error other than an abort, e.g. a KeyError for a delete of an object it does not have)
    """
    store: TransactionalKeyValueStore = fresh_store(mode, initial_state)
    run: ScheduleRun = run_schedule(store, schedule, operation_count)
    # the verdict is only meaningful once every transaction has ended; an empty schedule stays pending:
    verdict: Verdict = Verdict("pending", "Pending: not every transaction has ended.")
    if run.error is not None:
        # TODO(#53): revisit once deleting an object that is not visible raises KeyError (see TODO.md)
        verdict = Verdict("error", f"The run stopped: {run.error}.")
    elif run.records and all(
        record.committed or record.aborted for record in run.records
    ):
        verdict = serializability_verdict(
            {stored.object_id: stored.row for stored in initial_state},
            run.records,
            run.final_state,
        )
    # the names of the transactions by the id the store gave them and by their commit timestamp, to name the writer
    # of a work-in-progress and of a committed version:
    names: dict[int, str] = {
        record.TA_id: record.name for record in run.records if record.TA_id is not None
    }
    writers: dict[int, str] = {
        record.commit_timestamp: record.name
        for record in run.records
        if record.commit_timestamp is not None
    }
    # why the store aborted a transaction, at each such operation (the log marks them, see run_schedule), and what
    # the marked read would return in the order of the serialization points:
    explanations: dict[int, str] = {
        position: abort_explanation(schedule, initial_state, mode, position)
        for position, line in enumerate(run.log)
        if line.text.endswith(": aborted")
    }
    if verdict.marked_position is not None and verdict.marked_explanation is not None:
        explanations[verdict.marked_position] = verdict.marked_explanation
    return RunState(
        objects=object_states(store, names, writers),
        transactions=transaction_states(store, run.records),
        log=tuple(run.log),
        verdict=verdict,
        explanations=explanations,
    )
