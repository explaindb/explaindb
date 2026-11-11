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
"""Tests that the trees of the B-tree page (``visualizations/b-tree.html``) are those of the repository's B+-tree code.

The page shows the code's ``BPlusTree(8, 16)``: up to 2k = 8 keys in an inner node (k = 4) and 2k* = 16 in a leaf
(k* = 8). Its script holds the start tree as nested lists of leaf keys (``START``, without the keys of the inner nodes)
and the three keys the film inserts (``PUTS``). These tests build the start tree from the code's node classes, as a
bulk load would, insert the three keys with the code's own ``put`` and compare the four trees with
``EXPECTED_DIGESTS`` in ``b_tree_page_trees.py``, against which ``BTreePageTest`` in ``test_visualizations.py`` checks
the trees the page itself makes. They also run the film's point query and range query on the start tree with the
code's ``get`` and ``get_all_in_range`` and compare the nodes visited and the keys found with ``EXPECTED_POINT_PATH``
and ``EXPECTED_RANGE_HITS``, against which ``BTreePageTest`` checks what the page shows.
"""

import unittest
from collections.abc import Iterator
from unittest import mock

from system.indexes.btree import BPlusTree
from system.tests.repo.b_tree_page_trees import (
    EXPECTED_DIGESTS,
    EXPECTED_POINT_PATH,
    BETWEEN_LEAVES_RANGE,
    EXPECTED_BETWEEN_LEAVES,
    EXPECTED_RANGE_HITS,
    EXPECTED_RANGE_LEAVES,
    NestedLeaves,
    Tree,
    digest_mismatches,
    digests,
    read_queries,
    read_start_and_puts,
)

# BPlusTree(8, 16): an inner node holds up to 2k = 8 keys, a leaf up to 2k* = 16:
INNER_CAPACITY: int = 8
LEAF_CAPACITY: int = 16


def least_key(node: BPlusTree.AbstractNode) -> int:
    """Returns the least key in the subtree of node."""
    while isinstance(node, BPlusTree.Inner):
        node = node.children[0]
    return node.keys[0]


def build_tree(start: list) -> BPlusTree[int, str]:
    """Builds the code's BPlusTree(8, 16) from the nested lists of the page's ``START``, bottom-up.

    Each leaf holds its keys, each with the value ``parcel <key>``, and is chained to the leaf before it. Each key of an
    inner node is the least key of the subtree to its right, as the code's splits make them.

    @param start: the start tree as nested lists: an inner node is the list of its subtrees, a leaf the list of its keys
    @return: the tree, whose root is the node built from start
    """
    leaves: list[BPlusTree.Leaf] = []

    def build(part: list) -> BPlusTree.AbstractNode:
        """Builds a leaf from a list of keys, else an inner node over the nodes built from the items of part."""
        if isinstance(part[0], int):
            leaf: BPlusTree.Leaf = BPlusTree.Leaf(
                LEAF_CAPACITY, list(part), [f"parcel {key}" for key in part]
            )
            # the leaf chain, for scans in both directions:
            if leaves:
                leaves[-1].next = leaf
                leaf.previous = leaves[-1]
            leaves.append(leaf)
            return leaf
        children: list[BPlusTree.AbstractNode] = [build(item) for item in part]
        separators: list[int] = [least_key(child) for child in children[1:]]
        return BPlusTree.Inner(INNER_CAPACITY, separators, children)

    tree: BPlusTree[int, str] = BPlusTree[int, str](INNER_CAPACITY, LEAF_CAPACITY)
    tree.root = build(start)
    return tree


def plain(node: BPlusTree.AbstractNode) -> Tree:
    """Returns the subtree of node as plain data, in the form the page writes into ``data-trees`` (see ``Tree``)."""
    if isinstance(node, BPlusTree.Inner):
        return {
            "keys": list(node.keys),
            "children": [plain(child) for child in node.children],
        }
    return list(node.keys)


