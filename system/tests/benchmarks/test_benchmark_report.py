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

# This module exceeds pylint's 1000 lines, as it tests the loading of the results, the charts and the whole page.
# pylint: disable=too-many-lines
"""Tests for the HTML report of the store benchmarks: loading the results, the charts' scales and the page."""

import contextlib
import io
import json
import math
import os
import random
import re
import shlex
import tempfile
import unittest
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from unittest import mock

from system.benchmarks import charts, report, run
from system.benchmarks.workloads import Fingerprint
from system.tests.benchmarks.page_parser import Element, PageParser, Svg, parse

# the (Python, Rust) medians of the fake results in seconds per operation, by workload, method and store size;
# round numbers, distinct within each language, so that speed-ups (2× to 70×) and positions on the axes are exact:
FAKE_MEDIANS: dict[tuple[str, int, int], tuple[float, float]] = {
    ("bulkload", 2, 100): (2e-6, 1e-7),
    ("bulkload", 2, 1_000): (6e-6, 2e-7),
    ("bulkload", 2, 10_000): (1.6e-5, 4e-7),
    ("get", 2, 100): (2.5e-6, 5e-8),
    ("get", 2, 1_000): (3.6e-6, 6e-8),
    ("get", 2, 10_000): (4.9e-6, 7e-8),
    ("read", 2, 100): (1.1e-5, 1e-6),
    ("read", 2, 1_000): (1.2e-4, 1e-5),
    ("read", 2, 10_000): (1.3e-3, 1e-4),
    ("update_commit", 2, 100): (2.8e-5, 2e-6),
    ("update_commit", 2, 1_000): (4.5e-5, 3e-6),
    ("update_commit", 2, 10_000): (6.4e-5, 4e-6),
    ("read_only", 1, 1_000): (3e-4, 1.5e-4),
    ("read_only", 2, 1_000): (3.2e-4, 8e-5),
    ("read_write_disjoint", 1, 1_000): (1e-3, 2e-4),
    ("read_write_disjoint", 2, 1_000): (2e-3, 2.5e-4),
    ("read_write_contention", 1, 1_000): (5e-3, 5e-4),
    ("read_write_contention", 2, 1_000): (2.5e-2, 1e-3),
}
# the first benchmark of a full run, which the broken results below change:
FIRST: run.Config = run.configs(quick=False)[0]

# a change made to the fake results before they are written:
Change = Callable[[dict[str, Any]], object]


def fake_results(quick: bool = False) -> dict[str, Any]:
    """Returns results as `run.run` returns them, for the benchmarks of `run.configs(quick)` with the medians of
    `FAKE_MEDIANS`: three repetitions of twice the median, half of it and the median (unsorted, so that the median
    must be computed), in a shuffled order (always the same) and with a valid provenance.
    """
    measurements: list[dict[str, Any]] = []
    for index, config in enumerate(run.configs(quick)):
        medians: tuple[float, float] = FAKE_MEDIANS[
            config.workload, config.method, config.objects
        ]
        # one fingerprint per benchmark, shared by Python and Rust, as they did the same work; its commits are the
        # benchmark's index and it has no aborts:
        fingerprint: Fingerprint = Fingerprint(
            index, 0, config.operations, index + 1, config.objects, 42 * index
        )
        for language, median in zip(("python", "rust"), medians):
            seconds: list[float] = [median * 2, median / 2, median]
            measurements.append(
                asdict(
                    run.Measurement(language, config, seconds, [1, 2, 3], fingerprint)
                )
            )
    # shuffle the measurements with a fixed seed, so that `load_results` must bring them into the order of a full run:
    random.Random(16).shuffle(measurements)
    provenance: run.Provenance = run.Provenance(
        date="2026-01-02T03:04:05+00:00",
        cpu="Test CPU",
        machine="arm64",
        cores=8,
        os="TestOS-1.0",
        python="3.12.0",
        rustc="rustc 1.0.0 (0000000 2026-01-01)",
        git_commit="0123456789abcdef0123456789abcdef01234567",
        git_dirty=True,
    )
    return {
        "provenance": asdict(provenance),
        "repetitions": 3,
        "measurements": measurements,
    }


def write_results(directory: Path, data: object) -> Path:
    """Writes `data` as JSON to ``results.json`` in `directory` and returns its path."""
    path: Path = directory / "results.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def entry(data: dict[str, Any], language: str, config: run.Config) -> dict[str, Any]:
    """Returns the measurement of `config` in `language` from the results `data`."""
    return next(
        m
        for m in data["measurements"]
        if m["language"] == language and m["config"] == asdict(config)
    )


def replaced(key: str, index: int | str, value: object) -> Change:
    """Returns a change that sets ``[key][index]`` of the Python measurement of `FIRST` to `value`."""

    def change(data: dict[str, Any]) -> None:
        """Sets the value."""
        entry(data, "python", FIRST)[key][index] = value

    return change


def provenance_field(name: str, value: object) -> Change:
    """Returns a change that sets the provenance field `name` to `value`."""

    def change(data: dict[str, Any]) -> None:
        """Sets the field."""
        data["provenance"][name] = value

    return change


def resized(key: str, length: int) -> Change:
    """Returns a change that shortens or lengthens the list `key` of the Python measurement of `FIRST` to
    `length` by dropping or repeating values.
    """

    def change(data: dict[str, Any]) -> None:
        """Resizes the list."""
        values: list[Any] = entry(data, "python", FIRST)[key]
        values[:] = (values * length)[:length]

    return change


@dataclass(frozen=True)
class BrokenResults:
    """Results that `load_results` rejects: what is wrong, the change that breaks the fake results, and a part of
    the error message that names the problem.
    """

    description: str
    change: Change
    problem: str


