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

"""Model of the replacement selection playground: the input, its presets and the sub-steps of replacement selection.

The playground shows :class:`~system.query_processing.sorting.ReplacementSelection` at work, sub-step by sub-step: it
drives the iterator on :class:`Element` objects and records a :class:`Frame` for every sub-step, with main memory as
the iterator keeps it, one array whose front is the heap and whose rest is the list. Replacement selection is not
implemented a second time: the swaps of a sift are read off the heap array before and after it, its comparisons are
read off the heap shown and checked against those swaps, the linear bulk load is replayed with
:func:`~system.query_processing.sorting.sift_down`, and after every step the memory shown is checked against the
iterator's, place by place.
"""

from __future__ import annotations

import random
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Literal, NamedTuple, cast

from system.query_processing.sorting import ReplacementSelection, sift_down

# the values the input may hold, and how many of them:
MIN_VALUE: int = 0
MAX_VALUE: int = 999
MAX_VALUES: int = 60
# the range of M, the number of places of main memory, which heap and list share:
MIN_MEMORY: int = 3
MAX_MEMORY: int = 12

# the caption of the frame that ends every heap maintenance, a bulk load or the sift after an output, in the words of
# the slides:
HALF_ORDER: str = "Heap maintains half order: no child is smaller than its parent"
# what the caption of the frame in which an element took the root's place adds when that frame also shows the sift
# after it (heap maintenance not step by step):
SANK: str = " and sifts down"
# the caption of the frame in which the list moves to the front of memory before a bulk load, closing the places that
# outputs left empty after the input ended:
LIST_TO_FRONT: str = (
    "Heap is empty: the list moves to the front of memory, in its order, closing the empty places"
)

# the example of the lecture's slides (09b, slides 24 to 43; slide 44 gives the pseudocode):
SLIDES_VALUES: tuple[int, ...] = (30, 20, 10, 40, 25, 73, 16, 26, 33, 50, 31)
SLIDES_MEMORY: int = 4

# the presets: the slides' example, and inputs of n distinct values drawn at random from a seed, as drawn, sorted,
# sorted in reverse, or sorted with a few neighbours swapped:
SLIDES: str = "slides' example"
RANDOM: str = "random"
SORTED: str = "sorted"
REVERSED: str = "reversed"
ALMOST_SORTED: str = "almost sorted"
PRESETS: tuple[str, ...] = (SLIDES, RANDOM, SORTED, REVERSED, ALMOST_SORTED)
# the n and the seed the generated presets start with:
DEFAULT_COUNT: int = 24
DEFAULT_SEED: int = 1

# a token of the input text that is a whole number, maybe with a sign (so that -5 is reported as out of range, not as
# no number, and +5 is read as 5); only the digits 0 to 9, unlike int(), which also reads other scripts' digits and
# underscores:
NUMBER_TOKEN: re.Pattern[str] = re.compile(r"[+-]?[0-9]+")
# how many characters of a token a message shows at most:
SHORTENED_LENGTH: int = 12

# the rows of the view a frame can mark a place in (a place of memory is marked in the heap's tree as well if it
# belongs to the heap):
Row = Literal["input", "memory", "output"]


class ReplayError(RuntimeError):
    """Raised when what the playground shows differs from the state of the iterator it follows."""


@dataclass(frozen=True, eq=False)
class Element:
    """An input element: its value and its position in the input.

    Elements compare by value only, with ``<``, the only comparison :mod:`~system.query_processing.sorting` uses, so
    that the code sees what it would see with plain numbers. Two elements are the same only if they are the same
    object (``eq=False``), so that the playground tells equal values apart by their position in the input.
    """

    value: int
    index: int

    def __lt__(self, other: Element) -> bool:
        """Compares the values of two elements.

        @param other: the element to compare with
        @return: whether this element's value is smaller
        """
        return self.value < other.value

    def __str__(self) -> str:
        """The element's value, as captions show it."""
        return str(self.value)


class Output(NamedTuple):
    """An element written to an output run."""

    run: int
    element: Element


class Mark(NamedTuple):
    """A place the view marks as changed or read in a sub-step."""

    # the row of the view:
    row: Row
    # the place in that row: in the input the position in the input, in memory the place in its array (place i of the
    # heap is place i of memory), in the output the position among all elements written, counted across the runs:
    place: int


class Comparison(NamedTuple):
    """The comparison of an output step, as the slides show it: the element written to the output (the last output)
    and the next element of the input, which is compared with it."""

    # the next element of the input, None if the input is empty, so that nothing is compared:
    drawn: Element | None
    # the element the step writes to the output:
    last: Element

    @property
    def into_heap(self) -> bool | None:
        """Whether the drawn element goes into the heap: it is not smaller than the last output, so it can still be
        written to the current run; None if the input is empty."""
        if self.drawn is None:
            return None
        return not self.drawn < self.last


