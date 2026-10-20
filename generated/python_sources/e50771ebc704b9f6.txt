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

"""Benchmark workloads of the MVCC store in Python; their Rust twin is generated/rust/examples/benchmarks/workloads.rs.

Both implement the same workloads on the same data, with the same names and parameters, and print the same CSV
line per repetition, so that the runner (:mod:`system.benchmarks.run`) can compare them. The Rust twin builds its
stores with ``TransactionalKeyValueStore::with_validation`` where this module calls :func:`new_store`, and writes
its where clauses with a small helper ``clause``.
"""

from __future__ import annotations

import argparse
import gc
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from system.query_processing.predicates import WHERE_Clause
from system.stores.MVCC import TransactionAbortedException, TransactionalKeyValueStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore

# number of read_objects calls timed by the micro-benchmark `read`:
READS: int = 100
# number of transactions of the micro-benchmark `update_commit` and of the transactions-per-second workloads:
TRANSACTIONS: int = 1_000
# a repetition repeats whole passes until their timed parts add up to at least this many seconds:
MIN_SECONDS: float = 0.05


@dataclass(frozen=True)
class Stuff:
    """A benchmark object with two integer attributes (Rust: `Stuff` in
    generated/rust/examples/benchmarks/workloads.rs)."""

    a: int
    b: int


@dataclass(frozen=True)
class Fingerprint:
    """What a pass did; Python and Rust must report the same fingerprint for the same workload."""

    # committed transactions:
    commits: int
    # aborted transactions:
    aborts: int
    # objects returned by all reads (read_objects and get):
    objects_read: int
    # the store's transaction counter after the pass (the next id it would hand out):
    transaction_counter: int
    # committed versions of all objects in the store after the pass, delete markers included:
    committed_versions: int
    # sum over the objects in store order of (position + 1) * b of their most recent committed version, so that it
    # also shows which objects were updated:
    weighted_sum_of_b: int


@dataclass(frozen=True)
class Pass:
    """One run of a workload on a fresh store."""

    # the seconds of the timed part:
    seconds: float
    # the operations in the timed part:
    operations: int
    # what the pass did:
    fingerprint: Fingerprint


@dataclass(frozen=True)
class Repetition:
    """One repetition: passes repeated until at least `MIN_SECONDS` of timed work."""

    # timed seconds of all passes divided by their timed operations:
    seconds_per_operation: float
    # the number of passes run:
    passes: int
    # the fingerprint, the same for every pass:
    fingerprint: Fingerprint


def fake_data(number_of_objects: int) -> list[tuple[str, Stuff]]:
    """Returns the objects ("0", Stuff), ("1", Stuff), ... of a store of the given size; the same formula as
    generated/rust/tests/common and generated/rust/examples, so both languages load the same data. Attribute a is
    unique for up to 1001 objects."""
    return [
        (str(i), Stuff(a=(i * 37) % 1001, b=(i * 53) % 2001))
        for i in range(number_of_objects)
    ]


def new_store(use_brute_force_validation: bool) -> TransactionalKeyValueStore:
    """Returns an empty transactional store with validation method 1 (brute force) or 2."""
    return TransactionalKeyValueStore(
        use_brute_force_validation=use_brute_force_validation
    )


def filled_store(
    number_of_objects: int, use_brute_force_validation: bool
) -> TransactionalKeyValueStore:
    """Returns a store holding the objects of `fake_data(number_of_objects)`."""
    store: TransactionalKeyValueStore = new_store(use_brute_force_validation)
    store.bulkload(iter(fake_data(number_of_objects)))
    return store


def fingerprint(
    store: TransactionalKeyValueStore, commits: int, aborts: int, objects_read: int
) -> Fingerprint:
    """Returns the fingerprint of a pass from the counts of the workload and the state of `store`."""
    committed_versions: int = 0
    weighted_sum_of_b: int = 0
    for position, entry in enumerate(store.key_value_store.values()):
        committed_versions += len(entry.committed)
        if entry.committed and isinstance(
            entry.committed[-1], VersionedKeyValueStore.UpdateEntry
        ):
            weighted_sum_of_b += (position + 1) * entry.committed[-1].value.b
    return Fingerprint(
        commits=commits,
        aborts=aborts,
        objects_read=objects_read,
        transaction_counter=store.TA_id,
        committed_versions=committed_versions,
        weighted_sum_of_b=weighted_sum_of_b,
    )


