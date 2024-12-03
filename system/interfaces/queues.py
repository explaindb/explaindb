from abc import ABC, abstractmethod
from typing import Iterator


class ReadQueue[ObjectType](ABC, Iterator):
    """ReadQueue is an API for queues you can read data from. This is an Iterator that can directly be used in for-loops."""

    @abstractmethod
    def __next__(self) -> ObjectType:
        """Reads the next entry from the queue without removing it from the queue. Corresponds to the next() aka get()
        and peek() method of a container."""

        pass

    @abstractmethod
    def pop(self) -> ObjectType:
        """Removes and returns the first element of the queue"""

        pass

    @abstractmethod
    def close(self) -> None:
        """Closes the queue"""

        pass

    @abstractmethod
    def set_memory_limit(self, memory_limit: int) -> None:
        """Sets the memory limit for the queue. This is useful for queues that are disk-based and can use a buffer in
        memory to speed up access. If the memory limit is set to 0, the queue should not use any memory buffer.

        @param memory_limit The memory limit in bytes to use for the queue."""

        pass


class WriteQueue[ObjectType](ABC):
    """WriteQueue is an API for queues you can write data to."""

    @abstractmethod
    def insert(self, entry: ObjectType) -> None:
        """Inserts an entry into the queue. Corresponds to the add() and put() methods of a container, also next(entry)
        in a push-based iterator."""

        pass

    @abstractmethod
    def flush(self) -> int:
        """Flushes the contents of the queue, e.g. to a file, i.e. writes the contents of the buffer to the file.

        @return The number of objects written to the file for this call to flush()"""

        pass

    @abstractmethod
    def close(self) -> None:
        """Closes the queue and  potentially any file(s) backing the queue."""
        pass

    @abstractmethod
    def size(self) -> int:
        """Returns the number of elements inserted into this queue so far.

        @return The number of elements inserted into this queue so far."""

        pass

    @abstractmethod
    def set_memory_limit(self, memory_limit: int) -> None:
        """Sets the memory limit for the queue. This is useful for queues that are disk-based and can use a buffer in
        memory to speed up access. If the memory limit is set to 0, the queue should not use any memory buffer.

        @param memory_limit The memory limit in bytes to use for the queue."""

        pass


class ReadWriteQueue[ObjectType](ReadQueue[ObjectType], WriteQueue[ObjectType], ABC):
    """ReadWriteQueue is an API for queues that can be read from and can be written to."""

    def __init__(self, memory_limit: int = 10000):
        """Initializes the ReadWriteQueue."""
        self.memory_limit: int = memory_limit

    def reset(self) -> None:
        """Resets the queue to the initial state."""
        pass

    def set_memory_limit(self, memory_limit: int) -> None:
        """Sets the memory limit for the queue. This is useful for queues that are disk-based and can use a buffer in
        memory to speed up access. If the memory limit is set to 0, the queue should not use any memory buffer.

        @param memory_limit The memory limit in bytes to use for the queue."""
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

        pass
