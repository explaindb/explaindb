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

"""Tests for basic key-value store operations."""

import unittest

from system.stores.IndexedMVCC import IndexedTransactionalKeyValueStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore
from system.stores.MVCC import (
    TransactionalKeyValueStore,
    Begin,
    Commit,
    Abort,
    Delete,
    Update,
)
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
        self.assertIsInstance(tkvs.committed_transactions_trace, list)

    def test_begin_transaction(self):
        """Test begin_transaction method"""
        tkvs = TransactionalKeyValueStore()
        TA_ID: int = tkvs.begin_transaction()

        # check store:
        self.assertEqual(len(tkvs.key_value_store), 0)
        self.assertIn(TA_ID, tkvs.TD)
        TD_entry = tkvs.TD[TA_ID]
        self.assertIsInstance(TD_entry.read_clauses, set)
        self.assertIsInstance(TD_entry.write_set, set)
        self.assertIsNone(TD_entry.committed_timestamp)
        self.assertEqual(TD_entry.last_committed_TA_index_in_TA_trace, -1)

        tkvs.begin_transaction()

        tkvs.commit_transaction(TA_ID)
        self.assertEqual(TD_entry.last_committed_TA_index_in_TA_trace, -1)

    def test_journaling(self):
        """Test journaling/logging of transactions, test creation of appropriate journal/log entries"""

        tkvs = TransactionalKeyValueStore()
        TA_ID: int = tkvs.begin_transaction()

        # check begin:
        self.assertEqual(tkvs.journal.size(), 1)
        self.assertEqual(len(list(tkvs.journal.get(TA_ID))), 1)
        self.assertEqual(list(tkvs.journal.get(TA_ID))[0], Begin(TA_id=TA_ID))

        TA_ID_2: int = tkvs.begin_transaction()
        # check second begin:
        self.assertEqual(tkvs.journal.size(), 2)
        self.assertEqual(len(list(tkvs.journal.get(TA_ID))), 1)
        self.assertEqual(len(list(tkvs.journal.get(TA_ID_2))), 1)
        self.assertEqual(list(tkvs.journal.get(TA_ID_2))[0], Begin(TA_id=TA_ID_2))

        tkvs.commit_transaction(TA_ID)
        # check commit:
        self.assertEqual(tkvs.journal.size(), 2)
        self.assertEqual(len(list(tkvs.journal.get(TA_ID))), 2)
        self.assertEqual(
            list(tkvs.journal.get(TA_ID))[1], Commit(TA_id=TA_ID, commit_timestamp=3)
        )

        tkvs.update_object("a", "b", TA_ID_2)
        # check update:
        self.assertEqual(tkvs.journal.size(), 2)
        self.assertEqual(len(list(tkvs.journal.get(TA_ID_2))), 2)
        self.assertEqual(
            list(tkvs.journal.get(TA_ID_2))[1],
            Update(object_id="a", nev_value="b", TA_id=TA_ID_2),
        )

        tkvs.update_object("b", "c", TA_ID_2)
        # check update:
        self.assertEqual(tkvs.journal.size(), 2)
        self.assertEqual(len(list(tkvs.journal.get(TA_ID_2))), 3)
        self.assertEqual(
            list(tkvs.journal.get(TA_ID_2))[2],
            Update(object_id="b", nev_value="c", TA_id=TA_ID_2),
        )

        tkvs.delete_object("b", TA_ID_2)
        # check delete:
        self.assertEqual(tkvs.journal.size(), 2)
        self.assertEqual(
            list(tkvs.journal.get(TA_ID_2))[3], Delete(TA_id=TA_ID_2, object_id="b")
        )
        self.assertEqual(len(list(tkvs.journal.get(TA_ID_2))), 4)

        tkvs.abort_transaction(TA_ID_2)
        # check abort:
        self.assertEqual(tkvs.journal.size(), 2)
        self.assertEqual(list(tkvs.journal.get(TA_ID_2))[4], Abort(TA_id=TA_ID_2))
        self.assertEqual(len(list(tkvs.journal.get(TA_ID_2))), 5)

    def test_IndexedTransactionalKeyValueStore_basics(self):
        """Test basic functionality of IndexedTransactionalKeyValueStore"""
        itkvs: IndexedTransactionalKeyValueStore = IndexedTransactionalKeyValueStore()
        self.assertEqual(itkvs.indexes_by_name, {})

        self.assertEqual(itkvs.indexes_by_properties, {})
        itkvs.create_index("a", "a", "=")

        itkvs.drop_index("a")


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
