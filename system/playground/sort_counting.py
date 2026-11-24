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

"""Counts what :class:`ExternalMergeSort` does: its runs, its merges and the elements it writes and reads.

The runs and the merges (with their input and output runs) and the counts are recorded on the sort's queues and its
input. The sort is run unchanged on counting list queues. A merge's input runs are found by the order of events on the
queues: each queue notes when it is made and when it is first read. :class:`SingleStreamMerge` reads the first
element of each of its input runs before :class:`ExternalMergeSort` asks the queue factory for the merge's output
queue, so the queues first read since the previous output queue was made are the inputs of the next one; the queues
first read after the last output queue was made are those of the final merge. :func:`sort_counted` checks that the
runs found this way add up and raises a RuntimeError if they do not, e.g. because ``sorting.py`` changed that order.

Making the runs is called phase 0 in the sort's code here, as in ``sorting.py``; the slides, the notebook and
the formula functions :func:`merge_passes` and :func:`textbook_cost` call it pass 0.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from system.interfaces.queues import QueueFactory
from system.query_processing.queues.list_queues import ListQueue
from system.query_processing.sorting import Comparable, ExternalMergeSort


class CountingQueue[ObjectType: Comparable](ListQueue[ObjectType]):
    """A list queue that counts the elements inserted into it and read from it, notes on a clock shared with the
    other queues of its factory when it was made and when it was first read, and keeps the memory limits the sort
    gave it, in order.

    It counts in the queue itself, not in a wrapper around it: :class:`SingleStreamMerge.HeapEntry` iterates the
    queue itself, so that a wrapper would not see these reads.
    """

    def __init__(self, clock: Iterator[int] | None = None) -> None:
        """Initializes an empty queue with both counts at 0 and notes the time it was made.

        @param clock: the clock shared by the queues of a factory, a counter that each event advances by one; a
        clock of its own if None
        """
        super().__init__()
        self.clock: Iterator[int] = itertools.count() if clock is None else clock
        # the elements inserted so far:
        self.written: int = 0
        # the elements read so far, by __next__; a call at the end, which raises StopIteration, reads nothing:
        self.read: int = 0
        # when the queue was made and when it was first read (None while it was not read), on the clock:
        self.made: int = next(self.clock)
        self.first_read: int | None = None
        # the memory limits set by set_memory_limit, in the order they were set (a merge sets them for its input
        # runs and its output run):
        self.memory_limits: list[int] = []

    def set_memory_limit(self, memory_limit: int) -> None:
        """See :meth:`WriteQueue.set_memory_limit`. Keeps the limit in :attr:`memory_limits`."""
        super().set_memory_limit(memory_limit)
        self.memory_limits.append(memory_limit)

    def insert(self, entry: ObjectType) -> None:
        """See :meth:`WriteQueue.insert`. Counts the element as written."""
        super().insert(entry)
        self.written += 1

    def __next__(self) -> ObjectType:
        """See :meth:`ReadQueue.__next__`. Counts the element as read and notes the time of the first read."""
        element: ObjectType = super().__next__()
        self.read += 1
        if self.first_read is None:
            self.first_read = next(self.clock)
        return element


class CountingQueueFactory[ObjectType: Comparable](QueueFactory[ObjectType]):
    """A queue factory that makes :class:`CountingQueue` instances on one shared clock and keeps them in the order
    they were made."""

    def __init__(self) -> None:
        """Initializes the factory with no queues made and its clock at 0."""
        self.clock: Iterator[int] = itertools.count()
        self.queues: list[CountingQueue[ObjectType]] = []

    def get_queue_instance(self) -> CountingQueue[ObjectType]:
        """See :meth:`QueueFactory.get_queue_instance`. Produces a :class:`CountingQueue` on the factory's clock and
        keeps it."""
        queue: CountingQueue[ObjectType] = CountingQueue[ObjectType](self.clock)
        self.queues.append(queue)
        return queue


class CountingInput[ObjectType](Iterator[ObjectType]):
    """An iterator over the input that counts the elements read from it."""

    def __init__(self, values: Iterable[ObjectType]) -> None:
        """Initializes the iterator at the first value.

        @param values: the input
        """
        self.values: Iterator[ObjectType] = iter(values)
        # the elements read so far:
        self.read: int = 0

    def __next__(self) -> ObjectType:
        """Returns the next value and counts it as read.

        @return: the next value
        @raise StopIteration: once all values were read
        """
        value: ObjectType = next(self.values)
        self.read += 1
        return value


@dataclass(frozen=True)
class Run[ObjectType: Comparable]:
    """A run the sort wrote: one of phase 0 or the output of a merge before the final merge."""

    # the position of the run among all runs written, in the order they were made (those of phase 0 first):
    number: int
    # 0 for a run of phase 0, else the level of the merge that wrote it:
    level: int
    # the elements of the run, in sorted order:
    elements: tuple[ObjectType, ...]


@dataclass(frozen=True)
class Merge[ObjectType: Comparable]:
    """One merge of the sort before the final merge: the runs it read and the run it wrote."""

    # the runs read, in the order the merge first read them:
    inputs: tuple[Run[ObjectType], ...]
    # the run written:
    output: Run[ObjectType]
    # one more than the highest level of its input runs (the slides' pass):
    level: int


@dataclass(frozen=True)
class FinalMerge[ObjectType: Comparable]:
    """The final merge of the sort: the runs it read. It writes no run; its output goes straight to the reader of the
    sort."""

    # the runs read, in the order the merge first read them:
    inputs: tuple[Run[ObjectType], ...]
    # one more than the highest level of its input runs (the slides' pass), 1 without input runs:
    level: int


@dataclass(frozen=True)
# pylint: disable-next=too-many-instance-attributes
class SortCounts[ObjectType: Comparable]:
    """What :class:`ExternalMergeSort` did with one input, memory, fan-in and run generation, as recorded on its
    queues and its input."""

    # M, the number of elements in main memory, and F, the most runs a merge reads from:
    memory: int
    fan_in: int
    # True if the runs were made by replacement selection, False if by sorting chunks of M:
    replacement_selection: bool
    # the input, in its order:
    values: tuple[ObjectType, ...]
    # the runs made in phase 0, in the order they were made:
    runs: tuple[Run[ObjectType], ...]
    # the merges before the final merge, in the order they were made:
    merges: tuple[Merge[ObjectType], ...]
    # the final merge, which writes no run:
    final_merge: FinalMerge[ObjectType]
    # the elements read from the input (in phase 0):
    input_read: int
    # the elements written to the runs of phase 0:
    runs_written: int
    # the elements the merges before the final merge read from their input runs and wrote to their output runs:
    merges_read: int
    merges_written: int
    # the elements the final merge read:
    final_read: int
    # the sorted output of the final merge:
    output: tuple[ObjectType, ...]

    @property
    def run_lengths(self) -> tuple[int, ...]:
        """The lengths of the runs made in phase 0, in the order they were made."""
        return tuple(len(run.elements) for run in self.runs)

    @property
    def merge_outputs(self) -> tuple[int, ...]:
        """The lengths of the runs the merges before the final merge wrote, in the order they were made."""
        return tuple(len(merge.output.elements) for merge in self.merges)

    @property
    def final_fan_in(self) -> int:
        """The number of runs the final merge reads from."""
        return len(self.final_merge.inputs)

    @property
    def written(self) -> int:
        """All elements written: to the runs of phase 0 and by the merges before the final merge."""
        return self.runs_written + self.merges_written

    @property
    def read(self) -> int:
        """All elements read: the input once in phase 0, the input runs of the merges and those of the final merge."""
        return self.input_read + self.merges_read + self.final_read

    @property
    def cost(self) -> int:
        """The elements written and read, counted: :attr:`written` plus :attr:`read`."""
        return self.written + self.read

    @property
    def textbook_cost(self) -> int:
        """The textbook's cost for this input with the real number of runs W: 2N · (1 + ⌈log_F W⌉), see
        :func:`textbook_cost`."""
        return textbook_cost(len(self.values), len(self.runs), self.fan_in)


@dataclass(frozen=True)
class Comparison[ObjectType: Comparable]:
    """The same input sorted with both run generations, with the same memory and fan-in."""

    # M, the number of elements in main memory:
    memory: int
    # F, the most runs a merge reads from:
    fan_in: int
    # the counts with chunks of M sorted in memory, and with replacement selection:
    chunks: SortCounts[ObjectType]
    replacement_selection: SortCounts[ObjectType]


def check_fan_in(memory: int, fan_in: int) -> None:
    """Checks that the code can merge with a fan-in: a merge needs memory for one element of each input run and one
    of its output run, so F is at most M − 1; a merge of fewer than two runs makes no progress, so F is at least 2.

    @param memory: M, the number of elements in main memory
    @param fan_in: F, the most runs a merge reads from
    @raise ValueError: if F is not from 2 to M − 1
    """
    if not 2 <= fan_in <= memory - 1:
        raise ValueError(
            f"the fan-in F must be from 2 to M − 1 = {memory - 1}, got {fan_in}"
        )


def merge_passes(runs: int, fan_in: int) -> int:
    """The textbook's number of merge passes for W runs and fan-in F: ⌈log_F W⌉, the smallest k with F^k ≥ W
    (0 for at most one run), computed with integers only.

    @param runs: W, the number of runs of pass 0
    @param fan_in: F, at least 2
    @return: ⌈log_F W⌉
    @raise ValueError: if F is less than 2 (or not a number) or W is negative
    """
    # "not F ≥ 2" also rejects a float NaN, for which every comparison is false:
    if not fan_in >= 2 or runs < 0:
        raise ValueError(f"need F ≥ 2 and W ≥ 0, got F = {fan_in} and W = {runs}")
    # F^k ≥ W holds at the latest for k = W, as F^W ≥ 2^W ≥ W for F ≥ 2, so only k = 0 to W are tried:
    for passes in range(runs + 1):
        if fan_in**passes >= runs:
            return passes
    raise AssertionError(f"no k ≤ W = {runs} with F^k ≥ W for F = {fan_in}")


def textbook_cost(elements: int, runs: int, fan_in: int) -> int:
    """The textbook's cost of external merge sort in elements written and read: 2N · (1 + ⌈log_F W⌉), as pass 0
    and every merge pass read and write all N elements once.

    @param elements: N, the number of elements
    @param runs: W, the number of runs of pass 0
    @param fan_in: F, at least 2
    @return: 2N · (1 + ⌈log_F W⌉)
    @raise ValueError: if F is less than 2 (or not a number) or W is negative
    """
    return 2 * elements * (1 + merge_passes(runs, fan_in))


def _run[ObjectType: Comparable](
    queue: CountingQueue[ObjectType], number: int, level: int
) -> Run[ObjectType]:
    """Returns a queue's contents as a :class:`Run`.

    @param queue: the queue of the run
    @param number: the position of the run among all runs written
    @param level: the level of the run
    @return: the run
    """
    return Run(number=number, level=level, elements=tuple(queue.buffer))


def _merge_level[ObjectType: Comparable](inputs: Iterable[Run[ObjectType]]) -> int:
    """The level of a merge: one more than the highest level of its input runs, 1 without input runs.

    @param inputs: the input runs of the merge
    @return: the level
    """
    return 1 + max((run.level for run in inputs), default=0)


def _runs_and_merges[ObjectType: Comparable](
    queues: Sequence[CountingQueue[ObjectType]], phase_0: int
) -> tuple[
    tuple[Run[ObjectType], ...],
    tuple[Merge[ObjectType], ...],
    tuple[Run[ObjectType], ...],
]:
    """Finds the runs and merges of a sort from the times its queues were made and first read: each merge before the
    final merge reads the queues first read before its output queue was made and not read by an earlier merge; the
    final merge reads the runs not merged yet.

    @param queues: all queues of the sort, in the order they were made
    @param phase_0: the number of queues phase 0 made (its runs)
    @return: the runs of phase 0, the merges before the final merge, and the input runs of the final merge
    @raise RuntimeError: if the runs found for a merge do not add up to its output
    """
    phase_0_runs: tuple[Run[ObjectType], ...] = tuple(
        _run(queue, index, 0) for index, queue in enumerate(queues[:phase_0])
    )
    # the runs not merged yet, by number, and the queues read, in the order of their first read:
    unmerged: dict[int, Run[ObjectType]] = {run.number: run for run in phase_0_runs}
    reads: list[tuple[int, int]] = sorted(
        (queue.first_read, index)
        for index, queue in enumerate(queues)
        if queue.first_read is not None
    )
    merges: list[Merge[ObjectType]] = []
    # the position in reads of the first read after the previous output queue was made; output queues are made in
    # the order of time, so it only moves forward:
    position: int = 0
    for index in range(phase_0, len(queues)):
        start: int = position
        while position < len(reads) and reads[position][0] < queues[index].made:
            position += 1
        inputs: tuple[Run[ObjectType], ...] = tuple(
            unmerged.pop(number)
            for _, number in reads[start:position]
            if number in unmerged
        )
        output: Run[ObjectType] = _run(queues[index], index, _merge_level(inputs))
        if sum(len(run.elements) for run in inputs) != len(output.elements):
            raise RuntimeError(
                f"the runs read before output queue {index} was made do not add up to it: the sort no longer reads"
                " a merge's input runs before it makes the merge's output queue"
            )
        merges.append(Merge(inputs=inputs, output=output, level=output.level))
        unmerged[index] = output
    final_inputs: tuple[Run[ObjectType], ...] = tuple(
        unmerged[number] for _, number in reads if number in unmerged
    )
    return phase_0_runs, tuple(merges), final_inputs


def sort_counted[ObjectType: Comparable](
    values: Iterable[ObjectType],
    memory: int,
    fan_in: int,
    replacement_selection: bool,
) -> SortCounts[ObjectType]:
    """Sorts the values with :class:`ExternalMergeSort` on counting queues and records what it does.

    The queues made by phase 0 (``create_runs``) are the runs; the queues made after it are the outputs of the merges
    before the final merge. The inputs of each merge are the queues first read since the previous output queue was
    made (see the module docstring); each queue is read by one merge only.

    @param values: the input
    @param memory: M, the number of elements in main memory
    @param fan_in: F, the most runs a merge reads from
    @param replacement_selection: True to make the runs by replacement selection, False to sort chunks of M
    @return: the counts
    @raise ValueError: if F is not from 2 to M − 1
    @raise RuntimeError: if the runs found for a merge do not add up to its output, or those of the final merge are
    not the runs the sort has left, i.e. if the sort no longer reads a merge's inputs before it makes its output
    queue
    """
    check_fan_in(memory, fan_in)
    elements: tuple[ObjectType, ...] = tuple(values)
    factory: CountingQueueFactory[ObjectType] = CountingQueueFactory[ObjectType]()
    source: CountingInput[ObjectType] = CountingInput(elements)
    sort: ExternalMergeSort[ObjectType] = ExternalMergeSort[ObjectType](
        input_data=source,
        queue_factory=factory,
        number_of_tuples_in_main_memory=memory,
        fan_in=fan_in,
        replacement_selection=replacement_selection,
    )
    # phase 0, then the merges up to the final merge, then the final merge, which reads while its output is consumed:
    sort.create_runs()
    phase_0: int = len(factory.queues)
    sort.merge()
    output: tuple[ObjectType, ...] = tuple(sort)

    queues: list[CountingQueue[ObjectType]] = factory.queues
    runs, merges, final_inputs = _runs_and_merges(queues, phase_0)
    # the runs found for the final merge must be the runs left on the sort's heap:
    if {id(queues[run.number]) for run in final_inputs} != {
        id(metadata.queue) for metadata in sort.heap
    }:
        raise RuntimeError(
            "the runs read after the last output queue was made are not those of the final merge"
        )
    final_read: int = sum(queues[run.number].read for run in final_inputs)
    return SortCounts(
        memory=memory,
        fan_in=fan_in,
        replacement_selection=replacement_selection,
        values=elements,
        runs=runs,
        merges=merges,
        final_merge=FinalMerge(inputs=final_inputs, level=_merge_level(final_inputs)),
        input_read=source.read,
        runs_written=sum(queue.written for queue in queues[:phase_0]),
        merges_read=sum(queue.read for queue in queues) - final_read,
        merges_written=sum(queue.written for queue in queues[phase_0:]),
        final_read=final_read,
        output=output,
    )


def compare[ObjectType: Comparable](
    values: Iterable[ObjectType], memory: int, fan_in: int
) -> Comparison[ObjectType]:
    """Sorts the values with chunks of M and with replacement selection, with the same memory and fan-in.

    @param values: the input
    @param memory: M, the number of elements in main memory
    @param fan_in: F, the most runs a merge reads from
    @return: the counts of both
    @raise ValueError: if F is not from 2 to M − 1
    """
    elements: tuple[ObjectType, ...] = tuple(values)
    return Comparison(
        memory=memory,
        fan_in=fan_in,
        chunks=sort_counted(elements, memory, fan_in, replacement_selection=False),
        replacement_selection=sort_counted(
            elements, memory, fan_in, replacement_selection=True
        ),
    )
