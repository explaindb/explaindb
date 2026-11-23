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
"""Tests for the external merge sort and its run generation by replacement selection."""

import copy
import logging
import math
import random
import string
from dataclasses import dataclass
from typing import Iterable, Iterator
from unittest import mock

from faker import Faker

from system.data_classes import Person
import unittest

from system.interfaces.queues import QueueFactory, ReadWriteQueue
from system.query_processing.queues.queue_factories import (
    ExternalQueueFactory,
    ListQueueFactory,
)
from system.query_processing.sorting import (
    RunGenerator,
    SingleStreamMerge,
    ExternalMergeSort,
    RunGenerationResult,
    RunMetadata,
    ReplacementSelection,
    Comparable,
    bulkload,
    sift_down,
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)


Faker.seed(42)
fake = Faker()


class MergeSortingTest(unittest.TestCase):
    @staticmethod
    def create_data(number_of_tuples=10000):
        return [Person(fake.name(), fake.date()) for _ in range(number_of_tuples)]

    def test_run_generation_and_single_merge(self):
        number_of_tuples: int = 1000
        persons: list[Person] = self.create_data(number_of_tuples=number_of_tuples)

        for number_of_tuples_in_main_memory in [
            100,
            1000,
            10000,
        ]:
            queue_factory: QueueFactory[Person]
            for queue_factory in [
                ListQueueFactory[Person](),
                ExternalQueueFactory[Person](number_of_tuples_in_main_memory),
            ]:
                persons2 = copy.deepcopy(persons)
                persons2.sort()
                self.assertEqual(len(persons), number_of_tuples)

                # create a tmp directory to store the runs:
                rg: RunGenerator = RunGenerator(
                    input_data=persons.__iter__(),
                    queue_factory=queue_factory,
                    number_of_tuples_in_main_memory=number_of_tuples_in_main_memory,
                )

                # create runs:
                run_generation_result: RunGenerationResult = rg.create_runs()

                # check the number of elements written:
                self.assertEqual(
                    run_generation_result.elements_written, number_of_tuples
                )
                run_sizes_sum = sum(
                    run_metadata.size
                    for run_metadata in run_generation_result.runs_metadata
                )
                self.assertEqual(run_sizes_sum, number_of_tuples)

                number_of_runs_in_theory = math.ceil(
                    number_of_tuples / number_of_tuples_in_main_memory
                )
                self.assertEqual(
                    len(run_generation_result.runs_metadata), number_of_runs_in_theory
                )

                # create a single stream merge from these runs:
                ssm: SingleStreamMerge = SingleStreamMerge(
                    run_generation_result.runs_metadata,
                    queue_factory,
                    number_of_tuples_in_main_memory,
                )

                count = 0
                # iterate over the merged elements:
                entry: Person
                for entry in ssm:
                    # compare merged elements with a copy of the sorted list:
                    self.assertEqual(entry, persons2.pop(0))
                    count += 1

                self.assertEqual(count, number_of_tuples)

    def test_external_sorting_new(self):
        number_of_tuples: int = 1500
        persons: list[Person] = self.create_data(number_of_tuples=number_of_tuples)

        for number_of_tuples_in_main_memory in [
            100,
            1000,
            10000,
        ]:
            queue_factory: QueueFactory[Person]
            for queue_factory in [
                ListQueueFactory[Person](),
                ExternalQueueFactory[Person](number_of_tuples_in_main_memory),
            ]:
                persons2 = copy.deepcopy(persons)
                persons2.sort()
                self.assertEqual(len(persons), number_of_tuples)

                ems: ExternalMergeSort[Person] = ExternalMergeSort[Person](
                    input_data=persons.__iter__(),
                    queue_factory=queue_factory,
                    number_of_tuples_in_main_memory=number_of_tuples_in_main_memory,
                    fan_in=5,
                )
                ems.create_runs()
                ems.merge()
                count: int = 0
                element: Person
                for element in ems:
                    # compare merged elements with the sorted list:
                    self.assertEqual(element, persons2.pop(0))
                    count += 1

                self.assertEqual(count, number_of_tuples)

    def test_external_sorting_with_fan_in_plus_one_tuples_in_main_memory(self) -> None:
        """External merge sort sorts correctly when main memory holds only fan_in + 1 tuples, e.g. three tuples
        for a fan-in of 2: an intermediate merge of fan_in runs then holds one tuple of each input run and one
        tuple of its output run in main memory."""
        number_of_tuples: int = 100
        persons: list[Person] = self.create_data(number_of_tuples=number_of_tuples)

        for number_of_tuples_in_main_memory, fan_in in [(3, 2), (6, 5)]:
            queue_factory: QueueFactory[Person]
            for queue_factory in [
                ListQueueFactory[Person](),
                ExternalQueueFactory[Person](number_of_tuples_in_main_memory),
            ]:
                with self.subTest(
                    number_of_tuples_in_main_memory=number_of_tuples_in_main_memory,
                    fan_in=fan_in,
                    queue_factory=type(queue_factory).__name__,
                ):
                    # sort the persons in runs of number_of_tuples_in_main_memory tuples, then merge at most
                    # fan_in runs at a time:
                    ems: ExternalMergeSort[Person] = ExternalMergeSort[Person](
                        input_data=persons.__iter__(),
                        queue_factory=queue_factory,
                        number_of_tuples_in_main_memory=number_of_tuples_in_main_memory,
                        fan_in=fan_in,
                    )
                    ems.create_runs()
                    ems.merge()

                    # the output holds every person exactly once, in sorted order:
                    self.assertEqual(list(ems), sorted(persons))

    def test_external_sorting_fan_in_must_be_at_least_two(self) -> None:
        """The constructor rejects a fan_in below 2, as merging fewer than two runs at a time does not reduce the
        number of runs."""

        # a fan_in of 1, 0 or below is rejected:
        for fan_in in [1, 0, -1]:
            with self.subTest(fan_in=fan_in):
                with self.assertRaisesRegex(ValueError, "fan_in must be at least 2"):
                    ExternalMergeSort[Person](
                        input_data=iter([]),
                        queue_factory=ListQueueFactory[Person](),
                        number_of_tuples_in_main_memory=100,
                        fan_in=fan_in,
                    )

        # the smallest valid fan_in, 2, is accepted:
        ems: ExternalMergeSort[Person] = ExternalMergeSort[Person](
            input_data=iter([]),
            queue_factory=ListQueueFactory[Person](),
            number_of_tuples_in_main_memory=100,
            fan_in=2,
        )
        self.assertEqual(ems.fan_in, 2)

    def test_runs_of_equal_size_leave_the_heap_oldest_first(self) -> None:
        """Of two runs of the same size, the one made first is the smaller in the heap of runs; a smaller run still
        comes before a larger one, however old."""
        queue_factory: ListQueueFactory[int] = ListQueueFactory[int]()
        older: RunMetadata = RunMetadata(
            queue=queue_factory.get_queue_instance(), size=4
        )
        newer: RunMetadata = RunMetadata(
            queue=queue_factory.get_queue_instance(), size=4
        )
        smaller_but_newest: RunMetadata = RunMetadata(
            queue=queue_factory.get_queue_instance(), size=3
        )

        # equal sizes: the older run first, either way round:
        self.assertTrue(older < newer)
        self.assertFalse(newer < older)
        # different sizes: the smaller run first, though it was made last:
        self.assertTrue(smaller_but_newest < older)
        self.assertFalse(older < smaller_but_newest)

    def test_runs_of_equal_size_are_merged_in_the_order_they_were_made(self) -> None:
        """With 9 runs of the same size and a fan-in of 3, ExternalMergeSort merges runs 0 to 2, then 3 to 5, then 6
        to 8 (numbered from 0 in the order they were made), and finally the three runs these merges made, in this
        order: of runs of the same size, the oldest first."""
        # 36 values in 9 pieces of 4 (memory for 4 values): run i holds the values 4 i … 4 i + 3, unsorted within
        # its piece, so that a run's smallest value tells which run it is:
        values: list[int] = [
            4 * run + place for run in range(9) for place in (2, 0, 3, 1)
        ]
        # for each merge, the runs it reads (by number, from 0):
        merges: list[list[int]] = []
        start_merge = SingleStreamMerge.__init__

        def note_merge(
            merge: SingleStreamMerge,
            run_infos: list[RunMetadata],
            queue_factory: QueueFactory,
            number_of_tuples_in_main_memory: int,
        ) -> None:
            """Notes which runs a merge reads (from their smallest values), then sets it up as the code does."""
            merges.append([min(run.queue) // 4 for run in run_infos])
            start_merge(
                merge, run_infos, queue_factory, number_of_tuples_in_main_memory
            )

        with mock.patch.object(SingleStreamMerge, "__init__", note_merge):
            ems: ExternalMergeSort[int] = ExternalMergeSort[int](
                input_data=iter(values),
                queue_factory=ListQueueFactory[int](),
                number_of_tuples_in_main_memory=4,
                fan_in=3,
            )
            ems.create_runs()
            ems.merge()
            output: list[int] = list(ems)

        # three merges of three runs in the order they were made, then the final merge of their three outputs (whose
        # smallest values are 0, 12 and 24, the smallest of runs 0, 3 and 6):
        self.assertEqual(merges, [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6]])
        self.assertEqual(output, sorted(values))


# the input sequence R of the replacement selection example in lecture 09b (slides 24-44, M = 4):
SLIDE_INPUT: tuple[int, ...] = (30, 20, 10, 40, 25, 73, 16, 26, 33, 50, 31)


def heap_violations[T: Comparable](heap: list[T]) -> list[int]:
    """Lists the positions of a heap whose element is smaller than the element at its parent position.

    @param heap: a list in level order (the parent of position i is at position (i - 1) // 2)
    @return: the positions that break the heap property, an empty list for a heap
    """
    # every position but the root, compared with its parent:
    return [
        position
        for position in range(1, len(heap))
        if heap[position] < heap[(position - 1) // 2]
    ]


def runs_of[T](output: Iterable[tuple[int, T]]) -> list[list[T]]:
    """Groups the (run number, element) pairs of replacement selection into runs.

    @param output: the pairs in output order; the run numbers count up from 0 without gaps
    @return: the elements of each run in output order, run 0 first
    """
    runs: list[list[T]] = list[list[T]]()
    for run_number, element in output:
        # the first element of a run opens the run's list:
        if run_number == len(runs):
            runs.append(list[T]())
        runs[run_number].append(element)
    return runs


def run_sizes(ems: ExternalMergeSort) -> list[int]:
    """Returns the sizes of the runs on the heap of runs of an external merge sort, in the order they were made.

    @param ems: an external merge sort after create_runs()
    @return: the number of elements of each run, the run made first first
    """
    # the heap of runs is in heap order; the runs' creation numbers give the order they were made in:
    return [run.size for run in sorted(ems.heap, key=lambda run: run.number)]


@dataclass
class Comparisons:
    """Counts the comparisons made by ``CountedValue`` objects."""

    count: int = 0


@dataclass
class CountedValue:
    """An integer that counts every ``<`` comparison it takes part in."""

    value: int
    comparisons: Comparisons

    def __lt__(self, other: "CountedValue") -> bool:
        """Compares by value and counts the comparison."""
        self.comparisons.count += 1
        return self.value < other.value


@dataclass
class TaggedValue:
    """An integer with a tag: ``<`` compares the values only, ``==`` values and tags, so that a test can tell
    equal values apart by their tags."""

    value: int
    tag: str

    def __lt__(self, other: "TaggedValue") -> bool:
        """Compares by value only; the tag does not count."""
        return self.value < other.value

    def __repr__(self) -> str:
        """Shows value and tag as in the docstrings, e.g. ``5a``."""
        return f"{self.value}{self.tag}"


def tagged(*labels: str) -> list[TaggedValue]:
    """Makes tagged values from labels such as ``"5a"``: the digits are the value, the letters after them the tag.

    @param labels: one label per value, digits followed by no, one or more lowercase letters
    @return: the tagged values in the order of the labels
    """
    values: list[TaggedValue] = list[TaggedValue]()
    for label in labels:
        # "5a" is the value 5 with the tag "a":
        digits: str = label.rstrip(string.ascii_lowercase)
        values.append(TaggedValue(int(digits), label[len(digits) :]))
    return values


def non_decreasing_stretches[T: Comparable](values: list[T]) -> list[list[T]]:
    """Splits a sequence into its maximal non-decreasing stretches: a new stretch starts at every element that is
    smaller than the element before it.

    @param values: the sequence
    @return: the stretches in order, an empty list for an empty sequence
    """
    stretches: list[list[T]] = list[list[T]]()
    for value in values:
        # a value smaller than the one before it starts a new stretch:
        if not stretches or value < stretches[-1][-1]:
            stretches.append(list[T]())
        stretches[-1].append(value)
    return stretches


class CountingQueueFactory[ObjectType](ListQueueFactory[ObjectType]):
    """A list queue factory that counts the queues it hands out."""

    def __init__(self) -> None:
        """Starts with no queue handed out."""
        self.queues_made: int = 0

    def get_queue_instance(self) -> ReadWriteQueue[ObjectType]:
        """See :meth:`QueueFactory.get_queue_instance`; also counts the queue."""
        self.queues_made += 1
        return super().get_queue_instance()


class CountingIterator[T](Iterator[T]):
    """An iterator that counts the elements taken from it."""

    def __init__(self, values: Iterable[T]) -> None:
        """Starts before the first element, with no element taken.

        @param values: the elements to hand out, in this order
        """
        self.values: Iterator[T] = iter(values)
        self.taken: int = 0

    def __next__(self) -> T:
        """Returns the next element and counts it; at the end, raises StopIteration without counting."""
        value: T = next(self.values)
        self.taken += 1
        return value


class SiftDownAndBulkLoadTest(unittest.TestCase):
    """The textbook heap of replacement selection: ``sift_down`` and the linear ``bulkload``."""

    def test_sift_down_moves_an_element_down_along_its_smaller_children(self) -> None:
        """sift_down swaps an element with its smaller child until no child is smaller; positions above the start
        stay as they are.

        - 73 replaces the root of the slides' heap [20, 25, 30, 40]: it swaps with 25 (smaller than 30), then with
          40, its only child: [25, 40, 30, 73];
        - 73 replaces the root of [25, 40, 30]: it swaps with the right child 30, which is smaller than 40;
        - 35 swaps with 20 and stops above 40 and 50: [20, 35, 30, 40, 50, 60, 70];
        - started at position 1 of [10, 50, 20, 30, 40], 50 swaps with 30, the smaller of 30 and 40; 10 and 20 stay.
        """
        cases: list[tuple[list[int], int, list[int]]] = [
            ([73, 25, 30, 40], 0, [25, 40, 30, 73]),
            ([73, 40, 30], 0, [30, 40, 73]),
            ([35, 20, 30, 40, 50, 60, 70], 0, [20, 35, 30, 40, 50, 60, 70]),
            ([10, 50, 20, 30, 40], 1, [10, 30, 20, 50, 40]),
        ]
        for heap, position, expected in cases:
            with self.subTest(heap=list(heap), position=position):
                # move the element at the given position down:
                sift_down(heap, position)
                self.assertEqual(heap, expected)

    def test_sift_down_stops_above_an_equal_child(self) -> None:
        """sift_down stops above a child that is equal to the element moving down: equal elements do not swap.

        - in [5a, 5b, 7], the smaller child of 5a is 5b, which is not smaller than 5a: nothing moves;
        - in [6a, 3, 4, 6b, 8], 6a swaps with 3, the smaller of 3 and 4, and then stops at position 1 above its
          smaller child 6b: [3, 6a, 4, 6b, 8].

        A sift that also swapped with an equal child would give [5b, 5a, 7] and [3, 6b, 4, 6a, 8].
        """
        cases: list[tuple[list[TaggedValue], list[TaggedValue]]] = [
            (tagged("5a", "5b", "7"), tagged("5a", "5b", "7")),
            (tagged("6a", "3", "4", "6b", "8"), tagged("3", "6a", "4", "6b", "8")),
        ]
        for heap, expected in cases:
            with self.subTest(heap=list(heap)):
                # move the root down; the tags show which of the equal elements ends up where:
                sift_down(heap, 0)
                self.assertEqual(heap, expected)

    def test_sift_down_takes_the_left_of_two_equal_children(self) -> None:
        """Of two equal children, sift_down swaps with the left one.

        - in [9, 4a, 4b], 9 swaps with 4a, the left child: [4a, 9, 4b];
        - in [9, 2, 3, 5a, 5b], 9 swaps with 2, the smaller of 2 and 3, then with 5a, the left of its equal
          children 5a and 5b: [2, 5a, 3, 9, 5b].

        A sift that took the right child on a tie would give [4b, 4a, 9] and [2, 5b, 3, 5a, 9].
        """
        cases: list[tuple[list[TaggedValue], list[TaggedValue]]] = [
            (tagged("9", "4a", "4b"), tagged("4a", "9", "4b")),
            (tagged("9", "2", "3", "5a", "5b"), tagged("2", "5a", "3", "9", "5b")),
        ]
        for heap, expected in cases:
            with self.subTest(heap=list(heap)):
                # move the root down; the tags show which of the equal children it swapped with:
                sift_down(heap, 0)
                self.assertEqual(heap, expected)

    def test_bulkload_of_the_slides_lists(self) -> None:
        """bulkload turns the first four elements of the slide input into the heap [10, 20, 30, 40] and leaves the
        list [16, 26, 33, 50] of run 1 as it is.

        The inner nodes of four elements are positions 1 and 0, sifted in this order. In [30, 20, 10, 40], 20 stays
        above its child 40, then 30 swaps with 10, the smaller of 20 and 10, and lands on a leaf. In
        [16, 26, 33, 50], 26 is smaller than 50 and 16 smaller than 26 and 33: nothing moves.
        """
        # the first M = 4 elements of the slide input:
        first_four: list[int] = list(SLIDE_INPUT[:4])
        bulkload(first_four)
        self.assertEqual(first_four, [10, 20, 30, 40])

        # the list from which run 1's heap is bulk-loaded:
        pending: list[int] = [16, 26, 33, 50]
        bulkload(pending)
        self.assertEqual(pending, [16, 26, 33, 50])

    def test_bulkload_makes_a_heap_of_the_same_elements(self) -> None:
        """bulkload turns random lists of 1 to 64 elements into heaps that hold the same elements.

        A bulk load that started at the root instead of the last inner node, or skipped an inner node, leaves
        elements smaller than the element at their parent position in some of these lists.
        """
        rng: random.Random = random.Random(49)
        for size in range(1, 65):
            with self.subTest(size=size):
                # a random list and a heap bulk-loaded from a copy of it:
                elements: list[int] = [rng.randrange(1000) for _ in range(size)]
                heap: list[int] = list(elements)
                bulkload(heap)

                # no element is smaller than the element at its parent position, and none is lost or added:
                self.assertEqual(heap_violations(heap), [])
                self.assertEqual(sorted(heap), sorted(elements))

    def test_bulkload_makes_a_linear_number_of_comparisons(self) -> None:
        """bulkload on 4096 elements in descending order makes at most 2 · (4096 − 1) = 8190 comparisons, a
        number linear in n.

        In descending order every element is larger than all elements below it, so every inner node sifts down to
        a leaf. The textbook sift makes two comparisons per level: which child is smaller, and whether that child
        is smaller than the element moving down. A node of height h moves down at most h levels, and the heights
        of all nodes of a heap of n nodes add up to n − (number of 1 bits in n), here 4096 − 1. Inserting the
        elements one by one would take about 10 n comparisons instead, as each new, smaller element climbs up to
        the root.
        """
        # 4096 counted values in descending order:
        n: int = 4096
        comparisons: Comparisons = Comparisons()
        elements: list[CountedValue] = [
            CountedValue(value, comparisons) for value in range(n, 0, -1)
        ]

        # the bulk load makes at most two comparisons per level, summed over the heights of all nodes (8190):
        bulkload(elements)
        self.assertLessEqual(comparisons.count, 2 * (n - bin(n).count("1")))

        # and it made a heap of the same elements:
        self.assertEqual(heap_violations(elements), [])
        self.assertEqual(
            sorted(element.value for element in elements), list(range(1, n + 1))
        )


class ReplacementSelectionTest(unittest.TestCase):
    """Run generation by replacement selection, on its own and inside the external merge sort."""

    def test_the_slide_example_gives_the_slides_two_runs(self) -> None:
        """Replacement selection with M = 4 makes the runs 10 20 25 30 40 73 and 16 26 31 33 50 from the slide
        input 30 20 10 40 25 73 16 26 33 50 31.

        The heap starts as [10, 20, 30, 40]. 25 and 73 are not smaller than the outputs 10 and 20 and go into the
        heap; 16, 26, 33 and 50 are smaller than the outputs 25, 30, 40 and 73 and go into the list, until 73 leaves
        the heap empty. The list becomes the heap of run 1; 31 is not smaller than 16 and joins run 1.
        """
        runs: list[list[int]] = runs_of(ReplacementSelection(SLIDE_INPUT, 4))
        self.assertEqual(runs, [[10, 20, 25, 30, 40, 73], [16, 26, 31, 33, 50]])

    def test_heap_and_list_hold_M_elements_until_the_input_runs_out(self) -> None:
        """After the i-th output, heap and list together hold exactly min(M, n − i) elements, and exactly
        min(n, M + i) elements have been taken from the input.

        Replacement selection reads one input element per output once the first M are in memory, so after i
        outputs it has read min(n, M + i) elements and written i. On the slide input with M = 4: 4 elements after
        each of the first seven outputs, then 3, 2, 1 and 0. A version that read the input ahead, e.g. all of it
        into a list first, would take more elements than that.
        """
        rng: random.Random = random.Random(49)
        cases: list[tuple[list[int], int]] = [(list(SLIDE_INPUT), 4)] + [
            ([rng.randrange(100) for _ in range(50)], M) for M in (2, 5, 10)
        ]
        for values, M in cases:
            with self.subTest(values=values, M=M):
                # the input, through an iterator that counts the elements taken from it:
                n: int = len(values)
                input_data: CountingIterator[int] = CountingIterator[int](values)
                rs: ReplacementSelection[int] = ReplacementSelection[int](input_data, M)

                # right after construction, the list holds the first M elements (all of them if the input is shorter),
                # and no other element has been taken:
                self.assertEqual(len(rs.heap) + len(rs.pending), min(M, n))
                self.assertEqual(input_data.taken, min(M, n))

                # after each output, heap and list hold the elements read but not yet written, and one more element
                # has been taken (until the input runs out):
                outputs: int = 0
                for i, _ in enumerate(rs, start=1):
                    self.assertEqual(
                        len(rs.heap) + len(rs.pending), min(M, n - i), f"output {i}"
                    )
                    self.assertEqual(input_data.taken, min(n, M + i), f"output {i}")
                    outputs = i
                self.assertEqual(outputs, n)

    def test_start_next_run_bulkloads_the_list_when_the_heap_is_empty(self) -> None:
        """start_next_run() changes nothing while the heap holds elements; once the heap is empty it bulk-loads the
        list into the heap, empties the list and counts up the run number.

        On the slide input with M = 4, after three outputs the heap is [30, 40, 73] and the list [16]. The sixth
        output, 73, empties the heap; the list then holds 16 26 33 50, a heap as it is, and 16 is the first output
        of run 1.
        """
        rs: ReplacementSelection[int] = ReplacementSelection[int](SLIDE_INPUT, 4)

        # three outputs: the heap still holds elements, so no new run starts:
        self.assertEqual([next(rs) for _ in range(3)], [(0, 10), (0, 20), (0, 25)])
        self.assertIs(rs.start_next_run(), False)
        self.assertEqual((rs.heap, rs.pending, rs.run), ([30, 40, 73], [16], 0))

        # three more outputs empty the heap; the list holds the elements of the next run:
        self.assertEqual([next(rs) for _ in range(3)], [(0, 30), (0, 40), (0, 73)])
        self.assertEqual((rs.heap, rs.pending, rs.run), ([], [16, 26, 33, 50], 0))

        # start_next_run() makes the list the heap of run 1:
        self.assertIs(rs.start_next_run(), True)
        self.assertEqual((rs.heap, rs.pending, rs.run), ([16, 26, 33, 50], [], 1))

        # the next output is the root of the new heap, in run 1:
        self.assertEqual(next(rs), (1, 16))

    def test_sorted_input_gives_one_run(self) -> None:
        """Sorted input gives a single run: every next element is not smaller than the output before it, so it
        always goes into the heap. Chunk sorting makes ⌈20 / 4⌉ = 5 runs from the same 20 elements.
        """
        values: list[int] = list(range(20))
        self.assertEqual(runs_of(ReplacementSelection(values, 4)), [values])

    def test_reversed_input_gives_runs_of_M(self) -> None:
        """Input in descending order gives runs of M elements, the last one n mod M (if that is not 0): each run
        holds the next M input elements, sorted, as with chunk sorting.

        For 9 8 7 6 5 4 3 2 1 0 and M = 4: every next element is smaller than the output before it and goes into
        the list, so each run outputs only the M elements in the heap at its start: 6 7 8 9, then 2 3 4 5, then 0 1.
        """
        for n, M in [(10, 4), (12, 4), (11, 3)]:
            with self.subTest(n=n, M=M):
                # the runs of n descending values:
                values: list[int] = list(range(n - 1, -1, -1))
                runs: list[list[int]] = runs_of(ReplacementSelection(values, M))

                # run k holds the input elements at positions k M to k M + M - 1, sorted:
                self.assertEqual(
                    runs,
                    [sorted(values[start : start + M]) for start in range(0, n, M)],
                )

    def test_random_input_gives_runs_of_about_2M(self) -> None:
        """On 10 000 random numbers with M = 100, the runs are sorted, hold the input together, and are on average
        between 1.7 M and 2.3 M long (theory: 2 M).

        Runs of exactly M, as chunk sorting makes, give a mean of M and fail the lower bound.
        """
        # 10 000 random numbers in [0, 1), seeded:
        rng: random.Random = random.Random(49)
        values: list[float] = [rng.random() for _ in range(10_000)]
        M: int = 100
        runs: list[list[float]] = runs_of(ReplacementSelection(values, M))

        # every run is sorted, and the runs together hold every input element once:
        for run in runs:
            self.assertEqual(run, sorted(run))
        self.assertEqual(
            sorted(element for run in runs for element in run), sorted(values)
        )

        # the mean run length is about 2 M:
        mean_run_length: float = len(values) / len(runs)
        self.assertGreaterEqual(mean_run_length, 1.7 * M)
        self.assertLessEqual(mean_run_length, 2.3 * M)

    def test_the_constructor_reads_the_first_M_elements_into_the_list(self) -> None:
        """The constructor reads the first M input elements into the list, in input order, leaves the heap empty
        and the run number at -1; the first start_next_run() bulk-loads the list into the heap and starts run 0.

        - slide input, M = 4: the list is 30 20 10 40; the bulk load makes the heap [10, 20, 30, 40];
        - input 3 1 2, M = 6: the list holds all three elements, 3 1 2; the bulk load swaps 3 with its smaller
          child 1: [1, 3, 2].

        A constructor that bulk-loaded right away would leave [10, 20, 30, 40] and [1, 3, 2] in the list.
        """
        cases: list[tuple[list[int], int, list[int], list[int]]] = [
            (list(SLIDE_INPUT), 4, [30, 20, 10, 40], [10, 20, 30, 40]),
            ([3, 1, 2], 6, [3, 1, 2], [1, 3, 2]),
        ]
        for values, M, first_elements, first_heap in cases:
            with self.subTest(values=values, M=M):
                # after construction: the first M elements in the list, as read; no heap, no run yet:
                rs: ReplacementSelection[int] = ReplacementSelection[int](values, M)
                self.assertEqual(
                    (rs.heap, rs.pending, rs.run), ([], first_elements, -1)
                )

                # the first start_next_run() turns the list into the heap of run 0:
                self.assertIs(rs.start_next_run(), True)
                self.assertEqual((rs.heap, rs.pending, rs.run), (first_heap, [], 0))

    def test_start_next_run_changes_nothing_while_the_list_is_empty(self) -> None:
        """start_next_run() returns False and changes nothing when the list is empty but the heap is not, and when
        both are empty.

        On the slide input with M = 4, right after run 0 starts, the heap is [10, 20, 30, 40] and the list is
        empty. After all 11 outputs, heap and list are empty and the run number stays 1. A start_next_run that did not
        check for an empty list would count up the run number when heap and list are both empty.
        """
        rs: ReplacementSelection[int] = ReplacementSelection[int](SLIDE_INPUT, 4)
        self.assertIs(rs.start_next_run(), True)

        # heap full, list empty: no new run:
        self.assertIs(rs.start_next_run(), False)
        self.assertEqual((rs.heap, rs.pending, rs.run), ([10, 20, 30, 40], [], 0))

        # all 11 outputs leave heap and list empty: still no new run:
        self.assertEqual(len(list(rs)), 11)
        self.assertIs(rs.start_next_run(), False)
        self.assertEqual((rs.heap, rs.pending, rs.run), ([], [], 1))

    def test_an_element_equal_to_the_output_stays_in_the_run(self) -> None:
        """An input element equal to the element just output still fits into the current run: it goes into the
        heap, not into the list.

        - M = 1, input 7a 7b 7c: each next 7 is not smaller than the 7 just output and replaces it as the root,
          so there is one run 7a 7b 7c;
        - M = 2, input 2a 4 2b 5: the heap starts as [2a, 4]; 2b is not smaller than the output 2a, becomes the
          root and stays above 4; 5 is not smaller than the output 2b, becomes the root and swaps with 4: [4, 5].
          One run: 2a 2b 4 5.

        If equal elements went into the list, the runs would be 7a | 7b | 7c and 2a 4 5 | 2b.
        """
        cases: list[tuple[list[TaggedValue], int, list[list[TaggedValue]]]] = [
            (tagged("7a", "7b", "7c"), 1, [tagged("7a", "7b", "7c")]),
            (tagged("2a", "4", "2b", "5"), 2, [tagged("2a", "2b", "4", "5")]),
        ]
        for values, M, expected_runs in cases:
            with self.subTest(values=values, M=M):
                # the tags show that every equal element stays in run 0, in this order:
                runs: list[list[TaggedValue]] = runs_of(ReplacementSelection(values, M))
                self.assertEqual(runs, expected_runs)

    def test_equal_elements_leave_the_heap_in_textbook_order(self) -> None:
        """Equal elements leave the heap in the order of the textbook heap (sift_down stops above an equal child
        and takes the left of two equal children), not in input order; M = 3.

        - 5a 5b 5c 6: the heap [5a, 5b, 5c]; 5a out, 6 replaces the root and moves below 5b: [5b, 6, 5c]; 5b out,
          the last element 5c takes the root's place, 6 is not smaller: [5c, 6]; then 5c and 6. One run:
          5a 5b 5c 6.
        - 5a 5b 5c 1: 5a out; 1 is smaller and goes into the list; the last element 5c takes the root's place and
          stays above the equal 5b: [5c, 5b]; then 5c, 5b. Runs: 5a 5c 5b, then 1.

        A removal as in heapq's heappop, which moves the new root down to a leaf first and then up again, would
        leave [5b, 5c] after 5a and give 5a 5b 5c in the second case.
        """
        cases: list[tuple[list[TaggedValue], list[list[TaggedValue]]]] = [
            (tagged("5a", "5b", "5c", "6"), [tagged("5a", "5b", "5c", "6")]),
            (tagged("5a", "5b", "5c", "1"), [tagged("5a", "5c", "5b"), tagged("1")]),
        ]
        for values, expected_runs in cases:
            with self.subTest(values=values):
                # the runs, with M = 3:
                runs: list[list[TaggedValue]] = runs_of(ReplacementSelection(values, 3))
                self.assertEqual(runs, expected_runs)

    def test_M_of_1_gives_the_non_decreasing_stretches_of_the_input(self) -> None:
        """With M = 1, the runs are exactly the maximal non-decreasing stretches of the input.

        The heap holds one element: a next element not smaller than the output replaces it and continues the run;
        a smaller one goes into the list, the heap is empty after the output, and the next run starts with that
        element. For 3 5 5 2 8 1 1 4 the runs are 3 5 5 | 2 8 | 1 1 4.
        """
        # the example worked out above:
        self.assertEqual(
            runs_of(ReplacementSelection([3, 5, 5, 2, 8, 1, 1, 4], 1)),
            [[3, 5, 5], [2, 8], [1, 1, 4]],
        )

        # 200 random digits (with many repeats): the runs are the stretches found by comparing neighbours:
        rng: random.Random = random.Random(49)
        values: list[int] = [rng.randrange(10) for _ in range(200)]
        self.assertEqual(
            runs_of(ReplacementSelection(values, 1)), non_decreasing_stretches(values)
        )

    def test_M_at_least_the_input_size_gives_one_sorted_run(self) -> None:
        """If M is at least the number of input elements, the constructor reads the whole input, and replacement
        selection outputs it as one sorted run: there is nothing left to read, so each output just removes the
        root of the heap.

        For the 11 elements of the slide input and M = 11, 12 or 100: one run 10 16 20 25 26 30 31 33 40 50 73.
        """
        for M in (11, 12, 100):
            with self.subTest(M=M):
                self.assertEqual(
                    runs_of(ReplacementSelection(SLIDE_INPUT, M)),
                    [[10, 16, 20, 25, 26, 30, 31, 33, 40, 50, 73]],
                )

    def test_empty_input_gives_no_run(self) -> None:
        """On empty input, start_next_run() returns False, as heap and list are empty, the run number stays -1,
        and ReplacementSelection yields nothing."""
        rs: ReplacementSelection[int] = ReplacementSelection[int]([], 4)

        # no element to start a run with:
        self.assertIs(rs.start_next_run(), False)
        self.assertEqual((rs.heap, rs.pending, rs.run), ([], [], -1))

        # and nothing to output:
        self.assertEqual(list(rs), [])

    def test_any_iterable_is_input_and_the_end_stays_the_end(self) -> None:
        """ReplacementSelection takes any iterable as input (a list, a tuple, an iterator, a generator) and makes
        the slides' two runs from each. After the last output, every further next() raises StopIteration again.
        """
        inputs: dict[str, Iterable[int]] = {
            "list": list(SLIDE_INPUT),
            "tuple": tuple(SLIDE_INPUT),
            "iterator": iter(SLIDE_INPUT),
            "generator": (value for value in SLIDE_INPUT),
        }
        for kind, input_data in inputs.items():
            with self.subTest(kind=kind):
                # the slides' two runs:
                rs: ReplacementSelection[int] = ReplacementSelection[int](input_data, 4)
                self.assertEqual(
                    runs_of(rs), [[10, 20, 25, 30, 40, 73], [16, 26, 31, 33, 50]]
                )

                # the end stays the end:
                for _ in range(3):
                    with self.assertRaises(StopIteration):
                        next(rs)

    def test_a_list_given_as_input_is_not_changed(self) -> None:
        """ReplacementSelection reads a list given as input without changing it."""
        # make the runs of a list:
        values: list[int] = list(SLIDE_INPUT)
        runs_of(ReplacementSelection(values, 4))

        # the list still holds the slide input in its order:
        self.assertEqual(values, list(SLIDE_INPUT))

    def test_M_below_1_is_rejected(self) -> None:
        """M must be at least 1: ReplacementSelection with M = 0 or M = -1 raises a ValueError, and so does
        create_runs() of RunGenerator and of ExternalMergeSort with replacement selection and M = 0.

        With M = 0, the constructor would read no element into the list, and replacement selection would end
        at once, without a single output: the whole input would be lost.
        """
        # the constructor rejects M = 0 and M = -1:
        for M in (0, -1):
            with self.subTest(M=M):
                with self.assertRaisesRegex(
                    ValueError, "number_of_tuples_in_main_memory must be at least 1"
                ):
                    ReplacementSelection[int](SLIDE_INPUT, M)

        # phase 0 with replacement selection rejects M = 0, on its own and inside the external merge sort:
        with self.assertRaisesRegex(
            ValueError, "number_of_tuples_in_main_memory must be at least 1"
        ):
            RunGenerator[int](
                input_data=iter(SLIDE_INPUT),
                queue_factory=ListQueueFactory[int](),
                number_of_tuples_in_main_memory=0,
                replacement_selection=True,
            ).create_runs()
        with self.assertRaisesRegex(
            ValueError, "number_of_tuples_in_main_memory must be at least 1"
        ):
            ExternalMergeSort[int](
                input_data=iter(SLIDE_INPUT),
                queue_factory=ListQueueFactory[int](),
                number_of_tuples_in_main_memory=0,
                fan_in=2,
                replacement_selection=True,
            ).create_runs()

    def test_run_generator_writes_each_run_to_its_own_queue(self) -> None:
        """RunGenerator(replacement_selection=True) writes every element once, one queue per run of replacement
        selection, holding that run's elements in output order; for list and external queues.
        """
        # 1000 random values and their runs by replacement selection with M = 50:
        rng: random.Random = random.Random(49)
        values: list[int] = [rng.randrange(10_000) for _ in range(1000)]
        expected_runs: list[list[int]] = runs_of(ReplacementSelection(values, 50))

        queue_factory: QueueFactory[int]
        for queue_factory in [ListQueueFactory[int](), ExternalQueueFactory[int](50)]:
            with self.subTest(queue_factory=type(queue_factory).__name__):
                result: RunGenerationResult = RunGenerator[int](
                    input_data=iter(values),
                    queue_factory=queue_factory,
                    number_of_tuples_in_main_memory=50,
                    replacement_selection=True,
                ).create_runs()

                # every element is written once:
                self.assertEqual(result.elements_written, 1000)

                # one queue per run, with that run's elements and size:
                self.assertEqual(
                    [list(run.queue) for run in result.runs_metadata], expected_runs
                )
                self.assertEqual(
                    [run.size for run in result.runs_metadata],
                    [len(run) for run in expected_runs],
                )

    def test_external_merge_sort_makes_runs_of_6_and_5_on_the_slide_input(self) -> None:
        """ExternalMergeSort(replacement_selection=True) makes runs of 6 and 5 elements from the slide input with
        M = 4, where chunk sorting makes runs of 4, 4 and 3, and its output is the sorted input; for list and
        external queues."""
        queue_factory: QueueFactory[int]
        for queue_factory in [ListQueueFactory[int](), ExternalQueueFactory[int](4)]:
            with self.subTest(queue_factory=type(queue_factory).__name__):
                # replacement selection: the slides' two runs, in the order they were made:
                ems: ExternalMergeSort[int] = ExternalMergeSort[int](
                    input_data=iter(SLIDE_INPUT),
                    queue_factory=queue_factory,
                    number_of_tuples_in_main_memory=4,
                    fan_in=2,
                    replacement_selection=True,
                )
                ems.create_runs()
                self.assertEqual(run_sizes(ems), [6, 5])

                # the final merge of the two runs gives the sorted input:
                ems.merge()
                self.assertEqual(list(ems), sorted(SLIDE_INPUT))

                # chunk sorting, for comparison: runs of 4, 4 and 3:
                chunks: ExternalMergeSort[int] = ExternalMergeSort[int](
                    input_data=iter(SLIDE_INPUT),
                    queue_factory=queue_factory,
                    number_of_tuples_in_main_memory=4,
                    fan_in=2,
                )
                chunks.create_runs()
                self.assertEqual(run_sizes(chunks), [4, 4, 3])

    def test_external_merge_sort_makes_one_run_from_sorted_input(self) -> None:
        """ExternalMergeSort(replacement_selection=True) makes a single run from 100 sorted values with M = 10
        (chunk sorting: 10 runs) and returns them in order; for list and external queues.
        """
        values: list[int] = list(range(100))
        queue_factory: QueueFactory[int]
        for queue_factory in [ListQueueFactory[int](), ExternalQueueFactory[int](10)]:
            with self.subTest(queue_factory=type(queue_factory).__name__):
                # phase 0 makes one run of all 100 values:
                ems: ExternalMergeSort[int] = ExternalMergeSort[int](
                    input_data=iter(values),
                    queue_factory=queue_factory,
                    number_of_tuples_in_main_memory=10,
                    fan_in=3,
                    replacement_selection=True,
                )
                ems.create_runs()
                self.assertEqual(run_sizes(ems), [100])

                # the merge reads that run back in order:
                ems.merge()
                self.assertEqual(list(ems), values)

    def test_run_generator_opens_one_queue_per_run_none_for_empty_input(self) -> None:
        """RunGenerator(replacement_selection=True) makes no run from empty input and asks the queue factory for
        no queue, as it opens a run's queue only with the run's first element. For the slide input, it asks for two
        queues, one per run.

        A queue opened before the first element would give an empty run for empty input, which the merge cannot
        read a first element from.
        """
        # empty input: no run, nothing written, no queue asked for:
        empty_factory: CountingQueueFactory[int] = CountingQueueFactory[int]()
        result: RunGenerationResult = RunGenerator[int](
            input_data=iter([]),
            queue_factory=empty_factory,
            number_of_tuples_in_main_memory=4,
            replacement_selection=True,
        ).create_runs()
        self.assertEqual((result.runs_metadata, result.elements_written), ([], 0))
        self.assertEqual(empty_factory.queues_made, 0)

        # the slide input: one queue for each of its two runs, and no other:
        slide_factory: CountingQueueFactory[int] = CountingQueueFactory[int]()
        result = RunGenerator[int](
            input_data=iter(SLIDE_INPUT),
            queue_factory=slide_factory,
            number_of_tuples_in_main_memory=4,
            replacement_selection=True,
        ).create_runs()
        self.assertEqual(len(result.runs_metadata), 2)
        self.assertEqual(slide_factory.queues_made, 2)

    def test_external_merge_sort_of_empty_input_outputs_nothing(self) -> None:
        """ExternalMergeSort(replacement_selection=True) of empty input makes no run and outputs nothing."""
        # sort nothing:
        ems: ExternalMergeSort[int] = ExternalMergeSort[int](
            input_data=iter([]),
            queue_factory=ListQueueFactory[int](),
            number_of_tuples_in_main_memory=4,
            fan_in=2,
            replacement_selection=True,
        )
        ems.create_runs()
        ems.merge()
        self.assertEqual(list(ems), [])

    def test_external_merge_sort_sorts_persons_as_sorted_does(self) -> None:
        """ExternalMergeSort(replacement_selection=True) puts 1000 fake persons into the same order as sorted(),
        with M = 10 and M = 100 and a fan-in of 5; for list and external queues.

        Persons compare by name only, in descending order. The persons come from a Faker seeded in this test, so
        they do not depend on the tests before it.
        """
        # 1000 fake persons from this test's own seeded Faker:
        faker: Faker = Faker()
        faker.seed_instance(49)
        persons: list[Person] = [
            Person(faker.name(), faker.date()) for _ in range(1000)
        ]
        for number_of_tuples_in_main_memory in (10, 100):
            queue_factory: QueueFactory[Person]
            for queue_factory in [
                ListQueueFactory[Person](),
                ExternalQueueFactory[Person](number_of_tuples_in_main_memory),
            ]:
                with self.subTest(
                    number_of_tuples_in_main_memory=number_of_tuples_in_main_memory,
                    queue_factory=type(queue_factory).__name__,
                ):
                    # runs by replacement selection, merged at most five at a time:
                    ems: ExternalMergeSort[Person] = ExternalMergeSort[Person](
                        input_data=persons.__iter__(),
                        queue_factory=queue_factory,
                        number_of_tuples_in_main_memory=number_of_tuples_in_main_memory,
                        fan_in=5,
                        replacement_selection=True,
                    )
                    ems.create_runs()
                    ems.merge()

                    # the output holds every person once, in the order of sorted():
                    self.assertEqual(list(ems), sorted(persons))


if __name__ == "__main__":
    # only execute a specific test class
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
