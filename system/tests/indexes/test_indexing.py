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
"""Tests for the index implementations (B+-tree, radix trie, Christmas tree)."""

import unittest
from collections import Counter
from dataclasses import dataclass
from typing import Iterable
from unittest import mock

from system.indexes.btree import BPlusTree
from system.indexes.christmas_tree import ChristmasTree
from system.indexes.indexes import (
    PythonDictionaryIndex,
)
from system.indexes.radix_trie import RadixTrie, PrefixDigitMapping
from system.interfaces.indexing.Index import IndexProperties, KeyValueStore
from system.query_processing.predicates import Clause, TrueClause, WHERE_Clause
from system.stores.IndexedMVCC import IndexedTransactionalKeyValueStore
from system.stores.MVCC import TransactionAbortedException, TransactionalKeyValueStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore
from faker import Faker

from system.tests.abstract_unit_test import AbstractUnitTest
from system.indexes.utils import Triangle, Vector

Faker.seed(42)

import random

random.seed(42)


class IndexingTest(AbstractUnitTest):

    def test_indexing_basics_with_duplicates(self):
        index: PythonDictionaryIndex[str, str] = PythonDictionaryIndex[str, str]()
        index.put("key1", "value1")
        index.put("key1", "value2")
        index.put("key1", "value3")
        self.assertEqual(index.size(), 1)
        self.assertEqual(list(index.get("key1")), ["value1", "value2", "value3"])

        index.delete("key1", "value1")
        self.assertEqual(index.size(), 1)
        self.assertEqual(list(index.get("key1")), ["value2", "value3"])

        index.delete("key1", "value2")
        self.assertEqual(index.size(), 1)
        self.assertEqual(list(index.get("key1")), ["value3"])

        with self.assertRaises(KeyError):
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
        store.create_index("a_idx", "a", "=")
        with self.assertRaises(Exception):
            store.create_index("a_idx", "b", "=")

        # check for existence of metadata:
        self.assertEqual(len(store.indexes_by_properties), 1)
        self.assertEqual(len(store.indexes_by_name), 1)

        # get the index:
        index_entry: IndexedTransactionalKeyValueStore.IndexCatalogueEntry = (
            store.indexes_by_name["a_idx"]
        )
        no_unique_keys = len(set([x[1].a for x in fake_data]))
        # worst case: all "a" values are unique
        self.assertGreaterEqual(no_unique_keys, 1)

        # index must have as many entries as unique keys:
        self.assertEqual(index_entry.index.size(), no_unique_keys)

        # drop the index:
        store.drop_index("a_idx")
        self.assertEqual(len(store.indexes_by_properties), 0)
        self.assertEqual(len(store.indexes_by_name), 0)

        # drop the index again:
        with self.assertRaises(Exception):
            store.drop_index("a_idx")

        # create the index again:
        store.create_index("a_idx", "a", "=")
        self.assertEqual(len(store.indexes_by_properties), 1)
        self.assertEqual(len(store.indexes_by_name), 1)

        # create a second index on "b":
        store.create_index("b_idx", "b", "=")
        self.assertEqual(len(store.indexes_by_properties), 2)
        self.assertEqual(len(store.indexes_by_name), 2)

        # get index on "b":
        index_entry_b: IndexedTransactionalKeyValueStore.IndexCatalogueEntry = (
            store.indexes_by_name["b_idx"]
        )
        no_unique_keys_on_b = len(set([x[1].b for x in fake_data]))
        # worst case: all "b" values are unique
        self.assertGreaterEqual(no_unique_keys_on_b, 1)

        # index must have as many entries as unique keys:
        self.assertEqual(index_entry_b.index.size(), no_unique_keys_on_b)

    def test_create_index_rejects_second_index_on_same_attribute_and_operator(self):
        """Creating a second index on an attribute and operator that are already indexed raises a KeyError and
        leaves the catalogue unchanged; once the first index is dropped, the second one can be created.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a1", "a", "=")

        # a second equality index on a is rejected:
        with self.assertRaises(KeyError):
            store.create_index("a2", "a", "=")

        # both catalogues still know only a1, and a1 is the suitable index for a = ...:
        self.assertEqual(list(store.indexes_by_name), ["a1"])
        self.assertEqual(store.indexes_by_properties, {IndexProperties("a", "="): "a1"})
        self.assertEqual(
            list(store.get_suitable_indexes("a", "=")), [IndexProperties("a", "=")]
        )

        # a1 still holds "1":
        index_entry_a1: IndexedTransactionalKeyValueStore.IndexCatalogueEntry = (
            store.indexes_by_name["a1"]
        )
        self.assertEqual(index_entry_a1.index.size(), 1)
        self.assertEqual(list(index_entry_a1.index.get(2)), ["1"])

        # dropping a1 empties both catalogues:
        store.drop_index("a1")
        self.assertEqual(store.indexes_by_name, {})
        self.assertEqual(store.indexes_by_properties, {})

        # now a2 can be created and is the index for a = ...:
        store.create_index("a2", "a", "=")
        self.assertEqual(list(store.indexes_by_name), ["a2"])
        self.assertEqual(store.indexes_by_properties, {IndexProperties("a", "="): "a2"})

    def test_failing_create_index_leaves_no_index(self):
        """A create_index that fails on an attribute value that cannot be hashed leaves no index behind; reads of
        a==5 still scan and return "1" and "3", and other indexes can still be created.
        """

        @dataclass
        class Row:
            """An object whose attribute a may hold a value that cannot be hashed."""

            a: object
            b: int

        store = IndexedTransactionalKeyValueStore()
        store.put("1", Row(5, 1))
        store.put("2", Row([5], 2))
        store.put("3", Row(5, 3))

        # the index on a cannot hash the list [5] of "2":
        with self.assertRaises(TypeError):
            store.create_index("a_idx", "a", "=")

        # no index is left in the catalogues, and no read of a==5 can use one:
        self.assertEqual(store.indexes_by_name, {})
        self.assertEqual(store.indexes_by_properties, {})
        self.assertEqual(list(store.get_suitable_indexes("a", "=")), [])
        self.assertIsNone(store._index_for(WHERE_Clause("a", "==", 5)))

        # a running transaction reads a==5 through the scan and sees "1" and "3":
        TA_ID_1: int = store.begin_transaction()
        result: list[tuple[str, object]] = store.read_objects(
            TA_ID_1, WHERE_Clause("a", "==", 5)
        )
        self.assertEqual(
            IndexingTest._sorted_by_object_id(result),
            [("1", Row(5, 1)), ("3", Row(5, 3))],
        )

        # a second attempt fails the same way instead of finding a_idx already there:
        with self.assertRaises(TypeError):
            store.create_index("a_idx", "a", "=")

        # an index on b can still be created and is the only index in both catalogues:
        store.create_index("b_idx", "b", "=")
        self.assertEqual(list(store.indexes_by_name), ["b_idx"])
        self.assertEqual(
            store.indexes_by_properties, {IndexProperties("b", "="): "b_idx"}
        )

        # a read of b==2 goes through that index and returns "2":
        self.assertIsNotNone(store._index_for(WHERE_Clause("b", "==", 2)))
        self.assertEqual(
            store.read_objects(TA_ID_1, WHERE_Clause("b", "==", 2)),
            [("2", Row([5], 2))],
        )

    def test_index_maintenance_transactional_store_commits(self):
        """The indexes hold every object version: an update adds its new version at once, a delete and the commit
        change nothing.

        t1
        begin
        update "1" to (3, 4)
        delete "2"
        commit

        Before t1 begins, the store holds "1"=(2, 3) and "2"=(4, 3) with equality indexes on a and b; the test first
        checks which indexes get_suitable_indexes offers.
        """
        store = IndexedTransactionalKeyValueStore()

        store.put("1", IndexingTest.Stuff(2, 3))
        store.put("2", IndexingTest.Stuff(4, 3))

        store.create_index("a_idx", "a", "=")
        store.create_index("b_idx", "b", "=")

        # test get_suitable_indexes():
        suitable_indexes_a = list(store.get_suitable_indexes("a", "="))
        self.assertEqual(len(suitable_indexes_a), 1)

        suitable_indexes_a_le = list(store.get_suitable_indexes("a", "<="))
        self.assertEqual(len(suitable_indexes_a_le), 0)

        suitable_indexes_b = list(store.get_suitable_indexes("b", "="))
        self.assertEqual(len(suitable_indexes_b), 1)

        suitable_indexes_c = list(store.get_suitable_indexes("c", "="))
        self.assertEqual(len(suitable_indexes_c), 0)

        # check for correct index entries of index a_idx:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 2)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(4)), ["2"])

        # check for correct index entries of index b_idx:
        self.assertEqual(store.indexes_by_name["b_idx"].index.size(), 1)
        self.assertEqual(list(store.indexes_by_name["b_idx"].index.get(3)), ["1", "2"])

        # check index maintenance while running transactions
        TA_ID_1: int = store.begin_transaction()

        # check update functionality:
        store.update_object("1", IndexingTest.Stuff(3, 4), TA_ID_1)

        def check_indexes(_self, _store):
            # check for correct index entries of index a_idx:
            _self.assertEqual(_store.indexes_by_name["a_idx"].index.size(), 3)
            _self.assertEqual(list(_store.indexes_by_name["a_idx"].index.get(2)), ["1"])
            _self.assertEqual(list(_store.indexes_by_name["a_idx"].index.get(3)), ["1"])
            _self.assertEqual(list(_store.indexes_by_name["a_idx"].index.get(4)), ["2"])

            # check for correct index entries of index b_idx:
            _self.assertEqual(_store.indexes_by_name["b_idx"].index.size(), 2)
            _self.assertEqual(
                list(_store.indexes_by_name["b_idx"].index.get(3)), ["1", "2"]
            )
            _self.assertEqual(list(_store.indexes_by_name["b_idx"].index.get(4)), ["1"])

        check_indexes(self, store)
        # check delete functionality:
        store.delete_object("2", TA_ID_1)

        # indexes should be untouched:
        check_indexes(self, store)

        store.commit_transaction(TA_ID_1)

        # indexes should be untouched:
        check_indexes(self, store)

    def test_index_maintenance_transactional_store_aborts(self):
        """Aborting a transaction removes the version added by its update from the indexes.

        t1
        begin
        update "1" to (3, 4)
        abort

        Before t1 begins, the store holds "1"=(2, 3) with equality indexes on a and b.
        """
        store = IndexedTransactionalKeyValueStore()

        store.put("1", IndexingTest.Stuff(2, 3))

        store.create_index("a_idx", "a", "=")
        store.create_index("b_idx", "b", "=")

        # check index maintenance while running transactions
        TA_ID_1: int = store.begin_transaction()

        # check update functionality:
        store.update_object("1", IndexingTest.Stuff(3, 4), TA_ID_1)

        # abort the transaction:
        store.abort_transaction(TA_ID_1)

        # check for correct index entries of indexes a_idx and b_idx:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 1)
        self.assertEqual(store.indexes_by_name["b_idx"].index.size(), 1)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["b_idx"].index.get(3)), ["1"])

    def test_index_maintenance_transactional_store_double_delete(self):
        """A transaction may delete an object twice and commit; the index keeps the committed version.

        t1                          t2
        begin
        delete "1"
        delete "1"
        commit
                                    begin
                                    read all -> sees nothing

        Before t1 begins, the store holds "1"=(2, 3) with an equality index on a.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a_idx", "a", "=")

        TA_ID_1: int = store.begin_transaction()
        store.delete_object("1", TA_ID_1)
        store.delete_object("1", TA_ID_1)
        store.commit_transaction(TA_ID_1)

        # a later transaction no longer sees the object:
        TA_ID_2: int = store.begin_transaction()
        self.assertEqual(store.read_objects(TA_ID_2, TrueClause()), [])

        # the committed version before the delete is still indexed:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 1)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])

    def test_index_maintenance_transactional_store_delete_then_update(self):
        """A transaction may update an object it deleted before.

        t1
        begin
        delete "1"
        update "1" to (5, 5)
        read all -> sees (5, 5)

        Before t1 begins, the store holds "1"=(2, 3) with an equality index on a. The new version is indexed next to
        the committed one; the delete marker adds nothing.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a_idx", "a", "=")

        TA_ID_1: int = store.begin_transaction()
        store.delete_object("1", TA_ID_1)
        store.update_object("1", IndexingTest.Stuff(5, 5), TA_ID_1)

        # the transaction sees its own update:
        self.assertEqual(
            store.read_objects(TA_ID_1, TrueClause()),
            [("1", IndexingTest.Stuff(5, 5))],
        )

        # committed version and new wip version are both indexed:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 2)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(5)), ["1"])

    def test_index_maintenance_transactional_store_update_delete_abort(self):
        """The delete already removes the version (7, 7) of the preceding update from the index; after the abort,
        the index is as before the transaction.

        t1                          t2
        begin
        update "1" to (7, 7)
        delete "1"
        abort
                                    begin
                                    read all -> sees (2, 3)

        Before t1 begins, the store holds "1"=(2, 3) with an equality index on a.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a_idx", "a", "=")

        TA_ID_1: int = store.begin_transaction()
        store.update_object("1", IndexingTest.Stuff(7, 7), TA_ID_1)
        store.delete_object("1", TA_ID_1)
        store.abort_transaction(TA_ID_1)

        # a later transaction sees the original object:
        TA_ID_2: int = store.begin_transaction()
        self.assertEqual(
            store.read_objects(TA_ID_2, TrueClause()),
            [("1", IndexingTest.Stuff(2, 3))],
        )

        # the index is exactly as before the aborted transaction:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 1)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        with self.assertRaises(KeyError):
            list(store.indexes_by_name["a_idx"].index.get(7))

    def test_index_maintenance_transactional_store_update_conflicts_with_delete(
        self,
    ):
        """A transaction cannot update an object that another transaction has deleted but not yet committed.

        t1                          t2
        begin
                                    begin
        delete "1"
                                    update "1" -> aborted
        commit
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a_idx", "a", "=")

        TA_ID_1: int = store.begin_transaction()
        TA_ID_2: int = store.begin_transaction()
        store.delete_object("1", TA_ID_1)

        # TA 2 conflicts with the delete of TA 1 and is aborted:
        with self.assertRaises(TransactionAbortedException):
            store.update_object("1", IndexingTest.Stuff(5, 5), TA_ID_2)
        self.assertNotIn(TA_ID_2, store.TD)

        store.commit_transaction(TA_ID_1)

        # the aborted update left no trace in the index:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 1)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])

    def test_create_index_after_committed_delete(self):
        """Creating an index after a committed delete indexes every committed object version, none for the delete.

        t1
        begin
        delete "2"
        commit

        Before t1 begins, the store holds "1"=(2, 3) and "2"=(4, 3) and no index; the equality index on a is
        created after t1 has committed.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.put("2", IndexingTest.Stuff(4, 3))

        # delete "2" transactionally, leaving a committed delete marker:
        TA_ID_1: int = store.begin_transaction()
        store.delete_object("2", TA_ID_1)
        store.commit_transaction(TA_ID_1)

        store.create_index("a_idx", "a", "=")

        # only real object versions are indexed:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 2)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(4)), ["2"])

    def test_put_after_create_index_indexes_the_object(self):
        """Before the first transaction, a put after create_index adds the object to every index; a put of an
        existing object_id fails and leaves the indexes unchanged.
        """
        store = IndexedTransactionalKeyValueStore()
        store.create_index("a_idx", "a", "=")
        store.create_index("b_idx", "b", "=")

        # put "1" into the store that already has its indexes:
        store.put("1", IndexingTest.Stuff(2, 3))
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 1)
        self.assertEqual(store.indexes_by_name["b_idx"].index.size(), 1)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["b_idx"].index.get(3)), ["1"])

        # a second put of "1" fails:
        with self.assertRaises(KeyError):
            store.put("1", IndexingTest.Stuff(5, 5))

        # the failed put left the indexes unchanged:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 1)
        self.assertEqual(store.indexes_by_name["b_idx"].index.size(), 1)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["b_idx"].index.get(3)), ["1"])
        with self.assertRaises(KeyError):
            list(store.indexes_by_name["a_idx"].index.get(5))

    def test_autocommit_put_after_create_index_indexes_the_object_once(self):
        """With autocommit, a put after create_index lists the object once in the index, an equality read through
        the index finds it, and after a delete with autocommit the read returns nothing.

        t1                          t2                          autocommit
                                                                put "1" as (2, 3), commit
        begin
        read a==2 -> sees (2, 3)
        commit
                                                                delete "1", commit
                                    begin
                                    read a==2 -> sees nothing
        """
        store = IndexedTransactionalKeyValueStore(autocommit=True)
        store.create_index("a_idx", "a", "=")
        index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index
        where_a_2: WHERE_Clause = WHERE_Clause("a", "==", 2)

        # the put runs as a transaction of its own and lists "1" once in the index:
        store.put("1", IndexingTest.Stuff(2, 3))
        self.assertEqual(index.size(), 1)
        self.assertEqual(list(index.get(2)), ["1"])

        # t1 reads "1" through the index:
        TA_ID_1: int = store.begin_transaction()
        self.assertIs(store._index_for(where_a_2), index)
        self.assertEqual(
            store.read_objects(TA_ID_1, where_a_2), [("1", IndexingTest.Stuff(2, 3))]
        )
        store.commit_transaction(TA_ID_1)

        # after the delete with autocommit, the read of t2 returns nothing, although the old version stays indexed:
        store.delete("1")
        TA_ID_2: int = store.begin_transaction()
        self.assertEqual(store.read_objects(TA_ID_2, where_a_2), [])
        self.assertEqual(list(index.get(2)), ["1"])

    def test_bulkload_after_create_index_indexes_every_object(self):
        """A bulkload after create_index adds every loaded object to every index."""
        store = IndexedTransactionalKeyValueStore()
        store.create_index("a_idx", "a", "=")
        store.create_index("b_idx", "b", "=")

        # bulkload two objects that share the value of b:
        store.bulkload(
            iter([("1", IndexingTest.Stuff(2, 3)), ("2", IndexingTest.Stuff(4, 3))])
        )
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 2)
        self.assertEqual(store.indexes_by_name["b_idx"].index.size(), 1)

        # each object is found under its values of a and b:
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(4)), ["2"])
        self.assertEqual(list(store.indexes_by_name["b_idx"].index.get(3)), ["1", "2"])

    def test_index_contains_uncommitted_version_but_concurrent_reader_sees_snapshot(
        self,
    ):
        """A transaction does not see another transaction's uncommitted update, although the index already holds it.

        t1                          t2                          t3
        begin
        update "1" to (5, 5)
                                    begin
                                    read a==2 -> sees (2, 3)
                                    read a==5 -> sees nothing
        read a==5 -> sees (5, 5)
        commit
                                    read a==2 -> still sees (2, 3)
                                                                begin
                                                                read a==5 -> sees (5, 5)

        The index holds all versions of an object, including uncommitted ones. The reads of a==2 and a==5 go through
        the index, which offers "1" for both values; which version a transaction sees is decided by the store's
        snapshot read.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a_idx", "a", "=")
        where_a_2: WHERE_Clause = WHERE_Clause("a", "==", 2)
        where_a_5: WHERE_Clause = WHERE_Clause("a", "==", 5)

        TA_ID_1: int = store.begin_transaction()
        store.update_object("1", IndexingTest.Stuff(5, 5), TA_ID_1)
        TA_ID_2: int = store.begin_transaction()

        # the index already offers "1" for both the committed and the uncommitted value:
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(5)), ["1"])

        # the read through the index gets "1" as a candidate for a==5, but TA 2's visible version does not
        # satisfy a==5:
        self.assertEqual(
            store._get_visible_object_version("1", TA_ID_2), IndexingTest.Stuff(2, 3)
        )
        self.assertEqual(
            store.read_objects(TA_ID_2, where_a_2), [("1", IndexingTest.Stuff(2, 3))]
        )
        self.assertEqual(store.read_objects(TA_ID_2, where_a_5), [])

        # TA 1 sees its own update:
        self.assertEqual(
            store.read_objects(TA_ID_1, where_a_5), [("1", IndexingTest.Stuff(5, 5))]
        )

        store.commit_transaction(TA_ID_1)

        # the index keeps both versions after the commit:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 2)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(5)), ["1"])

        # TA 2 keeps its snapshot; a transaction that starts now sees the new version:
        self.assertEqual(
            store.read_objects(TA_ID_2, where_a_2), [("1", IndexingTest.Stuff(2, 3))]
        )
        TA_ID_3: int = store.begin_transaction()
        self.assertEqual(
            store.read_objects(TA_ID_3, where_a_5), [("1", IndexingTest.Stuff(5, 5))]
        )

    def test_index_maintenance_transactional_store_insert(self):
        """A transaction may insert a new object; the index holds the new version at once, and the commit leaves the
        index unchanged.

        t1                          t2
        begin
        insert "2" as (4, 5)
        read a==4 -> sees (4, 5)
        commit
                                    begin
                                    read a==4 -> sees (4, 5)

        Before t1 begins, the store holds "1"=(2, 3) with an equality index on a.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a_idx", "a", "=")
        where_a_4: WHERE_Clause = WHERE_Clause("a", "==", 4)

        # TA 1 inserts a new object and sees it:
        TA_ID_1: int = store.begin_transaction()
        store.update_object("2", IndexingTest.Stuff(4, 5), TA_ID_1)
        self.assertEqual(
            store.read_objects(TA_ID_1, where_a_4), [("2", IndexingTest.Stuff(4, 5))]
        )

        # the uncommitted new version is indexed next to the existing object:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 2)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(4)), ["2"])

        # the commit leaves the index unchanged:
        store.commit_transaction(TA_ID_1)
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 2)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(4)), ["2"])

        # a transaction that starts now sees the inserted object:
        TA_ID_2: int = store.begin_transaction()
        self.assertEqual(
            store.read_objects(TA_ID_2, where_a_4), [("2", IndexingTest.Stuff(4, 5))]
        )

    def test_index_maintenance_transactional_store_insert_overwrite_abort(self):
        """A second write to an object inserted by the same transaction replaces its version in the index; after the
        abort, the index is as before the transaction.

        t1                          t2
        begin
        insert "2" as (4, 5)
        update "2" to (6, 6)
        abort
                                    begin
                                    read all -> sees only "1"

        Before t1 begins, the store holds "1"=(2, 3) with an equality index on a.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a_idx", "a", "=")

        # TA 1 inserts a new object and overwrites it:
        TA_ID_1: int = store.begin_transaction()
        store.update_object("2", IndexingTest.Stuff(4, 5), TA_ID_1)
        store.update_object("2", IndexingTest.Stuff(6, 6), TA_ID_1)

        # only the latest version of the inserted object is indexed:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 2)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(6)), ["2"])
        with self.assertRaises(KeyError):
            list(store.indexes_by_name["a_idx"].index.get(4))

        # the abort removes the inserted object from the index:
        store.abort_transaction(TA_ID_1)
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 1)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        with self.assertRaises(KeyError):
            list(store.indexes_by_name["a_idx"].index.get(4))
        with self.assertRaises(KeyError):
            list(store.indexes_by_name["a_idx"].index.get(6))

        # a later transaction sees only the original object:
        TA_ID_2: int = store.begin_transaction()
        self.assertEqual(
            store.read_objects(TA_ID_2, TrueClause()),
            [("1", IndexingTest.Stuff(2, 3))],
        )

    def test_index_maintenance_transactional_store_insert_conflicts_with_insert(
        self,
    ):
        """A transaction cannot insert an object that another transaction has inserted but not yet committed.

        t1                          t2
        begin
                                    begin
        insert "2" as (4, 5)
                                    insert "2" as (6, 6) -> aborted
        commit

        Before t1 begins, the store holds "1"=(2, 3) with an equality index on a.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a_idx", "a", "=")

        TA_ID_1: int = store.begin_transaction()
        TA_ID_2: int = store.begin_transaction()
        store.update_object("2", IndexingTest.Stuff(4, 5), TA_ID_1)

        # TA 2 conflicts with the insert of TA 1 and is aborted:
        with self.assertRaises(TransactionAbortedException):
            store.update_object("2", IndexingTest.Stuff(6, 6), TA_ID_2)
        self.assertNotIn(TA_ID_2, store.TD)

        store.commit_transaction(TA_ID_1)

        # the index holds only the version inserted by TA 1:
        self.assertEqual(store.indexes_by_name["a_idx"].index.size(), 2)
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(2)), ["1"])
        self.assertEqual(list(store.indexes_by_name["a_idx"].index.get(4)), ["2"])
        with self.assertRaises(KeyError):
            list(store.indexes_by_name["a_idx"].index.get(6))

    @staticmethod
    def _sorted_by_object_id(
        pairs: Iterable[tuple[str, object]],
    ) -> list[tuple[str, object]]:
        """Returns the (object id, object) pairs of a read sorted by object id.

        The order of a read result is undefined, so two results are compared as sorted lists; a repeated object id
        stays in the list and makes the comparison fail.
        """
        return sorted(pairs, key=lambda pair: pair[0])

    def test_index_read_visits_only_the_candidates(self):
        """A read of a==5 through the index reads the visible version of each object the index offers for 5, each
        object once, and of no other object.

        t1                          t2
        begin
        update "x" to (5, 1)
        commit
                                    begin
                                    read a==5 -> sees (5, 1) for "x" and (5, 0) for "y"

        Before t1 begins, the store holds 98 objects with a == 0 plus "x"=(5, 0) and "y"=(5, 0), with an equality
        index on a. After t1, the index offers "x" twice for 5, once per version.
        """
        store = IndexedTransactionalKeyValueStore()
        store.bulkload(
            iter(
                [(str(i), IndexingTest.Stuff(0, i)) for i in range(98)]
                + [("x", IndexingTest.Stuff(5, 0)), ("y", IndexingTest.Stuff(5, 0))]
            )
        )
        store.create_index("a_idx", "a", "=")

        # t1 commits an update of "x" that keeps a == 5, so the index lists "x" once per version:
        TA_ID_1: int = store.begin_transaction()
        store.update_object("x", IndexingTest.Stuff(5, 1), TA_ID_1)
        store.commit_transaction(TA_ID_1)
        self.assertEqual(store.size(), 100)
        self.assertEqual(
            list(store.indexes_by_name["a_idx"].index.get(5)), ["x", "y", "x"]
        )

        # t2 reads a==5 while a spy records every snapshot read of a single object:
        TA_ID_2: int = store.begin_transaction()
        with mock.patch.object(
            store,
            "_get_visible_object_version",
            wraps=store._get_visible_object_version,
        ) as spy:
            result: list[tuple[str, object]] = list(
                store._read_objects_iterable(TA_ID_2, WHERE_Clause("a", "==", 5))
            )

        # only the two candidates were read, each once, and t2 sees the current version of both:
        self.assertEqual(spy.call_count, 2)
        self.assertEqual(
            sorted(call.args[0] for call in spy.call_args_list), ["x", "y"]
        )
        self.assertEqual(
            IndexingTest._sorted_by_object_id(result),
            [("x", IndexingTest.Stuff(5, 1)), ("y", IndexingTest.Stuff(5, 0))],
        )

    def test_read_without_suitable_index_scans_all_objects(self):
        """A read whose where clause the index cannot answer scans all objects and returns the result of the scan.

        The store holds "0" to "9" with object i = (i % 2, i) and an equality index on a. One transaction reads with
        b == 3 (no index on b), a < 1 (the index only answers ==), TrueClause and no where clause at all.
        """
        store = IndexedTransactionalKeyValueStore()
        store.bulkload(
            iter([(str(i), IndexingTest.Stuff(i % 2, i)) for i in range(10)])
        )
        store.create_index("a_idx", "a", "=")
        TA_ID_1: int = store.begin_transaction()

        label: str
        where: Clause | None
        for label, where in [
            ("b == 3", WHERE_Clause("b", "==", 3)),
            ("a < 1", WHERE_Clause("a", "<", 1)),
            ("TrueClause", TrueClause()),
            ("no where clause", None),
        ]:
            with self.subTest(where=label):
                # the reference result is the scan of the base class:
                expected: list[tuple[str, object]] = IndexingTest._sorted_by_object_id(
                    TransactionalKeyValueStore._read_objects_iterable(
                        store, TA_ID_1, where
                    )
                )

                # the indexed store reads the visible version of every object and returns the same pairs:
                with mock.patch.object(
                    store,
                    "_get_visible_object_version",
                    wraps=store._get_visible_object_version,
                ) as spy:
                    result: list[tuple[str, object]] = list(
                        store._read_objects_iterable(TA_ID_1, where)
                    )
                self.assertEqual(spy.call_count, 10)
                self.assertEqual(IndexingTest._sorted_by_object_id(result), expected)

    def test_index_read_of_an_absent_value_returns_nothing(self):
        """A read of a==7 returns no objects and reads none if no version has a == 7, although the index raises a
        KeyError for 7.
        """
        store = IndexedTransactionalKeyValueStore()
        store.bulkload(
            iter([("1", IndexingTest.Stuff(2, 3)), ("2", IndexingTest.Stuff(4, 3))])
        )
        store.create_index("a_idx", "a", "=")

        # no version has a == 7, so the index has no entry for 7:
        with self.assertRaises(KeyError):
            list(store.indexes_by_name["a_idx"].index.get(7))

        # the read returns an empty result without reading a single object:
        TA_ID_1: int = store.begin_transaction()
        with mock.patch.object(
            store,
            "_get_visible_object_version",
            wraps=store._get_visible_object_version,
        ) as spy:
            self.assertEqual(
                store.read_objects(TA_ID_1, WHERE_Clause("a", "==", 7)), []
            )
        self.assertEqual(spy.call_count, 0)

    def test_index_read_returns_the_same_results_as_the_scan(self):
        """A read of a==v through the index returns the same (object id, object) pairs as the scan, for every value
        v, for every running transaction, and with and without the transaction's own uncommitted versions.

        t1                          t2                          t3
        begin
        update "1" to (1, 1)
        delete "2"
        update "5" to (1, 6)
        commit
                                    begin
                                                                begin
                                                                update "3" to (0, 3)
                                    update "4" to (2, 4)
                                    read a==v for v in 0..4
                                                                read a==v for v in 0..4

        Before t1 begins, the store holds "1"=(0, 1), "2"=(1, 2), "3"=(2, 3), "4"=(3, 4) and "5"=(1, 5) with an
        equality index on a. So the index offers candidates whose visible version does not match: the old version
        of "1", the deleted "2" and the other transaction's uncommitted version. It lists "5" twice for 1, once per
        version, and no version has a == 4.
        """
        store = IndexedTransactionalKeyValueStore()
        store.bulkload(
            iter(
                [
                    ("1", IndexingTest.Stuff(0, 1)),
                    ("2", IndexingTest.Stuff(1, 2)),
                    ("3", IndexingTest.Stuff(2, 3)),
                    ("4", IndexingTest.Stuff(3, 4)),
                    ("5", IndexingTest.Stuff(1, 5)),
                ]
            )
        )
        store.create_index("a_idx", "a", "=")

        # t1 commits an update of "1", a delete of "2" and an update of "5" that keeps a == 1:
        TA_ID_1: int = store.begin_transaction()
        store.update_object("1", IndexingTest.Stuff(1, 1), TA_ID_1)
        store.delete_object("2", TA_ID_1)
        store.update_object("5", IndexingTest.Stuff(1, 6), TA_ID_1)
        store.commit_transaction(TA_ID_1)
        self.assertEqual(
            list(store.indexes_by_name["a_idx"].index.get(1)), ["2", "5", "1", "5"]
        )

        # t2 and t3 each update a different object and keep running:
        TA_ID_2: int = store.begin_transaction()
        TA_ID_3: int = store.begin_transaction()
        store.update_object("3", IndexingTest.Stuff(0, 3), TA_ID_3)
        store.update_object("4", IndexingTest.Stuff(2, 4), TA_ID_2)

        # every read goes through the index and returns the same pairs as the scan of the base class:
        TA_id: int
        value: int
        ignore_wip: bool
        for TA_id in [TA_ID_2, TA_ID_3]:
            for value in range(5):
                for ignore_wip in [False, True]:
                    with self.subTest(TA_id=TA_id, value=value, ignore_wip=ignore_wip):
                        where: WHERE_Clause = WHERE_Clause("a", "==", value)
                        self.assertIsNotNone(store._index_for(where))
                        self.assertEqual(
                            IndexingTest._sorted_by_object_id(
                                store._read_objects_iterable(
                                    TA_id, where, ignore_wip=ignore_wip
                                )
                            ),
                            IndexingTest._sorted_by_object_id(
                                TransactionalKeyValueStore._read_objects_iterable(
                                    store, TA_id, where, ignore_wip=ignore_wip
                                )
                            ),
                        )

    def _assert_index_reads_equal_scans(
        self, store: IndexedTransactionalKeyValueStore, events: Counter[str]
    ) -> None:
        """Asserts that every read of a==v for v in 0..4 goes through the index on a and returns the same
        (object id, object) pairs as the scan of the base class, and counts in <events> the cases the reads met.

        Reads for every running transaction, with and without its own uncommitted versions, and for the committed
        state at the next timestamp, which no transaction has yet (as the validation re-reads at a commit).
        """
        index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index

        # the readers: every running transaction with and without its own uncommitted versions, and the committed
        # state:
        readers: list[tuple[int, bool]] = [
            (TA_id, ignore_wip)
            for TA_id in sorted(store.TD)
            if store.TD[TA_id].committed_timestamp is None
            for ignore_wip in [False, True]
        ] + [(store.TA_id, False)]

        timestamp: int
        ignore_wip: bool
        value: int
        for timestamp, ignore_wip in readers:
            for value in range(5):
                # the read goes through the index and returns the same pairs as the scan:
                where: WHERE_Clause = WHERE_Clause("a", "==", value)
                self.assertIsNotNone(store._index_for(where))
                self.assertEqual(
                    IndexingTest._sorted_by_object_id(
                        store._read_objects_iterable(
                            timestamp, where, ignore_wip=ignore_wip
                        )
                    ),
                    IndexingTest._sorted_by_object_id(
                        TransactionalKeyValueStore._read_objects_iterable(
                            store, timestamp, where, ignore_wip=ignore_wip
                        )
                    ),
                    msg=f"read of a=={value} at {timestamp}, ignore_wip={ignore_wip}",
                )

                # count the cases: no version has the value, or the index offers candidates:
                try:
                    candidate_ids: list[str] = list(index.get(value))
                except KeyError:
                    events["absent value"] += 1
                    continue

                # a candidate whose visible version does not match, an id listed more than once whose visible version
                # matches, and an id offered for another transaction's uncommitted version:
                object_id: str
                for object_id in sorted(set(candidate_ids)):
                    visible: object | None = store._get_visible_object_version(
                        object_id, timestamp, ignore_wip=ignore_wip
                    )
                    if visible is None or not where.evaluate(visible):
                        events["candidate rejected"] += 1
                    elif candidate_ids.count(object_id) > 1:
                        events["repeated candidate"] += 1
                    wip: VersionedKeyValueStore.VersionEntry | None = (
                        store.key_value_store[object_id].wip
                    )
                    if (
                        isinstance(wip, VersionedKeyValueStore.UpdateEntry)
                        and wip.start_validity != timestamp
                        and where.evaluate(wip.value)
                    ):
                        events["uncommitted version of another transaction"] += 1

    def test_index_reads_equal_scans_under_random_concurrent_transactions(self):
        """Under a random workload of concurrent transactions, every read of a==v through the index returns the same
        (object id, object) pairs as the scan, with validation method 2 (the default), with validation method 1
        (brute force) and under snapshot isolation.

        The store starts with "0" to "4" and no index. In each of 300 steps, the workload begins a transaction (at
        most three run at the same time), or a running transaction inserts or updates one of "0" to "9" with a random
        a in 0..3, deletes an object, reads a==v, commits or aborts. A write or a commit may abort the transaction
        (write conflict, failed validation); the workload goes on with the other transactions. The equality index on
        a is created part-way through: from step 60 on, as soon as a transaction holds an uncommitted version.

        From then on, after every step, each read of a==v for v in 0..4 (no version has a == 4) goes through the
        index and returns the same pairs as the scan: for every running transaction with and without its own
        uncommitted versions, and for the committed state. The workload uses its own seeded random generator, so it
        is the same in every run. Each configuration must meet these cases of the index read: a candidate whose
        visible version does not match, an id listed more than once, another transaction's uncommitted version, an
        absent value; and these events that change the index or the store: deletes, aborts, write conflicts and,
        under serializable, failed validations.
        """
        object_ids: list[str] = [str(i) for i in range(10)]

        label: str
        store: IndexedTransactionalKeyValueStore
        for label, store in [
            ("validation method 2", IndexedTransactionalKeyValueStore()),
            (
                "validation method 1",
                IndexedTransactionalKeyValueStore(use_brute_force_validation=True),
            ),
            (
                "snapshot isolation",
                IndexedTransactionalKeyValueStore(isolation_level="snapshot isolation"),
            ),
        ]:
            with self.subTest(configuration=label):
                # a private generator (never the module-wide random) and a counter for the cases met:
                rng: random.Random = random.Random(41)
                events: Counter[str] = Counter[str]()

                # start with five committed objects and no index:
                store.bulkload(
                    iter(
                        [
                            (object_id, IndexingTest.Stuff(rng.randrange(4), 0))
                            for object_id in object_ids[:5]
                        ]
                    )
                )

                step: int
                for step in range(1, 301):
                    running: list[int] = sorted(
                        TA_id
                        for TA_id, entry in store.TD.items()
                        if entry.committed_timestamp is None
                    )

                    # create the index part-way through, from step 60 on, once a transaction holds an uncommitted
                    # version:
                    if (
                        not store.indexes_by_name
                        and step >= 60
                        and any(store.TD[TA_id].write_set for TA_id in running)
                    ):
                        store.create_index("a_idx", "a", "=")

                    # begin a transaction, or let a running one do one operation (b = step keeps versions distinct):
                    operation: str = "begin"
                    if not running or (len(running) < 3 and rng.random() < 0.3):
                        store.begin_transaction()
                    else:
                        TA_id: int = rng.choice(running)
                        operation = rng.choices(
                            ["write", "delete", "read", "commit", "abort"],
                            weights=[4, 1, 3, 2, 1],
                        )[0]
                        try:
                            if operation == "write":
                                store.update_object(
                                    rng.choice(object_ids),
                                    IndexingTest.Stuff(rng.randrange(4), step),
                                    TA_id,
                                )
                            elif operation == "delete":
                                store.delete_object(
                                    rng.choice(sorted(store.key_value_store)), TA_id
                                )
                            elif operation == "read":
                                store.read_objects(
                                    TA_id, WHERE_Clause("a", "==", rng.randrange(4))
                                )
                            elif operation == "commit":
                                store.commit_transaction(TA_id)
                            else:
                                store.abort_transaction(TA_id)
                        except TransactionAbortedException:
                            # the store aborted the transaction:
                            operation = (
                                "validation abort"
                                if operation == "commit"
                                else "write conflict"
                            )

                    # once the index exists, count the operation and compare every read through the index with the
                    # scan:
                    if store.indexes_by_name:
                        events[operation] += 1
                        self._assert_index_reads_equal_scans(store, events)

                # the index was created, and every case occurred at least once (snapshot isolation does not
                # validate reads):
                self.assertIn("a_idx", store.indexes_by_name)
                required: list[str] = [
                    "candidate rejected",
                    "repeated candidate",
                    "uncommitted version of another transaction",
                    "absent value",
                    "delete",
                    "abort",
                    "write conflict",
                ]
                if store.isolation_level == "serializable":
                    required.append("validation abort")
                event: str
                for event in required:
                    self.assertGreater(events[event], 0, msg=event)

    def test_validation_aborts_a_phantom_read_through_the_index(self):
        """A transaction that read a==5 through the index and found nothing is aborted at its commit if another
        transaction inserted an object with a == 5 and committed in the meantime (phantom); with validation method 1
        and method 2.

        t1                          t2
        begin
        read a==5 -> sees nothing
                                    begin
                                    insert "2" as (5, 5)
                                    commit
        update "1" to (2, 4)
        commit -> aborted

        Before t1 begins, the store holds "1"=(2, 3) with an equality index on a. Method 1 reads a==5 again at the
        commit of t1, through the index, which now offers "2"; method 2 does not read again, but finds "2" in the
        write set of t2.
        """
        label: str
        use_brute_force_validation: bool
        for label, use_brute_force_validation in [
            ("validation method 1", True),
            ("validation method 2", False),
        ]:
            with self.subTest(configuration=label):
                store = IndexedTransactionalKeyValueStore(
                    use_brute_force_validation=use_brute_force_validation
                )
                store.put("1", IndexingTest.Stuff(2, 3))
                store.create_index("a_idx", "a", "=")
                where_a_5: WHERE_Clause = WHERE_Clause("a", "==", 5)

                # t1 reads a==5 through the index and sees nothing:
                TA_ID_1: int = store.begin_transaction()
                self.assertIsNotNone(store._index_for(where_a_5))
                self.assertEqual(store.read_objects(TA_ID_1, where_a_5), [])

                # t2 inserts an object with a == 5 and commits:
                TA_ID_2: int = store.begin_transaction()
                store.update_object("2", IndexingTest.Stuff(5, 5), TA_ID_2)
                store.commit_transaction(TA_ID_2)

                # t1 writes and fails validation, as its read of a==5 would now see "2":
                store.update_object("1", IndexingTest.Stuff(2, 4), TA_ID_1)
                with self.assertRaises(TransactionAbortedException):
                    store.commit_transaction(TA_ID_1)
                self.assertNotIn(TA_ID_1, store.TD)

    def test_brute_force_validation_passes_although_an_abort_reordered_the_index(
        self,
    ):
        """With validation method 1, a transaction whose read of a==5 returns the same objects at its commit commits,
        although an aborted transaction changed the order of the ids in the index list for 5.

        t1                          t2
        begin
        read a==5 -> sees "1" and "2"
                                    begin
                                    update "1" to (5, 6)
                                    abort
        update "3" to (7, 8)
        commit -> passes

        Before t1 begins, the store holds "1"=(5, 3), "2"=(5, 4) and "3"=(7, 7) with an equality index on a, which
        lists ["1", "2"] for 5. The update of t2 appends "1", and its abort removes the first "1", so the list is
        ["2", "1"] when t1 commits. The read visits the candidates in sorted order, so the read again at the commit
        returns the pairs in the same order and the checksum is unchanged.
        """
        store = IndexedTransactionalKeyValueStore(use_brute_force_validation=True)
        store.put("1", IndexingTest.Stuff(5, 3))
        store.put("2", IndexingTest.Stuff(5, 4))
        store.put("3", IndexingTest.Stuff(7, 7))
        store.create_index("a_idx", "a", "=")
        index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index
        self.assertEqual(list(index.get(5)), ["1", "2"])

        # t1 reads a==5 and sees both objects:
        TA_ID_1: int = store.begin_transaction()
        self.assertEqual(
            IndexingTest._sorted_by_object_id(
                store.read_objects(TA_ID_1, WHERE_Clause("a", "==", 5))
            ),
            [("1", IndexingTest.Stuff(5, 3)), ("2", IndexingTest.Stuff(5, 4))],
        )

        # t2 updates "1" without changing a and aborts, which reorders the list for 5:
        TA_ID_2: int = store.begin_transaction()
        store.update_object("1", IndexingTest.Stuff(5, 6), TA_ID_2)
        self.assertEqual(list(index.get(5)), ["1", "2", "1"])
        store.abort_transaction(TA_ID_2)
        self.assertEqual(list(index.get(5)), ["2", "1"])

        # t1 writes another object and passes validation:
        store.update_object("3", IndexingTest.Stuff(7, 8), TA_ID_1)
        store.commit_transaction(TA_ID_1)
        self.assertIsNotNone(store.TD[TA_ID_1].committed_timestamp)

    def test_index_lists_an_object_once_per_version_with_the_same_value(self):
        """An update that keeps the value of a lists the object a second time under that value, and a read of the
        value returns the object once; the abort removes the uncommitted version from the index.

        t1
        begin
        update "1" to (2, 4)
        read a==2 -> sees (2, 4)
        abort

        Before t1 begins, the store holds "1"=(2, 3) with an equality index on a.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a_idx", "a", "=")
        index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index

        # the update keeps a == 2, so the index lists "1" once per version:
        TA_ID_1: int = store.begin_transaction()
        store.update_object("1", IndexingTest.Stuff(2, 4), TA_ID_1)
        self.assertEqual(list(index.get(2)), ["1", "1"])

        # the read returns "1" once, in the version of t1:
        self.assertEqual(
            store.read_objects(TA_ID_1, WHERE_Clause("a", "==", 2)),
            [("1", IndexingTest.Stuff(2, 4))],
        )

        # the abort removes the uncommitted version:
        store.abort_transaction(TA_ID_1)
        self.assertEqual(list(index.get(2)), ["1"])

    def test_create_index_while_a_transaction_runs_indexes_every_version(self):
        """An index created while a transaction runs holds every version of an object, committed and uncommitted;
        the transaction reads its own version through the index, and its abort removes that version from the index.

        t1                          t2
        begin
        update "1" to (3, 3)
        commit
                                    begin
                                    update "1" to (4, 3)
                                    read a==4 -> sees (4, 3)
                                    abort

        Before t1 begins, the store holds "1"=(2, 3) and no index; the equality index on a is created after the
        update of t2, before its read.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))

        # t1 commits an update of "1"; t2 updates "1" again and keeps running:
        TA_ID_1: int = store.begin_transaction()
        store.update_object("1", IndexingTest.Stuff(3, 3), TA_ID_1)
        store.commit_transaction(TA_ID_1)
        TA_ID_2: int = store.begin_transaction()
        store.update_object("1", IndexingTest.Stuff(4, 3), TA_ID_2)

        # the new index holds the two committed versions and the uncommitted one:
        store.create_index("a_idx", "a", "=")
        index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index
        self.assertEqual(index.size(), 3)
        self.assertEqual(list(index.get(2)), ["1"])
        self.assertEqual(list(index.get(3)), ["1"])
        self.assertEqual(list(index.get(4)), ["1"])

        # t2 reads its own version through the index:
        where_a_4: WHERE_Clause = WHERE_Clause("a", "==", 4)
        self.assertIsNotNone(store._index_for(where_a_4))
        self.assertEqual(
            store.read_objects(TA_ID_2, where_a_4), [("1", IndexingTest.Stuff(4, 3))]
        )

        # the abort removes the uncommitted version; the committed ones stay:
        store.abort_transaction(TA_ID_2)
        with self.assertRaises(KeyError):
            list(index.get(4))
        self.assertEqual(list(index.get(2)), ["1"])
        self.assertEqual(list(index.get(3)), ["1"])

    # a BaseException like KeyboardInterrupt, but one that does not stop the whole test run if a test lets it escape:
    class _Interrupt(BaseException):
        """Stands in for Ctrl-C."""

    @dataclass
    class _Row:
        """An object whose attributes may hold values that the index cannot hash, e.g. a list."""

        a: object
        b: object

    def test_abort_after_an_update_with_an_unhashable_value_ends_the_transaction(
        self,
    ):
        """A transaction whose update fails because the index cannot hash the new value of a can be aborted: the
        abort ends the transaction and leaves the index unchanged, so a later transaction can write the object.

        t1                          t2
        begin
        update "1" to ([1], 2) -> TypeError
        abort
                                    begin
                                    update "1" to (3, 2)
                                    commit

        Before t1 begins, the store holds "1"=(1, 1) with an equality index on a. The update stores the new version
        of "1" before it indexes it, so t1 aborts with a version that is not in the index.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest._Row(1, 1))
        store.create_index("a_idx", "a", "=")
        index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index

        # t1 updates "1" to a value of a that the index cannot hash:
        TA_ID_1: int = store.begin_transaction()
        with self.assertRaises(TypeError):
            store.update_object("1", IndexingTest._Row([1], 2), TA_ID_1)

        # the abort ends t1 and leaves the index as before t1:
        store.abort_transaction(TA_ID_1)
        self.assertNotIn(TA_ID_1, store.TD)
        self.assertEqual(index.size(), 1)
        self.assertEqual(list(index.get(1)), ["1"])

        # t2 writes "1" and commits; the index lists "1" once under the value of each committed version:
        TA_ID_2: int = store.begin_transaction()
        store.update_object("1", IndexingTest._Row(3, 2), TA_ID_2)
        store.commit_transaction(TA_ID_2)
        self.assertEqual(index.size(), 2)
        self.assertEqual(list(index.get(1)), ["1"])
        self.assertEqual(list(index.get(3)), ["1"])

    def test_abort_after_a_failed_second_index_removes_the_entry_of_the_first(self):
        """A transaction whose update fails because the second index cannot hash the new value of b can be aborted:
        the abort ends the transaction and removes the entry that the first index got for the new version; the
        second index stays unchanged.

        t1
        begin
        update "1" to (3, [2]) -> TypeError
        abort

        Before t1 begins, the store holds "1"=(1, 1) with equality indexes on a and b. The update indexes the new
        version in one index after the other, so a_idx lists it under 3 when b_idx raises.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest._Row(1, 1))

        # create a_idx before b_idx: the update visits the indexes in the order of the catalogue (a dict, which keeps
        # the order of creation), so a_idx gets its entry before b_idx raises:
        store.create_index("a_idx", "a", "=")
        store.create_index("b_idx", "b", "=")
        a_index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index
        b_index: KeyValueStore[object, str] = store.indexes_by_name["b_idx"].index

        # t1 updates "1" to a value of b that b_idx cannot hash, after a_idx listed the new version under 3:
        TA_ID_1: int = store.begin_transaction()
        with self.assertRaises(TypeError):
            store.update_object("1", IndexingTest._Row(3, [2]), TA_ID_1)
        self.assertEqual(list(a_index.get(3)), ["1"])

        # the abort ends t1 and removes that entry, so both indexes are as before t1:
        store.abort_transaction(TA_ID_1)
        self.assertNotIn(TA_ID_1, store.TD)
        with self.assertRaises(KeyError):
            list(a_index.get(3))
        self.assertEqual(list(a_index.get(1)), ["1"])
        self.assertEqual(b_index.size(), 1)
        self.assertEqual(list(b_index.get(1)), ["1"])

    def test_autocommit_put_of_an_unhashable_value_leaves_no_transaction_open(self):
        """With autocommit, a put whose value of a the index cannot hash raises TypeError and leaves no transaction
        open, so a later put of the same object id succeeds and the index lists the object once.

        autocommit
        put "1" as ([1], 2) -> TypeError, abort
        put "1" as (1, 2), commit

        The store is empty and has an equality index on a. Each put runs as a transaction of its own, which the put
        aborts if the insert raises.
        """
        store = IndexedTransactionalKeyValueStore(autocommit=True)
        store.create_index("a_idx", "a", "=")
        index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index

        # the put of a value of a that the index cannot hash raises:
        with self.assertRaises(TypeError):
            store.put("1", IndexingTest._Row([1], 2))

        # no transaction is left open:
        open_TA_ids: list[int] = [
            TA_id
            for TA_id, entry in store.TD.items()
            if entry.committed_timestamp is None
        ]
        self.assertEqual(open_TA_ids, [])

        # a second put of "1" succeeds, and the index lists "1" once:
        store.put("1", IndexingTest._Row(1, 2))
        self.assertEqual(index.size(), 1)
        self.assertEqual(list(index.get(1)), ["1"])

    def test_abort_after_interrupted_indexing_keeps_the_entry_of_the_committed_version(
        self,
    ):
        """If an update that keeps the value of a is interrupted before it indexes the new version, the abort keeps
        the index entry of the committed version, so a later read through the index still finds the object.

        t1                          t2
        begin
        update "1" to (2, 4) -> interrupted
        abort
                                    begin
                                    read a==2 -> sees (2, 3)

        Before t1 begins, the store holds "1"=(2, 3) with an equality index on a, which lists "1" once under 2. The
        update stores the new version and is interrupted (e.g. by Ctrl-C) before it indexes it, so the only entry
        under 2 belongs to the committed version.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a_idx", "a", "=")
        index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index

        # t1's update is interrupted when it adds the new version to the index:
        TA_ID_1: int = store.begin_transaction()
        with self.assertRaises(IndexingTest._Interrupt):
            with mock.patch.object(index, "put", side_effect=IndexingTest._Interrupt):
                store.update_object("1", IndexingTest.Stuff(2, 4), TA_ID_1)

        # the new version is stored, but the index lists only the committed one:
        self.assertEqual(
            store._get_visible_object_version("1", TA_ID_1), IndexingTest.Stuff(2, 4)
        )
        self.assertEqual(list(index.get(2)), ["1"])

        # the abort ends t1 and keeps the entry of the committed version:
        store.abort_transaction(TA_ID_1)
        self.assertNotIn(TA_ID_1, store.TD)
        self.assertEqual(list(index.get(2)), ["1"])

        # t2 reads a==2 through the index and sees the committed version:
        where_a_2: WHERE_Clause = WHERE_Clause("a", "==", 2)
        TA_ID_2: int = store.begin_transaction()
        self.assertIsNotNone(store._index_for(where_a_2))
        self.assertEqual(
            store.read_objects(TA_ID_2, where_a_2), [("1", IndexingTest.Stuff(2, 3))]
        )

    def test_abort_after_interrupted_indexing_of_an_insert_ends_the_transaction(self):
        """If an insert is interrupted before it indexes the new object, the abort ends the transaction, so a later
        transaction can write the object and commit.

        t1                          t2
        begin
        insert "9" as (7, 1) -> interrupted
        abort
                                    begin
                                    insert "9" as (7, 2)
                                    commit

        Before t1 begins, the store holds "1"=(2, 3) with an equality index on a. No version has a == 7, so the
        index has no entry for 7 when t1 aborts.
        """
        store = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest.Stuff(2, 3))
        store.create_index("a_idx", "a", "=")
        index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index

        # t1's insert is interrupted when it adds the new object to the index:
        TA_ID_1: int = store.begin_transaction()
        with self.assertRaises(IndexingTest._Interrupt):
            with mock.patch.object(index, "put", side_effect=IndexingTest._Interrupt):
                store.update_object("9", IndexingTest.Stuff(7, 1), TA_ID_1)

        # the abort ends t1:
        store.abort_transaction(TA_ID_1)
        self.assertNotIn(TA_ID_1, store.TD)

        # t2 inserts "9" and commits; the index lists "9" once under 7:
        TA_ID_2: int = store.begin_transaction()
        store.update_object("9", IndexingTest.Stuff(7, 2), TA_ID_2)
        store.commit_transaction(TA_ID_2)
        self.assertIsNotNone(store.TD[TA_ID_2].committed_timestamp)
        self.assertEqual(list(index.get(7)), ["9"])

    def test_second_write_after_interrupted_indexing_is_found_through_the_index(self):
        """If the insert of an object is interrupted before it indexes the object and the transaction then writes
        the object again with the same value of a, the index lists the object once under that value, and reads
        through the index find the new version, in the transaction and after its commit.

        t1                          t2
        begin
        insert "1" as (2, 4) -> interrupted
        update "1" to (2, 5)
        read a==2 -> sees (2, 5)
        commit
                                    begin
                                    read a==2 -> sees (2, 5)

        Before t1 begins, the store is empty and has an equality index on a. The second write replaces a version
        that is not in the index, so the entry under 2 belongs to the new version.
        """
        store = IndexedTransactionalKeyValueStore()
        store.create_index("a_idx", "a", "=")
        index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index
        where_a_2: WHERE_Clause = WHERE_Clause("a", "==", 2)

        # t1's insert is interrupted when it adds the new object to the index, which stays empty:
        TA_ID_1: int = store.begin_transaction()
        with self.assertRaises(IndexingTest._Interrupt):
            with mock.patch.object(index, "put", side_effect=IndexingTest._Interrupt):
                store.update_object("1", IndexingTest.Stuff(2, 4), TA_ID_1)
        self.assertEqual(index.size(), 0)

        # t1 writes "1" again and reads its new version through the index:
        store.update_object("1", IndexingTest.Stuff(2, 5), TA_ID_1)
        self.assertIsNotNone(store._index_for(where_a_2))
        self.assertEqual(
            store.read_objects(TA_ID_1, where_a_2), [("1", IndexingTest.Stuff(2, 5))]
        )

        # after the commit of t1, t2 reads the new version through the index, which lists "1" once under 2:
        store.commit_transaction(TA_ID_1)
        TA_ID_2: int = store.begin_transaction()
        self.assertEqual(
            store.read_objects(TA_ID_2, where_a_2), [("1", IndexingTest.Stuff(2, 5))]
        )
        self.assertEqual(list(index.get(2)), ["1"])

    def test_second_write_after_an_unhashable_value_succeeds(self):
        """A transaction whose update failed because the index cannot hash the new value of a can write the object
        again and commit: a second update is indexed, a second write that deletes the object deletes it.

        t1                          t2
        begin
        update "1" to ([1], 2) -> TypeError
        update "1" to (3, 2)
        commit
                                    begin
                                    read a==3 -> sees (3, 2)

        The same with delete "1" as the second write of t1, after which t2 reads all and sees nothing. Before t1
        begins, the store holds "1"=(1, 1) with an equality index on a (a new store for each second write). The
        failed update stored its version of "1" without indexing it; the second write replaces that version.
        """

        def store_after_a_failed_update() -> (
            tuple[IndexedTransactionalKeyValueStore, int]
        ):
            """Returns a new store with "1"=(1, 1) and an equality index on a, and the id of a running transaction
            whose update of "1" to ([1], 2) raised TypeError.
            """
            new_store: IndexedTransactionalKeyValueStore = (
                IndexedTransactionalKeyValueStore()
            )
            new_store.put("1", IndexingTest._Row(1, 1))
            new_store.create_index("a_idx", "a", "=")
            TA_id: int = new_store.begin_transaction()
            with self.assertRaises(TypeError):
                new_store.update_object("1", IndexingTest._Row([1], 2), TA_id)
            return new_store, TA_id

        store: IndexedTransactionalKeyValueStore
        TA_ID_1: int
        TA_ID_2: int

        with self.subTest(second_write="update"):
            # t1 updates "1" again; the index lists "1" once under 3, next to the committed version under 1:
            store, TA_ID_1 = store_after_a_failed_update()
            index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index
            store.update_object("1", IndexingTest._Row(3, 2), TA_ID_1)
            self.assertEqual(list(index.get(3)), ["1"])
            self.assertEqual(list(index.get(1)), ["1"])

            # after the commit of t1, t2 reads a==3 through the index and sees the new version:
            store.commit_transaction(TA_ID_1)
            where_a_3: WHERE_Clause = WHERE_Clause("a", "==", 3)
            TA_ID_2 = store.begin_transaction()
            self.assertIsNotNone(store._index_for(where_a_3))
            self.assertEqual(
                store.read_objects(TA_ID_2, where_a_3),
                [("1", IndexingTest._Row(3, 2))],
            )

        with self.subTest(second_write="delete"):
            # t1 deletes "1" and commits; t2 no longer sees "1":
            store, TA_ID_1 = store_after_a_failed_update()
            store.delete_object("1", TA_ID_1)
            store.commit_transaction(TA_ID_1)
            TA_ID_2 = store.begin_transaction()
            self.assertEqual(store.read_objects(TA_ID_2, TrueClause()), [])

    def test_abort_after_writes_without_the_indexed_attribute_ends_the_transaction(
        self,
    ):
        """A transaction that writes an object twice as a version without the indexed attribute a can be aborted:
        the index never lists these versions, the abort ends the transaction and leaves the index unchanged, so a
        later transaction can write the object.

        t1                          t2
        begin
        update "1" to (b=2)
        update "1" to (b=3)
        abort
                                    begin
                                    update "1" to (3, 2)
                                    commit

        Before t1 begins, the store holds "1"=(1, 1) with an equality index on a. The second update of t1 replaces
        a version without a, and the abort discards another one; neither has an entry in the index to remove.
        """

        @dataclass
        class OnlyB:
            """An object without the indexed attribute a."""

            b: int

        store: IndexedTransactionalKeyValueStore = IndexedTransactionalKeyValueStore()
        store.put("1", IndexingTest._Row(1, 1))
        store.create_index("a_idx", "a", "=")
        index: KeyValueStore[object, str] = store.indexes_by_name["a_idx"].index

        # t1 writes "1" twice as a version without a; the index lists only the committed version:
        TA_ID_1: int = store.begin_transaction()
        store.update_object("1", OnlyB(2), TA_ID_1)
        store.update_object("1", OnlyB(3), TA_ID_1)
        self.assertEqual(store._get_visible_object_version("1", TA_ID_1), OnlyB(3))
        self.assertEqual(index.size(), 1)
        self.assertEqual(list(index.get(1)), ["1"])

        # the abort ends t1 and leaves the index as before t1:
        store.abort_transaction(TA_ID_1)
        self.assertNotIn(TA_ID_1, store.TD)
        self.assertEqual(index.size(), 1)
        self.assertEqual(list(index.get(1)), ["1"])

        # t2 writes "1" and commits; the index lists "1" once under the value of each committed version:
        TA_ID_2: int = store.begin_transaction()
        store.update_object("1", IndexingTest._Row(3, 2), TA_ID_2)
        store.commit_transaction(TA_ID_2)
        self.assertEqual(index.size(), 2)
        self.assertEqual(list(index.get(1)), ["1"])
        self.assertEqual(list(index.get(3)), ["1"])


num_runs = 10
max_num_keys = 400
lower_bound = 0
upper_bound = 1000
num_range_queries = 200


class BPlusTreeTest(unittest.TestCase):

    @staticmethod
    def create_btree(
        gen_sorted: bool = False,
    ) -> tuple[BPlusTree, list[int], list[int], int]:
        """
        Creates a b-tree with random keys and values
        :param gen_sorted: sort the data before inserting
        :return: a tuple with the b-tree, the keys, the values and the number of keys
        """

        num_keys = random.randint(2, max_num_keys)
        assert upper_bound > lower_bound
        assert (upper_bound - lower_bound) > num_keys
        keys = random.sample(
            range(lower_bound, upper_bound), num_keys
        )  # keys without duplicates
        if gen_sorted:
            keys.sort()
        values = list(range(num_keys))
        btree: BPlusTree[int, int] = BPlusTree[int, int]()
        for key, value in zip(keys, values):
            btree.put(key, value)

        btree.consistency_check()

        return btree, keys, values, num_keys

    def test_btree_get(self):
        for _ in range(num_runs):
            btree, keys, values, num_keys = self.create_btree()
            self.assertEqual(btree.size(), num_keys)
            for i in range(len(keys)):
                v = list(btree.get(keys[i]))[0]
                self.assertEqual(
                    v, values[i], msg=f"k={keys[i]} | got={v} | expected={values[i]}"
                )

    def test_btree_update_and_get(self):
        """Tests the b-tree update method varying the inner and leaf capacity"""

        for inner_capacity in [2, 5, 100]:
            for leaf_capacity in [2, 5, 100]:
                btree: BPlusTree[int, int] = BPlusTree[int, int](
                    inner_capacity, leaf_capacity
                )

                # a dict for comparing results:
                d: dict[int, int] = {}
                for _ in range(1000):
                    next_int: int = random.randint(1, 400)
                    next_key: int = next_int
                    next_value: int = next_int * 2
                    btree.put(next_key, next_value)
                    d[next_key] = next_value

                    # test get:
                    self.assertEqual(
                        list(btree.get(next_key)),
                        [next_value],
                    )

                self.assertEqual(btree.size(), len(d))
                for key, value in d.items():
                    self.assertEqual(list(btree.get(key))[0], value)

    def test_btree_get_all_in_range(self):
        for _ in range(num_runs):
            btree, keys, values, num_keys = self.create_btree(
                True
            )  # use sorted `keys` to check correctness
            self.assertEqual(btree.size(), num_keys)
            for _ in range(num_range_queries):
                # create random range query:
                min, max = sorted(random.sample(range(lower_bound, upper_bound), 2))
                # query the b-tree:
                values_got = list(btree.get_all_in_range(min, max))
                values_expected = []
                for k, v in zip(keys, values):
                    if min <= k <= max:
                        values_expected.append(v)
                if values_expected != values_got:
                    btree.show()
                self.assertListEqual(values_expected, values_got)

    def test_counting_leaf_raises_not_implemented_error(self):
        """Regression test: the unsupported CountingLeaf operations must raise NotImplementedError.

        Previously they used ``raise NotImplemented`` which raises a TypeError instead, so we explicitly
        assert the correct exception type here.
        """
        leaf: BPlusTree.CountingLeaf = BPlusTree.CountingLeaf()

        # supported operations keep working:
        leaf.put(1, 1)
        leaf.put(2, 2)
        self.assertEqual(leaf.size(), 2)

        # unsupported operations raise NotImplementedError (and NOT TypeError):
        self.assertRaises(NotImplementedError, leaf.split)
        self.assertRaises(NotImplementedError, leaf.get, 1)
        self.assertRaises(NotImplementedError, leaf.get_all_in_range, 0, 10)
        self.assertRaises(NotImplementedError, leaf.is_full)
        self.assertRaises(NotImplementedError, leaf.consistency_check)


class RadixTrieTest(unittest.TestCase):

    def test_radix_trie(self):

        prefix_mapping: PrefixDigitMapping = PrefixDigitMapping()
        self.assertEqual(prefix_mapping.map("35576", 0), 3)
        self.assertEqual(prefix_mapping.map("324564", 1), 2)
        self.assertEqual(prefix_mapping.map("324456456", 1), 2)

        trie: RadixTrie[str, str] = RadixTrie[str, str](
            key_mapping=prefix_mapping,
            children_per_inner_node=4,
            number_of_inner_node_levels=1,
        )

        trie.put("32", "g")
        trie.put("33", "s")
        trie.put("13", "f")
        # trie.show()

        trie: RadixTrie[str, str] = RadixTrie[str, str](
            key_mapping=prefix_mapping,
            children_per_inner_node=2,
            number_of_inner_node_levels=3,
        )
        trie.put("110", "a")
        trie.put("101", "b")
        trie.put("010", "c")
        # trie.show()

        for number_of_inner_node_levels in [0, 1, 2, 3]:
            for children_per_inner_node in [2, 3, 7, 15]:
                trie: RadixTrie[str, str] = RadixTrie[str, str](
                    key_mapping=prefix_mapping,
                    children_per_inner_node=children_per_inner_node,
                    number_of_inner_node_levels=number_of_inner_node_levels,
                )
                # nodes created by the trie:
                actual_nodes: int = trie.number_of_nodes()

                # nodes expected to be created by the trie:
                inner_nodes: int = sum(
                    children_per_inner_node**level
                    for level in range(number_of_inner_node_levels)
                )
                leaves: int = children_per_inner_node**number_of_inner_node_levels
                total_nodes: int = inner_nodes + leaves

                self.assertEqual(actual_nodes, total_nodes)


class ChristmasTreeTest(unittest.TestCase):

    def test_christmas_tree(self):
        triangle: Triangle = Triangle(Vector(0, 0), Vector(300, 0), Vector(150, 300))

        # check different variants of the ChristmasTree by varying the inner_node_factory:
        for node_factory in [
            ChristmasTree.InnerNodeFactory[Vector, str](config="inner"),
            ChristmasTree.InnerNodeFactory[Vector, str](config="buffered"),
            ChristmasTree.InnerNodeFactory[Vector, str](config="crystalball"),
        ]:
            christmas_trie: ChristmasTree[Vector, str] = ChristmasTree[Vector, str](
                children_per_inner_node=4,
                descriptor=triangle,
                number_of_inner_node_levels=2,
                inner_node_factory=node_factory,
            )
            # christmas_trie.show()

            for i in range(1000):
                v: Vector
                while True:
                    v = Vector(random.randint(0, 300), random.randint(0, 300))
                    if triangle.contains(v):
                        break
                christmas_trie.put(v, str(i))
                # christmas_trie.show()

                # test get
                # christmas_trie.show()
                self.assertIn(str(i), list(christmas_trie.get(v)))
            # christmas_trie.show()


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
