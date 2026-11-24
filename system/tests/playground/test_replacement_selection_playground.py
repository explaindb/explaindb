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
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring,too-many-lines
"""Tests for the replacement selection playground's model: the input, its presets and the frames of the sub-steps."""

from __future__ import annotations

import random
import re
import unittest
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import cast
from unittest import mock

from system.playground.replacement_selection_playground import (
    ALMOST_SORTED,
    HALF_ORDER,
    LIST_TO_FRONT,
    MAX_MEMORY,
    MAX_VALUE,
    MAX_VALUES,
    MIN_MEMORY,
    MIN_VALUE,
    RANDOM,
    REVERSED,
    SANK,
    SLIDES,
    SLIDES_MEMORY,
    SLIDES_VALUES,
    SORTED,
    Comparison,
    Element,
    Frame,
    Mark,
    Output,
    ReplayError,
    Tracer,
    bulkload_order_caption,
    caption_start,
    children_caption,
    format_values,
    next_output,
    parse_values,
    preset_values,
    run_lengths,
    shorten,
    sift_swaps,
    smaller_child,
    trace,
    without_maintenance_steps,
)
from system.query_processing.sorting import ReplacementSelection, bulkload, sift_down

# the caption of a swap, in the sift after an output and in the bulk load:
SWAP: str = "swaps with its smaller child"
# the end of a sift whose element has moved down to a leaf:
LEAF: str = "has reached a leaf"
# the starts of the captions of the frames right before a heap maintenance: the start of a bulk load, and the frames
# in which an element takes the root's place after an output:
BEFORE_MAINTENANCE: tuple[str, ...] = (
    "Bulkload a heap from the list",
    "Draw next element",
    "The heap gives up its last place",
    "R is empty",
)
# the start of the caption of the frame in which a drawn element smaller than the output goes into the place the heap
# gave up, after the sift:
FREED_PLACE: str = "goes into the freed place"
# the starts of the captions of the frames that end an output step: the next output, the list moved to the front of
# memory, the start of a bulk load and the end:
STEP_ENDS: tuple[str, ...] = (
    "Remove top element",
    LIST_TO_FRONT,
    "Bulkload a heap",
    "Continue… and end",
)
# the most characters a caption has, so that it fits on one line of a notebook of normal width: 110 characters of the
# widgets' bold text (13 px in JupyterLab) are about 700 pixels wide:
MAX_CAPTION_LENGTH: int = 110


def values(memory: Sequence[Element | None]) -> list[int | None]:
    """Returns the values of an array of memory (or of the heap, or the list), None for an empty place."""
    return [None if element is None else element.value for element in memory]


def runs(output: Sequence[Output]) -> list[list[int]]:
    """Returns the values written to each run, from run 0 on."""
    found: list[list[int]] = []
    for written in output:
        if written.run == len(found):
            found.append([])
        found[-1].append(written.element.value)
    return found


def find(frames: Sequence[Frame], caption: str) -> int:
    """Returns the position of the only frame with ``caption``."""
    positions: list[int] = [
        position for position, frame in enumerate(frames) if frame.caption == caption
    ]
    if len(positions) != 1:
        raise AssertionError(f"{len(positions)} frames have the caption {caption!r}")
    return positions[0]


def at(heap: Sequence[Element | None], place: int) -> Element:
    """Returns the element at ``place`` of a heap array, which must not be the empty root."""
    element: Element | None = heap[place]
    if element is None:
        raise AssertionError(f"place {place} of the heap is empty")
    return element


def comparison_of(frame: Frame) -> tuple[int | None, int, bool | None]:
    """Returns the comparison of a frame of an output step: the value of the next element of the input, the value of
    the element written and whether the next element goes into the heap; the first and the last are None once the
    input is empty."""
    comparison: Comparison | None = frame.comparison
    if comparison is None:
        raise AssertionError(f"the frame {frame.caption!r} compares nothing")
    drawn: int | None = None if comparison.drawn is None else comparison.drawn.value
    return drawn, comparison.last.value, comparison.into_heap


def sift_captions(frames: Sequence[Frame]) -> list[str]:
    """Returns the captions of the frames that show sifts, in a bulk load or after an output: every comparison, every
    swap and every end at a leaf."""
    return [
        frame.caption
        for frame in frames
        if frame.compared or SWAP in frame.caption or LEAF in frame.caption
    ]


def steps(
    frames: Sequence[Frame],
) -> list[tuple[str, tuple[int, ...], frozenset[Mark]]]:
    """Returns frames, e.g. those of a sift, as (caption, compared places, marks)."""
    return [(frame.caption, frame.compared, frame.marks) for frame in frames]


def half_order_after(frames: Sequence[Frame], position: int) -> int:
    """Returns the position of the first frame "Heap maintains half order" after ``position``, the end of the heap
    maintenance under way there."""
    for later in range(position + 1, len(frames)):
        if frames[later].caption == HALF_ORDER:
            return later
    raise AssertionError(f"no frame {HALF_ORDER!r} after frame {position}")


def memory_marks(*places: int) -> frozenset[Mark]:
    """Returns the marks of places of memory (place i of the heap is place i of memory)."""
    return frozenset(Mark("memory", place) for place in places)


def changed_places(before: Frame, after: Frame) -> frozenset[Mark]:
    """Returns the marks of the places of memory that hold another element in ``after`` than in ``before``, told
    apart by identity."""
    return frozenset(
        Mark("memory", place)
        for place, (old, new) in enumerate(zip(before.memory, after.memory))
        if old is not new
    )


def random_values(generator: random.Random, count: int, repeats: bool) -> list[int]:
    """Returns ``count`` values drawn by ``generator``: from 0 to 9 if ``repeats``, so that equal values are common,
    else distinct values from :data:`MIN_VALUE` to :data:`MAX_VALUE`."""
    if repeats:
        return [generator.randint(0, 9) for _ in range(count)]
    return generator.sample(range(MIN_VALUE, MAX_VALUE + 1), count)


# the captions of the outputs of the slides' example, in order:
SLIDES_OUTPUTS: list[str] = [
    f"Remove top element {value} from heap and write it to output run {run}"
    for run, run_values in enumerate(((10, 20, 25, 30, 40, 73), (16, 26, 31, 33, 50)))
    for value in run_values
]


# The changes of the iterator below reach into its memory, which its properties only show as copies; they stand for an
# iterator that holds another state than the playground shows.
# pylint: disable=protected-access


def clear_list(selection: ReplacementSelection[Element]) -> None:
    """Empties every place of the iterator's list, a change of the iterator for :class:`ChangingTracer`."""
    for place in range(selection.heap_size, len(selection.memory)):
        selection._memory[place] = None


def reverse_list(selection: ReplacementSelection[Element]) -> None:
    """Reverses the iterator's list in its places: the same elements in another order."""
    selection._memory[selection.heap_size :] = selection._memory[selection.heap_size :][
        ::-1
    ]


def swap_last_two(selection: ReplacementSelection[Element]) -> None:
    """Swaps the last two elements of the iterator's heap, a heap still."""
    last: int = selection.heap_size - 1
    selection._memory[last - 1], selection._memory[last] = (
        selection._memory[last],
        selection._memory[last - 1],
    )


def clear_heap(selection: ReplacementSelection[Element]) -> None:
    """Empties the iterator's heap: its places become empty and its size 0."""
    for place in range(selection.heap_size):
        selection._memory[place] = None
    selection._heap_size = 0


def shrink_heap(selection: ReplacementSelection[Element]) -> None:
    """Counts the iterator's heap one place smaller, its places unchanged."""
    selection._heap_size -= 1


def fill_empty_place(selection: ReplacementSelection[Element]) -> None:
    """Puts a new element of value 99 into the last place of the iterator's memory, which is empty."""
    assert selection._memory[-1] is None
    selection._memory[-1] = Element(99, 99)


def count_on(selection: ReplacementSelection[Element]) -> None:
    """Counts the iterator's current run as the next one."""
    selection._run += 1


# pylint: enable=protected-access


class ChangingTracer(Tracer):
    """A tracer, of the slides' example unless told otherwise, that changes the iterator's state once, between two
    steps, as soon as the playground shows a given number of outputs."""

    def __init__(
        self,
        outputs: int,
        change: Callable[[ReplacementSelection[Element]], None],
        input_values: tuple[int, ...] = SLIDES_VALUES,
        memory: int = SLIDES_MEMORY,
    ) -> None:
        """Makes the tracer.

        @param outputs: the number of outputs after which the iterator is changed
        @param change: what changes the iterator
        @param input_values: the input
        @param memory: M
        """
        super().__init__(input_values, memory)
        self.outputs: int = outputs
        self.change: Callable[[ReplacementSelection[Element]], None] | None = change

    def step(self) -> bool:
        """See :meth:`Tracer.step`. Before the step, changes the iterator if ``outputs`` elements are shown and it was
        not changed yet."""
        if self.change is not None and len(self.output) == self.outputs:
            self.change(self.selection)
            self.change = None
        return super().step()


