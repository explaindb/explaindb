import unittest
from dataclasses import dataclass

from faker import Faker


class AbstractUnitTest(unittest.TestCase):

    # frozen (read-only) dataclass implicitly creates __eq__ and __hash__ methods
    @dataclass(frozen=True)
    class Stuff:
        a: int
        b: int

    @staticmethod
    def _create_fake_data(number_of_tuples: int = 100):
        fake = Faker()

        return [
            (
                str(i),
                AbstractUnitTest.Stuff(
                    fake.pyint(max_value=1000), fake.pyint(max_value=2000)
                ),
            )
            for i in range(number_of_tuples)
        ]
