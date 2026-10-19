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

"""Tests for the number formatting and the ticks of the charts of the benchmark report."""

import unittest

from system.benchmarks import charts


class FormatTest(unittest.TestCase):
    """Checks the numbers and axis ticks the charts and the table show."""

    def test_format_seconds_picks_the_unit_with_three_significant_digits(self) -> None:
        """Durations from below a nanosecond to seconds get three significant digits and their unit, separated by
        a no-break space; the unit is chosen after rounding, so 999.7 ns is ``1.00 µs``.

        Would fail if the unit or the number of digits were chosen wrongly, the unit were chosen before rounding
        (``1000 ns``), or a normal space split number and unit.
        """
        cases: dict[float, str] = {
            1e-10: "0.100\u00a0ns",
            4.02e-08: "40.2\u00a0ns",
            9.997e-07: "1.00\u00a0µs",
            2.86e-06: "2.86\u00a0µs",
            9.997e-04: "1.00\u00a0ms",
            7.28e-03: "7.28\u00a0ms",
            2.5: "2.50\u00a0s",
        }
        for seconds, expected in cases.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(expected, charts.format_seconds(seconds))

    def test_format_count_groups_digits_by_three(self) -> None:
        """47 158 is written with a narrow no-break space between the groups of three digits.

        Would fail if the groups were separated by a comma or a normal space, which may break the line.
        """
        self.assertEqual("47\u202f158", charts.format_count(47158))

    def test_format_decade(self) -> None:
        """Each power of ten of seconds is labelled with 1, 10 or 100 of the largest unit it reaches, e.g. 10**-7
        as ``100 ns`` and 10**-6 as ``1 µs``; from 1 s on, seconds are used.

        Would fail if the label switched to the next unit too early or too late, e.g. ``0.1 µs`` or ``1000 ns``.
        """
        cases: dict[int, str] = {
            -9: "1\u00a0ns",
            -8: "10\u00a0ns",
            -7: "100\u00a0ns",
            -6: "1\u00a0µs",
            -3: "1\u00a0ms",
            0: "1\u00a0s",
            2: "100\u00a0s",
        }
        for exponent, expected in cases.items():
            with self.subTest(exponent=exponent):
                self.assertEqual(expected, charts.format_decade(exponent))

    def test_format_factor(self) -> None:
        """Factors from 9.95 on are written as whole numbers, smaller ones with one decimal.

        Would fail if the switch happened at 10 instead, so that 9.96 became ``10.0×``, or small factors lost their
        decimal.
        """
        cases: dict[float, str] = {
            76.3: "76×",
            9.96: "10×",
            9.94: "9.9×",
            2.54: "2.5×",
            0.4: "0.4×",
        }
        for factor, expected in cases.items():
            with self.subTest(factor=factor):
                self.assertEqual(expected, charts.format_factor(factor))

    def test_decades_enclose_low_and_high(self) -> None:
        """The decades run from the power of ten at or below the lowest value to the one at or above the highest:
        from 40 ns to 7 ms they are 10**-8 to 10**-2; powers of ten (e.g. the store sizes 100 to 10 000) are the
        ends; values within one decade (2 µs, 3 µs) give the two powers of ten around them, and so does a single
        power of ten (100).

        Would fail if a value fell outside the axis because of a wrong floor or ceiling, a power of ten got an extra
        decade, or an axis had a single decade, whose length of zero divides by zero in `LogAxis.position`.
        """
        cases: dict[tuple[float, float], list[int]] = {
            (4e-8, 7e-3): list(range(-8, -1)),
            (1e-6, 1e-3): [-6, -5, -4, -3],
            (100, 10_000): [2, 3, 4],
            (2e-6, 3e-6): [-6, -5],
            (100, 100): [2, 3],
        }
        for (low, high), expected in cases.items():
            with self.subTest(low=low, high=high):
                self.assertEqual(expected, charts.decades(low, high))

    def test_linear_ticks(self) -> None:
        """Ticks go from 0 in steps of 1, 2 or 5 times a power of ten, also below 1, up to the first tick at or
        above the maximum, e.g. 0, 20, 40, 60, 80 for 76; a maximum on a tick ends the axis, even if it is a little
        off in floating point (0.1 × 3 is 0.30000000000000004).

        Would fail if the step were not rounded to 1, 2 or 5 times a power of ten, a step below 1 became a whole
        number, the last tick were below the maximum, or a maximum on a tick got one more tick.
        """
        cases: dict[float, list[float]] = {
            76.0: [0, 20, 40, 60, 80],
            4.0: [0, 1, 2, 3, 4],
            2.5: [0, 0.5, 1, 1.5, 2, 2.5],
            1.0: [0, 0.2, 0.4, 0.6, 0.8, 1],
            100.0: [0, 20, 40, 60, 80, 100],
            59114.0: [0, 20_000, 40_000, 60_000],
            0.1 * 3: [0, 0.1, 0.2, 0.3],
        }
        for maximum, expected in cases.items():
            with self.subTest(maximum=maximum):
                ticks: list[float] = charts.linear_ticks(maximum)
                self.assertEqual(expected, [round(t, 9) for t in ticks])

    def test_coordinate(self) -> None:
        """Coordinates are rounded to 0.1, without ``.0`` and without a negative zero.

        Would fail if a value just below 0 were written as ``-0`` or whole numbers kept their ``.0``, which changes
        the page without changing the chart.
        """
        cases: dict[float, str] = {-0.04: "0", 12.0: "12", 12.34: "12.3"}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(expected, charts.coordinate(value))


if __name__ == "__main__":
    unittest.main()