class SlidesExampleTest(unittest.TestCase):
    """The example of the lecture's slides: 30 20 10 40 25 73 16 26 33 50 31 with M = 4."""

    def setUp(self) -> None:
        """Traces the slides' example."""
        self.frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)

    def test_runs_of_the_slides(self) -> None:
        """The output holds the two runs of the slides, 10 20 25 30 40 73 and 16 26 31 33 50, and the last caption
        sums them up.

        By hand: run 0 writes the heap 10 20 30 40 together with 25 (drawn after 10, 25 ≥ 10) and 73 (drawn after 20,
        73 ≥ 20); 16, 26, 33 and 50 are each smaller than the last output when drawn and go to the list; run 1 writes
        them with 31 (drawn after 16, 31 ≥ 16).

        Would fail if a drawn element that is not smaller than the last output went to the list, or if the frames
        recorded another output than the iterator's.
        """
        output: tuple[Output, ...] = self.frames[-1].output
        self.assertEqual([[10, 20, 25, 30, 40, 73], [16, 26, 31, 33, 50]], runs(output))
        self.assertEqual([6, 5], run_lengths(output))
        self.assertEqual(
            "Continue… and end: 11 elements in 2 runs (6 5), on average 5.5 = 1.4 × M",
            self.frames[-1].caption,
        )

    def test_captions_at_the_start(self) -> None:
        """The first ten captions load the list, bulk-load it as run 0, name the order of the bulk load and sift 20,
        then 30 down, one frame per comparison and per swap; the start marks the four elements of the input the load
        takes.

        By hand: of the four places, 2 and 3 are leaves, so the inner nodes 1 and then 0 are sifted. 20 at place 1
        has the only child 40, and 40 ≥ 20, so 20 stays; 30 at place 0 has the children 20 and 10, of which 10 is
        smaller, and 10 < 30, so the two swap, and 30 at place 2 has no child.

        Would fail if the first M elements went into the heap directly, if the bulk load left out its order or sifted
        the root first, if the children of 30 were not compared before 30 was compared with the smaller one, or if
        the start marked other elements of the input than those the load takes.
        """
        self.assertEqual(
            [
                "Start: M = 4 elements fit into main memory, heap and list together",
                "Load next 4 elements from input sequence into the list",
                "Bulkload a heap from the list: new run 0 starts",
                "Places 2 and 3 are leaves: nothing to sift. Sift down the inner nodes from place 1 back to the root, "
                "place 0",
                "Sift down 20 from place 1: its only child is 40; 40 ≥ 20, so 20 stays",
                "Sift down 30 from place 0: its children are 20 and 10; 10 is smaller",
                "30 and its smaller child 10: 10 < 30, so they swap",
                "30 swaps with its smaller child 10",
                "30 at place 2 has reached a leaf",
                "Heap maintains half order: no child is smaller than its parent",
            ],
            [frame.caption for frame in self.frames[:10]],
        )
        # the start marks 30 20 10 40, the elements the load takes, and shows memory empty:
        self.assertEqual(
            frozenset(Mark("input", index) for index in range(4)), self.frames[0].marks
        )
        self.assertEqual(
            ([None] * 4, 0), (values(self.frames[0].memory), self.frames[0].heap_size)
        )
        # memory holds the first four elements in reading order, all of them in the list, the heap is still empty:
        self.assertEqual(
            ([30, 20, 10, 40], 0, [], [30, 20, 10, 40]),
            (
                values(self.frames[1].memory),
                self.frames[1].heap_size,
                values(self.frames[1].heap),
                values(self.frames[1].pending),
            ),
        )
        self.assertEqual(4, self.frames[1].taken)

    def test_load_marks_the_list(self) -> None:
        """The frame that loads 30 20 10 40 into the list marks exactly the four places of memory it fills, 0 to 3,
        and no place of the input or the output.

        Would fail if the load marked the input it read instead of the places it filled, or fewer places than it
        loaded.
        """
        load: int = find(
            self.frames, "Load next 4 elements from input sequence into the list"
        )
        self.assertEqual(memory_marks(0, 1, 2, 3), self.frames[load].marks)

    def test_drawn_element_takes_the_root(self) -> None:
        """25 is drawn after 10 was written: 25 ≥ 10, so it takes the root's place and sinks: its children are
        compared, it swaps with the smaller one, 20, not with 30, is compared at place 1 with its only child 40 and
        stays; the heap maintains half order again before 20 is written.

        By hand: the heap 10 20 30 40 loses its root 10, so 25 at the root gives 25 20 30 40; of its children 20 and
        30, 20 is smaller, and 20 < 25, so the swap gives 20 25 30 40; at place 1, 40 ≥ 25, so 25 stays. The heap
        keeps its four places: memory holds no list.

        Would fail if the comparison were green for a drawn element that goes to the list, if the root swapped with
        the larger child, if a comparison of the sift had no frame of its own or named other places, or if the half
        order did not end the sift.
        """
        draw: int = find(
            self.frames,
            "Draw next element 25 from input sequence: 25 ≥ 10, so it takes the root's place in the heap",
        )
        frame: Frame = self.frames[draw]
        # the drawn element is at the root, compared with the last output 10:
        self.assertEqual(
            ([25, 20, 30, 40], 4, []),
            (values(frame.memory), frame.heap_size, values(frame.pending)),
        )
        self.assertEqual((25, 10, True), comparison_of(frame))
        self.assertEqual(memory_marks(0), frame.marks)
        # its sift, frame by frame, with its only swap:
        self.assertEqual(
            [
                (
                    "Sift down 25 from place 0: its children are 20 and 30; 20 is smaller",
                    (1, 2),
                    frozenset(),
                ),
                (
                    "25 and its smaller child 20: 20 < 25, so they swap",
                    (0, 1),
                    frozenset(),
                ),
                ("25 swaps with its smaller child 20", (), memory_marks(0, 1)),
                (
                    "25 at place 1: its only child is 40; 40 ≥ 25, so 25 stays",
                    (1, 3),
                    frozenset(),
                ),
                (HALF_ORDER, (), frozenset()),
            ],
            steps(self.frames[draw + 1 : draw + 6]),
        )
        self.assertEqual([20, 25, 30, 40], values(self.frames[draw + 3].memory))
        self.assertEqual(
            "Remove top element 20 from heap and write it to output run 0",
            self.frames[draw + 6].caption,
        )

    def test_drawn_element_goes_to_the_list(self) -> None:
        """16 is drawn after 25 was written: 16 < 25, so it goes to the list. It waits in the comparison box while the
        heap gives up its last place and the element there, 73, takes the root's place, is compared with 30, the
        smaller of its children, swaps with it and reaches a leaf; once the heap maintains half order again, 16 goes
        into the freed place, as the list's newest element, right behind the heap.

        By hand: after 10 and 20 were written memory is 25 40 30 73, all heap; 25 leaves, so the root is empty
        (_ 40 30 73); the heap gives up place 3, and 73 moves from there to the root (73 40 30 _, heap of three); of
        its children 40 and 30, 30 is smaller, and 30 < 73, so 73 swaps with 30 (30 40 73 _) and is at the leaf
        place 2; 16 goes into place 3 (30 40 73 16).

        Would fail if the drawn element replaced the root although it is smaller than the last output, if it went into
        memory before the sift, if the heap kept its last place after the last element moved to the root, if the bar
        between heap and list moved later than that, or if the sift of the last element left out a comparison or its
        end.
        """
        draw: int = find(
            self.frames,
            "Draw next element 16 from input sequence: 16 < 25, so it goes to the list, for the next run",
        )
        frame: Frame = self.frames[draw]
        # the root's place is empty, 16 is only in the comparison box, which is red; nothing in memory changes:
        self.assertEqual(
            ([None, 40, 30, 73], 4, []),
            (values(frame.memory), frame.heap_size, values(frame.pending)),
        )
        self.assertEqual((16, 25, False), comparison_of(frame))
        self.assertEqual(frozenset(), frame.marks)
        # the heap gives up its last place, and 73 moves from there to the root; both places are marked:
        moved: Frame = self.frames[draw + 1]
        self.assertEqual(
            "The heap gives up its last place, and its last element 73 takes the root's place",
            moved.caption,
        )
        self.assertEqual(
            ([73, 40, 30, None], 3, memory_marks(0, 3)),
            (values(moved.memory), moved.heap_size, moved.marks),
        )
        # 73 sinks: compared with the smaller child 30, at place 2, and swapped with it:
        self.assertEqual(
            [
                (
                    "Sift down 73 from place 0: its children are 40 and 30; 30 is smaller",
                    (1, 2),
                    frozenset(),
                ),
                (
                    "73 and its smaller child 30: 30 < 73, so they swap",
                    (0, 2),
                    frozenset(),
                ),
                ("73 swaps with its smaller child 30", (), memory_marks(0, 2)),
                ("73 at place 2 has reached a leaf", (), memory_marks(2)),
                (HALF_ORDER, (), frozenset()),
            ],
            steps(self.frames[draw + 2 : draw + 7]),
        )
        self.assertEqual(
            [[30, 40, 73, None]] * 3,
            [values(later.memory) for later in self.frames[draw + 4 : draw + 7]],
        )
        # then 16 goes into the freed place 3, the list's only element, and the next output follows:
        placed: Frame = self.frames[draw + 7]
        self.assertEqual(
            (
                "16 goes into the freed place: the list's newest element, next to the heap",
                [30, 40, 73, 16],
                3,
                [16],
                memory_marks(3),
                (16, 25, False),
            ),
            (
                placed.caption,
                values(placed.memory),
                placed.heap_size,
                values(placed.pending),
                placed.marks,
                comparison_of(placed),
            ),
        )
        self.assertEqual(SLIDES_OUTPUTS[3], self.frames[draw + 8].caption)

    def test_list_grows_towards_the_front(self) -> None:
        """The four elements of run 1 go into memory in the order they are drawn, each into the place the heap has
        just given up: 16 into place 3, 26 into place 2, 33 into place 1 and 50 into place 0, so that the list reads
        newest first, 50 33 26 16, when the heap is empty.

        By hand: the heap has four places when 16 is drawn and gives up one place for each of the four, the last one
        (place 0) when 73, the heap's only element, is written and 50 takes its place at once.

        Would fail if the list grew towards the end of memory, in the order of the input, or if a drawn element went
        into a place the heap still holds.
        """
        # per element drawn into the list (elements are equal only if they are the same), its value, the place it
        # first stands in and the heap's size in that frame:
        seen: list[Element] = []
        placed: list[tuple[int, int, int]] = []
        for frame in self.frames:
            comparison: Comparison | None = frame.comparison
            if (
                comparison is None
                or comparison.drawn is None
                or comparison.into_heap
                or comparison.drawn in seen
                or comparison.drawn not in frame.memory
            ):
                continue
            seen.append(comparison.drawn)
            placed.append(
                (
                    comparison.drawn.value,
                    frame.memory.index(comparison.drawn),
                    frame.heap_size,
                )
            )
        # (value, place, heap size): each right behind the heap:
        self.assertEqual([(16, 3, 3), (26, 2, 2), (33, 1, 1), (50, 0, 0)], placed)
        # memory before the bulk load of run 1:
        start: int = find(
            self.frames, "Bulkload a heap from the list: new run 1 starts"
        )
        self.assertEqual(
            ([50, 33, 26, 16], 0),
            (values(self.frames[start - 1].memory), self.frames[start - 1].heap_size),
        )

    def test_memory_after_outputs(self) -> None:
        """Memory as one array, worked out by hand on the slides' input with M = 4: after 3 outputs it is
        30 40 73 16 with a heap of three places; after 6 outputs 50 33 26 16 with an empty heap; after the bulk load
        of run 1 16 33 26 50, all heap. The heap of run 1 is not the slides' 16 26 33 50, as the in-place list is
        newest first.

        By hand: after 10 and 20 the heap is 25 40 30 73 (see test_drawn_element_goes_to_the_list), after 25 it is
        30 40 73 with 16 behind it; after 30 (26 drawn, 26 < 30) 73 moves up, swaps with 40, and 26 goes into place 2:
        40 73 26 16; after 40 (33 < 40) 73 moves up alone and 33 goes into place 1: 73 33 26 16; after 73 (50 < 73)
        50 takes place 0: 50 33 26 16. The bulk load sifts 33 at place 1 down past its only child 16 (50 16 26 33),
        then 50 at place 0 past 16 and past 33 (16 33 26 50).

        Would fail if the list were kept in another order, if the heap's size did not follow its places, or if the
        bulk load worked on another array than memory.
        """
        # per point: the frame before which the state is taken, the memory and the heap size there:
        cases: tuple[tuple[str, list[int | None], int], ...] = (
            (SLIDES_OUTPUTS[3], [30, 40, 73, 16], 3),
            ("Bulkload a heap from the list: new run 1 starts", [50, 33, 26, 16], 0),
            (SLIDES_OUTPUTS[6], [16, 33, 26, 50], 4),
        )
        for caption, memory, heap_size in cases:
            with self.subTest(caption=caption):
                before: Frame = self.frames[find(self.frames, caption) - 1]
                self.assertEqual(
                    (memory, heap_size), (values(before.memory), before.heap_size)
                )

    def test_run_1_starts_with_the_list(self) -> None:
        """Once 73 was written and 50 took its place, the heap is empty and memory holds the list 50 33 26 16 at its
        front, so that the list need not move: the bulk load of run 1 takes its four places as the heap's array, in
        place.

        Would fail if the next run started before the heap was empty, kept the run number, moved the list in memory
        or left a place to the list, or if a frame moved the list to the front although it starts there already.
        """
        start: int = find(
            self.frames, "Bulkload a heap from the list: new run 1 starts"
        )
        # before: the heap is empty, the list fills memory, run 0 still current:
        before: Frame = self.frames[start - 1]
        self.assertEqual(
            ([50, 33, 26, 16], 0, [50, 33, 26, 16], 0),
            (
                values(before.memory),
                before.heap_size,
                values(before.pending),
                before.run,
            ),
        )
        # the list's places become the heap of run 1, element by element, all four marked, the inner nodes dashed:
        frame: Frame = self.frames[start]
        self.assertEqual(
            (before.memory, 4, [], 1, memory_marks(0, 1, 2, 3), frozenset({0, 1})),
            (
                frame.memory,
                frame.heap_size,
                values(frame.pending),
                frame.run,
                frame.marks,
                frame.inner,
            ),
        )
        # the list never moves to the front in the slides' example:
        self.assertNotIn(LIST_TO_FRONT, [frame.caption for frame in self.frames])

    def test_drawn_element_swaps_twice(self) -> None:
        """73 is drawn after 20 was written: 73 ≥ 20, so it takes the root's place and swaps first with 25, then
        with 40, one frame per swap, each after the comparisons that lead to it; it ends at a leaf, and the heap
        maintains half order again.

        By hand: the heap 20 25 30 40 loses its root 20, so 73 at the root gives 73 25 30 40; of its children 25 and
        30, 25 is smaller, and 25 < 73, so 73 swaps with 25 (25 73 30 40); at place 1 its only child 40 < 73, so 73
        swaps with 40 (25 40 30 73) and is at the leaf place 3.

        Would fail if a sift of two levels were shown as one frame, if the second swap or a comparison were missed, if
        the comparison one level down were captioned as a new sift, or if the marks did not follow the moving element
        down.
        """
        draw: int = find(
            self.frames,
            "Draw next element 73 from input sequence: 73 ≥ 20, so it takes the root's place in the heap",
        )
        self.assertEqual([73, 25, 30, 40], values(self.frames[draw].memory))
        # the sift, frame by frame: the comparisons and the swap at the root, then those one level down:
        self.assertEqual(
            [
                (
                    "Sift down 73 from place 0: its children are 25 and 30; 25 is smaller",
                    (1, 2),
                    frozenset(),
                ),
                (
                    "73 and its smaller child 25: 25 < 73, so they swap",
                    (0, 1),
                    frozenset(),
                ),
                ("73 swaps with its smaller child 25", (), memory_marks(0, 1)),
                (
                    "73 at place 1: its only child is 40; 40 < 73, so they swap",
                    (1, 3),
                    frozenset(),
                ),
                ("73 swaps with its smaller child 40", (), memory_marks(1, 3)),
                ("73 at place 3 has reached a leaf", (), memory_marks(3)),
                (HALF_ORDER, (), frozenset()),
            ],
            steps(self.frames[draw + 1 : draw + 8]),
        )
        # memory after each swap:
        self.assertEqual(
            ([25, 73, 30, 40], [25, 40, 30, 73]),
            (
                values(self.frames[draw + 3].memory),
                values(self.frames[draw + 5].memory),
            ),
        )
        # then the next output:
        self.assertEqual(SLIDES_OUTPUTS[2], self.frames[draw + 8].caption)

    def test_heap_of_one_element_and_a_smaller_draw(self) -> None:
        """After 40 is written, 33 < 40 is drawn: the heap gives up place 1, 73 takes the root's place, alone in the
        heap, so nothing is compared, and 33 goes into place 1. After 73 is written, 50 < 73 is drawn: in a single
        frame the heap gives up its only place, and 50 takes it as the list's newest element.

        By hand: before 40 is written memory is 40 73 26 16 with a heap of two places; then _ 73 26 16; 73 _ 26 16
        with a heap of one; 73 33 26 16. Writing 73 gives _ 33 26 16, and 50 takes place 0: 50 33 26 16, heap empty.

        Would fail if a heap of one element were sifted or followed by the half order, or if a drawn element took two
        frames where the root was the heap's only element.
        """
        written: int = find(self.frames, SLIDES_OUTPUTS[4])
        self.assertEqual(
            [
                (
                    "Draw next element 33 from input sequence: 33 < 40, so it goes to the list, for the next run",
                    [None, 73, 26, 16],
                    2,
                    frozenset(),
                ),
                (
                    "The heap gives up its last place, and its last element 73 takes the root's place",
                    [73, None, 26, 16],
                    1,
                    memory_marks(0, 1),
                ),
                (
                    "33 goes into the freed place: the list's newest element, next to the heap",
                    [73, 33, 26, 16],
                    1,
                    memory_marks(1),
                ),
                (SLIDES_OUTPUTS[5], [None, 33, 26, 16], 1, memory_marks(0)),
                (
                    "Draw next element 50 from input sequence: 50 < 73, so it goes to the list, into the place the "
                    "heap gives up",
                    [50, 33, 26, 16],
                    0,
                    memory_marks(0),
                ),
                (
                    "Bulkload a heap from the list: new run 1 starts",
                    [50, 33, 26, 16],
                    4,
                    memory_marks(0, 1, 2, 3),
                ),
            ],
            [
                (
                    frame.caption,
                    values(frame.memory),
                    frame.heap_size,
                    # the places of memory marked (the write of 73 also marks the output and the input):
                    frozenset(mark for mark in frame.marks if mark.row == "memory"),
                )
                for frame in self.frames[written + 1 : written + 7]
            ],
        )
        # 50 is the comparison's drawn element, on red:
        self.assertEqual((50, 73, False), comparison_of(self.frames[written + 5]))

    def test_input_empty_last_element_takes_the_root(self) -> None:
        """Once the input is empty, writing 26 leaves the root's place empty; the heap gives up its last place, which
        stays empty, and the element there, 50, takes the root's place, is compared with its smaller child 31, swaps
        with it and reaches a leaf; the heap maintains half order again.

        By hand: run 1 starts with 16 33 26 50; 16 is written and 31 drawn (31 ≥ 16), which takes the root's place,
        and of its children 33 and 26 the smaller, 26, swaps with it: 26 33 31 50. 26 leaves, nothing is drawn, so the
        heap gives up place 3 and 50 moves from there to the root (50 33 31 _, heap of three); of its children 33 and
        31, 31 is smaller, and 31 < 50, so 50 swaps with 31 (31 33 50 _) and is at the leaf place 2.

        Would fail if the caption did not say that the input is empty, if the heap kept its last place, if the place
        given up were not empty, if a frame compared an element of the input although none was drawn, or if the sift
        left out a comparison or its end.
        """
        written: int = find(
            self.frames, "Remove top element 26 from heap and write it to output run 1"
        )
        # writing 26 marks it and the empty root, but no element of the input, which is empty; 26 is compared with
        # nothing:
        self.assertEqual(
            frozenset({Mark("output", 7), Mark("memory", 0)}),
            self.frames[written].marks,
        )
        self.assertEqual((None, 26, None), comparison_of(self.frames[written]))
        # the last element at the root, its place empty, the input used up, still nothing compared with 26:
        moved: Frame = self.frames[written + 1]
        self.assertEqual(
            "R is empty: the heap gives up its last place, and its last element 50 takes the root's place",
            moved.caption,
        )
        self.assertEqual(
            ([50, 33, 31, None], 3, []),
            (values(moved.memory), moved.heap_size, values(moved.pending)),
        )
        self.assertEqual(memory_marks(0, 3), moved.marks)
        self.assertEqual(
            (len(SLIDES_VALUES), (None, 26, None)),
            (moved.taken, comparison_of(moved)),
        )
        # its sift, with the swap with 31, still comparing nothing with 26:
        self.assertEqual(
            [
                (
                    "Sift down 50 from place 0: its children are 33 and 31; 31 is smaller",
                    (1, 2),
                    frozenset(),
                ),
                (
                    "50 and its smaller child 31: 31 < 50, so they swap",
                    (0, 2),
                    frozenset(),
                ),
                ("50 swaps with its smaller child 31", (), memory_marks(0, 2)),
                ("50 at place 2 has reached a leaf", (), memory_marks(2)),
                (HALF_ORDER, (), frozenset()),
            ],
            steps(self.frames[written + 2 : written + 7]),
        )
        self.assertEqual([31, 33, 50, None], values(self.frames[written + 4].memory))
        self.assertEqual(
            [(None, 26, None)] * 5,
            [comparison_of(frame) for frame in self.frames[written + 2 : written + 7]],
        )

    def test_writing_marks_the_next_element_of_the_input(self) -> None:
        """The frame that writes the root marks, as on the slides, the element in the output, the empty root and the
        next element of the input, which is compared with it: 25 when 10 is written, 16 when 25 is written.

        Would fail if the next element of the input were marked a frame late, at the draw, where its cell of the
        input is empty already, or not at all, or if the element written or the empty root were not marked.
        """
        cases: tuple[tuple[str, int, int], ...] = (
            (SLIDES_OUTPUTS[0], 0, 4),
            (SLIDES_OUTPUTS[2], 2, 6),
        )
        for caption, output, next_input in cases:
            with self.subTest(caption=caption):
                frame: Frame = self.frames[find(self.frames, caption)]
                self.assertEqual(
                    frozenset(
                        {
                            Mark("output", output),
                            Mark("memory", 0),
                            Mark("input", next_input),
                        }
                    ),
                    frame.marks,
                )
                # the marked element of the input is the next one, still in the input:
                self.assertEqual(next_input, frame.taken)

    def test_frame_count_and_outputs(self) -> None:
        """The slides' example has exactly 85 frames, and its outputs, in order, are 10 20 25 30 40 73 to run 0 and
        16 26 31 33 50 to run 1.

        By hand, counting per bulk load its start, its order, its comparisons, swaps and ends of sifts and its half
        order (the list never has to move to the front), and per output its write, its draw, the heap giving up its
        last place to the root, the comparisons, swaps and end of its sift, the half order and the drawn element put
        into the freed place, as far as they happen:

        - start 1 + load 1;
        - bulk load of run 0: 8 (new run; order; 20 compared with its only child 40, stays; 30's children 20 and 10
          compared, 30 compared with 10, swapped, at a leaf; half order);
        - outputs of run 0: 39, that is 7 for 10 (write; draw 25; its children compared, 25 compared with 20,
          swapped, compared with 40, stays; half order), 9 for 20 (write; draw 73; children compared, compared with
          25, swapped, compared with 40, swapped, at a leaf; half order), 9 for 25 (write; draw 16; 73 to the root;
          children compared, compared with 30, swapped, at a leaf; half order; 16 into place 3), 8 for 30 (write; draw
          26; 73 to the root; compared with its only child 40, swapped, at a leaf; half order; 26 into place 2), 4 for
          40 (write; draw 33; 73 to the root, alone in the heap, so no sift; 33 into place 1) and 2 for 73 (write;
          draw 50, which takes the heap's only place);
        - bulk load of run 1: 12 (new run; order; 33 compared with its only child 16, swapped, at a leaf; 50's
          children 16 and 26 compared, 50 compared with 16, swapped, compared with its only child 33, swapped, at a
          leaf; half order);
        - outputs of run 1: 23, that is 7 for 16 (write; draw 31; children 33 and 26 compared, compared with 26,
          swapped, at a leaf; half order), 7 for 26 (write; 50 to the root; children compared, compared with 31,
          swapped, at a leaf; half order), 6 for 31 (write; 50 to the root; compared with its only child 33, swapped,
          at a leaf; half order), 2 for 33 (write; 50 to the root, alone) and 1 for 50;
        - end 1;

        2 + 8 + 39 + 12 + 23 + 1 = 85.

        Would fail if a sub-step were added or dropped (e.g. a swap shown twice, a comparison, the end of a sift, a
        half order or the placing of a drawn element missing, or a heap of one element sifted), or if an output were
        written to the wrong run.
        """
        self.assertEqual(85, len(self.frames))
        self.assertEqual(
            SLIDES_OUTPUTS,
            [
                frame.caption
                for frame in self.frames
                if frame.caption.startswith("Remove top element")
            ],
        )


class EqualValuesTest(unittest.TestCase):
    """The notebook's example of equal values: 5 5 3 5 1 5 with M = 3."""

    def test_equal_values(self) -> None:
        """An element equal to the last output goes into the heap, and an element sifting down stops above an equal
        child; the frames tell the equal values apart by their position in the input.

        By hand, with the 5s named by their order in the input (5a 5b 3 5c 1 5d):

        - the list 5a 5b 3 is bulk-loaded as run 0: places 1 and 2 are leaves, so only the root is sifted; of 5a's
          children 5b and 3, 3 is smaller, and 3 < 5a, so 5a swaps with 3 and reaches a leaf, which gives 3 5b 5a;
        - 3 is written; 5c is drawn, 5c ≥ 3, so it takes the root's place (5c 5b 5a); its children 5b and 5a are
          equal, so the sift takes the left one, 5b, and 5b ≥ 5c, so 5c stays;
        - 5c is written; 1 is drawn, 1 < 5c, so it goes to the list; the heap gives up place 2, and the element there,
          5a, takes the root's place (5a 5b _), its only child 5b ≥ 5a, so it stays above the equal 5b; 1 goes into
          place 2 (5a 5b 1);
        - 5a is written; 5d is drawn, 5d ≥ 5a (equal, green), so it takes the root's place (5d 5b 1), and as 5b ≥ 5d
          it stays;
        - 5d is written; the input is empty, so the heap gives up place 1, and 5b takes the root's place, alone in the
          heap, so nothing is compared (5b _ 1); 5b is written, and the heap is empty (_ _ 1);
        - the list 1 moves to the front of memory (1 _ _) and is bulk-loaded as run 1, which has no inner node, and 1
          is written.

        Every sift ends with the heap in half order.

        Would fail if an element equal to the last output went to the list, if a sift swapped with an equal child or
        took the right one of two equal children, or if the frames mixed up equal values.
        """
        frames: list[Frame] = trace([5, 5, 3, 5, 1, 5], 3)
        # every caption of the walk-through above:
        self.assertEqual(
            [
                "Start: M = 3 elements fit into main memory, heap and list together",
                "Load next 3 elements from input sequence into the list",
                "Bulkload a heap from the list: new run 0 starts",
                "Places 1 and 2 are leaves: nothing to sift. Sift down the only inner node, the root, place 0",
                "Sift down 5 from place 0: its children are 5 and 3; 3 is smaller",
                "5 and its smaller child 3: 3 < 5, so they swap",
                "5 swaps with its smaller child 3",
                "5 at place 2 has reached a leaf",
                HALF_ORDER,
                "Remove top element 3 from heap and write it to output run 0",
                "Draw next element 5 from input sequence: 5 ≥ 3, so it takes the root's place in the heap",
                "Sift down 5 from place 0: its children are 5 and 5; neither is smaller, so the sift takes the left "
                "one",
                "5 and its smaller child 5: 5 ≥ 5, so 5 stays",
                HALF_ORDER,
                "Remove top element 5 from heap and write it to output run 0",
                "Draw next element 1 from input sequence: 1 < 5, so it goes to the list, for the next run",
                "The heap gives up its last place, and its last element 5 takes the root's place",
                "Sift down 5 from place 0: its only child is 5; 5 ≥ 5, so 5 stays",
                HALF_ORDER,
                "1 goes into the freed place: the list's newest element, next to the heap",
                "Remove top element 5 from heap and write it to output run 0",
                "Draw next element 5 from input sequence: 5 ≥ 5, so it takes the root's place in the heap",
                "Sift down 5 from place 0: its only child is 5; 5 ≥ 5, so 5 stays",
                HALF_ORDER,
                "Remove top element 5 from heap and write it to output run 0",
                "R is empty: the heap gives up its last place, and its last element 5 takes the root's place",
                "Remove top element 5 from heap and write it to output run 0",
                LIST_TO_FRONT,
                "Bulkload a heap from the list: new run 1 starts",
                HALF_ORDER,
                "Remove top element 1 from heap and write it to output run 1",
                "Continue… and end: 6 elements in 2 runs (5 1), on average 3.0 = 1.0 × M",
            ],
            [frame.caption for frame in frames],
        )
        # 5d, equal to the last output 5a, goes into the heap (green), above the equal 5b:
        draw: int = find(
            frames,
            "Draw next element 5 from input sequence: 5 ≥ 5, so it takes the root's place in the heap",
        )
        self.assertEqual((5, 5, True), comparison_of(frames[draw]))
        self.assertEqual(
            [5, 1, 4], [at(frames[draw].memory, place).index for place in (0, 1, 2)]
        )
        # the 5s are written as 5c 5a 5d 5b, so no sift swapped one of them with an equal child:
        self.assertEqual(
            [2, 3, 0, 5, 1, 4],
            [written.element.index for written in frames[-1].output],
        )
        self.assertEqual([[3, 5, 5, 5, 5], [1]], runs(frames[-1].output))


