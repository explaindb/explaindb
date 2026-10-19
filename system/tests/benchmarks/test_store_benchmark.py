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

# This module exceeds pylint's 1000 lines, as it tests the workloads, the harness and the runner of the benchmarks.
# pylint: disable=too-many-lines
"""Tests for the store benchmarks: the fingerprints of the workloads, the repetition harness and the runner."""

import contextlib
import gc
import io
import itertools
import json
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from system.benchmarks import run, workloads
from system.benchmarks.run import Config, Measurement
from system.benchmarks.workloads import Fingerprint, Pass, Repetition, Workload

# The store data of fake_data(n): object i is at position i of the store and has a = (i * 37) % 1001 and
# b = (i * 53) % 2001. The last fingerprint field, weighted_sum_of_b, is the sum of (i + 1) * b_i over the objects.
# - For n = 10, b_i = 53 * i (53 * 9 < 2001), so the weighted sum is 53 * (0*1 + 1*2 + ... + 9*10)
#   = 53 * (285 + 45) = 53 * 330 = 17 490. a_i = 37 * i, so exactly the objects 0, 1, 2 (a = 0, 37, 74) have
#   a < 100, and no object has a == 42.
# - a == 42 holds for object 434 only (37 * 434 = 16058 = 16 * 1001 + 42), so a store needs 435 objects for `read`
#   to find something.
# - The hot set a < 10 of `read_write_contention` is the objects 0, 379, 406, 433, 460, 487, 893, 920, 947, 974
#   (37 * 379 = 14023 = 14 * 1001 + 9, ...); a store of 380 objects has the smallest hot set of two objects: 0 and 379,
#   a store of 1 000 objects has all ten.
# - For n = 380, 435 and 1 000, b wraps around 2001, so the weighted sums are only given by their definition,
#   sum((i + 1) * ((i * 53) % 2001) for i in range(n)).
# generated/rust/examples/benchmarks/workloads.rs asserts the same fingerprints for the same parameters.
WEIGHTED_SUM_OF_B_10: int = 17_490
WEIGHTED_SUM_OF_B_380: int = 74_321_305
WEIGHTED_SUM_OF_B_435: int = 93_888_631
WEIGHTED_SUM_OF_B_1000: int = 498_335_133

# reads or transactions of a pass in the tests on small stores; 20 transactions on 10 objects update each object
# twice, so the versions of an object pile up as in the real runs:
SMALL_OPERATIONS: int = 20
SMALL_READS: int = 10

# the fingerprint of update_commit on 10 objects with 20 transactions (read_write_disjoint differs only in the 20
# objects it reads): every object is updated twice (b + 2), which adds 2 * (1 + 2 + ... + 10) = 110 to the weighted
# sum; each transaction takes two ids (begin, commit), so the counter ends at 1 + 2 * 20 = 41:
UPDATED_TWICE_10: Fingerprint = Fingerprint(
    20, 0, 0, 41, 10 + 20, WEIGHTED_SUM_OF_B_10 + 110
)


def both_methods() -> tuple[bool, ...]:
    """Returns the two values of `use_brute_force_validation`: validation method 1 (True) and 2 (False)."""
    return (True, False)


