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
"""Tests for the queue implementations."""

import copy

from faker import Faker

from system.data_classes import Person
import unittest

from system.interfaces.queues import ReadWriteQueue, QueueFactory
from system.query_processing.queues.queue_factories import (
    ExternalQueueFactory,
    ListQueueFactory,
)
from system.query_processing.queues.list_queues import ListQueue

Faker.seed(42)
fake = Faker()


class QueueTest(unittest.TestCase):
    @staticmethod
    def create_data(number_of_tuples=10000):
        return [Person(fake.name(), fake.date()) for _ in range(number_of_tuples)]

    def test_queues(self):
        persons = self.create_data()

        queue_factory: QueueFactory[Person]
        # test against the queue API, useful for testing the queue implementations:

        number_of_objects_in_buffer: int = 1000
        for queue_factory in [
            ListQueueFactory[Person](),
            ExternalQueueFactory[Person](number_of_objects_in_buffer),
        ]:
            # copy the input list (the check below pops from the copy):
            persons2: list[Person] = copy.deepcopy(persons)

            # create a queue:
            queue: ReadWriteQueue[Person] = queue_factory.get_queue_instance()

            # insert the data into the queue:
            for person in persons2:
                queue.insert(person)

            queue.flush()

            self.assertEqual(queue.size(), 10000)

            # now read the data back:
            iterator_count: int = 0
            for item in queue:
                self.assertEqual(item, persons2.pop(0))
                iterator_count += 1

            # iterator should have been called 10000 times:
            self.assertEqual(iterator_count, 10000)

            # close the queue:
            queue.close()

    def test_next_advances_and_iter_restarts(self) -> None:
        """next() returns the elements in insertion order without removing them, and iter() restarts reading at the
        first element."""
        queue_factory: QueueFactory[int]
        for queue_factory in [ListQueueFactory[int](), ExternalQueueFactory[int]()]:
            with self.subTest(queue_factory=type(queue_factory).__name__):
                # insert three elements and flush them:
                queue: ReadWriteQueue[int] = queue_factory.get_queue_instance()
                for element in range(3):
                    queue.insert(element)
                queue.flush()

                # start reading; iter() returns the queue itself, and next() is called on the queue:
                self.assertIs(iter(queue), queue)
                read: list[int] = [next(queue) for _ in range(3)]
                self.assertEqual(read, [0, 1, 2])

                # all elements are read, but none of them is removed:
                with self.assertRaises(StopIteration):
                    next(queue)
                self.assertEqual(queue.size(), 3)

                # iter() restarts reading at the first element:
                iter(queue)
                self.assertEqual(next(queue), 0)

                # close the queue:
                queue.close()

    def test_list_queue_reset_rewinds_reading(self) -> None:
        """reset() on a ListQueue rewinds reading to the first element and keeps the contents and the size."""
        # insert three elements and read the first two:
        queue: ListQueue[int] = ListQueue[int]()
        for element in range(3):
            queue.insert(element)
        iter(queue)
        self.assertEqual(next(queue), 0)
        self.assertEqual(next(queue), 1)

        # reset() rewinds reading to the first element; the size stays:
        queue.reset()
        self.assertEqual(next(queue), 0)
        self.assertEqual(queue.size(), 3)

    def test_list_queue_pop_continues_with_unread_element(self) -> None:
        """pop() on a ListQueue removes the first element, and the next call of next() returns the first remaining
        element not read yet, whether reading has already started or not."""
        queue: ListQueue[int]
        with self.subTest(case="pop after reading the first element"):
            # insert three elements and read the first one:
            queue = ListQueue[int]()
            for element in range(3):
                queue.insert(element)
            iter(queue)
            self.assertEqual(next(queue), 0)

            # pop() removes the element just read; reading continues with the second element up to the end:
            self.assertEqual(queue.pop(), 0)
            self.assertEqual(next(queue), 1)
            self.assertEqual(next(queue), 2)
            with self.assertRaises(StopIteration):
                next(queue)

        with self.subTest(case="pop before reading"):
            # insert three elements into a fresh queue and pop the first one before reading anything:
            queue = ListQueue[int]()
            for element in range(3):
                queue.insert(element)
            iter(queue)
            self.assertEqual(queue.pop(), 0)

            # reading starts at the new first element:
            self.assertEqual(next(queue), 1)


if __name__ == "__main__":
    # run all tests of this module:
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
