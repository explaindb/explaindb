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

"""B+-tree index implementation with node splitting."""

from __future__ import (
    annotations,
)  # postponed evaluation of annotations https://peps.python.org/pep-0563/

import copy
from typing import cast, Iterator
from abc import ABC, abstractmethod
from itertools import count
from dataclasses import dataclass

from IPython.core.display_functions import display

from system.interfaces.indexing.Index import AbstractBTree, PutInfo
from typing import Optional

import bisect
import graphviz


@dataclass
class NoSplit(PutInfo):
    """Result of a put that did not cause a node to split."""


@dataclass
class SplitHappens[Key](PutInfo):
    """Result of a put that caused a node to split into two.

    Wraps the two nodes produced by the split and the pivot key that separates them: ``left_node`` holds the
    keys below the pivot, ``right_node`` holds the keys at or above it, and ``pivot`` is the separating key
    propagated up to the parent.
    """

    left_node: BPlusTree.AbstractNode
    right_node: BPlusTree.AbstractNode
    pivot: Key


def _leftmost_leaf(node: BPlusTree.AbstractNode) -> BPlusTree.Leaf:
    """Returns the leftmost leaf of the subtree of a node, i.e. the one reached by always following the first pointer.

    :param node: an inner node or a leaf
    :return: the leftmost leaf below ``node`` (``node`` itself if it is a leaf)
    """
    while isinstance(node, BPlusTree.Inner):
        node = node.children[0]
    return cast(BPlusTree.Leaf, node)


def _rightmost_leaf(node: BPlusTree.AbstractNode) -> BPlusTree.Leaf:
    """Returns the rightmost leaf of the subtree of a node, i.e. the one reached by always following the last pointer.

    :param node: an inner node or a leaf
    :return: the rightmost leaf below ``node`` (``node`` itself if it is a leaf)
    """
    while isinstance(node, BPlusTree.Inner):
        node = node.children[-1]
    return cast(BPlusTree.Leaf, node)


def _height(node: BPlusTree.AbstractNode) -> int:
    """Returns the number of pointers on the way from a node down to its leftmost leaf.

    :param node: an inner node or a leaf
    :return: 0 for a leaf, 1 for an inner node above leaves, and so on
    """
    height: int = 0
    while isinstance(node, BPlusTree.Inner):
        node = node.children[0]
        height += 1
    return height


def _fill_of(node: BPlusTree.AbstractNode) -> str:
    """Describes how full a node is, for the message of a broken invariant Inv2.

    :param node: an inner node or a leaf
    :return: e.g. "the leaf [39] holds 1 of 4 entries" or "the inner node [] has 1 of 4 pointers"
    """
    if isinstance(node, BPlusTree.Inner):
        return f"the inner node {node.keys} has {len(node.children)} of {node.capacity + 1} pointers"
    return f"the leaf {node.keys} holds {len(node.keys)} of {node.capacity} entries"


def _nodes_reached_once(root: BPlusTree.AbstractNode) -> list[BPlusTree.AbstractNode]:
    """Returns all nodes of a tree, after checking that the pointers reach each of them exactly once from the root.

    A node reached twice, through a pointer back up or because two inner nodes point to it, would make the other
    checks of :meth:`BPlusTree.consistency_check` run forever or look at the node twice.

    :param root: the root of the tree
    :return: the nodes, the root first
    :raise AssertionError: if a node is reached twice
    :raise NotImplementedError: if the tree has counting leaves, which the consistency check does not support
    """
    nodes: list[BPlusTree.AbstractNode] = []
    seen: set[int] = set()
    to_visit: list[BPlusTree.AbstractNode] = [root]
    while to_visit:
        node: BPlusTree.AbstractNode = to_visit.pop()
        assert (
            id(node) not in seen
        ), "the pointers reach a node twice from the root: a pointer leads back up, or a node has two parents"
        if isinstance(node, BPlusTree.CountingLeaf):
            raise NotImplementedError(
                "the consistency check does not support trees with counting leaves"
            )
        seen.add(id(node))
        nodes.append(node)
        if isinstance(node, BPlusTree.Inner):
            to_visit.extend(node.children)
    return nodes