class SmallStoreFingerprintTest(unittest.TestCase):
    """Checks the fingerprint of a pass of every workload on a small store; the Rust tests assert the same numbers."""

    def assert_fingerprint(
        self,
        name: str,
        number_of_objects: int,
        operations: int,
        expected: Fingerprint,
        timed_operations: int,
    ) -> None:
        """Asserts that one pass of workload `name` has fingerprint `expected` and times `timed_operations`
        operations, with both validation methods."""
        for use_brute_force_validation in both_methods():
            with self.subTest(brute_force=use_brute_force_validation):
                result: Pass = workloads.WORKLOADS[name](
                    number_of_objects, use_brute_force_validation, operations
                )
                self.assertEqual(expected, result.fingerprint)
                self.assertEqual(timed_operations, result.operations)

    def test_bulkload(self) -> None:
        """Bulkloading 10 objects runs no transaction, leaves one committed version per object and counts one
        operation per object, whatever operations it is given.

        Would fail if bulkload loaded other data than fake_data or timed the operations argument instead of the
        objects.
        """
        self.assert_fingerprint(
            "bulkload",
            10,
            SMALL_OPERATIONS,
            Fingerprint(0, 0, 0, 1, 10, WEIGHTED_SUM_OF_B_10),
            10,
        )

    def test_get(self) -> None:
        """Getting each of 10 objects counts 10 objects read, runs no transaction, changes nothing and times one
        operation per object, whatever operations it is given.

        Would fail if `get` took transaction ids, created versions, or timed the operations argument instead of the
        objects.
        """
        self.assert_fingerprint(
            "get",
            10,
            SMALL_OPERATIONS,
            Fingerprint(0, 0, 10, 1, 10, WEIGHTED_SUM_OF_B_10),
            10,
        )

    def test_read(self) -> None:
        """10 reads of a == 42 in one transaction on 435 objects each find object 434; the transaction takes the
        ids 1 (begin) and 2 (commit), so the counter ends at 3.

        Would fail if the reads ran in more than one transaction, ignored the number of reads, or the where clause
        matched other objects.
        """
        self.assert_fingerprint(
            "read",
            435,
            SMALL_READS,
            Fingerprint(1, 0, SMALL_READS, 3, 435, WEIGHTED_SUM_OF_B_435),
            SMALL_READS,
        )

    def test_update_commit(self) -> None:
        """20 transactions on 10 objects update every object twice (b + 1 each time).

        Would fail if a transaction updated a stale value (b + 1 of the bulkloaded value instead of the current one)
        or the wrap-around `i mod number_of_objects` broke.
        """
        self.assert_fingerprint(
            "update_commit", 10, SMALL_OPERATIONS, UPDATED_TWICE_10, SMALL_OPERATIONS
        )

    def test_read_only(self) -> None:
        """20 transactions on 10 objects each read the 3 objects with a < 100 and commit, writing nothing.

        Would fail if the read-only transactions created versions or read another number of objects.
        """
        self.assert_fingerprint(
            "read_only",
            10,
            SMALL_OPERATIONS,
            Fingerprint(20, 0, 20 * 3, 41, 10, WEIGHTED_SUM_OF_B_10),
            SMALL_OPERATIONS,
        )

    def test_read_write_disjoint(self) -> None:
        """20 transactions on 10 objects each read one object by its unique a and update it; none aborts.

        Would fail if a transaction read more than its object or an update was lost.
        """
        expected: Fingerprint = Fingerprint(
            20, 0, 20, 41, 10 + 20, WEIGHTED_SUM_OF_B_10 + 110
        )
        self.assert_fingerprint(
            "read_write_disjoint", 10, SMALL_OPERATIONS, expected, SMALL_OPERATIONS
        )

    def test_read_write_contention(self) -> None:
        """20 transactions on 380 objects (hot set 0 and 379) form 10 rounds as in the schedule of the
        `read_write_contention` docstring; the first of each round commits and the second aborts, with both
        validation methods.

        Each transaction reads both hot objects (4 per round); every transaction takes two ids, aborted ones too
        (1 + 2 * 20 = 41); only the 10 committed updates add a version, all to object 0 at position 0, so the
        weighted sum grows by 1 * 10.
        Would fail if a validation method let the second transaction of a round commit.
        """
        self.assert_fingerprint(
            "read_write_contention",
            380,
            SMALL_OPERATIONS,
            Fingerprint(10, 10, 10 * 4, 41, 380 + 10, WEIGHTED_SUM_OF_B_380 + 10),
            SMALL_OPERATIONS,
        )

    def test_read_write_contention_rotates_through_the_hot_set(self) -> None:
        """20 transactions on 1 000 objects form 10 rounds as in the schedule of the `read_write_contention`
        docstring, rotating through all ten hot objects 0, 379, 406, 433, 460, 487, 893, 920, 947, 974.

        Round j updates hot[2j mod 10] in its first, committing transaction and hot[2j + 1 mod 10] in its second,
        aborted one; so the commits update 0, 406, 460, 893, 947 (positions + 1: 1, 407, 461, 894, 948, sum 2711)
        twice each, which adds 2 * 2711 = 5422 to the weighted sum, and the second visit reads the first update
        (b + 2). Each transaction reads the 10 hot objects (20 * 10 = 200), takes two ids (1 + 2 * 20 = 41), and the
        10 commits add 10 versions. The Rust tests assert the same fingerprint.
        Would fail if the rotation `mod len(hot)` broke, the rounds updated other hot objects, or a later round
        updated a stale value.
        """
        self.assert_fingerprint(
            "read_write_contention",
            1000,
            SMALL_OPERATIONS,
            Fingerprint(10, 10, 20 * 10, 41, 1000 + 10, WEIGHTED_SUM_OF_B_1000 + 5422),
            SMALL_OPERATIONS,
        )

    def test_contention_with_an_odd_number_of_transactions(self) -> None:
        """21 transactions form 10 rounds of two (see the schedule in the `read_write_contention` docstring), the
        same work as 20 transactions; the pass times the 20 transactions it ran.

        Would fail if the seconds per operation were divided by the 21 transactions asked for, or the odd
        transaction began without a partner.
        """
        result: Pass = workloads.read_write_contention(380, False, 21)
        self.assertEqual(20, result.operations)
        self.assertEqual(
            workloads.read_write_contention(380, False, 20).fingerprint,
            result.fingerprint,
        )

    def test_weighted_sums_of_b_follow_from_their_definition(self) -> None:
        """The weighted sums of b used in the expected fingerprints are sum((i + 1) * b_i) over `fake_data(n)`.

        Would fail if a constant had a typo, which would make the fingerprint tests of both languages wrong alike.
        """
        self.assertEqual(
            WEIGHTED_SUM_OF_B_10, sum((i + 1) * ((i * 53) % 2001) for i in range(10))
        )
        self.assertEqual(
            WEIGHTED_SUM_OF_B_380, sum((i + 1) * ((i * 53) % 2001) for i in range(380))
        )
        self.assertEqual(
            WEIGHTED_SUM_OF_B_435, sum((i + 1) * ((i * 53) % 2001) for i in range(435))
        )
        self.assertEqual(
            WEIGHTED_SUM_OF_B_1000,
            sum((i + 1) * ((i * 53) % 2001) for i in range(1000)),
        )

    def test_contention_needs_two_hot_objects(self) -> None:
        """The contention workload raises ValueError on a store of 10 objects, whose hot set is object 0 only, as the
        schedule in the `read_write_contention` docstring needs two hot objects per round.

        Would fail if both transactions of a round updated the same object, which would measure other work.
        """
        with self.assertRaisesRegex(ValueError, "at least two objects"):
            workloads.read_write_contention(10, False, SMALL_OPERATIONS)


