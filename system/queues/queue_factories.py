"""Factories for creating in-memory list queues and external queues."""

from system.interfaces.queues import QueueFactory, ReadWriteQueue
from system.queues.external_queues import ExternalQueue
from system.queues.list_queues import ListQueue


class ListQueueFactory[ObjectType](QueueFactory[ObjectType]):
    """Factory producing in-memory, list-backed queues."""

    def get_queue_instance(self) -> ReadWriteQueue[ObjectType]:
        """See :meth:`QueueFactory.get_queue_instance`.

        Produces a :class:`ListQueue` instance.
        """

        return ListQueue[ObjectType]()


class ExternalQueueFactory[ObjectType](QueueFactory[ObjectType]):
    """Factory producing disk-backed external queues with a fixed in-memory buffer."""

    def __init__(self, number_of_objects_in_buffer: int = 100):
        """Initializes the ExternalQueueFactory.

        @param number_of_objects_in_buffer: The number of objects each produced queue buffers in memory before
        spilling to disk.
        """
        self.number_of_objects_in_buffer = number_of_objects_in_buffer

    def get_queue_instance(self) -> ReadWriteQueue[ObjectType]:
        """See :meth:`QueueFactory.get_queue_instance`.

        Produces an :class:`ExternalQueue` instance configured with this factory's buffer size.
        """

        return ExternalQueue[ObjectType](self.number_of_objects_in_buffer)
