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
"""Tests that ``BPlusTree.consistency_check`` accepts valid B+-trees and finds each broken invariant.

The five invariants are those of lecture 06a (slide "B-Tree Invariants and Rules"). Most broken trees are the example
tree of the lecture with one change each.
"""

import random
import unittest

from system.indexes.btree import BPlusTree


def linked(*leaves: BPlusTree.Leaf) -> list[BPlusTree.Leaf]:
    """Links the given leaves to their neighbours in the given order, in both directions.

    @param leaves: the leaves, from left to right
    @return: the leaves as a list
    """
    for left, right in zip(leaves, leaves[1:]):
        left.next = right
        right.previous = left
    return list(leaves)


def example_leaves() -> list[BPlusTree.Leaf]:
    """Returns the six linked leaves of the example tree of lecture 06a, with leaf capacity 4.

    @return: the leaves [3 8 9 11], [14 18 20], [21 22 25 31], [32 34 36], [39 41], [44 46 49], valued 1 to 19
    """
    return linked(
        BPlusTree.Leaf(4, [3, 8, 9, 11], [1, 2, 3, 4]),
        BPlusTree.Leaf(4, [14, 18, 20], [5, 6, 7]),
        BPlusTree.Leaf(4, [21, 22, 25, 31], [8, 9, 10, 11]),
        BPlusTree.Leaf(4, [32, 34, 36], [12, 13, 14]),
        BPlusTree.Leaf(4, [39, 41], [15, 16]),
        BPlusTree.Leaf(4, [44, 46, 49], [17, 18, 19]),
    )


def tree_with_root(
    root: BPlusTree.AbstractNode, inner_capacity: int = 3, leaf_capacity: int = 4
) -> BPlusTree[int, int]:
    """Returns a tree with the given capacities whose root is the given node.

    @param root: the root node
    @param inner_capacity: the capacity of the tree's inner nodes
    @param leaf_capacity: the capacity of the tree's leaves
    @return: the tree
    """
    tree: BPlusTree[int, int] = BPlusTree[int, int](inner_capacity, leaf_capacity)
    tree.root = root
    return tree


def example_tree(leaves: list[BPlusTree.Leaf] | None = None) -> BPlusTree[int, int]:
    """Returns the example tree of lecture 06a: root [32] over the inner nodes [13 21] and [38 43] over six leaves.

    @param leaves: the six leaves to use, by default those of :func:`example_leaves`
    @return: the tree, with inner capacity 3 and leaf capacity 4
    """
    leaves = example_leaves() if leaves is None else leaves
    left: BPlusTree.Inner = BPlusTree.Inner(3, [13, 21], leaves[:3])
    right: BPlusTree.Inner = BPlusTree.Inner(3, [38, 43], leaves[3:])
    return tree_with_root(BPlusTree.Inner(3, [32], [left, right]))


class ValidTreeTest(unittest.TestCase):
    """Valid B+-trees pass the consistency check."""

    def test_the_example_tree_of_the_lecture_is_valid(self) -> None:
        """The example tree of lecture 06a keeps all five invariants."""
        example_tree().consistency_check()

    def test_every_tree_built_by_put_is_valid(self) -> None:
        """A tree keeps all five invariants after every single put, for several capacities and insert orders.

        The smallest capacities split the most nodes; inner capacity 1 creates inner nodes with no key and one
        pointer, the fewest that a node with room for two pointers may have. Ascending and descending keys always
        split the same end of the tree.
        """
        shuffler: random.Random = random.Random(42)
        for inner_capacity, leaf_capacity in [
            (1, 1),
            (1, 3),
            (2, 1),
            (2, 2),
            (3, 4),
            (4, 3),
            (5, 2),
        ]:
            for order in ["ascending", "descending", "random"]:
                with self.subTest(
                    inner=inner_capacity, leaf=leaf_capacity, order=order
                ):
                    # the keys 0 to 99 in the given order:
                    keys: list[int] = list(range(100))
                    if order == "descending":
                        keys.reverse()
                    elif order == "random":
                        shuffler.shuffle(keys)

                    # put them one by one and check the tree after each put:
                    tree: BPlusTree[int, int] = BPlusTree[int, int](
                        inner_capacity, leaf_capacity
                    )
                    for key in keys:
                        tree.put(key, key * 10)
                        tree.consistency_check()
                    self.assertEqual(100, tree.size())

    def test_a_root_may_be_less_than_half_full(self) -> None:
        """A root may be less than half full: an empty tree and a root leaf with one of four entries are valid."""
        # the empty tree, a single empty leaf:
        BPlusTree[int, int](3, 4).consistency_check()

        # a root leaf with one key:
        tree: BPlusTree[int, int] = BPlusTree[int, int](3, 4)
        tree.put(7, 70)
        tree.consistency_check()

    def test_a_subtree_is_valid_on_its_own(self) -> None:
        """The right subtree of the example tree is a valid B+-tree on its own, although its first leaf has a left
        neighbour."""
        subtree: BPlusTree.AbstractNode = example_tree().root.children[1]
        subtree.consistency_check()


