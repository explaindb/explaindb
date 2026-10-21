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

"""Scenarios for the MVCC playground: classic schedules that show how the store prevents (or allows) anomalies.

The anomaly names lost update, write skew, phantom insert and concurrent delete follow the tests in
``system/tests/stores/test_store_anomalies.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from system.playground.schedules import (
    DataOperation,
    Operation,
    Row,
    Schedule,
    ScheduledOperation,
    StoredObject,
)


@dataclass(frozen=True)
class Scenario:
    """A schedule to try, with its initial objects and what it shows."""

    name: str
    description: str
    initial_state: tuple[StoredObject, ...]
    schedule: Schedule


def schedule_of(*operations: tuple[int, Operation]) -> Schedule:
    """Returns the schedule of ``operations``, in execution order, each given with the number of its transaction.

    @param operations: e.g. ``(2, DataOperation("delete", "x"))`` for ``T2: delete x``
    """
    # T1 is the transaction with index 0:
    return tuple(
        ScheduledOperation(number - 1, operation) for number, operation in operations
    )


def make_scenario(
    name: str,
    description: str,
    initial_objects: dict[str, Row],
    operations: list[tuple[int, Operation]],
) -> Scenario:
    """Builds a scenario from its initial objects and its operations (see :func:`schedule_of`)."""
    return Scenario(
        name,
        description,
        tuple(
            StoredObject(object_id, row) for object_id, row in initial_objects.items()
        ),
        schedule_of(*operations),
    )


# the scenarios, each with the objects it starts from and its schedule; how each one ends in each mode is pinned in
# system/tests/playground/test_mvcc_playground.py:
SCENARIOS: tuple[Scenario, ...] = (
    make_scenario(
        "serial",
        "T2 begins after T1 committed, so it sees T1's write: nothing can go wrong.",
        {"x": Row(1, 0)},
        [
            (1, "begin"),
            (1, DataOperation("read", a_equals=1)),
            (1, DataOperation("update", "y", Row(1, 0))),
            (1, "commit"),
            (2, "begin"),
            (2, DataOperation("read", a_equals=1)),
            (2, DataOperation("delete", "x")),
            (2, "commit"),
        ],
    ),
    make_scenario(
        "lost update",
        "Both transactions read x, T1 writes it and commits, then T2 overwrites it based on the old value.",
        {"x": Row(1, 0)},
        [
            (1, "begin"),
            (2, "begin"),
            (1, DataOperation("read")),
            (2, DataOperation("read")),
            (1, DataOperation("update", "x", Row(1, 1))),
            (1, "commit"),
            (2, DataOperation("update", "x", Row(1, 2))),
            (2, "commit"),
        ],
    ),
    make_scenario(
        "write skew",
        "Both transactions read x and y; each then updates a different one, based on what it read.",
        {"x": Row(1, 0), "y": Row(2, 0)},
        [
            (1, "begin"),
            (2, "begin"),
            (1, DataOperation("read", a_equals=1)),
            (1, DataOperation("read", a_equals=2)),
            (2, DataOperation("read", a_equals=1)),
            (2, DataOperation("read", a_equals=2)),
            (1, DataOperation("update", "x", Row(1, 100))),
            (2, DataOperation("update", "y", Row(2, 200))),
            (1, "commit"),
            (2, "commit"),
        ],
    ),
    make_scenario(
        "write skew via phantom (insert and delete)",
        "Each transaction writes into what the other one read, through the predicate a==1: T1 inserts y into it, "
        "T2 deletes x from it.",
        {"x": Row(1, 0)},
        [
            (1, "begin"),
            (2, "begin"),
            (1, DataOperation("read", a_equals=1)),
            (2, DataOperation("read", a_equals=1)),
            (1, DataOperation("update", "y", Row(1, 0))),
            (2, DataOperation("delete", "x")),
            (1, "commit"),
            (2, "commit"),
        ],
    ),
    make_scenario(
        "phantom insert",
        "T2 inserts y into what T1 read (a phantom) and commits before T1 commits.",
        {"x": Row(1, 0), "z": Row(0, 0)},
        [
            (1, "begin"),
            (1, DataOperation("read", a_equals=1)),
            (2, "begin"),
            (2, DataOperation("update", "y", Row(1, 0))),
            (2, "commit"),
            (1, DataOperation("update", "z", Row(0, 1))),
            (1, "commit"),
        ],
    ),
    make_scenario(
        "concurrent delete",
        "T2 deletes x, which T1 read, and commits before T1 commits.",
        {"x": Row(1, 0), "z": Row(0, 0)},
        [
            (1, "begin"),
            (2, "begin"),
            (1, DataOperation("read", a_equals=1)),
            (2, DataOperation("delete", "x")),
            (2, "commit"),
            (1, DataOperation("update", "z", Row(0, 1))),
            (1, "commit"),
        ],
    ),
    make_scenario(
        "blind write",
        "T1 and T2 begin; T2 updates x and commits; then T1 updates x without reading it (a blind write). Committing "
        "both gives the same result as running T2, then T1, yet snapshot isolation aborts T1 at its write, as x "
        "changed after T1 began.",
        {"x": Row(1, 0)},
        [
            (1, "begin"),
            (2, "begin"),
            (2, DataOperation("update", "x", Row(1, 2))),
            (2, "commit"),
            (1, DataOperation("update", "x", Row(1, 1))),
            (1, "commit"),
        ],
    ),
    make_scenario(
        "read-only transaction",
        "T1 only reads; it sees the snapshot of its begin, although T2 commits a change before T1 reads.",
        {"x": Row(1, 0)},
        [
            (1, "begin"),
            (2, "begin"),
            (2, DataOperation("update", "x", Row(0, 0))),
            (2, "commit"),
            (1, DataOperation("read", a_equals=1)),
            (1, "commit"),
        ],
    ),
    make_scenario(
        "read-only anomaly (Fekete et al.)",
        "Checking account x and savings account y, the account number in a (1 and 2) and the balance in b: T1 reads "
        "only y and deposits 20 into it; T2 reads both, withdraws 10 from x and pays a fee of 1, as it saw no "
        "deposit (x's balance becomes -11); the read-only T3 sees the deposit but not the withdrawal.",
        {"x": Row(1, 0), "y": Row(2, 0)},
        [
            (2, "begin"),
            (2, DataOperation("read")),
            (1, "begin"),
            (1, DataOperation("read", a_equals=2)),
            (1, DataOperation("update", "y", Row(2, 20))),
            (1, "commit"),
            (3, "begin"),
            (3, DataOperation("read")),
            (3, "commit"),
            (2, DataOperation("update", "x", Row(1, -11))),
            (2, "commit"),
        ],
    ),
)
