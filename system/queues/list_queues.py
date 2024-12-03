from typing import Iterator

import numpy as np

from system.interfaces.queues import ReadWriteQueue


class ListQueue[ObjectType](ReadWriteQueue[ObjectType], Iterator):
    """ListReadQueue is a read queue that uses a list as buffer and backing storage."""

    def __init__(self):
        """Initializes the ListQueue."""
        super().__init__()
        self.buffer: list[ObjectType] = list[ObjectType]()

    def flush(self) -> int:
        """Flushes the contents of the queue, i.e. writes the contents of the buffer to the file.

        @return The number of objects written to the file for this call to flush()
        """
        return 0

    def insert(self, entry: ObjectType) -> None:
        self.buffer.append(entry)

    def __iter__(self):
        """Returns the iterator object. Required to be able to loop over the contents of the queue."""

        return self.buffer.__iter__()

    def __next__(self) -> ObjectType:
        """Returns the next entry from the queue without removing it.

        @return The next entry from the queue.
        """
        return self.__iter__().__next__()

    def pop(self) -> ObjectType:
        """Pops the first element from the queue.

        @return The first element from the queue.
        """
        return self.buffer.pop(0)

    def size(self) -> int:
        """Returns the number of elements inserted into this queue so far.

        @return The number of elements inserted into this queue so far.
        """
        return len(self.buffer)

    def close(self) -> None:
        """Closes the queue. Does not do anything for this implementation."""
        pass
