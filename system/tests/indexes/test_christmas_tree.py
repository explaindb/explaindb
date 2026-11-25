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
"""Tests for the Christmas tree index (system/indexes/christmas_tree.py)."""

import unittest

from system.indexes.christmas_tree import ChristmasTree
from system.indexes.radix_trie import RadixTrie
from system.indexes.utils import Triangle, Vector


class ChristmasTreeLeafTest(unittest.TestCase):
    """The leaves of a Christmas tree: a tree without inner node levels, and the leaf factory."""

    def test_tree_without_inner_node_levels_is_a_single_leaf_that_stores_and_finds_keys(
        self,
    ) -> None:
        """A Christmas tree without inner node levels is a single leaf that stores and finds keys."""
        triangle: Triangle = Triangle(Vector(0, 0), Vector(300, 0), Vector(150, 300))

        # build a tree with the default number of inner node levels:
        tree: ChristmasTree[Vector, str] = ChristmasTree[Vector, str](
            children_per_inner_node=4, descriptor=triangle
        )
        self.assertEqual(tree.number_of_inner_node_levels, 0)
        self.assertEqual(tree.number_of_nodes(), 1)

        # the root is the only leaf: it covers the whole triangle and has no left sibling:
        root: RadixTrie.AbstractNode | None = tree.root
        self.assertIsInstance(root, RadixTrie.LeafNode)
        assert isinstance(root, RadixTrie.LeafNode)
        self.assertIs(root.parent_descriptor, triangle)
        self.assertIsNone(root.left_sibling)

        # put three pairs, two of them under the same key:
        tree.put(Vector(150, 100), "a")
        tree.put(Vector(100, 50), "b")
        tree.put(Vector(150, 100), "c")
        self.assertEqual(tree.size(), 3)

        # the leaf returns all values of a key in the order they were put, and nothing for a point that was not stored:
        self.assertEqual(list(tree.get(Vector(150, 100))), ["a", "c"])
        self.assertEqual(list(tree.get(Vector(100, 50))), ["b"])
        self.assertEqual(list(tree.get(Vector(200, 50))), [])

    def test_leaf_factory_takes_the_previous_leaf_by_keyword(self) -> None:
        """The leaf factory of the Christmas tree takes the arguments of RadixTrie.LeafFactory.new_instance by
        keyword and chains the new leaf to the previous leaf.
        """
        triangle: Triangle = Triangle(Vector(0, 0), Vector(300, 0), Vector(150, 300))

        # create the previous leaf directly, without the factory under test:
        first: RadixTrie.LeafNode[Vector, str] = RadixTrie.LeafNode[Vector, str](
            triangle
        )

        # create the next leaf through the factory, passing both arguments by keyword:
        leaf: RadixTrie.LeafNode[Vector, str] = ChristmasTree.LeafFactory[
            Vector, str
        ]().new_instance(parent_descriptor=triangle, previous_leaf=first)
        self.assertIs(leaf.left_sibling, first)
        self.assertIs(leaf.parent_descriptor, triangle)


if __name__ == "__main__":
    unittest.main()
