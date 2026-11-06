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
"""Tests that every notebook runs its unit tests with ``run_notebook_tests``.

The CI job ``ipynb_test`` runs every notebook in ``notebooks/``. A notebook that
runs its unit tests with ``unittest.main(..., exit=False)`` only prints a failing
test, so the notebook run and the CI job stay green.
``system.playground.notebook_tests.run_notebook_tests`` raises an
``AssertionError`` instead. These tests check the code cells of every notebook:
no notebook calls ``unittest.main``, and every notebook that defines a
``unittest.TestCase`` subclass calls ``run_notebook_tests``. Comment lines are
ignored, so a commented-out example call counts neither way.
"""

import json
import re
import unittest
from pathlib import Path
from typing import Any

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
NOTEBOOKS_DIR: Path = REPO_ROOT / "notebooks"

# A class statement with ``TestCase`` among its bases, e.g.
# ``class MyTest(unittest.TestCase):`` or ``class MyTest(TestCase):``.
TEST_CASE_PATTERN: re.Pattern[str] = re.compile(
    r"^\s*class\s+\w+\s*\([^)]*\bTestCase\b"
)


def code_lines(notebook: dict[str, Any]) -> list[str]:
    """Return the lines of all code cells of a notebook, without comment lines.

    A comment line is a line whose first non-blank character is ``#``. Markdown
    and raw cells are skipped.

    @param notebook: the notebook as parsed from its JSON file.
    @return: the non-comment lines of all code cells, in notebook order.
    """
    lines: list[str] = []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        # a notebook stores the source as a list of lines or as a single string:
        source: list[str] | str = cell["source"]
        text: str = "".join(source) if isinstance(source, list) else source
        lines.extend(
            line for line in text.splitlines() if not line.strip().startswith("#")
        )
    return lines


def calls_unittest_main(lines: list[str]) -> bool:
    """Return whether one of the lines calls ``unittest.main``.

    @param lines: code lines as returned by :func:`code_lines`.
    @return: True if a line contains ``unittest.main(``.
    """
    return any("unittest.main(" in line for line in lines)


def defines_test_case(lines: list[str]) -> bool:
    """Return whether one of the lines defines a ``TestCase`` subclass.

    @param lines: code lines as returned by :func:`code_lines`.
    @return: True if a line matches :data:`TEST_CASE_PATTERN`.
    """
    return any(TEST_CASE_PATTERN.match(line) for line in lines)


def calls_run_notebook_tests(lines: list[str]) -> bool:
    """Return whether one of the lines calls ``run_notebook_tests``.

    The import line names the function without a parenthesis and is no call.

    @param lines: code lines as returned by :func:`code_lines`.
    @return: True if a line contains ``run_notebook_tests(``.
    """
    return any("run_notebook_tests(" in line for line in lines)


