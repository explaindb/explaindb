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
"""Tests for the counting of external merge sort: its runs, its merges with their inputs and levels, and its cost."""

from __future__ import annotations

import heapq
import random
import re
import unittest
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import astuple, dataclass, field
from typing import Any
from unittest import mock

from system.interfaces.queues import QueueFactory
from system.playground.sort_counting import (
    Comparison,
    CountingInput,
    CountingQueue,
    CountingQueueFactory,
    FinalMerge,
    Merge,
    Run,
    SortCounts,
    check_fan_in,
    compare,
    merge_passes,
    sort_counted,
    textbook_cost,
)
from system.query_processing import sorting
from system.query_processing.sorting import (
    ExternalMergeSort,
    RunMetadata,
    SingleStreamMerge,
)

# the input row of slides 22 (quicksort) and 23 (replacement selection) of lecture 09b:
SLIDES: tuple[int, ...] = (3, 4, 6, 2, 9, 4, 8, 7, 5, 6, 3, 1, 1, 4, 6, 7)
# the slides' row with the 1 and the 7 of its last two pages swapped; replacement selection makes three runs of it:
SWAPPED_ROW: tuple[int, ...] = (3, 4, 6, 2, 9, 4, 8, 7, 5, 6, 3, 1, 7, 4, 6, 1)
# the 11 values of the slides' example input R:
ELEVEN: tuple[int, ...] = (30, 20, 10, 40, 25, 73, 16, 26, 33, 50, 31)
# the values 0 to 15 in an order without a pattern:
SHUFFLED_16: tuple[int, ...] = (9, 2, 14, 5, 0, 11, 7, 13, 3, 15, 8, 1, 12, 6, 10, 4)
# 200 distinct values in a random order, seeded:
RANDOM_200: tuple[int, ...] = tuple(random.Random(51).sample(range(1000), 200))
# 60 values from 0 to 29 in a random order, many of them more than once, seeded:
RANDOM_60: tuple[int, ...] = tuple(random.Random(60).choices(range(30), k=60))
# 24 keys from 0 to 3 only, each of them three to eight times:
FOUR_KEYS: tuple[int, ...] = (
    2, 2, 3, 3, 2, 3, 0, 1, 3, 2, 3, 0, 1, 0, 2, 2, 0, 0, 1, 3, 3, 0, 3, 0,
)  # fmt: skip

# sorts with merges of 2 and of 3 runs, merges that read an earlier merge's output, and final merges of runs from
# different levels, as (values, M, F, replacement selection):
MERGE_CASES: dict[str, tuple[tuple[int, ...], int, int, bool]] = {
    "slide 22, quicksort": (SLIDES, 4, 2, False),
    "20 ascending, quicksort": (tuple(range(20)), 4, 2, False),
    "swapped slide row, replacement selection": (SWAPPED_ROW, 4, 2, True),
    "104 descending, replacement selection": (tuple(range(103, -1, -1)), 4, 3, True),
    "200 random, quicksort": (RANDOM_200, 5, 3, False),
    "200 random, replacement selection": (RANDOM_200, 5, 3, True),
}


@dataclass(order=True, frozen=True)
class Record:
    """A record ordered by its key only; its name is payload that ``<`` and ``==`` ignore."""

    key: int
    name: str = field(compare=False)


def written_and_read(counts: SortCounts[Any]) -> tuple[int, ...]:
    """Returns the elements written (runs, merges, total) and read (input, merges, final merge, total), in this
    order."""
    return (
        counts.runs_written,
        counts.merges_written,
        counts.written,
        counts.input_read,
        counts.merges_read,
        counts.final_read,
        counts.read,
    )


def merge_numbers(
    counts: SortCounts[Any],
) -> list[tuple[tuple[int, ...], int | None, int]]:
    """Returns every merge, the final merge last, as the numbers of its input runs (in the order it read them), the
    number of its output run (None for the final merge) and its level."""
    return [
        (
            tuple(run.number for run in merge.inputs),
            merge.output.number if isinstance(merge, Merge) else None,
            merge.level,
        )
        for merge in (*counts.merges, counts.final_merge)
    ]


def sorts_of_every_kind() -> Iterator[tuple[str, SortCounts[int]]]:
    """Yields a name and the counts of every sort of several inputs with M = 4, F = 2 and F = 3, and both run
    generations."""
    inputs: dict[str, tuple[int, ...]] = {
        "slides": SLIDES,
        "swapped slide row": SWAPPED_ROW,
        "eleven": ELEVEN,
        "sorted": tuple(sorted(SLIDES)),
        "reversed": tuple(sorted(SLIDES, reverse=True)),
        "16 shuffled": SHUFFLED_16,
        "20 ascending": tuple(range(20)),
        "104 descending": tuple(range(103, -1, -1)),
    }
    for name, values in inputs.items():
        for fan_in in (2, 3):
            comparison: Comparison[int] = compare(values, 4, fan_in)
            yield f"{name}, F = {fan_in}, quicksort", comparison.chunks
            yield f"{name}, F = {fan_in}, replacement selection", comparison.replacement_selection


@dataclass(frozen=True)
class NotedSort:
    """What an :class:`ExternalMergeSort` on a :class:`CountingQueueFactory` did up to its final merge, noted on the
    side of the sort: the queues it gave each :class:`SingleStreamMerge` to read from.
    """

    # the factory, which keeps all queues of the sort in the order they were made:
    factory: CountingQueueFactory[int]
    # the number of queues phase 0 made (its runs):
    phase_0: int
    # the input queues of each merge before the final merge, in the order the sort made the merges:
    merges: list[list[CountingQueue[int]]]
    # the input queues of the final merge, and the queues of the runs on the sort's heap after merge():
    final_merge: list[CountingQueue[int]]
    heap: list[CountingQueue[int]]

    def numbers(self, queues: Iterable[CountingQueue[int]]) -> tuple[int, ...]:
        """Returns the numbers of the runs in the queues: their positions among all queues of the sort."""
        positions: dict[int, int] = {
            id(queue): number for number, queue in enumerate(self.factory.queues)
        }
        return tuple(positions[id(queue)] for queue in queues)


def sort_and_note_merges(
    values: Iterable[int], memory: int, fan_in: int, replacement_selection: bool
) -> NotedSort:
    """Runs :class:`ExternalMergeSort` on a :class:`CountingQueueFactory` up to its final merge, with
    :class:`SingleStreamMerge` replaced by a subclass that notes the input queues of every merge the sort makes.
    """
    noted: list[list[CountingQueue[int]]] = []

    class NotingMerge(SingleStreamMerge):
        """A :class:`SingleStreamMerge` that notes the queues of its input runs before it reads them."""

        def __init__(
            self,
            run_infos: list[RunMetadata],
            queue_factory: QueueFactory,
            number_of_tuples_in_main_memory: int,
        ) -> None:
            """Notes the input queues, then initializes the merge, which reads the first element of each."""
            noted.append([run.queue for run in run_infos])
            super().__init__(run_infos, queue_factory, number_of_tuples_in_main_memory)

    factory: CountingQueueFactory[int] = CountingQueueFactory[int]()
    sort: ExternalMergeSort[int] = ExternalMergeSort[int](
        input_data=iter(values),
        queue_factory=factory,
        number_of_tuples_in_main_memory=memory,
        fan_in=fan_in,
        replacement_selection=replacement_selection,
    )
    with mock.patch.object(sorting, "SingleStreamMerge", NotingMerge):
        sort.create_runs()
        phase_0: int = len(factory.queues)
        sort.merge()
    # the last merge the sort made is the final merge:
    return NotedSort(
        factory=factory,
        phase_0=phase_0,
        merges=noted[:-1],
        final_merge=noted[-1],
        heap=[metadata.queue for metadata in sort.heap],
    )


