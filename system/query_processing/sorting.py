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

"""External merge sort: runs by chunk sorting or replacement selection (textbook heap), multi-way merging (heapq)."""

import heapq
import itertools
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Protocol

from system.interfaces.queues import (
    QueueFactory,
    ReadWriteQueue,
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)


class RunMetadata:
    """RunMetadata is a helper class allowing us to keep track of queues in external memory algorithms."""

    # numbers the runs in the order they are made (see __lt__):
    _made: Iterator[int] = itertools.count()

    def __init__(self, queue: ReadWriteQueue, size: int):
        """Initializes the RunMetadata.

        @param queue: The queue instance representing the run.
        @param size: The size of the run.

        """
        self.queue: ReadWriteQueue = queue
        self.size: int = size
        # when the run was made, relative to the other runs (a smaller number: made earlier):
        self.number: int = next(RunMetadata._made)

    def __lt__(self, other):
        """The smallest run has the highest priority. This leads to a bottom-up merge in a recursive merge sort. Of
        runs of the same size, the one made first comes first, so that such runs are merged in the order they were
        made (runs 1 to 3 first, not, say, runs 1, 3 and 7 as the heap's internal order would have it).

        @param other: The other RunMetadata to compare with.
        """

        return (self.size, self.number) < (other.size, other.number)

    def __str__(self):
        """Human-readable summary showing the number of elements in the run."""
        return f"RunMetadata:  {self.size} elements"


@dataclass
class RunGenerationResult:
    """RunGenerationResult is a helper class to store the result of the run generation phase."""

    # list of RunMetadata instances:
    runs_metadata: list[RunMetadata]

    # total number of elements written while creating runs:
    elements_written: int


class Comparable(Protocol):
    """An element that the sorting code in this module can order: it supports ``<``."""

    def __lt__(self, other: Any, /) -> bool:
        """Whether this element comes before ``other``."""


def sift_down[ObjectType: Comparable](heap: list[ObjectType], position: int) -> None:
    """Moves the element at ``position`` down the heap until no child is smaller: it swaps with its smaller child
    (the left one, unless the right one is smaller) and stops above a child that is not smaller, including an equal
    one. The heap is a list in level order: the children of position i are at 2i + 1 and 2i + 2. Only ``<`` is used.

    @param heap: The list whose subtrees below ``position`` are heaps already.
    @param position: The index of the element to move down.
    """
    size: int = len(heap)
    # walk down, one level per round, until the element has no smaller child:
    while True:
        # the left child of the position (the right child, if there is one, follows it):
        child: int = 2 * position + 1
        if child >= size:
            # a leaf: no child to compare with:
            return
        # the smaller of the two children (the left one if they are equal):
        if child + 1 < size and heap[child + 1] < heap[child]:
            child += 1
        # the element stays where it is if the smaller child is not smaller (also if it is equal):
        if not heap[child] < heap[position]:
            return
        # the smaller child moves up, the element one level down, and the walk goes on from there:
        heap[position], heap[child] = heap[child], heap[position]
        position = child


