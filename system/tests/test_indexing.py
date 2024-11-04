import unittest

from system.store import (
    VersionedKeyValueStore,
    TransactionalKeyValueStore,
    IndexedTransactionalKeyValueStore,
)
from dataclasses import dataclass
from faker import Faker


Faker.seed(42)


class StoreIndexing(unittest.TestCase):

    # frozen (read-only) dataclass implicitly creates __eq__ and __hash__ methods
    @dataclass(frozen=True)
    class Stuff:
        a: int
        b: int

    @staticmethod
    def _create_fake_data(number_of_tuples: int = 100):
        fake = Faker()

        return [
            StoreIndexing.Stuff(fake.pyint(max_value=1000), fake.pyint(max_value=2000))
            for _ in range(number_of_tuples)
        ]

    def test_KeyValueStore_basics(self):
        store = IndexedTransactionalKeyValueStore()
        store.bulkload(self._create_fake_data())
        self.assertEqual(store.size(), 100)


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