def merge_output_queue_first(sort: ExternalMergeSort[int]) -> None:
    """Merges the two smallest runs on the sort's heap into a new run, as the sort does with F = 2, but asks the
    queue factory for the output queue before the merge reads its input runs."""
    # the output queue first:
    queue: CountingQueue[int] = sort.queue_factory.get_queue_instance()
    # then the merge, which reads the first element of each input run when it is made:
    inputs: list[RunMetadata] = [heapq.heappop(sort.heap), heapq.heappop(sort.heap)]
    for element in SingleStreamMerge(
        inputs, sort.queue_factory, sort.number_of_tuples_in_main_memory
    ):
        queue.insert(element)
    heapq.heappush(sort.heap, RunMetadata(queue=queue, size=queue.size()))


class SlideExampleTest(unittest.TestCase):
    """The slides' input row 3,4 6,2 9,4 8,7 5,6 3,1 1,4 6,7 with M = 4 and F = 2 (slides 22 and 23)."""

    def test_slide_22_chunks(self) -> None:
        """Quicksort with M = 4 gives the runs (2 3 4 6), (4 7 8 9), (1 3 5 6) and (1 4 6 7). Two merges at level 1
        merge runs 0 and 1 into run 4 = (2 3 4 4 6 7 8 9) and runs 2 and 3 into run 5 = (1 1 3 4 5 6 6 7); the final
        merge reads runs 4 and 5 at level 2. Written: 16 (runs) + 16 (merges) = 32; read: 16 (input) + 16 (merges) +
        16 (final merge) = 48.

        Would fail if a merge's inputs were taken from the wrong queues, if the merges' outputs were numbered apart
        from the runs of phase 0, or if the final merge's reads were added to those of the merges.
        """
        counts: SortCounts[int] = compare(SLIDES, 4, 2).chunks
        # phase 0: four quicksort runs of M = 4, numbered 0 to 3, at level 0; Run(number, level, elements):
        runs: tuple[Run[int], ...] = (
            Run(0, 0, (2, 3, 4, 6)),
            Run(1, 0, (4, 7, 8, 9)),
            Run(2, 0, (1, 3, 5, 6)),
            Run(3, 0, (1, 4, 6, 7)),
        )
        self.assertEqual(runs, counts.runs)
        # two merges at level 1, whose outputs are runs 4 and 5:
        first: Run[int] = Run(4, 1, (2, 3, 4, 4, 6, 7, 8, 9))
        second: Run[int] = Run(5, 1, (1, 1, 3, 4, 5, 6, 6, 7))
        self.assertEqual(
            (
                Merge(inputs=(runs[0], runs[1]), output=first, level=1),
                Merge(inputs=(runs[2], runs[3]), output=second, level=1),
            ),
            counts.merges,
        )
        # the final merge of runs 4 and 5 at level 2, and the counts:
        self.assertEqual(
            FinalMerge(inputs=(first, second), level=2), counts.final_merge
        )
        self.assertEqual((16, 16, 32, 16, 16, 16, 48), written_and_read(counts))
        self.assertEqual(tuple(sorted(SLIDES)), counts.output)

    def test_slide_23_replacement_selection(self) -> None:
        """Replacement selection gives the runs (2 3 4 4 6 7 8 9) and (1 1 3 4 5 6 6 7), the same as the merges of
        slide 22. As 2 runs are not more than F = 2, there is no merge before the final merge, which reads both runs
        at level 1. Written: 16 (runs); read: 16 (input) + 16 (final merge) = 32.

        Would fail if the sort made its runs with quicksort although replacement selection was asked for, or if the
        final merge were recorded as a merge before it.
        """
        counts: SortCounts[int] = compare(SLIDES, 4, 2).replacement_selection
        # phase 0: two runs of 8, longer than M = 4:
        runs: tuple[Run[int], ...] = (
            Run(0, 0, (2, 3, 4, 4, 6, 7, 8, 9)),
            Run(1, 0, (1, 1, 3, 4, 5, 6, 6, 7)),
        )
        self.assertEqual(runs, counts.runs)
        # no merge before the final merge, which reads both runs at level 1:
        self.assertEqual((), counts.merges)
        self.assertEqual(FinalMerge(inputs=runs, level=1), counts.final_merge)
        # written 16, read 16 + 0 + 16 = 32:
        self.assertEqual((16, 0, 16, 16, 0, 16, 32), written_and_read(counts))


class CompareTest(unittest.TestCase):
    """``compare`` sorts one input with both run generations."""

    def test_both_sorts_get_the_whole_input(self) -> None:
        """Given a one-time iterator, ``compare`` sorts all of it with quicksort and with replacement selection, with
        the memory and fan-in given, and records the input and the run generation in each.

        Would fail if ``compare`` passed the iterator on to both sorts, so that the second sort got an empty input,
        or if it swapped the run generations.
        """
        comparison: Comparison[int] = compare(iter(SLIDES), 4, 2)
        self.assertEqual((4, 2), (comparison.memory, comparison.fan_in))
        # each sort got the whole input, with the run generation of its name:
        for counts, selection in (
            (comparison.chunks, False),
            (comparison.replacement_selection, True),
        ):
            with self.subTest(replacement_selection=selection):
                self.assertEqual(
                    (4, 2, selection, SLIDES),
                    (
                        counts.memory,
                        counts.fan_in,
                        counts.replacement_selection,
                        counts.values,
                    ),
                )
                self.assertEqual(tuple(sorted(SLIDES)), counts.output)


