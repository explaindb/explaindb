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
"""Tests that the runs, merges and page counts of the external sorting page are those of the repository's code.

The page (``visualizations/external-sorting.html``) shows the code's ``ExternalMergeSort`` with a main memory of 64
values (4 pages of 16) and fan-in 3 on table R, the 576 keys of ``INPUT`` in its script. These tests run the code on
``INPUT``, note the runs that pass 0 writes and the runs that each merge reads, and compare them with the runs and the
merge groups that ``external_sorting_page_data.py`` expects; they also compare the pages that the code's runs fill
with the page counts there, against which ``ExternalSortingPageTest`` in ``test_visualizations.py`` checks the page's
counter, and each merge's heap with the replay there, against which it checks the page's heap stand.
``ExternalSortingPageDataReadersTest`` checks that module's page count and readers, and merge_heaps' input check, on
small cases.
"""

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from system.interfaces.queues import QueueFactory
from system.query_processing.queues.queue_factories import ListQueueFactory
from system.query_processing.sorting import (
    ExternalMergeSort,
    RunGenerationResult,
    RunGenerator,
    RunMetadata,
    SingleStreamMerge,
)
from system.tests.repo.external_sorting_page_data import (
    EXPECTED_GROUPS,
    EXPECTED_PASS_COUNTS,
    EXPECTED_READS,
    EXPECTED_WRITES,
    FAN_IN,
    MEMORY_VALUES,
    VALUES_PER_PAGE,
    PageCounts,
    merge_heaps,
    merged_runs,
    pages_of,
    pass_0_runs,
    pass_page_counts,
    read_groups,
    read_input,
)


@dataclass
class NotedRun:
    """A run of the code's sort as the test notes it: its values, in order, and its size as the code keeps it."""

    values: list[int]
    # RunMetadata.size, the number of values the code counts in the run's queue:
    size: int


@dataclass
class SortRecord:
    """What the code's external merge sort did with R, as run_sort notes it."""

    # the runs that pass 0 writes, in the order it writes them:
    runs: list[NotedRun]
    # for each merge, in the order the code starts them, the runs it reads; the last one is the final merge:
    merges: list[list[NotedRun]]
    # for each merge, in the same order, the values on its heap by place (the root first, then its children) before
    # each value it gives out:
    heaps: list[list[list[int]]]
    # the sorted output, as the final merge returns it:
    output: list[int]


def note(run: RunMetadata) -> NotedRun:
    """Returns a run's values and size, read from its queue (a ListQueue, which can be read again from its start)."""
    return NotedRun(values=list(run.queue), size=run.size)


def run_sort(values: list[int]) -> SortRecord:
    """Sorts values with the code's ExternalMergeSort, with memory for 64 values and fan-in 3, as the page does, and
    notes the runs of pass 0 and the inputs and heaps of each merge.

    @param values: the input (R)
    @return: the runs, the merges' inputs and heaps, and the output
    """
    runs: list[NotedRun] = []
    merges: list[list[NotedRun]] = []
    heaps: list[list[list[int]]] = []
    # the merges in the order they were started, kept alive so that each is found by its identity:
    started: list[SingleStreamMerge] = []
    create_runs = RunGenerator.create_runs
    start_merge = SingleStreamMerge.__init__
    give_out = SingleStreamMerge.__next__

    def note_runs(generator: RunGenerator) -> RunGenerationResult:
        """Creates the runs as the code does, then notes them in the order pass 0 wrote them (before the sort puts
        them into its heap)."""
        result: RunGenerationResult = create_runs(generator)
        runs.extend(note(run) for run in result.runs_metadata)
        return result

    def note_merge(
        merge: SingleStreamMerge,
        run_infos: list[RunMetadata],
        queue_factory: QueueFactory,
        number_of_tuples_in_main_memory: int,
    ) -> None:
        """Notes the runs a merge reads, before it starts reading them, then sets it up as the code does."""
        merges.append([note(run) for run in run_infos])
        start_merge(merge, run_infos, queue_factory, number_of_tuples_in_main_memory)
        started.append(merge)
        heaps.append([])

    def note_heap(merge: SingleStreamMerge) -> object:
        """Notes the values on a merge's heap by place before it gives out its next value, then gives that out as
        the code does (or ends the merge, once its heap is empty)."""
        if merge.heap:
            index: int = next(i for i, other in enumerate(started) if other is merge)
            heaps[index].append([entry.value for entry in merge.heap])
        return give_out(merge)

    # the code's own sort, with the runs and each merge's inputs and heaps noted on the way:
    with (
        mock.patch.object(RunGenerator, "create_runs", note_runs),
        mock.patch.object(SingleStreamMerge, "__init__", note_merge),
        mock.patch.object(SingleStreamMerge, "__next__", note_heap),
    ):
        sort: ExternalMergeSort[int] = ExternalMergeSort[int](
            iter(values), ListQueueFactory[int](), MEMORY_VALUES, FAN_IN
        )
        sort.create_runs()
        sort.merge()
        output: list[int] = list(sort)
    return SortRecord(runs=runs, merges=merges, heaps=heaps, output=output)


