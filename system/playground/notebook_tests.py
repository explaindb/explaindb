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

"""Runs the unit tests of a notebook so that a failing test fails the notebook run."""

from __future__ import annotations

import unittest


def run_notebook_tests(*test_cases: type[unittest.TestCase]) -> None:
    """Runs the tests of the given test case classes and prints the same report as ``unittest.main`` with ``-v``.

    A notebook calls this instead of ``unittest.main(..., exit=False)``, which only prints a failing test: the cell
    ends normally, and so does a run of the whole notebook, e.g. in the CI job that runs every notebook. This
    function raises an AssertionError instead, so the cell stops with an error and the notebook run fails; a Jupyter
    kernel keeps running. The AssertionError names every test that failed or raised an error.

    @param test_cases: the test case classes whose tests are run.
    """
    loader: unittest.TestLoader = unittest.TestLoader()
    suite: unittest.TestSuite = unittest.TestSuite(
        loader.loadTestsFromTestCase(case) for case in test_cases
    )
    # the runner writes to sys.stderr like unittest.main, so a notebook shows the same report:
    result: unittest.TestResult = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        broken: list[str] = [test.id() for test, _ in result.failures + result.errors]
        raise AssertionError("Failing notebook tests: " + ", ".join(broken))