class MergeTest(unittest.TestCase):
    """The merges recorded: their inputs, outputs and levels."""

    def test_merge_inputs_are_in_the_order_they_were_read(self) -> None:
        """The slides' example R = 30 20 10 40 25 73 16 26 33 50 31 with M = 4, F = 2 and quicksort gives the runs
        (10 20 30 40), (16 25 26 73) and (31 33 50). The merge first reads the smallest run, run 2, then the older run
        of 4, run 0 (runs of equal length leave the heap oldest first), and writes run 3 of 7 elements; the final
        merge reads runs 1 and 3. Written: 11 + 7 = 18; read: 11 + 7 + 11 = 29.

        Would fail if a merge's inputs were listed by their numbers instead of the order the merge read them.
        """
        counts: SortCounts[int] = sort_counted(ELEVEN, 4, 2, False)
        runs: tuple[Run[int], ...] = counts.runs
        self.assertEqual((4, 4, 3), counts.run_lengths)
        # the merge reads run 2, then run 0, and writes run 3 at level 1:
        output: Run[int] = Run(3, 1, (10, 20, 30, 31, 33, 40, 50))
        self.assertEqual(
            (Merge(inputs=(runs[2], runs[0]), output=output, level=1),),
            counts.merges,
        )
        # the final merge reads run 1, then run 3:
        self.assertEqual(
            FinalMerge(inputs=(runs[1], output), level=2), counts.final_merge
        )
        self.assertEqual((11, 7, 18, 11, 7, 11, 29), written_and_read(counts))

    def test_a_merge_reads_the_output_of_an_earlier_merge(self) -> None:
        """20 values 0 to 19 in ascending order, M = 4, F = 2, quicksort: 5 runs of 4. Smallest first, of equal sizes
        the oldest: runs 0 and 1 into run 5 (level 1), runs 2 and 3 into run 6 (level 1), then run 4 and run 5, read
        in this order, into run 7 of 12 at level 2. The final merge reads runs 6 and 7 at level 3. Written: 20 + 28 =
        48; read: 20 + 28 + 20 = 68.

        Would fail if a merge's level were not one more than the highest level of its inputs, or if an output read by
        a later merge were also given to the final merge.
        """
        counts: SortCounts[int] = sort_counted(range(20), 4, 2, False)
        runs: tuple[Run[int], ...] = counts.runs
        self.assertEqual((4, 4, 4, 4, 4), counts.run_lengths)
        # three merges at levels 1, 1 and 2, of outputs 8, 8 and 12:
        self.assertEqual([1, 1, 2], [merge.level for merge in counts.merges])
        self.assertEqual((8, 8, 12), counts.merge_outputs)
        # the third merge reads run 4, then the first merge's output, run 5:
        first: Run[int] = counts.merges[0].output
        third: Merge[int] = counts.merges[2]
        self.assertEqual((runs[4], first), third.inputs)
        self.assertEqual(Run(7, 2, (*range(8), *range(16, 20))), third.output)
        # the final merge reads the other two, the second merge's output and the third's, at level 3:
        self.assertEqual(
            FinalMerge(inputs=(counts.merges[1].output, third.output), level=3),
            counts.final_merge,
        )
        self.assertEqual((20, 28, 48, 20, 28, 20, 68), written_and_read(counts))

    def test_with_f_3_every_merge_reads_3_runs_only_for_an_odd_number_of_runs(
        self,
    ) -> None:
        """With F = 3, every merge, the final one included, reads 3 runs if phase 0 makes W = 3, 5, 7 or 9 runs; with
        W = 4, 6 or 8 the last merge before the final one reads only 2, and with W = 1 or 2 the final merge reads
        fewer than 3. Each merge of three runs leaves two runs fewer, so only an odd number of runs comes down to the
        3 runs of the final merge in merges of three.

        Would fail if the code's last merge before the final one took F runs whenever it could (W = 4 would give
        merges of 3 and then 2 runs), or took fewer runs earlier.
        """
        # by W: the number of runs each merge reads, the final merge last:
        expected: dict[int, list[int]] = {
            1: [1],
            2: [2],
            3: [3],
            4: [2, 3],
            5: [3, 3],
            6: [3, 2, 3],
            7: [3, 3, 3],
            8: [3, 3, 2, 3],
            9: [3, 3, 3, 3],
        }
        for runs, fan_ins in expected.items():
            with self.subTest(runs=runs):
                # W runs of 4 values each, quicksort with M = 4 and F = 3:
                counts: SortCounts[int] = sort_counted(range(4 * runs), 4, 3, False)
                self.assertEqual(runs, len(counts.runs))
                self.assertEqual(
                    fan_ins,
                    [
                        len(merge.inputs)
                        for merge in (*counts.merges, counts.final_merge)
                    ],
                )
                # every merge reads three runs exactly for an odd number of runs, at least 3:
                self.assertEqual(runs >= 3 and runs % 2 == 1, set(fan_ins) == {3})

    def test_last_merge_takes_fewer_than_f_runs(self) -> None:
        """16 values 0 to 15 in any order, M = 4, F = 3, quicksort: 4 runs of 4. As 4 runs are more than F = 3, merge()
        merges, but only runs 0 and 1, not 3 runs: the last merge before the final merge takes just enough runs that
        the final merge reads from at most F runs. Its run of 8 and runs 2 and 3 go to the final merge, which reads
        from 3 runs. Written: 16 + 8 = 24; read: 16 + 8 + 16 = 40.

        Would fail if the counting assumed that every merge reads F runs.
        """
        for values in (tuple(range(16)), tuple(range(15, -1, -1)), SHUFFLED_16):
            with self.subTest(values=values):
                counts: SortCounts[int] = sort_counted(values, 4, 3, False)
                self.assertEqual((4, 4, 4, 4), counts.run_lengths)
                # one merge of runs 0 and 1 into run 4 of 8:
                self.assertEqual(
                    [(0, 1)],
                    [
                        tuple(run.number for run in merge.inputs)
                        for merge in counts.merges
                    ],
                )
                self.assertEqual((8,), counts.merge_outputs)
                # the final merge reads runs 2, 3 and 4:
                self.assertEqual(
                    (2, 3, 4), tuple(run.number for run in counts.final_merge.inputs)
                )
                self.assertEqual((16, 8, 24, 16, 8, 16, 40), written_and_read(counts))

    def test_every_sort_sorts_and_reads_the_input_once(self) -> None:
        """Every sort, of every input with both run generations and F = 2 or 3, outputs the values sorted, reads the
        input once in phase 0, writes all of it to the runs, reads all of it in the final merge, and reads in its
        merges exactly what they write.

        Would fail if the counting missed the reads of a merge's input runs, or counted the reads of the final merge
        as those of the merges before it.
        """
        for name, counts in sorts_of_every_kind():
            with self.subTest(sort=name):
                n: int = len(counts.values)
                # the output is the input sorted:
                self.assertEqual(tuple(sorted(counts.values)), counts.output)
                # the input is read once, written once to the runs and read once by the final merge:
                self.assertEqual(
                    (n, n, n, n),
                    (
                        counts.input_read,
                        counts.runs_written,
                        sum(counts.run_lengths),
                        counts.final_read,
                    ),
                )
                # the merges before the final merge read what they write:
                self.assertEqual(counts.merges_written, counts.merges_read)
                self.assertEqual(sum(counts.merge_outputs), counts.merges_written)

    def test_every_run_is_read_by_exactly_one_merge(self) -> None:
        """In every sort, the runs written (those of phase 0, then the merges' outputs) are numbered 0, 1, 2, ... in
        the order they were made, each is read by exactly one merge (one before the final merge, or the final merge),
        each merge before the final merge reads 2 to F runs and writes their elements merged, and each merge's level
        is one more than the highest level of its inputs.

        Would fail if a run were given to two merges or to none, or if a merge's output did not hold its inputs.
        """
        for name, counts in sorts_of_every_kind():
            with self.subTest(sort=name):
                every_merge: list[Merge[int] | FinalMerge[int]] = [
                    *counts.merges,
                    counts.final_merge,
                ]
                written: list[Run[int]] = [*counts.runs] + [
                    merge.output for merge in counts.merges
                ]
                # the runs written are numbered in the order they were made:
                self.assertEqual(
                    list(range(len(written))), [run.number for run in written]
                )
                # every run written is read by exactly one merge:
                read: Counter[int] = Counter(
                    run.number for merge in every_merge for run in merge.inputs
                )
                self.assertEqual(Counter(range(len(written))), read)
                # every merge reads 2 to F runs, writes them merged, one level above its highest input:
                for merge in counts.merges:
                    self.assertIn(len(merge.inputs), range(2, counts.fan_in + 1))
                    merged: list[int] = sorted(
                        element for run in merge.inputs for element in run.elements
                    )
                    self.assertEqual(tuple(merged), merge.output.elements)
                for merge in every_merge:
                    self.assertEqual(
                        1 + max(run.level for run in merge.inputs), merge.level
                    )

    def test_empty_input(self) -> None:
        """No values give no runs, no merges, a final merge of no runs at level 1, all counts 0 and an empty output,
        with both run generations.

        Would fail if an empty run were made for the empty input, or if the sort failed on it.
        """
        for selection in (False, True):
            with self.subTest(replacement_selection=selection):
                self.assertEqual(
                    SortCounts(
                        memory=4,
                        fan_in=2,
                        replacement_selection=selection,
                        values=(),
                        runs=(),
                        merges=(),
                        final_merge=FinalMerge(inputs=(), level=1),
                        input_read=0,
                        runs_written=0,
                        merges_read=0,
                        merges_written=0,
                        final_read=0,
                        output=(),
                    ),
                    sort_counted((), 4, 2, selection),
                )

    def test_a_single_run_with_both_run_generations(self) -> None:
        """One value, 3 values (fewer than M = 4) and 4 values (exactly M) make a single run with both run generations:
        run 0 at level 0 holds the values sorted, no merge comes before the final merge, which reads run 0 at level 1,
        and the input is read once, written once to the run and read once by the final merge.

        Would fail if a last run shorter than M were dropped, if values that fill the memory exactly were split into two
        runs, or if the final merge of a single run were recorded as a merge that writes a run.
        """
        for values in ((5,), (3, 1, 2), (4, 3, 1, 2)):
            for selection in (False, True):
                with self.subTest(values=values, replacement_selection=selection):
                    # one run of the values sorted, read by the final merge alone; N read, written and read again:
                    n: int = len(values)
                    run: Run[int] = Run(0, 0, tuple(sorted(values)))
                    self.assertEqual(
                        SortCounts(
                            memory=4,
                            fan_in=2,
                            replacement_selection=selection,
                            values=values,
                            runs=(run,),
                            merges=(),
                            final_merge=FinalMerge(inputs=(run,), level=1),
                            input_read=n,
                            runs_written=n,
                            merges_read=0,
                            merges_written=0,
                            final_read=n,
                            output=tuple(sorted(values)),
                        ),
                        sort_counted(values, 4, 2, selection),
                    )

    def test_a_merge_of_runs_that_lie_far_apart(self) -> None:
        """39 values 0 to 38 in ascending order, M = 4, F = 3, quicksort: runs 0 to 8 of 4 and run 9 of 3. The first
        merge reads the shortest run, run 9, then runs 0 and 1 (of runs of equal length the oldest first) into run 10
        at level 1; runs 2-4 and 5-7 merge into runs 11 and 12 at level 1, then run 8 and run 10 into run 13 at level
        2; the final merge reads runs 11, 12 and 13 at level 3. Written: 39 + 50 = 89; read: 39 + 50 + 39 = 128.

        Would fail if a merge's inputs were taken to be neighbouring runs, e.g. runs 0, 1 and 2, instead of the runs
        the merge read, or if run 10 were given to the final merge as well as to the merge that reads it.
        """
        counts: SortCounts[int] = sort_counted(range(39), 4, 3, False)
        runs: tuple[Run[int], ...] = counts.runs
        # phase 0: nine runs of 4, then the last run of 3:
        self.assertEqual((4,) * 9 + (3,), counts.run_lengths)
        # the first merge reads run 9, at one end of the runs, then runs 0 and 1, at the other end:
        first: Run[int] = Run(10, 1, (*range(8), 36, 37, 38))
        self.assertEqual(
            Merge(inputs=(runs[9], runs[0], runs[1]), output=first, level=1),
            counts.merges[0],
        )
        # every merge, the final merge last, as (input runs, output run, level):
        self.assertEqual(
            [
                ((9, 0, 1), 10, 1),
                ((2, 3, 4), 11, 1),
                ((5, 6, 7), 12, 1),
                ((8, 10), 13, 2),
                ((11, 12, 13), None, 3),
            ],
            merge_numbers(counts),
        )
        # the counts and the output:
        self.assertEqual((39, 50, 89, 39, 50, 39, 128), written_and_read(counts))
        self.assertEqual(tuple(range(39)), counts.output)