def notebook_code_lines() -> dict[str, list[str]]:
    """Return the code lines of every notebook in ``notebooks/``.

    Non-recursive on purpose, like ``test_readme_notebooks.py``: Jupyter's
    git-ignored ``.ipynb_checkpoints/`` would otherwise be checked locally but
    not in CI.

    @return: a map from notebook file name to the result of :func:`code_lines`.
    """
    return {
        path.name: code_lines(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(NOTEBOOKS_DIR.glob("*.ipynb"))
    }


def code_cell(*lines: str) -> dict[str, Any]:
    """Return a code cell whose source is the given lines, stored as a list.

    @param lines: the cell's lines without line breaks.
    @return: the cell as it appears in a notebook's JSON.
    """
    return {"cell_type": "code", "source": [line + "\n" for line in lines]}


class LineScanTest(unittest.TestCase):
    """Tests for the line scanning helpers on hand-written cells."""

    def test_code_lines_skips_comments_and_markdown_cells(self) -> None:
        """Only non-comment lines of code cells are returned, for both source forms.

        Would fail if comment lines or markdown cells were scanned, so a
        commented-out ``unittest.main(`` would be reported, or if a source
        stored as a single string was read character by character.
        """
        # a markdown cell, a code cell stored as a list of lines and one stored
        # as a single string; each code cell holds comment lines:
        notebook: dict[str, Any] = {
            "cells": [
                {"cell_type": "markdown", "source": ["unittest.main(exit=False)\n"]},
                code_cell("# unittest.main(exit=False)", "x = 1", "    # indented"),
                {"cell_type": "code", "source": "y = 2\n# z = 3\nprint(y)"},
            ]
        }
        self.assertEqual(code_lines(notebook), ["x = 1", "y = 2", "print(y)"])

    def test_unittest_main_call_is_found_unless_commented_out(self) -> None:
        """A ``unittest.main(...)`` call is found; the same call as a comment is not.

        Would fail if the scan missed a call with arguments, or if comment lines
        reached the scan.
        """
        # a call with arguments and exit=False:
        call: str = 'unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)'
        self.assertTrue(calls_unittest_main(code_lines({"cells": [code_cell(call)]})))

        # the same call commented out:
        commented: dict[str, Any] = {"cells": [code_cell("# " + call)]}
        self.assertFalse(calls_unittest_main(code_lines(commented)))

    def test_test_case_with_only_the_import_misses_the_call(self) -> None:
        """A ``TestCase`` subclass with only the import of the helper misses the call.

        Would fail if the import line or the commented-out example
        ``# run_notebook_tests(MyTest, MyOtherTest)`` from Top-k.ipynb counted as
        a call, which would let a notebook that never runs its tests pass.
        """
        # a cell stored as a single string, as in Bitmaps-and-Bloom-Filters.ipynb,
        # with a TestCase subclass, the import and the commented-out example:
        cell: dict[str, Any] = {
            "cell_type": "code",
            "source": (
                "from system.playground.notebook_tests import run_notebook_tests\n"
                "class MyTest(unittest.TestCase):\n"
                "    pass\n"
                "# run_notebook_tests(MyTest, MyOtherTest)"
            ),
        }
        lines: list[str] = code_lines({"cells": [cell]})
        self.assertTrue(defines_test_case(lines))
        self.assertFalse(calls_run_notebook_tests(lines))

        # adding the real call makes it count:
        cell["source"] += "\nrun_notebook_tests(MyTest)"
        self.assertTrue(calls_run_notebook_tests(code_lines({"cells": [cell]})))

    def test_test_case_subclass_is_found_for_both_base_spellings(self) -> None:
        """``unittest.TestCase``, a bare ``TestCase`` and a second base all count.

        Would fail if the pattern required the ``unittest.`` prefix, or matched
        a base that merely contains ``TestCase`` in a longer name.
        """
        # bases that make the class a TestCase subclass:
        for line in [
            "class MyTest(unittest.TestCase):",
            "class MyTest(TestCase):",
            "    class Inner(Mixin, unittest.TestCase):",
        ]:
            with self.subTest(line=line):
                self.assertTrue(defines_test_case([line]))

        # bases that do not:
        for line in ["class Helper(MyTestCaseBase):", "class Point(object):"]:
            with self.subTest(line=line):
                self.assertFalse(defines_test_case([line]))


class NotebookTestCallsTest(unittest.TestCase):
    """Every notebook runs its unit tests with ``run_notebook_tests``."""

    def test_notebooks_are_found_and_some_define_test_cases(self) -> None:
        """Notebooks exist, and at least one defines a ``TestCase`` subclass.

        Would fail if the notebooks directory moved or the cells were misread,
        which would otherwise let the checks below pass on nothing.
        """
        # the directory holds notebooks:
        notebooks: dict[str, list[str]] = notebook_code_lines()
        self.assertGreater(len(notebooks), 0, f"No notebooks found in {NOTEBOOKS_DIR}")

        # at least one of them defines unit tests:
        with_tests: list[str] = [
            name for name, lines in notebooks.items() if defines_test_case(lines)
        ]
        self.assertGreater(
            len(with_tests), 0, "No notebook defines a unittest.TestCase subclass"
        )

    def test_no_notebook_calls_unittest_main(self) -> None:
        """No notebook calls ``unittest.main``.

        Would fail if a notebook ran its tests with ``unittest.main(...,
        exit=False)``, whose failing tests do not fail the CI job ipynb_test.
        """
        for name, lines in notebook_code_lines().items():
            with self.subTest(notebook=name):
                self.assertFalse(
                    calls_unittest_main(lines),
                    f"{name} calls unittest.main, which only prints failing tests, "
                    "so the CI job ipynb_test stays green. Call "
                    "run_notebook_tests(<TestCase classes>) from "
                    "system.playground.notebook_tests instead.",
                )

    def test_notebooks_with_test_cases_call_run_notebook_tests(self) -> None:
        """A notebook that defines a ``TestCase`` subclass calls ``run_notebook_tests``.

        Would fail if a notebook defined tests but never ran them, or ran them in
        a way that a failing test does not fail the notebook run.
        """
        for name, lines in notebook_code_lines().items():
            if not defines_test_case(lines):
                continue
            with self.subTest(notebook=name):
                self.assertTrue(
                    calls_run_notebook_tests(lines),
                    f"{name} defines a unittest.TestCase subclass but does not call "
                    "run_notebook_tests. Run its tests with "
                    "run_notebook_tests(<TestCase classes>) from "
                    "system.playground.notebook_tests instead of unittest.main.",
                )


if __name__ == "__main__":
    unittest.main()
