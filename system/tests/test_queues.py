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

"""Tests for the queue implementations."""

import copy

from faker import Faker

from system.data_classes import Person
import unittest

from system.interfaces.queues import ReadWriteQueue, QueueFactory
from system.queues.queue_factories import ExternalQueueFactory, ListQueueFactory

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
            # create a copy of the sorted list:
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


if __name__ == "__main__":
    # only execute a specific test class
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