class ExternalSortingPageDataTest(unittest.TestCase):
    """Checks the runs, merges and page counts of the external sorting page against the repository's external merge
    sort."""

    def setUp(self) -> None:
        """Reads R from the page, sorts it with the code and works out the runs that the page expects."""
        # INPUT: the keys of table R, in the order of its pages:
        self.values: list[int] = read_input()
        self.record: SortRecord = run_sort(self.values)
        # the runs r1 … r9 of pass 0, then r10 … r12 of merge level 1, as the page draws them:
        self.runs: list[list[int]] = pass_0_runs(self.values)
        self.level_2_runs: list[list[int]] = merged_runs(self.runs, EXPECTED_GROUPS)

    def name_of(self, values: list[int]) -> str:
        """Returns the page's name of the run with these values (r1 … r12), or says that no run of the page has them.

        @param values: the values of a run, in order
        @return: e.g. ``r3``; for values that are no run of the page, how many there are
        """
        for number, run in enumerate(self.runs + self.level_2_runs, 1):
            if run == values:
                return f"r{number}"
        return f"no run of the page ({len(values)} values)"

    def test_r_holds_576_distinct_keys_from_100_to_999(self) -> None:
        """INPUT holds 576 keys, each once, all from 100 to 999: 36 full pages of 16, 9 loads of the 4-page memory.

        Fails if INPUT is edited so that a key is there twice (a tie in a merge, which the page's mergeByHeap may settle
        otherwise than the code's heap), a key falls outside 100 … 999 (its blue bar, key / 1000 of the full length,
        would overrun its parcel or almost vanish), or R no longer fills 9 memory loads of 4 full pages.
        """
        # 576 keys, each once:
        self.assertEqual(576, len(self.values))
        self.assertEqual(len(self.values), len(set(self.values)))

        # all with three digits:
        self.assertGreaterEqual(min(self.values), 100)
        self.assertLessEqual(max(self.values), 999)

        # 36 full pages, 9 full loads of memory:
        self.assertEqual((36, 0), divmod(len(self.values), VALUES_PER_PAGE))
        self.assertEqual((9, 0), divmod(len(self.values), MEMORY_VALUES))

    def test_pass_0_writes_the_runs_of_the_page(self) -> None:
        """The code's pass 0 writes the 9 runs of the page, in order: each the next 64 keys of R, sorted.

        Fails if RunGenerator cuts R into pieces of another size or in another order than the page's bench, which
        loads pages 1 to 4 of R for r1, 5 to 8 for r2, and so on.
        """
        # the runs' values, in order:
        self.assertEqual(self.runs, [run.values for run in self.record.runs])
        # their sizes:
        self.assertEqual([64] * 9, [run.size for run in self.record.runs])

    def test_the_merges_take_the_groups_of_the_page(self) -> None:
        """The code merges three groups of three runs of pass 0, the groups EXPECTED_GROUPS, in their order
        (r1, r2, r3 into r10, r4, r5, r6 into r11, r7, r8, r9 into r12: runs of the same size, oldest first), then the
        three runs these merges wrote in the final merge, r10, r11, r12; each merge reads its runs in this order. The
        page's GROUPS are the same groups, in the same order, each with its runs in the same order.

        The runs are compared by their values. Fails if the code's heap hands out the runs of the same size in another
        order (e.g. after a change to RunMetadata.__lt__ or to how runs are pushed), so that the page would merge other
        runs than the code or fill its heap from them in another order, or if the page's GROUPS change without the
        code.
        """
        # each merge's input runs, in the order the merge reads them, by the page's names for them:
        merged: list[list[str]] = [
            [self.name_of(run.values) for run in merge] for merge in self.record.merges
        ]

        # three merges of level 1 in the page's groups, then the final merge of r10, r11 and r12:
        expected: list[list[str]] = [
            [f"r{place + 1}" for place in group] for group in EXPECTED_GROUPS
        ] + [["r10", "r11", "r12"]]
        self.assertEqual(expected, merged)

        # the page merges the same groups, in the same order:
        self.assertEqual(EXPECTED_GROUPS, read_groups())

    def test_merge_heaps_replays_the_heap_of_each_merge(self) -> None:
        """Before each value that the code's SingleStreamMerge gives out, its heap holds the values that merge_heaps
        replays for the page's inputs of that merge (each group of EXPECTED_GROUPS, then r10, r11, r12), on the same
        places: the root, then its two children. ExternalSortingPageTest compares the page's heap stand with this
        replay.

        Fails if the code's heap changes its layout (e.g. another way of sinking a new root, or entries put in another
        order) without the replay, so that the page's heap stand would no longer show the code's heap, or if the replay
        loses or repeats a value.
        """
        # the inputs of the page's merges, in the order each merge reads them:
        inputs: list[list[list[int]]] = [
            [self.runs[place] for place in group] for group in EXPECTED_GROUPS
        ] + [self.level_2_runs]

        # the replay, merge by merge, is the code's heap before each value given out:
        replayed: list[list[list[int]]] = [merge_heaps(runs) for runs in inputs]
        self.assertEqual(len(self.record.heaps), len(replayed))
        for number, (code, replay) in enumerate(zip(self.record.heaps, replayed), 1):
            with self.subTest(merge=number):
                self.assertEqual(code, replay)
                # one heap per value given out, its root that value, in ascending order:
                self.assertEqual(
                    sorted(value for runs in inputs[number - 1] for value in runs),
                    [heap[0] for heap in replay],
                )

    def test_the_sort_returns_r_in_ascending_order(self) -> None:
        """The final merge returns all 576 keys of R in ascending order, the green pages the page pushes to the query.

        Fails if a merge loses, repeats or misorders keys, so that the code's result would differ from the page's.
        """
        # the final merge's output, against R sorted:
        self.assertEqual(sorted(self.values), self.record.output)

    def test_the_code_s_runs_fill_the_pages_the_counter_counts(self) -> None:
        """Counted in pages of 16 values from the sizes of the code's runs, each pass reads all 36 pages and pass 0 and
        merge level 1 write all 36 again, the final merge none: 108 reads and 72 writes, as the page's counter shows
        at the end (ExternalSortingPageTest).

        Fails if the code makes runs of other sizes (e.g. merge level 1 writes 4 runs, or a fourth pass is needed), so
        that the code would read or write another number of pages than the page counts.
        """
        runs: list[NotedRun] = self.record.runs
        level_1: list[list[NotedRun]] = self.record.merges[:-1]
        final: list[NotedRun] = self.record.merges[-1]

        # pass 0 reads R and writes its runs; merge level 1 reads those and writes the runs that the final merge reads
        # (test_the_merges_take_the_groups_of_the_page checks that these are the runs level 1 wrote); the final merge
        # writes nothing:
        passes: list[PageCounts] = [
            pass_page_counts([len(self.values)], [run.size for run in runs]),
            pass_page_counts(
                [run.size for merge in level_1 for run in merge],
                [run.size for run in final],
            ),
            pass_page_counts([run.size for run in final], []),
        ]
        self.assertEqual(EXPECTED_PASS_COUNTS, passes)

        # all three passes together, as the counter shows them at the end:
        self.assertEqual(
            PageCounts(EXPECTED_READS, EXPECTED_WRITES),
            PageCounts(
                sum(counts.reads for counts in passes),
                sum(counts.writes for counts in passes),
            ),
        )