@dataclass(frozen=True)
class Frame:  # pylint: disable=too-many-instance-attributes
    """What the view shows after one sub-step."""

    # what happened, in the wording of the slides:
    caption: str
    # how many elements were taken from the input; the next one is at this position:
    taken: int
    # main memory as one array of M places: the heap at the front, the list behind it, its newest element first. None
    # is an empty place: every place before the first load; the root's place for a moment after an output; the place
    # the heap just gave up, while the drawn element waits for it during the sift; a place the heap gave up after the
    # input ended; the places behind the list once it moved to the front; and the places an input shorter than M never
    # fills:
    memory: tuple[Element | None, ...]
    # the number of places at the front of memory that hold the heap, in level order (the children of place i are at
    # 2i + 1 and 2i + 2):
    heap_size: int
    # the elements written so far, with their runs:
    output: tuple[Output, ...]
    # the run the heap's elements belong to, -1 before the first run starts; the list's elements belong to the next
    # one:
    run: int
    # what the comparison box shows: the comparison of the output step the frame belongs to, from the frame that writes
    # the root to the output to the last frame before the next output, move of the list to the front or bulk load, and
    # at the end that of the last output step; None before the first output, in the move of the list to the front and
    # during a bulk load:
    comparison: Comparison | None = None
    # the places the sub-step changed or reads:
    marks: frozenset[Mark] = frozenset()
    # the inner nodes of the heap during a bulk load, which it sifts down one by one:
    inner: frozenset[int] = frozenset()
    # the places of the two elements a sift compares: the two children of the sinking element, or the sinking element
    # and its smaller child; empty if none:
    compared: tuple[()] | tuple[int, int] = ()
    # whether the frame is a step of heap maintenance: the order of a bulk load, or a comparison, swap or end of a sift
    # (in a bulk load or after an output), which the view leaves out with "Heap maintenance step by step" off:
    maintenance: bool = False

    @property
    def heap(self) -> tuple[Element | None, ...]:
        """The heap: the first ``heap_size`` places of memory; None is the root's place while it is empty."""
        return self.memory[: self.heap_size]

    @property
    def pending(self) -> tuple[Element, ...]:
        """The list of the slides, with the elements for the next run: the elements behind the heap, in memory order
        (the newest first once a run has started), without the empty places."""
        return tuple(
            element for element in self.memory[self.heap_size :] if element is not None
        )


def parse_values(text: str) -> tuple[int, ...]:
    """Reads the input from a text of whole numbers separated by spaces or commas.

    @param text: e.g. ``30 20 10 40`` or ``30, 20, 10, 40``
    @return: the values in their order
    @raise ValueError: with a message for the reader if the text holds no value, more than :data:`MAX_VALUES` values,
        a token that is not a whole number, or a value outside :data:`MIN_VALUE` to :data:`MAX_VALUE`
    """
    tokens: list[str] = text.replace(",", " ").split()
    if not tokens:
        raise ValueError("Type at least one value, e.g. 30 20 10 40.")
    if len(tokens) > MAX_VALUES:
        raise ValueError(
            f"{len(tokens)} values are too many: the playground takes at most {MAX_VALUES}."
        )
    values: list[int] = []
    for token in tokens:
        if not NUMBER_TOKEN.fullmatch(token):
            raise ValueError(f"'{shorten(token)}' is not a whole number.")
        # the digits without sign and leading zeros ("0" for zero) decide the length check: with more digits than
        # MAX_VALUE the number is out of range unconverted, so that int() never sees a long token (int() refuses a
        # string of more than 4300 digits, even if they are all leading zeros, with a message meant for programmers);
        # the minus is put back for int() and the message:
        digits: str = token.lstrip("+-").lstrip("0") or "0"
        signed_digits: str = ("-" if token.startswith("-") else "") + digits
        value: int | None = (
            None if len(digits) > len(str(MAX_VALUE)) else int(signed_digits)
        )
        if value is None or not MIN_VALUE <= value <= MAX_VALUE:
            raise ValueError(
                f"{shorten(signed_digits)} is out of range: values go from {MIN_VALUE} to {MAX_VALUE}."
            )
        values.append(value)
    return tuple(values)


def shorten(token: str) -> str:
    """Shortens a token of the input text for a message.

    @param token: the token
    @return: the token, or its first :data:`SHORTENED_LENGTH` characters and an ellipsis if it is longer
    """
    if len(token) <= SHORTENED_LENGTH:
        return token
    return token[:SHORTENED_LENGTH] + "…"


def format_values(values: Iterable[int]) -> str:
    """Writes values as the input text shows them.

    @param values: the values
    @return: the values separated by spaces, e.g. ``30 20 10 40``
    """
    return " ".join(str(value) for value in values)