class ElementTypeTest(unittest.TestCase):
    """Elements that are not numbers: anything ordered by ``<``."""

    def test_strings(self) -> None:
        """Seven words with M = 3, F = 2 and quicksort give the runs (apple fig pear), (banana date kiwi) and (cherry);
        run 2 and run 0 merge into run 3, which the final merge reads with run 1. Written: 7 + 4 = 11; read: 7 + 4 + 7
        = 18.

        Would fail if the counting relied on numbers, e.g. summed or subtracted elements.
        """
        words: tuple[str, ...] = (
            "pear",
            "apple",
            "fig",
            "kiwi",
            "date",
            "banana",
            "cherry",
        )
        counts: SortCounts[str] = sort_counted(words, 3, 2, False)
        # phase 0: quicksort runs of 3, the last one shorter:
        runs: tuple[Run[str], ...] = (
            Run(0, 0, ("apple", "fig", "pear")),
            Run(1, 0, ("banana", "date", "kiwi")),
            Run(2, 0, ("cherry",)),
        )
        self.assertEqual(runs, counts.runs)
        # one merge of runs 2 and 0, then the final merge:
        output: Run[str] = Run(3, 1, ("apple", "cherry", "fig", "pear"))
        self.assertEqual(
            (Merge(inputs=(runs[2], runs[0]), output=output, level=1),), counts.merges
        )
        self.assertEqual(
            FinalMerge(inputs=(runs[1], output), level=2), counts.final_merge
        )
        # the output sorted, and the counts:
        self.assertEqual(tuple(sorted(words)), counts.output)
        self.assertEqual((7, 4, 11, 7, 4, 7, 18), written_and_read(counts))

    def test_records_ordered_by_a_key(self) -> None:
        """Records ordered by their key, with a name that ``<`` and ``==`` ignore, are sorted by key with their names
        kept, and their runs and merge are recorded with whole records (M = 3, F = 2, quicksort).

        Would fail if the sort or the counting lost or swapped a record's payload; the records are compared as
        (key, name) pairs, as ``==`` on records compares the keys only.
        """
        records: tuple[Record, ...] = (
            Record(3, "Tolstoy"),
            Record(1, "Austen"),
            Record(4, "Woolf"),
            Record(2, "Brontë"),
            Record(6, "Mann"),
            Record(5, "Kafka"),
            Record(0, "Eco"),
        )
        counts: SortCounts[Record] = sort_counted(records, 3, 2, False)
        # phase 0: quicksort runs of 3, sorted by key, names kept:
        self.assertEqual(
            [
                [(1, "Austen"), (3, "Tolstoy"), (4, "Woolf")],
                [(2, "Brontë"), (5, "Kafka"), (6, "Mann")],
                [(0, "Eco")],
            ],
            [[astuple(record) for record in run.elements] for run in counts.runs],
        )
        # one merge of runs 2 and 0 into run 3, then the final merge of runs 1 and 3:
        merge: Merge[Record] = counts.merges[0]
        self.assertEqual(
            ((2, 0), 3, 1),
            (
                tuple(run.number for run in merge.inputs),
                merge.output.number,
                merge.level,
            ),
        )
        self.assertEqual((1, 3), tuple(run.number for run in counts.final_merge.inputs))
        # the output: all records sorted by key, with their names:
        self.assertEqual(
            [
                (0, "Eco"),
                (1, "Austen"),
                (2, "Brontë"),
                (3, "Tolstoy"),
                (4, "Woolf"),
                (5, "Kafka"),
                (6, "Mann"),
            ],
            [astuple(record) for record in counts.output],
        )

    def test_records_give_the_runs_and_merges_of_their_keys(self) -> None:
        """Records whose keys are the slides' row followed by 3, 1, 4 (19 keys, most of them more than once) give the
        same runs, merges, levels and counts as the bare keys, with both run generations (M = 4, F = 2); the output
        holds every record once, in the order of the keys.

        Would fail if the sort or the counting treated records differently from their keys, e.g. if records with
        equal keys were taken for the same element and counted once; the records are compared as (key, name) pairs,
        as ``==`` on records compares the keys only.
        """
        keys: tuple[int, ...] = (*SLIDES, 3, 1, 4)
        records: tuple[Record, ...] = tuple(
            Record(key, f"r{index}") for index, key in enumerate(keys)
        )
        for selection in (False, True):
            with self.subTest(replacement_selection=selection):
                plain: SortCounts[int] = sort_counted(keys, 4, 2, selection)
                counted: SortCounts[Record] = sort_counted(records, 4, 2, selection)
                # the runs of phase 0 as numbers, levels and keys, then the merges, are those of the bare keys:
                self.assertEqual(
                    [(run.number, run.level, run.elements) for run in plain.runs],
                    [
                        (
                            run.number,
                            run.level,
                            tuple(record.key for record in run.elements),
                        )
                        for run in counted.runs
                    ],
                )
                self.assertEqual(merge_numbers(plain), merge_numbers(counted))
                self.assertEqual(written_and_read(plain), written_and_read(counted))
                # the output holds every record once, in the order of the keys:
                self.assertEqual(
                    Counter(astuple(record) for record in records),
                    Counter(astuple(record) for record in counted.output),
                )
                self.assertEqual(
                    tuple(sorted(keys)), tuple(record.key for record in counted.output)
                )

    def test_replacement_selection_keeps_every_record_with_equal_keys(self) -> None:
        """24 records with keys from 0 to 3 only, M = 3, F = 2, replacement selection: runs of 7, 4, 5, 6 and 2
        records, three merges at levels 1, 1 and 2, and the final merge at level 3. The runs of phase 0 together hold
        every record exactly once, each merge's output holds exactly the records of its input runs, and the output
        holds every record once, in the order of the keys.

        Would fail if replacement selection or a merge lost a record whose key equals another's, or wrote it twice;
        the records are compared as (key, name) pairs, as a comparison of the keys alone would not notice.
        """
        records: tuple[Record, ...] = tuple(
            Record(key, f"r{index}") for index, key in enumerate(FOUR_KEYS)
        )
        every_record: Counter[tuple[Any, ...]] = Counter(map(astuple, records))
        counts: SortCounts[Record] = sort_counted(records, 3, 2, True)
        # the runs and the levels of the merges:
        self.assertEqual((7, 4, 5, 6, 2), counts.run_lengths)
        self.assertEqual(
            [1, 1, 2, 3],
            [merge.level for merge in (*counts.merges, counts.final_merge)],
        )
        # the runs of phase 0 together hold every record once:
        self.assertEqual(
            every_record,
            Counter(astuple(record) for run in counts.runs for record in run.elements),
        )
        # each merge writes exactly the records it reads:
        for merge in counts.merges:
            self.assertEqual(
                Counter(
                    astuple(record) for run in merge.inputs for record in run.elements
                ),
                Counter(map(astuple, merge.output.elements)),
            )
        # the output holds every record once, in the order of the keys:
        self.assertEqual(every_record, Counter(map(astuple, counts.output)))
        self.assertEqual(
            tuple(sorted(FOUR_KEYS)), tuple(record.key for record in counts.output)
        )


