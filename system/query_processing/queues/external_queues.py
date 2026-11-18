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

"""Disk-backed external queue implementation."""

import pickle
import tempfile

from system.interfaces.queues import (
    ReadWriteQueue,
)


class ExternalQueue[ObjectType](ReadWriteQueue):
    """ExternalQueue is a disk-backed read-write queue that buffers elements in memory and spills to a
    temporary file once the buffer is full."""

    def __init__(
        self,
        memory_limit: int = 10000,
    ):
        """Initializes the ExternalQueue.

        @param memory_limit: The number of objects that can be buffered in memory before the buffer is spilled
        to the backing file. Reading uses a second buffer that holds up to the same number of objects.
        """
        super().__init__(memory_limit)

        assert memory_limit > 0, "The memory limit must be greater than 0."

        # open a temporary file:
        self.file = tempfile.NamedTemporaryFile(delete=True)

        # write buffer: inserted elements that are not flushed to the file yet:
        self.buffer = list[ObjectType]()

        # read buffer: elements read back from the file, returned one by one by __next__:
        self.read_buffer: list[ObjectType] = list[ObjectType]()
        self.element_read_position_in_buffer = 0

        # file positions of the next element to read and of the end of the flushed elements, and the number of
        # flushed elements:
        self.current_read_seek = 0
        self.current_write_seek = 0
        self.total_flushed_so_far = 0

    def reset(self) -> None:
        """See :meth:`ReadWriteQueue.reset`.

        Empties the read buffer and moves the read position to the start of the file. The write buffer and the
        write position stay as they are, so unflushed elements are kept and the next flush still appends.
        """
        self.read_buffer = list[ObjectType]()
        self.element_read_position_in_buffer = 0
        self.current_read_seek = 0

    def __iter__(self):
        """Returns the iterator object. Required to be able to loop over the contents of the queue.
        Rewinds reading to the first element of the queue, see :meth:`reset`.
        """
        self.reset()

        return self

    def __next__(self) -> ObjectType:
        """Returns the next entry from the queue without removing it. In this implementation, the read buffer is
        filled from the file once the element read position is beyond the data available in the read buffer.
        """
        # element read position beyond the data available in the read buffer?
        if self.element_read_position_in_buffer >= len(self.read_buffer):
            # fill the read buffer:
            self._fill_buffer()

            # reset the element read position:
            self.element_read_position_in_buffer = 0

            # read buffer is empty?
            if len(self.read_buffer) == 0:
                raise StopIteration

        # retrieve the next element from the read buffer:
        element: ObjectType = self.read_buffer[self.element_read_position_in_buffer]

        # increment the element read position:
        self.element_read_position_in_buffer += 1

        # return the element:
        return element

    def pop(self) -> ObjectType:
        """Not supported by this disk-backed queue: always raises :class:`NotImplementedError`."""
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
        """See :meth:`WriteQueue.flush`.

        Appends the write buffer to the file after the elements flushed before, then empties the write buffer.
        """

        if len(self.buffer) == 0:
            return 0

        elements_written: int = len(self.buffer)

        # move to the end of the flushed elements, as a read may have moved the file position:
        self.file.seek(self.current_write_seek)

        # write contents of the buffer to the file:
        for element in self.buffer:
            # the queue only reads back what it wrote itself, so pickle is safe here:
            # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
            pickle.dump(element, self.file)

        # the next flush continues where this one stopped:
        self.current_write_seek = self.file.tell()
        self.total_flushed_so_far += elements_written

        # empty the buffer by initializing it with an empty list:
        self.buffer = list[ObjectType]()

        return elements_written

    def _fill_buffer(self) -> int:
        """Flushes the write buffer, so that the file holds all elements in insertion order, then replaces the
        contents of the read buffer with the next elements from the file, at most memory_limit many.

        @return The number of objects read from the file for this call to _fill_buffer()
        """
        # flush the write buffer, so that reads also return the elements that were not flushed yet:
        self.flush()

        # empty the read buffer:
        self.read_buffer = list[ObjectType]()

        # read the contents of the file into the read buffer:
        self.file.seek(self.current_read_seek)
        item_count = 0
        while item_count < self.memory_limit:
            try:
                # the file holds only what this queue wrote (see flush):
                # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
                item: ObjectType = pickle.load(self.file)
                self.read_buffer.append(item)
                item_count += 1
            except EOFError:
                break

        # update read seek:
        self.current_read_seek = self.file.tell()

        # return the number of objects read:
        return len(self.read_buffer)

    def close(self) -> None:
        """Closes the temporary file backing the queue. This will also delete that file."""

        self.file.close()

    def size(self) -> int:
        """Returns the number of elements inserted into this queue so far"""

        return self.total_flushed_so_far + len(self.buffer)