def preset_values(
    name: str, count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED
) -> tuple[int, ...]:
    """Returns the input of a preset.

    @param name: one of :data:`PRESETS`
    @param count: n, the number of values of a generated preset (all but the slides' example)
    @param seed: the seed of the random draw of a generated preset
    @return: the slides' example, or ``count`` distinct values drawn at random from :data:`MIN_VALUE` to
        :data:`MAX_VALUE`, as drawn (random), sorted, sorted in reverse, or sorted with about every tenth pair of
        neighbours swapped (almost sorted, at least one pair if n > 1)
    @raise ValueError: if the name is not a preset or ``count`` is not between 1 and :data:`MAX_VALUES`
    """
    if name == SLIDES:
        return SLIDES_VALUES
    if name not in PRESETS:
        raise ValueError(f"The preset must be one of {PRESETS}, got {name!r}.")
    if not 1 <= count <= MAX_VALUES:
        raise ValueError(f"n goes from 1 to {MAX_VALUES}, got {count}.")
    generator: random.Random = random.Random(seed)
    values: list[int] = generator.sample(range(MIN_VALUE, MAX_VALUE + 1), count)
    if name == RANDOM:
        return tuple(values)
    values.sort()
    if name == REVERSED:
        values.reverse()
    elif name == ALMOST_SORTED and count > 1:
        # swap distinct pairs of neighbours, so that no swap undoes another (two pairs may overlap, which moves a
        # value two places):
        for left in generator.sample(range(count - 1), max(1, count // 10)):
            values[left], values[left + 1] = values[left + 1], values[left]
    return tuple(values)


def sift_swaps(
    before: Sequence[Element], after: Sequence[Element], position: int
) -> list[tuple[int, int]]:
    """Returns the swaps one sift down from ``position`` made, read off the heap array before and after it.

    The element at ``position`` moves down one path: it ends at the path's end, and every element below
    ``position`` on the path moves up one level. Each edge of the path is one swap of a parent with its child.

    @param before: the heap array before the sift
    @param after: the heap array after it
    @param position: the place of the element that was sifted down
    @return: the swaps as (parent, child) places, from the top down; none if the element stayed
    @raise ReplayError: if ``after`` is not ``before`` with the element at ``position`` moved down one path
    """
    moving: Element = before[position]
    ends: list[int] = [
        place for place, element in enumerate(after) if element is moving
    ]
    if len(before) != len(after) or len(ends) != 1:
        raise ReplayError(
            f"The heap {values_text(after)} is not the heap {values_text(before)} after a sift."
        )
    # the path from the end up to the sifted place, then turned top down:
    path: list[int] = [ends[0]]
    while path[-1] > position:
        path.append((path[-1] - 1) // 2)
    if path[-1] != position:
        raise ReplayError(
            f"{moving} did not move down from place {position}, it ended at place {ends[0]}."
        )
    path.reverse()
    swaps: list[tuple[int, int]] = list(zip(path, path[1:]))
    # the swaps must lead from the array before to the array after, element by element:
    replayed: list[Element] = list(before)
    for parent, child in swaps:
        replayed[parent], replayed[child] = replayed[child], replayed[parent]
    check_same(replayed, after, "heap after the swaps")
    return swaps


def check_same(
    shown: Sequence[Element | None], actual: Sequence[Element | None], what: str
) -> None:
    """Checks that the playground shows the same elements, in the same places, as the iterator holds.

    @param shown: what the playground shows, None for an empty place
    @param actual: what the iterator holds, None for an empty place
    @param what: what the two are, for the message
    @raise ReplayError: if the two differ in length or in any place; elements are compared by identity, so that two
        equal values at different positions of the input count as different, and an empty place only matches an empty
        place
    """
    if len(shown) != len(actual) or any(
        mine is not theirs for mine, theirs in zip(shown, actual)
    ):
        raise ReplayError(
            f"The playground's {what} {values_text(shown)} differs from the iterator's {values_text(actual)}."
        )


def values_text(elements: Iterable[Element | None]) -> str:
    """Writes elements for a message.

    @param elements: the elements, None for an empty place
    @return: their values in brackets, e.g. ``[10, 20, _]``
    """
    return (
        "["
        + ", ".join("_" if element is None else str(element) for element in elements)
        + "]"
    )


def run_lengths(output: Sequence[Output]) -> list[int]:
    """Returns how many elements each run holds.

    @param output: the elements written, in order, with their runs
    @return: the lengths of the runs, from run 0 on
    """
    lengths: list[int] = []
    for written in output:
        if written.run == len(lengths):
            lengths.append(0)
        lengths[-1] += 1
    return lengths


def smaller_child(heap: Sequence[Element], place: int) -> int | None:
    """Returns the place of the smaller child, as :func:`~system.query_processing.sorting.sift_down` chooses it.

    @param heap: the heap array
    @param place: a place in it
    @return: the place of the left child, or of the right one if it is smaller; None if the place has no child
    """
    left: int = 2 * place + 1
    if left >= len(heap):
        return None
    if left + 1 < len(heap) and heap[left + 1] < heap[left]:
        return left + 1
    return left


def children_caption(left: Element, right: Element) -> str:
    """Returns the caption's words on the comparison of a sinking element's two children.

    @param left: the left child
    @param right: the right child
    @return: e.g. ``"its children are 20 and 10; 10 is smaller"``; for equal children, that the sift takes the left
        one, as :func:`~system.query_processing.sorting.sift_down` does
    """
    children: str = f"its children are {left} and {right}; "
    if right < left:
        return f"{children}{right} is smaller"
    if left < right:
        return f"{children}{left} is smaller"
    return f"{children}neither is smaller, so the sift takes the left one"


def bulkload_order_caption(size: int) -> str:
    """Returns the caption of the frame that shows the order of a bulk load: the leaves need no sift, and the inner
    nodes are sifted down from the last one back to the root, as in
    :func:`~system.query_processing.sorting.bulkload`.

    @param size: the number of elements bulk-loaded, at least 2, so that there is an inner node
    @return: e.g. ``"Places 2 and 3 are leaves: nothing to sift. Sift down the inner nodes from place 1 back to the
        root, place 0"`` for 4 elements
    """
    # the inner nodes are the places 0 to size // 2 - 1, the leaves the places after them:
    first_leaf: int = size // 2
    last: int = size - 1
    leaves: str
    if first_leaf == last:
        leaves = f"Place {last} is a leaf"
    elif first_leaf + 1 == last:
        leaves = f"Places {first_leaf} and {last} are leaves"
    else:
        leaves = f"Places {first_leaf} to {last} are leaves"
    order: str = (
        "the only inner node, the root, place 0"
        if first_leaf == 1
        else f"the inner nodes from place {first_leaf - 1} back to the root, place 0"
    )
    return f"{leaves}: nothing to sift. Sift down {order}"


def caption_start(moving: Element, place: int, position: int) -> str:
    """Returns the opening words of the caption of a comparison in a sift.

    @param moving: the sinking element
    @param place: where it is now
    @param position: where the sift started
    @return: ``"Sift down 30 from place 0: "`` for the sift's first comparison, else ``"30 at place 2: "``
    """
    if place == position:
        return f"Sift down {moving} from place {position}: "
    return f"{moving} at place {place}: "


def plural(count: int, noun: str) -> str:
    """Writes a count with its noun.

    @param count: the count
    @param noun: the noun in the singular
    @return: e.g. ``1 element`` or ``4 elements``
    """
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


class Tracer:  # pylint: disable=too-many-instance-attributes
    """Drives :class:`ReplacementSelection` on an input and records a :class:`Frame` for every sub-step."""

    def __init__(self, values: Sequence[int], memory: int) -> None:
        """Makes the elements and the iterator, which reads the first M elements into its memory, as its list.

        @param values: the input
        @param memory: M, the number of places of main memory, which heap and list share
        @raise ValueError: if M is less than 1 (raised by the iterator)
        """
        # M, which the parameter memory names here as everywhere in this module (the array is self.memory below):
        self.places: int = memory
        self.elements: tuple[Element, ...] = tuple(
            Element(value, index) for index, value in enumerate(values)
        )
        self.selection: ReplacementSelection[Element] = ReplacementSelection(
            iter(self.elements), memory
        )
        self.frames: list[Frame] = []
        # what the frames show; it follows the iterator's state sub-step by sub-step:
        self.taken: int = 0
        # main memory with as many places as the iterator's, min(M, n), empty until the first M elements are loaded
        # (the frames add the places an input shorter than M never fills), and the size of the heap at its front:
        self.memory: list[Element | None] = [None] * len(self.selection.memory)
        self.heap_size: int = 0
        self.output: list[Output] = []
        # -1 until the first run starts, as in the iterator:
        self.run: int = -1
        # the comparison of the current output step, None outside of one:
        self.comparison: Comparison | None = None

    def record(
        self,
        caption: str,
        marks: Iterable[Mark] = (),
        inner: frozenset[int] = frozenset(),
        compared: tuple[()] | tuple[int, int] = (),
        maintenance: bool = False,
    ) -> None:
        """Records a frame of what the playground shows now, with the comparison of the current output step.

        @param caption: what happened
        @param marks: the places the sub-step changed or reads
        @param inner: the inner nodes of the heap, during a bulk load
        @param compared: the places of the two elements a sift compares
        @param maintenance: whether the frame is a step of heap maintenance (see :attr:`Frame.maintenance`)
        """
        self.frames.append(
            Frame(
                caption=caption,
                taken=self.taken,
                # padded to M places; those an input shorter than M never fills stay empty:
                memory=tuple(self.memory) + (None,) * (self.places - len(self.memory)),
                heap_size=self.heap_size,
                output=tuple(self.output),
                run=self.run,
                comparison=self.comparison,
                marks=frozenset(marks),
                inner=inner,
                compared=compared,
                maintenance=maintenance,
            )
        )

    def check_memory(self, what: str = "memory") -> None:
        """Checks that the playground shows the iterator's memory: every place, the empty ones included, and the size
        of the heap at its front.

        @param what: what the memory is, for the message
        @raise ReplayError: if a place or the heap size differs
        """
        check_same(self.memory, self.selection.memory, what)
        if self.heap_size != self.selection.heap_size:
            raise ReplayError(
                f"The playground's heap size {self.heap_size} differs from the iterator's "
                f"{self.selection.heap_size}."
            )

    def trace(self) -> list[Frame]:
        """Records the frames from the start to the end.

        @return: the frames
        @raise ReplayError: if what the playground shows ever differs from the iterator's state
        """
        # the start marks the elements the next step loads, as the slides do:
        self.record(
            f"Start: M = {self.places} elements fit into main memory, heap and list together",
            marks=(Mark("input", index) for index in range(len(self.memory))),
        )
        # the iterator has read the first M elements into its memory as the list, in reading order; the first step
        # bulk-loads them into the heap, as every later run's list:
        self.taken = len(self.memory)
        self.memory = list(self.elements[: self.taken])
        self.check_memory()
        if self.memory:
            self.record(
                f"Load next {plural(self.taken, 'element')} from input sequence into the list",
                marks=(Mark("memory", place) for place in range(self.taken)),
            )
        while self.step():
            pass
        lengths: list[int] = run_lengths(self.output)
        if not lengths:
            self.record("End: the input is empty, so no run is written")
            return self.frames
        average: float = sum(lengths) / len(lengths)
        # the end keeps the comparison of the last output step, whose input is empty, so that the box decides nothing;
        # the run lengths are separated by spaces, as in the input text, so that even 20 runs fit on one line:
        self.record(
            f"Continue… and end: {plural(len(self.output), 'element')} in {plural(len(lengths), 'run')} "
            f"({format_values(lengths)}), on average {average:.1f} "
            f"= {average / self.places:.1f} × M"
        )
        return self.frames

    def show_bulkload(self) -> None:
        """Shows the linear bulk load of the heap node by node and checks the memory it leads to against the
        iterator's.

        If the heap has an inner node, a frame first shows the bulk load's order (see :func:`bulkload_order_caption`).
        Then the loop is that of :func:`~system.query_processing.sorting.bulkload` on the heap at the front of memory:
        every inner node is sifted down within the heap, from the last one to the root (see :meth:`show_sift`). A frame
        with the finished heap in half order ends the bulk load.

        @raise ReplayError: if the replayed memory differs from the iterator's
        """
        size: int = self.heap_size
        inner: frozenset[int] = frozenset(range(size // 2))
        # the copy of memory that sift_down works on, as bulkload on the iterator's, so that the swaps can be read off
        # its heap:
        replayed: list[Element | None] = list(self.memory)
        if inner:
            self.record(bulkload_order_caption(size), inner=inner, maintenance=True)
        for position in reversed(range(size // 2)):
            # no place of the heap is empty in a bulk load:
            before: list[Element] = cast(list[Element], replayed[:size])
            sift_down(replayed, position, size)
            after: list[Element] = cast(list[Element], replayed[:size])
            self.show_sift(before, sift_swaps(before, after, position), position, inner)
        self.check_memory("bulk-loaded memory")
        self.record(HALF_ORDER)

    def show_sift(
        self,
        before: Sequence[Element],
        swaps: list[tuple[int, int]],
        position: int,
        inner: frozenset[int] = frozenset(),
    ) -> None:
        """Shows one sift down from ``position`` within the heap, every comparison and every swap a frame of its own.

        The comparisons are those :func:`~system.query_processing.sorting.sift_down` makes: where the sinking element
        has two children, first the two children compared with each other, then the sinking element compared with the
        smaller child; where it has one child, only that comparison. A comparison that finds the child smaller leads to
        a swap, and the sift goes on one level lower; else the element stays and the sift ends. A sift that reaches a
        leaf ends with a frame that says so; one that starts at a leaf compares nothing and shows nothing.

        The comparisons are read off the heap shown, which is ``before`` at the start, and checked against ``swaps``.

        @param before: the heap array before the sift (the first ``heap_size`` places of memory), which the playground
            shows now
        @param swaps: the swaps the sift made as (parent, child) places, from the top down (see :func:`sift_swaps`)
        @param position: the place the sift starts at
        @param inner: the inner nodes of the heap, during a bulk load
        @raise ReplayError: if the playground shows another heap than ``before``, or if the swaps the comparisons
            lead to differ from ``swaps``
        """
        check_same(self.memory[: self.heap_size], before, "heap before the sift")
        # the heap shown, which the comparisons are read off:
        heap: list[Element] = list(before)
        moving: Element = heap[position]
        place: int = position
        # the swaps the comparisons shown lead to, which must be those sift_down made:
        shown_swaps: list[tuple[int, int]] = []
        while True:
            child: int | None = smaller_child(heap, place)
            if child is None:
                # a leaf: a sift that has swapped has reached it; one that starts at a leaf compares nothing:
                if shown_swaps:
                    self.record(
                        f"{moving} at place {place} has reached a leaf",
                        marks=[Mark("memory", place)],
                        inner=inner,
                        maintenance=True,
                    )
                break
            start: str = caption_start(moving, place, position)
            left: int = 2 * place + 1
            lead: str
            if left + 1 < len(heap):
                # two children: they are compared first, and the decision's caption names the smaller one:
                self.record(
                    start + children_caption(heap[left], heap[left + 1]),
                    inner=inner,
                    compared=(left, left + 1),
                    maintenance=True,
                )
                lead = f"{moving} and its smaller child {heap[child]}: "
            else:
                lead = f"{start}its only child is {heap[child]}; "
            if not heap[child] < moving:
                self.record(
                    f"{lead}{heap[child]} ≥ {moving}, so {moving} stays",
                    inner=inner,
                    compared=(place, child),
                    maintenance=True,
                )
                break
            self.record(
                f"{lead}{heap[child]} < {moving}, so they swap",
                inner=inner,
                compared=(place, child),
                maintenance=True,
            )
            heap[place], heap[child] = heap[child], heap[place]
            self.show_swap(place, child, inner)
            shown_swaps.append((place, child))
            place = child
        if shown_swaps != swaps:
            raise ReplayError(
                f"The comparisons in the heap {values_text(before)} lead to the swaps {shown_swaps}, sift_down made "
                f"{swaps}."
            )

    def show_swap(
        self, parent: int, child: int, inner: frozenset[int] = frozenset()
    ) -> None:
        """Shows one swap of a sift, a frame of heap maintenance: the sinking element and its smaller child change
        places.

        @param parent: the place of the sinking element
        @param child: the place of its smaller child
        @param inner: the inner nodes of the heap, during a bulk load
        """
        moving: Element | None = self.memory[parent]
        smaller: Element | None = self.memory[child]
        self.memory[parent], self.memory[child] = smaller, moving
        self.record(
            f"{moving} swaps with its smaller child {smaller}",
            marks=[Mark("memory", parent), Mark("memory", child)],
            inner=inner,
            maintenance=True,
        )

    def step(self) -> bool:
        """Shows one output of the iterator: the root goes to the output run and the next element is drawn. If it is
        not smaller than the output, it takes the root's place; if it is smaller, or the input is empty, the heap gives
        up its last place and the element there takes the root's place (if the root was the heap's only element, the
        drawn element takes that place itself, as the list's newest element). If the heap then holds more than one
        element, the element at the root sinks (see :meth:`show_sift`), ending with the heap in half order; then a
        drawn element that is smaller than the output goes into the place the heap gave up, as the list's newest
        element. Before all that, if the heap is empty and the list is not, starts the next run.

        @return: False if heap and list are empty, so that nothing is left to write
        @raise ReplayError: if what the playground shows differs from the iterator's state
        """
        # the memory the playground shows must be the iterator's before the step, every place and the heap size:
        self.check_memory()
        if self.selection.heap_size == 0:
            if not self.selection.pending:
                return False
            self.next_run()
        before: list[Element] = self.selection.heap
        drawn: Element | None = (
            self.elements[self.taken] if self.taken < len(self.elements) else None
        )
        run, written = next(self.selection)
        if written is not before[0] or run != self.run:
            raise ReplayError(
                f"The iterator wrote {written} to run {run}, not the root {before[0]} to run {self.run}."
            )
        # the root goes to the output run; its place stays empty for a moment. From here to the last frame before the
        # next output, move of the list to the front or bulk load, every frame shows the root written and the next
        # element of the input compared with it, as on the slides:
        comparison: Comparison = Comparison(drawn, written)
        self.comparison = comparison
        self.memory[0] = None
        self.output.append(Output(run, written))
        # marked as on the slides: the element written, the empty root and the next element of the input, which is
        # compared with it:
        self.record(
            f"Remove top element {written} from heap and write it to output run {run}",
            marks=[Mark("output", len(self.output) - 1), Mark("memory", 0)]
            + ([] if drawn is None else [Mark("input", self.taken)]),
        )
        # the drawn element, or else the heap's last element, takes the root's place; a drawn element that waits for
        # the next run is placed after the sift:
        before_sift: list[Element]
        waiting: Element | None = None
        if drawn is None:
            before_sift = self.move_last(before, input_empty=True)
        else:
            self.taken += 1
            if comparison.into_heap:
                self.memory[0] = drawn
                self.record(
                    f"Draw next element {drawn} from input sequence: {drawn} ≥ {written}, so it takes the root's "
                    "place in the heap",
                    [Mark("memory", 0)],
                )
                before_sift = [drawn, *before[1:]]
            elif len(before) == 1:
                # the root was the heap's only element: the heap gives up its only place, which the drawn element
                # takes at once:
                self.memory[0] = drawn
                self.heap_size = 0
                self.record(
                    f"Draw next element {drawn} from input sequence: {drawn} < {written}, so it goes to the list, "
                    "into the place the heap gives up",
                    [Mark("memory", 0)],
                )
                before_sift = []
            else:
                # the drawn element waits in the comparison box while the heap gives up its last place:
                self.record(
                    f"Draw next element {drawn} from input sequence: {drawn} < {written}, so it goes to the list, "
                    "for the next run"
                )
                before_sift = self.move_last(before, input_empty=False)
                waiting = drawn
        # the element at the root sinks, as far as the iterator moved it, with every comparison and swap a frame, and
        # the heap maintains half order again; the root of a heap of one element has no child to compare with:
        if len(before_sift) > 1:
            self.show_sift(
                before_sift, sift_swaps(before_sift, self.selection.heap, 0), 0
            )
            self.record(HALF_ORDER)
        if waiting is not None:
            # the place the heap gave up, right behind it, takes the drawn element:
            self.memory[self.heap_size] = waiting
            self.record(
                f"{waiting} goes into the freed place: the list's newest element, next to the heap",
                [Mark("memory", self.heap_size)],
            )
        self.check_memory()
        return True

    def move_last(self, before: list[Element], input_empty: bool) -> list[Element]:
        """The heap gives up its last place, and the element there moves to the empty root, as the iterator does when
        the root leaves for good: the drawn element goes to the list, or the input is empty. The place given up stays
        empty, until the drawn element goes there after the sift (see :meth:`step`), or for good once the input is
        empty.

        @param before: the heap array before the root left, at least two elements unless the input is empty
        @param input_empty: whether the input is empty, which the caption then says
        @return: the heap array with the last element at the root, before it is sifted down; empty if the root was the
            heap's only element, whose place then stays empty without a frame of its own
        """
        self.heap_size = len(before) - 1
        if self.heap_size == 0:
            return []
        last: Element = before[-1]
        self.memory[0] = last
        self.memory[self.heap_size] = None
        self.record(
            (
                "R is empty: the heap gives up its last place,"
                if input_empty
                else "The heap gives up its last place,"
            )
            + f" and its last element {last} takes the root's place",
            marks=[Mark("memory", 0), Mark("memory", self.heap_size)],
        )
        return [last, *before[1:-1]]

    def next_run(self) -> None:
        """Starts the next run. If outputs left empty places before the list's elements (once the input has ended),
        the list first moves to the front of memory, in its memory order, closing them, as the iterator does. Then the
        list is shown as the new heap's array, the iterator starts the run (which moves the list and bulk-loads it in
        one go), and the playground shows that bulk load node by node and checks it against the iterator's memory.

        @raise ReplayError: if the iterator starts no run or a run with another number, or bulk-loads another heap
        """
        # a bulk load belongs to no output step, so the comparison box shows no comparison:
        self.comparison = None
        # the list's elements at the front, in their memory order, and the empty places behind them:
        front: list[Element | None] = [
            element for element in self.memory if element is not None
        ]
        size: int = len(front)
        front += [None] * (len(self.memory) - size)
        moved: list[int] = [
            place
            for place, (before, after) in enumerate(zip(self.memory, front))
            if before is not after
        ]
        if moved:
            self.memory = front
            self.record(LIST_TO_FRONT, marks=(Mark("memory", place) for place in moved))
        # the list's places become the heap's, in their order, as an array that need not be a heap yet:
        self.heap_size = size
        self.run += 1
        self.record(
            f"Bulkload a heap from the list: new run {self.run} starts",
            marks=(Mark("memory", place) for place in range(size)),
            inner=frozenset(range(size // 2)),
        )
        if not self.selection.start_next_run() or self.selection.run != self.run:
            raise ReplayError(f"The iterator did not start run {self.run}.")
        self.show_bulkload()


def trace(values: Sequence[int], memory: int) -> list[Frame]:
    """Runs replacement selection on an input and returns what the playground shows, sub-step by sub-step.

    Every frame shows main memory as the iterator keeps it: one array of M places, the heap at the front, the list
    behind it. The sub-steps: the start; the first M elements loaded into memory, as the list, in reading order;
    whenever the heap is empty and the list is not, the next run (run 0 first): if outputs left empty places before the
    list's elements, the list moved to the front of memory; the list's places taken as the heap's array; the bulk
    load's order (which places are leaves, and that the inner nodes are sifted down from the last one back to the
    root), then node by node every comparison, every swap and the end of each sift a frame of its own (see
    :meth:`Tracer.show_sift`), and the finished heap ("Heap maintains half order"). For every output: the root written
    to the output run; the next element drawn, which takes the root's place if it is not smaller than the output;
    else, or if the input is empty, the heap gives up its last place and the element there takes the root's place
    (where the root was the heap's only element, a drawn element takes the root's place itself, as the list's newest
    element); if the heap has more than one element, the sift of the element at the root, with every comparison and
    swap, and the heap again in half order; then a drawn element smaller than the output goes into the place the heap
    gave up, as the list's newest element. Last the end. The steps of heap maintenance (the order of a bulk load, the
    comparisons, swaps and ends of the sifts) are flagged (:attr:`Frame.maintenance`), so that the view can leave them
    out (see :func:`without_maintenance_steps`).

    @param values: the input
    @param memory: M, the number of places of main memory, which heap and list share
    @return: the frames, from the start to the end
    @raise ValueError: if M is less than 1
    @raise ReplayError: if what the playground shows ever differs from the iterator's state
    """
    return Tracer(values, memory).trace()


def next_output(frames: Sequence[Frame], position: int) -> int:
    """Returns the position of the next frame that writes an element to the output, for the view's button "next
    output", which skips draws, comparisons, swaps and bulk loads.

    @param frames: the frames shown: those of a trace, maybe without the steps of heap maintenance (see
        :func:`without_maintenance_steps`)
    @param position: the position of the frame shown now
    @return: the position of the first frame after ``position`` with one more element in the output than the frame
        before it; the last frame if no element is written after ``position``
    """
    for later in range(position + 1, len(frames)):
        if len(frames[later].output) > len(frames[later - 1].output):
            return later
    return len(frames) - 1


def without_maintenance_steps(
    frames: Sequence[Frame],
) -> tuple[list[Frame], list[int]]:
    """Returns the frames without the steps of heap maintenance, for the view's checkbox "Heap maintenance step by
    step".

    A bulk load keeps two frames: "Bulkload a heap from the list", with the list as an array that need not be a heap
    yet (without the dashes of the inner nodes, which no step sifts here), and the frame that ends it, "Heap maintains
    half order", marked where a place holds another element than before the bulk load. After an output, restoring the
    heap's half order is no step of its own: the frame in which the drawn element or the heap's last element took the
    root's place shows memory after the sift, marked where a place changed, and its caption says that the element
    sifts down (SANK). The steps in between (see :attr:`Frame.maintenance`) and the half order after an output are
    left out. The frames themselves come from :func:`trace`, which replays and checks every heap maintenance in full
    either way.

    @param frames: the frames of a trace
    @return: the frames kept, and for each its position in ``frames``, so that the view can find the same place in
        either list
    """
    kept_frames: list[Frame] = []
    positions: list[int] = []
    # memory in the frame before the heap maintenance under way, None outside of one, and whether that maintenance is
    # a bulk load (its first frame has inner nodes) or the sift after an output:
    memory_before: tuple[Element | None, ...] | None = None
    bulk_load: bool = False
    for position, frame in enumerate(frames):
        if frame.maintenance:
            # a step of heap maintenance; the first one follows the frame whose memory the end is compared with (every
            # trace starts with a frame that is no step of heap maintenance):
            if memory_before is None:
                memory_before = frames[position - 1].memory
                bulk_load = bool(frames[position - 1].inner)
            continue
        if memory_before is not None:
            # the end of the heap maintenance, "Heap maintains half order"; the places that hold another element than
            # before it (all of them in the heap, as heap maintenance moves elements within the heap only):
            changed: frozenset[Mark] = frozenset(
                Mark("memory", place)
                for place, (before, after) in enumerate(
                    zip(memory_before, frame.memory)
                )
                if before is not after
            )
            memory_before = None
            if not bulk_load:
                # after an output, the frame before the sift shows its result instead:
                before_sift: Frame = kept_frames[-1]
                kept_frames[-1] = replace(
                    before_sift,
                    caption=before_sift.caption + SANK,
                    memory=frame.memory,
                    marks=before_sift.marks | changed,
                )
                continue
            frame = replace(frame, marks=changed)
        elif frame.inner:
            # the start of a bulk load, whose inner nodes no step sifts here:
            frame = replace(frame, inner=frozenset())
        kept_frames.append(frame)
        positions.append(position)
    return kept_frames, positions