def constant_workload(
    seconds: float, operations: int, calls: list[tuple[int, bool, int]] | None = None
) -> Workload:
    """Returns a fake workload whose passes take `seconds`, do `operations` and have the same fingerprint; it
    appends its arguments to `calls` if given."""

    def workload(
        number_of_objects: int, use_brute_force_validation: bool, requested: int
    ) -> Pass:
        """A pass that does nothing but report fixed numbers."""
        if calls is not None:
            calls.append((number_of_objects, use_brute_force_validation, requested))
        return Pass(seconds, operations, Fingerprint(0, 0, 0, 1, 0, 0))

    return workload


class RepetitionTest(unittest.TestCase):
    """Checks the harness that repeats passes of a workload."""

    def test_zero_min_seconds_runs_exactly_one_pass(self) -> None:
        """With `min_seconds` 0, a repetition runs one pass and reports the fingerprint of the pass.

        Would fail if the loop could end before the first pass, leaving no fingerprint and dividing by zero.
        """
        result: Repetition = workloads.repetition(
            workloads.bulkload, 10, False, SMALL_OPERATIONS, 0.0
        )
        self.assertEqual(1, result.passes)
        self.assertEqual(
            Fingerprint(0, 0, 0, 1, 10, WEIGHTED_SUM_OF_B_10), result.fingerprint
        )

    def test_passes_until_min_seconds_and_divides_by_all_operations(self) -> None:
        """Passes of 0.01 s with 4 operations each repeat until 0.025 s are reached, i.e. 3 passes, and the seconds
        per operation are 0.03 s / 12 operations; every pass gets the same arguments.

        Would fail if the harness stopped too early, divided by the operations of one pass only, or did not pass
        the operations on to the workload.
        """
        calls: list[tuple[int, bool, int]] = []
        result: Repetition = workloads.repetition(
            constant_workload(0.01, 4, calls), 10, True, 7, 0.025
        )
        self.assertEqual(3, result.passes)
        self.assertAlmostEqual(0.0025, result.seconds_per_operation)
        self.assertEqual([(10, True, 7)] * 3, calls)

    def test_different_fingerprints_raise(self) -> None:
        """A repetition raises RuntimeError if two passes report different fingerprints.

        Would fail if a workload that does different work in each pass went unnoticed.
        """
        counter: Iterator[int] = itertools.count()

        def changing_workload(
            _number_of_objects: int, _use_brute_force_validation: bool, _operations: int
        ) -> Pass:
            """A pass that takes no time and reports another number of commits each time."""
            return Pass(0.0, 1, Fingerprint(next(counter), 0, 0, 1, 0, 0))

        with self.assertRaisesRegex(RuntimeError, "all passes must do the same work"):
            workloads.repetition(changing_workload, 10, False, 1, 1.0)

    def test_pass_without_operations_raises(self) -> None:
        """A repetition raises RuntimeError if a pass times no operation, e.g. contention with one transaction (no
        complete round), instead of repeating it forever.

        Would fail if such a repetition looped or divided by zero.
        """
        with self.assertRaisesRegex(
            RuntimeError, "a pass must time at least one operation"
        ):
            workloads.repetition(workloads.read_write_contention, 380, False, 1, 1.0)

    def test_garbage_collector_runs_once_and_is_off_during_the_passes(self) -> None:
        """A repetition collects garbage once before its passes, keeps the collector off while they run and turns it
        on again afterwards.

        Would fail if the collector ran during timing (noisy numbers), collected before every pass, or stayed off
        after the repetition.
        """
        self.addCleanup(gc.enable)
        enabled_during_pass: list[bool] = []

        def recording_workload(
            _number_of_objects: int, _use_brute_force_validation: bool, _operations: int
        ) -> Pass:
            """A pass of 0.5 s that records whether the garbage collector is on."""
            enabled_during_pass.append(gc.isenabled())
            return Pass(0.5, 1, Fingerprint(0, 0, 0, 1, 0, 0))

        with mock.patch.object(gc, "collect") as collect:
            workloads.repetition(recording_workload, 10, False, 1, 1.0)
        self.assertEqual(1, collect.call_count)
        self.assertEqual([False, False], enabled_during_pass)
        self.assertTrue(gc.isenabled())

    def test_garbage_collector_is_on_after_a_failing_workload(self) -> None:
        """The garbage collector is on again after a workload raised during the repetition.

        Would fail if an error in a workload left the collector off for the rest of the process.
        """
        self.addCleanup(gc.enable)
        with self.assertRaises(ValueError):
            workloads.repetition(
                workloads.read_write_contention, 10, False, SMALL_OPERATIONS, 0.0
            )
        self.assertTrue(gc.isenabled())


class CsvLineTest(unittest.TestCase):
    """Checks the CSV line the benchmark program prints per repetition."""

    def test_fields_in_the_order_the_runner_reads_them(self) -> None:
        """`csv_line` prints seconds per operation, passes and the six fingerprint fields, and the runner's
        `parse_output` reads them back unchanged.

        Would fail if a field were missing or moved, or the seconds lost precision on the way to the runner.
        """
        repetition: Repetition = Repetition(
            1.234567890123e-07, 3, Fingerprint(1, 2, 3, 4, 5, 6)
        )
        line: str = workloads.csv_line(repetition)
        self.assertEqual("1.234567890123e-07,3,1,2,3,4,5,6", line)
        measurement: Measurement = run.parse_output(
            "python", Config("read", 2, 435, 10), line + "\n", 1
        )
        self.assertEqual(
            [repetition.seconds_per_operation], measurement.seconds_per_operation
        )
        self.assertEqual([3], measurement.passes)
        self.assertEqual(repetition.fingerprint, measurement.fingerprint)


