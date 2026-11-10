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
"""Tests that the example B+-tree of ``notebooks/B-tree.ipynb`` finds every stored key.

The example cell of B-tree.ipynb builds a B+-tree by hand from six linked leaves and
three inner nodes, shows it, inserts four keys and shows the tree after each insert.
If a leaf holds a key for which the inner nodes send a search to another leaf, the
picture shows that pair, but no search returns it as stored. These tests run the cell
and check every tree it shows with ``get`` and with a range query on each stored key
alone; the number of pairs of each shown tree makes sure that the hand-built leaves
are among the trees checked. Tests on small hand-built trees check the helper itself.
"""

import contextlib
import io
import json
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from system.indexes.btree import BPlusTree

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
NOTEBOOK_PATH: Path = REPO_ROOT / "notebooks" / "B-tree.ipynb"

# The text by which the example cell is found: it is the only code cell of the notebook
# that builds leaves by hand.
EXAMPLE_CELL_MARKER: str = "BPlusTree.Leaf("

# The number of pairs in each tree the example cell shows: the 19 pairs of the six
# hand-built leaves, then one more after each of the four inserts.
EXPECTED_PAIR_COUNTS: list[int] = [19, 20, 21, 22, 23]


def leaf_entries(node: BPlusTree.AbstractNode) -> list[tuple[int, int]]:
    """Return the (key, value) pairs of the leaves below a node, from left to right.

    @param node: an inner node or a leaf of a B+-tree with int keys and values.
    @return: the pairs of all leaves below ``node`` (of ``node`` itself if it is a
        leaf), in leaf order.
    """
    # an inner node collects the pairs of its children, from left to right:
    if isinstance(node, BPlusTree.Inner):
        return [entry for child in node.children for entry in leaf_entries(child)]

    # a leaf holds its pairs itself:
    return list(zip(node.keys, node.values))


def entries_not_found_exactly(tree: BPlusTree[int, int]) -> list[tuple[int, int]]:
    """Return the stored (key, value) pairs that a search does not return exactly.

    A pair counts if ``get(key)`` or ``get_all_in_range(key, key)`` returns anything
    but exactly ``[value]``. A ``get`` that raises ``KeyError`` returns nothing.

    @param tree: the B+-tree to search.
    @return: the pairs that are not found exactly as stored, in leaf order.
    """
    not_found: list[tuple[int, int]] = []
    for key, value in leaf_entries(tree.root):
        # Leaf.get is a generator, so it raises KeyError only while it is consumed:
        try:
            found: list[int] = list(tree.get(key))
        except KeyError:
            found = []

        # the range query on the key alone must return the same single value:
        in_range: list[int] = list(tree.get_all_in_range(key, key))
        if found != [value] or in_range != [value]:
            not_found.append((key, value))
    return not_found


def two_leaf_tree(left_keys: list[int], right_keys: list[int]) -> BPlusTree[int, int]:
    """Return a tree with root ``[32]`` over a left and a right leaf of two keys each.

    The left leaf holds the values 1 and 2, the right leaf 3 and 4; the leaves are
    linked in both directions.

    @param left_keys: the two keys of the left leaf.
    @param right_keys: the two keys of the right leaf.
    @return: the tree, with inner capacity 3 and leaf capacity 4.
    """
    # two linked leaves with distinct values:
    left: BPlusTree.Leaf = BPlusTree.Leaf(4, left_keys, [1, 2])
    right: BPlusTree.Leaf = BPlusTree.Leaf(4, right_keys, [3, 4])
    left.next = right
    right.previous = left

    # a root with the separator 32 above them:
    tree: BPlusTree[int, int] = BPlusTree[int, int](3, 4)
    tree.root = BPlusTree.Inner(3, [32], [left, right])
    return tree


class EntriesNotFoundExactlyTest(unittest.TestCase):
    """Tests for :func:`entries_not_found_exactly` on a small hand-built tree."""

    def test_key_stored_in_two_leaves_reports_both_pairs(self) -> None:
        """Key 31 stored in two leaves is reported for both of its pairs, in leaf order.

        The range query on 31 alone returns both values, so neither pair is found
        exactly. Would fail if the helper missed a pair whose range query returns more
        than its own value.
        """
        tree: BPlusTree[int, int] = two_leaf_tree([21, 31], [31, 34])
        self.assertEqual([(31, 2), (31, 3)], entries_not_found_exactly(tree))

    def test_key_right_of_its_separator_is_reported(self) -> None:
        """Key 31 stored only in the leaf right of the separator 32 is reported.

        ``get(31)`` searches the left leaf and raises ``KeyError``, while the range
        query on 31 alone still returns its value. Would fail if the helper missed a
        pair that ``get`` never reaches.
        """
        tree: BPlusTree[int, int] = two_leaf_tree([21, 25], [31, 34])
        self.assertEqual([(31, 3)], entries_not_found_exactly(tree))

    def test_tree_whose_right_leaf_starts_at_the_separator_has_none(self) -> None:
        """A tree whose right leaf starts at the separator 32 has no pair to report.

        Would fail if the helper reported a pair that both searches find, e.g. a key
        equal to the separator, which the inner node routes to the right leaf.
        """
        tree: BPlusTree[int, int] = two_leaf_tree([21, 31], [32, 34])
        self.assertEqual([], entries_not_found_exactly(tree))


