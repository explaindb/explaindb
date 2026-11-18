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

# Test modules use self-documenting method/class names and module-level
# fixtures, so pylint's naming and docstring checks are relaxed here.
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring
"""Tests for the order, size and reset behaviour of the disk-backed ExternalQueue."""

import unittest
from typing import Iterable

from system.query_processing.queues.external_queues import ExternalQueue


def _insert_all(queue: ExternalQueue[int], elements: Iterable[int]) -> None:
    """Inserts <elements> into <queue> one by one, in the given order.

    @param queue: the queue to insert into
    @param elements: the elements to insert
    """
    element: int
    for element in elements:
        queue.insert(element)


def _read_rest(queue: ExternalQueue[int]) -> list[int]:
    """Reads the remaining elements of <queue> with next() until StopIteration. Unlike list(queue) or a for-loop,
    this does not call iter(), so it does not rewind the queue and continues where the last read stopped.

    @param queue: the queue to read from
    @return: the elements read, in the order next() returned them
    """
    elements: list[int] = []
    while True:
        try:
            elements.append(next(queue))
        except StopIteration:
            return elements


class ExternalQueueTest(unittest.TestCase):
    """Reads, flushes, sizes and resets of an ExternalQueue with room for two elements in memory."""

    def _create_queue(self) -> ExternalQueue[int]:
        """Creates an empty queue that holds at most two elements in memory and closes it after the test.

        @return: the new queue
        """
        queue: ExternalQueue[int] = ExternalQueue[int](2)
        self.addCleanup(queue.close)
        return queue

    def test_read_without_flush_returns_insertion_order(self) -> None:
        """Reading a queue whose last inserted element was not flushed returns all elements in insertion order."""
        queue: ExternalQueue[int] = self._create_queue()

        # insert 0..4 without flushing; with room for two elements, 0..3 go to the file and 4 stays in memory:
        _insert_all(queue, range(5))

        # a whole read returns the flushed elements first, then the one in memory:
        self.assertEqual(list(queue), [0, 1, 2, 3, 4])

    def test_flush_after_partial_read_appends(self) -> None:
        """A flush after a partial read appends the new elements after all elements flushed before."""
        queue: ExternalQueue[int] = self._create_queue()

        # insert 0..3 and flush them to the file:
        _insert_all(queue, range(4))
        queue.flush()

        # read only the first element; this leaves the file position in the middle of the flushed elements:
        self.assertEqual(next(iter(queue)), 0)

        # insert and flush 4; a whole read returns it after 0..3:
        queue.insert(4)
        queue.flush()
        self.assertEqual(list(queue), [0, 1, 2, 3, 4])

    def test_flush_after_reset_appends(self) -> None:
        """A flush after reset() appends the new elements after all elements flushed before, and size() counts all
        of them."""
        queue: ExternalQueue[int] = self._create_queue()

        # insert 0..2, flush them to the file and reset the queue:
        _insert_all(queue, range(3))
        queue.flush()
        queue.reset()

        # insert and flush 3:
        queue.insert(3)
        queue.flush()

        # the queue holds 0..3 in insertion order:
        self.assertEqual(list(queue), [0, 1, 2, 3])
        self.assertEqual(queue.size(), 4)

    def test_elements_inserted_during_read_are_read_in_order(self) -> None:
        """Elements inserted during a read are returned after the elements already in the queue, in insertion
        order."""
        queue: ExternalQueue[int] = self._create_queue()

        # insert 0..3, flush them to the file and read the first element:
        _insert_all(queue, range(4))
        queue.flush()
        self.assertEqual(next(iter(queue)), 0)

        # insert 4..6 while the read is under way; the read continues with 1..3 and then 4..6:
        _insert_all(queue, range(4, 7))
        self.assertEqual(_read_rest(queue), [1, 2, 3, 4, 5, 6])

        # a new whole read returns all seven elements in insertion order:
        self.assertEqual(list(queue), [0, 1, 2, 3, 4, 5, 6])

    def test_size_during_partial_read(self) -> None:
        """During a read, size() is the number of inserted elements."""
        queue: ExternalQueue[int] = self._create_queue()

        # insert 0..3 and flush them to the file:
        _insert_all(queue, range(4))
        queue.flush()

        # reading the first element does not change the size:
        self.assertEqual(next(iter(queue)), 0)
        self.assertEqual(queue.size(), 4)

    def test_size_after_whole_read(self) -> None:
        """After a whole read, size() is the number of inserted elements, including those that were not flushed."""
        queue: ExternalQueue[int] = self._create_queue()

        # insert 0..4 without flushing; with room for two elements, 4 stays in memory:
        _insert_all(queue, range(5))

        # reading all elements does not change the size:
        list(queue)
        self.assertEqual(queue.size(), 5)

    def test_reset_keeps_unflushed_elements_and_size(self) -> None:
        """reset() keeps inserted elements that were not flushed yet, and the size stays the same."""
        queue: ExternalQueue[int] = self._create_queue()

        # insert 0..4 without flushing; with room for two elements, 4 stays in memory:
        _insert_all(queue, range(5))

        # after the reset, the size is unchanged and a read returns all five elements:
        queue.reset()
        self.assertEqual(queue.size(), 5)
        self.assertEqual(_read_rest(queue), [0, 1, 2, 3, 4])

    def test_reset_after_partial_read_rewinds_to_first_element(self) -> None:
        """After a partial read, reset() makes the next read start at the first element of the queue."""
        queue: ExternalQueue[int] = self._create_queue()

        # insert 0..4 and flush them to the file:
        _insert_all(queue, range(5))
        queue.flush()

        # read the first three elements; iter() rewinds and returns the queue itself, so next() moves the queue's
        # own read position:
        iterator: ExternalQueue[int] = iter(queue)
        self.assertEqual([next(iterator) for _ in range(3)], [0, 1, 2])

        # after the reset, reading starts again at 0:
        queue.reset()
        self.assertEqual(_read_rest(queue), [0, 1, 2, 3, 4])

    def test_new_iteration_after_partial_read_starts_at_first_element(self) -> None:
        """A new iteration over the queue after a partial read starts at the first element."""
        queue: ExternalQueue[int] = self._create_queue()

        # insert 0..3 and flush them to the file:
        _insert_all(queue, range(4))
        queue.flush()

        # read the first three elements; iter() rewinds and returns the queue itself, so next() moves the queue's
        # own read position:
        iterator: ExternalQueue[int] = iter(queue)
        self.assertEqual([next(iterator) for _ in range(3)], [0, 1, 2])

        # a new whole read returns all elements from the first one on:
        self.assertEqual(list(queue), [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
