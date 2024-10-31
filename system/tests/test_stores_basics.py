import unittest

from system.store import (
    VersionedKeyValueStore,
    TransactionalKeyValueStore,
    IndexedTransactionalKeyValueStore,
)
from dataclasses import dataclass
from faker import Faker


Faker.seed(42)


class StoreTestBasics(unittest.TestCase):

    # frozen (read-only) dataclass implicitly creates __eq__ and __hash__ methods
    @dataclass(frozen=True)
    class Stuff:
        a: int
        b: int

    @staticmethod
    def _create_fake_data(number_of_tuples: int = 100):
        fake = Faker()

        return [
            StoreTestBasics.Stuff(
                fake.pyint(max_value=1000), fake.pyint(max_value=2000)
            )
            for _ in range(number_of_tuples)
        ]

    def test_KeyValueStore_basics(self):
        """Test basic bulkload functionality of KeyValueStore"""
        kvs: VersionedKeyValueStore
        for kvs in [
            VersionedKeyValueStore(),
            TransactionalKeyValueStore(),
            IndexedTransactionalKeyValueStore(),
        ]:
            kvs.bulkload(self._create_fake_data())
            self.assertTrue(kvs.size() == 100)
            for key, value in kvs.key_value_store.items():
                self.assertIsInstance(key, str)
                entries = value.committed
                self.assertIsInstance(entries, list)
                self.assertEqual(len(entries), 1)
                entry = entries[0]
                self.assertIsInstance(entry, VersionedKeyValueStore.VersionEntry)
                self.assertIsInstance(entry.value, StoreTestBasics.Stuff)
                self.assertEqual(entry.start_validity, 0)
                self.assertFalse(entry.deleted)

    def test_bulkload_with_prefix(self):
        """Test bulkload with object_id_prefix"""
        kvs: VersionedKeyValueStore = VersionedKeyValueStore()
        kvs.bulkload(self._create_fake_data(), object_id_prefix="stuff_")
        self.assertTrue(kvs.size() == 100)
        for key in kvs.key_value_store.keys():
            self.assertTrue(key.startswith("stuff_"))

    def test_TransactionalKeyValueStore(self):
        tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore()
        self.assertTrue(tkvs.size() == 0)
        self.assertEqual(tkvs.TA_id, 1)
        self.assertEqual(tkvs._get_next_TA_id(), 1)
        self.assertEqual(tkvs._get_next_TA_id(), 2)
        self.assertIsInstance(tkvs.TD, dict)
        self.assertIsInstance(tkvs.committed_transactions_log, list)

    def test_begin_transaction(self):
        """Test begin_transaction method"""
        tkvs = TransactionalKeyValueStore()
        TA_ID: int = tkvs.begin_transaction()
        self.assertEqual(len(tkvs.key_value_store), 0)
        self.assertIn(TA_ID, tkvs.TD)
        TD_entry = tkvs.TD[TA_ID]
        self.assertIsInstance(TD_entry.read_clauses, set)
        self.assertIsInstance(TD_entry.write_set, set)
        self.assertIsNone(TD_entry.committed_timestamp)
        self.assertEqual(TD_entry.last_committed_TA_index_in_TA_log, -1)

        tkvs.begin_transaction()
        tkvs.commit_transaction(TA_ID)
        self.assertEqual(TD_entry.last_committed_TA_index_in_TA_log, -1)

    def test_IndexedTransactionalKeyValueStore_basics(self):
        """Test basic functionality of IndexedTransactionalKeyValueStore"""
        itkvs: IndexedTransactionalKeyValueStore = IndexedTransactionalKeyValueStore()
        self.assertEqual(itkvs.indexes_by_name, {})

        self.assertEqual(itkvs.indexes_by_properties, {})
        itkvs.create_index("a", "a", "=")

        itkvs.drop_index("a")


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
