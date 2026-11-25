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

"""In-memory list-backed queue implementation."""

from typing import Iterator, Self


from system.interfaces.queues import ReadWriteQueue


class ListQueue[ObjectType](ReadWriteQueue[ObjectType], Iterator):
    """ListQueue is an in-memory read-write queue that uses a list as both buffer and backing storage."""

    def __init__(self):
        """Initializes the ListQueue."""
        super().__init__()
        self.buffer: list[ObjectType] = list[ObjectType]()
        # index in the buffer of the element the next call of __next__ returns:
        self.read_position: int = 0

    def reset(self) -> None:
        """See :meth:`ReadWriteQueue.reset`.

        Sets the read position to 0.
        """
        self.read_position = 0

    def flush(self) -> int:
        """See :meth:`WriteQueue.flush`.

        No-op for this in-memory queue: there is no backing file to write to, so nothing is written and 0 is
        always returned.
        """
        return 0

    def insert(self, entry: ObjectType) -> None:
        """See :meth:`WriteQueue.insert`."""
        self.buffer.append(entry)

    def __iter__(self) -> Self:
        """See :meth:`ReadQueue.__iter__`."""
        self.read_position = 0
        return self

    def __next__(self) -> ObjectType:
        """See :meth:`ReadQueue.__next__`."""
        # all elements read?
        if self.read_position >= len(self.buffer):
            raise StopIteration

        # return the element at the read position and advance the read position:
        element: ObjectType = self.buffer[self.read_position]
        self.read_position += 1
        return element

    def pop(self) -> ObjectType:
        """See :meth:`ReadQueue.pop`.

        If the removed element was already read, the read position moves back by one, so reading continues with the
        same element as before.
        """
        element: ObjectType = self.buffer.pop(0)

        # all elements moved one place to the front; keep the read position on the same next element:
        if self.read_position > 0:
            self.read_position -= 1

        return element

    def size(self) -> int:
        """See :meth:`WriteQueue.size`."""
        return len(self.buffer)

    def close(self) -> None:
        """Closes the queue. Does not do anything for this implementation."""
