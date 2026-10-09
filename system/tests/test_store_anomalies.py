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
"""Tests for transactional store isolation and anomalies (snapshot isolation, write skew)."""

import unittest

from system.query_processing.predicates import WHERE_Clause, TrueClause
from system.stores.VersionedKeyValueStore import HashableDict, VersionedKeyValueStore
from system.stores.MVCC import (
    Abort,
    Begin,
    TransactionAbortedException,
    TransactionalKeyValueStore,
)
from system.stores.IndexedMVCC import IndexedTransactionalKeyValueStore
from dataclasses import dataclass
from faker import Faker

from system.tests.abstract_unit_test import AbstractUnitTest

Faker.seed(42)


class StoreTestAnomalies(AbstractUnitTest):

    def test_update_multiple_objects_in_TA(self):
        tkvs = TransactionalKeyValueStore()
        tkvs.bulkload(self._create_fake_data())
        TA_id = tkvs.begin_transaction()

        # modify object <object_id> multiple times:
        # allows us to test if the write set is correctly updated
        object_ids_to_test = ["42", "11", "0", "7", "99"]

        for i in range(3):

            for idx, object_id in enumerate(object_ids_to_test):
                # bypass the store to read an object (we will test reading separately):
                _object: object = tkvs.key_value_store[object_id].committed[0].value

                # modify the object, i.e. create a new instance as we use frozen data classes:
                _object = StoreTestAnomalies.Stuff(a=_object.a, b=_object.b + 4242)

                tkvs.update_object(object_id, _object, TA_id)
                self.assertEqual(len(tkvs.TD[TA_id].read_clauses), 0)
                # now, there must be a wip-entry by this TA:
                self.assertEqual(
                    tkvs.key_value_store[object_id].wip.start_validity, TA_id
                )
                self.assertTrue(
                    isinstance(
                        tkvs.key_value_store[object_id].wip,
                        VersionedKeyValueStore.UpdateEntry,
                    )
                )

                # instances must be different, i.e. we created a copy:
                self.assertNotEqual(
                    id(_object), id(tkvs.key_value_store[object_id].wip.value)
                )
                self.assertEqual(
                    len(tkvs.TD[TA_id].write_set),
                    len(object_ids_to_test) if i > 0 else idx + 1,
                )
                self.assertIn(object_id, tkvs.TD[TA_id].write_set)

        # commit the transaction:
        tkvs.commit_transaction(TA_id)

        # now we have two committed versions for each object:
        for object_id in object_ids_to_test:
            self.assertEqual(len(tkvs.key_value_store[object_id].committed), 2)

            # and no wip entry:
            self.assertIsNone(tkvs.key_value_store[object_id].wip)

        # write set is still there:
        self.assertEqual(len(tkvs.TD[TA_id].write_set), len(object_ids_to_test))

    def test_store_snapshot_isolation_TA_self_modification(self):
        """Tests if the store correctly handles reads from the store in particular w.r.t. snapshot isolation from the
        point of view of a single TA"""

        tkvs = TransactionalKeyValueStore()
        tkvs.bulkload(self._create_fake_data())

        object_id: str = "4242"

        # create an object with an object_id that is guaranteed to not be in the store yet:
        # (if they were, put would overwrite them anyway
        tkvs.put(object_id, StoreTestAnomalies.Stuff(4243, 0))

        TA_ID = tkvs.begin_transaction()
        where = WHERE_Clause("a", "==", 4243)
        result_initial: list[tuple[str, object]] = list(
            tkvs.read_objects(TA_ID, where=where)
        )
        self.assertEqual(len(result_initial), 1)

        item: tuple[str, object] = result_initial[0]

        self.assertEqual(object_id, item[0])
        self.assertEqual(4243, item[1].a)
        self.assertEqual(0, item[1].b)

        new_version = StoreTestAnomalies.Stuff(4243, 4243)
        tkvs.update_object("4242", new_version, TA_ID)

        # committed version is untouched:
        self.assertEqual(tkvs.key_value_store["4242"].committed[0].value.b, 0)

        # and nothing was added to the commit list:
        self.assertEqual(len(tkvs.key_value_store["4242"].committed), 1)

        # we have a wip entry now:
        self.assertEqual(tkvs.key_value_store["4242"].wip.value.b, 4243)

        # bypass store semantics and add a new committed version
        # simulating an insert from another concurrent transaction with a greater TA_ID than <TA_ID>:
        tkvs.key_value_store["4242"].committed.append(
            VersionedKeyValueStore.UpdateEntry(
                start_validity=TA_ID + 1, value=StoreTestAnomalies.Stuff(45, 45)
            )
        )
        self.assertEqual(len(tkvs.key_value_store["4242"].committed), 2)

        # read the same object again:
        result_reread: list[tuple[str, object]] = list(
            tkvs.read_objects(TA_ID, where=where)
        )
        self.assertEqual(len(result_reread), 1)

        item: tuple[str, object] = result_reread[0]
        # snapshot isolation must return the same object as before:
        self.assertEqual(new_version, item[1])

    def test_snapshot_isolation_read_correct_version(self):
        """Tests if the store correctly handles reads from the store in particular w.r.t. snapshot isolation"""

        tkvs = TransactionalKeyValueStore()

        object_id: str = "4242"

        # build a committed list and force it into the store:
        tkvs.key_value_store[object_id] = VersionedKeyValueStore.KVStoreEntry(
            committed=[
                VersionedKeyValueStore.UpdateEntry(
                    start_validity=0, value=StoreTestAnomalies.Stuff(45, 45)
                ),
                VersionedKeyValueStore.UpdateEntry(
                    start_validity=5, value=StoreTestAnomalies.Stuff(47, 45)
                ),
                VersionedKeyValueStore.UpdateEntry(
                    start_validity=8, value=StoreTestAnomalies.Stuff(49, 45)
                ),
            ]
        )

        # read different versions of the object:
        ret = tkvs._get_visible_object_version(object_id, 1)
        self.assertEqual(ret, StoreTestAnomalies.Stuff(45, 45))
        ret = tkvs._get_visible_object_version(object_id, 6)
        self.assertEqual(ret, StoreTestAnomalies.Stuff(47, 45))
        ret = tkvs._get_visible_object_version(object_id, 9)
        self.assertEqual(ret, StoreTestAnomalies.Stuff(49, 45))

        # intentionally destroy commit order in the committed list:
        tkvs.key_value_store[object_id].committed.append(
            VersionedKeyValueStore.UpdateEntry(
                start_validity=4, value=StoreTestAnomalies.Stuff(50, 45)
            )
        )

        # assert of the store must fail now:
        with self.assertRaises(Exception):
            tkvs._get_visible_object_version(object_id, 6)

    def test_read_write_conflict(self):
        """Tests if the store correctly handles reads from the store in particular w.r.t. snapshot isolation while
        interacting with other modifying TAs."""

        tkvs = TransactionalKeyValueStore()

        object_id: str = "4242"

        # create a data item in the store:
        tkvs.put(object_id, StoreTestAnomalies.Stuff(7, 0))

        # start two transactions:
        TA_ID_1 = tkvs.begin_transaction()
        TA_ID_2 = tkvs.begin_transaction()

        # TA 1 reads an object from the store:
        where = WHERE_Clause("a", "==", 7)
        result_initial: list[tuple[str, object]] = list(
            tkvs.read_objects(TA_ID_1, where=where)
        )
        self.assertEqual(len(result_initial), 1)

        item: tuple[str, object] = result_initial[0]
        self.assertEqual(item[0], object_id)
        self.assertEqual(7, item[1].a)

        # TA 2 creates a new version of the object and performs an update:
        new_version = StoreTestAnomalies.Stuff(7, 8)
        tkvs.update_object(object_id, new_version, TA_ID_2)

        # committed version in the store is untouched:
        self.assertEqual(tkvs.key_value_store[object_id].committed[0].value.b, 0)

        # and nothing was added to the commit list:
        self.assertEqual(len(tkvs.key_value_store[object_id].committed), 1)

        # we have a wip entry now:
        self.assertEqual(tkvs.key_value_store[object_id].wip.value.b, 8)

        # and it is from TA_ID_2:
        self.assertEqual(tkvs.key_value_store[object_id].wip.start_validity, TA_ID_2)

        # TA_ID_1 must not see the new (wip)-value from TA 2, TA 1 still sees the old object:
        result_reread = list(tkvs.read_objects(TA_ID_1, where=where))
        self.assertEqual(result_initial, result_reread)

        # now, commit transaction TA_ID_2:
        tkvs.commit_transaction(TA_ID_2)

        # the wip entry is gone:
        self.assertIsNone(tkvs.key_value_store[object_id].wip)

        # we have a new committed version:
        self.assertEqual(len(tkvs.key_value_store[object_id].committed), 2)

        # TA_ID_1 must not see the new value even though TA_ID_2 has already committed,
        # TA_ID 1 still sees the old object as it is running under snapshot isolation -> repeatable reads
        result_reread = list(tkvs.read_objects(TA_ID_1, where=where))
        self.assertEqual(result_initial, result_reread)

        # now, let's try to commit transaction TA_ID_1:
        # this must fail: because TA_ID_1 has read an object that has been modified and committed by another transaction
        # (TA 2) after TA_ID_1 started.
        # Note: TA 1 has to update something, otherwise it would be a read-only transaction and hence always pass
        # validation:
        tkvs.update_object(object_id, StoreTestAnomalies.Stuff(7, 4534), TA_ID_1)

        with self.assertRaises(TransactionAbortedException):
            tkvs.commit_transaction(TA_ID_1)

        # start a new transaction TA 3:
        TA_ID_3 = tkvs.begin_transaction()

        # TA_ID_3 must see the new value just committed by TA_ID_2:
        result_reread_TA_3: list[tuple[str, object]] = list(
            tkvs.read_objects(TA_ID_3, where=where)
        )
        self.assertEqual(len(result_initial), 1)
        item_reread: tuple[str, object] = result_reread_TA_3[0]

        self.assertEqual(item_reread[1], new_version)

    def test_write_skew_anomaly(self):
        """Checks for write skew anomaly detection. Checks both validation algorithms"""

        for use_brute_force_validation in [
            True,
            False,
        ]:  # test both validation algorithms

            tkvs = TransactionalKeyValueStore(
                use_brute_force_validation=use_brute_force_validation
            )

            # create two data items A and B:
            tkvs.put("X", StoreTestAnomalies.Stuff(1, 0))
            tkvs.put("Y", StoreTestAnomalies.Stuff(2, 0))

            # start two transactions:
            TA_ID_1: int = tkvs.begin_transaction()
            TA_ID_2: int = tkvs.begin_transaction()
            self.assertNotEqual(TA_ID_1, TA_ID_2)

            where_A = WHERE_Clause("a", "==", 1)
            where_B = WHERE_Clause("a", "==", 2)

            # TA_1 reads both objects X and Y from the store:
            result_X_TA_1: list[tuple[str, object]] = list(
                tkvs.read_objects(TA_ID_1, where=where_A)
            )
            result_Y_TA_1: list[tuple[str, object]] = list(
                tkvs.read_objects(TA_ID_1, where=where_B)
            )
            self.assertEqual(len(result_X_TA_1), 1)
            self.assertEqual(len(result_Y_TA_1), 1)

            # TA_2 reads the same objects X and Y from the store:
            result_X_TA_2: list[tuple[str, object]] = list(
                tkvs.read_objects(TA_ID_2, where=where_A)
            )
            result_Y_TA_2: list[tuple[str, object]] = list(
                tkvs.read_objects(TA_ID_2, where=where_B)
            )
            self.assertEqual(len(result_X_TA_2), 1)
            self.assertEqual(len(result_Y_TA_2), 1)

            new_X_Version_TA_1 = StoreTestAnomalies.Stuff(1, 100)

            # TA_1 updates object X:
            tkvs.update_object("X", new_X_Version_TA_1, TA_ID_1)

            # TA_2 updates object Y:
            new_Y_Version_TA_2 = StoreTestAnomalies.Stuff(2, 200)
            tkvs.update_object("Y", new_Y_Version_TA_2, TA_ID_2)

            # now, commit transaction TA_1:
            tkvs.commit_transaction(TA_ID_1)

            # now, commit transaction TA_2:
            # this must fail: because TA_ID_2 has read an object that has been modified and committed by
            # another transaction, i.e. TA_ID_1
            with self.assertRaises(TransactionAbortedException):
                tkvs.commit_transaction(TA_ID_2)

    def test_delete_semantics(self):
        """Tests if the store correctly handles object deletions"""

        tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore()

        # create an object in the store:
        object_id = "4042"

        tkvs.put(object_id, StoreTestAnomalies.Stuff(4243, 0))

        # begin a transaction:
        TA_ID = tkvs.begin_transaction()

        # read the object:
        where = WHERE_Clause("a", "==", 4243)
        result_initial: list[tuple[str, object]] = list(
            tkvs.read_objects(TA_ID, where=where)
        )
        self.assertEqual(result_initial[0][0], object_id)
        item: tuple[str, object] = result_initial[0]

        self.assertEqual(len(result_initial), 1)
        self.assertEqual(4243, item[1].a)
        self.assertEqual(0, item[1].b)

        # delete the object:
        tkvs.delete_object(object_id, TA_ID)

        # the committed version is untouched:
        self.assertEqual(tkvs.key_value_store[object_id].committed[0].value.b, 0)

        # and nothing was added to the commit list:
        self.assertEqual(len(tkvs.key_value_store[object_id].committed), 1)

        # we have aa delete marker now:
        self.assertTrue(
            isinstance(
                tkvs.key_value_store[object_id].wip, VersionedKeyValueStore.DeleteEntry
            )
        )

        # and it is from TA_ID:
        self.assertEqual(tkvs.key_value_store[object_id].wip.start_validity, TA_ID)

        # commit the transaction:
        tkvs.commit_transaction(TA_ID)

        # now we have two committed versions for each object:
        self.assertEqual(len(tkvs.key_value_store[object_id].committed), 2)

        # and no wip entry:
        self.assertIsNone(tkvs.key_value_store[object_id].wip)

        # read the same object again:
        # this must fail as we already committed transaction <TA_ID> and are not allowed to perform further reads:
        with self.assertRaises(Exception):
            list(tkvs.read_objects(TA_ID, where=where))

        # same for deletes:
        with self.assertRaises(Exception):
            tkvs.delete_object(object_id, TA_ID)

        # same for updates:
        with self.assertRaises(Exception):
            tkvs.update_object(object_id, StoreTestAnomalies.Stuff(4243, 0), TA_ID)

        # start a new transaction:
        TA_ID_2 = tkvs.begin_transaction()

        # read the same object again from TA_ID_2:
        result_reread_TA_2 = list(tkvs.read_objects(TA_ID_2, where=where))

        # must not see the object anymore:
        self.assertEqual(len(result_reread_TA_2), 0)

    def test_write_write_conflict(self):
        tkvs = TransactionalKeyValueStore()
        object_id = "4242"
        tkvs.put(object_id, StoreTestAnomalies.Stuff(1, 0))

        TA_ID_1 = tkvs.begin_transaction()
        TA_ID_2 = tkvs.begin_transaction()

        tkvs.update_object(object_id, StoreTestAnomalies.Stuff(1, 1), TA_ID_1)

        # TA 2 tries to update the same object, this must fail as there is a write-write conflict:
        # there can only be one writer at a time
        with self.assertRaises(TransactionAbortedException):
            tkvs.update_object(object_id, StoreTestAnomalies.Stuff(1, 2), TA_ID_2)

    def test_write_write_conflict_on_delete(self):
        """A transaction that deletes an object on which another transaction holds a wip entry is aborted.

        t1                                  t2
        begin
                                            begin
        update or delete "4242"
                                            delete "4242" -> aborted
        commit -> succeeds

        t2 is removed from the transaction dictionary and its journal holds only Begin and Abort; t1's wip entry
        is untouched. Checked for a first writer that updates and one that deletes.
        """
        for first_write in ["update", "delete"]:
            with self.subTest(first_write=first_write):
                tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore()
                object_id: str = "4242"
                tkvs.put(object_id, StoreTestAnomalies.Stuff(1, 0))

                TA_ID_1: int = tkvs.begin_transaction()
                TA_ID_2: int = tkvs.begin_transaction()

                # TA 1 becomes the single writer of the object:
                if first_write == "update":
                    tkvs.update_object(
                        object_id, StoreTestAnomalies.Stuff(1, 1), TA_ID_1
                    )
                else:
                    tkvs.delete_object(object_id, TA_ID_1)

                # TA 2 tries to delete the same object: write-write conflict, TA 2 must be aborted:
                with self.assertRaises(TransactionAbortedException):
                    tkvs.delete_object(object_id, TA_ID_2)

                # TA 2 is gone from the transaction dictionary:
                self.assertNotIn(TA_ID_2, tkvs.TD)

                # TA 1's wip entry is unchanged:
                entry: VersionedKeyValueStore.KVStoreEntry = tkvs.key_value_store[
                    object_id
                ]
                wip: VersionedKeyValueStore.VersionEntry | None = entry.wip
                self.assertIsNotNone(wip)
                self.assertEqual(wip.start_validity, TA_ID_1)
                if first_write == "update":
                    self.assertIsInstance(wip, VersionedKeyValueStore.UpdateEntry)
                    self.assertEqual(wip.value, StoreTestAnomalies.Stuff(1, 1))
                else:
                    self.assertIsInstance(wip, VersionedKeyValueStore.DeleteEntry)

                # TA 2 wrote nothing to the journal except its begin and abort entries:
                self.assertEqual(
                    list(tkvs.journal.get(TA_ID_2)),
                    [Begin(TA_id=TA_ID_2), Abort(TA_id=TA_ID_2)],
                )

                # TA 1 can still commit:
                tkvs.commit_transaction(TA_ID_1)
                self.assertEqual(tkvs.committed_transactions_trace[-1], TA_ID_1)

    def test_double_update_from_same_transaction(self):
        tkvs = TransactionalKeyValueStore()
        object_id = "4242"
        tkvs.put(object_id, StoreTestAnomalies.Stuff(1, 0))

        TA_ID_1 = tkvs.begin_transaction()

        # where-clause to read the object:
        where_A: WHERE_Clause = WHERE_Clause("a", "==", 1)

        # first update:
        tkvs.update_object(object_id, StoreTestAnomalies.Stuff(1, 1), TA_ID_1)

        # now read:
        result: list[tuple[str, object]] = tkvs.read_objects(TA_ID_1, where_A)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], (object_id, StoreTestAnomalies.Stuff(1, 1)))

        # second update:
        tkvs.update_object(object_id, StoreTestAnomalies.Stuff(1, 2), TA_ID_1)

        # now read again:
        result: list[tuple[str, object]] = tkvs.read_objects(TA_ID_1, where_A)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], (object_id, StoreTestAnomalies.Stuff(1, 2)))

        # third update, i.e. delete the object:
        tkvs.delete_object(object_id, TA_ID_1)
        result: list[tuple[str, object]] = tkvs.read_objects(TA_ID_1, where_A)
        self.assertEqual(len(result), 0)

    def test_checksums_on_self_updates(self):
        @dataclass(frozen=True)
        class T:
            a: int
            b: int

        tkvs = TransactionalKeyValueStore(use_brute_force_validation=True)

        tkvs.put("1", T(1, 1))

        t1 = tkvs.begin_transaction()

        # read the object:
        ret1: list[tuple[str, object]] = tkvs.read_objects(
            t1, WHERE_Clause("a", "==", 1)
        )
        self.assertEqual(len(ret1), 1)

        # modify the object such that it does not match the read clause anymore:
        tkvs.update_object("1", T(2, 2), t1)

        # issue the read again:
        ret2: list[tuple[str, object]] = tkvs.read_objects(
            t1, WHERE_Clause("a", "==", 1)
        )
        self.assertEqual(len(ret2), 0)

        # following line fails if checksums are not correctly updated,
        # i.e. if checksums also consider own changes
        tkvs.commit_transaction(t1)
        self.assertEqual(tkvs.committed_transactions_trace[-1], t1)

    def test_read_all(self):
        """Tests if the store correctly handles read_all requests"""

        @dataclass(frozen=True)
        class T:
            a: int
            b: int

        for use_brute_force_validation in [True, False]:
            for t2_commits in [True, False]:
                tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore(
                    use_brute_force_validation=use_brute_force_validation
                )

                tkvs.put("1", T(1, 1))
                tkvs.put("2", T(2, 2))

                t1 = tkvs.begin_transaction()
                t2 = tkvs.begin_transaction()

                # t2 modifies something after t1 started...
                tkvs.update_object("1", T(11, 11), t2)

                # ... and commits:
                if t2_commits:
                    tkvs.commit_transaction(t2)

                # t1 reads everything from its snapshot with a TrueClause:
                ret1: list[tuple[str, object]] = tkvs.read_objects(t1, TrueClause())
                self.assertEqual(len(ret1), 2)

                # t1 modifies something (possibly influenced by the previous read)
                tkvs.update_object("2", T(22, 22), t1)

                # t1 commits and fails validation:
                if t2_commits:
                    with self.assertRaises(TransactionAbortedException):
                        tkvs.commit_transaction(t1)
                else:
                    tkvs.commit_transaction(t1)

    def test_read_skips_object_inserted_and_committed_after_snapshot(self):
        """A reader does not see an object that a TA inserted and committed after the reader began.

        t_i                                 t_j
        begin
                                            begin
                                            insert C
                                            commit
        read all -> sees only A
        """
        tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore()
        tkvs.put("A", StoreTestAnomalies.Stuff(1, 0))

        t_i: int = tkvs.begin_transaction()
        t_j: int = tkvs.begin_transaction()

        # t_j inserts a brand-new object and commits:
        tkvs.update_object("C", StoreTestAnomalies.Stuff(42, 0), t_j)
        tkvs.commit_transaction(t_j)

        # C did not exist in t_i's snapshot:
        result: list[tuple[str, object]] = tkvs.read_objects(t_i, TrueClause())
        self.assertEqual(result, [("A", StoreTestAnomalies.Stuff(1, 0))])

    def test_read_skips_object_inserted_by_uncommitted_concurrent_TA(self):
        """A reader does not see an object that another, still running TA has inserted.

        t_i                                 t_j
        begin
                                            begin
                                            insert C
        read all -> sees only A
        """
        tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore()
        tkvs.put("A", StoreTestAnomalies.Stuff(1, 0))

        t_i: int = tkvs.begin_transaction()
        t_j: int = tkvs.begin_transaction()

        # t_j inserts a brand-new object, but does not commit:
        tkvs.update_object("C", StoreTestAnomalies.Stuff(42, 0), t_j)

        result: list[tuple[str, object]] = tkvs.read_objects(t_i, TrueClause())
        self.assertEqual(result, [("A", StoreTestAnomalies.Stuff(1, 0))])

    def test_read_own_insert(self):
        """A TA sees the object it inserted itself, next to the pre-existing objects.

        t inserts C and reads everything: it sees A and C with their values.
        """
        tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore()
        tkvs.put("A", StoreTestAnomalies.Stuff(1, 0))

        t: int = tkvs.begin_transaction()
        tkvs.update_object("C", StoreTestAnomalies.Stuff(2, 0), t)

        result: list[tuple[str, object]] = tkvs.read_objects(t, TrueClause())
        self.assertEqual(
            sorted(result, key=lambda item: item[0]),
            [
                ("A", StoreTestAnomalies.Stuff(1, 0)),
                ("C", StoreTestAnomalies.Stuff(2, 0)),
            ],
        )

    def test_aborted_insert_is_invisible_and_key_can_be_reinserted(self):
        """An aborted insert leaves no visible object behind, and the key can be inserted again later.

        t inserts C and aborts: t2 sees only A. t3 inserts C again and commits: t4 sees A and C with t3's value.
        """
        tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore()
        tkvs.put("A", StoreTestAnomalies.Stuff(1, 0))

        # insert C and abort:
        t: int = tkvs.begin_transaction()
        tkvs.update_object("C", StoreTestAnomalies.Stuff(2, 0), t)
        tkvs.abort_transaction(t)

        # the aborted insert must not be visible:
        t2: int = tkvs.begin_transaction()
        result_t2: list[tuple[str, object]] = tkvs.read_objects(t2, TrueClause())
        self.assertEqual(result_t2, [("A", StoreTestAnomalies.Stuff(1, 0))])

        # re-insert C and commit:
        t3: int = tkvs.begin_transaction()
        tkvs.update_object("C", StoreTestAnomalies.Stuff(3, 0), t3)
        tkvs.commit_transaction(t3)

        # a later TA sees the re-inserted value:
        t4: int = tkvs.begin_transaction()
        result_t4: list[tuple[str, object]] = tkvs.read_objects(t4, TrueClause())
        self.assertEqual(
            sorted(result_t4, key=lambda item: item[0]),
            [
                ("A", StoreTestAnomalies.Stuff(1, 0)),
                ("C", StoreTestAnomalies.Stuff(3, 0)),
            ],
        )

    def test_get_visible_object_version_returns_None_if_object_not_in_snapshot(self):
        """_get_visible_object_version returns None for an object that does not exist in the reader's snapshot.

        This covers an object whose only committed version starts at or after the reader's timestamp, and an object
        with an empty committed list.
        """
        tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore()

        # (a) the only committed version became valid at timestamp 5:
        tkvs.key_value_store["late"] = VersionedKeyValueStore.KVStoreEntry(
            committed=[
                VersionedKeyValueStore.UpdateEntry(
                    start_validity=5, value=StoreTestAnomalies.Stuff(1, 0)
                )
            ]
        )
        # an older reader and a reader with the same timestamp (boundary) must not see it:
        self.assertIsNone(tkvs._get_visible_object_version("late", 3))
        self.assertIsNone(tkvs._get_visible_object_version("late", 5))

        # (b) no committed version at all:
        tkvs.key_value_store["empty"] = VersionedKeyValueStore.KVStoreEntry(
            committed=[]
        )
        self.assertIsNone(tkvs._get_visible_object_version("empty", 3))

    def test_validation_detects_lost_update_on_read_object(self):
        """A TA that read an object and then overwrites it aborts if another TA committed a change to it meanwhile.

        t_i                                 t_j
        begin
                                            begin
        read a==42 -> sees A=(42, 0)
                                            update A to (7, 0)
                                            commit
        update A to (5, 0)
        commit -> aborted

        Validation compares against the version t_i read, (42, 0), not t_i's own work-in-progress version. Checked for
        both validation methods.
        """
        for use_brute_force_validation in [True, False]:
            with self.subTest(use_brute_force_validation=use_brute_force_validation):
                tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore(
                    use_brute_force_validation=use_brute_force_validation
                )
                tkvs.put("A", StoreTestAnomalies.Stuff(42, 0))

                t_i: int = tkvs.begin_transaction()
                t_j: int = tkvs.begin_transaction()

                # t_i reads A:
                result: list[tuple[str, object]] = tkvs.read_objects(
                    t_i, WHERE_Clause("a", "==", 42)
                )
                self.assertEqual(result, [("A", StoreTestAnomalies.Stuff(42, 0))])

                # t_j changes A and commits:
                tkvs.update_object("A", StoreTestAnomalies.Stuff(7, 0), t_j)
                tkvs.commit_transaction(t_j)

                # t_i overwrites A based on its outdated read (allowed: no wip entry on A anymore):
                tkvs.update_object("A", StoreTestAnomalies.Stuff(5, 0), t_i)

                with self.assertRaises(TransactionAbortedException):
                    tkvs.commit_transaction(t_i)

    def test_validation_detects_phantom_insert(self):
        """A TA aborts if another TA committed an insert that matches one of its earlier reads.

        t_i                                 t_j
        begin
                                            begin
        read a==42 -> sees nothing
                                            insert C=(42, 0)
                                            commit
        update A
        commit -> aborted

        C did not exist in t_i's snapshot but matches now. Checked for both validation methods.
        """
        for use_brute_force_validation in [True, False]:
            with self.subTest(use_brute_force_validation=use_brute_force_validation):
                tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore(
                    use_brute_force_validation=use_brute_force_validation
                )
                tkvs.put("A", StoreTestAnomalies.Stuff(1, 0))

                t_i: int = tkvs.begin_transaction()
                t_j: int = tkvs.begin_transaction()

                # t_i reads and finds nothing:
                result: list[tuple[str, object]] = tkvs.read_objects(
                    t_i, WHERE_Clause("a", "==", 42)
                )
                self.assertEqual(result, [])

                # t_j inserts a matching object and commits (phantom for t_i):
                tkvs.update_object("C", StoreTestAnomalies.Stuff(42, 0), t_j)
                tkvs.commit_transaction(t_j)

                # t_i writes something, so it is not read-only and must be validated:
                tkvs.update_object("A", StoreTestAnomalies.Stuff(2, 0), t_i)

                with self.assertRaises(TransactionAbortedException):
                    tkvs.commit_transaction(t_i)

    def test_validation_detects_concurrent_delete_of_read_object(self):
        """A TA aborts if another TA committed the deletion of an object it had read.

        t_i                                 t_j
        begin
                                            begin
        read a==42 -> sees A
                                            delete A
                                            commit
        update B
        commit -> aborted

        A matched in t_i's snapshot. Checked for both validation methods.
        """
        for use_brute_force_validation in [True, False]:
            with self.subTest(use_brute_force_validation=use_brute_force_validation):
                tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore(
                    use_brute_force_validation=use_brute_force_validation
                )
                tkvs.put("A", StoreTestAnomalies.Stuff(42, 0))
                tkvs.put("B", StoreTestAnomalies.Stuff(0, 0))

                t_i: int = tkvs.begin_transaction()
                t_j: int = tkvs.begin_transaction()

                # t_i reads A:
                result: list[tuple[str, object]] = tkvs.read_objects(
                    t_i, WHERE_Clause("a", "==", 42)
                )
                self.assertEqual(result, [("A", StoreTestAnomalies.Stuff(42, 0))])

                # t_j deletes A and commits:
                tkvs.delete_object("A", t_j)
                tkvs.commit_transaction(t_j)

                # t_i writes a different object, possibly based on what it read about A:
                tkvs.update_object("B", StoreTestAnomalies.Stuff(1, 0), t_i)

                with self.assertRaises(TransactionAbortedException):
                    tkvs.commit_transaction(t_i)

    def test_validation_detects_change_after_read_without_predicate(self):
        """A TA that read all objects (no WHERE clause) aborts if another TA committed a change to any of them.

        t_i                                 t_j
        begin
                                            begin
        read all -> sees A and B
                                            update A
                                            commit
        update B
        commit -> aborted

        A read without a WHERE clause selects every existing object. Checked for both validation methods.
        """
        for use_brute_force_validation in [True, False]:
            with self.subTest(use_brute_force_validation=use_brute_force_validation):
                tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore(
                    use_brute_force_validation=use_brute_force_validation
                )
                tkvs.put("A", StoreTestAnomalies.Stuff(1, 0))
                tkvs.put("B", StoreTestAnomalies.Stuff(1, 0))

                t_i: int = tkvs.begin_transaction()
                t_j: int = tkvs.begin_transaction()

                # t_i reads everything, i.e. without a WHERE clause:
                result: list[tuple[str, object]] = tkvs.read_objects(t_i)
                self.assertEqual(
                    sorted(result, key=lambda item: item[0]),
                    [
                        ("A", StoreTestAnomalies.Stuff(1, 0)),
                        ("B", StoreTestAnomalies.Stuff(1, 0)),
                    ],
                )

                # t_j changes A and commits:
                tkvs.update_object("A", StoreTestAnomalies.Stuff(9, 0), t_j)
                tkvs.commit_transaction(t_j)

                # t_i writes B, possibly based on what it read about A:
                tkvs.update_object("B", StoreTestAnomalies.Stuff(5, 0), t_i)

                with self.assertRaises(TransactionAbortedException):
                    tkvs.commit_transaction(t_i)

    def test_validation_ignores_concurrent_write_outside_read_predicate(self):
        """A TA commits if the only concurrent change touched an object that never matched its reads.

        t_i                                 t_j
        begin
                                            begin
        read a==42 -> sees A
                                            update X from (1, 0) to (2, 0)
                                            commit
        update A
        commit -> succeeds

        X matches a==42 neither before nor after t_j's change. Checked for both validation methods.
        """
        for use_brute_force_validation in [True, False]:
            with self.subTest(use_brute_force_validation=use_brute_force_validation):
                tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore(
                    use_brute_force_validation=use_brute_force_validation
                )
                tkvs.put("A", StoreTestAnomalies.Stuff(42, 0))
                tkvs.put("X", StoreTestAnomalies.Stuff(1, 0))

                t_i: int = tkvs.begin_transaction()
                t_j: int = tkvs.begin_transaction()

                # t_i reads A:
                result: list[tuple[str, object]] = tkvs.read_objects(
                    t_i, WHERE_Clause("a", "==", 42)
                )
                self.assertEqual(result, [("A", StoreTestAnomalies.Stuff(42, 0))])

                # t_j changes X, which never matches t_i's read, and commits:
                tkvs.update_object("X", StoreTestAnomalies.Stuff(2, 0), t_j)
                tkvs.commit_transaction(t_j)

                # t_i updates A and must commit:
                tkvs.update_object("A", StoreTestAnomalies.Stuff(43, 0), t_i)
                tkvs.commit_transaction(t_i)
                self.assertEqual(tkvs.committed_transactions_trace[-1], t_i)

    def test_read_objects_evaluates_where_clause_twice_only_for_method_1(self):
        """With validation method 2, read_objects evaluates the where clause once per object; method 1 evaluates it a
        second time on the committed snapshot to compute the checksum. The result contains the transaction's own
        change.

        Checked for both store classes and both validation methods.
        """

        class CountingWHERE_Clause(WHERE_Clause):
            """A WHERE clause that counts how often it is evaluated."""

            def __init__(self, attribute: str, operator: str, constant):
                """See :meth:`WHERE_Clause.__init__`. Starts the evaluation counter at 0."""
                super().__init__(attribute, operator, constant)
                self.evaluations: int = 0

            def evaluate(self, _object: object) -> bool:
                """See :meth:`WHERE_Clause.evaluate`. Also increments the evaluation counter."""
                self.evaluations += 1
                return super().evaluate(_object)

        for store_class in [
            TransactionalKeyValueStore,
            IndexedTransactionalKeyValueStore,
        ]:
            for use_brute_force_validation in [True, False]:
                with self.subTest(
                    store_class=store_class.__name__,
                    use_brute_force_validation=use_brute_force_validation,
                ):
                    tkvs: TransactionalKeyValueStore = store_class(
                        use_brute_force_validation=use_brute_force_validation
                    )
                    tkvs.put("A", StoreTestAnomalies.Stuff(42, 0))
                    # B does not match the where clause, it is evaluated nevertheless:
                    tkvs.put("B", StoreTestAnomalies.Stuff(7, 0))

                    t_i: int = tkvs.begin_transaction()
                    # t_i changes A such that it still matches the where clause:
                    tkvs.update_object("A", StoreTestAnomalies.Stuff(42, 1), t_i)

                    where: CountingWHERE_Clause = CountingWHERE_Clause("a", "==", 42)
                    result: list[tuple[str, object]] = tkvs.read_objects(t_i, where)

                    # check the counter before any commit, as validation in commit evaluates the clause again:
                    # two objects, evaluated twice (method 1) or once (method 2) each:
                    self.assertEqual(
                        where.evaluations, 4 if use_brute_force_validation else 2
                    )
                    self.assertEqual(result, [("A", StoreTestAnomalies.Stuff(42, 1))])

                    # method 1 checksums the committed version of A, method 2 stores no checksum:
                    expected_checksum: int | None = (
                        hash(("A", StoreTestAnomalies.Stuff(42, 0)))
                        if use_brute_force_validation
                        else None
                    )
                    self.assertEqual(
                        tkvs.TD[t_i].read_clauses,
                        {
                            HashableDict(
                                {"where_clause": where, "checksum": expected_checksum}
                            )
                        },
                    )


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