class WorkloadsMainTest(unittest.TestCase):
    """Checks the command line of the Python benchmark program."""

    def test_prints_one_csv_line_per_repetition(self) -> None:
        """`main` prints one line per repetition, not one for the warm-up; with `min_seconds` 0 each repetition is one
        pass.

        Would fail if the warm-up were printed or the arguments reached the workload in another order.
        """
        output: io.StringIO = io.StringIO()
        with contextlib.redirect_stdout(output):
            workloads.main(["update_commit", "2", "10", "20", "3"], min_seconds=0.0)
        lines: list[str] = output.getvalue().splitlines()
        self.assertEqual(3, len(lines))
        for line in lines:
            fields: list[str] = line.split(",")
            self.assertEqual("1", fields[1])
            self.assertEqual(
                ["20", "0", "0", "41", "30", str(WEIGHTED_SUM_OF_B_10 + 110)],
                fields[2:],
            )

    def test_method_1_is_brute_force_validation(self) -> None:
        """Method "1" runs the workload with brute-force validation and method "2" without, for the warm-up and
        every repetition, with the given objects and operations.

        Would fail if the methods were swapped, which would mislabel all transactions-per-second results.
        """
        for method, use_brute_force_validation in (("1", True), ("2", False)):
            with self.subTest(method=method):
                calls: list[tuple[int, bool, int]] = []
                fake: Workload = constant_workload(1.0, 1, calls)
                with mock.patch.dict(workloads.WORKLOADS, {"fake": fake}):
                    with contextlib.redirect_stdout(io.StringIO()):
                        workloads.main(["fake", method, "7", "5", "2"])
                # one pass each for the warm-up and the two repetitions:
                self.assertEqual([(7, use_brute_force_validation, 5)] * 3, calls)

    def test_wrong_arguments_exit_with_status_2(self) -> None:
        """`main` exits with status 2 and prints nothing to standard output for a wrong command line: an unknown
        workload, method 3, a number below 1, a number that is no plain ASCII number (as Rust rejects it), or too
        few or too many arguments.

        Would fail if a wrong command line ran a benchmark, which the runner would then measure, or Python accepted
        a number that the Rust twin rejects.
        """
        cases: dict[str, list[str]] = {
            "unknown workload": ["bulk_load", "2", "10", "20", "1"],
            "method 3": ["bulkload", "3", "10", "20", "1"],
            "0 objects": ["bulkload", "2", "0", "20", "1"],
            "0 operations": ["bulkload", "2", "10", "0", "1"],
            "0 repetitions": ["bulkload", "2", "10", "20", "0"],
            "negative": ["bulkload", "2", "10", "-1", "1"],
            "no number": ["bulkload", "2", "10", "ten", "1"],
            "spaces": ["bulkload", "2", " 7 ", "20", "1"],
            "underscore": ["bulkload", "2", "10", "1_000", "1"],
            "plus sign": ["bulkload", "2", "+7", "10", "1"],
            "Arabic-Indic digit": ["bulkload", "2", "10", "20", "\u0663"],
            "missing argument": ["bulkload", "2", "10", "20"],
            "too many arguments": ["bulkload", "2", "10", "20", "1", "1"],
        }
        for case, arguments in cases.items():
            with self.subTest(case):
                output: io.StringIO = io.StringIO()
                with contextlib.redirect_stdout(output):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as context:
                            workloads.main(arguments, min_seconds=0.0)
                self.assertEqual(2, context.exception.code)
                self.assertEqual("", output.getvalue())


# a CSV line of each language for update_commit on 10 objects with 20 transactions, each in the number format of
# its language (Python's repr, Rust's Debug format):
PYTHON_LINE: str = "2.5e-05,2,20,0,0,41,30,17600"
RUST_LINE: str = "1.5e-7,300,20,0,0,41,30,17600"


class FakeRunner:
    """A command runner that records the commands and answers them with canned output instead of running them."""

    def __init__(self, python_line: str, rust_line: str, porcelain: str = "") -> None:
        """Answers the Python benchmark with `python_line` and the Rust one with `rust_line`, once per repetition
        asked for (the last argument), and `git status --porcelain` with `porcelain`."""
        self.python_line: str = python_line
        self.rust_line: str = rust_line
        self.porcelain: str = porcelain
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, arguments: list[str], directory: Path) -> str:
        """See :data:`run.CommandRunner`; fails for a command the runner is not expected to run."""
        self.calls.append((arguments, directory))
        if arguments[0] == sys.executable:
            return (self.python_line + "\n") * int(arguments[-1])
        if arguments[0] == str(run.RUST_BENCHMARK):
            return (self.rust_line + "\n") * int(arguments[-1])
        canned: dict[tuple[str, ...], str] = {
            ("cargo", "build"): "",
            ("rustc", "--version"): "rustc 1.98.1 (fake 2026-10-01)\n",
            ("git", "rev-parse"): "0123456789abcdef\n",
            ("git", "status"): self.porcelain,
            ("sysctl", "-n"): "Fake CPU\n",
        }
        return canned[tuple(arguments[:2])]

    def index_of(self, program: str) -> int:
        """Returns the position of the first recorded command that runs `program`."""
        return next(
            i for i, (arguments, _) in enumerate(self.calls) if arguments[0] == program
        )

    def benchmark_languages(self) -> list[str]:
        """Returns the languages of the recorded benchmark commands, in the order they ran."""
        languages: dict[str, str] = {
            sys.executable: "python",
            str(run.RUST_BENCHMARK): "rust",
        }
        return [
            languages[arguments[0]]
            for arguments, _ in self.calls
            if arguments[0] in languages
        ]