class BPlusTree[Key, Value](AbstractBTree[Key, Value]):
    """A simple, educational B+tree implementation with support for inserts, splits, as well as
    point, and range queries.
    Deletes and merges are not supported.
    Note that this outside class is simply a wrapper around the actual tree which is held as a reference.
    So this is a Decorator Design Pattern.
    The only purpose of the outside wrapper is to keep track of basic capacity parameters
    AND handle the root node in case of a split.
    """

    class AbstractNode(AbstractBTree[Key, Value], ABC):
        """Abstract node API of a b+-tree. An abstract node can be either implemented as an inner node or a leaf node.
        An abstract node and all its subclasses are valid B-Tree Indexes.
        """

        # class variable, node counter used to assign unique ids to nodes:
        _ids: count[int] = count(0)

        # the keys of the node, set by Inner and Leaf (a CountingLeaf has none):
        keys: list[Key]

        def __init__(self, capacity: int):
            """Initializes a node with a given capacity.
            :param capacity: The maximum number of keys that can be stored in this node.
            """

            self.id: int = next(self._ids)
            self.capacity: int = capacity  # max capacity of this node

        @abstractmethod
        def put(self, key: Key, value: Value) -> None | PutInfo:
            """Insert the given `key` and `value` into the abstract node.

            :param key: The key to insert.
            :param value: The value to insert.
            :return: A PutInfo instance: NoSplit if the pair fit without splitting, or SplitHappens (wrapping
            the two new nodes and the pivot) if this insertion caused a split.
            """

        @abstractmethod
        def split(
            self,
        ) -> SplitHappens[Key]:
            """Split-operation for nodes. Splits the keys and values of this node into two nodes.

            :return: A SplitHappens instance wrapping the left node, the right node, and the new pivot if a split occurred
            """

        @abstractmethod
        def get(self, key: Key) -> Iterator[Value]:
            """See :meth:`PointQueryMixIn.get`."""

        @abstractmethod
        def get_all_in_range(self, min_key: Key, max_key: Key) -> Iterator[Value]:
            """See :meth:`RangeQueryMixIn.get_all_in_range`."""

        @abstractmethod
        def is_full(self) -> bool:
            """Returns true if the node is full, otherwise false."""

        @abstractmethod
        def is_at_least_half_full(self) -> bool:
            """Returns true if the node is at least half full, otherwise false.

            Every node of a B+-tree except the root must be at least half full (invariant Inv2 of lecture 06a, slide
            "B-Tree Invariants and Rules"). For a leaf this counts its entries, for an inner node its pointers to
            children (one more than its keys): after a split, an inner node may hold fewer keys than half its
            capacity c, but never fewer pointers than half of the c + 1 it can hold.
            """

        @abstractmethod
        def size(self) -> int:
            """Returns the number of keys in the subtree."""

        @abstractmethod
        def dot(self, s: str) -> str:
            """Returns a string representation of the node in dot format."""

        @abstractmethod
        def consistency_check(self) -> None:
            """Checks that the subtree of this node is a valid B+-tree with this node as its root.

            Raises ``AssertionError`` if the structure of a node is broken (an inner node with not exactly one more
            child than keys or with a child twice, a leaf with not as many values as keys), or if one of the
            invariants of lecture 06a (slide "B-Tree Invariants and Rules") does not hold; the message then starts
            with the name of the invariant:

            - Inv1: each node partitions the keys of its subtree: the subtree of the child between the separators a
              and b holds only keys k with a <= k < b;
            - Inv2: every node of the subtree except this one is at least half full (see :meth:`is_at_least_half_full`);
            - Inv3: all leaves of the subtree lie at the same depth;
            - Inv4: the keys inside each node are sorted in ascending order, without duplicates, and no node holds
              more keys than its capacity;
            - Inv5: each leaf of the subtree is linked to its left and right neighbour in key order.

            The links of the leftmost and rightmost leaf may point outside the subtree, as the subtree may be part of
            a larger tree. :meth:`BPlusTree.consistency_check` checks in addition that the chain of leaves begins at
            the tree's first leaf and ends at its last, that every node has the capacity of the tree, and that the
            pointers reach every node exactly once (a pointer back up would make this check run forever). The check
            consists of ``assert`` statements, so it does nothing when Python runs with ``-O``.
            """

        def delete(self, key: Key, value: Value = None) -> None:
            """See :meth:`Index.delete`.

            Not supported for b+-tree nodes.
            """
            raise NotImplementedError

        def flush(self, key: Key | None = None) -> None:
            """See :meth:`Index.flush`.

            Not supported for b+-tree nodes.
            """
            raise NotImplementedError

        @abstractmethod
        def show(self) -> None:
            """Shows the content of the index."""

    class Inner(AbstractNode):
        """Inner node of a b+-tree. Inner nodes have keys and references to children subtrees, i.e. Nodes or Leaves.
        Inner Nodes in inself are an index structure.
        """

        def __init__(
            self, capacity: int, keys: list[Key], children: list[BPlusTree.AbstractNode]
        ):
            """Initializes an inner node with a given capacity, its keys, and its children.

            :param capacity: The maximum number of keys that can be stored in this node.
            :param keys: The keys of this node as a list.
            :param children: The children of this node as a list.
            """

            super().__init__(capacity)
            assert len(keys) + 1 == len(
                children
            ), "an inner node has to contain one more child than keys"

            assert sorted(keys) == keys, "keys need to be sorted"

            # assign keys and children
            self.keys: list[Key] = copy.copy(keys)
            self.children: list[BPlusTree.AbstractNode] = copy.copy(children)

        def show(self) -> None:
            """Shows the content of the inner node."""
            print(self.keys)
            for child in self.children:
                child.show()

        def split(self) -> SplitHappens[Key]:
            """Split-operation for inner nodes. This implementation splits the keys and children of this node into two
            inner nodes plus pivot.
            Note: No re-use of this instance, we are creating two new Inner-instances.

            :return: A SplitHappens wrapping the left node, the right node, and the new pivot.
            """

            # find middle (aka pivot) element:
            mid: int = len(self.keys) // 2

            # return two new Inner instances and the pivot key,
            # note: this is in spirit similar to what happens in a partitioning step in quicksort:
            # BUT: the pivot is REMOVED from the partitions, it moves up into the parent! (compare with Leaf.split)
            return SplitHappens[Key](
                # left node:
                left_node=BPlusTree.Inner(
                    self.capacity, self.keys[:mid], self.children[: mid + 1]
                ),
                # right node:
                right_node=BPlusTree.Inner(
                    self.capacity, self.keys[mid + 1 :], self.children[mid + 1 :]
                ),
                # the pivot (key) separating the two partitions (aka nodes):
                pivot=self.keys[mid],
            )

        def put(self, key: Key, value: Value) -> PutInfo:
            """Insert the given `key` and `value` into the inner node.

            :param key: The key to insert.
            :param value: The value to insert.
            :return: A PutInfo instance: NoSplit if the pair fit without splitting, or SplitHappens (wrapping
            the two new nodes and the pivot) if this insertion caused a split.
            """

            # perform binary search to find the position to insert the key:
            pos: int = bisect.bisect(self.keys, key)
            put_info: PutInfo | None = self.children[pos].put(key, value)

            if (
                type(put_info) == SplitHappens
            ):  # a split happened in the layer immediately below this node
                split_happens: SplitHappens[Key] = cast(SplitHappens[Key], put_info)
                # check if this node is full:
                if self.is_full():
                    pivot_pos = bisect.bisect_left(self.keys, split_happens.pivot)
                    del self.children[
                        pivot_pos
                    ]  # remove old child and replace with the two new children (obtained through split in layer below)
                    # insert the two new children at the correct position:
                    self.children.insert(pivot_pos, split_happens.left_node)
                    self.children.insert(pivot_pos + 1, split_happens.right_node)
                    # insert the pivot: this node now overflows temporarily, as it holds capacity + 1 keys, one more
                    # than allowed; the split right below replaces it by two new nodes:
                    self.keys.insert(pivot_pos, split_happens.pivot)

                    # split this node:
                    return self.split()

                # post condition: this node is not full and has room to insert the new pivot returned from the split
                del self.children[
                    pos
                ]  # remove old child and replace with the two new children (obtained through split in layer below)
                self.children.insert(pos, split_happens.left_node)
                self.children.insert(pos + 1, split_happens.right_node)
                self.keys.insert(pos, split_happens.pivot)

            return NoSplit()

        def get(self, key: Key) -> Iterator[Value]:
            """Finds the appropriate subtree to search for the given `key` and calls `get` on that subtree.
            :param key: The key to search for.
            """

            # find subtree:
            pos: int = bisect.bisect(self.keys, key)

            # delegate to subtree:
            return self.children[pos].get(key)

        def get_all_in_range(self, min_key: Key, max_key: Key) -> Iterator[Value]:
            """Finds the appropriate subtree to search for the given key range and calls `get_all_in_range` on that subtree.

            :param min_key: The minimum key to search for.
            :param max_key: The maximum key to search for.
            :return: A list of values for all keys in the given range.
            """

            # find subtree:
            pos: int = bisect.bisect(self.keys, min_key)

            # delegate to subtree:
            return self.children[pos].get_all_in_range(min_key, max_key)

        def is_full(self) -> bool:
            """Returns true if the node is full, otherwise false."""

            return len(self.keys) == self.capacity

        def is_at_least_half_full(self) -> bool:
            """See :meth:`AbstractNode.is_at_least_half_full`.

            Counts the pointers to children: a node with capacity c has up to c + 1 of them, so it needs at least
            (c + 1) / 2, rounded up.
            """

            # x / 2 rounded up is (x + 1) // 2, here with x = c + 1:
            return len(self.children) >= (self.capacity + 2) // 2

        def size(self) -> int:
            """Returns the number of keys mapped by this subtree.

            :return: The sum of the number of keys of this subtree.
            """

            return sum(child.size() for child in self.children)

        def dot(self, s: str) -> str:
            """Returns a string representation of the inner node in dot format."""

            s += f"\t{self.id} [label=<\n"
            s += '\t\t<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4">\n'
            s += "\t\t\t<TR>"
            for i in range(self.capacity):
                s += f'<TD BGCOLOR="royalblue" PORT="p{i}"></TD>'
                s += f'<TD BGCOLOR="khaki1" WIDTH="20">{self.keys[i] if i < len(self.keys) else ""}</TD>'

            s += f'<TD BGCOLOR="royalblue" PORT="p{len(self.keys)}"></TD>'
            s += "</TR>\n"
            s += "\t\t</TABLE>\n"
            s += "\t>, shape=plaintext];\n"
            # draw edges
            for i, child in enumerate(self.children):
                s += f"\t{self.id}:p{i} -> {child.id};\n"
            # recursively dot children
            for child in self.children:
                s = child.dot(s)
            return s

        def consistency_check(self) -> None:
            """See :meth:`AbstractNode.consistency_check`.

            Checks this node and the borders between the subtrees of its children, then the subtree of each child.
            That is enough: in a valid subtree the keys ascend from its leftmost to its rightmost leaf, its leaves lie
            at one depth, and its leaves are linked to each other. So this node only needs to compare the first and
            the last key of each subtree with its separators, the heights of the subtrees, and the one link where two
            neighbouring subtrees meet. A node is walked over at most once per level above it, and in total the check
            takes time about linear in the size of the tree.
            """

            # the structure of the node: one more child than keys, each child only once:
            assert len(self.keys) + 1 == len(
                self.children
            ), "an inner node has to contain one more child than keys"
            assert len(set(self.children)) == len(
                self.children
            ), "an inner node has to point to each child only once"

            # at most `capacity` keys, in strictly ascending order (Inv4):
            assert (
                len(self.keys) <= self.capacity
            ), f"Inv4: the inner node {self.keys} holds {len(self.keys)} keys, more than its capacity {self.capacity}"
            assert all(
                key < next_key for key, next_key in zip(self.keys, self.keys[1:])
            ), f"Inv4: the keys of the inner node {self.keys} are not sorted in ascending order without duplicates"

            # each child is at least half full, as it is not the root (Inv2):
            for child in self.children:
                assert (
                    child.is_at_least_half_full()
                ), f"Inv2: {_fill_of(child)}, less than half, although it is not the root"

            # the subtree of each child holds only keys between the separators left and right of its pointer (Inv1);
            # the first and the last child have no separator on one side. The keys of a valid subtree ascend from its
            # leftmost to its rightmost leaf, so the first key of the one and the last key of the other suffice:
            for i, child in enumerate(self.children):
                first: BPlusTree.Leaf = _leftmost_leaf(child)
                last: BPlusTree.Leaf = _rightmost_leaf(child)
                if i > 0 and first.keys:
                    assert (
                        first.keys[0] >= self.keys[i - 1]
                    ), f"Inv1: key {first.keys[0]} is less than the separator {self.keys[i - 1]} left of the pointer that leads to its leaf"
                if i < len(self.keys) and last.keys:
                    assert (
                        last.keys[-1] < self.keys[i]
                    ), f"Inv1: key {last.keys[-1]} is not less than the separator {self.keys[i]} right of the pointer that leads to its leaf"

            # the subtrees of all children are equally high (Inv3); in a valid subtree all leaves lie at one depth,
            # so all leaves below this node then lie at the same depth:
            heights: list[int] = [_height(child) for child in self.children]
            assert (
                len(set(heights)) == 1
            ), f"Inv3: the subtrees below the inner node {self.keys} have different heights {heights}, so its leaves lie at different depths"

            # where two neighbouring subtrees meet, the rightmost leaf of the left one and the leftmost leaf of the
            # right one are linked to each other, in both directions (Inv5):
            for left_child, right_child in zip(self.children, self.children[1:]):
                left_leaf: BPlusTree.Leaf = _rightmost_leaf(left_child)
                right_leaf: BPlusTree.Leaf = _leftmost_leaf(right_child)
                assert (
                    left_leaf.next is right_leaf and right_leaf.previous is left_leaf
                ), f"Inv5: the neighbouring leaves {left_leaf.keys} and {right_leaf.keys} are not linked to each other in both directions"

            # the same inside the subtree of each child:
            for child in self.children:
                child.consistency_check()

    class Leaf(AbstractNode):
        """Leaf node of a b-tree. Leaf nodes have keys and values."""

        def __init__(
            self,
            capacity: int,
            keys: Optional[list[Key]] = None,
            values: Optional[list[Value]] = None,
        ):
            """Initializes a leaf node with a given capacity, keys, and values.

            :param capacity: The maximum number of keys that can be stored in this node.
            :param keys: The keys of this node as a list.
            :param values: The values of this node as a list.
            """
            super().__init__(capacity)
            if keys and values:
                assert len(keys) == len(
                    values
                ), "keys and values need to have same length"
                assert (
                    len(keys) <= capacity
                ), "number of leaf entries exceeds max capacity"

            self.keys: list[Key] = (
                keys if keys is not None else []
            )  # use `None` as default to avoid shared mutable default arguments

            self.values: list[Value] = (
                values if values is not None else []
            )  # use `None` as default to avoid shared mutable default arguments

            # links for ISAM: sequential scanning on leaves in both directions:
            self.previous: Optional[BPlusTree.Leaf] = None
            self.next: Optional[BPlusTree.Leaf] = None

        def show(self) -> None:
            """Shows the content of the leaf."""
            print(self.keys)
            print(self.values)

        def split(self) -> SplitHappens[Key]:
            """Split operation for leaf nodes. This implementation splits the keys and values of this Leaf into two
            Leaves.
            Note: No re-use of this instance, we are creating two new Leaf instances.

            :return: A SplitHappens wrapping the left leaf, the right leaf, and the new pivot.
            """

            # find middle (aka pivot) element:
            mid: int = len(self.keys) // 2

            # return two new Leaf instances and the pivot key,
            # note: this is in spirit similar to what happens in a partitioning step in quicksort:
            return SplitHappens[Key](
                # left leaf:
                left_node=BPlusTree.Leaf(
                    self.capacity, self.keys[:mid], self.values[:mid]
                ),
                # right leaf:
                right_node=BPlusTree.Leaf(
                    self.capacity, self.keys[mid:], self.values[mid:]
                ),
                # the pivot (key) separating the two partitions (aka leaves):
                pivot=self.keys[mid],
            )

        def put(self, key: Key, value: Value) -> PutInfo:
            """Insert the given `key` and `value` into the leaf.

            :param key: The key to insert.
            :param value: The value to insert.
            :return: A PutInfo instance: NoSplit if the pair fit without splitting, or SplitHappens (wrapping
            the two new nodes and the pivot) if this insertion caused a split.
            """
            # find the position to insert the key:
            pos: int = bisect.bisect_left(self.keys, key)

            # does the key already exist in the leaf?
            if pos != len(self.keys) and self.keys[pos] == key:
                # update: replace value of already existing key
                self.values[pos] = value

                return NoSplit()

            if not self.is_full():
                # leaf was not full _before_ inserting the new key-value pair:
                assert len(self.keys) < self.capacity
                self.keys.insert(pos, key)
                self.values.insert(pos, value)

                return NoSplit()

            # the leaf is full:
            assert len(self.keys) == self.capacity

            # maximum capacity reached (before inserting!): split the leaf
            # variant implemented: first insert allowing for overflow, then split
            # (1.) insert key-value pair at correct position:
            self.keys.insert(pos, key)
            self.values.insert(pos, value)

            # the leaf overflows temporarily: it holds one key more than allowed:
            assert len(self.keys) == self.capacity + 1

            # (2.) split the leaf:
            # call split to create two new leaf nodes:
            split_happens: SplitHappens[Key] = self.split()

            # the split of a leaf returns two leaves:
            left_leaf: BPlusTree.Leaf = cast(BPlusTree.Leaf, split_happens.left_node)
            right_leaf: BPlusTree.Leaf = cast(BPlusTree.Leaf, split_happens.right_node)

            # (3.) redirect leaf pointers for sequential scanning
            # is there a leaf to the left of self?: update its next pointer
            if self.previous:
                self.previous.next = left_leaf

            # new left node points to the previous leaf:
            left_leaf.previous = self.previous
            # new left node points to the right node (just created by the split):
            left_leaf.next = right_leaf

            # new right node points to the new left node (just created by the split):
            right_leaf.previous = left_leaf
            # new right node points to the next leaf:
            right_leaf.next = self.next

            if self.next:
                self.next.previous = right_leaf

            # return the split information up the call stack:
            return split_happens

        def get(self, key: Key) -> Iterator[Value]:
            """Returns the value for the given key if it exists.
            :param key: The key to search for.
            """
            # perform binary search to find the position of the key:
            pos: int = bisect.bisect_left(self.keys, key)

            # check if that key is contained in the keys list:
            if pos != len(self.keys) and self.keys[pos] == key:
                yield self.values[pos]
            else:
                raise KeyError

        def _scan_leaf(
            self, max_key: Key, result: list[Value], start_pos: int = 0
        ) -> bool:
            """Scans the leaf and adds the value of each key that is less than or are equal to `max_key` to the
            result list.

            :param max_key: The maximum key to scan up to (inclusive).
            :param result: The list to append the values to.

            :return: Returns true if we need to scan the next leaf as well, otherwise returns false.
            """
            for pos in range(start_pos, len(self.keys)):
                if self.keys[pos] > max_key:  # inclusive `max_key`
                    return False
                result.append(self.values[pos])

            return True

        def get_all_in_range(self, min_key: Key, max_key: Key) -> Iterator[Value]:
            """Returns a list of values for all keys in the given range. Implements ISAM-like sequential scanning.

            :param min_key: The minimum key to search for.
            :param max_key: The maximum key to search for.
            :return: A list of values for all keys in the given range.
            """

            result: list[Value] = list[Value]()
            pos: int = bisect.bisect_left(self.keys, min_key)

            # scan this leaf and check whether we have to continue scanning with next leaf:
            continue_scan: bool = self._scan_leaf(max_key, result, pos)
            next_leaf: BPlusTree.Leaf = self.next

            # keep on scanning the next leaf until we reach the end of the range:
            while continue_scan and next_leaf:
                # scan next_leaf:
                continue_scan = next_leaf._scan_leaf(max_key, result)
                # update next leaf:
                next_leaf = next_leaf.next

            yield from result

        def is_full(self):
            """Returns true if the node is full, otherwise false."""
            return len(self.keys) == self.capacity

        def is_at_least_half_full(self) -> bool:
            """See :meth:`AbstractNode.is_at_least_half_full`.

            Counts the entries: a leaf with capacity c needs at least c / 2 of them, rounded up.
            """
            # x / 2 rounded up is (x + 1) // 2, here with x = c:
            return len(self.keys) >= (self.capacity + 1) // 2

        def size(self) -> int:
            """Returns the number of keys mapped by this leaf, i.e., the number of keys in the leaf."""
            return len(self.keys)

        def dot(self, s: str) -> str:
            """Returns a string representation of the leaf node in dot format."""

            s += f"\t{self.id} [label=<\n"
            s += '\t\t<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4">\n'
            dot_keys = ""
            dot_values = ""
            for i in range(self.capacity):
                dot_keys += f'<TD BGCOLOR="lightgreen" WIDTH="20">{self.keys[i] if i < len(self.keys) else ""}</TD>'
                dot_values += f'<TD BGCOLOR="silver" WIDTH="20">{self.values[i] if i < len(self.values) else ""}</TD>'
            s += f'\t\t\t<TR>"{dot_keys}</TR>\n'
            s += f'\t\t\t<TR>"{dot_values}</TR>\n'
            s += "\t\t</TABLE>\n"
            s += "\t>, shape=plaintext, margin=0];\n"
            # draw links between leaves
            if self.next:
                s += f"\t{self.id} -> {self.next.id} [dir=both, arrowsize=0.5, constraint=false];\n"
            return s

        def consistency_check(self) -> None:
            """See :meth:`AbstractNode.consistency_check`.

            A leaf on its own is a tree of one node, its root, so Inv2 does not apply to it; its parent checks it.
            """
            assert len(self.keys) == len(
                self.values
            ), "keys and values need to have same length"
            assert (
                len(self.keys) <= self.capacity
            ), f"Inv4: the leaf {self.keys} holds {len(self.keys)} entries, more than its capacity {self.capacity}"
            assert (
                sorted(self.keys) == self.keys
            ), f"Inv4: the keys of the leaf {self.keys} are not sorted in ascending order"
            assert len(set(self.keys)) == len(
                self.keys
            ), f"Inv4: the leaf {self.keys} holds a key twice"

            # check ISAM links:
            # check pointer to left sibling:
            if self.previous:
                assert (
                    self.previous.next == self
                ), f"Inv5: the left neighbour of the leaf {self.keys} does not link back to it"
                assert (
                    type(self.previous) == BPlusTree.Leaf
                ), f"Inv5: the left neighbour of the leaf {self.keys} is not a leaf"
                assert (
                    self.previous is not self
                ), f"Inv5: the leaf {self.keys} is its own left neighbour"

            # check pointer to right sibling:
            if self.next:
                assert (
                    self.next.previous == self
                ), f"Inv5: the right neighbour of the leaf {self.keys} does not link back to it"
                assert (
                    type(self.next) == BPlusTree.Leaf
                ), f"Inv5: the right neighbour of the leaf {self.keys} is not a leaf"
                assert (
                    self.next is not self
                ), f"Inv5: the leaf {self.keys} is its own right neighbour"

    class CountingLeaf(AbstractNode):
        """A leaf node that does not store values but counts the number of put-calls."""

        def __init__(self):
            """Initializes a counting leaf with capacity 0 and a put-call counter set to zero."""
            super().__init__(0)
            self.put_calls: int = 0

        def put(self, key: Key, value: Value) -> PutInfo | None:
            """See :meth:`Index.put`.

            Does not store the value; only increments the counter of put calls.
            """
            self.put_calls += 1

        def split(self) -> SplitHappens[Key]:
            """Counting leaves are never split: always raises ``NotImplementedError``."""
            raise NotImplementedError

        def get(self, key: Key) -> Iterator[Value]:
            """See :meth:`PointQueryMixIn.get`.

            Not supported for counting leaves: always raises ``NotImplementedError``.
            """
            raise NotImplementedError

        def get_all_in_range(self, min_key: Key, max_key: Key) -> Iterator[Value]:
            """See :meth:`RangeQueryMixIn.get_all_in_range`.

            Not supported for counting leaves: always raises ``NotImplementedError``.
            """
            raise NotImplementedError

        def is_full(self) -> bool:
            """Not supported for counting leaves: always raises ``NotImplementedError``."""
            raise NotImplementedError

        def is_at_least_half_full(self) -> bool:
            """Not supported for counting leaves: always raises ``NotImplementedError``."""
            raise NotImplementedError

        def size(self) -> int:
            """See :meth:`Index.size`.

            Returns the number of put calls counted so far.
            """
            return self.put_calls

        def dot(self, s: str) -> str:
            """Returns a string representation of the leaf node in dot format."""

            s += f"\t{self.id} [label=<\n"
            s += '\t\t<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4">\n'
            dot_keys = ""
            dot_values = ""
            dot_keys += '<TD BGCOLOR="lightgreen" WIDTH="20">count</TD>'
            # TODO: overfitting the data, need max over all leaves here
            height: int = min(max(15, self.put_calls // 100), 200)
            dot_values += f'<TD BGCOLOR="silver" WIDTH="20" HEIGHT="{str(height)}">{self.put_calls}</TD>'
            s += f'\t\t\t<TR>"{dot_keys}</TR>\n'
            s += f'\t\t\t<TR>"{dot_values}</TR>\n'
            s += "\t\t</TABLE>\n"
            s += "\t>, shape=plaintext, margin=0];\n"
            return s

        def consistency_check(self) -> None:
            """Not supported for counting leaves: always raises ``NotImplementedError``."""
            raise NotImplementedError

        def show(self) -> None:
            """See :meth:`Index.show`.

            Prints the number of put calls counted so far.
            """
            print(self.put_calls)

    def __init__(self, inner_capacity: int = 3, leaf_capacity: int = 4):
        """Initializes a B+tree with a given inner node capacity and leaf node capacity.

        :param inner_capacity: The maximum number of keys that can be stored in an inner node.
        :param leaf_capacity: The maximum number of keys that can be stored in a leaf node.
        """

        self.inner_capacity: int = inner_capacity
        self.leaf_capacity: int = leaf_capacity
        self.root: BPlusTree.AbstractNode = BPlusTree.Leaf(leaf_capacity)

    def put(self, key: Key, value: Value) -> None | PutInfo:
        """See :meth:`Index.put`.

        Copies the value before storing it and, if the root node split, replaces the root with a new inner node
        holding the two halves and the separating pivot.
        """

        # copy to avoid outside modifications:
        put_info: PutInfo | None = self.root.put(key, copy.copy(value))

        # B+tree only consists of a single leaf node that gets split
        if type(put_info) == SplitHappens:
            split_happens: SplitHappens[Key] = cast(SplitHappens[Key], put_info)
            self.root = BPlusTree.Inner(
                self.inner_capacity,
                [split_happens.pivot],
                [split_happens.left_node, split_happens.right_node],
            )

    def get(self, key: Key) -> Iterator[Value]:
        """See :meth:`PointQueryMixIn.get`.

        Note: this simple B+tree does not support multiple values for the same key.
        """
        # TODO: our b-tree currently does not support multiple values for the same key
        return self.root.get(key)

    def get_all_in_range(self, min_key: Key, max_key: Key) -> Iterator[Value]:
        """See :meth:`RangeQueryMixIn.get_all_in_range`."""

        yield from self.root.get_all_in_range(min_key, max_key)

    def delete(self, key: Key, value: Value = None):
        """See :meth:`Index.delete`.

        Not implemented in this simple B+tree.
        """
        raise NotImplementedError

    def flush(self, key: Key | None = None) -> None:
        """See :meth:`Index.flush`.

        Not implemented in this simple B+tree.
        """
        raise NotImplementedError

    def bulkload(self, input_data: Iterator[tuple[Key, Value]]):
        """Bulkloads the given list of key->value mappings into the index. Not overridden in this simple B+tree."""
        super().bulkload(input_data)

    def size(self) -> int:
        """See :meth:`Index.size`."""
        return self.root.size()

    def consistency_check(self) -> None:
        """Checks that the tree is a valid B+-tree, i.e. that the five invariants of lecture 06a hold (slide "B-Tree
        Invariants and Rules").

        See :meth:`AbstractNode.consistency_check`, applied to the root. In addition: the pointers reach every node
        exactly once from the root, every node has the capacity of the tree (``inner_capacity`` or
        ``leaf_capacity``), and the chain of leaves begins at the tree's first leaf and ends at its last (Inv5): the
        first has no left neighbour, the last no right neighbour.

        Raises ``NotImplementedError`` for a tree with counting leaves (see :meth:`convert_to_counting_leaf_tree`).
        """
        assert self.root is not None, "root is None"

        # every node is reached exactly once and has the capacity of the tree; without the first, the checks below
        # could run forever, and without the second, a node of another size could seem half full:
        for node in _nodes_reached_once(self.root):
            if isinstance(node, BPlusTree.Inner):
                assert (
                    node.capacity == self.inner_capacity
                ), f"the inner node {node.keys} has capacity {node.capacity}, the tree's inner nodes {self.inner_capacity}"
            else:
                assert (
                    node.capacity == self.leaf_capacity
                ), f"the leaf {node.keys} has capacity {node.capacity}, the tree's leaves {self.leaf_capacity}"

        self.root.consistency_check()

        # the chain of leaves begins at the first leaf and ends at the last one (Inv5):
        first: BPlusTree.Leaf = _leftmost_leaf(self.root)
        last: BPlusTree.Leaf = _rightmost_leaf(self.root)
        assert (
            first.previous is None
        ), f"Inv5: the first leaf {first.keys} has a left neighbour"
        assert (
            last.next is None
        ), f"Inv5: the last leaf {last.keys} has a right neighbour"

    def show(self) -> None:
        """Displays the B+tree using graphviz."""

        s = "digraph BTree {\n\tgraph [nodesep=0.4];\n\tnode [shape=record];\n\n"
        s = self.root.dot(s)
        s += "\n}"
        display(graphviz.Source(s))

    def __str__(self):
        """Returns a short representation of the tree showing its inner and leaf node capacities."""
        s = f"BPlusTree(inner_capacity={self.inner_capacity}, leaf_capacity={self.leaf_capacity})"
        return s

    def _get_lastlevel_inner_nodes(self, node: BPlusTree.Inner) -> set[BPlusTree.Inner]:
        """Returns all inner nodes of the last level of the tree.

        :param node: an inner node of the tree
        :return: A set of inner nodes of the last level of the tree.
        """
        # last inner before leaf level?:
        if type(node.children[0]) == BPlusTree.Leaf:
            return {node}
        # more inner nodes:
        inner_nodes: set[BPlusTree.Inner] = set()
        child: BPlusTree.Inner
        for child in node.children:
            inner_nodes.update(self._get_lastlevel_inner_nodes(child))
        return inner_nodes

    def convert_to_counting_leaf_tree(self) -> None:
        """Keeps all inner nodes but replaces all leaves with CountingLeafs."""

        # get root node:
        node: BPlusTree[Key, Value].AbstractNode = self.root

        inner_nodes = None
        # get all inner nodes before the leaf level:
        if type(self.root) == BPlusTree.Inner:
            inner_nodes = self._get_lastlevel_inner_nodes(cast(BPlusTree.Inner, node))
        else:
            raise ValueError("root is not an inner node")
        for inner_node in inner_nodes:
            # convert children to CountingLeafs:
            for i, _ in enumerate(inner_node.children):
                inner_node.children[i] = BPlusTree.CountingLeaf()