class BTreePageDataTest(unittest.TestCase):
    """Checks the start tree and the three puts of the B-tree page against the repository's B+-tree code."""

    def setUp(self) -> None:
        """Reads START, PUTS, POINT_KEY and RANGE from the page."""
        # START: nested lists of the leaves' keys (unlike Tree, no inner nodes' keys):
        self.start: NestedLeaves
        # PUTS: the three keys the film inserts, in their order:
        self.puts: list[int]
        self.start, self.puts = read_start_and_puts()
        # POINT_KEY: the key the film's point query looks for:
        self.point_key: int
        # RANGE: the least and greatest key of the range query, both included:
        self.range: tuple[int, int]
        self.point_key, self.range = read_queries()

    def test_the_code_makes_the_trees_of_the_page(self) -> None:
        """The code's put, given the page's start tree and its three keys, makes the four trees that the page shows.

        Fails if the page's START or PUTS change without new expected digests, or if BPlusTree.put starts to split
        differently (e.g. another key moves up), so that the page would no longer show the code's trees.
        """
        # the start tree passes the code's own check (sorted keys, leaves within their capacity, the leaf chain):
        tree: BPlusTree[int, str] = build_tree(self.start)
        tree.consistency_check()
        trees: list[Tree] = [plain(tree.root)]

        # each key goes in through the code's own put:
        for key in self.puts:
            tree.put(key, f"parcel {key}")
            trees.append(plain(tree.root))

        # the start tree and the three trees after it are those the page writes (BTreePageTest):
        self.assertEqual(EXPECTED_DIGESTS, digests(trees), digest_mismatches(trees))

    def test_the_point_query_takes_the_way_of_the_code(self) -> None:
        """The code's get, asked for the point query's key on the start tree, finds its value and visits the nodes
        whose keys EXPECTED_POINT_PATH lists, from the root down to the leaf; BTreePageTest checks that the page
        shows the same way.

        Fails if START changes so that the way to the key leads through other nodes, or if get descends into another
        subtree than the one whose interval holds the key.
        """
        tree: BPlusTree[int, str] = build_tree(self.start)
        visited: list[list[int]] = []
        inner_get = BPlusTree.Inner.get
        leaf_get = BPlusTree.Leaf.get

        def visit_inner(node: BPlusTree.Inner, key: int) -> Iterator[str]:
            """Notes the keys of the inner node that get passes through, then goes on as the code does."""
            visited.append(list(node.keys))
            return inner_get(node, key)

        def visit_leaf(node: BPlusTree.Leaf, key: int) -> Iterator[str]:
            """Notes the keys of the leaf that get ends in, then looks the key up as the code does."""
            visited.append(list(node.keys))
            return leaf_get(node, key)

        # the code's own get, with each node it visits noted on the way:
        with (
            mock.patch.object(BPlusTree.Inner, "get", visit_inner),
            mock.patch.object(BPlusTree.Leaf, "get", visit_leaf),
        ):
            values: list[str] = list(tree.get(self.point_key))

        # it finds the key's value, through the nodes of the film's point query:
        self.assertEqual([f"parcel {self.point_key}"], values)
        self.assertEqual(EXPECTED_POINT_PATH, visited)

    def test_the_range_query_finds_the_keys_of_the_code(self) -> None:
        """The code's get_all_in_range, asked for the range query's keys on the start tree, finds the keys that
        EXPECTED_RANGE_HITS lists; BTreePageTest checks that the page finds the same ones.

        Fails if START changes so that the range holds other keys, or if get_all_in_range stops following the leaf
        chain too early or too late.
        """
        tree: BPlusTree[int, str] = build_tree(self.start)

        # the keys of the values found (each value names its key):
        hits: list[int] = [
            int(value.removeprefix("parcel "))
            for value in tree.get_all_in_range(*self.range)
        ]
        self.assertEqual(EXPECTED_RANGE_HITS, hits)

    def test_the_range_query_reads_the_leaves_of_the_code(self) -> None:
        """The code's get_all_in_range scans the leaves that EXPECTED_RANGE_LEAVES lists for the film's range, and those
        that EXPECTED_BETWEEN_LEAVES lists for a range whose least key falls between two leaves (the leaf its way down
        lands in comes first, although none of its keys is in the range); BTreePageTest checks that the page reads the
        same ones, the latter on a copy with that range.

        Fails if START changes so that other leaves hold the range, or if get_all_in_range starts or stops elsewhere.
        """
        for key_range, expected in [
            (self.range, EXPECTED_RANGE_LEAVES),
            (BETWEEN_LEAVES_RANGE, EXPECTED_BETWEEN_LEAVES),
        ]:
            with self.subTest(key_range=key_range):
                self.assertEqual(expected, self.leaves_scanned(key_range))

    def leaves_scanned(self, key_range: tuple[int, int]) -> list[int]:
        """Runs the code's get_all_in_range on the start tree and returns the least key of each leaf it scans, in order.

        @param key_range: the least and the greatest key of the range (both included)
        @return: the least keys of the leaves that the code scans for it
        """
        tree: BPlusTree[int, str] = build_tree(self.start)
        scanned: list[int] = []
        scan = BPlusTree.Leaf._scan_leaf  # pylint: disable=protected-access

        def note_leaf(
            leaf: BPlusTree.Leaf, max_key: int, result: list[str], start_pos: int = 0
        ) -> bool:
            """Notes the least key of the leaf that the code scans, then scans it as the code does."""
            scanned.append(leaf.keys[0])
            return scan(leaf, max_key, result, start_pos)

        # the code's own range query, with each leaf it scans noted on the way:
        with mock.patch.object(BPlusTree.Leaf, "_scan_leaf", note_leaf):
            list(tree.get_all_in_range(*key_range))
        return scanned

    def test_the_start_tree_is_a_b_tree_with_k_4_and_k_star_8(self) -> None:
        """The start tree is a B+-tree as the lecture defines it, for k = 4 and k* = 8: its keys ascend from leaf to
        leaf, all leaves lie on the fourth level, each inner node but the root holds 4 to 8 keys and each leaf 8 to 16;
        the root is full, with 8 keys.

        The code's consistency_check() (in the test above) already rejects a node that is less than half full or too
        full and leaves at different depths. This test adds what the film needs besides: the tree has height 4 (its
        leaves lie three levels below the root) and its root is full, so that the last put splits up to the root.
        Fails if START is changed into a valid tree of another height or with a root that is not full.
        """
        leaf_depths: set[int] = set()
        inner_sizes: list[int] = []
        leaves: list[list[int]] = []

        def walk(part: list, depth: int) -> None:
            """Notes the depth and size of each leaf and the number of keys of each inner node below the root."""
            if isinstance(part[0], int):
                leaf_depths.add(depth)
                leaves.append(part)
                return
            if depth > 0:
                # an inner node has one key less than it has subtrees:
                inner_sizes.append(len(part) - 1)
            for item in part:
                walk(item, depth + 1)

        walk(self.start, 0)

        # the keys ascend from leaf to leaf, each key once (so each least key of a subtree separates it from the left):
        keys: list[int] = [key for leaf in leaves for key in leaf]
        self.assertEqual(sorted(set(keys)), keys, "the keys do not ascend, each once")

        # all leaves lie three levels below the root, so the tree has height 4:
        self.assertEqual({3}, leaf_depths, "the depths of the leaves below the root")

        # each node is at least half full, and the root is full:
        self.assertEqual(8, len(self.start) - 1, "the number of keys of the root")
        self.assertGreaterEqual(
            min(inner_sizes), 4, "an inner node is less than half full"
        )
        self.assertLessEqual(
            max(inner_sizes), 8, "an inner node holds more than 2k keys"
        )
        self.assertGreaterEqual(
            min(len(leaf) for leaf in leaves), 8, "a leaf is less than half full"
        )
        self.assertLessEqual(
            max(len(leaf) for leaf in leaves), 16, "a leaf holds more than 2k* keys"
        )


if __name__ == "__main__":
    unittest.main()
