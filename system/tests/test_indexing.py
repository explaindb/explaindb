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

    def test_create_and_drop_index_transactional_store(self):
        store = IndexedTransactionalKeyValueStore()
        fake_data = self._create_fake_data()
        store.bulkload(fake_data)

        self.assertEqual(store.size(), 100)
        store.create_index("a", "a", "=")
        with self.assertRaises(Exception):
            store.create_index("a", "b", "=")

        # check for existence of metadata:
        self.assertEqual(len(store.indexes_by_properties), 1)
        self.assertEqual(len(store.indexes_by_name), 1)

        # get the index:
        index_entry: IndexedTransactionalKeyValueStore.IndexCatalogueEntry = (
            store.indexes_by_name["a"]
        )
        no_unique_keys = len(set([x.a for x in fake_data]))
        # worst case: all "a" values are unique
        self.assertGreaterEqual(no_unique_keys, 1)

        # index must have as many entries as unique keys:
        self.assertEqual(index_entry.index.size(), no_unique_keys)

        # drop the index:
        store.drop_index("a")
        self.assertEqual(len(store.indexes_by_properties), 0)
        self.assertEqual(len(store.indexes_by_name), 0)

        # drop the index again:
        with self.assertRaises(Exception):
            store.drop_index("a")

        # create the index again:
        store.create_index("a", "a", "=")
        self.assertEqual(len(store.indexes_by_properties), 1)
        self.assertEqual(len(store.indexes_by_name), 1)

        # create a second index on "b":
        store.create_index("b", "b", "=")
        self.assertEqual(len(store.indexes_by_properties), 2)
        self.assertEqual(len(store.indexes_by_name), 2)

        # get index on "b":
        index_entry_b: IndexedTransactionalKeyValueStore.IndexCatalogueEntry = (
            store.indexes_by_name["b"]
        )
        no_unique_keys_on_b = len(set([x.b for x in fake_data]))
        # worst case: all "b" values are unique
        self.assertGreaterEqual(no_unique_keys_on_b, 1)

        # index must have as many entries as unique keys:
        self.assertEqual(index_entry_b.index.size(), no_unique_keys_on_b)


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
