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
"""Tests of ``BPlusTree.convert_to_counting_leaf_tree``, which replaces the leaves with leaves that only count keys."""

import unittest

from system.indexes.btree import BPlusTree


def inner_levels(tree: BPlusTree[int, int]) -> list[list[BPlusTree.Inner]]:
    """Returns the inner nodes of the given tree level by level, from the root down.

    @param tree: the tree to walk; its leaves may be leaves or counting leaves
    @return: one list per level of inner nodes, each from left to right, the root's
        level first; an empty list if the root is a leaf
    """
    levels: list[list[BPlusTree.Inner]] = []
    level: list[BPlusTree.AbstractNode] = [tree.root]

    # all leaves lie at the same depth, so a level holds either inner nodes only or
    # leaves only; walk down until the level of the leaves:
    while True:
        inner_nodes: list[BPlusTree.Inner] = [
            node for node in level if isinstance(node, BPlusTree.Inner)
        ]
        if not inner_nodes:
            return levels
        levels.append(inner_nodes)
        level = [child for node in inner_nodes for child in node.children]


class ConvertToCountingLeafTreeTest(unittest.TestCase):
    """Tests for :meth:`BPlusTree.convert_to_counting_leaf_tree`."""

    def test_converting_twice_replaces_the_counting_leaves(self) -> None:
        """Converting a tree whose leaves already count replaces them with new
        counting leaves, whose counts start at zero, and keeps the inner nodes.

        Checked for a tree with one level of inner nodes and for one with three.
        Would fail if the conversion recognised only leaves that store keys, not
        counting leaves, as the level below the last level of inner nodes.
        """
        for label, number_of_keys, number_of_inner_levels in [
            ("two levels", 5, 1),
            ("four levels", 30, 3),
        ]:
            with self.subTest(case=label):
                # a tree with inner capacity 3 and leaf capacity 4 that holds the
                # keys 0 to number_of_keys - 1:
                keys: list[int] = list(range(number_of_keys))
                tree: BPlusTree[int, int] = BPlusTree[int, int](3, 4)
                for key in keys:
                    tree.put(key, key)

                # the first conversion; the counting leaves then count every key
                # put into the tree again:
                tree.convert_to_counting_leaf_tree()
                for key in keys:
                    tree.put(key, key)
                self.assertEqual(number_of_keys, tree.size())

                # remember the inner nodes of each level and a copy of their keys;
                # the number of levels makes sure the label of the case is right:
                levels: list[list[BPlusTree.Inner]] = inner_levels(tree)
                self.assertEqual(number_of_inner_levels, len(levels))
                keys_per_level: list[list[list[int]]] = [
                    [list(node.keys) for node in level] for level in levels
                ]

                # remember the counting leaves of the first conversion:
                old_leaves: list[BPlusTree.AbstractNode] = [
                    child for node in levels[-1] for child in node.children
                ]

                # the second conversion keeps every inner node, level by level:
                tree.convert_to_counting_leaf_tree()
                levels_after: list[list[BPlusTree.Inner]] = inner_levels(tree)
                self.assertEqual(
                    [len(level) for level in levels],
                    [len(level) for level in levels_after],
                )
                for level, level_after in zip(levels, levels_after):
                    for node, node_after in zip(level, level_after):
                        self.assertIs(node, node_after)

                # the inner nodes keep their keys:
                self.assertEqual(
                    keys_per_level,
                    [[list(node.keys) for node in level] for level in levels_after],
                )

                # every child of the last level of inner nodes is a counting leaf
                # whose count starts at zero, so the tree counts no key yet:
                for node in levels_after[-1]:
                    for child in node.children:
                        self.assertIsInstance(child, BPlusTree.CountingLeaf)
                        self.assertEqual(0, child.size())
                self.assertEqual(0, tree.size())

                # each of these counting leaves is a new one, not one of the first
                # conversion:
                new_leaves: list[BPlusTree.AbstractNode] = [
                    child for node in levels_after[-1] for child in node.children
                ]
                self.assertEqual(len(old_leaves), len(new_leaves))
                for old_leaf, new_leaf in zip(old_leaves, new_leaves):
                    self.assertIsNot(old_leaf, new_leaf)

                # the new counting leaves count every key put into the tree again:
                for key in keys:
                    tree.put(key, key)
                self.assertEqual(number_of_keys, tree.size())


if __name__ == "__main__":
    unittest.main()