def bulkload(
    number_of_objects: int, use_brute_force_validation: bool, _operations: int
) -> Pass:
    """Times loading `number_of_objects` objects into an empty store; one operation per object."""
    data: list[tuple[str, Stuff]] = fake_data(number_of_objects)
    store: TransactionalKeyValueStore = new_store(use_brute_force_validation)
    start: int = time.perf_counter_ns()
    store.bulkload(iter(data))
    seconds: float = (time.perf_counter_ns() - start) / 1e9
    return Pass(seconds, number_of_objects, fingerprint(store, 0, 0, 0))


def get(
    number_of_objects: int, use_brute_force_validation: bool, _operations: int
) -> Pass:
    """Times one non-transactional `get` of every object of a filled store; one operation per get. Python's `get`
    returns a generator, so its cost is part of the measurement."""
    store: TransactionalKeyValueStore = filled_store(
        number_of_objects, use_brute_force_validation
    )
    ids: list[str] = [str(i) for i in range(number_of_objects)]
    start: int = time.perf_counter_ns()
    for object_id in ids:
        next(store.get(object_id))
    seconds: float = (time.perf_counter_ns() - start) / 1e9
    return Pass(seconds, number_of_objects, fingerprint(store, 0, 0, len(ids)))


def read(number_of_objects: int, use_brute_force_validation: bool, reads: int) -> Pass:
    """Times `reads` reads of `a == 42` in one transaction on a filled store, without keeping them in the read set;
    each read scans all objects. One operation per read."""
    store: TransactionalKeyValueStore = filled_store(
        number_of_objects, use_brute_force_validation
    )
    where_clause: WHERE_Clause = WHERE_Clause("a", "==", 42)
    ta_id: int = store.begin_transaction()
    objects_read: int = 0
    start: int = time.perf_counter_ns()
    for _ in range(reads):
        objects_read += len(
            store.read_objects(ta_id, where_clause, collect_read_clause=False)
        )
    seconds: float = (time.perf_counter_ns() - start) / 1e9
    store.commit_transaction(ta_id)
    return Pass(seconds, reads, fingerprint(store, 1, 0, objects_read))


def update_commit(
    number_of_objects: int, use_brute_force_validation: bool, transactions: int
) -> Pass:
    """Times `transactions` transactions on a filled store, each updating object `i mod number_of_objects` (b + 1)
    and committing; one operation per transaction."""
    data: list[tuple[str, Stuff]] = fake_data(number_of_objects)
    store: TransactionalKeyValueStore = filled_store(
        number_of_objects, use_brute_force_validation
    )
    # the current values, kept outside the store, so the transactions need no read:
    current: list[Stuff] = [value for _, value in data]
    start: int = time.perf_counter_ns()
    for i in range(transactions):
        index: int = i % number_of_objects
        ta_id: int = store.begin_transaction()
        updated: Stuff = Stuff(a=current[index].a, b=current[index].b + 1)
        store.update_object(str(index), updated, ta_id)
        store.commit_transaction(ta_id)
        current[index] = updated
    seconds: float = (time.perf_counter_ns() - start) / 1e9
    return Pass(seconds, transactions, fingerprint(store, transactions, 0, 0))


def read_only(
    number_of_objects: int, use_brute_force_validation: bool, transactions: int
) -> Pass:
    """Times `transactions` transactions on a filled store, each reading `a < 100` and committing; one operation
    per transaction."""
    store: TransactionalKeyValueStore = filled_store(
        number_of_objects, use_brute_force_validation
    )
    objects_read: int = 0
    start: int = time.perf_counter_ns()
    for _ in range(transactions):
        ta_id: int = store.begin_transaction()
        objects_read += len(store.read_objects(ta_id, WHERE_Clause("a", "<", 100)))
        store.commit_transaction(ta_id)
    seconds: float = (time.perf_counter_ns() - start) / 1e9
    return Pass(
        seconds, transactions, fingerprint(store, transactions, 0, objects_read)
    )


