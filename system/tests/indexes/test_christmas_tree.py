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
from unittest import mock

from system.indexes.christmas_tree import ChristmasTree
from system.indexes.radix_trie import KeyMapping, RadixTrie
from system.indexes.utils import Descriptor, Triangle, Vector


class _FirstChildMapping(KeyMapping[Vector, str]):
    """A key mapping that routes every key to the first child of every inner node, unlike the sub-triangles of a
    Christmas tree."""

    def map(self, key: Vector, level: int, descriptor: Descriptor | None = None) -> int:
        """See :meth:`KeyMapping.map`.

        Returns 0 for every key and level; ``descriptor`` is ignored.
        """
        return 0


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


class ChristmasTreeKeyMappingTest(unittest.TestCase):
    """A Christmas tree with a key mapping."""

    def test_default_inner_nodes_route_keys_with_the_key_mapping(self) -> None:
        """A Christmas tree with a key mapping and the default inner node factory routes keys with the mapping in
        every inner node, not with the sub-triangles.
        """
        triangle: Triangle = Triangle(Vector(0, 0), Vector(300, 0), Vector(150, 300))

        # build a tree with two inner node levels, the mapping and the default inner node factory:
        mapping: _FirstChildMapping = _FirstChildMapping()
        tree: ChristmasTree[Vector, str] = ChristmasTree[Vector, str](
            children_per_inner_node=4,
            descriptor=triangle,
            key_mapping=mapping,
            number_of_inner_node_levels=2,
        )

        # put a point that lies in the top sub-triangle (child 1) on both levels: the sub-triangles would route it to
        # root.children[1].children[1], the mapping routes it to root.children[0].children[0]:
        tree.put(Vector(150, 250), "a")

        # find the inner nodes on both paths:
        root: RadixTrie.AbstractNode | None = tree.root
        self.assertIsInstance(root, RadixTrie.InnerNode)
        assert isinstance(root, RadixTrie.InnerNode)
        first_child: RadixTrie.AbstractNode = root.children[0]
        second_child: RadixTrie.AbstractNode = root.children[1]
        self.assertIsInstance(first_child, RadixTrie.InnerNode)
        assert isinstance(first_child, RadixTrie.InnerNode)
        self.assertIsInstance(second_child, RadixTrie.InnerNode)
        assert isinstance(second_child, RadixTrie.InnerNode)

        # the pair is in the first leaf, and the leaf the sub-triangles would choose is empty:
        mapping_leaf: RadixTrie.AbstractNode = first_child.children[0]
        triangle_leaf: RadixTrie.AbstractNode = second_child.children[1]
        self.assertIsInstance(mapping_leaf, RadixTrie.LeafNode)
        assert isinstance(mapping_leaf, RadixTrie.LeafNode)
        self.assertIsInstance(triangle_leaf, RadixTrie.LeafNode)
        assert isinstance(triangle_leaf, RadixTrie.LeafNode)
        self.assertEqual(mapping_leaf.values, [(Vector(150, 250), "a")])
        self.assertEqual(triangle_leaf.values, [])

        # the root and each of its four children carry the mapping:
        for node in [root, *root.children]:
            self.assertIsInstance(node, RadixTrie.InnerNode)
            assert isinstance(node, RadixTrie.InnerNode)
            self.assertIs(node.key_mapping, mapping)

        # the tree finds the value under its key again:
        self.assertEqual(list(tree.get(Vector(150, 250))), ["a"])


class _BinaryDigitsOfXMapping(KeyMapping[Vector, str]):
    """Maps a vector key to a child of an inner node by the binary digits of its x coordinate, an integer from 0 to 7
    written with three binary digits: the inner node on level 0 takes the first (most significant) digit, the one on
    level 2 the last.

    Example: for Vector(6, 0), 6 is 110 in binary, so the key goes to child 1 on level 0, child 1 on level 1 and child
    0 on level 2, i.e. into ``leaves[6]``, the leaf numbered 6 when the leaves are counted from 0 at the left (in a
    trie with 2 children per inner node and 3 inner node levels).
    """

    def map(self, key: Vector, level: int, descriptor: Descriptor | None = None) -> int:
        """See :meth:`KeyMapping.map`.

        The x coordinate of the key must be an integer from 0 to 7; ``descriptor`` is ignored.
        """
        assert 0 <= int(key.x) < 8
        return int(f"{int(key.x):03b}"[level])


def _leaves(node: RadixTrie.AbstractNode) -> list[RadixTrie.LeafNode]:
    """Returns the leaves below the given node from left to right."""
    if isinstance(node, RadixTrie.LeafNode):
        return [node]
    assert isinstance(node, RadixTrie.InnerNode)
    return [leaf for child in node.children for leaf in _leaves(child)]