class BrokenInvariantTest(unittest.TestCase):
    """The consistency check finds each broken invariant of lecture 06a and names it."""

    def test_inv1_a_key_on_the_wrong_side_of_a_separator(self) -> None:
        """A key outside the interval of its leaf breaks Inv1, below or above it."""
        # 31 in the leaf right of the root's separator 32; also with the value of the 31 in the leaf left of it, as
        # the check looks at where a key is, not at its value:
        for value in [12, 11]:
            with self.subTest(case="31 right of 32", value=value):
                leaves: list[BPlusTree.Leaf] = example_leaves()
                leaves[3].keys[0], leaves[3].values[0] = 31, value
                tree: BPlusTree[int, int] = example_tree(leaves)
                with self.assertRaisesRegex(
                    AssertionError, "^Inv1: key 31 is less than the separator 32 left"
                ):
                    tree.consistency_check()

        # 13 in the first leaf, whose interval in its parent ends below the separator 13:
        with self.subTest(case="13 not below 13"):
            leaves = example_leaves()
            leaves[0].keys[-1] = 13
            tree = example_tree(leaves)
            with self.assertRaisesRegex(
                AssertionError, "^Inv1: key 13 is not less than the separator 13 right"
            ):
                tree.consistency_check()

    def test_inv2_a_node_less_than_half_full(self) -> None:
        """A node other than the root that is less than half full breaks Inv2.

        A leaf with capacity c needs c / 2 entries, an inner node with capacity c needs (c + 1) / 2 pointers, both
        rounded up; the odd capacities 3 (leaf) and 4 (inner node) show the rounding.
        """
        # the leaf [39 41] with 39 only, 1 of 4 entries:
        with self.subTest(node="leaf, capacity 4"):
            leaves: list[BPlusTree.Leaf] = example_leaves()
            leaves[4].keys, leaves[4].values = [39], [15]
            tree: BPlusTree[int, int] = example_tree(leaves)
            with self.assertRaisesRegex(
                AssertionError, r"^Inv2: the leaf \[39\] holds 1 of 4 entries"
            ):
                tree.consistency_check()

        # a leaf with 1 of 3 entries, which needs 2:
        with self.subTest(node="leaf, capacity 3"):
            leaves = linked(
                BPlusTree.Leaf(3, [1, 2], [1, 2]), BPlusTree.Leaf(3, [10], [3])
            )
            tree = tree_with_root(BPlusTree.Inner(3, [10], leaves), 3, 3)
            with self.assertRaisesRegex(
                AssertionError, r"^Inv2: the leaf \[10\] holds 1 of 3 entries"
            ):
                tree.consistency_check()

        # an inner node with no key and a single pointer, 1 of 4, to one leaf with the keys 32 to 41:
        with self.subTest(node="inner node, capacity 3"):
            leaves = linked(
                *example_leaves()[:3], BPlusTree.Leaf(4, [32, 34, 39, 41], [1, 2, 3, 4])
            )
            left: BPlusTree.Inner = BPlusTree.Inner(3, [13, 21], leaves[:3])
            right: BPlusTree.Inner = BPlusTree.Inner(3, [], leaves[3:])
            tree = tree_with_root(BPlusTree.Inner(3, [32], [left, right]))
            with self.assertRaisesRegex(
                AssertionError, r"^Inv2: the inner node \[\] has 1 of 4 pointers"
            ):
                tree.consistency_check()

        # an inner node with 2 of 5 pointers, which needs 3:
        with self.subTest(node="inner node, capacity 4"):
            leaves = linked(
                *(
                    BPlusTree.Leaf(2, [k, k + 1], [k, k + 1])
                    for k in [1, 10, 20, 30, 40]
                )
            )
            left = BPlusTree.Inner(4, [10], leaves[:2])
            right = BPlusTree.Inner(4, [30, 40], leaves[2:])
            tree = tree_with_root(BPlusTree.Inner(4, [20], [left, right]), 4, 2)
            with self.assertRaisesRegex(
                AssertionError, r"^Inv2: the inner node \[10\] has 2 of 5 pointers"
            ):
                tree.consistency_check()

    def test_inv3_leaves_at_different_depths(self) -> None:
        """Leaves at different depths break Inv3: the root points to an inner node and directly to a leaf."""
        # the three left leaves below an inner node, a fourth leaf directly below the root, which ends the chain:
        leaves: list[BPlusTree.Leaf] = linked(*example_leaves()[:4])
        leaves[3].next = None
        left: BPlusTree.Inner = BPlusTree.Inner(3, [13, 21], leaves[:3])
        tree: BPlusTree[int, int] = tree_with_root(
            BPlusTree.Inner(3, [32], [left, leaves[3]])
        )
        with self.assertRaisesRegex(
            AssertionError,
            r"^Inv3: the subtrees below the inner node \[32\] have different heights \[1, 0\]",
        ):
            tree.consistency_check()

    def test_inv4_keys_out_of_order_or_too_many(self) -> None:
        """Keys out of order or twice inside a node, and more keys than its capacity, break Inv4."""
        # 8 before 3 in the first leaf:
        with self.subTest(case="leaf out of order"):
            leaves: list[BPlusTree.Leaf] = example_leaves()
            leaves[0].keys[:2] = [8, 3]
            tree: BPlusTree[int, int] = example_tree(leaves)
            with self.assertRaisesRegex(
                AssertionError,
                r"^Inv4: the keys of the leaf \[8, 3, 9, 11\] are not sorted",
            ):
                tree.consistency_check()

        # 8 twice in the first leaf:
        with self.subTest(case="key twice in a leaf"):
            leaves = example_leaves()
            leaves[0].keys[2] = 8
            tree = example_tree(leaves)
            with self.assertRaisesRegex(
                AssertionError, r"^Inv4: the leaf \[3, 8, 8, 11\] holds a key twice"
            ):
                tree.consistency_check()

        # the separators [21 13] of the left inner node out of order; this also leaves a pointer with an empty
        # interval (Inv1), but the order of the keys is checked first:
        with self.subTest(case="inner node out of order"):
            tree = example_tree()
            tree.root.children[0].keys = [21, 13]
            with self.assertRaisesRegex(
                AssertionError,
                r"^Inv4: the keys of the inner node \[21, 13\] are not sorted",
            ):
                tree.consistency_check()

        # the separator 43 twice in the right inner node, over four leaves; this, too, leaves an empty interval:
        with self.subTest(case="separator twice"):
            leaves = example_leaves()
            extra: BPlusTree.Leaf = BPlusTree.Leaf(4, [50, 51], [1, 2])
            linked(*leaves, extra)
            left: BPlusTree.Inner = BPlusTree.Inner(3, [13, 21], leaves[:3])
            right: BPlusTree.Inner = BPlusTree.Inner(
                3, [38, 43, 43], [*leaves[3:], extra]
            )
            tree = tree_with_root(BPlusTree.Inner(3, [32], [left, right]))
            with self.assertRaisesRegex(
                AssertionError,
                r"^Inv4: the keys of the inner node \[38, 43, 43\] are not sorted",
            ):
                tree.consistency_check()

        # five entries in a leaf of capacity 4:
        with self.subTest(case="leaf over capacity"):
            leaves = example_leaves()
            leaves[0].keys, leaves[0].values = [3, 8, 9, 10, 11], [1, 2, 3, 4, 5]
            tree = example_tree(leaves)
            with self.assertRaisesRegex(
                AssertionError,
                r"^Inv4: the leaf \[3, 8, 9, 10, 11\] holds 5 entries, more than its capacity 4",
            ):
                tree.consistency_check()

        # four keys in a root of capacity 3, over five leaves:
        with self.subTest(case="inner node over capacity"):
            leaves = linked(
                *(
                    BPlusTree.Leaf(4, [k, k + 1], [k, k + 1])
                    for k in [0, 10, 20, 30, 40]
                )
            )
            tree = tree_with_root(BPlusTree.Inner(3, [10, 20, 30, 40], leaves))
            with self.assertRaisesRegex(
                AssertionError,
                r"^Inv4: the inner node \[10, 20, 30, 40\] holds 4 keys, more than its capacity 3",
            ):
                tree.consistency_check()

    def test_inv5_leaves_not_linked_to_their_neighbours(self) -> None:
        """A missing link, links in the wrong order or backwards, and links beyond the first or last leaf break Inv5.

        A link that points backwards would make a range query run in a circle; the check finds it without following
        the links.
        """
        # the third leaf without a link to the fourth, which lies in the other subtree of the root:
        with self.subTest(case="missing link between subtrees"):
            leaves: list[BPlusTree.Leaf] = example_leaves()
            leaves[2].next = None
            tree: BPlusTree[int, int] = example_tree(leaves)
            with self.assertRaisesRegex(
                AssertionError,
                r"^Inv5: the neighbouring leaves \[21, 22, 25, 31\] and \[32, 34, 36\] are not linked",
            ):
                tree.consistency_check()

        # the first leaf without a link to the second, both below the same inner node:
        with self.subTest(case="missing link inside a subtree"):
            leaves = example_leaves()
            leaves[0].next = None
            tree = example_tree(leaves)
            with self.assertRaisesRegex(
                AssertionError,
                r"^Inv5: the neighbouring leaves \[3, 8, 9, 11\] and \[14, 18, 20\] are not linked",
            ):
                tree.consistency_check()

        # the first two leaves linked in the wrong order, with links in both directions that fit each other:
        with self.subTest(case="links in the wrong order"):
            leaves = example_leaves()
            linked(leaves[1], leaves[0], leaves[2])
            leaves[1].previous = None
            tree = example_tree(leaves)
            with self.assertRaisesRegex(
                AssertionError,
                r"^Inv5: the neighbouring leaves \[3, 8, 9, 11\] and \[14, 18, 20\] are not linked",
            ):
                tree.consistency_check()

        # the third leaf linked back to the first:
        with self.subTest(case="link backwards"):
            leaves = example_leaves()
            leaves[2].next = leaves[0]
            tree = example_tree(leaves)
            with self.assertRaisesRegex(
                AssertionError,
                r"^Inv5: the neighbouring leaves \[21, 22, 25, 31\] and \[32, 34, 36\] are not linked",
            ):
                tree.consistency_check()

        # a leaf outside the tree linked before the first leaf, and one after the last leaf, in both directions:
        with self.subTest(case="link beyond the first leaf"):
            leaves = example_leaves()
            linked(BPlusTree.Leaf(4, [1, 2], [1, 2]), leaves[0])
            tree = example_tree(leaves)
            with self.assertRaisesRegex(
                AssertionError,
                r"^Inv5: the first leaf \[3, 8, 9, 11\] has a left neighbour",
            ):
                tree.consistency_check()
        with self.subTest(case="link beyond the last leaf"):
            leaves = example_leaves()
            linked(leaves[-1], BPlusTree.Leaf(4, [50, 51], [1, 2]))
            tree = example_tree(leaves)
            with self.assertRaisesRegex(
                AssertionError,
                r"^Inv5: the last leaf \[44, 46, 49\] has a right neighbour",
            ):
                tree.consistency_check()