def read_write_disjoint(
    number_of_objects: int, use_brute_force_validation: bool, transactions: int
) -> Pass:
    """Times `transactions` transactions on a filled store, transaction i reading object `i mod number_of_objects`
    by its attribute a (unique for up to 1001 objects), updating it (b + 1) and committing; there are no
    conflicts. One operation per transaction."""
    data: list[tuple[str, Stuff]] = fake_data(number_of_objects)
    store: TransactionalKeyValueStore = filled_store(
        number_of_objects, use_brute_force_validation
    )
    objects_read: int = 0
    start: int = time.perf_counter_ns()
    for i in range(transactions):
        index: int = i % number_of_objects
        ta_id: int = store.begin_transaction()
        result: list[tuple[str, Stuff]] = store.read_objects(
            ta_id, WHERE_Clause("a", "==", data[index][1].a)
        )
        objects_read += len(result)
        object_id, value = result[0]
        store.update_object(object_id, Stuff(a=value.a, b=value.b + 1), ta_id)
        store.commit_transaction(ta_id)
    seconds: float = (time.perf_counter_ns() - start) / 1e9
    return Pass(
        seconds, transactions, fingerprint(store, transactions, 0, objects_read)
    )


def read_and_increment_b(
    store: TransactionalKeyValueStore, ta_id: int, object_id: str
) -> int:
    """Lets transaction `ta_id` read the hot set (a < 10) and update hot object `object_id` (b + 1); returns the
    number of objects read. Raises StopIteration if the read does not return `object_id`; the workloads only pass
    objects of the hot set."""
    result: list[tuple[str, Stuff]] = store.read_objects(
        ta_id, WHERE_Clause("a", "<", 10)
    )
    # search the result, as the Rust twin does:
    old: Stuff = next(value for oid, value in result if oid == object_id)
    store.update_object(object_id, Stuff(a=old.a, b=old.b + 1), ta_id)
    return len(result)