class ChristmasTreeFlushTest(unittest.TestCase):
    """Flushing the buffers of a Christmas tree whose inner nodes are buffered."""

    def test_flush_all_buffers_moves_every_key_into_the_leaf_its_key_mapping_names(
        self,
    ) -> None:
        """Flushing all buffers of a Christmas tree with a key mapping moves every buffered key into the leaf that the
        key mapping names; every inner node routes its buffered keys by its own depth.
        """
        triangle: Triangle = Triangle(Vector(0, 0), Vector(300, 0), Vector(150, 300))

        for config in ["buffered", "crystalball"]:
            with self.subTest(config=config):
                # build a tree with 2 children per inner node and 3 levels of buffered inner nodes, which route by
                # the key mapping:
                tree: ChristmasTree[Vector, str] = ChristmasTree[Vector, str](
                    children_per_inner_node=2,
                    descriptor=triangle,
                    key_mapping=_BinaryDigitsOfXMapping(),
                    number_of_inner_node_levels=3,
                    inner_node_factory=ChristmasTree.InnerNodeFactory[Vector, str](
                        config=config
                    ),
                )

                # put 8 keys; they all stay in the root buffer, as it holds up to 30 pairs:
                for x in range(8):
                    tree.put(Vector(x, 0), str(x))
                root: RadixTrie.AbstractNode | None = tree.root
                self.assertIsInstance(root, ChristmasTree.BufferedInnerNode)
                assert isinstance(root, ChristmasTree.BufferedInnerNode)
                self.assertEqual(len(root.buffer), 8)

                # flush all buffers down to the 8 leaves:
                tree.flush_all_buffers()
                leaves: list[RadixTrie.LeafNode] = _leaves(tree.root)
                self.assertEqual(len(leaves), 8)

                # every leaf holds exactly the key whose binary digits name it, and get finds every key:
                for x in range(8):
                    self.assertEqual(leaves[x].values, [(Vector(x, 0), str(x))])
                    self.assertEqual(list(tree.get(Vector(x, 0))), [str(x)])


def _recorded_drawing(
    canvas: mock.MagicMock,
) -> list[tuple[str, list[tuple[float, float]]]]:
    """Returns what was drawn onto a mock canvas as a list of (method name, (x, y) points), in the order of the calls.

    Setting an attribute such as ``fill_style`` is not a call and is not recorded. A call of a method this helper does
    not know raises an AssertionError naming the method, so that a new kind of canvas call cannot slip past a test
    unnoticed.
    """
    drawing: list[tuple[str, list[tuple[float, float]]]] = []
    for name, args, _ in canvas.method_calls:
        # rectangles, circles and path steps get one point as their first two arguments:
        if name in ("fill_rect", "fill_arc", "move_to", "line_to"):
            drawing.append((name, [(args[0], args[1])]))
        # a gradient gets its start and its end point:
        elif name == "create_linear_gradient":
            drawing.append((name, [(args[0], args[1]), (args[2], args[3])]))
        # a polygon gets the list of its corners:
        elif name == "fill_polygon":
            drawing.append((name, list(args[0])))
        # starting and stroking a path take no points:
        elif name in ("begin_path", "stroke"):
            drawing.append((name, []))
        else:
            raise AssertionError(f"unexpected canvas call: {name}")
    return drawing


class ChristmasTreeDrawTest(unittest.TestCase):
    """Drawing the nodes of a Christmas tree onto a canvas."""

    def test_crystal_ball_node_draws_everything_shifted_by_the_same_y_offset(
        self,
    ) -> None:
        """A crystal-ball node draws its child triangles, children, candle and crystal ball shifted by the same y
        offset.
        """
        # build a tree whose root is a crystal-ball node with four leaves:
        tree: ChristmasTree[Vector, str] = ChristmasTree[Vector, str](
            children_per_inner_node=4,
            descriptor=Triangle(Vector(0, 0), Vector(300, 0), Vector(150, 300)),
            number_of_inner_node_levels=1,
            inner_node_factory=ChristmasTree.InnerNodeFactory[Vector, str](
                config="crystalball"
            ),
        )

        # put 35 points inside the triangle: the 31st put flushes the full buffer (30 pairs) into the leaves, and
        # the last 5 pairs stay in the buffer:
        for i in range(35):
            tree.put(Vector(100 + i, 50 + i), str(i))
        root: RadixTrie.AbstractNode[Vector, str] = tree.root
        self.assertIsInstance(root, ChristmasTree.CrystalBallBufferedInnerNode)
        assert isinstance(root, ChristmasTree.CrystalBallBufferedInnerNode)
        self.assertEqual(len(root.buffer), 5)

        # draw the root twice, onto two mock canvases that record every call, once with y offset 0 and once with
        # y offset 40:
        canvas_0: mock.MagicMock = mock.MagicMock()
        canvas_40: mock.MagicMock = mock.MagicMock()
        root.draw(canvas_0, canvas_height=300, x_offset=0, y_offset=0)
        root.draw(canvas_40, canvas_height=300, x_offset=0, y_offset=40)

        # the drawing with y offset 0 has the candle, the four child triangles, and 31 dots (the 30 keys in the
        # leaves and the crystal ball):
        recorded_0: list[tuple[str, list[tuple[float, float]]]] = _recorded_drawing(
            canvas_0
        )
        names_0: list[str] = [name for name, _ in recorded_0]
        self.assertEqual(names_0.count("fill_rect"), 1)
        self.assertEqual(names_0.count("fill_polygon"), 4)
        self.assertEqual(names_0.count("fill_arc"), 31)

        # a higher y offset moves every point up, i.e. its canvas y is 40 smaller and its x stays the same; exact
        # equality is safe, as all coordinates here are whole numbers or halves:
        recorded_40: list[tuple[str, list[tuple[float, float]]]] = _recorded_drawing(
            canvas_40
        )
        self.assertEqual(
            recorded_40,
            [(name, [(x, y - 40) for x, y in points]) for name, points in recorded_0],
        )


if __name__ == "__main__":
    unittest.main()
