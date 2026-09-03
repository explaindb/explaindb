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