class ExternalSortingPageDataReadersTest(unittest.TestCase):
    """Checks the page count and the readers of external_sorting_page_data.py on small cases that the page's own data
    does not reach: runs whose last page is not full, scripts whose INPUT or GROUPS the readers cannot read, and runs
    with a value twice, which merge_heaps rejects.
    """

    def write_page(self, script: str) -> Path:
        """Writes an HTML file with the given script into a folder that is removed after the test.

        @param script: the script's text, e.g. ``const GROUPS = [[0, 1, 2]];``
        @return: the file
        """
        folder: Path = Path(self.enterContext(tempfile.TemporaryDirectory()))
        page: Path = folder / "external-sorting.html"
        page.write_text(f"<script>\n{script}\n</script>\n", encoding="utf-8")
        return page

    def test_a_run_s_last_page_counts_even_if_it_is_not_full(self) -> None:
        """pages_of counts a page for every 16 values begun, and pass_page_counts starts each run on a page of its own:
        a run of 17 values fills 2 pages, and two of them fill 4, not the 3 that their 34 values would fill together.

        Fails if a page that a run fills only in part is not counted (e.g. 65 values as 4 pages) or runs are counted as
        one, so that a change of the code's run sizes to a size that is not a multiple of 16 could keep the page
        counts that ExternalSortingPageDataTest compares.
        """
        # a page for every 16 values begun:
        self.assertEqual(
            [1, 1, 2, 4, 5], [pages_of(size) for size in (1, 16, 17, 64, 65)]
        )

        # each run on pages of its own, those read and those written apart:
        self.assertEqual(
            PageCounts(reads=4, writes=5), pass_page_counts([17, 17], [65])
        )

    def test_read_input_takes_only_a_list_of_whole_numbers(self) -> None:
        """read_input reads INPUT as the page writes it, whole numbers over several lines with a comma after the last;
        a script without such a list, e.g. with INPUT computed, with a decimal or a negative key, or only in a comment,
        makes it raise ValueError instead of reading part of it.

        Fails if read_input reads a list it cannot take whole (e.g. drops a minus sign or a decimal point) or an INPUT
        left in a comment, so that the tests would check other keys than those the page sorts.
        """
        # the page's way of writing INPUT:
        page: Path = self.write_page("  const INPUT = [\n    983, 969,\n    157,\n  ];")
        self.assertEqual([983, 969, 157], read_input(page))

        # no list of whole numbers to read:
        scripts: dict[str, str] = {
            "missing": "const R = [983, 969];",
            "computed": "const INPUT = sample(range(100, 1000), 576);",
            "decimal": "const INPUT = [983, 96.9];",
            "negative": "const INPUT = [983, -969];",
            "in a comment": "// const INPUT = [983, 969];",
        }
        for case, script in scripts.items():
            with self.subTest(case=case):
                with self.assertRaisesRegex(ValueError, "has no array 'const INPUT"):
                    read_input(self.write_page(script))

    def test_read_groups_takes_only_groups_on_one_line(self) -> None:
        """read_groups reads GROUPS from its one line in the script, as the page writes it; a script without it, or
        with GROUPS spread over several lines, makes it raise ValueError.

        Fails if read_groups reads only a part of GROUPS spread over lines, or another array, so that the groups that
        test_the_merges_take_the_groups_of_the_page compares would not be the page's.
        """
        # the page's way of writing GROUPS:
        page: Path = self.write_page("  const GROUPS = [[0, 1, 2], [3, 4, 5]];")
        self.assertEqual([[0, 1, 2], [3, 4, 5]], read_groups(page))

        # no line to read:
        scripts: dict[str, str] = {
            "missing": "const RUNS = [[0, 1, 2]];",
            "over lines": "const GROUPS = [\n  [0, 1, 2],\n  [3, 4, 5],\n];",
        }
        for case, script in scripts.items():
            with self.subTest(case=case):
                with self.assertRaisesRegex(ValueError, "has no line 'const GROUPS"):
                    read_groups(self.write_page(script))

    def test_merge_heaps_takes_only_distinct_values(self) -> None:
        """merge_heaps raises ValueError if a value occurs twice, in two runs or in one: with equal values the replay
        would break ties otherwise than the code's heap.

        Fails if the check is removed. No other test reaches the check, as the page's keys are all distinct.
        """
        # the same value in two runs, and twice in one run:
        repeats: dict[str, list[list[int]]] = {
            "two runs": [[1, 2], [2, 3]],
            "one run": [[1, 1]],
        }
        for case, runs in repeats.items():
            with self.subTest(case=case):
                with self.assertRaisesRegex(ValueError, "distinct values only"):
                    merge_heaps(runs)

        # distinct values are replayed: each value given out is the smallest of the heap's values just before:
        self.assertEqual([[1, 2], [2, 3], [3]], merge_heaps([[1, 3], [2]]))


if __name__ == "__main__":
    unittest.main()
