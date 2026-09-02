"""Factories for creating in-memory list queues and external queues."""

from system.interfaces.queues import QueueFactory, ReadWriteQueue
from system.queues.external_queues import ExternalQueue
from system.queues.list_queues import ListQueue


class ListQueueFactory[ObjectType](QueueFactory[ObjectType]):

    def get_queue_instance(self) -> ReadWriteQueue[ObjectType]:
        """Returns a ReadWriteQueue instance of type ListReadWriteQueue.

        @return An instance of ListReadWriteQueue.
        """

        return ListQueue[ObjectType]()


class ExternalQueueFactory[ObjectType](QueueFactory[ObjectType]):

    def __init__(self, number_of_objects_in_buffer: int = 100):
        self.number_of_objects_in_buffer = number_of_objects_in_buffer

    def get_queue_instance(self) -> ReadWriteQueue[ObjectType]:
        """Returns a ReadWriteQueue instance of type ExternalQueue.

        @return An instance of ExternalQueue.
        """

        return ExternalQueue[ObjectType](self.number_of_objects_in_buffer)
