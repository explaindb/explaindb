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

"""Christmas tree index: a radix trie augmented with buffer-tree-style node buffers."""

from __future__ import annotations

from itertools import chain
from math import pi
from typing import Iterator, Protocol, cast

from ipycanvas import Canvas

from system.indexes.radix_trie import RadixTrie, KeyMapping
from system.interfaces.indexing.Index import PutInfo
from system.indexes.utils import Descriptor, Vector


class _BloomFilterKey(Protocol):
    """A key that a :class:`ChristmasTree.CrystalBallBufferedInnerNode` can enter into its bloom filter: it has a
    ``my_hash`` method, as :class:`Vector` has. The node calls it on every key it gets; the type checker cannot see
    this from the unbounded Key, hence the casts there."""

    def my_hash(self) -> int:
        """Returns a hash value of the key."""
        ...


class ChristmasTree[Key, Value](RadixTrie[Key, Value]):
    """A simple implementation of a Christmas tree data structure."""

    # unlike the nodes in radix_trie.py, the buffered nodes have no type parameters of their own but use the tree's
    # Key and Value, as no code makes one with type arguments (such as BufferedInnerNode[Vector, str]()):
    class BufferedInnerNode(RadixTrie.InnerNode[Key, Value]):
        """A simple implementation of an inner node in a Christmas tree adding buffer tree-style buffers."""

        def __init__(
            self,
            key_mapping: KeyMapping[Key, Value] | None = None,
            parent_descriptor: Descriptor | None = None,
            max_buffer_size: int = 30,
        ):
            """Create a new buffered inner node with the given key mapping and parent descriptor.
            @param key_mapping: The key mapping for this node.
            @param parent_descriptor: The parent descriptor for this node.
            @param max_buffer_size: The maximum number of key-value pairs that can be buffered in this node.
            """
            super().__init__(key_mapping, parent_descriptor)
            self.buffer: list[tuple[Key, Value]] = list[tuple[Key, Value]]()
            self.max_buffer_size: int = max_buffer_size

        def _flush_buffer(self, level: int = 0) -> None:
            """Flush the buffer to the children."""
            # buffer is full, push down all the buffered pairs to the children:
            for k, v in self.buffer:
                radix: int = self._get_radix(k, level)
                self.children[radix].put(k, v, level + 1)

            # empty the buffer:
            self.buffer.clear()

        def flush_all_buffers(self, level: int = 0) -> None:
            """Flush all buffers in this node and its children.
            @param level: The depth of this node in the trie (0 for the root); the key mapping routes the buffered
            keys by it (ignored when the node finds the child of a key by its child descriptors).
            """
            # flush this node's buffer at its own depth, then the buffered children one level deeper:
            self._flush_buffer(level)
            for c in self.children:
                if isinstance(
                    c, ChristmasTree.BufferedInnerNode
                ):  # TODO: refactor to get rid of type check, shown here for educational purposed how not do do this ;-)
                    c.flush_all_buffers(level + 1)

        def put(self, key: Key, value: Value, level: int = 0) -> None | PutInfo:
            """See :meth:`Index.put`.

            Buffer-tree variant: appends the pair to this node's in-memory buffer instead of pushing it down
            immediately; when the buffer is full it is first flushed to the children. The extra ``level``
            parameter is the current depth of this node in the trie.
            """
            if len(self.buffer) >= self.max_buffer_size:
                # buffer is full, then flush it:
                self._flush_buffer(level)

            # append to internal buffer:
            self.buffer.append((key, value))

        def get(self, key: Key, level: int = 0) -> Iterator[Value]:
            """See :meth:`PointQueryMixIn.get`.

            Buffer-tree variant: yields matching values from this node's buffer first and then chains in the
            values returned by the children, so pairs still sitting in the buffer are not missed. The extra
            ``level`` parameter is the current depth of this node in the trie.
            """
            # filter the buffer for the given search key:
            buffer_it: Iterator[tuple[Key, Value]] = filter(
                lambda t: t[0] == key, self.buffer
            )

            # map the results to their values:
            buffer_it_mapped_to_val: Iterator[Value] = map(lambda t: t[1], buffer_it)

            # in addition:
            # delegate get() to the child iterator (which one is done in super()):
            child_it: Iterator[Value] = super().get(key, level)

            # return the union of the buffer and the child iterator:
            return chain(buffer_it_mapped_to_val, child_it)

        def draw(
            self,
            canvas: Canvas,
            canvas_height: int = 0,
            x_offset: int = 0,
            y_offset: int = 0,
        ):
            """See :meth:`Drawable.draw`.

            In addition to the inner node drawn by the superclass, draws a red candle whose height is
            proportional to the current fill level of this node's buffer.
            """
            super().draw(canvas, canvas_height, x_offset, y_offset)
            # draw the buffer:
            canvas.fill_style = "#ff0000"
            canvas.line_width = 1
            # get the center of the descriptor; only a node with a descriptor can be drawn:
            assert (
                self.parent_descriptor is not None
            ), "only a node with a descriptor can be drawn"
            center: Vector = self.parent_descriptor.center()
            width: int = 8
            height: int = int(40 * (len(self.buffer) / self.max_buffer_size))
            # draw a rectangle/candle to symbolize the buffer:
            canvas.fill_rect(
                x_offset + center.x - width / 2,
                canvas_height - (y_offset + center.y + height / 2),
                width,
                height,
            )

        def show(self, indent: str = "") -> None:
            """See :meth:`Index.show`.

            In addition to the inner node printed by the superclass, prints the key-value pairs currently held
            in this node's buffer. The ``indent`` parameter is a prefix prepended to every printed line.
            """
            super().show(indent)
            print(indent + "Buffer:")
            for k, v in self.buffer:
                print(indent + f"  {k} -> {v}")

    class CrystalBallBufferedInnerNode(BufferedInnerNode):
        """Add a crystal ball to the buffered inner node."""

        def __init__(
            self,
            key_mapping: KeyMapping[Key, Value] | None = None,
            parent_descriptor: Descriptor | None = None,
            max_buffer_size: int = 30,
        ):
            """See :meth:`ChristmasTree.BufferedInnerNode.__init__`.

            Additionally allocates a small fixed-size "poor man's" bloom filter used to skip lookups for keys
            that were provably never inserted into this node.
            """
            super().__init__(key_mapping, parent_descriptor, max_buffer_size)
            # poor man's bloom- filter:
            # TODO: replace with full-blown implementation
            self.poor_mans_bloom_filter_size: int = 142
            self.poor_mans_bloom_filter: list[bool] = [
                False for _ in range(self.poor_mans_bloom_filter_size)
            ]

        def get(self, key: Key, level: int = 0) -> Iterator[Value]:
            """See :meth:`ChristmasTree.BufferedInnerNode.get`.

            Consults the bloom filter first: if the key's bit is not set the key cannot be present, so an empty
            iterator is returned without descending; otherwise the buffered-node lookup is delegated to.
            """
            # the bloom filter hashes the key with my_hash (see _BloomFilterKey):
            if self.poor_mans_bloom_filter[
                cast(_BloomFilterKey, key).my_hash() % self.poor_mans_bloom_filter_size
            ]:
                return super().get(key, level)
            return iter([])

        def put(self, key: Key, value: Value, level: int = 0) -> None | PutInfo:
            """See :meth:`ChristmasTree.BufferedInnerNode.put`.

            Additionally records the key in the bloom filter before delegating the insertion to the buffered
            node.
            """
            # the bloom filter hashes the key with my_hash (see _BloomFilterKey):
            self.poor_mans_bloom_filter[
                cast(_BloomFilterKey, key).my_hash() % self.poor_mans_bloom_filter_size
            ] = True
            return super().put(key, value, level)

        def show(self, indent: str = "") -> None:
            """See :meth:`ChristmasTree.BufferedInnerNode.show`.

            Additionally prints the contents of this node's bloom filter.
            """
            super().show(indent)
            print(indent + "Poor man's bloom filter:")
            print(indent + "  " + str(self.poor_mans_bloom_filter))

        def draw(
            self,
            canvas: Canvas,
            canvas_height: int = 0,
            x_offset: int = 0,
            y_offset: int = 0,
        ):
            """See :meth:`ChristmasTree.BufferedInnerNode.draw`.

            In addition to the buffered node drawn by the superclass, draws a "crystal ball" (a gradient-filled
            circle) whose opacity reflects how empty the bloom filter still is: the fuller the filter, the less
            useful it is and the fainter the ball.
            """
            super().draw(
                canvas,
                canvas_height,
                x_offset,
                y_offset,
            )
            radius: int = 25
            # get a consistent pseudo-random x_shift for the crystal ball:
            x_shift: int = -25 if self.__hash__() % 2 == 0 else 25
            # place the ball next to the center of the descriptor; only a node with a descriptor can be drawn:
            assert (
                self.parent_descriptor is not None
            ), "only a node with a descriptor can be drawn"
            x: int = x_shift + x_offset + self.parent_descriptor.center().x
            y: int = canvas_height - (y_offset + self.parent_descriptor.center().y)
            gradient = canvas.create_linear_gradient(
                x - radius / 2,
                y - radius / 2,  # Start position (x0, y0)
                x + radius / 2,
                y + radius / 2,  # End position (x1, y1)
                # List of color stops
                [
                    (0, "red"),
                    (1 / 2, "violet"),
                    (1, "blue"),
                ],
            )

            canvas.fill_style = gradient
            # set alpha based on the number of true values in the bloom filter:
            # rational: the more true values, the less useful the bloom filter is
            canvas.global_alpha = (
                # count the number of False values in the bloom filter:
                sum(map(lambda x: not x, self.poor_mans_bloom_filter))
                / float(self.poor_mans_bloom_filter_size)
            )
            canvas.fill_arc(x, y, 10, 0, 2 * pi)
            canvas.global_alpha = 1

    # the factories have type parameters of their own, so that a factory can be made before its tree, e.g. as
    # ChristmasTree.InnerNodeFactory[Vector, str](); they are named K and V, as Key and Value would shadow those of
    # ChristmasTree:
    class InnerNodeFactory[K, V](RadixTrie.InnerNodeFactory[K, V]):
        """A factory for creating nodes in a Christmas tree."""

        def __init__(self, config: str = "inner"):
            """Create a new node factory.

            @param config: The configuration of the node factory: a string in ["inner", "buffered", "crystalball"]
            """
            super().__init__()
            assert config in ["inner", "buffered", "crystalball"], "Invalid config"
            self.config = config

        def new_instance(
            self, key_mapping=None, new_descriptor: Descriptor | None = None
        ) -> RadixTrie.InnerNode[K, V]:
            """Create a new instance of the node."""
            if self.config == "inner":
                return ChristmasTree.InnerNode[K, V](
                    key_mapping=key_mapping, parent_descriptor=new_descriptor
                )
            if self.config == "buffered":
                return ChristmasTree.BufferedInnerNode(
                    key_mapping=key_mapping, parent_descriptor=new_descriptor
                )
            if self.config == "crystalball":
                return ChristmasTree.CrystalBallBufferedInnerNode(
                    key_mapping=key_mapping, parent_descriptor=new_descriptor
                )
            raise ValueError("Invalid configuration")

    class LeafFactory[K, V](RadixTrie.LeafFactory[K, V]):
        """A factory for creating leaf nodes in a Christmas tree."""

        def new_instance(
            self, parent_descriptor, previous_leaf
        ) -> RadixTrie.LeafNode[K, V]:
            """See :meth:`RadixTrie.LeafFactory.new_instance`."""
            return ChristmasTree.LeafNode[K, V](parent_descriptor, previous_leaf)

    def __init__(
        self,
        children_per_inner_node: int,
        descriptor: Descriptor,
        key_mapping: KeyMapping[Key, Value] | None = None,
        number_of_inner_node_levels: int = 0,
        inner_node_factory=InnerNodeFactory[Key, Value](),
        leaf_factory=LeafFactory[Key, Value](),
    ):
        """Create a new Christmas tree with the given triangle as the base.

        See :meth:`RadixTrie.__init__` for the parameters; unlike there, the ``descriptor`` (the triangle) is
        required, and the ``key_mapping`` defaults to None, so that the inner nodes locate the child of a key via the
        child descriptors (the sub-triangles).
        """
        super().__init__(
            key_mapping=key_mapping,
            children_per_inner_node=children_per_inner_node,
            number_of_inner_node_levels=number_of_inner_node_levels,
            inner_node_factory=inner_node_factory,
            leaf_factory=leaf_factory,
            descriptor=descriptor,
        )

    def show(self) -> None:
        """Show the Christmas tree."""
        print("Christmas tree:")
        print(self.descriptor)
        super().show()

    def flush_all_buffers(self):
        """Flush the buffer to the children. Makes sense only if the root is a buffered inner node."""
        if isinstance(self.root, ChristmasTree.BufferedInnerNode):
            self.root.flush_all_buffers()
