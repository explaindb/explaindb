"""In-memory list-backed queue implementation."""

from typing import Iterator

import numpy as np

from system.interfaces.queues import ReadWriteQueue


class ListQueue[ObjectType](ReadWriteQueue[ObjectType], Iterator):
    """ListQueue is an in-memory read-write queue that uses a list as both buffer and backing storage."""

    def __init__(self):
        """Initializes the ListQueue."""
        super().__init__()
        self.buffer: list[ObjectType] = list[ObjectType]()

    def flush(self) -> int:
        """See :meth:`WriteQueue.flush`.

        No-op for this in-memory queue: there is no backing file to write to, so nothing is written and 0 is
        always returned.
        """
        return 0

    def insert(self, entry: ObjectType) -> None:
        """See :meth:`WriteQueue.insert`."""
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