def committed_page() -> str:
    """Returns the committed report page."""
    return report.REPORT.read_text(encoding="utf-8")


class LoadResultsTest(unittest.TestCase):
    """Checks reading results and rejecting results that are not those of a full run."""

    def assert_file_rejected(self, content: str, problem: str) -> None:
        """Asserts that `load_results` rejects a file with `content` with a ValueError that names the file and
        contains `problem`.
        """
        with tempfile.TemporaryDirectory() as directory:
            path: Path = Path(directory) / "results.json"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                report.load_results(path)
        self.assertIn(str(path), str(caught.exception))
        self.assertIn(problem, str(caught.exception))

    def assert_rejected(self, cases: list[BrokenResults]) -> None:
        """Asserts for each case that `load_results` rejects the fake results after its change with a ValueError
        that names the file and the problem.
        """
        for broken in cases:
            with self.subTest(broken.description):
                data: dict[str, Any] = fake_results()
                broken.change(data)
                self.assert_file_rejected(json.dumps(data), broken.problem)

    def test_pairs_come_in_the_order_of_a_full_run(self) -> None:
        """Results in a shuffled order give one pair per benchmark in the order of `run.configs(quick=False)`, each
        with the Python and the Rust measurement in its place.

        Would fail if the pairs came in the order of the file, or Python and Rust were swapped.
        """
        data: dict[str, Any] = fake_results()
        # the benchmarks in the order of the file, each once although it has two measurements:
        file_order: list[run.Config] = list(
            dict.fromkeys(run.Config(**m["config"]) for m in data["measurements"])
        )
        # the fake results are not in the order of a full run:
        self.assertNotEqual(run.configs(quick=False), file_order)
        # write the fake results to a file and load them:
        with tempfile.TemporaryDirectory() as directory:
            results: report.Results = report.load_results(
                write_results(Path(directory), data)
            )
        # the pairs come in the order of a full run, each with the fake medians of Python and Rust in their places:
        self.assertEqual(run.configs(quick=False), list(results.pairs))
        for config, pair in results.pairs.items():
            with self.subTest(config=config):
                self.assertEqual(
                    FAKE_MEDIANS[config.workload, config.method, config.objects],
                    (pair.python.median, pair.rust.median),
                )
                self.assertEqual(
                    ("python", "rust"), (pair.python.language, pair.rust.language)
                )
        # the repetitions and the provenance are taken over from the file:
        self.assertEqual(3, results.repetitions)
        self.assertEqual(run.Provenance(**data["provenance"]), results.provenance)

    def test_rejects_a_wrong_set_of_benchmarks(self) -> None:
        """Results with a benchmark missing or too many, an unknown or missing language, a measurement given twice
        or Python and Rust doing different work are rejected.

        Would fail if a report could show a partial run, a benchmark of a quick run, or a comparison of different
        work.
        """
        # a benchmark that a full run does not have: the first one with 5 objects and 5 operations:
        extra: run.Config = replace(FIRST, objects=5, operations=5)
        cases: list[BrokenResults] = [
            BrokenResults(
                "a benchmark missing",
                lambda d: [
                    d["measurements"].remove(entry(d, x, FIRST))
                    for x in ("python", "rust")
                ],
                f"missing {[f'python {FIRST}', f'rust {FIRST}']}, unexpected []",
            ),
            BrokenResults(
                "an extra benchmark",
                lambda d: d["measurements"].extend(
                    {**m, "config": asdict(extra)}
                    for m in [entry(d, "python", FIRST), entry(d, "rust", FIRST)]
                ),
                "missing [], unexpected [",
            ),
            BrokenResults(
                "an unknown language",
                lambda d: entry(d, "rust", FIRST).update(language="java"),
                "unknown language 'java'",
            ),
            BrokenResults(
                "a language missing",
                lambda d: d["measurements"].remove(entry(d, "rust", FIRST)),
                f"missing {[f'rust {FIRST}']}, unexpected []",
            ),
            BrokenResults(
                "a measurement given twice",
                lambda d: d["measurements"].append(entry(d, "rust", FIRST)),
                "measured twice",
            ),
            BrokenResults(
                "different fingerprints",
                lambda d: entry(d, "rust", FIRST)["fingerprint"].update(commits=99),
                "did different work",
            ),
        ]
        self.assert_rejected(cases)

    def test_rejects_invalid_numbers(self) -> None:
        """Results with a repetition count that is not a whole number of at least 1, a list of seconds or passes of
        another length, seconds outside `report.SECONDS_RANGE` or not numbers, passes that are not whole numbers
        of at least 1 or a fingerprint field that is not a whole number are rejected; JSON allows NaN and Infinity.

        Would fail if one of these values reached the charts, where NaN or 0 breaks the logarithmic axis.
        """
        # a repetition count that is 0, a boolean or a string:
        cases: list[BrokenResults] = [
            BrokenResults(
                f"repetitions {v!r}",
                lambda d, v=v: d.update(repetitions=v),
                "repetitions must be a whole number of at least 1",
            )
            for v in (0, True, "7")
        ]
        # a validation method that is a boolean instead of a whole number:
        cases.append(
            BrokenResults(
                "method true", replaced("config", "method", True), "wrong type"
            )
        )
        # two `seconds_per_operation` values or four pass counts for three repetitions:
        cases += [
            BrokenResults(f"{key} of length {n}", resized(key, n), "not 3 repetitions")
            for key, n in (("seconds_per_operation", 2), ("passes", 4))
        ]
        # seconds that are NaN, infinite, 0, negative, outside `report.SECONDS_RANGE`, a string or a boolean:
        cases += [
            BrokenResults(
                f"seconds {v!r}",
                replaced("seconds_per_operation", 0, v),
                "seconds outside 1e-12 to 1e+06",
            )
            for v in (math.nan, math.inf, 0, -1e-6, 1e-13, 2e6, 10**400, "1e-06", True)
        ]
        # pass counts that are 0, a fraction or a boolean:
        cases += [
            BrokenResults(
                f"passes {v!r}",
                replaced("passes", 0, v),
                "a pass count that is not a whole number of at least 1",
            )
            for v in (0, 2.5, True)
        ]
        # a fingerprint field that is a string or a boolean:
        cases += [
            BrokenResults(
                f"fingerprint commits {v!r}",
                replaced("fingerprint", "commits", v),
                "a fingerprint field that is not a whole number",
            )
            for v in ("0", True)
        ]
        self.assert_rejected(cases)

    def test_rejects_wrong_keys_and_provenance(self) -> None:
        """Results with a key missing, an unknown provenance key, or a provenance field of the wrong type (a CPU
        that is a number, a dirty flag that is a string, zero cores) are rejected.

        Would fail if the report crashed on such a file with a KeyError or TypeError instead of naming the file, or
        wrote a wrong value into the provenance on the page.
        """
        # a missing or unknown key makes a lookup or a dataclass constructor fail with a message naming the key; a
        # CPU that is a number and a dirty flag that is a string are of the wrong type:
        wrong_type: str = "a provenance field of the wrong type"
        cases: list[BrokenResults] = [
            BrokenResults(
                "passes missing",
                lambda d: entry(d, "python", FIRST).pop("passes"),
                "'passes'",
            ),
            BrokenResults("cpu missing", lambda d: d["provenance"].pop("cpu"), "'cpu'"),
            BrokenResults(
                "an unknown provenance key",
                provenance_field("host", "lab-7"),
                "'host'",
            ),
            BrokenResults("cpu 42", provenance_field("cpu", 42), wrong_type),
            BrokenResults(
                "git_dirty 'no'", provenance_field("git_dirty", "no"), wrong_type
            ),
        ]
        # zero cores, or a boolean instead of a number of cores:
        cases += [
            BrokenResults(
                f"cores {v!r}",
                provenance_field("cores", v),
                "cores must be a whole number of at least 1 or null",
            )
            for v in (0, True)
        ]
        self.assert_rejected(cases)

    def test_accepts_seconds_at_the_limits_of_the_range(self) -> None:
        """Seconds of exactly 1e-12 and 1e6, the limits of `report.SECONDS_RANGE`, are accepted.

        Would fail if the range check excluded its limits.
        """
        for seconds in report.SECONDS_RANGE:
            with (
                self.subTest(seconds=seconds),
                tempfile.TemporaryDirectory() as directory,
            ):
                # set the first seconds value of Python's measurement of the first benchmark to the limit; the results
                # load and keep it:
                data: dict[str, Any] = fake_results()
                replaced("seconds_per_operation", 0, seconds)(data)
                results: report.Results = report.load_results(
                    write_results(Path(directory), data)
                )
                self.assertIn(
                    seconds, results.pairs[FIRST].python.seconds_per_operation
                )

    def test_rejects_a_missing_file(self) -> None:
        """A results file that does not exist is rejected with a ValueError naming it.

        Would fail if a mistyped ``--results`` stopped the report with a traceback instead of a message.
        """
        with tempfile.TemporaryDirectory() as directory:
            path: Path = Path(directory) / "missing.json"
            with self.assertRaisesRegex(ValueError, "missing.json.*No such file"):
                report.load_results(path)

    def test_rejects_a_file_that_is_not_a_results_object(self) -> None:
        """A file with invalid JSON, or JSON that is not an object, is rejected with a ValueError naming it.

        Would fail if a cut-off or wrong file stopped the report with a traceback instead of a message.
        """
        # JSON cut off in the middle, which `json.loads` rejects, and
        # a list, which cannot be indexed by the key ``repetitions``:
        for content, problem in (
            ('{"repetitions": 7,', "Expecting"),
            ("[]", "list indices"),
        ):
            with self.subTest(content=content):
                self.assert_file_rejected(content, problem)