class ParseOutputTest(unittest.TestCase):
    """Checks how the runner reads the CSV output of a benchmark program."""

    def parse(self, output: str, repetitions: int = 1) -> Measurement:
        """Parses `output` of the Rust program for update_commit on 10 objects with 20 transactions."""
        return run.parse_output(
            "rust", Config("update_commit", 2, 10, 20), output, repetitions
        )

    def test_reads_csv_lines_into_a_measurement(self) -> None:
        """`parse_output` reads seconds per operation and passes of every repetition and the common fingerprint.

        Would fail if the columns were mixed up or a repetition were dropped.
        """
        output: str = (
            "0.000721,5,20,0,0,41,30,17600\n"
            "1e-5,4,20,0,0,41,30,17600\n"
            "3.0e-06,6,20,0,0,41,30,17600\n"
        )
        self.assertEqual(
            Measurement(
                "rust",
                Config("update_commit", 2, 10, 20),
                [0.000721, 1e-05, 3.0e-06],
                [5, 4, 6],
                UPDATED_TWICE_10,
            ),
            self.parse(output, 3),
        )

    def test_wrong_number_of_fields_raises(self) -> None:
        """`parse_output` raises ValueError for a line of 7 or 9 fields.

        Would fail if a line of a program with a missing or extra fingerprint field were read with shifted fields.
        """
        for line in ("2.0e-06,5,20,0,0,41,30", "2.0e-06,5,20,0,0,41,30,17600,1"):
            with self.subTest(line=line):
                with self.assertRaisesRegex(ValueError, "instead of 8 fields"):
                    self.parse(line)

    def test_wrong_number_of_lines_raises(self) -> None:
        """`parse_output` raises ValueError unless the program printed exactly one line per repetition: no line at
        all, fewer lines or more lines than the 3 repetitions asked for.

        Would fail if a program that crashed after some repetitions, printed nothing, or printed extra lines (e.g.
        the warm-up) ended up in the results.
        """
        line: str = "2.0e-06,5,20,0,0,41,30,17600\n"
        for output, lines in (("", 0), ("\n", 0), (line * 2, 2), (line * 4, 4)):
            with self.subTest(lines=lines, output=output):
                with self.assertRaisesRegex(
                    ValueError, f": {lines} lines instead of 3 repetitions"
                ):
                    self.parse(output, 3)

    def test_bad_seconds_raise(self) -> None:
        """`parse_output` raises ValueError for seconds per operation that are not a number (Python's `nan`, Rust's
        `NaN`), infinite, negative or written in a form neither program prints.

        Would fail if a broken timer reached the results, where a NaN or negative time would spoil the medians, or
        if the runner read every form `float` reads.
        """
        for seconds in ("nan", "NaN", "inf", "1e999", "-1e-6", "1e-6 ", "+1e-6", "1_0"):
            with self.subTest(seconds=seconds):
                with self.assertRaisesRegex(ValueError, "bad seconds"):
                    self.parse(f"{seconds},5,20,0,0,41,30,17600")

    def test_zero_repetitions_raise(self) -> None:
        """Parsing for zero repetitions raises ValueError. Would fail if it indexed the first of no fingerprints."""
        with self.assertRaisesRegex(ValueError, "at least one repetition"):
            run.parse_output("rust", Config("get", 2, 10, 10), "", 0)

    def test_zero_passes_raise(self) -> None:
        """`parse_output` raises ValueError for a repetition of 0 passes.

        Would fail if a repetition that ran no pass, and so measured nothing, were accepted.
        """
        with self.assertRaisesRegex(ValueError, "no pass"):
            self.parse("2.0e-06,0,20,0,0,41,30,17600")

    def test_counts_that_are_not_plain_ascii_numbers_raise(self) -> None:
        """`parse_output` raises ValueError for passes or a fingerprint field written with a sign, a space or an
        underscore, all of which Python's `int` would accept.

        Would fail if passes or the fingerprint fields were read with `int`, so that e.g. a commit count of -1
        reached the results or two differently written counts compared equal.
        """
        for count in ("+1", " 1", "1_000", "-1"):
            for line in (
                f"2.0e-06,{count},20,0,0,41,30,17600",
                f"2.0e-06,5,{count},0,0,41,30,17600",
                f"2.0e-06,5,20,0,0,41,{count},17600",
            ):
                with self.subTest(line=line):
                    with self.assertRaisesRegex(ValueError, "is not a count"):
                        self.parse(line)

    def test_different_fingerprints_raise(self) -> None:
        """`parse_output` raises ValueError if two repetitions report different fingerprints.

        Would fail if a program that did different work per repetition were measured anyway.
        """
        output: str = "2.0e-06,5,20,0,0,41,30,17600\n1.0e-06,4,19,0,0,41,30,17600\n"
        with self.assertRaisesRegex(ValueError, "repetitions did different work"):
            self.parse(output, 2)


