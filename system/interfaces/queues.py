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

"""Abstract queue interfaces (read, write, read-write) and the queue factory."""

from abc import ABC, abstractmethod
from typing import Iterator


class ReadQueue[ObjectType](ABC, Iterator):
    """ReadQueue is an API for queues you can read data from. This is an Iterator that can directly be used in for-loops."""

    @abstractmethod
    def __next__(self) -> ObjectType:
        """Returns the next element of the queue and advances the read position; the element stays in the queue.
        Calling iter() on the queue restarts reading at the first element. Raises StopIteration once all elements
        have been read.

        @return The next element of the queue."""

    @abstractmethod
    def pop(self) -> ObjectType:
        """Removes and returns the first element of the queue. A queue that cannot remove elements, such as
        the disk-backed ExternalQueue, raises :class:`NotImplementedError`."""

    @abstractmethod
    def close(self) -> None:
        """Closes the queue"""

    @abstractmethod
    def set_memory_limit(self, memory_limit: int) -> None:
        """Sets the memory limit for the queue as the number of objects it may keep in memory. This is useful for
        queues that are disk-based and use a buffer in memory to speed up access; an in-memory queue ignores it.

        @param memory_limit The number of objects the queue may keep in memory; must be greater than 0.
        @raise ValueError: if memory_limit is 0 or less
        """


class WriteQueue[ObjectType](ABC):
    """WriteQueue is an API for queues you can write data to."""

    @abstractmethod
    def insert(self, entry: ObjectType) -> None:
        """Inserts an entry into the queue. Corresponds to the add() and put() methods of a container, also next(entry)
        in a push-based iterator."""

    @abstractmethod
    def flush(self) -> int:
        """Flushes the contents of the queue, e.g. to a file, i.e. writes the contents of the buffer to the file.

        @return The number of objects written to the file for this call to flush()"""

    @abstractmethod
    def close(self) -> None:
        """Closes the queue and  potentially any file(s) backing the queue."""

    @abstractmethod
    def size(self) -> int:
        """Returns the number of elements in this queue: all elements inserted so far, minus those removed
        with pop().

        @return The number of elements in this queue."""

    @abstractmethod
    def set_memory_limit(self, memory_limit: int) -> None:
        """Sets the memory limit for the queue as the number of objects it may keep in memory. This is useful for
        queues that are disk-based and use a buffer in memory to speed up access; an in-memory queue ignores it.

        @param memory_limit The number of objects the queue may keep in memory; must be greater than 0.
        @raise ValueError: if memory_limit is 0 or less
        """


class ReadWriteQueue[ObjectType](ReadQueue[ObjectType], WriteQueue[ObjectType], ABC):
    """ReadWriteQueue is an API for queues that can be read from and can be written to."""

    def __init__(self, memory_limit: int = 10000):
        """Initializes the ReadWriteQueue."""
        self.memory_limit: int = memory_limit

    def reset(self) -> None:
        """Rewinds reading: after this call, the next call of next() and every new iteration start again at the
        first element of the queue. The contents of the queue and :meth:`size` stay unchanged; elements inserted
        but not flushed yet are kept.

        The default implementation does nothing; it suits queues whose reads keep no position of their own.
        """

    def set_memory_limit(self, memory_limit: int) -> None:
        """See :meth:`WriteQueue.set_memory_limit`."""
        # refuse a limit that would leave the queue no room in memory:
        if memory_limit <= 0:
            raise ValueError(
                f"The memory limit must be greater than 0, got {memory_limit}."
            )
        self.memory_limit: int = memory_limit


class QueueFactory[ObjectType](ABC):
    """QueueFactory is an abstract factory class to create readwrite queues. You can use this class to create
    instances of the different queues and in particular to create queues that are either disk or memory based.
    This allows you to configure queue-based algorithms with different types of code, e.g. run merge sort either in
    memory or disk or on a key-value store or ....
    """

    @abstractmethod
    def get_queue_instance(self) -> ReadWriteQueue[ObjectType]:
        """Returns a ReadWriteQueue instance.

        @return An instance of a subclass of ReadWriteQueue.
        """
