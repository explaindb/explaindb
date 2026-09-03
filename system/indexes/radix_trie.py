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

"""Radix trie (compressed prefix tree) index implementation with pluggable key mapping."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterator

from ipycanvas import Canvas

from system.interfaces.indexing.Index import KeyValueStore, PutInfo
from system.utils import Descriptor, Drawable


class KeyMapping[Key, Value](ABC):
    """Maps a key to a value"""

    @abstractmethod
    def map(self, key: Key, level: int, descriptor: Descriptor = None) -> int:
        """Maps the given key to a bucket at the given level.

        @param key: The key to map.
        @param level: The level of the mapping.
        @param descriptor: The optional descriptor to use for the mapping.

        @return: The bucket index from 0 to max_buckets of an inner_node - 1.
        """


class RadixTrie[Key, Value](KeyValueStore[Key, Value], Drawable):
    """A simple implementation of a radix trie data structure."""

    class AbstractNode(KeyValueStore[Key, Value], Drawable, ABC):
        """Abstract node of a radix trie. A node is itself a valid key-value store: it is either an inner node
        that routes keys to children by radix, or a leaf node that stores the key-value pairs.
        """

        def __init__(self):
            """Create a new abstract node. Sets a node counter to 0"""
            self.count: int = 0

        def get(self, key: Key, level: int = 0) -> Iterator[Value]:
            """See :meth:`PointQueryMixIn.get`.

            The extra ``level`` parameter is the current depth of this node in the trie. Overridden by
            concrete node types.
            """

        def put(self, key: Key, value: Value, level: int = 0) -> None | PutInfo:
            """See :meth:`Index.put`.

            The extra ``level`` parameter is the current depth of this node in the trie. Overridden by
            concrete node types.
            """

        def size(self) -> int:
            """See :meth:`Index.size`."""
            return self.count

        def flush(self, key: Key | None = None) -> None:
            """See :meth:`Index.flush`.

            Not supported for trie nodes: always raises ``NotImplementedError``.
            """
            raise NotImplementedError

        def delete(self, key: Key, value: Value = None) -> None:
            """See :meth:`Index.delete`.

            Not supported for trie nodes: always raises ``NotImplementedError``.
            """
            raise NotImplementedError

        def show(self, indent: str = "") -> None:
            """See :meth:`Index.show`.

            The ``indent`` parameter is a prefix prepended to every printed line for nesting. Overridden by
            concrete node types.
            """

        def draw(
            self,
            canvas: Canvas,
            canvas_height: int = 0,
            x_offset: int = 0,
            y_offset: int = 0,
        ):
            """Draw this instance on the given canvas."""

    class InnerNode[Key, Value](AbstractNode[Key, Value]):
        """Inner node of a radix trie. Holds a list of children and routes each key to the matching child by
        computing its radix (either via the key mapping or via the child descriptors).
        """

        def __init__(
            self,
            key_mapping: KeyMapping[Key, Value] = None,
            parent_descriptor: Descriptor = None,  # not needed for the index but for the viz
        ):
            """Creates a new inner node.

            @param key_mapping: the mapping used to compute the child (radix) for a key; if omitted, children
            descriptors are used to locate the matching child instead.
            @param parent_descriptor: the descriptor of the region covered by this node; used only for the
            visualization and, when given, split into per-child descriptors.
            """
            super().__init__()
            # derive the child descriptors:
            self.children_descriptors: list[Descriptor] | None = None
            if parent_descriptor is not None:
                self.children_descriptors = list(
                    parent_descriptor.split_into_sub_descriptors()
                )
            self.parent_descriptor = parent_descriptor

            self.key_mapping: KeyMapping[Key, Value] = key_mapping
            self.children: list[RadixTrie.AbstractNode] = list[RadixTrie.AbstractNode]()

        def show(self, indent: str = "") -> None:
            """See :meth:`Index.show`.

            Prints this inner node and recurses into every child, indenting each level further.
            """
            print(indent + "InnerNode {")
            child: RadixTrie.AbstractNode
            for index, child in enumerate(self.children):
                if self.children_descriptors is not None:
                    print(indent + "\tdescriptor: ", self.children_descriptors[index])
                # print(indent + "\t", index, ":")
                child.show(indent=indent + "\t")
            print(indent + "}")

        def draw(
            self,
            canvas: Canvas,
            canvas_height: int = 0,
            x_offset: int = 0,
            y_offset: int = 0,
        ):
            """Draw this instance on the given canvas."""
            if self.children_descriptors is not None:
                for index, child in enumerate(self.children):
                    self.children_descriptors[index].draw(
                        canvas,
                        canvas_height=canvas_height,
                        x_offset=x_offset,
                        y_offset=y_offset,
                    )
            child: RadixTrie.AbstractNode
            for child in self.children:
                child.draw(
                    canvas,
                    canvas_height=canvas_height,
                    x_offset=x_offset,
                    y_offset=y_offset,
                )

        def _get_radix(self, key: Key, level: int = 0) -> int:
            """Get the radix for the given key at the given level."""
            radix: int | None = None
            if self.key_mapping:
                # descriptor-free search:
                radix = self.key_mapping.map(key, level)
            else:
                # use descriptors to find the correct child:
                # loop over all children descriptors:
                for i in range(len(self.children_descriptors)):
                    # check for containment
                    if self.children_descriptors[i].contains(key):
                        # first match wins:
                        radix: int = i
                        break

                if radix is None:
                    raise ValueError(f"Key {key} not contained in any child descriptor")

            return radix

        def get(self, key: Key, level: int = 0) -> Iterator[Value]:
            """See :meth:`PointQueryMixIn.get`.

            Computes the radix for the key at this level and delegates the lookup to the matching child at the
            next level.
            """
            radix: int = self._get_radix(key, level)
            return self.children[radix].get(key, level + 1)

        def put(self, key: Key, value: Value, level: int = 0) -> None | PutInfo:
            """See :meth:`Index.put`.

            Computes the radix for the key at this level and delegates the insertion to the matching child at
            the next level.
            """
            radix: int = self._get_radix(key, level)
            return self.children[radix].put(key, value, level + 1)

    class LeafNode[Key, Value](AbstractNode[Key, Value]):
        """Leaf node of a radix trie. Stores the key-value pairs and is chained to its left sibling so that all
        leaves form a sequence for ISAM-style scanning.
        """

        def __init__(
            self,
            parent_descriptor: Descriptor = None,
            left_sibling: RadixTrie.LeafNode[Key, Value] | None = None,
        ):
            """Create a new leaf node.
            @param parent_descriptor: The parent descriptor. THis is technically not needed but required for the
            visualization.
            @param left_sibling: The left sibling of this leaf node. This allows us to put all leaves in a chain for
            ISAM.

            """
            super().__init__()
            self.parent_descriptor = parent_descriptor
            self.values: list[tuple[Key, Value]] = list[tuple[Key, Value]]()
            self.left_sibling: RadixTrie.LeafNode[Key, Value] | None = left_sibling

        def show(self, indent: str = "") -> None:
            """See :meth:`Index.show`.

            Prints the key/value pairs stored in this leaf.
            """
            print(indent + "LeafNode {")
            print(indent + f"  values: {self.values}")
            print(indent + "},")

        def draw(
            self,
            canvas: Canvas,
            canvas_height: int = 0,
            x_offset: int = 0,
            y_offset: int = 0,
        ):
            """Draw this instance on the given canvas. This only works if the key is of type Drawable."""
            key: Drawable

            for key, _ in self.values:
                key.draw(canvas, canvas_height, x_offset, y_offset)

            if self.left_sibling is not None:
                # draw ISAM line, this corresponds to space filling curve over the sub-descriptors!:
                x_from: int = x_offset + self.left_sibling.parent_descriptor.center().x
                y_from: int = canvas_height - (
                    y_offset + self.left_sibling.parent_descriptor.center().y
                )
                x_to: int = x_offset + self.parent_descriptor.center().x
                y_to: int = canvas_height - (
                    y_offset + self.parent_descriptor.center().y
                )
                # yellow golden line:
                canvas.stroke_style = "#FFD700"
                canvas.line_width = 5
                canvas.begin_path()
                canvas.move_to(x_from, y_from)
                canvas.line_to(x_to, y_to)
                canvas.stroke()

        def put(self, key: Key, value: Value, level: int = 0) -> None | PutInfo:
            """See :meth:`Index.put`.

            Appends the (key, value) pair to this leaf and increments its element count; duplicates are kept.
            """
            self.count += 1
            self.values.append((key, value))

        def get(self, key: Key, level: int = 0) -> Iterator[Value]:
            """See :meth:`PointQueryMixIn.get`.

            Scans this leaf and yields the value of every stored pair whose key equals the search key.
            """
            for k, v in self.values:
                if k == key:
                    yield v

    class InnerNodeFactory[Key, Value]:
        """A factory that creates new RadixTrie.InnerNode instances."""

        def new_instance(
            self,
            key_mapping: KeyMapping[Key, Value] = None,
            new_descriptor: Descriptor = None,
        ) -> RadixTrie.InnerNode[Key, Value]:
            """Creates and returns a new :class:`RadixTrie.InnerNode`.

            @param key_mapping: the key mapping to pass to the new inner node.
            @param new_descriptor: the descriptor of the region covered by the new inner node.
            @return: the newly created inner node.
            """
            return RadixTrie.InnerNode[Key, Value](key_mapping, new_descriptor)

    class LeafFactory[Key, Value]():
        """A factory that creates new RadixTrie.LeafNode instances."""

        def new_instance(
            self, parent_descriptor, previous_leaf
        ) -> RadixTrie.LeafNode[Key, Value]:
            """Creates and returns a new :class:`RadixTrie.LeafNode`.

            @param parent_descriptor: the descriptor of the region covered by the new leaf.
            @param previous_leaf: the leaf to the left of the new leaf, used to chain leaves for ISAM.
            @return: the newly created leaf node.
            """
            return RadixTrie.LeafNode[Key, Value](parent_descriptor, previous_leaf)

    def __init__(
        self,
        key_mapping: KeyMapping[Key, Value],
        children_per_inner_node: int,
        inner_node_factory: RadixTrie.InnerNodeFactory[Key, Value] = InnerNodeFactory[
            Key, Value
        ](),
        leaf_factory: RadixTrie.LeafFactory[Key, Value] = LeafFactory[Key, Value](),
        descriptor: Descriptor = None,
        number_of_inner_node_levels: int = 0,
    ):
        """Creates a radix trie and eagerly builds its fixed node structure.

        @param key_mapping: the mapping used by inner nodes to compute the child (radix) for a key.
        @param children_per_inner_node: the fan-out, i.e. the number of children of each inner node.
        @param inner_node_factory: the factory used to create inner nodes.
        @param leaf_factory: the factory used to create leaf nodes.
        @param descriptor: the descriptor of the whole region covered by the trie; used for the visualization.
        @param number_of_inner_node_levels: the number of inner-node levels; 0 means the trie is a single leaf.
        """
        super().__init__()
        self.key_mapping: KeyMapping[Key, Value] = key_mapping
        self.children_per_inner_node: int = children_per_inner_node
        self.inner_node_factory: RadixTrie.InnerNodeFactory[Key, Value] = (
            inner_node_factory
        )
        self.leaf_factory: RadixTrie.LeafFactory[Key, Value] = leaf_factory
        self.descriptor: Descriptor = descriptor
        self.number_of_inner_node_levels: int = number_of_inner_node_levels

        # element count for the entire trie:
        self.count: int = 0

        # root node:
        self.root: RadixTrie.AbstractNode[Key, Value] | None = None

        self.node_count: int = self._build_trie()

    def number_of_nodes(self) -> int:
        """Returns the total number of nodes (inner nodes and leaves) in the trie.

        @return: the number of nodes in the trie.
        """
        return self.node_count

    def _build_trie(self) -> int:
        """Builds the trie based on self.number_of_inner_node_levels and the node and leaf factories given.
        @return: The number of nodes in this trie."""

        node_count: int = 0

        if self.number_of_inner_node_levels == 0:
            # no inner nodes, simply create a leaf node and return:
            self.root: RadixTrie.AbstractNode[Key, Value] = (
                self.leaf_factory.new_instance(
                    parent_descriptor=self.descriptor, previous_leaf=None
                )
            )
            node_count = 1
            return node_count

        # post condition: at least one inner node level:

        # dictionary to store nodes to process at each level:
        # helper structure to break up the recursion into a level-wise construction of the trie:
        nodes_to_process: dict[int, list[RadixTrie.AbstractNode[Key, Value]]] = dict[
            int, list[RadixTrie.AbstractNode[Key, Value]]
        ]()

        # get the root node:
        self.root: RadixTrie.AbstractNode[Key, Value] = (
            self.inner_node_factory.new_instance(
                key_mapping=self.key_mapping, new_descriptor=self.descriptor
            )
        )
        node_count += 1

        # add the root node to the list of nodes to process at level 0:
        nodes_to_process[0] = list[RadixTrie.AbstractNode[Key, Value]]([self.root])

        # level-wise construction (expansion) of the trie:
        for trie_level in range(1, self.number_of_inner_node_levels):
            node: RadixTrie.InnerNode[Key, Value]
            nodes_to_process[trie_level] = list[RadixTrie.InnerNode[Key, Value]]()

            # get all nodes from the previous trie_level:
            for node in nodes_to_process[trie_level - 1]:
                # for each of those nodes, create children inner nodes:
                for i in range(self.children_per_inner_node):
                    # create instance:
                    new_inner_node: RadixTrie.InnerNode[Key, Value] = (
                        self.inner_node_factory.new_instance(
                            self.key_mapping,
                            (
                                node.children_descriptors[i]
                                if node.children_descriptors is not None
                                else None
                            ),
                        )
                    )
                    node_count += 1
                    # append to children list of node:
                    node.children.append(new_inner_node)
                    # add to the list of nodes to process at the next level:
                    nodes_to_process[trie_level].append(new_inner_node)

            # remove all nodes from the previous level from the dictionary as these were processed:
            del nodes_to_process[trie_level - 1]

        assert len(nodes_to_process) == 1, "nodes from multiple levels in dictionary"

        # maximum key in the dictionary should be the number of inner node levels - 1
        # This is because the last level is for leaf nodes.
        max_level: int = max(nodes_to_process.keys())
        assert max_level == self.number_of_inner_node_levels - 1

        # get the inner nodes from the last level of the trie:
        previous_leaf = None
        for node in nodes_to_process[max_level]:
            assert isinstance(node, RadixTrie.InnerNode), "not an inner node"

            # create leaf nodes as children of the inner node:
            for i in range(self.children_per_inner_node):
                new_leaf = self.leaf_factory.new_instance(
                    node.parent_descriptor, previous_leaf
                )
                node.children.append(new_leaf)
                node_count += 1
                previous_leaf = new_leaf

        return node_count

    def get(self, key: Key) -> Iterator[Value]:
        """See :meth:`PointQueryMixIn.get`."""
        return self.root.get(key, 0)

    def put(self, key: Key, value: Value) -> None | PutInfo:
        """See :meth:`Index.put`."""
        self.count += 1
        self.root.put(key, value, 0)

    def size(self) -> int:
        """See :meth:`Index.size`."""
        return self.count

    def delete(self, key: Key, value: Value = None) -> None:
        """See :meth:`Index.delete`.

        Not implemented yet: always raises ``NotImplementedError``.
        """
        self.count -= 1
        # TODO: implement delete
        raise NotImplementedError

    def flush(self, key: Key | None = None) -> None:
        """See :meth:`Index.flush`.

        Not supported: always raises ``NotImplementedError``.
        """
        raise NotImplementedError

    def show(self) -> None:
        """See :meth:`Index.show`."""
        print("RadixTrie:")
        self.root.show(indent="\t")

    def draw(
        self,
        canvas: Canvas,
        canvas_height: int = 0,
        x_offset: int = 0,
        y_offset: int = 0,
    ):
        """Draw the radix trie on the given canvas."""
        self.descriptor.draw(canvas, canvas_height, x_offset, y_offset)
        self.root.draw(canvas, canvas_height, x_offset, y_offset)
        # display(canvas)
