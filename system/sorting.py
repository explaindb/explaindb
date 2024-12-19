import heapq
import logging
from typing import Iterable, Iterator

from attr import dataclass

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

    def __init__(self, queue: ReadWriteQueue, size: int):
        """Initializes the RunMetadata.

        @param queue: The queue instance representing the run.
        @param size: The size of the run.

        """
        self.queue: ReadWriteQueue = queue
        self.size: int = size

    def __lt__(self, other):
        """The smallest run has the highest priority. This leads to a bottom-up merge in a recursive merge sort.

        @param other: The other RunMetadata to compare with.
        """

        return self.size < other.size

    def __str__(self):
        return f"RunMetadata:  {self.size} elements"


@dataclass
class RunGenerationResult:
    """RunGenerationResult is a helper class to store the result of the run generation phase."""

    # list of RunMetadata instances:
    runs_metadata: list[RunMetadata]

    # total number of elements written while creating runs:
    elements_written: int


class RunGenerator[ObjectType]:
    def __init__(
        self,
        input_data: Iterator[ObjectType],
        queue_factory: QueueFactory,
        number_of_tuples_in_main_memory: int = 1000,
    ):
        """Initializes the RunGenerator.

        @param queue_factory: The factory to use to create read and write queues.
        @param input_data: The input data to create runs from.
        @param number_of_tuples_in_main_memory: The number of tuples that can be stored in memory.
        """

        self.queue_factory: QueueFactory = queue_factory
        self.input_data: Iterator[ObjectType] = input_data
        self.number_of_tuples_in_main_memory: int = number_of_tuples_in_main_memory

    def create_runs(self) -> RunGenerationResult:
        """Creates runs from the input file and write them to the output directory.

        @return: A tuple consisting of (a list of RunMetadata instances, elements_written while creating runs).
        """
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
            # TODO here we could alternatively use replacement selection
            buffer.sort()

            # get a queue instance:
            queue: ReadWriteQueue[ObjectType] = self.queue_factory.get_queue_instance()

            # insert the data into the queue:
            for element in buffer:
                queue.insert(element)

            # flush the queue (to allow memory-backed implementations to flush to disk):
            queue.flush()

            # flush the write queue buffer to disk:
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
        @param queue_factory: The factory to use to create read and write queues.
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
        """Returns the iterator object. Required to be able to loop over the contents of the queue."""

        return self


class ExternalMergeSort[ObjectType](Iterator):
    """ExternalMergeSort is a class to merge sorted runs recursively based on arbitrary queues (which may be list-based
    or external or whatever queues). ExternalMergeSort is an iterator that returns the next element in the
    sorted runs and thus can directly be used in for loops. The final merge is online (on demand).
    """

    def __init__(
        self,
        input_data: Iterator[ObjectType],
        queue_factory: QueueFactory,
        number_of_tuples_in_main_memory: int = 1000,
        fan_in: int = 10,
    ):
        """Initializes the ExternalMergeSort.

        @param input_data: The input data to create runs from.
        @param queue_factory: The factory to use to create read and write queues.
        @param number_of_tuples_in_main_memory: The number of tuples that can be stored in memory.
        @param fan_in: The fan-in of the merge sort.

        """
        self.input_data = input_data
        self.queue_factory = queue_factory
        self.number_of_tuples_in_main_memory = number_of_tuples_in_main_memory
        self.fan_in = fan_in

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
        """Phase i>0: Merges the next <self.fan_in> runs till only one final merge is left to be done online.
        This is a helper function to merge(). This will NOT perform the final merge.
        """

        # next_runs will contain the next self.fan_in runs to be merged in a non-online fashion
        next_runs: list[RunMetadata] = list[RunMetadata]()

        # pop the next self.fan_in runs from the heap:
        for _ in range(self.fan_in):
            # stop condition: if there are less than self.fan_in runs left in the heap
            # why: once we reach that situation we can initialize an online merge
            # len(next_runs) > 1 makes sure we do not merge one input run into a single output run
            if len(self.heap) < self.fan_in and len(next_runs) > 1:
                break

            next_runs.append(heapq.heappop(self.heap))

        # post: next_runs contains the next self.fan_in runs to be merged in a non-online fashion

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
            assert memory_for_ssm > len(
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

        # grab next self.fan_in runs and merge them:
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

    def __next__(self) -> None:
        """Returns the next element in the sorted runs. This is the online merge."""

        return self.final_merge.__next__()

    def __iter__(self) -> Iterator:
        """Returns the iterator object. Required to be able to loop over the contents of the queue."""

        return self