class BrokenStructureTest(unittest.TestCase):
    """The consistency check finds trees whose nodes do not fit together, and fails instead of running forever."""

    def test_a_node_with_another_capacity_than_the_tree(self) -> None:
        """A leaf of capacity 1 in a tree of leaf capacity 4 is reported, although it would count as half full."""
        leaves: list[BPlusTree.Leaf] = example_leaves()
        leaves[4] = BPlusTree.Leaf(1, [39], [15])
        linked(*leaves)
        tree: BPlusTree[int, int] = example_tree(leaves)
        with self.assertRaisesRegex(
            AssertionError, r"^the leaf \[39\] has capacity 1, the tree's leaves 4"
        ):
            tree.consistency_check()

    def test_a_node_reached_twice(self) -> None:
        """A pointer back up to the root, and a leaf with two parents, are reported instead of looping forever."""
        # the first pointer of the left inner node leads back up to the root:
        with self.subTest(case="pointer back up"):
            tree: BPlusTree[int, int] = example_tree()
            tree.root.children[0].children[0] = tree.root
            with self.assertRaisesRegex(
                AssertionError, "^the pointers reach a node twice"
            ):
                tree.consistency_check()

        # the third leaf is also the first child of the right inner node:
        with self.subTest(case="leaf with two parents"):
            tree = example_tree()
            tree.root.children[1].children[0] = tree.root.children[0].children[2]
            with self.assertRaisesRegex(
                AssertionError, "^the pointers reach a node twice"
            ):
                tree.consistency_check()

    def test_a_tree_with_counting_leaves_is_not_supported(self) -> None:
        """A tree whose leaves only count (see convert_to_counting_leaf_tree) raises NotImplementedError."""
        # a tree of three levels, whose leaves are then replaced by counting leaves:
        tree: BPlusTree[int, int] = BPlusTree[int, int](3, 4)
        for key in range(30):
            tree.put(key, key)
        tree.convert_to_counting_leaf_tree()

        with self.assertRaises(NotImplementedError):
            tree.consistency_check()


if __name__ == "__main__":
    unittest.main()
