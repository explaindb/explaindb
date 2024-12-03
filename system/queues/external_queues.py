import pickle
import tempfile
from typing import get_origin, get_args

from system.interfaces.queues import (
    ReadWriteQueue,
)


class ExternalQueue[ObjectType](ReadWriteQueue):
    """ExternalWriteQueue is a queue that writes to disk using a buffer."""

    def __init__(
        self,
        memory_limit: int = 10000,
    ):
        """Initializes the ExternalQueue.

        @param number_of_objects_in_buffer: The number of tuples that can be stored in memory.
        """
        super().__init__(memory_limit)

        assert memory_limit > 0, "The memory limit must be greater than 0."

        # open a temporary file:
        self.file = tempfile.NamedTemporaryFile(delete=True)
        self.buffer = list[ObjectType]()
        self.element_read_position_in_buffer = 0
        self.current_read_seek = 0
        self.current_write_seek = 0
        self.total_flushed_so_far = 0

    def reset(self) -> None:
        """Resets the queue to the initial state."""
        self.file.seek(0)
        self.buffer = list[ObjectType]()
        self.element_read_position_in_buffer = 0
        self.current_read_seek = 0
        self.current_write_seek = 0
        self.total_flushed_so_far = 0

    def __iter__(self):
        """Returns the iterator object. Required to be able to loop over the contents of the queue.
        Sets the element read position in the buffer to 0 and the current read seek to 0.
        """
        self.element_read_position_in_buffer = 0
        self.current_read_seek = 0

        return self

    def __next__(self) -> ObjectType:
        """Returns the next entry from the queue without removing it. In this implementation, the buffer is filled
        if it is empty and the element read position is beyond the data available in the buffer.
        """
        # element read position beyond the data available in the buffer?
        if self.element_read_position_in_buffer >= len(self.buffer):
            # fill the buffer:
            self._fill_buffer()

            # reset the element read position:
            self.element_read_position_in_buffer = 0

            # buffer is empty?
            if len(self.buffer) == 0:
                raise StopIteration

        # retrieve the next element from the buffer:
        element: ObjectType = self.buffer[self.element_read_position_in_buffer]

        # increment the element read position:
        self.element_read_position_in_buffer += 1

        # return the element:
        return element

    def pop(self) -> ObjectType:
        """Pops the first element from the queue.

        @return The first element from the queue.
        """
        raise NotImplementedError

    def insert(self, entry: ObjectType) -> None:
        """Inserts an entry into the queue

        @param entry: The entry to insert into the queue.
        """

        # buffer full? flush it to disk:
        if len(self.buffer) >= self.memory_limit:
            self.flush()

        self.buffer.append(entry)

    def flush(self) -> int:
        """Flushes the buffer to the file, i.e. writes the contents of the buffer to the file and empty the buffer."""

        if len(self.buffer) == 0:
            return 0

        elements_written: int = len(self.buffer)

        # write contents of the buffer to the file:
        for element in self.buffer:
            pickle.dump(element, self.file)

        self.total_flushed_so_far += elements_written

        # empty the buffer by initializing it with an empty list:
        self.buffer = list[ObjectType]()

        return elements_written

    def _fill_buffer(self) -> int:
        """Fills the buffer if empty. Discards the previous contents of the buffer.

        @return The number of objects read from the file for this call to fill_buffer()
        """
        # empty the buffer:
        self.buffer = list[ObjectType]()

        # read the contents of the file into the buffer:
        self.file.seek(self.current_read_seek)
        item_count = 0
        while item_count < self.memory_limit:
            try:
                item: ObjectType = pickle.load(self.file)
                self.buffer.append(item)
                item_count += 1
            except EOFError:
                break

        # update read seek:
        self.current_read_seek = self.file.tell()

        # return the number of objects read:
        return len(self.buffer)

    def close(self) -> None:
        """Closes the temporary file backing the queue. This will also delete that file."""

        self.file.close()

    def size(self) -> int:
        """Returns the number of elements inserted into this queue so far"""

        return self.total_flushed_so_far + len(self.buffer)
