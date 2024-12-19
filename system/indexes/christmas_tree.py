from __future__ import annotations

from itertools import chain
from math import pi
from typing import Iterator

from ipycanvas import Canvas

from system.indexes.radix_trie import RadixTrie, KeyMapping
from system.interfaces.indexing.Index import PutInfo
from system.utils import Descriptor, Vector


class ChristmasTree[Key, Value](RadixTrie[Key, Value]):
    """A simple implementation of a Christmas tree data structure."""

    class BufferedInnerNode[Key, Value](RadixTrie.InnerNode[Key, Value]):
        """A simple implementation of an inner node in a Christmas tree adding buffer tree-style buffers."""

        def __init__(
            self,
            key_mapping: KeyMapping[Key, Value] = None,
            parent_descriptor: Descriptor = None,
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

        def flush_all_buffers(self):
            """Flush all buffers in this node and its children."""
            self._flush_buffer()
            for c in self.children:
                if issubclass(
                    c.__class__, ChristmasTree.BufferedInnerNode
                ):  # TODO: refactor to get rid of type check, shown here for educational purposed how not do do this ;-)
                    c.flush_all_buffers()

        def put(self, key: Key, value: Value, level: int = 0) -> None | PutInfo:
            """Put the given key-value pair into this node."""
            if len(self.buffer) >= self.max_buffer_size:
                # buffer is full, then flush it:
                self._flush_buffer(level)

            # append to internal buffer:
            self.buffer.append((key, value))

            return None

        def get(self, key: Key, level: int = 0) -> Iterator[Value]:
            """Get the value for the given key.
            As this is a buffered inner node, we need to check the buffer first and in addition return the result of get
            from the children.
            """
            # filter the buffer for the given search key:
            buffer_it: Iterator[Value] = filter(lambda t: t[0] == key, self.buffer)

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
            super().draw(canvas, canvas_height, x_offset, y_offset)
            # draw the buffer:
            canvas.fill_style = "#ff0000"
            canvas.line_width = 1
            # get the center of the descriptor
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
            super().show(indent)
            print(indent + "Buffer:")
            for k, v in self.buffer:
                print(indent + f"  {k} -> {v}")

    class CrystalBallBufferedInnerNode(BufferedInnerNode):
        """Add a crystal ball to the buffered inner node."""

        def __init__(
            self,
            key_mapping: KeyMapping[Key, Value] = None,
            parent_descriptor: Descriptor = None,
            max_buffer_size: int = 30,
        ):
            super().__init__(key_mapping, parent_descriptor, max_buffer_size)
            # poor man's bloom- filter:
            # TODO: replace with full-blown implementation
            self.poor_mans_bloom_filter_size: int = 142
            self.poor_mans_bloom_filter: list[bool] = [
                False for _ in range(self.poor_mans_bloom_filter_size)
            ]

        def get(self, key: Key, level: int = 0) -> Iterator[Value]:
            if self.poor_mans_bloom_filter[
                key.my_hash() % self.poor_mans_bloom_filter_size
            ]:
                return super().get(key, level)
            else:
                return iter([])

        def put(self, key: Key, value: Value, level: int = 0) -> None | PutInfo:
            self.poor_mans_bloom_filter[
                key.my_hash() % self.poor_mans_bloom_filter_size
            ] = True
            return super().put(key, value, level)

        def show(self, indent: str = "") -> None:
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
            super().draw(
                canvas,
                canvas_height,
                x_offset,
            )
            radius: int = 25
            # get a consistent pseudo-random x_shift for the crystal ball:
            x_shift: int = -25 if self.__hash__() % 2 == 0 else 25
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

    class InnerNodeFactory[Key, Value](RadixTrie.InnerNodeFactory[Key, Value]):
        """A factory for creating nodes in a Christmas tree."""

        def __init__(self, config: str = "inner"):
            """Create a new node factory.

            @param config: The configuration of the node factory: a string in ["inner", "buffered", "crystalball"]
            """
            super().__init__()
            assert config in ["inner", "buffered", "crystalball"], "Invalid config"
            self.config = config

        def new_instance(
            self, key_mapping=None, new_descriptor: Descriptor = None
        ) -> RadixTrie[Key, Value].AbstractNode[Key, Value]:
            """Create a new instance of the node."""
            if self.config == "inner":
                return ChristmasTree.InnerNode[Key, Value](
                    parent_descriptor=new_descriptor
                )
            elif self.config == "buffered":
                return ChristmasTree.BufferedInnerNode[Key, Value](
                    key_mapping=key_mapping, parent_descriptor=new_descriptor
                )
            elif self.config == "crystalball":
                return ChristmasTree.CrystalBallBufferedInnerNode(
                    key_mapping=key_mapping, parent_descriptor=new_descriptor
                )
            else:
                raise ValueError("Invalid configuration")

    class LeafFactory[Key, Value](RadixTrie.LeafFactory[Key, Value]):
        """A factory for creating leaf nodes in a Christmas tree."""

        def new_instance(
            self, parent_descriptor, left_sibling=None
        ) -> RadixTrie[Key, Value].LeafNode[Key, Value]:
            """Create a new instance of the leaf node."""
            return ChristmasTree.LeafNode[Key, Value](parent_descriptor, left_sibling)

    def __init__(
        self,
        children_per_inner_node: int,
        descriptor: Descriptor,
        key_mapping: KeyMapping[Key, Value] = None,
        number_of_inner_node_levels: int = 0,
        inner_node_factory=InnerNodeFactory[Key, Value](),
        leaf_factory=LeafFactory[Key, Value](),
    ):
        """Create a new Christmas tree with the given triangle as the base."""
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
        if issubclass(self.root.__class__, ChristmasTree.BufferedInnerNode):
            self.root.flush_all_buffers()
