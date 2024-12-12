import unittest

from system.stores.IndexedMVCC import IndexedTransactionalKeyValueStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore
from system.stores.MVCC import TransactionalKeyValueStore
from faker import Faker

from system.tests.abstract_unit_test import AbstractUnitTest

Faker.seed(42)


class StoreTestBasics(AbstractUnitTest):

    def test_KeyValueStore_basics(self):
        """Test basic bulkload functionality of KeyValueStore"""
        kvs: VersionedKeyValueStore
        for kvs in [
            VersionedKeyValueStore(),
            TransactionalKeyValueStore(),
            IndexedTransactionalKeyValueStore(),
        ]:
            kvs.bulkload(self._create_fake_data().__iter__())
            self.assertTrue(kvs.size() == 100)
            for key, value in kvs.key_value_store.items():
                self.assertIsInstance(key, str)
                entries = value.committed
                self.assertIsInstance(entries, list)
                self.assertEqual(len(entries), 1)
                entry = entries[0]
                self.assertIsInstance(entry, VersionedKeyValueStore.UpdateEntry)
                self.assertIsInstance(entry.value, StoreTestBasics.Stuff)
                self.assertEqual(entry.start_validity, 0)
                self.assertTrue(isinstance(entry, VersionedKeyValueStore.UpdateEntry))
                self.assertEqual(list(kvs.get(key))[0], entry.value)

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