def read_write_contention(
    number_of_objects: int, use_brute_force_validation: bool, transactions: int
) -> Pass:
    """Times `transactions // 2` rounds of two interleaved transactions on a filled store; the second of each round
    fails validation, as the first changed an object it read.

    The hot set is the objects with a < 10. In round j::

        t1                                  t2
        begin
                                            begin
        read a < 10
        update hot object 2j (b + 1)
                                            read a < 10
                                            update hot object 2j + 1 (b + 1)
        commit
                                            commit -> aborted

    One operation per transaction (committed or aborted).

    Raises ValueError if the hot set has fewer than two objects.
    """
    store: TransactionalKeyValueStore = filled_store(
        number_of_objects, use_brute_force_validation
    )
    hot: list[str] = [
        object_id for object_id, value in fake_data(number_of_objects) if value.a < 10
    ]
    if len(hot) < 2:
        raise ValueError("the hot set needs at least two objects")
    commits: int = 0
    aborts: int = 0
    objects_read: int = 0
    start: int = time.perf_counter_ns()
    for j in range(transactions // 2):
        t1: int = store.begin_transaction()
        t2: int = store.begin_transaction()
        objects_read += read_and_increment_b(store, t1, hot[(2 * j) % len(hot)])
        objects_read += read_and_increment_b(store, t2, hot[(2 * j + 1) % len(hot)])
        for ta_id in (t1, t2):
            try:
                store.commit_transaction(ta_id)
                commits += 1
            except TransactionAbortedException:
                aborts += 1
    seconds: float = (time.perf_counter_ns() - start) / 1e9
    operations: int = 2 * (transactions // 2)
    return Pass(seconds, operations, fingerprint(store, commits, aborts, objects_read))


# a workload: (number of objects, use brute-force validation, operations) -> one pass; for bulkload and get, the
# operations are the objects, one per object, and the operations argument is not used:
Workload = Callable[[int, bool, int], Pass]

# the workloads by name, as the runner and the Rust twin name them:
WORKLOADS: dict[str, Workload] = {
    "bulkload": bulkload,
    "get": get,
    "read": read,
    "update_commit": update_commit,
    "read_only": read_only,
    "read_write_disjoint": read_write_disjoint,
    "read_write_contention": read_write_contention,
}


def repetition(
    workload: Workload,
    number_of_objects: int,
    use_brute_force_validation: bool,
    operations: int,
    min_seconds: float,
) -> Repetition:
    """Runs whole passes of `workload` (each on a fresh store) until their timed parts add up to `min_seconds`.

    The garbage collector runs once before the repetition and, as with `timeit`, is off while it runs.

    Raises RuntimeError if a pass times no operation (it could never add up to `min_seconds`), or if two passes
    report different fingerprints.
    """
    seconds: float = 0.0
    timed_operations: int = 0
    passes: int = 0
    first: Fingerprint | None = None
    gc.collect()
    gc.disable()
    try:
        while seconds < min_seconds or passes == 0:
            result: Pass = workload(
                number_of_objects, use_brute_force_validation, operations
            )
            if result.operations < 1:
                raise RuntimeError("a pass must time at least one operation")
            if first is None:
                first = result.fingerprint
            if result.fingerprint != first:
                raise RuntimeError("all passes must do the same work")
            seconds += result.seconds
            timed_operations += result.operations
            passes += 1
    finally:
        gc.enable()
    assert first is not None  # at least one pass ran
    return Repetition(seconds / timed_operations, passes, first)


def csv_line(result: Repetition) -> str:
    """Returns the CSV line of a repetition: seconds per operation, passes and the fingerprint fields in order."""
    fp: Fingerprint = result.fingerprint
    return (
        f"{result.seconds_per_operation!r},{result.passes},{fp.commits},{fp.aborts},{fp.objects_read},"
        f"{fp.transaction_counter},{fp.committed_versions},{fp.weighted_sum_of_b}"
    )


def positive(text: str) -> int:
    """Returns `text` as an integer of at least 1, written with ASCII digits only, as the Rust twin accepts it;
    raises argparse.ArgumentTypeError otherwise. Unlike this function, the Rust twin also rejects numbers above
    2^64 - 1.
    """
    if not (text.isascii() and text.isdigit()) or int(text) < 1:
        raise argparse.ArgumentTypeError(f"{text} is not a number of at least 1")
    return int(text)


def main(arguments: list[str], min_seconds: float = MIN_SECONDS) -> None:
    """Runs a workload and prints one CSV line per repetition after a warm-up repetition, as the Rust twin does;
    each repetition times at least `min_seconds`.

    Run as ``python -m system.benchmarks.workloads <workload> <method 1|2> <objects> <operations> <repetitions>``.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="python -m system.benchmarks.workloads",
        description="Runs one benchmark workload of the MVCC store.",
    )
    parser.add_argument("workload", choices=sorted(WORKLOADS))
    parser.add_argument("method", choices=["1", "2"], help="validation method")
    parser.add_argument("objects", type=positive, help="number of objects")
    parser.add_argument(
        "operations", type=positive, help="reads or transactions per pass"
    )
    parser.add_argument("repetitions", type=positive)
    options: argparse.Namespace = parser.parse_args(arguments)
    workload: Workload = WORKLOADS[options.workload]
    use_brute_force_validation: bool = options.method == "1"
    repetition(
        workload,
        options.objects,
        use_brute_force_validation,
        options.operations,
        min_seconds,
    )
    for _ in range(options.repetitions):
        print(
            csv_line(
                repetition(
                    workload,
                    options.objects,
                    use_brute_force_validation,
                    options.operations,
                    min_seconds,
                )
            )
        )


if __name__ == "__main__":
    main(sys.argv[1:])