class EdgeCaseTest(unittest.TestCase):
    """Inputs at the edges: none, fewer values than M, and the smallest M."""

    def test_empty_input(self) -> None:
        """An empty input gives the start frame and the end frame only, which mark nothing and compare nothing.

        Would fail if an empty list were bulk-loaded as a run, if the end's average divided by zero runs, if the start
        marked M elements of an input that has none, or if the end compared with a last output that does not exist.
        """
        frames: list[Frame] = trace([], 4)
        self.assertEqual(
            [
                "Start: M = 4 elements fit into main memory, heap and list together",
                "End: the input is empty, so no run is written",
            ],
            [frame.caption for frame in frames],
        )
        self.assertEqual(
            ((None,) * 4, 0, (), (), (), 0),
            (
                frames[-1].memory,
                frames[-1].heap_size,
                frames[-1].heap,
                frames[-1].pending,
                frames[-1].output,
                frames[-1].taken,
            ),
        )
        self.assertEqual(
            [(frozenset(), None)] * 2,
            [(frame.marks, frame.comparison) for frame in frames],
        )

    def test_fewer_values_than_memory(self) -> None:
        """Two values with M = 5 are loaded, bulk-loaded and written as one run, the input being empty after the
        load. Every frame shows memory with its five places, the three the input never fills empty, while the
        iterator holds two places only.

        By hand for 7 3: the start marks both values; the list 7 3 (7 3 _ _ _) is bulk-loaded (place 1 is a leaf, so
        only the root is sifted: 7 is compared with its only child 3, swaps with it and reaches a leaf: 3 7 _ _ _), 3
        is written and nothing is drawn, so the heap gives up place 1, and 7 takes the root's place, alone in the
        heap, so that nothing is compared (7 _ _ _ _); 7 is written, and the heap is empty.

        Would fail if the load waited for M elements, if the start or the load marked M places of an input shorter
        than M, if a frame showed fewer places than M or put an element into a place the input never fills, if the
        heap's only element were moved to its own place in a frame of its own, or if a heap of one element were sifted
        or followed by the half order.
        """
        tracer: Tracer = Tracer([7, 3], 5)
        frames: list[Frame] = tracer.trace()
        self.assertEqual(
            [
                "Start: M = 5 elements fit into main memory, heap and list together",
                "Load next 2 elements from input sequence into the list",
                "Bulkload a heap from the list: new run 0 starts",
                "Place 1 is a leaf: nothing to sift. Sift down the only inner node, the root, place 0",
                "Sift down 7 from place 0: its only child is 3; 3 < 7, so they swap",
                "7 swaps with its smaller child 3",
                "7 at place 1 has reached a leaf",
                HALF_ORDER,
                "Remove top element 3 from heap and write it to output run 0",
                "R is empty: the heap gives up its last place, and its last element 7 takes the root's place",
                "Remove top element 7 from heap and write it to output run 0",
                "Continue… and end: 2 elements in 1 run (2), on average 2.0 = 0.4 × M",
            ],
            [frame.caption for frame in frames],
        )
        # the start marks the two values, all the input holds, and the load the two places of memory they fill:
        self.assertEqual(
            frozenset({Mark("input", 0), Mark("input", 1)}), frames[0].marks
        )
        self.assertEqual(memory_marks(0, 1), frames[1].marks)
        # memory, frame by frame, with five places, of which the iterator holds the first two:
        self.assertEqual(2, len(tracer.selection.memory))
        self.assertEqual(
            [
                ([None] * 5, 0),
                ([7, 3, None, None, None], 0),
                # the bulk load: its start, its order and the comparison, then the swap, the leaf and the half order:
                *[([7, 3, None, None, None], 2)] * 3,
                *[([3, 7, None, None, None], 2)] * 3,
                ([None, 7, None, None, None], 2),
                ([7, None, None, None, None], 1),
                ([None] * 5, 1),
                ([None] * 5, 0),
            ],
            [(values(frame.memory), frame.heap_size) for frame in frames],
        )

    def test_smallest_memory(self) -> None:
        """With M = 1 every run is a stretch of the input that does not fall; with M = 2 the heap can hold back one
        element.

        By hand for 5 1 2 8 3 3 (the two 3s named 3a and 3b by their order in the input): with M = 1, 5 is written,
        1 < 5 takes the heap's only place as the list and starts run 1, which takes 1 2 8, and 3a < 8 starts run 2,
        which takes 3a 3b (3b ≥ 3a); a heap of one element never compares nor swaps. With M = 2, the list 5 1 is
        bulk-loaded (5 is compared with its only child 1, swaps with it and reaches a leaf: 1 5); 1 is written, 2
        drawn (compared with its only child 5, it stays) and written, 8 drawn (compared with 5, it swaps with it and
        reaches a leaf) and 5 written; 3a < 5 goes to the list: the heap gives up place 1, 8 takes the root's place,
        alone, so nothing is compared, and 3a goes into place 1 (8 3a); 8 is written, and 3b < 8 takes the heap's only
        place, newest first (3b 3a); run 1 bulk-loads 3b 3a, where 3b at the root is compared with the equal 3a and
        stays above it, and writes 3b first, then 3a.

        Would fail if a heap of one element showed a comparison or a swap, if the bulk load swapped an element with an
        equal child, if the list were kept in the order of the input, if a run were cut short or merged with the next,
        or if an element equal to the last output started a new run.
        """
        # per M: the runs, the positions in the input of the elements written, and the captions of the sifts:
        cases: tuple[tuple[int, list[list[int]], list[int], list[str]], ...] = (
            (1, [[5], [1, 2, 8], [3, 3]], [0, 1, 2, 3, 4, 5], []),
            (
                2,
                [[1, 2, 5, 8], [3, 3]],
                [1, 2, 0, 3, 5, 4],
                [
                    "Sift down 5 from place 0: its only child is 1; 1 < 5, so they swap",
                    "5 swaps with its smaller child 1",
                    "5 at place 1 has reached a leaf",
                    "Sift down 2 from place 0: its only child is 5; 5 ≥ 2, so 2 stays",
                    "Sift down 8 from place 0: its only child is 5; 5 < 8, so they swap",
                    "8 swaps with its smaller child 5",
                    "8 at place 1 has reached a leaf",
                    "Sift down 3 from place 0: its only child is 3; 3 ≥ 3, so 3 stays",
                ],
            ),
        )
        for memory, expected, indexes, sifts in cases:
            with self.subTest(memory=memory):
                frames: list[Frame] = trace([5, 1, 2, 8, 3, 3], memory)
                self.assertEqual(expected, runs(frames[-1].output))
                self.assertEqual(
                    indexes, [written.element.index for written in frames[-1].output]
                )
                self.assertEqual(sifts, sift_captions(frames))

    def test_memory_below_one(self) -> None:
        """M = 0 and M = -1 are rejected with a ValueError, as by the iterator.

        Would fail if the playground traced an input with no memory at all, which would write nothing.
        """
        for memory in (0, -1):
            with self.subTest(memory=memory):
                with self.assertRaisesRegex(ValueError, "at least 1"):
                    trace(SLIDES_VALUES, memory)


class ListToFrontTest(unittest.TestCase):
    """The list moved to the front of memory before a bulk load, where outputs after the end of the input left empty
    places before it."""

    def test_slides_input_cut_after_26(self) -> None:
        """The first eight values of the slides' input, 30 20 10 40 25 73 16 26, with M = 4: the input ends while the
        list holds 26 and 16 behind a heap of two, so the next two outputs leave places 1 and 0 empty, and before run 1
        the list moves to the front of memory, in its order, closing them, in a frame of its own; then it is
        bulk-loaded there as run 1.

        By hand: as in the slides' example, after 30 is written memory is 40 73 26 16 with a heap of two places. 40 is
        written and nothing is drawn: the heap gives up place 1, which stays empty, and 73 takes the root's place,
        alone (73 _ 26 16); 73 is written (_ _ 26 16), and the heap is empty. The list moves to the front (26 16 _ _),
        which changes every place; the bulk load takes places 0 and 1 as the heap: place 1 is a leaf, 26 at the root
        is compared with its only child 16, swaps with it and reaches a leaf (16 26 _ _). 16 is written, the heap
        gives up place 1, and 26 takes the root's place (26 _ _ _); 26 is written. The runs are 10 20 25 30 40 73 and
        16 26.

        Would fail if the bulk load worked on the list where it stands, behind empty places, if the move changed the
        list's order, if the move were part of the bulk load's start, so that the view could not show it, or if it
        were left out without the steps of heap maintenance.
        """
        frames: list[Frame] = trace(SLIDES_VALUES[:8], SLIDES_MEMORY)
        written: int = find(frames, SLIDES_OUTPUTS[4])
        # every frame from the write of 40 on, as (caption, memory, heap size, places of memory marked):
        self.assertEqual(
            [
                (SLIDES_OUTPUTS[4], [None, 73, 26, 16], 2, memory_marks(0)),
                (
                    "R is empty: the heap gives up its last place, and its last element 73 takes the root's place",
                    [73, None, 26, 16],
                    1,
                    memory_marks(0, 1),
                ),
                (SLIDES_OUTPUTS[5], [None, None, 26, 16], 1, memory_marks(0)),
                (LIST_TO_FRONT, [26, 16, None, None], 0, memory_marks(0, 1, 2, 3)),
                (
                    "Bulkload a heap from the list: new run 1 starts",
                    [26, 16, None, None],
                    2,
                    memory_marks(0, 1),
                ),
                (
                    "Place 1 is a leaf: nothing to sift. Sift down the only inner node, the root, place 0",
                    [26, 16, None, None],
                    2,
                    frozenset(),
                ),
                (
                    "Sift down 26 from place 0: its only child is 16; 16 < 26, so they swap",
                    [26, 16, None, None],
                    2,
                    frozenset(),
                ),
                (
                    "26 swaps with its smaller child 16",
                    [16, 26, None, None],
                    2,
                    memory_marks(0, 1),
                ),
                (
                    "26 at place 1 has reached a leaf",
                    [16, 26, None, None],
                    2,
                    memory_marks(1),
                ),
                (HALF_ORDER, [16, 26, None, None], 2, frozenset()),
                (
                    "Remove top element 16 from heap and write it to output run 1",
                    [None, 26, None, None],
                    2,
                    memory_marks(0),
                ),
                (
                    "R is empty: the heap gives up its last place, and its last element 26 takes the root's place",
                    [26, None, None, None],
                    1,
                    memory_marks(0, 1),
                ),
                (
                    "Remove top element 26 from heap and write it to output run 1",
                    [None] * 4,
                    1,
                    memory_marks(0),
                ),
                (
                    "Continue… and end: 8 elements in 2 runs (6 2), on average 4.0 = 1.0 × M",
                    [None] * 4,
                    0,
                    frozenset(),
                ),
            ],
            [
                (
                    frame.caption,
                    values(frame.memory),
                    frame.heap_size,
                    frozenset(mark for mark in frame.marks if mark.row == "memory"),
                )
                for frame in frames[written:]
            ],
        )
        # the move keeps the list's elements, in their order, and belongs to no output step:
        move: int = find(frames, LIST_TO_FRONT)
        self.assertEqual(frames[move - 1].pending, frames[move].pending)
        self.assertEqual((None, 0), (frames[move].comparison, frames[move].run))
        self.assertEqual([[10, 20, 25, 30, 40, 73], [16, 26]], runs(frames[-1].output))
        # without the steps of heap maintenance, the move is kept as it is:
        kept, positions = without_maintenance_steps(frames)
        self.assertIs(frames[move], kept[positions.index(move)])

    def test_move_is_the_iterators(self) -> None:
        """The list moves to the front in the order in which the iterator moves it. A second iterator on the same
        elements, whose bulk load is replaced by one that changes nothing, holds after starting run 1 exactly the memory
        of the frame that moves the list (26 16 _ _), element by element. The replay check after the bulk load alone
        could not tell, as both orders of 26 and 16 bulk-load into the same heap 16 26.

        Would fail if the playground moved the list in another order than ``start_next_run``, e.g. its oldest element
        first.
        """
        tracer: Tracer = Tracer(SLIDES_VALUES[:8], SLIDES_MEMORY)
        frames: list[Frame] = tracer.trace()
        moved: Frame = frames[find(frames, LIST_TO_FRONT)]
        self.assertEqual([26, 16, None, None], values(moved.memory))
        # a second iterator on the same elements, up to the end of run 0, whose six outputs empty its heap:
        selection: ReplacementSelection[Element] = ReplacementSelection(
            iter(tracer.elements), SLIDES_MEMORY
        )
        for _ in range(6):
            next(selection)
        self.assertEqual(0, selection.heap_size)
        # run 1 starts with the bulk load replaced by one that changes nothing, so that memory shows the list moved:
        with mock.patch("system.query_processing.sorting.bulkload") as bulk_load:
            self.assertTrue(selection.start_next_run())
        bulk_load.assert_called_once()
        self.assertEqual(
            [id(element) for element in moved.memory],
            [id(element) for element in selection.memory],
        )


