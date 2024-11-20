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
    pass


@dataclass
class SplitHappens[Key](PutInfo):
    left_node: BPlusTree.AbstractNode
    right_node: BPlusTree.AbstractNode
    pivot: Key


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
        _ids: int = count(0)

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
            :return: A SplitInfo instance.
            """

            pass

        @abstractmethod
        def split(
            self,
        ) -> SplitHappens[Key]:
            """Split-operation for nodes. Splits the keys and values of this node into two nodes.

            :return: A SplitHappens instance wrapping the left node, the right node, and the new pivot if a split occurred
            """
            pass

        @abstractmethod
        def get(self, key: Key) -> Iterator[Value]:
            """Returns the value for the given key if it exists.
            :param key: The key to search for.
            """
            pass

        @abstractmethod
        def get_all_in_range(self, min_key: Key, max_key: Key) -> Iterator[Value]:
            """Returns a list of values for all keys in the given range.
            :param min_key: The minimum key to search for.
            :param max_key: The maximum key to search for.
            """
            pass

        @abstractmethod
        def is_full(self) -> bool:
            """Returns true if the node is full, otherwise false."""
            pass

        @abstractmethod
        def size(self) -> int:
            """Returns the number of keys in the subtree."""
            pass

        @abstractmethod
        def dot(self, s: str) -> str:
            """Returns a string representation of the node in dot format."""
            pass

        @abstractmethod
        def consistency_check(self) -> None:
            """Check if the node is consistent, i.e., all keys are sorted and the number of children is correct."""
            pass

        def delete(self, key: Key, value: Value = None) -> None:
            """Deletes the key->value mapping from the index.

            @param key: the key
            @param value: the value to delete

            """
            raise NotImplemented

        def flush(self, key: Key | None = None) -> None:
            """Persists all changes, i.e. any changes done so far in volatile memory only are now made durable.

            @param key: if given, only the key/value pair is flushed, otherwise all key/value-mappings are
            flushed.
            """
            raise NotImplemented

        @abstractmethod
        def show(self) -> None:
            """Shows the content of the index."""

            pass

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
            """Split-operation for inner nodes. Splits the keys and children of this node into two inner nodes plus
            pivot.
            Note: No re-use of this instance, we are creating two new Inner-instances.

            :return: A SplitHappens wrapping the left node, the right node, and the new pivot.
            """

            # find middle (aka pivot) element:
            mid = len(self.keys) // 2

            # create new inner nodes:
            left_node = BPlusTree.Inner(
                self.capacity, self.keys[:mid], self.children[: mid + 1]
            )
            right_node = BPlusTree.Inner(
                self.capacity, self.keys[mid + 1 :], self.children[mid + 1 :]
            )

            return SplitHappens[Key](
                left_node=left_node, right_node=right_node, pivot=self.keys[mid]
            )

        def put(self, key: Key, value: Value) -> PutInfo:
            """Insert the given `key` and `value` into the inner node.

            :param key: The key to insert.
            :param value: The value to insert.
            :return: A SplitInfo instance.
            """

            # perform binary search to find the position to insert the key:
            pos: int = bisect.bisect(self.keys, key)
            sr: PutInfo[Key] = self.children[pos].put(key, value)

            if (
                type(sr) == SplitHappens
            ):  # a split happened in the layer immediately below this node
                sr: SplitHappens[Key] = cast(SplitHappens[Key], sr)
                # check if this node is full:
                if self.is_full():
                    pivot_pos = bisect.bisect_left(self.keys, sr.pivot)
                    del self.children[
                        pivot_pos
                    ]  # remove old child and replace with the two new children (obtained through split in layer below)
                    # insert the two new children at the correct position:
                    self.children.insert(pivot_pos, sr.left_node)
                    self.children.insert(pivot_pos + 1, sr.right_node)
                    self.keys.insert(
                        pivot_pos, sr.pivot
                    )  # now `self.keys` contains one element too many

                    # split this node:
                    return self.split()

                # post condition: this node is not full and has room to insert the new pivot returned from the split
                del self.children[
                    pos
                ]  # remove old child and replace with the two new children (obtained through split in layer below)
                self.children.insert(pos, sr.left_node)
                self.children.insert(pos + 1, sr.right_node)
                self.keys.insert(pos, sr.pivot)

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

        def size(self) -> int:
            """Returns the number of keys mapped by this subtree.

            :return: The sum of the number of keys of this subtree.
            """

            return sum([child.size() for child in self.children])

        def dot(self, s: str) -> str:
            """Returns a string representation of the inner node in dot format."""

            s += f"\t{self.id} [label=<\n"
            s += f'\t\t<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4">\n'
            s += f"\t\t\t<TR>"
            for i in range(self.capacity):
                s += f'<TD BGCOLOR="royalblue" PORT="p{i}"></TD>'
                s += f'<TD BGCOLOR="khaki1" WIDTH="20">{self.keys[i] if i < len(self.keys) else ""}</TD>'

            s += f'<TD BGCOLOR="royalblue" PORT="p{len(self.keys)}"></TD>'
            s += f"</TR>\n"
            s += f"\t\t</TABLE>\n"
            s += f"\t>, shape=plaintext];\n"
            # draw edges
            for i, child in enumerate(self.children):
                s += f"\t{self.id}:p{i} -> {child.id};\n"
            # recursively dot children
            for child in self.children:
                s = child.dot(s)
            return s

        def consistency_check(self) -> None:
            """Check if this node is consistent, i.e., all keys are sorted and the number of children is correct,
            etc."""
            assert len(self.keys) + 1 == len(
                self.children
            ), "an inner node has to contain one more child than keys"

            assert sorted(self.keys) == self.keys, "keys need to be sorted"

            assert len({child for child in self.children}) == len(
                self.children
            ), "no duplicate children"

            # recurse consistency check:
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

            self.keys: Optional[list[Key]] = (
                keys if keys is not None else []
            )  # use `None` as default to avoid shared mutable default arguments

            self.values: Optional[list[Value]] = (
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
            """Split-operation for leaf nodes. Splits the keys and values of this Leaf into two Leaves.
            Note: No re-use of this instance, we are creating two new Leaf instances.

            :return: A SplitHappens wrapping the left leaf, the right leaf, and the new pivot.
            """

            # find middle (aka pivot) element:
            mid: int = len(self.keys) // 2

            # return two new Leaf instances and the pivot key:
            return SplitHappens[Key](
                left_node=BPlusTree.Leaf(
                    self.capacity, self.keys[:mid], self.values[:mid]
                ),
                right_node=BPlusTree.Leaf(
                    self.capacity, self.keys[mid:], self.values[mid:]
                ),
                pivot=self.keys[mid],
            )

        def put(self, key: Key, value: int) -> PutInfo:
            """Insert the given `key` and `value` into the leaf.

            :param key: The key to insert.
            :param value: The value to insert.
            :return: A SplitInfo instance.
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
                self.keys.insert(pos, key)
                self.values.insert(pos, value)

                return NoSplit()
            else:
                # maximum capacity reached (before inserting!): split the leaf
                # variant implemented: first insert allowing for overflow, then split
                # (1.) insert key-value pair at correct position:
                self.keys.insert(pos, key)
                self.values.insert(pos, value)

                # (2.) split the leaf:
                # call split to create two new leaf nodes:
                sr: SplitHappens[Key] = self.split()

                # (3.) redirect leaf pointers for sequential scanning
                # is there a leaf to the left of self?: update its next pointer
                if self.previous:
                    self.previous.next = sr.left_node

                # new left node points to the previous leaf:
                sr.left_node.previous = self.previous
                # new left node points to the right node (just created by the split):
                sr.left_node.next = sr.right_node

                # new right node points to the new left node (just created by the split):
                sr.right_node.previous = sr.left_node
                # new right node points to the next leaf:
                sr.right_node.next = self.next

                if self.next:
                    self.next.previous = sr.right_node

                # return the split information up the call stack:
                return sr

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

            for res in result:
                yield res

        def is_full(self):
            """Returns true if the node is full, otherwise false."""
            return len(self.keys) == self.capacity

        def size(self) -> int:
            """Returns the number of keys mapped by this leaf, i.e., the number of keys in the leaf."""
            return len(self.keys)

        def dot(self, s: str) -> str:
            """Returns a string representation of the leaf node in dot format."""

            s += f"\t{self.id} [label=<\n"
            s += f'\t\t<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="4">\n'
            dot_keys = ""
            dot_values = ""
            for i in range(self.capacity):
                dot_keys += f'<TD BGCOLOR="lightgreen" WIDTH="20">{self.keys[i] if i < len(self.keys) else ""}</TD>'
                dot_values += f'<TD BGCOLOR="silver" WIDTH="20">{self.values[i] if i < len(self.values) else ""}</TD>'
            s += f'\t\t\t<TR>"{dot_keys}</TR>\n'
            s += f'\t\t\t<TR>"{dot_values}</TR>\n'
            s += f"\t\t</TABLE>\n"
            s += f"\t>, shape=plaintext, margin=0];\n"
            # draw links between leaves
            if self.next:
                s += f"\t{self.id} -> {self.next.id} [dir=both, arrowsize=0.5, constraint=false];\n"
            return s

        def consistency_check(self) -> None:
            """Check if this node is consistent, i.e., all keys are sorted and the number of children is correct,
            etc."""
            assert len(self.keys) == len(
                self.values
            ), "keys and values need to have same length"
            assert (
                len(self.keys) <= self.capacity
            ), "number of leaf entries exceeds max capacity"
            assert sorted(self.keys) == self.keys, "keys need to be sorted"
            assert len({k for k in self.keys}) == len(self.keys), "no duplicate keys"

            # check ISAM links:
            # check pointer to left sibling:
            if self.previous:
                assert (
                    self.previous.next == self
                ), "previous.next link not pointing to self"
                assert (
                    type(self.previous) == BPlusTree.Leaf
                ), "previous link is not a leaf"
                assert self.previous is not self, "previous link is pointing to self"

            # check pointer to right sibling:
            if self.next:
                assert (
                    self.next.previous == self
                ), "next.previous link is not pointing to self"
                assert type(self.next) == BPlusTree.Leaf, "previous link is not a leaf"
                assert self.next is not self, "next link is pointing to self"

    def __init__(self, inner_capacity: int = 3, leaf_capacity: int = 4):
        """Initializes a B+tree with a given inner node capacity and leaf node capacity.

        :param inner_capacity: The maximum number of keys that can be stored in an inner node.
        :param leaf_capacity: The maximum number of keys that can be stored in a leaf node.
        """

        self.inner_capacity: int = inner_capacity
        self.leaf_capacity: int = leaf_capacity
        self.root: BPlusTree.AbstractNode = BPlusTree.Leaf(leaf_capacity)

    def put(self, key: Key, value: Value) -> None | PutInfo:
        """Adds (puts) a new key->value mapping into the store.
        :param key: the key
        :param value: the value to associate with the key
        """

        # copy to avoid outside modifications:
        sr: PutInfo[Key] = self.root.put(key, copy.copy(value))

        # B+tree only consists of a single leaf node that gets split
        if type(sr) == SplitHappens:
            sr: SplitHappens[Key] = cast(SplitHappens[Key], sr)
            self.root = BPlusTree.Inner(
                self.inner_capacity, [sr.pivot], [sr.left_node, sr.right_node]
            )
        return None

    def get(self, key: Key) -> Iterator[Value]:
        """Returns the value for the given key if it exists.
        :param key: the key
        """
        # TODO: our b-tree currently does not support multiple values for the same key
        return self.root.get(key)

    def get_all_in_range(self, min_key: Key, max_key: Key) -> Iterator[Value]:
        """Returns a list of values for all keys in the given range.
        :param min_key: the minimum key to search for
        :param max_key: the maximum key to search for
        """

        for value in self.root.get_all_in_range(min_key, max_key):
            yield value

    def delete(self, key: Key, value: Value = None):
        """Deletes the key->value mapping from the index. Not implemented in this simple B+tree."""
        raise NotImplemented

    def flush(self, key: Key | None = None) -> None:
        """Persists all changes, i.e. any changes done so far in volatile memory only are now made durable. Not
        implemented in this simple B+tree."""
        raise NotImplemented

    def bulkload(self, input_data: Iterator[tuple[Key, Value]]):
        """Bulkloads the given list of key->value mappings into the index. Not overridden in this simple B+tree."""
        super().bulkload(input_data)

    def size(self) -> int:
        """Returns the number of keys mapped by this index."""
        return self.root.size()

    def consistency_check(self) -> None:
        """Check if the B+tree is consistent, i.e., all keys are sorted and the number of children is correct."""
        self.root.consistency_check()

        assert self.root is not None, "root is None"

    def show(self) -> None:
        """Displays the B+tree using graphviz."""

        s = "digraph BTree {\n\tgraph [nodesep=0.4];\n\tnode [shape=record];\n\n"
        s = self.root.dot(s)
        s += "\n}"
        display(graphviz.Source(s))

    def __str__(self):
        s = f"BPlusTree(inner_capacity={self.inner_capacity}, leaf_capacity={self.leaf_capacity})"
        return s