class ChartScaleTest(unittest.TestCase):
    """Checks where the charts put values on their axes."""

    def test_line_chart_maps_the_first_and_last_decade_to_the_plot_corners(
        self,
    ) -> None:
        """A point at the first decade of both axes lies at the bottom left of the plot, one at the last decades at
        the top right.

        Would fail if the time axis grew downwards, as SVG's y does, or an axis were offset or scaled wrongly.
        """
        # a chart with a Python point at the first decade of both axes (100 objects, 10 ns) and a Rust point at the
        # last ones (10 000 objects, 1 µs):
        chart: str = charts.line_chart(
            charts.Labels("scale", "Scale", "Two points."),
            [
                charts.Series("python", [charts.Point(100, 1e-8, 1e-8, 1e-8)]),
                charts.Series("rust", [charts.Point(10_000, 1e-6, 1e-6, 1e-6)]),
            ],
            charts.LogAxis([2, 3, 4], str),
            charts.LogAxis([-8, -7, -6], charts.format_decade),
        )
        # find the Python circle and the Rust square in the drawn chart:
        parser: PageParser = parse(chart)
        circle: dict[str, str] = next(
            e.attributes for e in parser.elements if e.test_id == "marker-python"
        )
        square: dict[str, str] = next(
            e.attributes for e in parser.elements if e.test_id == "marker-rust"
        )
        # the circle's centre lies at the bottom left corner of the plot:
        bottom: float = charts.LINE_CHART_HEIGHT - charts.LINE_CHART_BOTTOM
        self.assertEqual(
            (charts.LINE_CHART_LEFT, bottom), (float(circle["cx"]), float(circle["cy"]))
        )
        # the square's x and y are its top left corner, 3.5 units from its centre:
        self.assertEqual(
            (charts.LINE_CHART_WIDTH - charts.LINE_CHART_RIGHT, charts.LINE_CHART_TOP),
            (float(square["x"]) + 3.5, float(square["y"]) + 3.5),
        )

    def test_bar_lengths_are_proportional_and_labelled_after_their_end(self) -> None:
        """A bar of half the last tick is half as long as a bar of the last tick, which ends at the last grid line;
        the label of each bar starts 4 units after its end.

        Would fail if the scale did not start at 0 or ignored the last tick, so that bars were not comparable, or a
        label were placed at a fixed position, so that it overlapped a long bar or floated far from a short one.
        """
        # one row with a Rust bar of 100 and a Python bar of 50; 100 is also the last tick of the axis:
        row: charts.BarRow = charts.BarRow(
            "row",
            [charts.Bar("rust", 100.0, "full"), charts.Bar("python", 50.0, "half")],
        )
        labels: charts.Labels = charts.Labels("bars", "Bars", "Two bars.")
        parser: PageParser = parse(
            charts.bar_chart(labels, [charts.BarGroup("group", [row])], str, "value")
        )
        # the bars in the order they are drawn, Rust's full bar first; the half bar is half as long:
        full, half = [
            e.attributes
            for e in parser.elements
            if e.test_id in ("bar-rust", "bar-python")
        ]
        self.assertAlmostEqual(
            float(full["width"]) / 2, float(half["width"]), delta=0.1
        )
        # the full bar ends at the rightmost grid line, the one of the last tick:
        last_grid_line: float = max(
            float(e.attributes["x1"]) for e in parser.elements if e.test_id == "grid"
        )
        self.assertAlmostEqual(
            float(full["x"]) + float(full["width"]), last_grid_line, delta=0.1
        )
        # each bar's label starts (text-anchor start) 4 units to the right of the bar's end:
        bar_labels: list[Element] = [
            e for e in parser.elements if e.test_id == "bar-label"
        ]
        self.assertEqual(["full", "half"], [e.text for e in bar_labels])
        for rect, text in zip((full, half), bar_labels):
            with self.subTest(label=text.text):
                self.assertEqual("start", text.attributes["text-anchor"])
                self.assertAlmostEqual(
                    float(rect["x"]) + float(rect["width"]) + 4,
                    float(text.attributes["x"]),
                    delta=0.1,
                )