class CountedCostTest(unittest.TestCase):
    """The cost counted (elements written plus read) next to the formula's 2N · (1 + ⌈log_F W⌉) for the real
    number of runs W."""

    def test_chunks_with_w_a_power_of_f_cost_n_less_than_the_formula(self) -> None:
        """Quicksort with W = F^k runs costs exactly N less than the formula, as the final merge writes nothing:
        slide 22 (W = 4, F = 2) 80 against 96, 16 ascending values (W = 4, F = 2) 80 against 96, and 36 ascending
        values (W = 9, F = 3) 180 against 216.

        Would fail if :attr:`SortCounts.cost` left out the reads of phase 0 or the writes of the merges, or if
        :attr:`SortCounts.textbook_cost` used another value for W.
        """
        cases: dict[str, tuple[tuple[int, ...], int, int, int, int]] = {
            "slide 22": (SLIDES, 2, 4, 80, 96),
            "16 ascending": (tuple(range(16)), 2, 4, 80, 96),
            "36 ascending": (tuple(range(36)), 3, 9, 180, 216),
        }
        for name, (values, fan_in, runs, cost, formula) in cases.items():
            with self.subTest(case=name):
                counts: SortCounts[int] = sort_counted(values, 4, fan_in, False)
                # W runs, the cost counted and the formula's:
                self.assertEqual(
                    (runs, cost, formula),
                    (len(counts.runs), counts.cost, counts.textbook_cost),
                )
                # the cost is N less than the formula's:
                self.assertEqual(counts.textbook_cost - len(values), counts.cost)

    def test_eight_chunks_with_f_3_cost_n_less_than_the_formula(self) -> None:
        """32 ascending values, M = 4, F = 3, quicksort: W = 8 is not a power of F, yet the cost is 160 = 192 − 32, as
        for W = F^k: the merges of runs 0–2, 3–5 and 6–7 bring every element through one merge at level 1, and the
        final merge reads their 3 outputs at level 2.

        Would fail if the last merge before the final merge took F runs whenever it could, leaving a run of level 0
        for the final merge.
        """
        counts: SortCounts[int] = sort_counted(range(32), 4, 3, False)
        # three merges at level 1, of 3, 3 and 2 runs:
        self.assertEqual(
            [(3, 1), (3, 1), (2, 1)],
            [(len(merge.inputs), merge.level) for merge in counts.merges],
        )
        self.assertEqual((12, 12, 8), counts.merge_outputs)
        # the final merge reads 3 runs of level 1, at level 2:
        self.assertEqual(
            ([1, 1, 1], 2),
            (
                [run.level for run in counts.final_merge.inputs],
                counts.final_merge.level,
            ),
        )
        # 160 counted, 192 by the formula:
        self.assertEqual(
            (8, 160, 192), (len(counts.runs), counts.cost, counts.textbook_cost)
        )

    def test_runs_that_skip_a_level_cost_less(self) -> None:
        """When W is not a power of F, a run can skip a level and the cost drops below formula − N: 20 ascending values
        with quicksort (W = 5, F = 2), where run 6 goes from level 1 straight to the final merge at level 3, cost 116 <
        140 = 160 − 20; the swapped slide row with replacement selection (runs of 8, 7 and 1, F = 2), where the run of 8
        goes from level 0 straight to the final merge at level 2, cost 64 < 80 = 96 − 16.

        Would fail if the counting charged every element for every level, as the formula does.
        """
        # 20 ascending: the final merge reads run 6 of level 1 and run 7 of level 2:
        twenty: SortCounts[int] = sort_counted(range(20), 4, 2, False)
        self.assertEqual(
            [(6, 1), (7, 2)],
            [(run.number, run.level) for run in twenty.final_merge.inputs],
        )
        self.assertEqual((116, 160), (twenty.cost, twenty.textbook_cost))
        # the swapped slide row: runs of 8, 7 and 1; the runs of 1 and 7 merge, the run of 8 waits for the final merge:
        swapped: SortCounts[int] = sort_counted(SWAPPED_ROW, 4, 2, True)
        self.assertEqual((8, 7, 1), swapped.run_lengths)
        self.assertEqual(
            [(0, 0), (3, 1)],
            [(run.number, run.level) for run in swapped.final_merge.inputs],
        )
        self.assertEqual((64, 96), (swapped.cost, swapped.textbook_cost))
        # both below formula − N:
        self.assertLess(twenty.cost, twenty.textbook_cost - 20)
        self.assertLess(swapped.cost, swapped.textbook_cost - 16)

    def test_fewer_than_f_runs_only_at_the_end_can_cost_more_than_formula_minus_n(
        self,
    ) -> None:
        """104 values in descending order, M = 4, F = 3, replacement selection: 26 runs of 4. The code takes fewer than
        F runs only in its last merge before the final merge: eleven merges of 3 runs, then one of 2. That last merge
        reads a run of 12 at level 1 and a run of 20 at level 2, so the final merge is at level 4, one more than
        ⌈log_3 26⌉ = 3: the cost is 752, more than formula − N = 832 − 104 = 728, but still less than the formula's
        832.

        Would fail if the counting assumed that a sort never costs more than formula − N.
        """
        counts: SortCounts[int] = sort_counted(range(103, -1, -1), 4, 3, True)
        self.assertEqual((4,) * 26, counts.run_lengths)
        # eleven merges of 3 runs, the last one before the final merge of 2:
        self.assertEqual([3] * 11 + [2], [len(merge.inputs) for merge in counts.merges])
        # the last merge before the final merge: a run of 12 at level 1 and one of 20 at level 2, into 32 at level 3:
        last: Merge[int] = counts.merges[-1]
        self.assertEqual(
            [(12, 1), (20, 2)], [(len(run.elements), run.level) for run in last.inputs]
        )
        self.assertEqual((32, 3), (len(last.output.elements), last.level))
        self.assertEqual(4, counts.final_merge.level)
        # 752 counted, between formula − N = 728 and the formula's 832:
        self.assertEqual((752, 832), (counts.cost, counts.textbook_cost))
        self.assertGreater(counts.cost, counts.textbook_cost - 104)

    def test_a_single_run_costs_3n(self) -> None:
        """16 sorted values with replacement selection make one run: no merge before the final merge, which still
        reads the run phase 0 wrote. The cost is 3N = 48 (16 read from the input, 16 written, 16 read by the final
        merge), against the formula's 2N = 32 with ⌈log_F 1⌉ = 0 merge passes.

        Would fail if the final merge of a single run were not counted.
        """
        counts: SortCounts[int] = sort_counted(range(16), 4, 2, True)
        # one run of all 16 values, read by the final merge alone:
        self.assertEqual((Run(0, 0, tuple(range(16))),), counts.runs)
        self.assertEqual((), counts.merges)
        self.assertEqual(1, counts.final_fan_in)
        # 3N counted against the formula's 2N:
        self.assertEqual((48, 32), (counts.cost, counts.textbook_cost))

    def test_memory_for_all_values_costs_3n(self) -> None:
        """With M ≥ N, quicksort makes a single run as well: the slides' 16 values with M = 16 give one run of all
        values, no merge before the final merge, and the cost 3N = 48 against the formula's 2N = 32.

        Would fail if a single quicksort run were not read once more by the final merge.
        """
        counts: SortCounts[int] = sort_counted(SLIDES, 16, 2, False)
        # one run of all 16 values, sorted in memory, read by the final merge alone:
        self.assertEqual((Run(0, 0, tuple(sorted(SLIDES))),), counts.runs)
        self.assertEqual(((), 1), (counts.merges, counts.final_fan_in))
        # 3N counted against the formula's 2N:
        self.assertEqual((48, 32), (counts.cost, counts.textbook_cost))