class CountTest(unittest.TestCase):
    """Checks how the runner reads a count of the CSV output."""

    def test_reads_ascii_digits(self) -> None:
        """`count` reads 0 and a large count written with ASCII digits.

        Would fail if 0, the count of aborts of most workloads, were rejected.
        """
        self.assertEqual((0, 498_340_555), (run.count("0"), run.count("498340555")))

    def test_rejects_everything_else(self) -> None:
        """`count` raises ValueError for an empty text, a decimal number and digits outside ASCII (Arabic-Indic
        three, superscript two), which `str.isdigit` alone would accept.

        Would fail if the check for ASCII were dropped, so that a count Rust can never print were accepted.
        """
        for text in ("", "1.0", "\u0663", "\u00b2"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "is not a count"):
                    run.count(text)


class MeasurementTest(unittest.TestCase):
    """Checks the statistics of a measurement."""

    def test_median_minimum_and_maximum(self) -> None:
        """Of the seconds per operation 2, 1 and 3 microseconds, the median is 2, the minimum 1 and the maximum 3.

        Would fail if a statistic took the first or last repetition instead of the middle, smallest or largest one.
        """
        measurement: Measurement = Measurement(
            "python",
            Config("update_commit", 2, 10, 20),
            [2.0e-06, 1.0e-06, 3.0e-06],
            [5, 4, 6],
            UPDATED_TWICE_10,
        )
        self.assertEqual(
            (2.0e-06, 1.0e-06, 3.0e-06),
            (measurement.median, measurement.minimum, measurement.maximum),
        )


class MeasureTest(unittest.TestCase):
    """Checks that the runner runs both languages and compares their fingerprints."""

    def test_runs_the_real_python_program(self) -> None:
        """`measure` runs the Python benchmark program for real (only Rust is faked here), and `parse_output` accepts
        what it prints.

        Would fail if the module path or the command line of the Python program broke; the other tests fake both
        programs.
        """
        fake: FakeRunner = FakeRunner(PYTHON_LINE, RUST_LINE)

        def runner(arguments: list[str], directory: Path) -> str:
            """Runs the Python program and lets `fake` answer the Rust one."""
            if arguments[0] == sys.executable:
                return run.run_command(arguments, directory)
            return fake(arguments, directory)

        python, _ = run.measure(Config("update_commit", 2, 10, 20), 1, runner)
        self.assertEqual(UPDATED_TWICE_10, python.fingerprint)

    def test_returns_both_measurements_when_fingerprints_agree(self) -> None:
        """`measure` runs the Python module and then the Rust program with the same arguments (workload, method,
        objects, operations, repetitions) and returns both measurements of all repetitions.

        Would fail if the runner passed the arguments in another order than both programs read them.
        """
        runner: FakeRunner = FakeRunner(PYTHON_LINE, RUST_LINE)
        python, rust = run.measure(Config("update_commit", 2, 10, 20), 7, runner)
        self.assertEqual(
            ("python", [2.5e-05] * 7, [2] * 7),
            (python.language, python.seconds_per_operation, python.passes),
        )
        self.assertEqual(
            ("rust", [1.5e-07] * 7, [300] * 7),
            (rust.language, rust.seconds_per_operation, rust.passes),
        )
        self.assertEqual(UPDATED_TWICE_10, python.fingerprint)
        self.assertEqual(UPDATED_TWICE_10, rust.fingerprint)
        arguments: list[str] = ["update_commit", "2", "10", "20", "7"]
        self.assertEqual(
            [
                (
                    [sys.executable, "-m", "system.benchmarks.workloads", *arguments],
                    run.ROOT,
                ),
                ([str(run.RUST_BENCHMARK), *arguments], run.ROOT),
            ],
            runner.calls,
        )

    def test_rust_first(self) -> None:
        """With `rust_first`, `measure` runs the Rust program before the Python module and still returns the Python
        measurement first.

        Would fail if `rust_first` were ignored, or if it also swapped the results, so that the runner would label
        Rust's times as Python's.
        """
        runner: FakeRunner = FakeRunner(PYTHON_LINE, RUST_LINE)
        python, rust = run.measure(
            Config("update_commit", 2, 10, 20), 1, runner, rust_first=True
        )
        self.assertEqual(["rust", "python"], runner.benchmark_languages())
        self.assertEqual(
            ("python", [2.5e-05]), (python.language, python.seconds_per_operation)
        )
        self.assertEqual(
            ("rust", [1.5e-07]), (rust.language, rust.seconds_per_operation)
        )

    def test_different_fingerprints_raise(self) -> None:
        """`measure` raises ValueError if Python and Rust report different fingerprints.

        Would fail if the cross-check between the languages were skipped.
        """
        runner: FakeRunner = FakeRunner(PYTHON_LINE, "1.5e-7,300,20,0,0,41,30,17601")
        with self.assertRaisesRegex(ValueError, "Python and Rust did different work"):
            run.measure(Config("update_commit", 2, 10, 20), 1, runner)


