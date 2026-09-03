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

"""Tests for transactional store isolation and anomalies (snapshot isolation, write skew)."""

import unittest

from system.query_processing.predicates import WHERE_Clause, TrueClause
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore
from system.stores.MVCC import TransactionAbortedException, TransactionalKeyValueStore
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


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