class NotebookTreeTest(unittest.TestCase):
    """The example B+-tree of B-tree.ipynb finds every key it stores."""

    def test_every_shown_tree_finds_each_stored_key(self) -> None:
        """Every tree the example cell of B-tree.ipynb shows finds each key it stores.

        Each stored key is found with ``get`` and with a range query on that key alone.
        Would fail if a leaf of the example held a key that the inner nodes route to
        another leaf, so that the picture shows a pair that no search returns as stored.
        Would also fail if the cell no longer showed the hand-built tree, e.g. if it
        showed trees built by ``put`` alone: the numbers of pairs would then differ.
        """
        # the example cell is the only code cell that builds leaves by hand; a notebook
        # stores the source as a list of lines or as a single string, and joining
        # works for both:
        notebook: dict[str, Any] = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
        code_sources: list[str] = [
            "".join(cell["source"])
            for cell in notebook["cells"]
            if cell["cell_type"] == "code"
        ]
        example_cells: list[str] = [
            source for source in code_sources if EXAMPLE_CELL_MARKER in source
        ]
        self.assertEqual(
            1,
            len(example_cells),
            f"This test finds the example cell of {NOTEBOOK_PATH.name} as the only "
            f"code cell that contains {EXAMPLE_CELL_MARKER!r}, but "
            f"{len(example_cells)} code cells contain it. If the notebook was "
            "restructured, adapt how this test finds the cell.",
        )

        # instead of drawing the tree, each call of show records the number of pairs
        # of the shown tree and the pairs that are not found exactly; the tree changes
        # between the calls:
        pair_counts: list[int] = []
        not_found_per_tree: list[list[tuple[int, int]]] = []

        def record(tree: BPlusTree[int, int]) -> None:
            """Record the number of pairs of the shown tree and those not found exactly.

            Patched in as ``BPlusTree.show``, so it is bound as a method and receives
            the tree.

            @param tree: the tree whose ``show`` the cell calls.
            """
            pair_counts.append(len(leaf_entries(tree.root)))
            not_found_per_tree.append(entries_not_found_exactly(tree))

        # run the cell in a fresh namespace, without its printed headings; the cell is
        # plain Python from this repository's own notebook, so exec runs trusted code:
        namespace: dict[str, Any] = {}
        with mock.patch.object(BPlusTree, "show", new=record):
            with contextlib.redirect_stdout(io.StringIO()):
                exec(example_cells[0], namespace)

        # the cell shows the hand-built tree and the tree after each insert; the
        # numbers of pairs also make sure that the hand-built leaves were checked. A
        # subtest of its own, so that a wrong number does not hide the checks below:
        with self.subTest(check="number of pairs of each shown tree"):
            self.assertEqual(
                EXPECTED_PAIR_COUNTS,
                pair_counts,
                f"The example cell of {NOTEBOOK_PATH.name} should show its tree "
                f"{len(EXPECTED_PAIR_COUNTS)} times, the hand-built tree and the tree "
                f"after each insert, with {EXPECTED_PAIR_COUNTS} stored pairs. A "
                f"first number other than {EXPECTED_PAIR_COUNTS[0]} means that the "
                "tree shown first does not hold exactly the hand-built leaves. If "
                "the cell was changed on purpose, adapt EXPECTED_PAIR_COUNTS.",
            )

        # each shown tree finds all of its pairs exactly:
        for number, not_found in enumerate(not_found_per_tree, start=1):
            with self.subTest(shown_tree=number):
                self.assertEqual(
                    [],
                    not_found,
                    f"Tree number {number} shown by the example cell of "
                    f"{NOTEBOOK_PATH.name} (number 1 is the hand-built tree) stores "
                    "(key, value) pairs for which get(key) or the range query on "
                    "that key alone does not return exactly the value. For example, "
                    "a key is stored twice, a leaf holds a key that the inner nodes "
                    "send to another leaf, or a listed pair is the neighbour of "
                    "such a key.",
                )


if __name__ == "__main__":
    unittest.main()