class ConfigsTest(unittest.TestCase):
    """Checks the benchmarks the runner chooses."""

    def test_operations(self) -> None:
        """bulkload and get work on every object, read does 100 reads, all other workloads 1 000 transactions.

        Would fail if the runner asked for another number of operations than the workloads are designed for.
        """
        self.assertEqual(
            [100, 10_000, 100, 1000, 1000, 1000],
            [
                run.operations_per_pass("bulkload", 100),
                run.operations_per_pass("get", 10_000),
                run.operations_per_pass("read", 10_000),
                run.operations_per_pass("update_commit", 100),
                run.operations_per_pass("read_only", 1000),
                run.operations_per_pass("read_write_contention", 1000),
            ],
        )

    def test_quick_configs(self) -> None:
        """The quick run keeps only the smallest store size of the micro-benchmarks (method 2) and all six
        transactions-per-second benchmarks.

        Would fail if `--quick` dropped a transactions-per-second benchmark or kept a larger micro size.
        """
        self.assertEqual(
            [
                Config("bulkload", 2, 100, 100),
                Config("get", 2, 100, 100),
                Config("read", 2, 100, 100),
                Config("update_commit", 2, 100, 1000),
                Config("read_only", 1, 1000, 1000),
                Config("read_only", 2, 1000, 1000),
                Config("read_write_disjoint", 1, 1000, 1000),
                Config("read_write_disjoint", 2, 1000, 1000),
                Config("read_write_contention", 1, 1000, 1000),
                Config("read_write_contention", 2, 1000, 1000),
            ],
            run.configs(quick=True),
        )

    def test_full_configs(self) -> None:
        """The full run measures the four micro-benchmarks at 100, 1 000 and 10 000 objects, plus the six
        transactions-per-second benchmarks.

        Would fail if a store size of the micro-benchmarks were dropped.
        """
        full: list[Config] = run.configs(quick=False)
        self.assertEqual(4 * 3 + 6, len(full))
        self.assertEqual(
            [
                Config("bulkload", 2, 100, 100),
                Config("bulkload", 2, 1000, 1000),
                Config("bulkload", 2, 10_000, 10_000),
            ],
            full[:3],
        )