class TextbookCostTest(unittest.TestCase):
    """The formula's number of merge passes ⌈log_F W⌉ and its cost 2N · (1 + ⌈log_F W⌉)."""

    def test_merge_passes(self) -> None:
        """⌈log_F W⌉ is 0 for W = 0 and W = 1, k for W = F^k, and k + 1 for W = F^k + 1; W = 125, F = 5 gives 3.

        Would fail if computed with floating-point logarithms: math.log(125, 5) is 3.0000000000000004, whose ceiling
        is 4.
        """
        # (W, F, ⌈log_F W⌉):
        cases: list[tuple[int, int, int]] = [
            (0, 2, 0),
            (1, 2, 0),
            (1, 10, 0),
            (2, 2, 1),
            (4, 2, 2),
            (5, 2, 3),
            (9, 3, 2),
            (10, 3, 3),
            (26, 3, 3),
            (27, 3, 3),
            (28, 3, 4),
            (125, 5, 3),
            (126, 5, 4),
        ]
        for runs, fan_in, passes in cases:
            with self.subTest(runs=runs, fan_in=fan_in):
                self.assertEqual(passes, merge_passes(runs, fan_in))

    def test_f_below_2_and_negative_w_are_rejected(self) -> None:
        """F = 1, F = 0 and W = −1 raise a ValueError in ``merge_passes`` and in ``textbook_cost``.

        Would fail if F = 1 were not checked: no power of 1 reaches W = 4, so no number of passes is found (an
        AssertionError instead of the ValueError).
        """
        for runs, fan_in in ((4, 1), (4, 0), (-1, 2)):
            with self.subTest(runs=runs, fan_in=fan_in):
                # the message names F and W with the values given:
                message: str = re.escape(
                    f"need F ≥ 2 and W ≥ 0, got F = {fan_in} and W = {runs}"
                )
                with self.assertRaisesRegex(ValueError, message):
                    merge_passes(runs, fan_in)
                with self.assertRaisesRegex(ValueError, message):
                    textbook_cost(16, runs, fan_in)

    def test_f_not_a_number_is_rejected(self) -> None:
        """F = NaN (a float that is not a number) raises a ValueError in ``merge_passes`` and in ``textbook_cost``,
        although every comparison with it, ``NaN < 2`` included, is false.

        Would fail if F were checked with ``F < 2``, which lets NaN through to a search that finds no number of passes.
        """
        # NaN as the fan-in, against W = 5 runs:
        not_a_number: float = float("nan")
        # the message names F and W with the values given:
        message: str = re.escape("need F ≥ 2 and W ≥ 0, got F = nan and W = 5")
        with self.assertRaisesRegex(ValueError, message):
            merge_passes(5, not_a_number)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, message):
            textbook_cost(16, 5, not_a_number)  # type: ignore[arg-type]

    def test_textbook_cost(self) -> None:
        """2N · (1 + ⌈log_F W⌉): 96 for N = 16, W = 4, F = 2; 64 for W = 2; 32 for a single run; 0 for no elements;
        160 for N = 20, W = 5, F = 2; 832 for N = 104, W = 26, F = 3.

        Would fail if pass 0 were left out (2N · ⌈log_F W⌉) or if only one of reading and writing were counted.
        """
        # (N, W, F, cost):
        cases: list[tuple[int, int, int, int]] = [
            (16, 4, 2, 96),
            (16, 2, 2, 64),
            (16, 1, 2, 32),
            (0, 0, 2, 0),
            (20, 5, 2, 160),
            (104, 26, 3, 832),
        ]
        for elements, runs, fan_in, cost in cases:
            with self.subTest(elements=elements, runs=runs, fan_in=fan_in):
                self.assertEqual(cost, textbook_cost(elements, runs, fan_in))