def bulkload[ObjectType: Comparable](elements: list[ObjectType]) -> None:
    """Turns ``elements`` into a heap in place in linear time (Floyd's method): every inner node is moved down with
    ``sift_down``, from the last inner node up to the root, so each node moves down only into subtrees that are
    heaps already.

    @param elements: The list to turn into a heap.
    """
    # the inner nodes are the positions 0 to len // 2 - 1; the leaves after them are heaps of one element each.
    # From the last inner node up to the root, both subtrees of a node are heaps already when it moves down:
    for position in reversed(range(len(elements) // 2)):
        sift_down(elements, position)


class ReplacementSelection[ObjectType: Comparable](Iterator[tuple[int, ObjectType]]):
    """Run generation by replacement selection. Main memory holds M elements (``number_of_tuples_in_main_memory``),
    split into a heap (``heap``) for the current run and a list (``pending``, the slides' "list") for the next one.
    Each step outputs the root of the heap and reads the next input element: if it is not smaller than that output,
    it still fits into the current run and goes into the heap, else it goes into the list. When the heap is empty,
    the list is bulk-loaded into a heap and the next run starts. Yields (run number, element); run numbers start at
    0 for each instance (``run`` is -1 until the first run starts). ``heap``, ``pending`` and ``run`` can be read
    between steps; ``start_next_run`` makes the list the new ``heap`` and gives ``pending`` a new empty list, so read
    both again after each step.
    """

    def __init__(
        self, input_data: Iterable[ObjectType], number_of_tuples_in_main_memory: int
    ):
        """Reads the first M elements into the list; the first call of ``start_next_run`` (or of ``__next__``)
        bulk-loads them into the heap and starts run 0.

        @param input_data: The input data to create runs from.
        @param number_of_tuples_in_main_memory: M, the number of elements heap and list may hold together.
        @raise ValueError: if M is less than 1.
        """
        if number_of_tuples_in_main_memory < 1:
            raise ValueError(
                f"number_of_tuples_in_main_memory must be at least 1, got {number_of_tuples_in_main_memory}"
            )
        self.input_data: Iterator[ObjectType] = iter(input_data)
        # the elements of the current run, as a heap:
        self.heap: list[ObjectType] = list[ObjectType]()
        # the elements for the next run (the "list" of the slides), initially the first M input elements:
        self.pending: list[ObjectType] = list(
            itertools.islice(self.input_data, number_of_tuples_in_main_memory)
        )
        # the number of the current run, from 0 on (-1 until the first run starts):
        self.run: int = -1

    def start_next_run(self) -> bool:
        """If the heap is empty and the list (``pending``) is not, bulk-loads the list into the heap and starts the
        next run. ``__next__`` calls it whenever the heap is empty; it is public so that a caller can call it first
        and look at the new heap before the run's first output.

        @return: True if a run was started, False if nothing changed (the heap still holds elements, or the list is
        empty).
        """
        # a new run starts only when the current one is over (empty heap) and elements wait for it:
        if self.heap or not self.pending:
            return False
        # the list becomes the new run's heap, and an empty list collects the elements for the run after it:
        self.heap, self.pending = self.pending, list[ObjectType]()
        # turn the list into a heap, in linear time:
        bulkload(self.heap)
        self.run += 1
        return True

    def _remove_root(self) -> None:
        """Removes the root of the heap: the heap's last element takes the root's place and moves down."""
        # take the last element off, so the heap stays a complete tree:
        last: ObjectType = self.heap.pop()
        # unless it was the root itself, it takes the root's place and moves down:
        if self.heap:
            self.heap[0] = last
            sift_down(self.heap, 0)

    def __next__(self) -> tuple[int, ObjectType]:
        """Outputs the root of the heap and reads the next input element into memory. If the heap is empty, the next
        run is started first (``start_next_run``).

        @return: The run number and the element written to that run.
        @raise StopIteration: when heap and list are both empty.
        """
        # an empty heap ends the run: start the next one, or stop if the list is empty too:
        if not self.heap and not self.start_next_run():
            raise StopIteration
        # the root, the smallest element of the heap, is the run's next output:
        output: ObjectType = self.heap[0]
        # read the next input element into the place the output frees:
        try:
            next_element: ObjectType = next(self.input_data)
        except StopIteration:
            # no input is left: the heap shrinks:
            self._remove_root()
            return self.run, output
        if next_element < output:
            # the next element is smaller than the output, so it waits in the list for the next run:
            self._remove_root()
            self.pending.append(next_element)
        else:
            # the next element still fits into this run: it takes the root's place and moves down:
            self.heap[0] = next_element
            sift_down(self.heap, 0)
        return self.run, output

    def __iter__(self) -> Iterator[tuple[int, ObjectType]]:
        """Returns the iterator object."""
        return self


class RunGenerator[ObjectType: Comparable]:
    """Phase 0 of external merge sort: makes sorted runs, each written to a new queue from the queue factory,
    either by sorting memory-sized chunks or by replacement selection.
    """

    def __init__(
        self,
        input_data: Iterator[ObjectType],
        queue_factory: QueueFactory,
        number_of_tuples_in_main_memory: int = 1000,
        replacement_selection: bool = False,
    ):
        """Initializes the RunGenerator.

        @param queue_factory: The factory to use to create read and write queues.
        @param input_data: The input data to create runs from.
        @param number_of_tuples_in_main_memory: The number of tuples that can be stored in memory.
        @param replacement_selection: Make the runs by replacement selection instead of sorting chunks. Then
        ``create_runs`` raises a ValueError if ``number_of_tuples_in_main_memory`` is less than 1; chunk sorting does
        not check it.
        """

        self.queue_factory: QueueFactory = queue_factory
        self.input_data: Iterator[ObjectType] = input_data
        self.number_of_tuples_in_main_memory: int = number_of_tuples_in_main_memory
        self.replacement_selection: bool = replacement_selection

    def _finish_run(self, queue: ReadWriteQueue[ObjectType]) -> RunMetadata:
        """Flushes a run's queue and returns the run's metadata (its queue and size). The queue stays open, as the
        merge reads the run from it.

        @param queue: The queue holding the run.
        @return: The metadata of the run.
        """
        # write what the queue still buffers (a disk-backed queue writes it to its file):
        queue.flush()
        return RunMetadata(queue=queue, size=queue.size())

    def _create_runs_by_replacement_selection(self) -> RunGenerationResult:
        """Writes the output of replacement selection to one new queue per run.

        @return: A RunGenerationResult with the metadata of all runs and the number of elements written.
        @raise ValueError: if ``number_of_tuples_in_main_memory`` is less than 1.
        """
        runs_metadata: list[RunMetadata] = list[RunMetadata]()
        selection: ReplacementSelection[ObjectType] = ReplacementSelection(
            self.input_data, self.number_of_tuples_in_main_memory
        )
        # the queue of the run being written (none before the first element), and its run number:
        queue: ReadWriteQueue[ObjectType] | None = None
        current_run_number: int = 0
        for run_number, element in selection:
            if queue is None or run_number != current_run_number:
                # the first element, or a new run number: finish the current run (if any) and open a new queue:
                if queue is not None:
                    runs_metadata.append(self._finish_run(queue))
                queue = self.queue_factory.get_queue_instance()
                current_run_number = run_number
            queue.insert(element)
        # the last run (none for empty input):
        if queue is not None:
            runs_metadata.append(self._finish_run(queue))
        return RunGenerationResult(
            runs_metadata, sum(metadata.size for metadata in runs_metadata)
        )

    def create_runs(self) -> RunGenerationResult:
        """Reads the input data in chunks of ``number_of_tuples_in_main_memory`` elements, sorts each chunk in memory
        and writes it as a sorted run to a new queue from the queue factory. With ``replacement_selection``, makes the
        runs by replacement selection instead (see :class:`ReplacementSelection`).

        @return: A RunGenerationResult with the metadata of all runs and the number of elements written.
        @raise ValueError: with ``replacement_selection``, if ``number_of_tuples_in_main_memory`` is less than 1.
        """
        if self.replacement_selection:
            return self._create_runs_by_replacement_selection()
        runs_metadata: list[RunMetadata] = list[RunMetadata]()
        elements_written: int = 0

        while True:
            buffer: list[ObjectType] = list[ObjectType]()
            count: int = 0
            # draw elements from the input data iterator and append them to the buffer:
            for element in self.input_data:
                buffer.append(element)
                count += 1
                if count >= self.number_of_tuples_in_main_memory:
                    break
            # exit the loop if no more elements are available:
            if count == 0:
                break

            # sort the buffer:
            buffer.sort()

            # get a queue instance:
            queue: ReadWriteQueue[ObjectType] = self.queue_factory.get_queue_instance()

            # insert the data into the queue:
            for element in buffer:
                queue.insert(element)

            # flush the queue (to allow memory-backed implementations to flush to disk):
            queue.flush()

            # the size of the run is the number of elements in its queue:
            elements_in_run: int = queue.size()

            # add the run metadata for this run/queue to the list of run metadata:
            runs_metadata.append(RunMetadata(queue=queue, size=elements_in_run))

            # update the number of elements written:
            elements_written += elements_in_run

        return RunGenerationResult(runs_metadata, elements_written)


class SingleStreamMerge[ObjectType](Iterator):
    """Merges k sorted input streams into a single sorted output stream. This is a single merge, not a recursive
    merge. As this implementation is lazy/demand-driven it can also be used for the final merge of a recursive merge.
    """

    class HeapEntry[ObjectType]:
        """HeapEntry is a helper class to store the value of an element and the read queue it came from. It is used
        to store the smallest element (=highest priority) of each run in the heap."""

        def __init__(self, queue: ReadWriteQueue):
            """Initializes the HeapEntry.

            @param queue: The queue to get the next element from.
            """
            self.queue = queue
            # iterator rewiring:
            self.iterator = iter(queue)
            self.value: ObjectType = self.iterator.__next__()

        def __lt__(self, other: ObjectType):
            """Less than operator to compare heap entries by their value. Override less than operator of value to have
            other sort orders

            @param other: The other HeapEntry to compare with.
            """
            return self.value < other.value

    def __init__(
        self,
        run_infos: list[RunMetadata],
        queue_factory: QueueFactory,
        number_of_tuples_in_main_memory: int,
    ):
        """Initializes the SingleStreamMerge.

        @param run_infos: The list of RunMetadata objects containing the runs to merge, i.e. the runs to merge.
        @param queue_factory: Not used by the merge: it reads from the queues of the given runs.
        @param number_of_tuples_in_main_memory: The number of tuples that can be stored in memory.
        """

        self.run_infos = run_infos
        self.queue_factory = queue_factory
        self.number_of_tuples_in_main_memory = number_of_tuples_in_main_memory

        self._initialize_heap()

    def _initialize_heap(self):
        """Initializes the heap with the first element of each run."""

        # heap to decide from which input run to take the next element,
        # i.e. which input run contains the next smallest element:
        self.heap = list[SingleStreamMerge.HeapEntry[ObjectType]]()

        # create a heap entry for each input run given:
        run_info: RunMetadata
        for run_info in self.run_infos:
            queue: ReadWriteQueue[ObjectType] = run_info.queue

            # give each queue the same memory limit:
            memory_per_queue: int = self.number_of_tuples_in_main_memory // len(
                self.run_infos
            )
            assert memory_per_queue > 0, (
                f"Memory limit (={self.number_of_tuples_in_main_memory}) too low for the number of runs "
                f"(={len(self.run_infos)}) given."
            )
            queue.set_memory_limit(
                self.number_of_tuples_in_main_memory // len(self.run_infos)
            )
            queue.reset()

            self.heap.append(SingleStreamMerge.HeapEntry[ObjectType](queue))

        # finally, establish heap property:
        heapq.heapify(self.heap)

    def __next__(self) -> object:
        """Returns the next smallest element across all runs: takes the head of the heap, advances that run's
        iterator and re-heapifies, or drops the run (closing its queue) once it is exhausted.
        """
        # returns the next element in the sorted runs:
        if len(self.heap) == 0:
            raise StopIteration

        # get the smallest element from the heap without removing it:
        smallest_heap_entry: SingleStreamMerge.HeapEntry = self.heap[0]
        value: ObjectType = smallest_heap_entry.value

        try:
            # get the next element from the read queue:
            smallest_heap_entry.value = smallest_heap_entry.iterator.__next__()

            # replace the heap entry on the heap with the modified (reused) entry:
            heapq.heapreplace(self.heap, smallest_heap_entry)

        except StopIteration:
            # close the read queue:
            smallest_heap_entry.queue.close()

            # pop the heap entry from the heap as the read_queue is empty:
            heapq.heappop(self.heap)

        return value

    def __iter__(self) -> Iterator:
        """Returns the iterator object. Required to be able to loop over the merged, sorted output."""

        return self


class ExternalMergeSort[ObjectType: Comparable](Iterator):
    """ExternalMergeSort sorts its input data based on arbitrary queues (which may be list-based or external or
    whatever queues). Call create_runs() to create sorted runs (phase 0), then merge() to merge them until at most
    <fan_in> runs are left. After that, ExternalMergeSort is an iterator that returns the elements in sorted order
    and thus can directly be used in for loops. The final merge is online (on demand).
    """

    def __init__(
        self,
        input_data: Iterator[ObjectType],
        queue_factory: QueueFactory,
        number_of_tuples_in_main_memory: int = 1000,
        fan_in: int = 10,
        replacement_selection: bool = False,
    ):
        """Initializes the ExternalMergeSort.

        @param input_data: The input data to create runs from.
        @param queue_factory: The factory to use to create read and write queues.
        @param number_of_tuples_in_main_memory: The number of tuples that can be stored in memory. Must be at least
        fan_in + 1, which is one tuple per input run plus one for the output run.
        @param fan_in: The fan-in of the merge sort. Must be at least 2.
        @param replacement_selection: Make the runs by replacement selection instead of sorting chunks. Then
        ``create_runs`` raises a ValueError if ``number_of_tuples_in_main_memory`` is less than 1.
        @raise ValueError: if fan_in is less than 2.

        """
        # a merge of fewer than two runs does not reduce the number of runs, so merge() could loop forever:
        if fan_in < 2:
            raise ValueError(f"fan_in must be at least 2, got {fan_in}")
        self.input_data = input_data
        self.queue_factory = queue_factory
        self.number_of_tuples_in_main_memory = number_of_tuples_in_main_memory
        self.fan_in = fan_in
        self.replacement_selection: bool = replacement_selection

        # heap to keep track of the runs:
        self.heap: list[RunMetadata] = list[RunMetadata]()
        # final merge iterator:
        self.final_merge: Iterator | None = None

    def create_runs(self) -> None:
        """phase 0: create runs for the input data."""

        # get a run generator instance that will do all the work of phase 0:
        rg: RunGenerator[ObjectType] = RunGenerator[ObjectType](
            input_data=self.input_data,
            queue_factory=self.queue_factory,
            number_of_tuples_in_main_memory=self.number_of_tuples_in_main_memory,
            replacement_selection=self.replacement_selection,
        )

        # create the runs, i.e. execute phase 0:
        run_generation_result: RunGenerationResult = rg.create_runs()

        logger.info(f"created {len(run_generation_result.runs_metadata)} runs")
        for ri in run_generation_result.runs_metadata:
            logger.info(ri)

        # initialize the heap with the run metadata (NOT the contents of the actual runs):
        self.heap = run_generation_result.runs_metadata

        # establish heap property:
        heapq.heapify(self.heap)

    def _grab_next_fan_in_runs_and_merge_them(self) -> None:
        """Phase i>0: Merges the next runs from the heap (at most <self.fan_in>, the smallest first) into one new run
        and pushes it onto the heap. Merges fewer runs if that is already enough for the runs left on the heap plus the
        new run to fit into the final merge. This is a helper function to merge(). This will NOT perform the final
        merge.
        """

        # next_runs will contain the next runs (at most self.fan_in) to be merged in a non-online fashion
        next_runs: list[RunMetadata] = list[RunMetadata]()

        # pop the next runs (at most self.fan_in) from the heap:
        for _ in range(self.fan_in):
            # stop condition: if there are less than self.fan_in runs left in the heap
            # why: once we reach that situation we can initialize an online merge
            # len(next_runs) > 1 makes sure we do not merge one input run into a single output run
            if len(self.heap) < self.fan_in and len(next_runs) > 1:
                break

            next_runs.append(heapq.heappop(self.heap))

        # post: next_runs contains the next runs (at most self.fan_in) to be merged in a non-online fashion

        if len(next_runs) > 0:
            # logger output:
            logger.info(f"merging {len(next_runs)} runs")
            logger.info("input runs:")
            for ri in next_runs:
                logger.info(ri)

            # initialize a single stream merge from these runs:
            # distribute memory equally over all runs (including the output run)
            # Note: this is one possible configuration, other configurations are possible
            memory_for_ssm: int = (
                self.number_of_tuples_in_main_memory // (len(next_runs) + 1)
            ) * len(next_runs)

            # everything else is memory for the output run:
            memory_for_output_run: int = (
                self.number_of_tuples_in_main_memory - memory_for_ssm
            )

            # asserts to check memory distribution:
            assert memory_for_ssm >= len(
                next_runs
            ), "memory_for_ssm too low, not even one element per run available"
            assert (
                memory_for_ssm <= self.number_of_tuples_in_main_memory
            ), "memory_for_ssm does not leave memory for output run"
            assert memory_for_output_run > 0, "no memory for output run"
            assert memory_for_output_run <= self.number_of_tuples_in_main_memory
            assert (
                memory_for_ssm + memory_for_output_run
                == self.number_of_tuples_in_main_memory
            )

            # initialize a merge for the next runs:
            ssm: SingleStreamMerge = SingleStreamMerge(
                next_runs,
                self.queue_factory,
                memory_for_ssm,
            )

            # create a queue:
            queue: ReadWriteQueue[ObjectType] = self.queue_factory.get_queue_instance()
            queue.set_memory_limit(memory_for_output_run)

            # dump output of the ssm into the write queue:
            for element in ssm:
                queue.insert(element)

            # flush to allow implementations to force it to disk/SSD:
            queue.flush()

            # collect metadata about this run:
            new_run_info = RunMetadata(queue=queue, size=queue.size())

            # add metadata to the heap and maintain heap property:
            heapq.heappush(self.heap, new_run_info)

            logger.info("output run:")
            logger.info(new_run_info)

    def merge(self) -> None:
        """Phase i>0: Merges the runs iteratively till only one final merge is left to be done online."""

        # grab the next runs (at most self.fan_in) and merge them:
        ssm_counter: int = 0
        while len(self.heap) > self.fan_in:
            logger.info(f"SingleStreamMerge {ssm_counter}")
            logger.info(f"heap size: {len(self.heap)}")
            self._grab_next_fan_in_runs_and_merge_them()
            ssm_counter += 1

        # post: only one final merge is left to be done online:
        # initialize the final merge:
        ssm: SingleStreamMerge = SingleStreamMerge(
            self.heap,
            self.queue_factory,
            self.number_of_tuples_in_main_memory,
        )

        # set the final merge to be the online merge:
        self.final_merge: Iterable = ssm

        assert len(self.heap) <= self.fan_in
        # post: runs were merged, now we have <= self.fan_in runs left in the heap

    def __next__(self) -> ObjectType:
        """Returns the next element in the sorted runs. This is the online merge."""

        return self.final_merge.__next__()

    def __iter__(self) -> Iterator:
        """Returns the iterator object. Required to be able to loop over the merged, sorted output."""

        return self