class FakePageTest(unittest.TestCase):
    """Checks the page written from the fake results, whose numbers are known."""

    page: str
    parser: PageParser

    @classmethod
    def setUpClass(cls) -> None:
        """Renders the page of the fake results once and parses it."""
        cls.page = report.render(report.parse_results(fake_results()))
        cls.parser = parse(cls.page)

    def test_numbers_computed_from_the_medians(self) -> None:
        """The summary names the smallest and largest speed-up (2.0× for ``read_only`` with method 1, 70× for
        ``get`` on 10 000 objects), the transactions chart the most transactions per second of each language
        (1 / 80 µs and 1 / 300 µs), and a table row the medians, ranges, speed-up, commits and aborts.

        Would fail if a speed-up were inverted, transactions per second were not 1 / median, the minimum and
        maximum of a range or the commits and aborts were swapped.
        """
        # the template may wrap a sentence anywhere; no-break spaces stay, as they are part of the numbers:
        text: str = re.sub(r"[ \n]+", " ", self.page)
        self.assertIn("Rust is between 2.0× and 70× as fast as Python.", text)
        # the transactions chart's description, with the most transactions per second: Rust 1 / 80 µs,
        # Python 1 / 300 µs (both read_only):
        self.assertIn(
            "Rust reaches up to 12\u202f500 transactions per second, Python up to 3\u202f333.",
            self.page,
        )
        # the table row of read_write_contention with method 2: Python's median of 25 ms and its range from half to
        # twice that, the same for Rust's 1 ms, the speed-up of 25×, and the fingerprint's 17 commits and 0 aborts:
        self.assertIn(
            "<tr><td>read_write_contention</td><td>2</td><td>1\u202f000</td>"
            "<td>25.0\u00a0ms</td><td>12.5\u00a0ms – 50.0\u00a0ms</td>"
            "<td>1.00\u00a0ms</td><td>500\u00a0µs – 2.00\u00a0ms</td><td>25×</td>"
            "<td>17</td><td>0</td></tr>",
            self.page,
        )

    def test_workload_text_takes_its_numbers_from_the_results(self) -> None:
        """The text on the workloads names the reads, transactions and pairs per pass, the store sizes and the
        repetitions of the results, and the minimum time of a repetition; the template has a placeholder for each.

        Would fail if a number were typed into the template instead of a placeholder, a placeholder were missing,
        or one were filled from a benchmark with another number.
        """
        for placeholder in (
            "read_operations",
            "update_commit_operations",
            "read_only_operations",
            "read_write_disjoint_operations",
            "contention_pairs",
            "micro_sizes",
            "tps_size",
            "min_milliseconds",
            "repetitions",
        ):
            self.assertIn(f"${placeholder}", report.PAGE.template)
        # the template wraps its text, so line breaks count as spaces:
        text: str = re.sub(r"[ \n]+", " ", self.page)
        for phrase in (
            "<code>read</code>: 100 reads",
            "<code>update_commit</code>: 1\u202f000 transactions of one update",
            "<code>read_only</code>: 1\u202f000 transactions reading",
            "<code>read_write_disjoint</code>: 1\u202f000 transactions each reading",
            "<code>read_write_contention</code>: 500 pairs",
            "run with 100, 1\u202f000 and 10\u202f000 objects",
            "with 1\u202f000 objects and both validation methods",
            "at least 50&nbsp;ms",
            "3 repetitions are measured",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_chart_labels_and_texts_show_the_fake_numbers(self) -> None:
        """The charts write the numbers of the fake results: the most transactions per second (Rust, 1 / 80 µs),
        the largest speed-up (70×) and a micro chart's description with the medians at 10 000 objects.

        Would fail if the bars of the transactions chart took the other language's value, a speed-up were
        inverted, or a description mixed up the languages.
        """
        # the labels of all bars, in the transactions chart and in the speed-up chart:
        labels: list[str] = [
            e.text for e in self.parser.elements if e.test_id == "bar-label"
        ]
        self.assertIn("Rust 12\u202f500", labels)
        self.assertIn("Python 3\u202f333", labels)
        self.assertIn("70×", labels)
        # the description of each chart by its id, which the SVG names in aria-describedby:
        descriptions: dict[str, str] = {
            s.element.attributes["aria-describedby"]: s.desc.text
            for s in self.parser.svgs
            if s.desc is not None
        }
        self.assertEqual(
            "With 10\u202f000 objects: Python 16.0\u00a0µs, Rust 400\u00a0ns per operation. "
            "All numbers are in the table below.",
            descriptions["micro-bulkload-desc"],
        )

    def test_provenance_shows_every_field(self) -> None:
        """The page lists every field of the provenance with its value, and whether the working tree had changes
        as yes or no.

        Would fail if a field were left out, two fields swapped their values, or the flag for uncommitted changes
        were flipped.
        """
        # the description list of the fake provenance: one line per field, in this order:
        rows: list[str] = [
            "<dt>Date</dt><dd>2026-01-02T03:04:05+00:00</dd>",
            "<dt>CPU</dt><dd>Test CPU</dd>",
            "<dt>Cores</dt><dd>8</dd>",
            "<dt>Architecture</dt><dd>arm64</dd>",
            "<dt>Operating system</dt><dd>TestOS-1.0</dd>",
            "<dt>Python</dt><dd>3.12.0</dd>",
            "<dt>Rust</dt><dd>rustc 1.0.0 (0000000 2026-01-01)</dd>",
            "<dt>Commit</dt><dd>0123456789abcdef0123456789abcdef01234567</dd>",
            "<dt>Uncommitted changes</dt><dd>yes</dd>",
        ]
        self.assertIn("\n".join(rows), self.page)
        # the same results without uncommitted changes show ``no``:
        data: dict[str, Any] = fake_results()
        data["provenance"]["git_dirty"] = False
        page: str = report.render(report.parse_results(data))
        self.assertIn("<dt>Uncommitted changes</dt><dd>no</dd>", page)

    def test_range_bars_reach_from_the_minimum_to_the_maximum(self) -> None:
        """In the micro charts, each range bar runs from the minimum below the median's marker to the maximum above
        it; with repetitions of half, once and twice the median, both ends are equally far from the marker on the
        logarithmic axis.

        Would fail if a range bar were drawn from the median, or its ends were swapped or scaled wrongly.
        """
        # the Python markers and range bars of the micro charts, one of each per point and in the same order:
        circles: list[Element] = [
            e for e in self.parser.elements if e.test_id == "marker-python"
        ]
        ranges: list[Element] = [
            e for e in self.parser.elements if e.test_id == "range-python"
        ]
        self.assertEqual(len(circles), len(ranges))
        for circle, range_bar in zip(circles, ranges):
            with self.subTest(x=circle.attributes["cx"]):
                median: float = float(circle.attributes["cy"])
                low: float = float(range_bar.attributes["y1"])
                high: float = float(range_bar.attributes["y2"])
                # SVG's y grows downwards: the minimum lies below the median, the maximum above it
                self.assertGreater(low, median)
                self.assertLess(high, median)
                self.assertAlmostEqual(low - median, median - high, delta=0.2)

    def test_markers_are_circles_for_python_and_squares_for_rust(self) -> None:
        """Each of the 12 Python points of the micro charts is a circle, each of the 12 Rust points a square.

        Would fail if the shapes were swapped or equal, so that the languages differed only by colour.
        """
        python: list[Element] = [
            e for e in self.parser.elements if e.test_id == "marker-python"
        ]
        rust: list[Element] = [
            e for e in self.parser.elements if e.test_id == "marker-rust"
        ]
        # 4 micro charts with 3 store sizes each give 12 points per language:
        self.assertEqual(["circle"] * 12, [e.tag for e in python])
        self.assertEqual(["rect"] * 12, [e.tag for e in rust])
        # each Rust marker is as wide as high:
        for square in rust:
            self.assertEqual(square.attributes["width"], square.attributes["height"])

    def test_every_chart_element_has_a_test_id(self) -> None:
        """Every drawn element in the charts (all but ``title`` and ``desc``) has a ``data-testid`` of a known kind,
        by which the tests select it.

        Would fail if a new chart element came without one, so that a test would have to select it by its CSS class
        or its text, or if an id were misspelled.
        """
        # every element inside an SVG, except the SVG itself and its title and description:
        drawn: list[Element] = [
            e
            for e in self.parser.elements
            if e.tag not in ("svg", "title", "desc")
            and any(a.tag == "svg" for a in e.ancestors)
        ]
        # none of them lacks a data-testid, and together they use exactly these kinds:
        self.assertEqual([], [e.tag for e in drawn if not e.test_id])
        self.assertEqual(
            {
                "heading",
                "grid",
                "axis",
                "y-tick",
                "x-tick",
                "axis-title",
                "row-label",
                "bar-label",
                "bar-python",
                "bar-rust",
                "line-python",
                "line-rust",
                "range-python",
                "range-rust",
                "marker-python",
                "marker-rust",
            },
            {e.test_id for e in drawn},
        )

    def test_micro_charts_share_their_time_axis(self) -> None:
        """All four micro charts label their time axis from 10 ns to 10 ms, the range of all micro-benchmarks, even
        though ``bulkload`` alone stays below 100 µs.

        Would fail if each chart got its own axis, so that equal heights in two charts meant different times.
        """
        # the labels of 10 ns (10**-8) to 10 ms (10**-2):
        expected: list[str] = [charts.format_decade(e) for e in range(-8, -1)]
        # the four SVGs in the section of the micro-benchmarks each label their time axis with all these decades:
        micro: list[Svg] = [
            s for s in self.parser.svgs if s.element.inside("chart-micro")
        ]
        self.assertEqual(4, len(micro))
        for svg in micro:
            with self.subTest(chart=svg.element.attributes["aria-labelledby"]):
                labels: list[str] = [
                    e.text
                    for e in self.parser.elements
                    if e.test_id == "y-tick" and e.within(svg.element)
                ]
                self.assertEqual(expected, labels)

    def test_unknown_cores_are_shown_as_unknown(self) -> None:
        """Results without a number of cores (``null``, as `os.cpu_count` may return) show the cores as unknown.

        Would fail if None were rejected or written as ``None`` on the page.
        """
        data: dict[str, Any] = fake_results()
        data["provenance"]["cores"] = None
        page: str = report.render(report.parse_results(data))
        self.assertIn("<dt>Cores</dt><dd>unknown</dd>", page)

    def test_values_are_escaped_exactly_once(self) -> None:
        """A provenance value with markup characters appears escaped once, and a ``$placeholder`` in it is written
        as it is, while the charts and table rows stay markup.

        Would fail if a value were inserted unescaped, escaped twice (``&amp;lt;``), the generated markup were
        escaped, or a value were substituted into the template a second time.
        """
        data: dict[str, Any] = fake_results()
        # a CPU with markup characters, and an operating system that looks like placeholders of the template:
        data["provenance"].update(cpu='A<b>&"c', os="$table_rows ${x}")
        page: str = report.render(report.parse_results(data))
        # the CPU appears once, escaped once, and never unescaped:
        self.assertEqual(1, page.count("<dd>A&lt;b&gt;&amp;&quot;c</dd>"))
        self.assertNotIn("A<b>", page)
        self.assertNotIn("&amp;lt;", page)
        # the 6 charts and the 18 table rows are still markup, and the placeholders in the operating system are
        # written as they are, not filled:
        self.assertEqual(6, page.count("<svg "))
        self.assertEqual(18, page.count("<tr><td>"))
        self.assertIn("<dd>$table_rows ${x}</dd>", page)


class PageStructureTest(unittest.TestCase):
    """Checks the structure of the page written from the committed results."""

    page: str
    parser: PageParser

    @classmethod
    def setUpClass(cls) -> None:
        """Renders the page once and parses it."""
        cls.page = report.render(report.load_results(run.RESULTS))
        cls.parser = parse(cls.page)

    def by_test_id(self, test_id: str) -> Element:
        """Returns the only element with ``data-testid`` `test_id`."""
        found: list[Element] = [e for e in self.parser.elements if e.test_id == test_id]
        self.assertEqual(1, len(found), test_id)
        return found[0]

    def svgs_inside(self, test_id: str) -> list[Svg]:
        """Returns the SVGs inside the element with ``data-testid`` `test_id`."""
        self.by_test_id(test_id)
        return [s for s in self.parser.svgs if s.element.inside(test_id)]

    def test_charts_table_and_provenance_are_present(self) -> None:
        """The page has four micro-benchmark charts, one chart each of transactions per second and speed-up, a
        table with one body row per benchmark, and the provenance of the run.

        Would fail if a chart or section went missing from the template or the table lost or duplicated rows.
        """
        # `svgs_inside` and `by_test_id` also check that each section is on the page exactly once:
        self.assertEqual(4, len(self.svgs_inside("chart-micro")))
        self.assertEqual(1, len(self.svgs_inside("chart-tps")))
        self.assertEqual(1, len(self.svgs_inside("chart-speedup")))
        self.by_test_id("results-table")
        # the rows in the table's body, i.e. without the header row:
        body_rows: list[Element] = [
            e
            for e in self.parser.elements
            if e.tag == "tr"
            and e.inside("results-table")
            and any(a.tag == "tbody" for a in e.ancestors)
        ]
        self.assertEqual(18, len(body_rows))
        self.by_test_id("provenance")

    def test_every_chart_is_an_image_labelled_by_its_title_and_description(
        self,
    ) -> None:
        """Every SVG has the role ``img`` and a non-empty ``<title>`` and ``<desc>`` whose ids it names in
        ``aria-labelledby`` and ``aria-describedby``.

        Would fail if a screen reader found no name or description for a chart because the ids did not match or
        the texts were empty, or read the chart's parts one by one.
        """
        self.assertEqual(6, len(self.parser.svgs))
        for svg in self.parser.svgs:
            attributes: dict[str, str] = svg.element.attributes
            with self.subTest(labelledby=attributes.get("aria-labelledby")):
                self.assertEqual("img", attributes.get("role"))
                assert svg.title is not None and svg.desc is not None
                self.assertEqual(
                    svg.title.attributes.get("id"), attributes.get("aria-labelledby")
                )
                self.assertEqual(
                    svg.desc.attributes.get("id"), attributes.get("aria-describedby")
                )
                self.assertNotEqual("", svg.title.text.strip())
                self.assertNotEqual("", svg.desc.text.strip())

    def test_ids_are_unique_and_every_reference_points_to_one(self) -> None:
        """No two elements share an id, and every id named in ``aria-labelledby``, ``aria-describedby``, a
        ``href="#…"`` or a ``url(#…)`` exists.

        Would fail if two charts got the same chart id, so that a label pointed at the wrong chart, or a chart named
        a label, gradient or link target that is not on the page.
        """
        # count how often each id occurs on the page; none occurs twice:
        ids: Counter[str] = Counter(
            e.attributes["id"] for e in self.parser.elements if "id" in e.attributes
        )
        self.assertEqual([], [i for i, count in ids.items() if count > 1])
        # collect every id the page refers to: in ``url(#…)``, in the aria attributes and in links within the page:
        references: list[str] = re.findall(r"url\(#([^)]+)\)", self.page)
        for element in self.parser.elements:
            for name in ("aria-labelledby", "aria-describedby"):
                references += element.attributes.get(name, "").split()
            for name in ("href", "xlink:href"):
                if element.attributes.get(name, "").startswith("#"):
                    references.append(element.attributes[name][1:])
        # at least the two aria references of each of the 6 charts, and each one names an existing id:
        self.assertGreaterEqual(len(references), 12)
        self.assertEqual([], [r for r in references if r not in ids])

    def test_page_has_no_script_and_loads_nothing(self) -> None:
        """The page has no script, no embedded or linked element, and no attribute, ``url(…)`` or ``@import``
        that refers to anything outside the page; the namespaces in ``xmlns`` are names, not loaded.

        Would fail if a script, a web font, an image or a style sheet from elsewhere were added to the template,
        which the page promises not to have.
        """
        # no element that runs or embeds anything:
        embedding: set[str] = {"script", "link", "iframe", "object", "embed", "img"}
        self.assertEqual(
            [], [e.tag for e in self.parser.elements if e.tag in embedding]
        )
        # no attribute that links to anything but an id on the page,
        # and no ``url(…)`` or ``@import`` that loads from elsewhere:
        linking: tuple[str, ...] = ("src", "srcset", "href", "xlink:href", "action")
        outside: list[str] = [
            e.attributes[name]
            for e in self.parser.elements
            for name in linking
            if name in e.attributes and not e.attributes[name].startswith("#")
        ]
        self.assertEqual([], outside)
        self.assertEqual([], re.findall(r"url\((?!#)|@import", self.page))

    def test_head_declares_utf8_and_a_content_security_policy(self) -> None:
        """The page declares ``<meta charset="utf-8">`` within its first 1024 bytes, and its head has a
        Content-Security-Policy meta tag that allows nothing by default.

        Would fail if a longer comment pushed the charset beyond the bytes browsers look at, so that µ, × and the
        special spaces showed up garbled, or the policy were removed or moved out of the head, where browsers ignore
        it, so that a script injected through a value would run.
        """
        # the byte position of the charset declaration in the UTF-8 encoded page:
        position: int = self.page.encode("utf-8").find(b'<meta charset="utf-8">')
        self.assertTrue(0 <= position < 1024, position)
        # exactly one Content-Security-Policy, directly inside the head, that allows nothing by default:
        policies: list[Element] = [
            e
            for e in self.parser.elements
            if e.attributes.get("http-equiv", "").lower() == "content-security-policy"
        ]
        self.assertEqual(1, len(policies))
        self.assertEqual(["html", "head"], [a.tag for a in policies[0].ancestors])
        self.assertIn("default-src 'none'", policies[0].attributes["content"])

    def test_no_placeholder_is_left(self) -> None:
        """No ``$name`` or ``${name}`` of the template is left on the page.

        Would fail if the template had a placeholder that `render` does not fill and `render` used
        ``safe_substitute``, which keeps it on the page instead of raising.
        """
        self.assertEqual([], re.findall(r"\$[A-Za-z_{]\w*", self.page))


class CommittedPageTest(unittest.TestCase):
    """Checks that the committed page is the one the committed results give, and the command line of the report."""

    def test_committed_page_is_up_to_date(self) -> None:
        """Rendering the committed results gives exactly the committed page, byte for byte.

        Would fail if the page were edited by hand, the template or the charts changed without writing the page
        again, the page were saved with other line endings, or the output depended on anything but the results
        (e.g. the time or the order of a set).
        """
        self.assertEqual(
            report.REPORT.read_bytes(),
            report.render(report.load_results(run.RESULTS)).encode("utf-8"),
            f"benchmarks/index.html is out of date; run `{run.REPORT_COMMAND}`",
        )

    def test_committed_page_has_one_chart_element_per_line(self) -> None:
        """No line of the committed page is longer than 400 characters, and each line of a chart holds one SVG
        element.

        Would fail if a chart were written on one line, so that a new measurement changed the page as one huge
        line instead of line by line.
        """
        lines: list[str] = committed_page().splitlines()
        self.assertEqual([], [n for n, line in enumerate(lines, 1) if len(line) > 400])
        # from a line that starts with <svg up to and including the line </svg>, each line opens at most one element:
        in_chart: bool = False
        for number, line in enumerate(lines, 1):
            in_chart = in_chart or line.startswith("<svg")
            if in_chart:
                with self.subTest(line=number):
                    self.assertLessEqual(len(re.findall(r"<[a-z]", line)), 1)
            in_chart = in_chart and line != "</svg>"

    def test_main_writes_the_page_of_the_given_results(self) -> None:
        """`main --results ... --output ...` writes the page of the given results to the given file, creating its
        folder.

        Would fail if `main` read the committed results instead of ``--results``, ignored ``--output``, needed an
        existing folder or wrote another encoding than UTF-8.
        """
        with tempfile.TemporaryDirectory() as directory:
            # write the fake results and let `main` write their page into a folder that does not exist yet:
            results: Path = write_results(Path(directory), fake_results())
            output: Path = Path(directory) / "new" / "page.html"
            with contextlib.redirect_stderr(io.StringIO()):
                report.main(["--results", str(results), "--output", str(output)])
            # the written file is the page that `render` makes of these results:
            written: str = output.read_text(encoding="utf-8")
            expected: str = report.render(report.load_results(results))
        self.assertEqual(expected, written)
        # the fake results give another page than the committed ones:
        self.assertNotEqual(committed_page(), written)

    def test_main_refuses_to_overwrite_the_results(self) -> None:
        """`main` exits with status 2 if ``--output`` is the results file, which stays unchanged.

        Would fail if a mistyped ``--output`` could replace the measured results with the page.
        """
        with tempfile.TemporaryDirectory() as directory:
            results: Path = write_results(Path(directory), fake_results())
            before: bytes = results.read_bytes()
            # the same file under another name, a hard link:
            output: Path = Path(directory) / "link.json"
            os.link(results, output)
            # `main` stops with an argparse error, which exits with status 2, and leaves the results unchanged:
            errors: io.StringIO = io.StringIO()
            with contextlib.redirect_stderr(errors):
                with self.assertRaises(SystemExit) as caught:
                    report.main(["--results", str(results), "--output", str(output)])
            self.assertEqual(before, results.read_bytes())
        self.assertEqual(2, caught.exception.code)
        self.assertIn("--output must not be the results file", errors.getvalue())

    def test_main_rejects_the_results_of_a_quick_run(self) -> None:
        """`main` exits with status 2 and a message naming the results file and the missing benchmarks for the
        results of a quick run, and writes no page.

        Would fail if a report of a quick run, with a third of the micro-benchmarks, could replace the page.
        """
        with tempfile.TemporaryDirectory() as directory:
            # the results of a quick run, with only the smallest store size of the micro-benchmarks:
            results: Path = write_results(Path(directory), fake_results(quick=True))
            output: Path = Path(directory) / "page.html"
            # `main` stops with an argparse error, which exits with status 2:
            errors: io.StringIO = io.StringIO()
            with contextlib.redirect_stderr(errors):
                with self.assertRaises(SystemExit) as caught:
                    report.main(["--results", str(results), "--output", str(output)])
            self.assertFalse(output.exists())
        self.assertEqual(2, caught.exception.code)
        self.assertIn(str(results), errors.getvalue())
        self.assertIn("missing [", errors.getvalue())


class ReportHintTest(unittest.TestCase):
    """Checks the command that `run` suggests for writing the report."""

    def test_report_hint(self) -> None:
        """For the default results, also given as a relative path, the hint is the report command alone; for
        results elsewhere, it reads them and writes the page next to them with the suffix ``.html``, or with
        ``-report.html`` if that would overwrite the results or the committed page. Paths are quoted for the shell.

        Would fail if the paths were compared without resolving them, the hint wrote the page of a trial run over
        the committed page or its results, or a path with a space or a leading "-" broke the command.
        """
        # the default results, given as an absolute or a relative path:
        for path in (run.RESULTS, Path(os.path.relpath(run.RESULTS))):
            with self.subTest(path=str(path)):
                self.assertEqual(run.REPORT_COMMAND, run.report_hint(path))
        # results elsewhere: the page goes next to them with the suffix .html, and a path with a space is quoted:
        self.assertEqual(
            f"{run.REPORT_COMMAND} --results=/trials/fast.json --output=/trials/fast.html",
            run.report_hint(Path("/trials/fast.json")),
        )
        self.assertEqual(
            f"{run.REPORT_COMMAND} --results='/my trials/a.json' --output='/my trials/a.html'",
            run.report_hint(Path("/my trials/a.json")),
        )
        # with "=", a path that starts with "-" is not read as an option:
        self.assertEqual(
            f"{run.REPORT_COMMAND} --results=-x.json --output=-x.html",
            run.report_hint(Path("-x.json")),
        )
        # the page would overwrite the results or the committed page, so it gets another name:
        for results, page in (
            (Path("/trials/fast.html"), "/trials/fast-report.html"),
            (
                run.ROOT / "benchmarks" / "index.json",
                shlex.quote(f"{run.ROOT}/benchmarks/index-report.html"),
            ),
        ):
            with self.subTest(results=str(results)):
                self.assertTrue(run.report_hint(results).endswith(f"--output={page}"))

    def test_main_prints_the_hint_after_a_full_run_only(self) -> None:
        """`run.main` prints the hint after a full run, but not after ``--quick``, whose results the report
        rejects.

        Would fail if the hint were missing after a full run or suggested a report of a quick run.
        """
        for quick in (False, True):
            with self.subTest(quick=quick), tempfile.TemporaryDirectory() as directory:
                output: Path = Path(directory) / "results.json"
                errors: io.StringIO = io.StringIO()
                # `run.run` is replaced by a stub, so no benchmark runs; `main` writes the stub's results and prints
                # its messages to stderr:
                with mock.patch.object(run, "run", return_value={"repetitions": 3}):
                    with contextlib.redirect_stderr(errors):
                        run.main(["--output", str(output)] + ["--quick"] * quick)
                # after a full run, the hint follows the line naming the written file:
                expected: list[str] = [f"wrote {output}"]
                if not quick:
                    hint: str = run.report_hint(output)
                    expected.append(f"write the HTML report with: {hint}")
                self.assertEqual(expected, errors.getvalue().splitlines())


if __name__ == "__main__":
    unittest.main()