class RunShapeTest(unittest.TestCase):
    """The runs of sorted and reversed inputs, whose lengths are known."""

    def test_reversed_input_gives_runs_of_m(self) -> None:
        """A reversed input gives runs of exactly M elements, the last one of n mod M if that is not 0, each run
        sorted.

        Every element drawn is smaller than every element written before, so it goes to the list: each run writes the
        M elements it started with and no more.

        Would fail if a drawn element smaller than the last output went into the heap, or if a run started before
        the heap was empty.
        """
        for count in (1, 5, 12, 13, 24, MAX_VALUES):
            for memory in (1, 3, 4, 7, 12):
                with self.subTest(n=count, memory=memory):
                    frames: list[Frame] = trace(
                        preset_values(REVERSED, count, 3), memory
                    )
                    expected: list[int] = [memory] * (count // memory)
                    if count % memory:
                        expected.append(count % memory)
                    self.assertEqual(expected, run_lengths(frames[-1].output))
                    # each run is sorted:
                    for run in runs(frames[-1].output):
                        self.assertEqual(sorted(run), run)

    def test_sorted_input_gives_one_run(self) -> None:
        """A sorted input gives a single run of all n elements, whatever M.

        Would fail if an element not smaller than the last output went to the list.
        """
        for count in (1, 5, 24, MAX_VALUES):
            for memory in (1, 3, 12):
                with self.subTest(n=count, memory=memory):
                    input_values: tuple[int, ...] = preset_values(SORTED, count, 3)
                    frames: list[Frame] = trace(input_values, memory)
                    self.assertEqual([list(input_values)], runs(frames[-1].output))


class BulkLoadTest(unittest.TestCase):
    """The linear bulk load of the list into the heap, node by node and comparison by comparison."""

    def test_inner_nodes_from_the_last_to_the_root(self) -> None:
        """The bulk load names its order and sifts down every inner node, from the last one up to the root: every
        comparison has a frame of its own that names the two places compared (the two children of the sinking
        element, then the element and its smaller child), every swap a frame that marks the two places, and every
        sift ends with a frame that says why; every frame of the bulk load shows the inner nodes, and it ends with
        the heap Floyd's method builds.

        By hand:

        - 30 20 10 40 with M = 4: places 2 and 3 are leaves; 20 at place 1 stays above its only child 40; of 30's
          children 20 and 10, 10 is smaller, so 30 at place 0 swaps with 10 and reaches the leaf place 2;
        - 16 26 33 50 with M = 4: 26 stays above its only child 50; of 16's children 26 and 33, 26 is smaller, and 16
          stays above it, so nothing swaps;
        - 40 10 20 45 50 with M = 5: places 2 to 4 are leaves; of 10's children 45 and 50, 45 is smaller, and 10 at
          place 1 stays above it; of 40's children 10 and 20, 10 is smaller, so 40 at place 0 swaps with 10, and at
          place 1, of its children 45 and 50, 45 is smaller, and 40 stays above it;
        - 70 60 50 40 30 20 10 with M = 7: places 3 to 6 are leaves; of 50's children 20 and 10, 10 is smaller, so 50
          at place 2 swaps with 10 and reaches a leaf; of 60's children 40 and 30, 30 is smaller, so 60 at place 1
          swaps with 30 and reaches a leaf; of 70's children 30 and 10, 10 is smaller, so 70 at place 0 swaps with
          10, and at place 2, of its children 20 and 50, 20 is smaller, so it swaps with 20 and reaches the leaf
          place 5, which gives 10 30 20 40 60 70 50.

        Would fail if the inner nodes were sifted from the root down, if a leaf were sifted, if the order were not
        named first, if the children of a sinking element were not compared before it, if a comparison named the
        larger child or had no frame of its own, if a later comparison of a sift were captioned as a new sift, if the
        frame that ends a sift were missing or named the wrong reason, or if the frames of the bulk load did not show
        the inner nodes.
        """
        unmarked: frozenset[Mark] = frozenset()
        # per input: M, the frames of the bulk load as (caption, compared places, marks), and the heap after it:
        cases: tuple[
            tuple[
                tuple[int, ...],
                int,
                list[tuple[str, tuple[int, ...], frozenset[Mark]]],
                list[int],
            ],
            ...,
        ] = (
            (
                (30, 20, 10, 40),
                4,
                [
                    (
                        "Places 2 and 3 are leaves: nothing to sift. Sift down the inner nodes from place 1 "
                        "back to the root, place 0",
                        (),
                        unmarked,
                    ),
                    (
                        "Sift down 20 from place 1: its only child is 40; 40 ≥ 20, so 20 stays",
                        (1, 3),
                        unmarked,
                    ),
                    (
                        "Sift down 30 from place 0: its children are 20 and 10; 10 is smaller",
                        (1, 2),
                        unmarked,
                    ),
                    (
                        "30 and its smaller child 10: 10 < 30, so they swap",
                        (0, 2),
                        unmarked,
                    ),
                    ("30 swaps with its smaller child 10", (), memory_marks(0, 2)),
                    ("30 at place 2 has reached a leaf", (), memory_marks(2)),
                ],
                [10, 20, 30, 40],
            ),
            (
                (16, 26, 33, 50),
                4,
                [
                    (
                        "Places 2 and 3 are leaves: nothing to sift. Sift down the inner nodes from place 1 "
                        "back to the root, place 0",
                        (),
                        unmarked,
                    ),
                    (
                        "Sift down 26 from place 1: its only child is 50; 50 ≥ 26, so 26 stays",
                        (1, 3),
                        unmarked,
                    ),
                    (
                        "Sift down 16 from place 0: its children are 26 and 33; 26 is smaller",
                        (1, 2),
                        unmarked,
                    ),
                    (
                        "16 and its smaller child 26: 26 ≥ 16, so 16 stays",
                        (0, 1),
                        unmarked,
                    ),
                ],
                [16, 26, 33, 50],
            ),
            (
                (40, 10, 20, 45, 50),
                5,
                [
                    (
                        "Places 2 to 4 are leaves: nothing to sift. Sift down the inner nodes from place 1 "
                        "back to the root, place 0",
                        (),
                        unmarked,
                    ),
                    (
                        "Sift down 10 from place 1: its children are 45 and 50; 45 is smaller",
                        (3, 4),
                        unmarked,
                    ),
                    (
                        "10 and its smaller child 45: 45 ≥ 10, so 10 stays",
                        (1, 3),
                        unmarked,
                    ),
                    (
                        "Sift down 40 from place 0: its children are 10 and 20; 10 is smaller",
                        (1, 2),
                        unmarked,
                    ),
                    (
                        "40 and its smaller child 10: 10 < 40, so they swap",
                        (0, 1),
                        unmarked,
                    ),
                    ("40 swaps with its smaller child 10", (), memory_marks(0, 1)),
                    (
                        "40 at place 1: its children are 45 and 50; 45 is smaller",
                        (3, 4),
                        unmarked,
                    ),
                    (
                        "40 and its smaller child 45: 45 ≥ 40, so 40 stays",
                        (1, 3),
                        unmarked,
                    ),
                ],
                [10, 40, 20, 45, 50],
            ),
            (
                (70, 60, 50, 40, 30, 20, 10),
                7,
                [
                    (
                        "Places 3 to 6 are leaves: nothing to sift. Sift down the inner nodes from place 2 "
                        "back to the root, place 0",
                        (),
                        unmarked,
                    ),
                    (
                        "Sift down 50 from place 2: its children are 20 and 10; 10 is smaller",
                        (5, 6),
                        unmarked,
                    ),
                    (
                        "50 and its smaller child 10: 10 < 50, so they swap",
                        (2, 6),
                        unmarked,
                    ),
                    ("50 swaps with its smaller child 10", (), memory_marks(2, 6)),
                    ("50 at place 6 has reached a leaf", (), memory_marks(6)),
                    (
                        "Sift down 60 from place 1: its children are 40 and 30; 30 is smaller",
                        (3, 4),
                        unmarked,
                    ),
                    (
                        "60 and its smaller child 30: 30 < 60, so they swap",
                        (1, 4),
                        unmarked,
                    ),
                    ("60 swaps with its smaller child 30", (), memory_marks(1, 4)),
                    ("60 at place 4 has reached a leaf", (), memory_marks(4)),
                    (
                        "Sift down 70 from place 0: its children are 30 and 10; 10 is smaller",
                        (1, 2),
                        unmarked,
                    ),
                    (
                        "70 and its smaller child 10: 10 < 70, so they swap",
                        (0, 2),
                        unmarked,
                    ),
                    ("70 swaps with its smaller child 10", (), memory_marks(0, 2)),
                    (
                        "70 at place 2: its children are 20 and 50; 20 is smaller",
                        (5, 6),
                        unmarked,
                    ),
                    (
                        "70 and its smaller child 20: 20 < 70, so they swap",
                        (2, 5),
                        unmarked,
                    ),
                    ("70 swaps with its smaller child 20", (), memory_marks(2, 5)),
                    ("70 at place 5 has reached a leaf", (), memory_marks(5)),
                ],
                [10, 30, 20, 40, 60, 70, 50],
            ),
        )
        for input_values, memory, expected, heap in cases:
            with self.subTest(values=input_values):
                frames: list[Frame] = trace(input_values, memory)
                start: int = find(
                    frames, "Bulkload a heap from the list: new run 0 starts"
                )
                end: int = half_order_after(frames, start)
                # every frame between the start of the bulk load and its half order, in order:
                self.assertEqual(expected, steps(frames[start + 1 : end]))
                # every frame of the bulk load shows the inner nodes, the frame after it none:
                inner: frozenset[int] = frozenset(range(len(input_values) // 2))
                self.assertEqual(
                    [inner] * (end - start),
                    [frame.inner for frame in frames[start:end]],
                )
                self.assertEqual(frozenset(), frames[end].inner)
                # the heap after the bulk load:
                self.assertEqual(heap, values(frames[end].heap))


class SmallerChildTest(unittest.TestCase):
    """The smaller child a sift compares with, and the start of a comparison's caption."""

    def test_smaller_child(self) -> None:
        """``smaller_child`` returns the left child unless the right one is smaller, the left one of two equal
        children, the only child of a place that has one, and None for a leaf.

        Would fail if equal children gave the right one, which ``sift_down`` does not choose, if a place with only a
        left child read past the end of the heap, or if a leaf got a child.
        """
        ten, twenty, thirty, forty = (
            Element(10, 0),
            Element(20, 1),
            Element(30, 2),
            Element(40, 3),
        )
        # per case: the heap, the place and its smaller child:
        cases: tuple[tuple[str, list[Element], int, int | None], ...] = (
            ("right smaller", [ten, thirty, twenty], 0, 2),
            ("left smaller", [ten, twenty, thirty], 0, 1),
            ("equal children", [ten, twenty, Element(20, 4)], 0, 1),
            ("only a left child", [ten, twenty, thirty, forty], 1, 3),
            ("leaf", [ten, twenty, thirty, forty], 2, None),
            ("single element", [ten], 0, None),
        )
        for name, heap, place, expected in cases:
            with self.subTest(name):
                self.assertEqual(expected, smaller_child(heap, place))

    def test_smaller_child_is_the_one_sift_down_swaps_with(self) -> None:
        """On random heaps, with and without equal values, a sift that swaps at all swaps first with the child
        ``smaller_child`` returns, and a sift that swaps nothing has no child or one that ``smaller_child`` names and
        that is not smaller.

        Would fail if ``smaller_child`` chose between equal children otherwise than ``sift_down``, so that the
        playground framed a different child blue than the one the iterator compares with.
        """
        generator: random.Random = random.Random(11)
        moved: int = 0
        for attempt in range(300):
            size: int = generator.randint(1, 20)
            repeats: bool = attempt % 2 == 1
            # a heap with a new element at a random place, whose subtrees are heaps:
            heap: list[Element] = [
                Element(value, index)
                for index, value in enumerate(random_values(generator, size, repeats))
            ]
            bulkload(heap)
            position: int = generator.randrange(size)
            heap[position] = Element(random_values(generator, 1, repeats)[0], size)
            before: list[Element] = list(heap)
            sift_down(heap, position)
            swaps: list[tuple[int, int]] = sift_swaps(before, heap, position)
            child: int | None = smaller_child(before, position)
            with self.subTest(before=values(before), position=position):
                if swaps:
                    self.assertEqual((position, child), swaps[0])
                    moved += 1
                elif child is not None:
                    self.assertFalse(before[child] < before[position])
        # sifts that swap were checked:
        self.assertGreater(moved, 10)

    def test_caption_start(self) -> None:
        """``caption_start`` starts the caption of a sift's first comparison with the place the sift starts at, and of
        every later one with the place the sinking element has reached.

        Would fail if a later comparison said "Sift down" again, as if a new sift started, or named the sift's start
        instead of the element's place.
        """
        seventy: Element = Element(70, 0)
        self.assertEqual(
            [
                "Sift down 70 from place 0: ",
                "70 at place 2: ",
                "Sift down 70 from place 1: ",
                "70 at place 4: ",
            ],
            [
                caption_start(seventy, place, position)
                for place, position in ((0, 0), (2, 0), (1, 1), (4, 1))
            ],
        )


class ComparisonFrameTest(unittest.TestCase):
    """The frames of a sift's comparisons: the two children of the sinking element, then the element and its smaller
    child, or the only child alone."""

    def test_children_caption(self) -> None:
        """``children_caption`` names both children and the smaller one, whether it is the left or the right one, and
        says of equal children that neither is smaller, so that the sift takes the left one.

        Would fail if the larger child were named the smaller one, or if one of two equal children were called smaller,
        which would hide that ``sift_down`` takes the left one only because the right one is not smaller.
        """
        ten, twenty = Element(10, 0), Element(20, 1)
        # per case: the left child, the right child and the caption's words:
        cases: tuple[tuple[str, Element, Element, str], ...] = (
            ("right smaller", twenty, ten, "its children are 20 and 10; 10 is smaller"),
            ("left smaller", ten, twenty, "its children are 10 and 20; 10 is smaller"),
            (
                "equal",
                Element(5, 2),
                Element(5, 3),
                "its children are 5 and 5; neither is smaller, so the sift takes the left one",
            ),
        )
        for name, left, right, expected in cases:
            with self.subTest(name):
                self.assertEqual(expected, children_caption(left, right))

    def test_children_compared_before_the_smaller_child(self) -> None:
        """Where the sinking element has two children, a frame compares the two (both children's places), and the
        next frame compares the element with the smaller child: the right one if it is smaller, else the left one,
        also if the two are equal; neither frame changes the heap.

        By hand: in the slides' bulk load of run 0, 30's children are 20 and 10, the right one smaller; after 10 is
        written, 25 at the root has the children 20 and 30, the left one smaller; for 5 5 3 5 1 5 with M = 3, after 3
        is written, the third 5 of the input is at the root, with the second 5 at place 1 and the first one at place 2:
        the left child, the second 5, is taken, and the root stays above it.

        Would fail if a sift compared the element with a child before comparing the children, if the frame of the
        children named other places than theirs, if the sift took the right one of two equal children, or if a
        comparison were recorded after the swap it leads to.
        """
        # per case: the input, M, the caption of the frame that compares the children, and the caption and the places
        # of the frame after it, which compares the sinking element with the smaller child:
        cases: tuple[tuple[tuple[int, ...], int, str, str, tuple[int, int]], ...] = (
            (
                SLIDES_VALUES,
                SLIDES_MEMORY,
                "Sift down 30 from place 0: its children are 20 and 10; 10 is smaller",
                "30 and its smaller child 10: 10 < 30, so they swap",
                (0, 2),
            ),
            (
                SLIDES_VALUES,
                SLIDES_MEMORY,
                "Sift down 25 from place 0: its children are 20 and 30; 20 is smaller",
                "25 and its smaller child 20: 20 < 25, so they swap",
                (0, 1),
            ),
            (
                (5, 5, 3, 5, 1, 5),
                3,
                "Sift down 5 from place 0: its children are 5 and 5; neither is smaller, so the sift takes the left "
                "one",
                "5 and its smaller child 5: 5 ≥ 5, so 5 stays",
                (0, 1),
            ),
        )
        for input_values, memory, children, decision, compared in cases:
            with self.subTest(children=children):
                frames: list[Frame] = trace(input_values, memory)
                position: int = find(frames, children)
                # the two children, then the element and the smaller child:
                self.assertEqual(
                    [(children, (1, 2)), (decision, compared)],
                    [
                        (frame.caption, frame.compared)
                        for frame in frames[position : position + 2]
                    ],
                )
                # neither comparison changes the heap shown before it:
                self.assertEqual(
                    [frames[position - 1].heap] * 2,
                    [frame.heap for frame in frames[position : position + 2]],
                )
        # the two equal children: the left one, taken, is the second 5 of the input, the right one the first:
        frames = trace((5, 5, 3, 5, 1, 5), 3)
        heap: tuple[Element | None, ...] = frames[
            find(frames, "5 and its smaller child 5: 5 ≥ 5, so 5 stays")
        ].heap
        self.assertEqual([3, 1, 0], [at(heap, place).index for place in range(3)])

    def test_only_child_is_compared_alone(self) -> None:
        """Where the sinking element has only one child, a single frame compares the element with it, with no
        comparison of children before it, in a bulk load and after an output, at the start of a sift and one level
        down.

        By hand, in the slides' example: in the bulk load of run 0, 20 at place 1 has only the child 40 at place 3;
        after 20 is written, 73 swaps from the root to place 1, whose only child is 40 at place 3; after 30 is written,
        the heap gives up place 2 and 73 is at the root of 73 40, with only the child 40 at place 1.

        Would fail if a sift compared a right child that does not exist, showed a comparison of children where there
        is only one, or compared other places than the element's and its child's.
        """
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        # per case: the caption of the comparison, its places and the caption of the frame before it:
        cases: tuple[tuple[str, tuple[int, int], str], ...] = (
            (
                "Sift down 20 from place 1: its only child is 40; 40 ≥ 20, so 20 stays",
                (1, 3),
                "Places 2 and 3 are leaves: nothing to sift. Sift down the inner nodes from place 1 back to the root, "
                "place 0",
            ),
            (
                "73 at place 1: its only child is 40; 40 < 73, so they swap",
                (1, 3),
                "73 swaps with its smaller child 25",
            ),
            (
                "Sift down 73 from place 0: its only child is 40; 40 < 73, so they swap",
                (0, 1),
                "The heap gives up its last place, and its last element 73 takes the root's place",
            ),
        )
        for caption, compared, before in cases:
            with self.subTest(caption=caption):
                position: int = find(frames, caption)
                self.assertEqual(compared, frames[position].compared)
                # the frame before compares nothing:
                self.assertEqual(
                    (before, ()),
                    (frames[position - 1].caption, frames[position - 1].compared),
                )

    def test_element_that_stays_ends_the_sift(self) -> None:
        """A comparison that finds the child not smaller says that the sinking element stays, names the element's and
        the child's places, marks nothing and ends the sift without changing the heap: the heap maintenance ends with
        the half order, or a bulk load goes on with the sift of its next inner node.

        By hand: in the bulk load of 40 10 20 45 50 with M = 5, 10 at place 1 stays above 45, the smaller of its
        children 45 and 50, and the sift of 40 follows; 40, after its swap with 10, stays above 45 too, which ends the
        bulk load; in the slides' bulk load of run 0, 20 at place 1 stays above its only child 40, and the sift of 30
        follows; after 25 has taken the root's place and swapped with 20, 25 at place 1 stays above its only child 40,
        as on the slides; for 5 5 3 5 1 5 with M = 3, after 3 is written, the third 5 of the input takes the root's
        place and stays above the second one, the left of its two equal children.

        Would fail if a sift went on after its element stayed, if the comparison that ends it named other places or
        marked any, if the heap changed, or if the heap maintenance after an output did not end with the half order.
        """
        # per case: the input, M, the caption of the comparison, its places, whether it lies in a bulk load, and the
        # caption of the frame after it:
        cases: tuple[
            tuple[tuple[int, ...], int, str, tuple[int, int], bool, str], ...
        ] = (
            (
                (40, 10, 20, 45, 50),
                5,
                "10 and its smaller child 45: 45 ≥ 10, so 10 stays",
                (1, 3),
                True,
                "Sift down 40 from place 0: its children are 10 and 20; 10 is smaller",
            ),
            (
                (40, 10, 20, 45, 50),
                5,
                "40 and its smaller child 45: 45 ≥ 40, so 40 stays",
                (1, 3),
                True,
                HALF_ORDER,
            ),
            (
                SLIDES_VALUES,
                SLIDES_MEMORY,
                "Sift down 20 from place 1: its only child is 40; 40 ≥ 20, so 20 stays",
                (1, 3),
                True,
                "Sift down 30 from place 0: its children are 20 and 10; 10 is smaller",
            ),
            (
                SLIDES_VALUES,
                SLIDES_MEMORY,
                "25 at place 1: its only child is 40; 40 ≥ 25, so 25 stays",
                (1, 3),
                False,
                HALF_ORDER,
            ),
            (
                (5, 5, 3, 5, 1, 5),
                3,
                "5 and its smaller child 5: 5 ≥ 5, so 5 stays",
                (0, 1),
                False,
                HALF_ORDER,
            ),
        )
        for input_values, memory, caption, compared, in_bulk_load, after in cases:
            with self.subTest(caption=caption):
                frames: list[Frame] = trace(input_values, memory)
                position: int = find(frames, caption)
                frame: Frame = frames[position]
                self.assertEqual(
                    (compared, frozenset(), in_bulk_load),
                    (frame.compared, frame.marks, bool(frame.inner)),
                )
                # the next frame ends the sift, on the same memory:
                self.assertEqual(
                    (after, frame.memory),
                    (frames[position + 1].caption, frames[position + 1].memory),
                )


class HeapMaintenanceTest(unittest.TestCase):
    """The steps of heap maintenance (the order of a bulk load, and the comparisons, swaps and ends of every sift) and
    the half order that ends each heap maintenance."""

    def test_bulkload_order_caption(self) -> None:
        """``bulkload_order_caption`` names the leaves, one, two or a range of them, and the order of the sifts: the
        only inner node, the root, or the inner nodes from the last one back to the root.

        By hand: of n places, the inner nodes are 0 to n // 2 − 1 and the leaves n // 2 to n − 1: for n = 2 the leaf
        1 and the root alone; for 3 the leaves 1 and 2 and the root alone; for 4 the leaves 2 and 3 and the inner nodes
        1 and 0; for 5 the leaves 2 to 4 and the inner nodes 1 and 0; for 7 the leaves 3 to 6 and the inner nodes 2
        to 0.

        Would fail if the first leaf were off by one, so that the last inner node were called a leaf or the first leaf
        an inner node, if two leaves were written as a range or more than two as a pair, or if the last inner node
        named were not n // 2 − 1.
        """
        cases: tuple[tuple[int, str], ...] = (
            (
                2,
                "Place 1 is a leaf: nothing to sift. Sift down the only inner node, the root, place 0",
            ),
            (
                3,
                "Places 1 and 2 are leaves: nothing to sift. Sift down the only inner node, the root, place 0",
            ),
            (
                4,
                "Places 2 and 3 are leaves: nothing to sift. Sift down the inner nodes from place 1 back to the root, "
                "place 0",
            ),
            (
                5,
                "Places 2 to 4 are leaves: nothing to sift. Sift down the inner nodes from place 1 back to the root, "
                "place 0",
            ),
            (
                7,
                "Places 3 to 6 are leaves: nothing to sift. Sift down the inner nodes from place 2 back to the root, "
                "place 0",
            ),
        )
        for size, expected in cases:
            with self.subTest(size=size):
                self.assertEqual(expected, bulkload_order_caption(size))

    def test_order_follows_the_start_of_every_bulk_load(self) -> None:
        """On random inputs, with and without equal values, M from 1 to 12 and n from 1 to 60, every bulk load of at
        least two elements shows its order right after its start: the caption of ``bulkload_order_caption`` for its
        size, the start's inner nodes and heap, no marks, no compared pair and no comparison of an output step, as a
        step of heap maintenance, which is left out without the steps. A bulk load of one element has no inner node
        and no order: the half order follows its start. After the order, the sifts start at every inner node, from the
        last one back to the root, each with "Sift down … from place p", until the half order ends the bulk load.

        Would fail if the order came after the first sift or not at all, if a bulk load of one element showed an order
        with no inner node to sift, if the order marked places or showed another heap than the start, if it were kept
        with the steps of heap maintenance left out, or if a bulk load skipped an inner node (one whose element stays
        moves nothing) or sifted the inner nodes in another order.
        """
        sift_start: re.Pattern[str] = re.compile(r"Sift down \S+ from place (\d+): ")
        generator: random.Random = random.Random(3110)
        counted: dict[str, int] = {"with an order": 0, "of one element": 0}
        for attempt in range(240):
            memory: int = 1 + attempt % 12
            input_values: list[int] = random_values(
                generator, generator.randint(1, MAX_VALUES), attempt % 2 == 1
            )
            with self.subTest(values=input_values, memory=memory):
                frames: list[Frame] = trace(input_values, memory)
                kept_positions: list[int] = without_maintenance_steps(frames)[1]
                for position, frame in enumerate(frames):
                    if not frame.caption.startswith("Bulkload a heap from the list"):
                        continue
                    following: Frame = frames[position + 1]
                    where: str = f"frame {position}: {frame.caption}"
                    if len(frame.heap) == 1:
                        self.assertEqual(HALF_ORDER, following.caption, where)
                        counted["of one element"] += 1
                        continue
                    self.assertEqual(
                        frozenset(range(len(frame.heap) // 2)), frame.inner, where
                    )
                    self.assertEqual(
                        (
                            bulkload_order_caption(len(frame.heap)),
                            frame.inner,
                            frame.heap,
                            frozenset(),
                            (),
                            None,
                            True,
                        ),
                        (
                            following.caption,
                            following.inner,
                            following.heap,
                            following.marks,
                            following.compared,
                            following.comparison,
                            following.maintenance,
                        ),
                        where,
                    )
                    self.assertNotIn(position + 1, kept_positions, where)
                    end: int = next(
                        later
                        for later in range(position + 2, len(frames))
                        if frames[later].caption == HALF_ORDER
                    )
                    self.assertEqual(
                        list(range(len(frame.heap) // 2 - 1, -1, -1)),
                        [
                            int(found.group(1))
                            for found in (
                                sift_start.match(sifted.caption)
                                for sifted in frames[position + 2 : end]
                            )
                            if found
                        ],
                        where,
                    )
                    counted["with an order"] += 1
        # the inputs lead to many bulk loads of both kinds, so the checks above ran:
        self.assertGreater(min(counted.values()), 100, counted)

    def test_bulk_load_compares_at_most_2n_times(self) -> None:
        """A bulk load of n elements shows at most 2n frames that compare two places, as the notebook says: on
        reversed inputs of 60 values with M from 3 to 12, whose bulk load of run 0 makes every sift sink as deep as it
        can (the lists of the later runs, newest first, are sorted and so heaps already), and on random inputs.

        By hand: an inner node at height h sinks at most h levels, with at most two comparisons per level (its two
        children, then the element with the smaller one), and the heights of the inner nodes of a heap of n elements
        sum to less than n.

        Would fail if a bulk load showed far more comparisons than sift_down makes, e.g. each one twice; a single
        extra comparison stays under the bound and is caught by test_sifts_compare_before_every_swap.
        """
        generator: random.Random = random.Random(2468)
        cases: list[tuple[tuple[int, ...], int]] = [
            (preset_values(REVERSED, MAX_VALUES, memory), memory)
            for memory in range(3, 13)
        ]
        for attempt in range(120):
            cases.append(
                (
                    tuple(
                        random_values(
                            generator,
                            generator.randint(1, MAX_VALUES),
                            attempt % 2 == 1,
                        )
                    ),
                    1 + attempt % 12,
                )
            )
        bulk_loads: int = 0
        for input_values, memory in cases:
            with self.subTest(values=input_values, memory=memory):
                frames: list[Frame] = trace(input_values, memory)
                for position, frame in enumerate(frames):
                    if not frame.caption.startswith("Bulkload a heap from the list"):
                        continue
                    end: int = half_order_after(frames, position)
                    comparisons: int = sum(
                        bool(step.compared) for step in frames[position + 1 : end]
                    )
                    self.assertLessEqual(
                        comparisons, 2 * len(frame.heap), f"frame {position}"
                    )
                    bulk_loads += 1
        # the inputs lead to many bulk loads, so the checks above ran:
        self.assertGreater(bulk_loads, 500)

    def test_maintenance_flags_exactly_the_steps(self) -> None:
        """On random inputs, with and without equal values, M from 1 to 12 and n from 0 to 60, a frame is flagged as a
        step of heap maintenance exactly if it shows the order of a bulk load, a comparison, a swap or the end of a
        sift at a leaf, in a bulk load or after an output; the start of a bulk load, the half order, the move of the
        list to the front and the frames of an output step outside its sift (the write, the draw, the move of the last
        element, the drawn element put into the freed place) are never flagged.

        Would fail if the sift after an output were not flagged, so that the checkbox left its steps in, if the start
        of a bulk load or a half order were flagged, so that leaving out the steps lost the frames that show the heap
        before and after, or if a write or a draw were flagged.
        """
        generator: random.Random = random.Random(1123)
        # the steps checked, per kind, in a bulk load and after an output:
        counted: dict[tuple[str, bool], int] = {
            (kind, in_bulk_load): 0
            for kind in ("comparison", "swap", "leaf")
            for in_bulk_load in (True, False)
        }
        for attempt in range(240):
            memory: int = 1 + attempt % 12
            input_values: list[int] = random_values(
                generator, generator.randint(0, MAX_VALUES), attempt % 2 == 1
            )
            with self.subTest(values=input_values, memory=memory):
                frames: list[Frame] = trace(input_values, memory)
                for position, frame in enumerate(frames):
                    kind: str | None = None
                    if frame.compared:
                        kind = "comparison"
                    elif SWAP in frame.caption:
                        kind = "swap"
                    elif LEAF in frame.caption:
                        kind = "leaf"
                    # the order: the frame after the start of a bulk load that is not its half order:
                    order: bool = (
                        position > 0
                        and frames[position - 1].caption.startswith(
                            "Bulkload a heap from the list"
                        )
                        and frame.caption != HALF_ORDER
                    )
                    self.assertEqual(
                        kind is not None or order,
                        frame.maintenance,
                        f"frame {position}: {frame.caption}",
                    )
                    if kind is not None:
                        counted[kind, bool(frame.inner)] += 1
        # the inputs lead to many steps of every kind, so the checks above ran:
        self.assertGreater(min(counted.values()), 300, counted)

    def test_half_order_ends_every_sift_after_an_output(self) -> None:
        """On the slides' example and on random inputs, with and without equal values, M from 1 to 12 and n from 1 to
        60, an output step whose heap holds at least two elements when the root sinks shows the steps of the sift
        after its other frames and then the half order, which is its last frame unless a drawn element still goes
        into the freed place, in one frame after it; an output step whose heap holds one element or none shows
        neither steps nor half order. In the slides' example, the outputs 10, 20, 25, 30, 16, 26 and 31 are followed by
        a sift, and 40, 73, 33 and 50 are not: after 40 and 33 the heap holds one element, after 73 and 50 none.

        Would fail if the half order were missing after the sift of an output or came before its end, if a step of
        the sift came before the draw or the move of the last element, if the drawn element went into the freed place
        before the sift, or if a heap of one element were followed by a sift or the half order.
        """
        generator: random.Random = random.Random(808)
        cases: list[tuple[list[int], int]] = [(list(SLIDES_VALUES), SLIDES_MEMORY)]
        for attempt in range(120):
            cases.append(
                (
                    random_values(
                        generator, generator.randint(1, MAX_VALUES), attempt % 2 == 1
                    ),
                    1 + attempt % 12,
                )
            )
        counted: dict[bool, int] = {True: 0, False: 0}
        for input_values, memory in cases:
            with self.subTest(values=input_values, memory=memory):
                frames: list[Frame] = trace(input_values, memory)
                # the values written by the output steps that sift:
                sifted: list[int] = []
                for position, frame in enumerate(frames):
                    if not frame.caption.startswith("Remove top element"):
                        continue
                    # the output step: up to the next output, the list moved to the front, the next bulk load or
                    # the end:
                    end: int = next(
                        later
                        for later in range(position + 1, len(frames))
                        if frames[later].caption.startswith(STEP_ENDS)
                    )
                    step: list[Frame] = frames[position:end]
                    # whether a drawn element goes into the freed place at the step's end, in one frame:
                    placed: int = int(FREED_PLACE in step[-1].caption)
                    # its frames before the sift, the last of which the root sinks in:
                    plain: int = (
                        sum(
                            not other.maintenance and other.caption != HALF_ORDER
                            for other in step
                        )
                        - placed
                    )
                    size: int = sum(
                        element is not None for element in step[plain - 1].heap
                    )
                    where: str = f"frame {position}: {frame.caption}"
                    if size >= 2:
                        self.assertEqual(
                            [False] * plain
                            + [True] * (len(step) - plain - 1 - placed)
                            + [False] * (1 + placed),
                            [other.maintenance for other in step],
                            where,
                        )
                        self.assertEqual(
                            HALF_ORDER, step[len(step) - 1 - placed].caption, where
                        )
                        self.assertGreater(len(step) - plain - 1 - placed, 0, where)
                        sifted.append(frame.output[-1].element.value)
                    else:
                        self.assertEqual(
                            [False] * len(step),
                            [other.maintenance for other in step],
                            where,
                        )
                        self.assertNotIn(
                            HALF_ORDER, [other.caption for other in step], where
                        )
                    counted[size >= 2] += 1
                if input_values == list(SLIDES_VALUES):
                    self.assertEqual([10, 20, 25, 30, 16, 26, 31], sifted)
        # the inputs lead to many output steps of both kinds, so the checks above ran:
        self.assertGreater(min(counted.values()), 500, counted)

    def test_one_element_heap_after_an_output_shows_no_sift(self) -> None:
        """A heap of one element after an output, the drawn element at the root or the heap's last element moved there,
        compares nothing: neither a step of a sift nor the half order follows, and the next output comes right after,
        or after the frame that puts the drawn element into the freed place.

        By hand, for 5 7 6 with M = 1: the list 5 is bulk-loaded without an inner node; 5 is written, 7 ≥ 5 takes the
        root's place, alone in the heap, and is written; 6 < 7 takes the heap's only place as the list's newest
        element, in one frame, and is bulk-loaded as run 1 and written. In the slides' example, after 40 is written
        and 33 goes to the list, 73 takes the root's place as the heap's only element, 33 goes into the freed place,
        and 73 is written next.

        Would fail if a heap of one element showed a sift or the half order, e.g. if every heap that is not empty were
        sifted after an output.
        """
        self.assertEqual(
            [
                "Start: M = 1 elements fit into main memory, heap and list together",
                "Load next 1 element from input sequence into the list",
                "Bulkload a heap from the list: new run 0 starts",
                HALF_ORDER,
                "Remove top element 5 from heap and write it to output run 0",
                "Draw next element 7 from input sequence: 7 ≥ 5, so it takes the root's place in the heap",
                "Remove top element 7 from heap and write it to output run 0",
                "Draw next element 6 from input sequence: 6 < 7, so it goes to the list, into the place the heap "
                "gives up",
                "Bulkload a heap from the list: new run 1 starts",
                HALF_ORDER,
                "Remove top element 6 from heap and write it to output run 1",
                "Continue… and end: 3 elements in 2 runs (2 1), on average 1.5 = 1.5 × M",
            ],
            [frame.caption for frame in trace([5, 7, 6], 1)],
        )
        # the slides' example: 73 alone at the root, 33 placed behind it, then 73 written:
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        written: int = find(frames, SLIDES_OUTPUTS[5])
        self.assertEqual(
            [
                (
                    "The heap gives up its last place, and its last element 73 takes the root's place",
                    [73],
                ),
                (
                    "33 goes into the freed place: the list's newest element, next to the heap",
                    [73],
                ),
            ],
            [
                (frame.caption, values(frame.heap))
                for frame in frames[written - 2 : written]
            ],
        )


class SwapTest(unittest.TestCase):
    """The swaps the playground shows, read off the heap arrays before and after a sift."""

    def test_every_swap_is_with_the_smaller_child(self) -> None:
        """On random inputs, with and without equal values and M from 1 to 12, every swap the frames show exchanges a
        parent with its smaller child, which is smaller than the parent's element and not larger than its sibling.

        Would fail if a swap were shown between places that are not parent and child, with the larger child, with a
        child equal to the moving element, or if the frame did not exchange the two elements.
        """
        generator: random.Random = random.Random(50)
        checked: int = 0
        for attempt in range(240):
            memory: int = 1 + attempt % 12
            input_values: list[int] = random_values(
                generator, generator.randint(1, MAX_VALUES), attempt % 2 == 1
            )
            with self.subTest(values=input_values, memory=memory):
                frames: list[Frame] = trace(input_values, memory)
                for before, after in zip(frames, frames[1:]):
                    if SWAP not in after.caption:
                        continue
                    # the two marked places are a parent and one of its children:
                    self.assertEqual({"memory"}, {mark.row for mark in after.marks})
                    parent, child = sorted(mark.place for mark in after.marks)
                    self.assertIn(child, (2 * parent + 1, 2 * parent + 2))
                    # the child is smaller than the moving element and not larger than its sibling:
                    moving: Element = at(before.heap, parent)
                    smaller: Element = at(before.heap, child)
                    self.assertLess(smaller.value, moving.value)
                    sibling: int = child + 1 if child % 2 == 1 else child - 1
                    if sibling < len(before.heap):
                        self.assertLessEqual(
                            smaller.value, at(before.heap, sibling).value
                        )
                    # the two elements change places, as the caption says:
                    self.assertIs(smaller, after.heap[parent])
                    self.assertIs(moving, after.heap[child])
                    self.assertEqual(f"{moving} {SWAP} {smaller}", after.caption)
                    checked += 1
        # the inputs lead to many swaps, so the checks above ran:
        self.assertGreater(checked, 1000)

    def test_sifts_compare_before_every_swap(self) -> None:
        """On random inputs, with and without equal values and M from 1 to 12, every frame that compares two places
        lies in a sift, of a bulk load or after an output, and compares either the two children of the sinking element
        or the sinking element with its smaller child, the latter right after the former where there are two
        children: if the child is smaller, the caption says so and the next frame swaps the two, else the caption says
        that the element stays and the sift ends. Every swap follows the comparison of its two places and is followed
        by the comparison one level lower or by the frame that says the element has reached a leaf.

        Would fail if a comparison named the larger child or the right one of two equal children, if a sift swapped
        without showing the comparison first, if the two children were not compared where there are two, if an element
        stayed although its smaller child was smaller, if a sift went on after its element stayed or ended without
        saying so after a swap, or if the sifts after an output showed no comparisons.
        """
        generator: random.Random = random.Random(51)
        # the frames checked, per kind: the comparison of two children, and of a sinking element with its smaller
        # child, in a bulk load and after an output:
        checked: dict[tuple[str, bool], int] = {
            (kind, in_bulk_load): 0
            for kind in ("children", "element and child")
            for in_bulk_load in (True, False)
        }
        for attempt in range(240):
            memory: int = 1 + attempt % 12
            input_values: list[int] = random_values(
                generator, generator.randint(1, MAX_VALUES), attempt % 2 == 1
            )
            with self.subTest(values=input_values, memory=memory):
                frames: list[Frame] = trace(input_values, memory)
                for position, frame in enumerate(frames):
                    if SWAP in frame.caption:
                        self.check_swap(frames, position)
                    if frame.compared:
                        kind: str = self.check_comparison(frames, position)
                        checked[kind, bool(frame.inner)] += 1
        # the inputs lead to many comparisons of every kind, so the checks above ran:
        self.assertGreater(min(checked.values()), 500, checked)

    def check_swap(self, frames: Sequence[Frame], position: int) -> None:
        """Checks a frame that swaps: it follows the comparison of its two places, and the next frame compares at the
        place the element sank to, or says that it has reached a leaf there.

        @param frames: the frames of a trace
        @param position: the position of the frame that swaps
        """
        frame: Frame = frames[position]
        where: str = f"frame {position}: {frame.caption}"
        parent, child = sorted(mark.place for mark in frame.marks)
        self.assertEqual((parent, child), frames[position - 1].compared, where)
        moving: Element = at(frame.heap, child)
        following: Frame = frames[position + 1]
        if 2 * child + 1 < len(frame.heap):
            # the sift goes on one level lower: with the two children there, or with the only one:
            self.assertEqual(
                (
                    (2 * child + 1, 2 * child + 2)
                    if 2 * child + 2 < len(frame.heap)
                    else (child, 2 * child + 1)
                ),
                following.compared,
                where,
            )
            self.assertTrue(
                following.caption.startswith(f"{moving} at place {child}: "), where
            )
        else:
            self.assertEqual(
                f"{moving} at place {child} {LEAF}", following.caption, where
            )
            self.assertEqual(memory_marks(child), following.marks, where)

    def check_comparison(self, frames: Sequence[Frame], position: int) -> str:
        """Checks a frame that compares two places: it lies in a sift, of a bulk load (with the inner nodes and no
        comparison of an output step) or after an output (with the comparison of its step), and compares either the
        two children of the sinking element, followed by the comparison of the element with the smaller one, or the
        sinking element with its smaller child, after the comparison of the two children where there are two; then, if
        the child is smaller, the caption says so and the next frame swaps the two, else the caption says that the
        element stays, and the next frame ends the heap maintenance or, in a bulk load, starts the next sift.

        @param frames: the frames of a trace
        @param position: the position of the frame that compares
        @return: what the frame compares: ``"children"`` or ``"element and child"``
        """
        frame: Frame = frames[position]
        where: str = f"frame {position}: {frame.caption}"
        # a frame of a bulk load shows the inner nodes and no comparison of an output step, one after an output the
        # comparison of its step:
        self.assertEqual(bool(frame.inner), frame.comparison is None, where)
        heap: list[Element] = [
            at(frame.heap, place) for place in range(len(frame.heap))
        ]
        # a pair, as the caller checked that something is compared:
        self.assertEqual(2, len(frame.compared), where)
        first, second = frame.compared[0], frame.compared[-1]
        # the start of the caption, which names the sinking element, and the rest:
        start, found = frame.caption.split(": ", 1)
        following: Frame = frames[position + 1]
        if first % 2 == 1 and second == first + 1:
            # the two children of the place above them; the smaller one is named, or, if they are equal, the left one
            # is taken:
            parent: int = (first - 1) // 2
            moving: Element = heap[parent]
            left, right = heap[first], heap[second]
            self.assertIn(
                start,
                (
                    f"Sift down {moving} from place {parent}",
                    f"{moving} at place {parent}",
                ),
                where,
            )
            outcome: str
            if right < left:
                outcome = f"{right} is smaller"
            elif left < right:
                outcome = f"{left} is smaller"
            else:
                outcome = "neither is smaller, so the sift takes the left one"
            self.assertEqual(
                f"its children are {left} and {right}; {outcome}", found, where
            )
            # the next frame compares the sinking element with the smaller child:
            chosen: int = second if right < left else first
            self.assertEqual((parent, chosen), following.compared, where)
            self.assertTrue(
                following.caption.startswith(
                    f"{moving} and its smaller child {heap[chosen]}: "
                ),
                where,
            )
            return "children"
        # the sinking element and its smaller child, after the comparison of its two children if it has two, else its
        # only child:
        parent, child = first, second
        self.assertEqual(child, smaller_child(heap, parent), where)
        moving, smaller = heap[parent], heap[child]
        decision: str
        if 2 * parent + 2 < len(heap):
            self.assertEqual(
                (2 * parent + 1, 2 * parent + 2), frames[position - 1].compared, where
            )
            self.assertEqual(f"{moving} and its smaller child {smaller}", start, where)
            decision = found
        else:
            self.assertIn(
                start,
                (
                    f"Sift down {moving} from place {parent}",
                    f"{moving} at place {parent}",
                ),
                where,
            )
            only: str = f"its only child is {smaller}; "
            self.assertTrue(found.startswith(only), where)
            decision = found.removeprefix(only)
        if smaller < moving:
            self.assertEqual(f"{smaller} < {moving}, so they swap", decision, where)
            self.assertEqual(f"{moving} {SWAP} {smaller}", following.caption, where)
            self.assertEqual(memory_marks(parent, child), following.marks, where)
        else:
            self.assertEqual(
                f"{smaller} ≥ {moving}, so {moving} stays", decision, where
            )
            # the sift ends: the heap maintains half order, or a bulk load sifts its next inner node:
            self.assertTrue(
                following.caption == HALF_ORDER
                or (bool(frame.inner) and following.caption.startswith("Sift down ")),
                where,
            )
        return "element and child"

    def test_sift_swaps_replays_sift_down(self) -> None:
        """On random heaps, with and without equal values, the swaps ``sift_swaps`` reads off a sift lead from the
        array before it to exactly the array ``sift_down`` made, top down along one path.

        Would fail if ``sift_swaps`` missed an edge of the path, listed the swaps bottom up, or matched elements by
        value, so that it mixed up equal values.
        """
        generator: random.Random = random.Random(7)
        stayed: int = 0
        moved: int = 0
        for attempt in range(300):
            size: int = generator.randint(1, 20)
            repeats: bool = attempt % 2 == 1
            # a heap with a new element at a random place, whose subtrees are heaps:
            heap: list[Element] = [
                Element(value, index)
                for index, value in enumerate(random_values(generator, size, repeats))
            ]
            bulkload(heap)
            position: int = generator.randrange(size)
            heap[position] = Element(random_values(generator, 1, repeats)[0], size)
            before: list[Element] = list(heap)
            sift_down(heap, position)
            swaps: list[tuple[int, int]] = sift_swaps(before, heap, position)
            with self.subTest(before=values(before), position=position):
                # the swaps go top down from the sifted place, each from a parent to one of its children:
                children: list[int] = [child for _, child in swaps]
                self.assertEqual(
                    [position, *children][: len(swaps)], [parent for parent, _ in swaps]
                )
                for parent, child in swaps:
                    self.assertIn(child, (2 * parent + 1, 2 * parent + 2))
                # replayed on the array before, they give the very elements sift_down left in every place:
                replayed: list[Element] = list(before)
                for parent, child in swaps:
                    replayed[parent], replayed[child] = (
                        replayed[child],
                        replayed[parent],
                    )
                self.assertEqual(
                    [id(element) for element in heap],
                    [id(element) for element in replayed],
                )
            if swaps:
                moved += 1
            else:
                stayed += 1
        # both kinds of sift were checked:
        self.assertGreater(stayed, 10)
        self.assertGreater(moved, 10)


class InvariantTest(unittest.TestCase):
    """What holds in every frame of every trace."""

    def test_every_frame_keeps_the_elements(self) -> None:
        """On random inputs, with and without equal values, M from 1 to 12 and n from 0 to 60, every frame shows
        memory with exactly M places and a heap of at most M places, and holds every element exactly once in memory,
        the output or the input not yet taken, but for a drawn element smaller than the last output, which waits in
        the comparison box only from its draw until it goes into the freed place; within the heap only the root's
        place may be empty; the input is taken and the output written, never given back.

        In the slides' example the drawn element waits in 15 frames: for 16 the draw, 73 moved to the root, the 4
        steps of its sift and the half order (7); for 26 the draw, 73 moved up, 3 steps and the half order (6); for
        33 the draw and 73 moved up (2); 50 takes the heap's only place in its draw.

        Would fail if a frame showed an element in two places (e.g. the heap's last element both at the root and at
        its old place), lost one, or kept the drawn element out of memory after the step, if memory had another number
        of places than M, if a place of the heap other than the root were empty, or if a frame took back an output or
        an element of the input.
        """
        generator: random.Random = random.Random(2026)
        cases: list[tuple[list[int], int]] = [(list(SLIDES_VALUES), SLIDES_MEMORY)]
        for attempt in range(240):
            cases.append(
                (
                    random_values(
                        generator, generator.randint(0, MAX_VALUES), attempt % 2 == 1
                    ),
                    1 + attempt % 12,
                )
            )
        waiting_frames: int = 0
        for input_values, memory in cases:
            with self.subTest(values=input_values, memory=memory):
                tracer: Tracer = Tracer(input_values, memory)
                frames: list[Frame] = tracer.trace()
                every: list[int] = sorted(id(element) for element in tracer.elements)
                waiting: int = 0
                for position, frame in enumerate(frames):
                    where: str = f"frame {position}: {frame.caption}"
                    # M places, the heap at most all of them:
                    self.assertEqual(memory, len(frame.memory), where)
                    self.assertLessEqual(frame.heap_size, memory, where)
                    # every element in exactly one place, by identity, but a drawn element that waits for its place:
                    waiting += self.check_elements(tracer, frame, every, where)
                    # within the heap, only the root's place may be empty:
                    self.assertIn(
                        [
                            place
                            for place, element in enumerate(frame.heap)
                            if element is None
                        ],
                        ([], [0]),
                        where,
                    )
                    # the input is only taken and the output only grows:
                    if position > 0:
                        before: Frame = frames[position - 1]
                        self.assertGreaterEqual(frame.taken, before.taken, where)
                        self.assertEqual(
                            before.output, frame.output[: len(before.output)], where
                        )
                if input_values == list(SLIDES_VALUES):
                    self.assertEqual(15, waiting)
                waiting_frames += waiting
        # the inputs lead to many frames with a waiting element, so the checks above ran:
        self.assertGreater(waiting_frames, 1000)

    def check_elements(
        self, tracer: Tracer, frame: Frame, every: list[int], where: str
    ) -> bool:
        """Checks that a frame holds every element of the input exactly once, by identity, in memory, the output or
        the input not yet taken, but for a drawn element smaller than the last output, which may wait in the
        comparison box only.

        @param tracer: the tracer that recorded the frame, with the elements of the input
        @param frame: the frame
        @param every: the identities of all elements of the input, sorted
        @param where: the frame's name for the messages
        @return: whether the drawn element waits in the comparison box in this frame
        """
        held: list[Element] = [
            *(element for element in frame.memory if element is not None),
            *(written.element for written in frame.output),
            *tracer.elements[frame.taken :],
        ]
        missing: list[int] = sorted(set(every) - set(map(id, held)))
        if missing:
            comparison: Comparison | None = frame.comparison
            assert comparison is not None and comparison.drawn is not None, where
            self.assertEqual(
                ([id(comparison.drawn)], False),
                (missing, comparison.into_heap),
                where,
            )
        self.assertEqual(every, sorted([*map(id, held), *missing]), where)
        return bool(missing)

    def test_every_frame_has_the_comparison_of_its_step(self) -> None:
        """On random inputs, with and without equal values, M from 1 to 12 and n from 0 to 60, every frame of an output
        step, from the frame that writes the root to the last frame before the next output, bulk load or move of the
        list to the front, has the comparison of that step: the element written and the next element of the input,
        none once the input is empty; the end has the last output and no next element; the start, the load, the move
        of the list and every frame of a bulk load have no comparison. The frame that writes marks the element
        written, the empty root and the next element of the input. The draw takes exactly that element: into the heap
        at the root if the comparison says so; into the heap's only place, as the list's newest element, if the root
        was the heap's only element; else not yet into memory, until a later frame of the step puts it into the place
        the heap gave up, right behind the heap. Each of these marks only the element's new place, and the draw that
        leaves it out of memory marks nothing.

        Would fail if the comparison were recorded only in the frame that draws, if a bulk load kept the comparison
        of the step before it, if the next element were taken from the wrong place of the input or named once the
        input is empty, if the draw went against the comparison, if the drawn element went into memory before the
        heap gave up its last place or into another place than the one behind the heap, or if the draw still marked
        a cell of the input.
        """
        generator: random.Random = random.Random(4711)
        # the frames checked, per kind:
        counted: dict[str, int] = {"heap": 0, "only place": 0, "waits": 0, "placed": 0}
        for attempt in range(240):
            memory: int = 1 + attempt % 12
            input_values: list[int] = random_values(
                generator, generator.randint(0, MAX_VALUES), attempt % 2 == 1
            )
            with self.subTest(values=input_values, memory=memory):
                tracer: Tracer = Tracer(input_values, memory)
                frames: list[Frame] = tracer.trace()
                # the comparison the frames show, as (next element of the input, element written), from one output
                # or bulk load to the next, and the drawn element that waits for its place, if any:
                expected: tuple[Element | None, Element] | None = None
                waiting: Element | None = None
                for position, frame in enumerate(frames):
                    if frame.caption.startswith("Remove top element"):
                        self.assertIsNone(waiting, f"frame {position}")
                        expected = self.check_write(tracer, frames, position)
                    elif frame.caption.startswith(
                        (LIST_TO_FRONT, "Bulkload a heap from the list")
                    ):
                        self.assertIsNone(waiting, f"frame {position}")
                        expected = None
                    elif frame.caption.startswith("Continue… and end"):
                        expected = (None, frame.output[-1].element)
                    elif frame.caption.startswith("Draw next element"):
                        kind: str = self.check_draw(frames[position - 1], frame)
                        counted[kind] += 1
                        if kind == "waits":
                            waiting = (
                                frame.comparison.drawn if frame.comparison else None
                            )
                    elif FREED_PLACE in frame.caption:
                        self.check_placed(frames[position - 1], frame, waiting)
                        counted["placed"] += 1
                        waiting = None
                    # the comparison of the step, element by element (elements are equal only if they are the same):
                    shown: Comparison | None = frame.comparison
                    self.assertEqual(
                        expected,
                        None if shown is None else (shown.drawn, shown.last),
                        f"frame {position}: {frame.caption}",
                    )
        # the inputs lead to many draws of every kind, so the checks above ran:
        self.assertGreater(min(counted.values()), 300, counted)
        self.assertEqual(counted["waits"], counted["placed"])

    def check_write(
        self, tracer: Tracer, frames: Sequence[Frame], position: int
    ) -> tuple[Element | None, Element]:
        """Checks a frame that writes the root: the element written is the root of the frame before, and the frame
        marks it in the output, the empty root and the next element of the input, if there is one.

        @param tracer: the tracer that recorded the frames, with the elements of the input
        @param frames: the frames
        @param position: the position of the frame that writes
        @return: the comparison of the output step the frame starts, as (next element of the input, element written)
        """
        frame: Frame = frames[position]
        where: str = f"frame {position}: {frame.caption}"
        written: Element = frame.output[-1].element
        self.assertIs(at(frames[position - 1].heap, 0), written, where)
        upcoming: Element | None = (
            tracer.elements[frame.taken] if frame.taken < len(tracer.elements) else None
        )
        marks: set[Mark] = {Mark("output", len(frame.output) - 1), Mark("memory", 0)}
        if upcoming is not None:
            marks.add(Mark("input", frame.taken))
        self.assertEqual(frozenset(marks), frame.marks, where)
        return upcoming, written

    def check_draw(self, before: Frame, frame: Frame) -> str:
        """Checks a frame that draws: it takes the next element of the input, the one its comparison names, into the
        heap's root if the comparison says so; else, if the heap had one place, into that place, which becomes the
        list's newest; else nowhere yet, without changing memory. It marks only the element's new place, if any.

        @param before: the frame before it, which writes the root
        @param frame: the frame that draws
        @return: where the element went: ``"heap"``, ``"only place"`` or ``"waits"``
        """
        comparison: Comparison | None = frame.comparison
        assert comparison is not None and comparison.drawn is not None, frame.caption
        self.assertEqual(before.taken + 1, frame.taken, frame.caption)
        self.assertEqual(
            not comparison.drawn.value < comparison.last.value,
            comparison.into_heap,
            frame.caption,
        )
        if comparison.into_heap:
            # at the root, the heap's size unchanged:
            self.assertIs(comparison.drawn, frame.memory[0], frame.caption)
            self.assertEqual(before.heap_size, frame.heap_size, frame.caption)
            self.assertEqual(memory_marks(0), frame.marks, frame.caption)
            return "heap"
        if before.heap_size == 1:
            # the heap's only place, now the list's newest element:
            self.assertIs(comparison.drawn, frame.memory[0], frame.caption)
            self.assertEqual(0, frame.heap_size, frame.caption)
            self.assertEqual(memory_marks(0), frame.marks, frame.caption)
            return "only place"
        # nothing in memory changes yet:
        self.assertNotIn(comparison.drawn, frame.memory, frame.caption)
        self.assertEqual(
            (before.memory, before.heap_size, frozenset()),
            (frame.memory, frame.heap_size, frame.marks),
            frame.caption,
        )
        return "waits"

    def check_placed(
        self, before: Frame, frame: Frame, waiting: Element | None
    ) -> None:
        """Checks a frame that puts the drawn element, which waited, into the freed place: the place right behind the
        heap, which was empty in the frame before; the frame marks only that place, and nothing else changes.

        @param before: the frame before it, the half order of the sift or the frame in which the heap gave up its last
            place
        @param frame: the frame that puts the element
        @param waiting: the drawn element that waited for its place
        """
        assert waiting is not None, frame.caption
        place: int = frame.heap_size
        self.assertEqual(
            (
                f"{waiting} {FREED_PLACE}: the list's newest element, next to the heap",
                None,
                before.heap_size,
                memory_marks(place),
            ),
            (frame.caption, before.memory[place], frame.heap_size, frame.marks),
        )
        self.assertIs(waiting, frame.memory[place], frame.caption)
        self.assertEqual(
            before.memory[:place] + before.memory[place + 1 :],
            frame.memory[:place] + frame.memory[place + 1 :],
            frame.caption,
        )

    def test_every_run_starts_in_place(self) -> None:
        """On random inputs, with and without equal values, M from 1 to 12 and n from 0 to 60, exactly one frame per
        run starts it: "Bulkload a heap from the list: new run k starts", for k = 0, 1, … in order. It shows memory
        as the frame before it, element by element, takes the list's places as the heap's (the list's elements, in
        their order, become the heap's array), and leaves no list. The list's elements stand at the front of memory
        then: if they did not, because outputs after the end of the input left empty places before them, exactly one
        frame right before moves them there, in their memory order, closing the empty places, and marks every place
        that changed; no frame moves the list otherwise.

        Would fail if a run started with a heap other than the list's elements in their order, if the list moved in
        the same frame as the run started, if the list were moved to the front where it stands there already or not
        moved where it does not, or if the move changed the list's order.
        """
        generator: random.Random = random.Random(1508)
        counted: dict[str, int] = {"starts": 0, "moves": 0}
        for attempt in range(240):
            memory: int = 1 + attempt % 12
            input_values: list[int] = random_values(
                generator, generator.randint(0, MAX_VALUES), attempt % 2 == 1
            )
            with self.subTest(values=input_values, memory=memory):
                frames: list[Frame] = trace(input_values, memory)
                starts: list[int] = [
                    position
                    for position, frame in enumerate(frames)
                    if frame.caption.startswith("Bulkload a heap from the list")
                ]
                self.assertEqual(
                    [
                        f"Bulkload a heap from the list: new run {run} starts"
                        for run in range(len(run_lengths(frames[-1].output)))
                    ],
                    [frames[position].caption for position in starts],
                )
                moves: list[int] = [
                    position
                    for position, frame in enumerate(frames)
                    if frame.caption == LIST_TO_FRONT
                ]
                for position in starts:
                    before: Frame = frames[position - 1]
                    frame: Frame = frames[position]
                    size: int = len(before.pending)
                    # in place: the same memory, the list's elements at its front become the heap:
                    self.assertEqual(
                        (before.memory, before.pending, size, ()),
                        (frame.memory, frame.heap, frame.heap_size, frame.pending),
                        f"frame {position}",
                    )
                    if position - 1 not in moves:
                        continue
                    # the frame before moved the list to the front, from where the frame before it, the last
                    # output, held it behind a heap with no element left (its root's place empty):
                    held: Frame = frames[position - 2]
                    self.assertEqual(
                        ((None,) * held.heap_size, held.pending),
                        (held.heap, before.pending),
                        f"frame {position - 1}",
                    )
                    self.assertNotEqual(
                        held.pending, held.memory[:size], f"frame {position - 1}"
                    )
                    self.assertEqual(
                        frozenset(
                            Mark("memory", place)
                            for place, (old, new) in enumerate(
                                zip(held.memory, before.memory)
                            )
                            if old is not new
                        ),
                        before.marks,
                        f"frame {position - 1}",
                    )
                # a move only right before a start, and only where the list did not stand at the front:
                self.assertEqual(
                    moves,
                    [
                        position - 1
                        for position in starts
                        if frames[position - 1].caption == LIST_TO_FRONT
                    ],
                )
                for position in starts:
                    if position - 1 not in moves:
                        before = frames[position - 1]
                        self.assertEqual(
                            before.pending,
                            before.memory[: len(before.pending)],
                            f"frame {position}",
                        )
                counted["starts"] += len(starts)
                counted["moves"] += len(moves)
        # the inputs start many runs, some of them after a move, so the checks above ran:
        self.assertGreater(counted["starts"], 500, counted)
        self.assertGreater(counted["moves"], 50, counted)


class ReplayTest(unittest.TestCase):
    """The check that the playground shows the iterator's state."""

    def test_another_bulk_load_of_the_iterator_is_detected(self) -> None:
        """If the iterator bulk-loads another heap than the one the playground replays, ``trace`` raises
        ``ReplayError``.

        For 3 1 2, Floyd's method gives 1 3 2 (3 swaps with its smaller child 1), sorting gives 1 2 3, which is a heap
        as well.

        Would fail if the playground showed its own replay without comparing it with the iterator's heap.
        """

        def sort_in_place(elements: list[Element], size: int | None = None) -> None:
            """Sorts the first ``size`` elements in place, a bulk load that builds another heap than Floyd's method."""
            elements[:size] = sorted(cast(list[Element], elements[:size]))

        # without the patch, the bulk load gives Floyd's heap:
        frames: list[Frame] = trace([3, 1, 2], 3)
        end: int = half_order_after(
            frames, find(frames, "Bulkload a heap from the list: new run 0 starts")
        )
        self.assertEqual([1, 3, 2], values(frames[end].heap))
        # with the iterator sorting the list instead:
        with mock.patch("system.query_processing.sorting.bulkload", sort_in_place):
            with self.assertRaisesRegex(
                ReplayError,
                re.escape(
                    "bulk-loaded memory [1, 3, 2] differs from the iterator's [1, 2, 3]"
                ),
            ):
                trace([3, 1, 2], 3)

    def test_sift_swaps_rejects_another_heap(self) -> None:
        """``sift_swaps`` raises ``ReplayError`` if the heap after the sift has another length, or holds the sifted
        element not at all or twice.

        Would fail if ``sift_swaps`` read the swaps off an array that cannot come from the sift, e.g. one where an
        element was dropped, which would show swaps that never happened.
        """
        forty, ten, twenty = Element(40, 0), Element(10, 1), Element(20, 2)
        before: list[Element] = [forty, ten, twenty]
        cases: tuple[tuple[str, list[Element], str], ...] = (
            ("shorter", [ten, forty], "[10, 40] is not the heap [40, 10, 20]"),
            (
                "sifted element missing",
                [ten, twenty, Element(40, 3)],
                "[10, 20, 40] is not the heap [40, 10, 20]",
            ),
            (
                "sifted element twice",
                [ten, forty, forty],
                "[10, 40, 40] is not the heap [40, 10, 20]",
            ),
        )
        for name, after, message in cases:
            with self.subTest(name):
                with self.assertRaisesRegex(
                    ReplayError, re.escape(message + " after a sift")
                ):
                    sift_swaps(before, after, 0)

    def test_sift_swaps_rejects_a_move_off_the_path(self) -> None:
        """``sift_swaps`` raises ``ReplayError`` if the sifted element ends above its place or beside it, on no path
        down from it.

        Would fail if ``sift_swaps`` walked up from the end without checking that it reaches the sifted place, so
        that it showed a sift down for an element that moved up or sideways.
        """
        ten, forty, twenty, thirty = (
            Element(10, 0),
            Element(40, 1),
            Element(20, 2),
            Element(30, 3),
        )
        before: list[Element] = [ten, forty, twenty, thirty]
        cases: tuple[tuple[str, list[Element], int], ...] = (
            ("above", [forty, ten, twenty, thirty], 0),
            ("beside", [ten, twenty, forty, thirty], 2),
        )
        for name, after, end in cases:
            with self.subTest(name):
                with self.assertRaisesRegex(
                    ReplayError,
                    rf"40 did not move down from place 1, it ended at place {end}\.",
                ):
                    sift_swaps(before, after, 1)

    def test_sift_swaps_tells_equal_values_apart(self) -> None:
        """``sift_swaps`` raises ``ReplayError`` if the heap after the sift has the right values but two equal
        elements in each other's places.

        For 5 3 3 sifted from place 0, ``sift_down`` swaps 5 with the left 3 (the right one is not smaller); an array
        with the right 3 at the root and the left one in the last place has the same values, 3 5 3.

        Would fail if ``sift_swaps`` compared the replayed array with the one after by value, so that the playground
        showed one 3 where the iterator holds the other.
        """
        five, left, right = Element(5, 0), Element(3, 1), Element(3, 2)
        # the sift moves the left 3 up:
        self.assertEqual(
            [(0, 1)], sift_swaps([five, left, right], [left, five, right], 0)
        )
        # the same values with the two 3s swapped:
        with self.assertRaisesRegex(
            ReplayError,
            re.escape(
                "The playground's heap after the swaps [3, 5, 3] differs from the iterator's [3, 5, 3]."
            ),
        ):
            sift_swaps([five, left, right], [right, five, left], 0)

    def test_list_emptied_at_the_end_is_detected(self) -> None:
        """When the iterator's heap is empty, the list the playground shows must be the iterator's, before the trace
        takes the empty list for the end: a list emptied in the iterator alone ends the trace with ``ReplayError``.

        By hand, for 5 1 with M = 1: 5 is written, 1 is drawn and takes the heap's only place as the list's newest
        element (1 < 5), and the heap is empty. The iterator's list is then emptied, so that the iterator has nothing
        left, while the playground still shows 1 in its list.

        Would fail if the trace ended without comparing the playground's memory with the iterator's.
        """
        # after the first output, the iterator's list is emptied:
        tracer: ChangingTracer = ChangingTracer(
            1, clear_list, input_values=(5, 1), memory=1
        )
        with self.assertRaisesRegex(
            ReplayError,
            re.escape("The playground's memory [1] differs from the iterator's [_]."),
        ):
            tracer.trace()
        # the last frame shows 1 in the list, after the step that drew it:
        self.assertEqual([1], [element.value for element in tracer.frames[-1].pending])

    def test_changed_memory_is_detected(self) -> None:
        """If the iterator's memory changes between two steps, in any place, an empty one included, or in the size of
        its heap, the next step raises ``ReplayError``, naming what the playground shows and what the iterator holds;
        a heap emptied in the iterator alone is detected before the step takes it for the end or the start of the next
        run, and a list changed while the heap is empty before the next run starts.

        By hand, on the slides' example: after 10 is written, memory is 20 25 30 40, all heap; after 10, 20 and 25
        are written, 30 40 73 16 with a heap of three; after the six outputs of run 0, 50 33 26 16 with an empty heap,
        about to become the heap of run 1; after 16, 26 and 31 of run 1 (the input empty since 31 was drawn),
        33 50 _ _ with a heap of two.

        Would fail if a step drew on the iterator, or the next run bulk-loaded the list, without checking that the
        playground still shows the iterator's memory, if the check skipped the empty places, or if it compared the
        elements only and not the size of the heap.
        """
        # per case: the outputs after which the iterator is changed, the change, and the message:
        cases: tuple[
            tuple[int, Callable[[ReplacementSelection[Element]], None], str], ...
        ] = (
            (
                1,
                swap_last_two,
                "memory [20, 25, 30, 40] differs from the iterator's [20, 25, 40, 30]",
            ),
            (
                3,
                clear_list,
                "memory [30, 40, 73, 16] differs from the iterator's [30, 40, 73, _]",
            ),
            (
                1,
                clear_heap,
                "memory [20, 25, 30, 40] differs from the iterator's [_, _, _, _]",
            ),
            (
                3,
                clear_heap,
                "memory [30, 40, 73, 16] differs from the iterator's [_, _, _, 16]",
            ),
            (
                6,
                reverse_list,
                "memory [50, 33, 26, 16] differs from the iterator's [16, 26, 33, 50]",
            ),
            (
                9,
                fill_empty_place,
                "memory [33, 50, _, _] differs from the iterator's [33, 50, _, 99]",
            ),
            (1, shrink_heap, "heap size 4 differs from the iterator's 3"),
            (3, shrink_heap, "heap size 3 differs from the iterator's 2"),
        )
        for outputs, change, message in cases:
            with self.subTest(change=change.__name__, outputs=outputs):
                with self.assertRaisesRegex(
                    ReplayError, re.escape(f"The playground's {message}.")
                ):
                    ChangingTracer(outputs, change).trace()

    def test_changed_list_before_the_load_is_detected(self) -> None:
        """If the iterator's memory does not hold the first M elements in reading order, ``trace`` raises
        ``ReplayError`` before it records the load.

        Would fail if the playground showed the first M elements as loaded without checking that the iterator read
        exactly these, in this order, so that the frame of the load showed another list than the iterator's.
        """
        tracer: Tracer = Tracer(SLIDES_VALUES, SLIDES_MEMORY)
        # the iterator's memory holds the first four elements in reverse:
        reverse_list(tracer.selection)
        with self.assertRaisesRegex(
            ReplayError,
            re.escape(
                "The playground's memory [30, 20, 10, 40] differs from the iterator's [40, 10, 20, 30]."
            ),
        ):
            tracer.trace()
        # only the start was recorded, no load:
        self.assertEqual(
            ["Start: M = 4 elements fit into main memory, heap and list together"],
            [frame.caption for frame in tracer.frames],
        )

    def test_heap_after_the_swaps_is_checked(self) -> None:
        """If the swaps a step shows do not lead to the iterator's heap, that step raises ``ReplayError``: where the
        swaps read off the heap differ from those its comparisons lead to, in the sift; where the sift shows nothing
        at all, at the step's end.

        For 10 20 30 40 with M = 3, the bulk load of 10 20 30 swaps nothing; 10 is written, 40 ≥ 10 takes the root's
        place and the iterator sifts it down past 20 (20 40 30). With ``sift_swaps`` reading no swaps, the comparisons
        of the sift (20 < 40) still lead to the swap of places 0 and 1; with a sift that shows nothing, the playground
        still shows 40 20 30 at the step's end.

        Would fail if a sift showed swaps without checking them against its comparisons, or if a step ended without
        comparing its memory with the iterator's, so that swaps shown wrongly were noticed only at the start of the
        next step.
        """

        def show_nothing(*_: object) -> None:
            """Shows no frame of a sift and moves no element."""

        original: Callable[[Tracer], bool] = Tracer.step
        # per case: the function replaced, its replacement, and the message of the step that sifts 40:
        cases: tuple[tuple[str, object, str], ...] = (
            (
                "system.playground.replacement_selection_playground.sift_swaps",
                mock.Mock(return_value=[]),
                "The comparisons in the heap [40, 20, 30] lead to the swaps [(0, 1)], sift_down made [].",
            ),
            (
                "system.playground.replacement_selection_playground.Tracer.show_sift",
                show_nothing,
                "The playground's memory [40, 20, 30] differs from the iterator's [20, 40, 30].",
            ),
        )
        for target, replacement, message in cases:
            with self.subTest(replaced=target.rsplit(".", 1)[1]):
                with mock.patch(target, replacement):
                    with mock.patch.object(
                        Tracer, "step", autospec=True, side_effect=original
                    ) as step:
                        with self.assertRaisesRegex(ReplayError, re.escape(message)):
                            trace([10, 20, 30, 40], 3)
                # the first step raised, the one that sifted 40 down:
                self.assertEqual(1, step.call_count)

    def test_show_sift_checks_the_swaps_against_the_comparisons(self) -> None:
        """``Tracer.show_sift`` raises ``ReplayError`` if the swaps it is given differ from those its comparisons lead
        to, here none or the swap with the larger child; given the right swap, it shows the sift without an error.

        By hand, for the heap 40 10 20 sifted from place 0: of 40's children 10 and 20, 10 is smaller, and 10 < 40, so
        the comparisons lead to the swap of places 0 and 1, and 40 at place 1 has reached a leaf.

        Would fail if ``show_sift`` showed the swaps it is given without checking them against the heap it shows, so
        that its frames showed comparisons that contradict the swaps the iterator made.
        """
        forty, ten, twenty = Element(40, 0), Element(10, 1), Element(20, 2)
        for swaps in ([], [(0, 2)]):
            with self.subTest(swaps=swaps):
                # a tracer that shows the heap 40 10 20, all of memory:
                tracer: Tracer = Tracer([], 1)
                tracer.memory, tracer.heap_size = [forty, ten, twenty], 3
                with self.assertRaisesRegex(
                    ReplayError,
                    re.escape(
                        "The comparisons in the heap [40, 10, 20] lead to the swaps [(0, 1)], sift_down made "
                        f"{swaps}."
                    ),
                ):
                    tracer.show_sift([forty, ten, twenty], swaps, 0)
        # the swap the comparisons lead to is shown, frame by frame:
        tracer = Tracer([], 1)
        tracer.memory, tracer.heap_size = [forty, ten, twenty], 3
        tracer.show_sift([forty, ten, twenty], [(0, 1)], 0)
        self.assertEqual(
            [
                "Sift down 40 from place 0: its children are 10 and 20; 10 is smaller",
                "40 and its smaller child 10: 10 < 40, so they swap",
                "40 swaps with its smaller child 10",
                "40 at place 1 has reached a leaf",
            ],
            [frame.caption for frame in tracer.frames],
        )
        self.assertEqual([ten, forty, twenty], tracer.memory)

    def test_show_sift_checks_the_heap_shown(self) -> None:
        """``Tracer.show_sift`` raises ``ReplayError``, before it records a frame, if the heap the playground shows (the
        first ``heap_size`` places of its memory) is not the heap the sift starts from: the same elements in another
        order, an equal element in place of one, or one place more or less.

        Would fail if ``show_sift`` read its comparisons off the heap it is given without checking that the playground
        shows that heap, so that its frames compared elements that are not where the tree draws them, if it compared
        the two heaps by value, or if it took all of memory, or a heap of another size, for the heap.
        """
        forty, ten, twenty = Element(40, 0), Element(10, 1), Element(20, 2)
        # per case: the memory the playground shows and the size of its heap, while the sift starts from 40 10 20:
        cases: tuple[tuple[str, list[Element | None], int], ...] = (
            ("another order", [forty, twenty, ten], 3),
            ("an equal element", [forty, Element(10, 3), twenty], 3),
            ("a list behind it", [forty, ten, twenty, Element(5, 4)], 4),
            ("a place less", [forty, ten, twenty], 2),
        )
        for name, memory, heap_size in cases:
            with self.subTest(name):
                tracer: Tracer = Tracer([], 1)
                tracer.memory, tracer.heap_size = memory, heap_size
                shown: list[Element | None] = memory[:heap_size]
                with self.assertRaisesRegex(
                    ReplayError,
                    re.escape(
                        f"The playground's heap before the sift {values(shown)} differs from the iterator's "
                        "[40, 10, 20]."
                    ),
                ):
                    tracer.show_sift([forty, ten, twenty], [(0, 1)], 0)
                self.assertEqual([], tracer.frames)

    def test_output_other_than_the_root_is_detected(self) -> None:
        """If the iterator writes to another run than the current one, or writes an element that is not the root
        (here a copy of it with the same value and position), ``trace`` raises ``ReplayError``.

        Would fail if the playground took the iterator's output on trust, or matched it with the root by value.
        """

        # another run, after 10 was written:
        with self.assertRaisesRegex(
            ReplayError,
            re.escape("The iterator wrote 20 to run 1, not the root 20 to run 0."),
        ):
            ChangingTracer(1, count_on).trace()
        # a copy of the root:
        original: Callable[[ReplacementSelection[Element]], tuple[int, Element]] = (
            ReplacementSelection.__next__
        )

        def write_a_copy(
            selection: ReplacementSelection[Element],
        ) -> tuple[int, Element]:
            """Takes the next step, but returns a copy of the element written."""
            run, written = original(selection)
            return run, Element(written.value, written.index)

        with mock.patch.object(ReplacementSelection, "__next__", write_a_copy):
            with self.assertRaisesRegex(
                ReplayError,
                re.escape("The iterator wrote 10 to run 0, not the root 10 to run 0."),
            ):
                trace(SLIDES_VALUES, SLIDES_MEMORY)

    def test_run_not_started_is_detected(self) -> None:
        """If the iterator starts no run where the playground starts one, says it started none although it did, or
        numbers it differently, ``trace`` raises ``ReplayError``.

        Would fail if the playground counted the runs on its own without checking the iterator's run number, or
        ignored what ``start_next_run`` returns.
        """
        original: Callable[[ReplacementSelection[Element]], bool] = (
            ReplacementSelection.start_next_run
        )

        def skip_a_number(selection: ReplacementSelection[Element]) -> bool:
            """Starts the next run, but numbers it one too high."""
            started: bool = original(selection)
            count_on(selection)
            return started

        def deny_the_start(selection: ReplacementSelection[Element]) -> bool:
            """Starts the next run, bulk-loaded and numbered right, but returns False."""
            original(selection)
            return False

        # a run started and numbered right, but reported as not started:
        with mock.patch.object(ReplacementSelection, "start_next_run", deny_the_start):
            with self.assertRaisesRegex(
                ReplayError, re.escape("The iterator did not start run 0.")
            ):
                trace(SLIDES_VALUES, SLIDES_MEMORY)
        # no run started:
        with mock.patch.object(
            ReplacementSelection, "start_next_run", return_value=False
        ):
            with self.assertRaisesRegex(
                ReplayError, re.escape("The iterator did not start run 0.")
            ):
                trace(SLIDES_VALUES, SLIDES_MEMORY)
        # a run with another number:
        with mock.patch.object(ReplacementSelection, "start_next_run", skip_a_number):
            with self.assertRaisesRegex(
                ReplayError, re.escape("The iterator did not start run 0.")
            ):
                trace(SLIDES_VALUES, SLIDES_MEMORY)


class NextOutputTest(unittest.TestCase):
    """The position the button "next output" jumps to."""

    def test_jumps_of_the_slides_example(self) -> None:
        """In the slides' example, the jumps from the first frame go to the 11 frames that write an element, in
        order, and then to the last frame; from every frame the jump goes to the next frame that writes, or to the
        last frame, where it stays.

        Would fail if a jump stopped at a draw, a swap or a bulk load, skipped an output, or went past the last frame.
        """
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        last: int = len(frames) - 1
        outputs: list[int] = [
            position
            for position, frame in enumerate(frames)
            if frame.caption.startswith("Remove top element")
        ]
        self.assertEqual(11, len(outputs))
        # the jumps from the first frame; the loop also stops after more jumps than frames, should a jump not move
        # forward:
        visited: list[int] = []
        position: int = 0
        while position != last and len(visited) <= len(frames):
            position = next_output(frames, position)
            visited.append(position)
        self.assertEqual([*outputs, last], visited)
        # from every frame, to the next output or the last frame:
        for start in range(len(frames)):
            with self.subTest(start=start):
                expected: int = next(
                    (output for output in outputs if output > start), last
                )
                self.assertEqual(expected, next_output(frames, start))


class WithoutMaintenanceStepsTest(unittest.TestCase):
    """The frames the view shows with the checkbox "Heap maintenance step by step" off: every heap maintenance, a bulk
    load or the sift after an output, without its steps."""

    def setUp(self) -> None:
        """Traces the slides' example and leaves out the steps of its heap maintenance."""
        self.frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        self.kept: list[Frame]
        self.positions: list[int]
        self.kept, self.positions = without_maintenance_steps(self.frames)

    def test_slides_example(self) -> None:
        """Without the steps of heap maintenance, the slides' example has exactly 34 frames, in this order, at these
        positions among its 85 frames.

        By hand, the 51 frames left out are the steps of the two bulk loads, 6 in run 0 (its order; 20 stays; 30's
        children compared, 30 compared with 10, swapped, at a leaf) and 10 in run 1 (its order; 33 compared with its
        only child 16, swapped, at a leaf; 50's children compared, 50 compared with 16, swapped, compared with 33,
        swapped, at a leaf), and, for each of the seven sifts after an output, its steps and its half order: 4 + 1
        after 10 (children compared, 25 compared with 20, swapped, compared with 40, stays), 6 + 1 after 20 (children
        compared, 73 compared with 25, swapped, compared with 40, swapped, at a leaf), 4 + 1 after 25 (children
        compared, 73 compared with 30, swapped, at a leaf), 3 + 1 after 30 (73 compared with 40, swapped, at a leaf),
        4 + 1 after 16 (children compared, 31 compared with 26, swapped, at a leaf), 4 + 1 after 26 (children compared,
        50 compared with 31, swapped, at a leaf) and 3 + 1 after 31 (50 compared with 33, swapped, at a leaf). After
        the outputs 40, 73, 33 and 50 the heap holds at most one element, so nothing is sifted.
        6 + 10 + 5 + 7 + 5 + 4 + 5 + 5 + 4 = 51, and 85 − 51 = 34: a bulk load keeps its start and its half order, a
        sift after an output only the frame in which an element took the root's place, which shows the sift's result.

        Would fail if a step of heap maintenance or the half order after an output were kept, if the start of a bulk
        load, its half order or the frame before a sift were left out, if a frame of an output step outside its sift
        (the draw, or the drawn element put into the freed place) were left out as well, if a frame before a sift did
        not say that the element sifts down, or if a position named the frame before or after.
        """
        self.assertEqual(
            [
                "Start: M = 4 elements fit into main memory, heap and list together",
                "Load next 4 elements from input sequence into the list",
                "Bulkload a heap from the list: new run 0 starts",
                HALF_ORDER,
                "Remove top element 10 from heap and write it to output run 0",
                "Draw next element 25 from input sequence: 25 ≥ 10, so it takes the root's place in the heap"
                + SANK,
                "Remove top element 20 from heap and write it to output run 0",
                "Draw next element 73 from input sequence: 73 ≥ 20, so it takes the root's place in the heap"
                + SANK,
                "Remove top element 25 from heap and write it to output run 0",
                "Draw next element 16 from input sequence: 16 < 25, so it goes to the list, for the next run",
                "The heap gives up its last place, and its last element 73 takes the root's place"
                + SANK,
                "16 goes into the freed place: the list's newest element, next to the heap",
                "Remove top element 30 from heap and write it to output run 0",
                "Draw next element 26 from input sequence: 26 < 30, so it goes to the list, for the next run",
                "The heap gives up its last place, and its last element 73 takes the root's place"
                + SANK,
                "26 goes into the freed place: the list's newest element, next to the heap",
                "Remove top element 40 from heap and write it to output run 0",
                "Draw next element 33 from input sequence: 33 < 40, so it goes to the list, for the next run",
                "The heap gives up its last place, and its last element 73 takes the root's place",
                "33 goes into the freed place: the list's newest element, next to the heap",
                "Remove top element 73 from heap and write it to output run 0",
                "Draw next element 50 from input sequence: 50 < 73, so it goes to the list, into the place the heap "
                "gives up",
                "Bulkload a heap from the list: new run 1 starts",
                HALF_ORDER,
                "Remove top element 16 from heap and write it to output run 1",
                "Draw next element 31 from input sequence: 31 ≥ 16, so it takes the root's place in the heap"
                + SANK,
                "Remove top element 26 from heap and write it to output run 1",
                "R is empty: the heap gives up its last place, and its last element 50 takes the root's place"
                + SANK,
                "Remove top element 31 from heap and write it to output run 1",
                "R is empty: the heap gives up its last place, and its last element 50 takes the root's place"
                + SANK,
                "Remove top element 33 from heap and write it to output run 1",
                "R is empty: the heap gives up its last place, and its last element 50 takes the root's place",
                "Remove top element 50 from heap and write it to output run 1",
                "Continue… and end: 11 elements in 2 runs (6 5), on average 5.5 = 1.4 × M",
            ],
            [frame.caption for frame in self.kept],
        )
        # 34 of the 85 frames, at their positions in the full list:
        self.assertEqual((85, 34), (len(self.frames), len(self.kept)))
        self.assertEqual(
            [
                *(0, 1, 2, 9, 10, 11, 17, 18, 26, 27, 28, 34, 35, 36, 37, 42),
                *range(43, 50),
                *(60, 61, 62, 68, 69, 75, 76, 81, 82, 83, 84),
            ],
            self.positions,
        )

    def test_slides_bulk_loads_keep_their_start_and_their_heap(self) -> None:
        """Each bulk load of the slides' example keeps two frames. Its start shows memory as the frame before it, the
        list's four places taken as the heap's array, in order, without the dashes of the inner nodes and with its
        grey marks of all four places. Its finished heap marks the places whose element the bulk load moved: 0 and 2
        in run 0, where 30 and 10 swapped; 0 and 3 in run 1, where 50 went from place 0 to place 3 and 16 from place 3
        to place 0, while 33 moved down and back up to place 1. Apart from the dashes and the marks, both frames are
        those of the trace.

        Would fail if the start still showed the dashes of inner nodes that no step sifts, showed the heap after the
        bulk load or lost its marks; if the finished heap marked nothing, every place, every place a swap passed
        through or the places of another bulk load; or if any other field of either frame changed.
        """
        # per bulk load: its run, the place of its start among the frames kept, the list, the heap after it, and the
        # places marked on that heap:
        cases: tuple[tuple[int, int, list[int], list[int], frozenset[Mark]], ...] = (
            (0, 2, [30, 20, 10, 40], [10, 20, 30, 40], memory_marks(0, 2)),
            (1, 22, [50, 33, 26, 16], [16, 33, 26, 50], memory_marks(0, 3)),
        )
        for run, index, listed, heap, marks in cases:
            with self.subTest(run=run):
                start: Frame = self.kept[index]
                position: int = self.positions[index]
                self.assertEqual(
                    f"Bulkload a heap from the list: new run {run} starts",
                    start.caption,
                )
                # the start: memory of the frame before, its list's elements, in order, as the heap array:
                self.assertEqual(self.frames[position - 1].memory, start.memory)
                self.assertEqual(
                    list(self.frames[position - 1].pending), list(start.heap)
                )
                self.assertEqual(listed, values(start.heap))
                # no dashes, the grey marks of all four places, the rest as in the trace:
                self.assertEqual(
                    (frozenset(), memory_marks(0, 1, 2, 3)), (start.inner, start.marks)
                )
                self.assertEqual(
                    replace(self.frames[position], inner=frozenset()), start
                )
                # the finished heap, marked where an element moved, the rest as in the trace:
                finished: Frame = self.kept[index + 1]
                self.assertEqual(HALF_ORDER, finished.caption)
                self.assertEqual((heap, marks), (values(finished.heap), finished.marks))
                self.assertEqual(
                    replace(self.frames[self.positions[index + 1]], marks=marks),
                    finished,
                )

    def test_slides_sifts_after_an_output_show_their_result(self) -> None:
        """Without the steps of heap maintenance, each of the seven sifts after an output in the slides' example is
        shown by the frame in which an element took the root's place: its caption adds that the element sifts down, it
        shows memory after the sift (the half order's), and it adds to its own marks the places
        whose element the sift moved. Apart from these, it is the trace's frame; the half order is left out.

        By hand, per sift (marks of the frame itself + places the sift moved): 25 swaps with 20 (25 20 30 40 becomes
        20 25 30 40: {0} + {0, 1}); 73 swaps with 25 and with 40 (73 25 30 40 becomes 25 40 30 73: {0} + {0, 1, 3});
        73 swaps with 30 (73 40 30 _ becomes 30 40 73 _: {0, 3}, the root and the place given up, + {0, 2}); 73 swaps
        with 40 (73 40 _ 16 becomes 40 73 _ 16: {0, 2} + {0, 1}); 31 swaps with 26 (31 33 26 50 becomes 26 33 31 50:
        {0} + {0, 2}); 50 swaps with 31 (50 33 31 _ becomes 31 33 50 _: {0, 3} + {0, 2}); 50 swaps with 33 (50 33 _ _
        becomes 33 50 _ _: {0, 2} + {0, 1}).

        Would fail if the frame before the sift showed memory before the sift, kept its caption, lost its own marks,
        marked every place a swap passed through or none at all, or changed in any other field, or if the half order
        after an output were kept.
        """
        # per sift: the place of the frame among the frames kept, its caption in the trace, memory before and after
        # the sift and the places marked:
        cases: tuple[
            tuple[int, str, list[int | None], list[int | None], frozenset[Mark]], ...
        ] = (
            (
                5,
                "Draw next element 25 from input sequence: 25 ≥ 10, so it takes the root's place in the heap",
                [25, 20, 30, 40],
                [20, 25, 30, 40],
                memory_marks(0, 1),
            ),
            (
                7,
                "Draw next element 73 from input sequence: 73 ≥ 20, so it takes the root's place in the heap",
                [73, 25, 30, 40],
                [25, 40, 30, 73],
                memory_marks(0, 1, 3),
            ),
            (
                10,
                "The heap gives up its last place, and its last element 73 takes the root's place",
                [73, 40, 30, None],
                [30, 40, 73, None],
                memory_marks(0, 2, 3),
            ),
            (
                14,
                "The heap gives up its last place, and its last element 73 takes the root's place",
                [73, 40, None, 16],
                [40, 73, None, 16],
                memory_marks(0, 1, 2),
            ),
            (
                25,
                "Draw next element 31 from input sequence: 31 ≥ 16, so it takes the root's place in the heap",
                [31, 33, 26, 50],
                [26, 33, 31, 50],
                memory_marks(0, 2),
            ),
            (
                27,
                "R is empty: the heap gives up its last place, and its last element 50 takes the root's place",
                [50, 33, 31, None],
                [31, 33, 50, None],
                memory_marks(0, 2, 3),
            ),
            (
                29,
                "R is empty: the heap gives up its last place, and its last element 50 takes the root's place",
                [50, 33, None, None],
                [33, 50, None, None],
                memory_marks(0, 1, 2),
            ),
        )
        for index, caption, memory_before, memory_after, marks in cases:
            with self.subTest(caption=caption, memory=memory_before):
                shown: Frame = self.kept[index]
                position: int = self.positions[index]
                original: Frame = self.frames[position]
                half_order: int = half_order_after(self.frames, position)
                # the trace's frame before the sift, and the half order that ends it:
                self.assertEqual(
                    (caption, memory_before),
                    (original.caption, values(original.memory)),
                )
                self.assertEqual(memory_after, values(self.frames[half_order].memory))
                # the frame shown: the sift's result, marked, and the caption that says so; the rest as in the trace:
                self.assertEqual(
                    replace(
                        original,
                        caption=caption + SANK,
                        memory=self.frames[half_order].memory,
                        marks=marks,
                    ),
                    shown,
                )
                # the next frame kept follows the half order:
                self.assertEqual(half_order + 1, self.positions[index + 1])

    def test_marks_of_small_bulk_loads(self) -> None:
        """The finished heap of a bulk load of two, three or five elements marks exactly the places that hold another
        element than the list did, told apart by identity, not by value; the start shows the list without dashes.

        By hand:

        - 7 3 with M = 5: 7 swaps with its child 3, so 3 7 marks places 0 and 1;
        - 3 1 2 with M = 3: 3 swaps with its smaller child 1, so 1 3 2 marks places 0 and 1;
        - 1 2 3 with M = 3: 1 stays, so nothing is marked;
        - 9 8 20 1 30 with M = 5: 8 at place 1 swaps with 1; 9 swaps with 1 and then with 8, which is back at place
          1, so 1 8 20 9 30 marks places 0 and 3 only;
        - 9 5 7 5 8 with M = 5 (two 5s, the first at place 1, the second at place 3): the first 5 stays above the
          second; 9 swaps with the first 5 and then with the second, so 5 5 7 9 8 marks places 0, 1 and 3, as place 1
          now holds the second 5.

        The finished heap is frame 2 + 1 (order) + the steps of the sifts + 1: 7 3 has 3 (7 compared with its only
        child, swapped, at a leaf), 3 1 2 has 4 (children compared, 3 compared with 1, swapped, at a leaf), 1 2 3 has 2
        (children compared, 1 stays), 9 8 20 1 30 has 11 (4 for 8, as for 3 1 2; for 9: children compared, compared with
        1, swapped, children compared, compared with 8, swapped, at a leaf) and 9 5 7 5 8 has 9 (children compared and 5
        stays; then 7 for 9).

        Would fail if the marks compared values instead of elements (missing place 1 of the two 5s), if they marked
        every place a swap passed through (place 1 of 9 8 20 1 30) or no place at all, or if the steps of these bulk
        loads were not left out.
        """
        # per input: M, the positions of the start and of the finished heap in the full list, the list, the heap
        # after the bulk load and the places marked on it:
        cases: tuple[
            tuple[
                tuple[int, ...], int, list[int], list[int], list[int], frozenset[Mark]
            ],
            ...,
        ] = (
            ((7, 3), 5, [2, 7], [7, 3], [3, 7], memory_marks(0, 1)),
            ((3, 1, 2), 3, [2, 8], [3, 1, 2], [1, 3, 2], memory_marks(0, 1)),
            ((1, 2, 3), 3, [2, 6], [1, 2, 3], [1, 2, 3], frozenset()),
            (
                (9, 8, 20, 1, 30),
                5,
                [2, 15],
                [9, 8, 20, 1, 30],
                [1, 8, 20, 9, 30],
                memory_marks(0, 3),
            ),
            (
                (9, 5, 7, 5, 8),
                5,
                [2, 13],
                [9, 5, 7, 5, 8],
                [5, 5, 7, 9, 8],
                memory_marks(0, 1, 3),
            ),
        )
        for input_values, memory, positions, listed, heap, marks in cases:
            with self.subTest(values=input_values):
                kept, kept_positions = without_maintenance_steps(
                    trace(input_values, memory)
                )
                # the start and the finished heap follow each other, at these positions of the full list:
                self.assertEqual(positions, kept_positions[2:4])
                start, finished = kept[2], kept[3]
                self.assertEqual(
                    (listed, frozenset()), (values(start.heap), start.inner)
                )
                self.assertEqual((heap, marks), (values(finished.heap), finished.marks))
        # the two 5s: place 1 holds the second 5 (position 3 of the input) after the bulk load, the first one before:
        kept = without_maintenance_steps(trace((9, 5, 7, 5, 8), 5))[0]
        self.assertEqual((1, 3), (at(kept[2].heap, 1).index, at(kept[3].heap, 1).index))

    def test_marks_of_a_sift_after_an_output(self) -> None:
        """The frame that shows a sift after an output adds to its own mark, the root, exactly the places that hold
        another element after the sift than before it, told apart by identity: none where the sift moves nothing.

        By hand:

        - 5 5 3 5 1 5 with M = 3: after 3 is written, the third 5 takes the root's place and stays above the second 5,
          the left one of its two equal children, so the sift moves nothing (5 5 5 before and after): only the root is
          marked;
        - 1 5 7 5 8 9 with M = 5 (the bulk load moves nothing, so the first 5 stands at place 1, the second at place
          3): after 1 is written, 9 takes the root's place and swaps with the first 5, then with the second (9 5 7 5 8
          becomes 5 5 7 9 8), so places 0, 1 and 3 are marked, place 1 as it now holds the second 5.

        Would fail if a sift that moves nothing added a mark, or if the places were compared by value, which misses
        place 1 of the second input.
        """
        # per input: M, the caption of the frame before the sift, memory after the sift and the places marked:
        cases: tuple[
            tuple[tuple[int, ...], int, str, list[int], frozenset[Mark]], ...
        ] = (
            (
                (5, 5, 3, 5, 1, 5),
                3,
                "Draw next element 5 from input sequence: 5 ≥ 3, so it takes the root's place in the heap",
                [5, 5, 5],
                memory_marks(0),
            ),
            (
                (1, 5, 7, 5, 8, 9),
                5,
                "Draw next element 9 from input sequence: 9 ≥ 1, so it takes the root's place in the heap",
                [5, 5, 7, 9, 8],
                memory_marks(0, 1, 3),
            ),
        )
        for input_values, memory, caption, after, marks in cases:
            with self.subTest(values=input_values):
                frames: list[Frame] = trace(input_values, memory)
                kept: list[Frame] = without_maintenance_steps(frames)[0]
                shown: Frame = kept[
                    [frame.caption for frame in kept].index(caption + SANK)
                ]
                # memory after the sift and the marks; the frame is the trace's frame before the sift with memory of
                # the half order, element by element:
                self.assertEqual((after, marks), (values(shown.memory), shown.marks))
                before: int = find(frames, caption)
                self.assertEqual(
                    replace(
                        frames[before],
                        caption=caption + SANK,
                        memory=frames[half_order_after(frames, before)].memory,
                        marks=marks,
                    ),
                    shown,
                )

    def test_nothing_to_leave_out(self) -> None:
        """An input without a bulk load (the empty one) and an input whose only bulk load holds one element (5 with
        M = 3: a heap of one element has no inner node, so the bulk load sifts nothing, and writing 5 leaves no heap to
        sift) keep every frame, the same objects, each at its own position; the finished heap of 5 marks nothing.

        Would fail if a bulk load without inner nodes lost its start or its finished heap, or if a frame were copied
        or changed although nothing is left out.
        """
        cases: tuple[tuple[tuple[int, ...], list[str]], ...] = (
            (
                (),
                [
                    "Start: M = 3 elements fit into main memory, heap and list together",
                    "End: the input is empty, so no run is written",
                ],
            ),
            (
                (5,),
                [
                    "Start: M = 3 elements fit into main memory, heap and list together",
                    "Load next 1 element from input sequence into the list",
                    "Bulkload a heap from the list: new run 0 starts",
                    "Heap maintains half order: no child is smaller than its parent",
                    "Remove top element 5 from heap and write it to output run 0",
                    "Continue… and end: 1 element in 1 run (1), on average 1.0 = 0.3 × M",
                ],
            ),
        )
        for input_values, captions in cases:
            with self.subTest(values=input_values):
                frames: list[Frame] = trace(input_values, 3)
                kept, positions = without_maintenance_steps(frames)
                # every frame, the same object, at its own position:
                self.assertEqual(captions, [frame.caption for frame in kept])
                self.assertEqual(list(range(len(frames))), positions)
                for frame, original in zip(kept, frames):
                    self.assertIs(original, frame)
        # the finished heap of the one-element bulk load marks nothing:
        finished: Frame = without_maintenance_steps(trace((5,), 3))[0][3]
        self.assertEqual(([5], frozenset()), (values(finished.heap), finished.marks))

    def test_frames_outside_heap_maintenance_are_kept(self) -> None:
        """On the slides' example, the input that moves the list to the front and random inputs, with and without equal
        values, M from 1 to 12 and n from 0 to 60: the frames left out are exactly those between the frame before a
        heap maintenance (the start of a bulk load, or the frame in which an element took the root's place after an
        output) and its half order, which are exactly the frames flagged as steps of heap maintenance, and the half
        order after an output. Every other frame is kept as the same object, at its position in the full list, but for
        the start of a bulk load, which loses its dashes, the half order of a bulk load, marked where a place holds
        another element than at the start, and the frame before a sift after an output, which shows the sift's result
        as described in test_slides_sifts_after_an_output_show_their_result; no frame kept shows dashes or a compared
        pair.

        Would fail if a frame of an output step were left out or changed (e.g. the write, the draw or the drawn
        element put into the freed place taken for a step of heap maintenance), if the list moved to the front were
        left out, if the bulk load of a later run or the sift after an output kept its steps or its half order, if a
        frame were marked against another frame than the one before its heap maintenance, or if a position named
        another frame than the one kept, so that the view lost its place on a switch.
        """
        generator: random.Random = random.Random(2311)
        cases: list[tuple[list[int], int]] = [
            (list(SLIDES_VALUES), SLIDES_MEMORY),
            (list(SLIDES_VALUES[:8]), SLIDES_MEMORY),
        ]
        for attempt in range(120):
            cases.append(
                (
                    random_values(
                        generator, generator.randint(0, MAX_VALUES), attempt % 2 == 1
                    ),
                    1 + attempt % 12,
                )
            )
        for input_values, memory in cases:
            with self.subTest(values=input_values, memory=memory):
                frames: list[Frame] = trace(input_values, memory)
                kept, positions = without_maintenance_steps(frames)
                # the steps of heap maintenance, found by the captions of the frames before them and of the half
                # orders that end them, and per half order the frame before its heap maintenance:
                inside: list[int] = []
                before: dict[int, int] = {}
                start: int = 0
                for position, frame in enumerate(frames):
                    if frame.caption.startswith(BEFORE_MAINTENANCE):
                        start = position
                    elif frame.caption == HALF_ORDER:
                        inside += range(start + 1, position)
                        before[position] = start
                # they are the frames flagged as steps of heap maintenance:
                self.assertEqual(
                    inside,
                    [
                        position
                        for position, frame in enumerate(frames)
                        if frame.maintenance
                    ],
                )
                # the half orders after an output, each with the frame before its sift:
                after_output: dict[int, int] = {
                    position: start
                    for position, start in before.items()
                    if not frames[start].caption.startswith(
                        "Bulkload a heap from the list"
                    )
                }
                # exactly these are left out, the others kept in order, one position each:
                self.assertEqual(
                    [
                        position
                        for position in range(len(frames))
                        if position not in inside and position not in after_output
                    ],
                    positions,
                )
                self.assertEqual(len(positions), len(kept))
                # every frame kept is the trace's frame at its position, but for the frames described above:
                shows_sift: dict[int, int] = {
                    start: half_order for half_order, start in after_output.items()
                }
                for frame, position in zip(kept, positions):
                    original: Frame = frames[position]
                    where: str = f"frame {position}: {original.caption}"
                    if original.caption == HALF_ORDER:
                        # a bulk load's half order, marked against its start:
                        self.assertEqual(
                            replace(
                                original,
                                marks=changed_places(
                                    frames[before[position]], original
                                ),
                            ),
                            frame,
                            where,
                        )
                    elif original.caption.startswith("Bulkload a heap from the list"):
                        self.assertEqual(
                            replace(original, inner=frozenset()), frame, where
                        )
                    elif position in shows_sift:
                        finished: Frame = frames[shows_sift[position]]
                        self.assertEqual(
                            replace(
                                original,
                                caption=original.caption + SANK,
                                memory=finished.memory,
                                marks=original.marks
                                | changed_places(original, finished),
                            ),
                            frame,
                            where,
                        )
                    else:
                        self.assertIs(original, frame, where)
                # no dashes and no compared pair:
                self.assertEqual(
                    [(frozenset(), ())] * len(kept),
                    [(frame.inner, frame.compared) for frame in kept],
                )


class CaptionLengthTest(unittest.TestCase):
    """Every caption fits on one line, so that the view below it does not move from frame to frame."""

    def test_every_caption_fits_on_one_line(self) -> None:
        """No caption, with or without the steps of heap maintenance, has more than MAX_CAPTION_LENGTH characters: on
        the slides' example, every generated preset (n = 1, 24 and 60, three seeds each), the inputs of "Things to
        try", the empty input and inputs of three-digit values that repeat (so that a sift compares equal children),
        each with M from 3 to 12. The values of the presets have three digits mostly, and reversed input with n = 60
        and M = 3 ends with 20 runs, the longest list of run lengths. The inputs reach the longest caption of each kind
        that comes close to the limit: a three-digit element drawn into the list where the root was the heap's only
        element (110 characters); a three-digit element drawn into the heap's root, which then sifts down (109); the
        end with 20 runs (109); the heap's last element taking the root's place once the input is empty, then sifting
        down (108); two equal three-digit children (108); the order of a bulk load of 4, 11 or 12 elements (108).

        Would fail if a caption were longer, e.g. if the draw into the list where the root was the heap's only element
        added ", for the next run" (128 characters), or if the end separated its 20 run lengths with commas (128
        characters).
        """
        generator: random.Random = random.Random(2411)
        # the slides' example, the inputs of "Things to try" (equal values, the list moved to the front, the bulk load)
        # and the empty input:
        inputs: list[tuple[int, ...]] = [
            SLIDES_VALUES,
            (5, 5, 3, 5, 1, 5),
            SLIDES_VALUES[:8],
            (70, 60, 50, 40, 30, 20, 10),
            (),
        ]
        # every generated preset, with values of three digits mostly:
        for name in (RANDOM, SORTED, REVERSED, ALMOST_SORTED):
            for count in (1, 24, MAX_VALUES):
                for seed in range(3):
                    inputs.append(preset_values(name, count, seed))
        # three-digit values that repeat:
        for _ in range(5):
            inputs.append(
                tuple(generator.randint(995, MAX_VALUE) for _ in range(MAX_VALUES))
            )
        # the captions of every input with every M, with and without the steps of heap maintenance:
        captions: set[str] = set()
        for input_values in inputs:
            for memory in range(MIN_MEMORY, MAX_MEMORY + 1):
                frames: list[Frame] = trace(input_values, memory)
                captions.update(frame.caption for frame in frames)
                captions.update(
                    frame.caption for frame in without_maintenance_steps(frames)[0]
                )
        # none is too long:
        self.assertEqual(
            [],
            sorted(
                caption for caption in captions if len(caption) > MAX_CAPTION_LENGTH
            ),
        )
        # the longest caption of each kind that comes close to the limit, the kind found by a pattern:
        kinds: dict[str, re.Pattern[str]] = {
            "draw into the list, heap of one": re.compile(
                "^Draw next element .* into the place the heap gives up$"
            ),
            "draw into the heap, sift": re.compile(
                "^Draw next element .* and sifts down$"
            ),
            "end": re.compile("^Continue… and end"),
            "input empty, sift": re.compile("^R is empty: .* and sifts down$"),
            "equal children": re.compile("neither is smaller"),
            "order of a bulk load": re.compile("^Places .* are leaves"),
        }
        self.assertEqual(
            {
                "draw into the list, heap of one": MAX_CAPTION_LENGTH,
                "draw into the heap, sift": 109,
                "end": 109,
                "input empty, sift": 108,
                "equal children": 108,
                "order of a bulk load": 108,
            },
            {
                kind: max(
                    len(caption) for caption in captions if pattern.search(caption)
                )
                for kind, pattern in kinds.items()
            },
        )


class ParseValuesTest(unittest.TestCase):
    """Reading the input from the text field."""

    def test_spaces_and_commas(self) -> None:
        """Values may be separated by spaces, commas or both, and range from 0 to 999.

        Would fail if a comma without a space, several spaces or the bounds 0 and 999 were rejected.
        """
        self.assertEqual((30, 20, 10, 40), parse_values("30 20,10 ,  40"))
        self.assertEqual((0, 999), parse_values(" 0, 999 "))
        # exactly 60 values are allowed:
        self.assertEqual(MAX_VALUES, len(parse_values(" ".join(["7"] * MAX_VALUES))))
        # the text the playground writes reads back as the same values:
        self.assertEqual(
            "30 20 10 40 25 73 16 26 33 50 31", format_values(SLIDES_VALUES)
        )
        self.assertEqual(SLIDES_VALUES, parse_values(format_values(SLIDES_VALUES)))

    def test_errors(self) -> None:
        """A text with no value, more than 60 values, a token that is not a whole number in the digits 0 to 9, or a
        value out of range is rejected with a message that says why.

        Would fail if the tokens were checked with ``int()`` alone, which accepts ``1_0`` and digits of other scripts,
        if -5 were reported as no number, or if an empty text gave an empty input.
        """
        cases: tuple[tuple[str, str], ...] = (
            ("", "Type at least one value, e.g. 30 20 10 40."),
            (" , ", "at least one value"),
            (
                " ".join(["1"] * (MAX_VALUES + 1)),
                "61 values are too many: the playground takes at most 60.",
            ),
            ("30 x 10", "'x' is not a whole number"),
            ("1_0", "'1_0' is not a whole number"),
            ("٣", "'٣' is not a whole number"),
            ("2.5", "'2.5' is not a whole number"),
            ("x" * 20, "'xxxxxxxxxxxx…' is not a whole number"),
            ("-5", "-5 is out of range"),
            ("10 1000", "1000 is out of range: values go from 0 to 999."),
        )
        for text, message in cases:
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, re.escape(message)):
                    parse_values(text)

    def test_long_numbers(self) -> None:
        """A number of more than three digits, leading zeros not counted, is out of range, also one too long for
        ``int()``, and the message shows only its first 12 characters; a token of thousands of leading zeros is read
        as the few digits after them, so that ``int()`` never sees the long token.

        Would fail if Python's message about its limit of 4300 digits reached the reader, for many nines or for many
        leading zeros, or if 0007 were rejected.
        """
        # 5000 digits are out of range, shown shortened:
        with self.assertRaisesRegex(
            ValueError, "^" + re.escape("999999999999… is out of range")
        ):
            parse_values("9" * 5000)
        # leading zeros are no digits of their own:
        self.assertEqual((7, 999), parse_values("0007 000999"))
        # thousands of leading zeros: zero, minus zero and 7 are read, with no error from int():
        self.assertEqual(
            (0, 0, 7),
            parse_values(" ".join(("0" * 5000, "-" + "0" * 5000, "0" * 10000 + "7"))),
        )
        # thousands of leading zeros before a number out of range: out of range, shown without its leading zeros:
        with self.assertRaisesRegex(ValueError, r"^1000 is out of range"):
            parse_values("0" * 5000 + "1000")
        # and a negative number after thousands of zeros is read as such, shown by its value:
        with self.assertRaisesRegex(ValueError, r"^-5 is out of range"):
            parse_values("-" + "0" * 5000 + "5")

    def test_shortened_tokens(self) -> None:
        """A message shows a token of up to 12 characters whole and a longer one as its first 12 and an ellipsis.

        Would fail if the limit were off by one, so that a token of 12 characters lost its last one or one of 13 were
        shown whole.
        """
        self.assertEqual("abcdefghijkl", shorten("abcdefghijkl"))
        self.assertEqual("abcdefghijkl…", shorten("abcdefghijklm"))
        # in a message: 12 characters whole, 13 shortened:
        with self.assertRaisesRegex(ValueError, re.escape("'xxxxxxxxxxxx' is not")):
            parse_values("x" * 12)
        with self.assertRaisesRegex(ValueError, re.escape("'xxxxxxxxxxxx…' is not")):
            parse_values("x" * 13)

    def test_signs(self) -> None:
        """A number may have one sign: a plus sign is dropped, also before leading zeros, and minus zero is zero; a
        number out of range is shown with its minus, if it has one, but without a plus and without its leading zeros;
        two signs make no number.

        Would fail if a plus sign were called no number, if the message about a number out of range lost its minus or
        kept its plus sign, or if a doubled sign were read as one.
        """
        # one sign, read:
        self.assertEqual((5, 0, 0), parse_values("+5 +0 -0"))
        self.assertEqual((7,), parse_values("+0007"))
        cases: tuple[tuple[str, str], ...] = (
            # out of range, shown with the minus but without the plus:
            ("+1000", r"^1000 is out of range"),
            ("+01000", r"^1000 is out of range"),
            ("-1000", r"^-1000 is out of range"),
            # two signs, no number:
            ("--5", r"^'--5' is not a whole number"),
            ("+-5", r"^'\+-5' is not a whole number"),
        )
        for text, message in cases:
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, message):
                    parse_values(text)


class PresetValuesTest(unittest.TestCase):
    """The inputs of the presets."""

    def test_slides_example(self) -> None:
        """The slides' example is 30 20 10 40 25 73 16 26 33 50 31, whatever n and the seed.

        Would fail if the slides' example were drawn at random or cut to n values.
        """
        self.assertEqual(
            (30, 20, 10, 40, 25, 73, 16, 26, 33, 50, 31), preset_values(SLIDES)
        )
        self.assertEqual(SLIDES_VALUES, preset_values(SLIDES, 3, 42))

    def test_random_values_are_distinct(self) -> None:
        """The random preset has n distinct values from 0 to 999, for n from 1 to 60.

        Would fail if the values were drawn with repeats or outside the range the text field accepts.
        """
        for count in (1, 24, MAX_VALUES):
            with self.subTest(count=count):
                drawn: tuple[int, ...] = preset_values(RANDOM, count, 3)
                self.assertEqual(count, len(drawn))
                self.assertEqual(count, len(set(drawn)))
                # every value in the range:
                for value in drawn:
                    with self.subTest(value=value):
                        self.assertGreaterEqual(value, MIN_VALUE)
                        self.assertLessEqual(value, MAX_VALUE)

    def test_sorted_and_reversed(self) -> None:
        """The sorted and the reversed preset hold the values of the random preset with the same n and seed, sorted
        up and down; almost sorted holds them as well, not quite sorted.

        Would fail if the sorted presets drew other values than the random one, or if almost sorted were sorted.
        """
        drawn: tuple[int, ...] = preset_values(RANDOM, 24, 5)
        self.assertEqual(tuple(sorted(drawn)), preset_values(SORTED, 24, 5))
        self.assertEqual(
            tuple(sorted(drawn, reverse=True)), preset_values(REVERSED, 24, 5)
        )
        # almost sorted: the same values, with a few neighbours swapped:
        almost: tuple[int, ...] = preset_values(ALMOST_SORTED, 24, 5)
        self.assertEqual(sorted(drawn), sorted(almost))
        self.assertNotEqual(tuple(sorted(drawn)), almost)

    def test_same_seed_same_input(self) -> None:
        """Every generated preset gives the same input for the same n and seed, and another one for another seed.

        Would fail if the presets drew from the global random generator, so that the input changed on every call,
        or ignored the seed.
        """
        for name in (RANDOM, SORTED, REVERSED, ALMOST_SORTED):
            with self.subTest(preset=name):
                self.assertEqual(preset_values(name, 24, 5), preset_values(name, 24, 5))
                self.assertNotEqual(
                    preset_values(name, 24, 5), preset_values(name, 24, 6)
                )

    def test_unknown_preset_or_count(self) -> None:
        """An unknown preset and an n outside 1 to 60 are rejected.

        Would fail if an unknown name fell back to a preset, or if n = 0 gave an empty input.
        """
        with self.assertRaisesRegex(ValueError, "preset must be one of"):
            preset_values("shuffled")
        for count in (0, MAX_VALUES + 1):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError, "n goes from 1 to 60"):
                    preset_values(RANDOM, count)