class FanInTest(unittest.TestCase):
    """The fan-in F must be from 2 to M − 1."""

    def test_f_from_2_to_m_minus_1_is_accepted(self) -> None:
        """F = 2 and F = M − 1 are accepted, for M = 3, 4 and 100; with M = 4 the sort runs with F = 2 and F = 3.

        Would fail if a bound were exclusive, e.g. F < M − 1 instead of F ≤ M − 1.
        """
        # nothing raises, in the check or in the sorts with both fan-ins of M = 4:
        for memory, fan_in in ((4, 2), (4, 3), (3, 2), (100, 99)):
            with self.subTest(memory=memory, fan_in=fan_in):
                check_fan_in(memory, fan_in)
        for fan_in in (2, 3):
            with self.subTest(fan_in=fan_in):
                compare(SLIDES, 4, fan_in)

    def test_f_outside_2_to_m_minus_1_is_rejected(self) -> None:
        """F = 0, F = 1 and F = M raise a ValueError, in ``check_fan_in`` and, for M = 4, in ``sort_counted`` and
        ``compare``: a merge of one run makes no progress, and a merge of M runs leaves no memory for its output run.

        Would fail if ``sort_counted`` did not check F: for F = M = 4 the slides' 4 quicksort runs need no merge before
        the final merge, so the sort would return counts instead of raising.
        """
        for memory, fan_in in ((4, 0), (4, 1), (4, 4), (3, 3), (2, 2)):
            with self.subTest(memory=memory, fan_in=fan_in):
                with self.assertRaisesRegex(
                    ValueError,
                    re.escape(
                        f"the fan-in F must be from 2 to M − 1 = {memory - 1}, got {fan_in}"
                    ),
                ):
                    check_fan_in(memory, fan_in)
        # the sort checks F before it sorts:
        for fan_in in (1, 4):
            message: str = re.escape(
                f"the fan-in F must be from 2 to M − 1 = 3, got {fan_in}"
            )
            with self.subTest(fan_in=fan_in, function="sort_counted"):
                with self.assertRaisesRegex(ValueError, message):
                    sort_counted(SLIDES, 4, fan_in, False)
            with self.subTest(fan_in=fan_in, function="compare"):
                with self.assertRaisesRegex(ValueError, message):
                    compare(SLIDES, 4, fan_in)

    def test_f_at_its_limits_sorts_and_counts_consistently(self) -> None:
        """With F = 2 and F = M − 1 for M = 3, 4 and 5, both run generations sort 60 random values with duplicates:
        the output is the input sorted; the input is read once, written once to the runs and read once by the final
        merge; the merges before the final merge read what they write; each of them reads 2 to F runs, the final
        merge min(W, F) runs, and every run written is read by exactly one merge. Quicksort makes 60 / M runs of M.

        Would fail if the sort or the counting broke at a limit of F, e.g. if a merge of F = M − 1 runs left no memory
        for its output run, if the final merge read more than F runs, or if a run of a merge of four were missed.
        """
        # (M, F, replacement selection): F = 2 and F = M − 1 (one case for M = 3, where both are 2):
        cases: list[tuple[int, int, bool]] = [
            (memory, fan_in, selection)
            for memory in (3, 4, 5)
            for fan_in in sorted({2, memory - 1})
            for selection in (False, True)
        ]
        for memory, fan_in, selection in cases:
            with self.subTest(memory=memory, fan_in=fan_in, selection=selection):
                counts: SortCounts[int] = sort_counted(
                    RANDOM_60, memory, fan_in, selection
                )
                # the output is the input sorted; the input passes once through phase 0 and the final merge:
                self.assertEqual(tuple(sorted(RANDOM_60)), counts.output)
                self.assertEqual(
                    (60, 60, 60),
                    (counts.input_read, counts.runs_written, counts.final_read),
                )
                # the merges before the final merge read what they write:
                self.assertEqual(counts.merges_written, counts.merges_read)
                self.assertEqual(sum(counts.merge_outputs), counts.merges_written)
                # each merge reads 2 to F runs, the final merge min(W, F), and every run written is read once:
                self.assertEqual(
                    [],
                    [
                        len(merge.inputs)
                        for merge in counts.merges
                        if not 2 <= len(merge.inputs) <= fan_in
                    ],
                )
                self.assertEqual(min(len(counts.runs), fan_in), counts.final_fan_in)
                self.assertEqual(
                    Counter(range(len(counts.runs) + len(counts.merges))),
                    Counter(
                        number
                        for inputs, _, _ in merge_numbers(counts)
                        for number in inputs
                    ),
                )
                # quicksort makes 60 / M runs of M (replacement selection makes runs of other lengths):
                if not selection:
                    self.assertEqual((memory,) * (60 // memory), counts.run_lengths)

    def test_f_m_minus_1_with_at_most_f_runs(self) -> None:
        """With M = 5 and F = M − 1 = 4, 10, 15 and 20 values in descending order make W = 2, 3 and 4 runs of 5 with
        both run generations (replacement selection makes runs of exactly M of a descending input). As W ≤ F, no merge
        comes before the final merge, which reads all W runs at level 1, here in the order they were made; written: N;
        read: N + N.

        Would fail if the sort merged while no more than F runs were left (e.g. a merge for W = F = 4), or if the
        final merge's runs were not all found when it reads more than three.
        """
        for runs in (2, 3, 4):
            for selection in (False, True):
                with self.subTest(runs=runs, replacement_selection=selection):
                    n: int = 5 * runs
                    counts: SortCounts[int] = sort_counted(
                        range(n - 1, -1, -1), 5, 4, selection
                    )
                    # W runs of 5, and only the final merge, which reads all of them at level 1:
                    self.assertEqual((5,) * runs, counts.run_lengths)
                    self.assertEqual(
                        [(tuple(range(runs)), None, 1)], merge_numbers(counts)
                    )
                    # the input written once to the runs and read twice, by phase 0 and by the final merge:
                    self.assertEqual(
                        (n, 0, n, n, 0, n, 2 * n), written_and_read(counts)
                    )


class CountingQueueTest(unittest.TestCase):
    """The queue that counts the elements written to it and read from it, notes when it was made and first read,
    and keeps the memory limits set on it."""

    def test_keeps_the_memory_limits_in_order(self) -> None:
        """The memory limits set on a queue are kept in the order they were set, and the last one is the queue's
        limit; a limit below 1 is refused as by every queue and not kept.

        Would fail if only the last limit were kept, so that a limit set by a merge and overwritten by a later one
        could not be seen.
        """
        queue: CountingQueue[int] = CountingQueue()
        # no limit set yet:
        self.assertEqual([], queue.memory_limits)
        # two limits, kept in order, the last one in force:
        queue.set_memory_limit(3)
        queue.set_memory_limit(1)
        self.assertEqual(([3, 1], 1), (queue.memory_limits, queue.memory_limit))
        # a limit of 0 raises and is not kept:
        with self.assertRaises(ValueError):
            queue.set_memory_limit(0)
        self.assertEqual([3, 1], queue.memory_limits)

    def test_a_sort_sets_one_value_per_run_of_a_merge_of_three(self) -> None:
        """With M = 4 and F = 3, each merge gives each of its three input runs one value of memory and its output
        run one value when it writes it (3 + 1 = M); the final merge gives each of the three output runs one value
        again: the runs of phase 0 get [1], the merges' outputs [1, 1].

        Would fail if the sort did not set the memory limit of a merge's output run, which leaves the outputs [1].
        """
        factory: CountingQueueFactory[int] = CountingQueueFactory()
        sort: ExternalMergeSort[int] = ExternalMergeSort(
            iter(range(36)), factory, number_of_tuples_in_main_memory=4, fan_in=3
        )
        # phase 0 and the merges, with the set-up of the final merge:
        sort.create_runs()
        sort.merge()
        # 9 runs of phase 0, read by the merges, then the 3 outputs, written by the merges and read by the final one:
        self.assertEqual(
            [[1]] * 9 + [[1, 1]] * 3, [queue.memory_limits for queue in factory.queues]
        )

    def test_counts_inserts_and_reads_but_not_the_end(self) -> None:
        """Inserting 3 elements counts 3 written; reading them to the end counts 3 read, and the call at the end,
        which raises StopIteration, reads nothing.

        Would fail if a read were counted before the list queue's ``__next__`` returned, so that every run read to its
        end counted one read too many.
        """
        queue: CountingQueue[int] = CountingQueue[int]()
        # insert 3 elements, none read yet:
        for value in (30, 20, 10):
            queue.insert(value)
        self.assertEqual((3, 0), (queue.written, queue.read))
        # read all 3; list() also makes the call at the end that raises StopIteration:
        self.assertEqual([30, 20, 10], list(queue))
        self.assertEqual(3, queue.read)
        # one more call at the end still reads nothing:
        with self.assertRaises(StopIteration):
            next(queue)
        self.assertEqual((3, 3), (queue.written, queue.read))

    def test_made_and_first_read_on_the_factorys_clock(self) -> None:
        """The queues of one factory share its clock: two queues are made at times 0 and 1; reading the second, then
        the first, notes first reads at times 2 and 3; reading the first again keeps time 3 and does not advance the
        clock, so the next queue is made at time 4. The factory keeps its queues in the order they were made.

        Would fail if each queue had a clock of its own, which would make the order of events between queues
        unknowable, or if a later read overwrote the time of the first.
        """
        factory: CountingQueueFactory[int] = CountingQueueFactory[int]()
        first: CountingQueue[int] = factory.get_queue_instance()
        second: CountingQueue[int] = factory.get_queue_instance()
        # made at times 0 and 1, not read yet:
        self.assertEqual((0, 1), (first.made, second.made))
        self.assertEqual((None, None), (first.first_read, second.first_read))
        # fill both, read the second before the first:
        for queue in (first, second):
            queue.insert(7)
            queue.insert(8)
        self.assertEqual(7, next(iter(second)))
        self.assertEqual(7, next(iter(first)))
        self.assertEqual((3, 2), (first.first_read, second.first_read))
        # reading the first again from its start keeps the time of its first read:
        self.assertEqual([7, 8], list(first))
        self.assertEqual(3, first.first_read)
        # the next queue is made at time 4, and the factory keeps all three in order:
        third: CountingQueue[int] = factory.get_queue_instance()
        self.assertEqual(4, third.made)
        self.assertEqual([first, second, third], factory.queues)

    def test_a_queue_without_a_clock_has_its_own(self) -> None:
        """A queue made without a clock starts a clock of its own: it is made at time 0 and first read at time 1, and
        a second such queue is made at time 0 as well.

        Would fail if queues without a clock shared one, so that the times of one depended on the others.
        """
        queue: CountingQueue[str] = CountingQueue[str]()
        other: CountingQueue[str] = CountingQueue[str]()
        self.assertEqual((0, 0), (queue.made, other.made))
        # its first read is the next tick of its own clock:
        queue.insert("x")
        self.assertEqual("x", next(queue))
        self.assertEqual(1, queue.first_read)


class CountingInputTest(unittest.TestCase):
    """The iterator that counts the elements read from the input."""

    def test_counts_the_values_read_but_not_the_end(self) -> None:
        """Reading 3 values counts 3; the call at the end, which raises StopIteration, reads nothing.

        Would fail if a value were counted before the input returned it.
        """
        source: CountingInput[int] = CountingInput(iter((5, 3, 8)))
        # one value, then the rest:
        self.assertEqual(5, next(source))
        self.assertEqual(1, source.read)
        self.assertEqual([3, 8], list(source))
        # one more call at the end still reads nothing:
        with self.assertRaises(StopIteration):
            next(source)
        self.assertEqual(3, source.read)


class MergeOrderTest(unittest.TestCase):
    """The order of events the counting relies on: :class:`SingleStreamMerge` reads the first element of each of its
    input runs before :class:`ExternalMergeSort` asks the queue factory for the merge's output queue.
    """

    def test_a_merge_reads_its_inputs_before_its_output_queue_is_made(self) -> None:
        """On a :class:`CountingQueueFactory` used directly with :class:`ExternalMergeSort`, every input of a merge is
        first read after the queue made before the merge's output queue, and before the output queue is made; the
        inputs of the final merge are first read after the last queue was made.

        Would fail if ``sorting.py`` asked for a merge's output queue before the merge read its inputs, or read a
        merge's inputs before the previous merge's output queue was made; the counting then finds wrong merges.
        """
        for name, (values, memory, fan_in, selection) in MERGE_CASES.items():
            with self.subTest(case=name):
                noted: NotedSort = sort_and_note_merges(
                    values, memory, fan_in, selection
                )
                queues: list[CountingQueue[int]] = noted.factory.queues
                # the k-th merge writes the k-th queue made after phase 0:
                self.assertEqual(len(queues) - noted.phase_0, len(noted.merges))
                for index, inputs in enumerate(noted.merges, start=noted.phase_0):
                    output: CountingQueue[int] = queues[index]
                    # the pairing is right: the output holds the elements of its inputs, merged:
                    self.assertEqual(
                        sorted(element for queue in inputs for element in queue.buffer),
                        output.buffer,
                    )
                    # every input was first read between the making of the queue before the output and the output's:
                    for queue in inputs:
                        self.assertLess(queues[index - 1].made, queue.first_read)
                        self.assertLess(queue.first_read, output.made)
                # the final merge's inputs were first read after the last queue was made:
                for queue in noted.final_merge:
                    self.assertLess(queues[-1].made, queue.first_read)

    def test_found_merges_are_those_the_sort_made(self) -> None:
        """The merges ``sort_counted`` finds from the times on its queues read the runs the sort gave each
        :class:`SingleStreamMerge`, in the same order; the final merge's inputs are the runs on the sort's heap after
        ``merge()``.

        Would fail if the merges were found by another rule than the order of first reads, e.g. by taking F runs in
        the order of their numbers.
        """
        for name, (values, memory, fan_in, selection) in MERGE_CASES.items():
            with self.subTest(case=name):
                noted: NotedSort = sort_and_note_merges(
                    values, memory, fan_in, selection
                )
                counts: SortCounts[int] = sort_counted(
                    values, memory, fan_in, selection
                )
                # the merges before the final merge, as run numbers in the order they were read:
                self.assertEqual(
                    [noted.numbers(inputs) for inputs in noted.merges],
                    [
                        tuple(run.number for run in merge.inputs)
                        for merge in counts.merges
                    ],
                )
                # the final merge reads the runs left on the sort's heap:
                final: tuple[int, ...] = tuple(
                    run.number for run in counts.final_merge.inputs
                )
                self.assertEqual(noted.numbers(noted.final_merge), final)
                self.assertEqual(sorted(noted.numbers(noted.heap)), sorted(final))

    def test_a_broken_order_raises_a_runtime_error(self) -> None:
        """If the sort asks for a merge's output queue before the merge reads its inputs, ``sort_counted`` finds no
        input runs for that output queue (queue 4, the first after the slides' 4 runs) and raises a RuntimeError
        instead of returning wrong merges.

        Would fail if ``sort_counted`` did not check that the runs found for a merge add up to its output.
        """
        with mock.patch.object(
            ExternalMergeSort,
            "_grab_next_fan_in_runs_and_merge_them",
            merge_output_queue_first,
        ):
            with self.assertRaisesRegex(RuntimeError, "before output queue 4 was made"):
                sort_counted(SLIDES, 4, 2, False)

    def test_a_final_merge_of_other_runs_raises_a_runtime_error(self) -> None:
        """If the final merge read other runs than those left on the sort's heap, ``sort_counted`` raises a
        RuntimeError: replacement selection makes the slides' 2 runs, and a final merge that reads only the first
        run on the heap leaves the runs found for it (1) different from those on the heap (2).

        Would fail if ``sort_counted`` did not compare the final merge's runs with the runs left on the heap.
        """

        def merge_without_the_last_run(sort: ExternalMergeSort[int]) -> None:
            """Sets up a final merge of all runs on the heap but the last, without any merge before it."""
            sort.final_merge = SingleStreamMerge(
                sort.heap[:-1], sort.queue_factory, sort.number_of_tuples_in_main_memory
            )

        # the final merge reads one run, while two are left on the heap:
        with mock.patch.object(ExternalMergeSort, "merge", merge_without_the_last_run):
            with self.assertRaisesRegex(RuntimeError, "not those of the final merge"):
                sort_counted(SLIDES, 4, 2, True)


if __name__ == "__main__":
    unittest.main()
