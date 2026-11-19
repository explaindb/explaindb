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
"""Tests for the external merge sort."""

import copy
import logging
import math

from faker import Faker

from system.data_classes import Person
import unittest

from system.interfaces.queues import QueueFactory
from system.query_processing.queues.queue_factories import (
    ExternalQueueFactory,
    ListQueueFactory,
)
from system.query_processing.sorting import (
    RunGenerator,
    SingleStreamMerge,
    ExternalMergeSort,
    RunGenerationResult,
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)


Faker.seed(42)
fake = Faker()


class MergeSortingTest(unittest.TestCase):
    @staticmethod
    def create_data(number_of_tuples=10000):
        return [Person(fake.name(), fake.date()) for _ in range(number_of_tuples)]

    def test_run_generation_and_single_merge(self):
        number_of_tuples: int = 1000
        persons: list[Person] = self.create_data(number_of_tuples=number_of_tuples)

        for number_of_tuples_in_main_memory in [
            100,
            1000,
            10000,
        ]:
            queue_factory: QueueFactory[Person]
            for queue_factory in [
                ListQueueFactory[Person](),
                ExternalQueueFactory[Person](number_of_tuples_in_main_memory),
            ]:
                persons2 = copy.deepcopy(persons)
                persons2.sort()
                self.assertEqual(len(persons), number_of_tuples)

                # create a tmp directory to store the runs:
                rg: RunGenerator = RunGenerator(
                    input_data=persons.__iter__(),
                    queue_factory=queue_factory,
                    number_of_tuples_in_main_memory=number_of_tuples_in_main_memory,
                )

                # create runs:
                run_generation_result: RunGenerationResult = rg.create_runs()

                # check the number of elements written:
                self.assertEqual(
                    run_generation_result.elements_written, number_of_tuples
                )
                run_sizes_sum = sum(
                    run_metadata.size
                    for run_metadata in run_generation_result.runs_metadata
                )
                self.assertEqual(run_sizes_sum, number_of_tuples)

                number_of_runs_in_theory = math.ceil(
                    number_of_tuples / number_of_tuples_in_main_memory
                )
                self.assertEqual(
                    len(run_generation_result.runs_metadata), number_of_runs_in_theory
                )

                # create a single stream merge from these runs:
                ssm: SingleStreamMerge = SingleStreamMerge(
                    run_generation_result.runs_metadata,
                    queue_factory,
                    number_of_tuples_in_main_memory,
                )

                count = 0
                # iterate over the merged elements:
                entry: Person
                for entry in ssm:
                    # compare merged elements with a copy of the sorted list:
                    self.assertEqual(entry, persons2.pop(0))
                    count += 1

                self.assertEqual(count, number_of_tuples)

    def test_external_sorting_new(self):
        number_of_tuples: int = 1500
        persons: list[Person] = self.create_data(number_of_tuples=number_of_tuples)

        for number_of_tuples_in_main_memory in [
            100,
            1000,
            10000,
        ]:
            queue_factory: QueueFactory[Person]
            for queue_factory in [
                ListQueueFactory[Person](),
                ExternalQueueFactory[Person](number_of_tuples_in_main_memory),
            ]:
                persons2 = copy.deepcopy(persons)
                persons2.sort()
                self.assertEqual(len(persons), number_of_tuples)

                ems: ExternalMergeSort[Person] = ExternalMergeSort[Person](
                    input_data=persons.__iter__(),
                    queue_factory=queue_factory,
                    number_of_tuples_in_main_memory=number_of_tuples_in_main_memory,
                    fan_in=5,
                )
                ems.create_runs()
                ems.merge()
                count: int = 0
                element: Person
                for element in ems:
                    # compare merged elements with the sorted list:
                    self.assertEqual(element, persons2.pop(0))
                    count += 1

                self.assertEqual(count, number_of_tuples)

    def test_external_sorting_with_fan_in_plus_one_tuples_in_main_memory(self) -> None:
        """External merge sort sorts correctly when main memory holds only fan_in + 1 tuples, e.g. three tuples
        for a fan-in of 2: an intermediate merge of fan_in runs then holds one tuple of each input run and one
        tuple of its output run in main memory."""
        number_of_tuples: int = 100
        persons: list[Person] = self.create_data(number_of_tuples=number_of_tuples)

        for number_of_tuples_in_main_memory, fan_in in [(3, 2), (6, 5)]:
            queue_factory: QueueFactory[Person]
            for queue_factory in [
                ListQueueFactory[Person](),
                ExternalQueueFactory[Person](number_of_tuples_in_main_memory),
            ]:
                with self.subTest(
                    number_of_tuples_in_main_memory=number_of_tuples_in_main_memory,
                    fan_in=fan_in,
                    queue_factory=type(queue_factory).__name__,
                ):
                    # sort the persons in runs of number_of_tuples_in_main_memory tuples, then merge at most
                    # fan_in runs at a time:
                    ems: ExternalMergeSort[Person] = ExternalMergeSort[Person](
                        input_data=persons.__iter__(),
                        queue_factory=queue_factory,
                        number_of_tuples_in_main_memory=number_of_tuples_in_main_memory,
                        fan_in=fan_in,
                    )
                    ems.create_runs()
                    ems.merge()

                    # the output holds every person exactly once, in sorted order:
                    self.assertEqual(list(ems), sorted(persons))

    def test_external_sorting_fan_in_must_be_at_least_two(self) -> None:
        """The constructor rejects a fan_in below 2, as merging fewer than two runs at a time does not reduce the
        number of runs."""

        # a fan_in of 1, 0 or below is rejected:
        for fan_in in [1, 0, -1]:
            with self.subTest(fan_in=fan_in):
                with self.assertRaisesRegex(ValueError, "fan_in must be at least 2"):
                    ExternalMergeSort[Person](
                        input_data=iter([]),
                        queue_factory=ListQueueFactory[Person](),
                        number_of_tuples_in_main_memory=100,
                        fan_in=fan_in,
                    )

        # the smallest valid fan_in, 2, is accepted:
        ems: ExternalMergeSort[Person] = ExternalMergeSort[Person](
            input_data=iter([]),
            queue_factory=ListQueueFactory[Person](),
            number_of_tuples_in_main_memory=100,
            fan_in=2,
        )
        self.assertEqual(ems.fan_in, 2)


if __name__ == "__main__":
    # only execute a specific test class
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
