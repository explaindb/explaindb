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
"""Tests that the unit tests of the merge tree use the same small example as ``notebooks/External-Merge-Sort.ipynb``,
that the notebook's relative links lead to files, and that its stored outputs are complete.
"""

import ast
import json
import re
import unittest
from pathlib import Path
from typing import Any

from system.tests.playground.test_merge_tree import SMALL_EXAMPLE

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
NOTEBOOK_PATH: Path = REPO_ROOT / "notebooks" / "External-Merge-Sort.ipynb"


def notebook_constant(name: str) -> Any:
    """Returns the value of a constant that a code cell of the notebook assigns as a literal, e.g. ``SMALL_EXAMPLE``.

    @param name: the constant's name
    @return: its value
    @raise LookupError: if no code cell assigns the constant
    """
    for cell in read_notebook()["cells"]:
        if cell["cell_type"] != "code":
            continue
        # the assignments at the top level of the cell, with or without a type annotation:
        for statement in ast.parse("".join(cell["source"])).body:
            if (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.target.id == name
                and statement.value is not None
            ):
                return ast.literal_eval(statement.value)
            if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name
                for target in statement.targets
            ):
                return ast.literal_eval(statement.value)
    raise LookupError(f"no code cell of {NOTEBOOK_PATH.name} assigns {name}")


def read_notebook() -> dict[str, Any]:
    """Returns the notebook as stored in the repo.

    @return: the notebook's JSON, with its cells under ``cells``
    """
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def relative_links(notebook: dict[str, Any]) -> list[str]:
    """Returns the targets of the Markdown links ``[text](target)`` and ``[text](<target>)`` in the notebook's
    Markdown cells that are paths relative to the notebook, without a ``#fragment``.

    @param notebook: the notebook's JSON
    @return: the relative targets, in the order of the cells; links to the web (``scheme://``), ``mailto:`` links and
    links inside the page (``#...``) are left out
    """
    # a target in angle brackets may hold spaces and brackets; without them it ends at the first space or
    # closing round bracket:
    link: re.Pattern[str] = re.compile(r"\]\((?:<([^>]+)>|([^)\s]+))\)")
    targets: list[str] = []
    for cell in notebook["cells"]:
        if cell["cell_type"] != "markdown":
            continue
        for in_brackets, plain in link.findall("".join(cell["source"])):
            target: str = (in_brackets or plain).split("#", 1)[0]
            if target and "://" not in target and not target.startswith("mailto:"):
                targets.append(target)
    return targets


class SmallExampleCopyTest(unittest.TestCase):
    """The copy of the notebook's small example in ``test_merge_tree.py``."""

    def test_the_copy_is_the_notebooks_small_example(self) -> None:
        """``SMALL_EXAMPLE`` in ``test_merge_tree.py``, whose trees the tests check for overlapping arrows, holds the
        same 36 values as ``SMALL_EXAMPLE`` in the notebook, which the notebook draws.

        Would fail if the notebook's small example were changed without its copy in the tests, so that the tests checked
        trees the notebook does not show.
        """
        self.assertEqual(SMALL_EXAMPLE, notebook_constant("SMALL_EXAMPLE"))

    def test_a_missing_constant_raises_a_lookup_error(self) -> None:
        """Looking up a constant that no cell assigns raises a LookupError instead of returning a value.

        Would fail if the lookup returned None for a missing constant, so that a renamed constant went unnoticed.
        """
        with self.assertRaises(LookupError):
            notebook_constant("NO_SUCH_CONSTANT")


class RelativeLinksTest(unittest.TestCase):
    """The relative links in the notebook's Markdown cells."""

    def test_every_relative_link_leads_to_a_file(self) -> None:
        """Every relative link of the notebook, resolved from ``notebooks/``, leads to an existing file, e.g. the
        link to ``Replacement-Selection-Playground.ipynb``; and the notebook has both the link to the playground and
        the link to the tutorial page, whose target is written in angle brackets.

        Would fail if a linked file were renamed or moved without the link, or if the links were no longer found, so
        that nothing was checked.
        """
        targets: list[str] = relative_links(read_notebook())
        self.assertIn("../notebooks/Replacement-Selection-Playground.ipynb", targets)
        self.assertIn(
            "../docs/tutorial/03 Query Processing/External Sorting & Queues.md", targets
        )
        for target in targets:
            with self.subTest(target=target):
                self.assertTrue((NOTEBOOK_PATH.parent / target).is_file())

    def test_which_links_count_as_relative(self) -> None:
        """Of the links in made-up Markdown, the plain relative link and the relative link in angle brackets (with
        spaces and an ampersand in its target) are found, the latter without its ``#fragment``; the link to the web,
        the ``mailto:`` link and the link inside the page are left out, and so is a link in a code cell.

        Would fail if a target in angle brackets were cut at its first space or not found, so that such a link of the
        notebook went unchecked, or if a web link were taken for a file.
        """
        notebook: dict[str, Any] = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": [
                        "A [plain link](../docs/plain.md) and one\n",
                        "[in angle brackets](<../docs/a folder/Sorting & Queues (1).md#section>).\n",
                    ],
                },
                {"cell_type": "code", "source": ["# [not Markdown](../docs/code.md)"]},
                {
                    "cell_type": "markdown",
                    "source": [
                        "[web](https://example.org/page.html), [mail](mailto:someone@example.org), [above](#terms)"
                    ],
                },
            ]
        }
        self.assertEqual(
            ["../docs/plain.md", "../docs/a folder/Sorting & Queues (1).md"],
            relative_links(notebook),
        )


class StoredOutputsTest(unittest.TestCase):
    """The outputs stored in the notebook."""

    def test_the_stored_outputs_are_complete(self) -> None:
        """Every code cell has been run (it has an execution count), the counts are 1, 2, 3, ... in the order of the
        cells, as after one run from top to bottom, and no output is an error.

        Would fail if the notebook were committed with its outputs stripped, after running cells out of order or
        running a cell twice, or with a cell that raised an exception.
        """
        code_cells: list[dict[str, Any]] = [
            cell for cell in read_notebook()["cells"] if cell["cell_type"] == "code"
        ]
        self.assertTrue(code_cells)
        execution_counts: list[int | None] = [
            cell["execution_count"] for cell in code_cells
        ]
        # every code cell has been run:
        self.assertNotIn(None, execution_counts)
        # in the order of the cells, counted from 1 without a gap:
        self.assertEqual(list(range(1, len(execution_counts) + 1)), execution_counts)
        # no cell raised an exception:
        for position, cell in enumerate(code_cells):
            with self.subTest(code_cell=position):
                self.assertNotIn(
                    "error", [output["output_type"] for output in cell["outputs"]]
                )


if __name__ == "__main__":
    unittest.main()
