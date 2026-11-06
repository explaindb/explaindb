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

# Test modules use self-documenting method/class names, so pylint's naming and
# docstring checks are relaxed here.
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring
"""Tests for run_notebook_tests, which runs the unit tests of a notebook and fails the notebook if one of them fails."""

from __future__ import annotations

import contextlib
import io
import unittest

from system.playground.notebook_tests import run_notebook_tests

# The test case classes below are created inside functions, not at module level: unittest and pytest collect every
# test case class at module level and would run the failing ones as tests of this module.


def passing_case() -> type[unittest.TestCase]:
    """Returns a test case class whose two tests pass."""

    class Passing(unittest.TestCase):
        """Two passing tests without docstrings, so the runner prints each on one line ending in "ok"."""

        def test_sum(self) -> None:
            self.assertEqual(4, 2 + 2)

        def test_concatenation(self) -> None:
            self.assertEqual("ab", "a" + "b")

    return Passing


def failing_case() -> type[unittest.TestCase]:
    """Returns a test case class with one passing test and one test whose assertion fails."""

    class Failing(unittest.TestCase):
        """One passing and one failing test, without docstrings like the tests in :func:`passing_case`."""

        def test_right_sum(self) -> None:
            self.assertEqual(4, 2 + 2)

        def test_wrong_sum(self) -> None:
            self.assertEqual(5, 2 + 2)

    return Failing


def raising_case() -> type[unittest.TestCase]:
    """Returns a test case class with one test that raises an exception other than an assertion error."""

    class Raising(unittest.TestCase):
        """One test that looks up a key that does not exist."""

        def test_missing_key(self) -> None:
            self.assertEqual(1, {"a": 1}["b"])

    return Raising


class RunNotebookTestsTest(unittest.TestCase):
    """Running the tests of a notebook so that a failing test fails the notebook."""

    def test_names_a_failing_test(self) -> None:
        """A test whose assertion fails makes run_notebook_tests raise an AssertionError naming that test; the passing
        test of the same class is not named.

        Would fail if a failing test were only printed and the call returned normally, so the notebook run in CI
        stayed green.
        """
        # run the class with one passing and one failing test:
        Failing: type[unittest.TestCase] = failing_case()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(AssertionError) as caught:
                run_notebook_tests(Failing)

        # the message names the failing test by its id, but not the passing one:
        message: str = str(caught.exception)
        self.assertIn(Failing("test_wrong_sum").id(), message)
        self.assertNotIn("test_right_sum", message)

    def test_names_a_test_that_raises_an_error(self) -> None:
        """A test that raises another exception than an AssertionError (here a KeyError) makes run_notebook_tests
        raise an AssertionError naming that test.

        Would fail if only failed assertions counted and tests that crash with an error were ignored.
        """
        # run the class whose only test raises a KeyError:
        Raising: type[unittest.TestCase] = raising_case()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(AssertionError) as caught:
                run_notebook_tests(Raising)

        # the message names the test:
        self.assertIn(Raising("test_missing_key").id(), str(caught.exception))

    def test_returns_none_when_all_tests_pass(self) -> None:
        """If every test passes, run_notebook_tests returns None, and the runner's report ends in "OK".

        Would fail if passing tests raised an error, or if the report went to the stderr of the time of import
        instead of the stderr at the time of the call.
        """
        # run the class whose tests all pass, capturing the report; the call raises nothing and returns None:
        output: io.StringIO = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertIsNone(run_notebook_tests(passing_case()))

        # the last line of the report is the verdict of the whole run:
        self.assertEqual("OK", output.getvalue().splitlines()[-1])

    def test_runs_the_tests_of_several_classes(self) -> None:
        """Given several classes, run_notebook_tests runs the tests of all of them, prints one line per test, and
        names a failing test of the second class.

        Would fail if only the first class ran, or if a failure in a later class went unreported.
        """
        # run a passing class first and a class with a failing test second, capturing the report:
        Passing: type[unittest.TestCase] = passing_case()
        Failing: type[unittest.TestCase] = failing_case()
        output: io.StringIO = io.StringIO()
        with contextlib.redirect_stderr(output):
            with self.assertRaises(AssertionError) as caught:
                run_notebook_tests(Passing, Failing)

        # every test of both classes has its line in the report, e.g.
        # "test_sum (system.tests...Passing.test_sum) ... ok", the failing test ends in "FAIL":
        lines: list[str] = output.getvalue().splitlines()
        self.assertIn(f"{Passing('test_sum')} ... ok", lines)
        self.assertIn(f"{Passing('test_concatenation')} ... ok", lines)
        self.assertIn(f"{Failing('test_right_sum')} ... ok", lines)
        self.assertIn(f"{Failing('test_wrong_sum')} ... FAIL", lines)

        # the failing test of the second class is named:
        self.assertIn(Failing("test_wrong_sum").id(), str(caught.exception))

    def test_names_every_failing_test(self) -> None:
        """If one test fails and another raises an error, the AssertionError names both.

        Would fail if the message named only the first problem, so a student fixing it would not learn of the
        second one.
        """
        # run a class with a failing test and a class with a test that raises an error:
        Failing: type[unittest.TestCase] = failing_case()
        Raising: type[unittest.TestCase] = raising_case()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(AssertionError) as caught:
                run_notebook_tests(Failing, Raising)

        # the message names both tests:
        message: str = str(caught.exception)
        self.assertIn(Failing("test_wrong_sum").id(), message)
        self.assertIn(Raising("test_missing_key").id(), message)


if __name__ == "__main__":
    unittest.main()