class RunTest(unittest.TestCase):
    """Checks the provenance, a whole run of the runner and its command line."""

    def test_provenance(self) -> None:
        """The provenance holds exactly the date, the machine (CPU, architecture, cores, operating system), the
        Python and Rust versions, the git commit and whether the working tree has changes.

        Would fail if `git_dirty` ignored changes, a new field, e.g. the host or user name, revealed who measured
        the results where, or rustc ran outside generated/rust/, whose rust-toolchain.toml names the Rust version
        that builds the benchmark program.
        """
        for porcelain, dirty in ((" M generated/rust/Cargo.toml\n", True), ("", False)):
            with self.subTest(porcelain=porcelain):
                runner: FakeRunner = FakeRunner("", "", porcelain)
                result: run.Provenance = run.provenance(runner)
                self.assertIn(
                    (["rustc", "--version"], run.ROOT / "generated" / "rust"),
                    runner.calls,
                )
                self.assertEqual(
                    {
                        "date",
                        "cpu",
                        "machine",
                        "cores",
                        "os",
                        "python",
                        "rustc",
                        "git_commit",
                        "git_dirty",
                    },
                    set(vars(result)),
                )
                self.assertEqual("0123456789abcdef", result.git_commit)
                self.assertEqual(dirty, result.git_dirty)
                self.assertEqual("rustc 1.98.1 (fake 2026-10-01)", result.rustc)

    def test_run_records_provenance_before_building(self) -> None:
        """A run asks git and rustc for the provenance before it builds the Rust program, builds it in generated/rust/
        with `cargo build --release --locked --example workloads --target-dir <RUST_TARGET>`, and only then runs the
        benchmarks.

        Would fail if a commit during the build could mislabel the results, the runner measured a debug build or
        one with other dependency versions than Cargo.lock, a CARGO_TARGET_DIR of the environment made it measure
        an old build, or it ran another program than the one it built.
        """
        runner: FakeRunner = FakeRunner(PYTHON_LINE, RUST_LINE)
        with contextlib.redirect_stderr(io.StringIO()):
            run.run(True, 3, runner)
        build: int = runner.index_of("cargo")
        git_calls: list[int] = [
            i for i, (arguments, _) in enumerate(runner.calls) if arguments[0] == "git"
        ]
        self.assertEqual(2, len(git_calls))
        self.assertLess(max(git_calls), build)
        self.assertLess(runner.index_of("rustc"), build)
        self.assertLess(build, runner.index_of(sys.executable))
        self.assertLess(build, runner.index_of(str(run.RUST_BENCHMARK)))
        self.assertEqual(
            (
                "cargo build --release --locked --example workloads --target-dir".split()
                + [str(run.RUST_TARGET)],
                run.ROOT / "generated" / "rust",
            ),
            runner.calls[build],
        )

    def test_benchmark_program_is_the_one_cargo_builds(self) -> None:
        """The runner runs the example `workloads` from the release build in `RUST_TARGET`.

        Would fail if the runner ran another program than the one `cargo build --example workloads` writes.
        """
        self.assertEqual(
            run.RUST_TARGET / "release" / "examples" / "workloads", run.RUST_BENCHMARK
        )
        self.assertEqual(run.ROOT / "generated" / "rust" / "target", run.RUST_TARGET)

    def test_run_alternates_which_language_runs_first(self) -> None:
        """A run alternates the language that runs first between the workloads and store sizes, the same for both
        validation methods, and returns the Python measurement of each config before the Rust one.

        Would fail if one language always ran on a machine the other had just warmed up, if the first language were
        tied to the validation method, or if the order of the results followed the order of the runs.
        """
        runner: FakeRunner = FakeRunner(PYTHON_LINE, RUST_LINE)
        with contextlib.redirect_stderr(io.StringIO()):
            results: dict[str, Any] = run.run(False, 3, runner)
        # P: Python first, R: Rust first; four micro workloads with three store sizes each, then three workloads
        # with methods 1 and 2:
        first: str = "PRP" + "RPR" + "PRP" + "RPR" + "PP" + "RR" + "PP"
        order: dict[str, tuple[str, str]] = {
            "P": ("python", "rust"),
            "R": ("rust", "python"),
        }
        self.assertEqual(
            [language for letter in first for language in order[letter]],
            runner.benchmark_languages(),
        )
        self.assertEqual(
            ["python", "rust"] * len(first),
            [m["language"] for m in results["measurements"]],
        )

    def test_run_measures_every_config_in_both_languages(self) -> None:
        """A quick run returns a Python and a Rust measurement for every config.

        Would fail if a config were skipped or measured in one language only.
        """
        runner: FakeRunner = FakeRunner(PYTHON_LINE, RUST_LINE)
        with contextlib.redirect_stderr(io.StringIO()):
            results: dict[str, Any] = run.run(True, 3, runner)
        self.assertEqual(3, results["repetitions"])
        self.assertEqual(
            sorted(
                (language, c.workload, c.method, c.objects, c.operations)
                for c in run.configs(quick=True)
                for language in ("python", "rust")
            ),
            sorted(
                (
                    m["language"],
                    m["config"]["workload"],
                    m["config"]["method"],
                    m["config"]["objects"],
                    m["config"]["operations"],
                )
                for m in results["measurements"]
            ),
        )

    def test_main_writes_results_json(self) -> None:
        """`main --quick` writes the results of 3 repetitions as JSON to `--output`, creating its directory; each
        measurement holds its fingerprint as an object with named fields.

        Would fail if the measurements could not be written as JSON, the output directory had to exist, or the
        fingerprint lost its field names.
        """
        runner: FakeRunner = FakeRunner(PYTHON_LINE, RUST_LINE)
        with tempfile.TemporaryDirectory() as directory:
            output: Path = Path(directory) / "benchmarks" / "results.json"
            with mock.patch.object(run, "run_command", runner):
                with contextlib.redirect_stderr(io.StringIO()):
                    run.main(["--quick", "--output", str(output)])
            results: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(3, results["repetitions"])
        self.assertEqual(2 * len(run.configs(quick=True)), len(results["measurements"]))
        self.assertEqual(
            {
                "commits": 20,
                "aborts": 0,
                "objects_read": 0,
                "transaction_counter": 41,
                "committed_versions": 30,
                "weighted_sum_of_b": 17600,
            },
            results["measurements"][0]["fingerprint"],
        )
        # the Python program was asked for 3 repetitions:
        self.assertEqual("3", runner.calls[runner.index_of(sys.executable)][0][-1])

    def test_main_rejects_zero_repetitions(self) -> None:
        """`main --repetitions 0` exits with status 2 before it runs any command.

        Would fail if a run without repetitions built and ran the benchmarks and then failed on empty output.
        """
        runner: FakeRunner = FakeRunner(PYTHON_LINE, RUST_LINE)
        with mock.patch.object(run, "run_command", runner):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as context:
                    run.main(["--repetitions", "0"])
        self.assertEqual(2, context.exception.code)
        self.assertEqual([], runner.calls)

    def test_quick_ignores_the_repetitions(self) -> None:
        """`main --quick --repetitions 0` runs 3 repetitions instead of rejecting the 0, as `--quick` overrides
        `--repetitions`.

        Would fail if the check of `--repetitions` ran with `--quick`, or `--quick` passed the given repetitions on.
        """
        runner: FakeRunner = FakeRunner(PYTHON_LINE, RUST_LINE)
        with tempfile.TemporaryDirectory() as directory:
            output: Path = Path(directory) / "results.json"
            with mock.patch.object(run, "run_command", runner):
                with contextlib.redirect_stderr(io.StringIO()):
                    run.main(["--quick", "--repetitions", "0", "--output", str(output)])
            results: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(3, results["repetitions"])
        self.assertEqual("3", runner.calls[runner.index_of(sys.executable)][0][-1])
        self.assertEqual(
            "3", runner.calls[runner.index_of(str(run.RUST_BENCHMARK))][0][-1]
        )


class RunCommandTest(unittest.TestCase):
    """Checks the runner's real command runner on small Python commands."""

    def test_returns_standard_output(self) -> None:
        """`run_command` returns what the command printed to standard output.

        Would fail if the output were not captured as text.
        """
        self.assertEqual(
            "x\n", run.run_command([sys.executable, "-c", "print('x')"], run.ROOT)
        )

    def test_runs_in_the_given_directory(self) -> None:
        """`run_command` runs the command in the given directory.

        Would fail if `cargo build` ran outside generated/rust/, where it finds no Cargo.toml.
        """
        with tempfile.TemporaryDirectory() as directory:
            output: str = run.run_command(
                [sys.executable, "-c", "import os; print(os.getcwd())"],
                Path(directory),
            )
            self.assertEqual(Path(directory).resolve(), Path(output.strip()).resolve())

    def test_failing_command_raises(self) -> None:
        """`run_command` raises CalledProcessError with the exit status of a failing command.

        Would fail if a crashed benchmark program were read as a program that printed no lines.
        """
        with self.assertRaises(subprocess.CalledProcessError) as context:
            run.run_command([sys.executable, "-c", "raise SystemExit(3)"], run.ROOT)
        self.assertEqual(3, context.exception.returncode)


if __name__ == "__main__":
    unittest.main()
