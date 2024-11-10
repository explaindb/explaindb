import unittest

from system.indexes.indexes import (
    PythonDictionaryWithoutDuplicates,
    PythonDictionaryWithDuplicates,
)
from system.store import (
    IndexedTransactionalKeyValueStore,
)
from dataclasses import dataclass
from faker import Faker


Faker.seed(42)


class IndexingTest(unittest.TestCase):

    # frozen (read-only) dataclass implicitly creates __eq__ and __hash__ methods
    @dataclass(frozen=True)
    class Stuff:
        a: int
        b: int

    @staticmethod
    def _create_fake_data(number_of_tuples: int = 100):
        fake = Faker()

        return [
            IndexingTest.Stuff(fake.pyint(max_value=1000), fake.pyint(max_value=2000))
            for _ in range(number_of_tuples)
        ]

    def test_indexing_basics_no_duplicets(self):
        index: PythonDictionaryWithoutDuplicates = PythonDictionaryWithoutDuplicates()
        index.put("key1", "value1")
        index.put("key2", "value2")
        index.put("key3", "value3")
        self.assertEqual(index.size(), 3)

        index.delete("key1", "value1")
        self.assertEqual(index.size(), 2)

        with self.assertRaises(KeyError):
            index.delete("key1", "value1")
        with self.assertRaises(KeyError):
            index.get("key1")

        index.put("key1", "value1")
        self.assertEqual(index.get("key1"), "value1")
        self.assertEqual(index.size(), 3)

    def test_indexing_basics_with_duplicates(self):
        index: PythonDictionaryWithDuplicates[str, str] = (
            PythonDictionaryWithDuplicates[str, str]()
        )
        index.put("key1", "value1")
        index.put("key1", "value2")
        index.put("key1", "value3")
        self.assertEqual(index.size(), 1)
        self.assertEqual(index.get("key1"), ["value1", "value2", "value3"])

        index.delete("key1", "value1")
        self.assertEqual(index.size(), 1)
        self.assertEqual(index.get("key1"), ["value2", "value3"])

        index.delete("key1", "value2")
        self.assertEqual(index.size(), 1)
        self.assertEqual(index.get("key1"), ["value3"])

        with self.assertRaises(ValueError):
            index.delete("key1", "value4")

        with self.assertRaises(KeyError):
            index.delete("key7", "value4")

        index.delete("key1", "value3")
        self.assertEqual(index.size(), 0)

    def test_indexing_transactional_store(self):
        store = IndexedTransactionalKeyValueStore()
        store.bulkload(self._create_fake_data())
        self.assertEqual(store.size(), 100)


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
