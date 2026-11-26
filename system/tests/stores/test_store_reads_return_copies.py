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
"""Tests that the reads of the stores hand out copies, so that changing a returned object does not change the store."""

import unittest
from collections.abc import Callable
from dataclasses import dataclass, field

from system.query_processing.predicates import WHERE_Clause
from system.stores.IndexedMVCC import IndexedTransactionalKeyValueStore
from system.stores.MVCC import TransactionalKeyValueStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore
from system.tests.abstract_unit_test import AbstractUnitTest


@dataclass
class MutableStuff:
    """An object whose attributes can be changed in place, unlike the frozen :class:`AbstractUnitTest.Stuff`; the
    where clauses and the index of the tests use its attribute a. Its list c shows whether a copy is deep: a shallow
    copy shares the list with the stored version.
    """

    a: int
    b: int
    c: list[int] = field(default_factory=list)


class StoreReadsReturnCopiesTest(AbstractUnitTest):
    """Every read of the stores that hands objects to the caller returns copies of the stored versions: a caller
    that changes a returned object in place changes neither the store nor its indexes, inside or outside of a
    transaction.
    """

    # the transactional store classes the tests run on (the indexed store must behave like its base class here):
    TRANSACTIONAL_STORE_CLASSES: list[type[TransactionalKeyValueStore]] = [
        TransactionalKeyValueStore,
        IndexedTransactionalKeyValueStore,
    ]

    def test_get_outside_a_transaction_returns_a_copy(self) -> None:
        """Changing the object that get returns outside a transaction does not change the store: the next get and the
        committed version still have the object as it was put. This holds for the versioned store and for the
        transactional stores in the load phase (without autocommit, before the first transaction).
        """
        store_class: type[VersionedKeyValueStore]
        for store_class in [
            VersionedKeyValueStore,
            TransactionalKeyValueStore,
            IndexedTransactionalKeyValueStore,
        ]:
            with self.subTest(store_class=store_class.__name__):
                store: VersionedKeyValueStore = store_class()
                store.put("1", MutableStuff(1, 1))

                # change the object that get returns in place, an attribute and the content of its list:
                read_object: object = next(store.get("1"))
                assert isinstance(read_object, MutableStuff)
                read_object.a = 99
                read_object.c.append(99)

                # the next get still returns the object as it was put:
                self.assertEqual(list(store.get("1")), [MutableStuff(1, 1)])

                # and so does the committed version in the store:
                newest: VersionedKeyValueStore.VersionEntry = store.key_value_store[
                    "1"
                ].committed[-1]
                assert isinstance(newest, VersionedKeyValueStore.UpdateEntry)
                self.assertEqual(newest.value, MutableStuff(1, 1))

    def test_reads_with_autocommit_return_copies(self) -> None:
        """With autocommit, changing the object that get, or read_objects with the transaction id None, returns does
        not change the store: the next read, in a transaction of its own, returns the object as it was put.
        """
        # the two reads without a transaction, each returning the object "1" that it reads:
        reads: dict[str, Callable[[TransactionalKeyValueStore], object]] = {
            "get": lambda store: next(store.get("1")),
            "read_objects": lambda store: dict(store.read_objects(None))["1"],
        }

        store_class: type[TransactionalKeyValueStore]
        for store_class in StoreReadsReturnCopiesTest.TRANSACTIONAL_STORE_CLASSES:
            read_name: str
            read: Callable[[TransactionalKeyValueStore], object]
            for read_name, read in reads.items():
                with self.subTest(store_class=store_class.__name__, read=read_name):
                    store: TransactionalKeyValueStore = store_class(autocommit=True)
                    store.put("1", MutableStuff(1, 1))

                    # change the object that the read returns in place, an attribute and the content of its list:
                    read_object: object = read(store)
                    assert isinstance(read_object, MutableStuff)
                    read_object.a = 99
                    read_object.c.append(99)

                    # the next read still returns the object as it was put:
                    self.assertEqual(read(store), MutableStuff(1, 1))

    def test_read_objects_returns_copies_of_committed_versions(self) -> None:
        """Changing an object that read_objects returns to a transaction does not change the committed version: a
        concurrent transaction still reads the object as it was loaded.

        T1                              T2
        begin
                                        begin
        read all -> "1": (1, 1)
        change a of "1" to 2 in place
        abort
                                        read all -> "1": (1, 1)
                                        commit
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in StoreReadsReturnCopiesTest.TRANSACTIONAL_STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                # load "1", then begin T1 and T2:
                store: TransactionalKeyValueStore = store_class()
                store.put("1", MutableStuff(1, 1))
                T1: int = store.begin_transaction()
                T2: int = store.begin_transaction()

                # T1 reads all objects and changes the object it reads in place, an attribute and its list:
                T1_read: dict[str, object] = dict(store.read_objects(T1))
                self.assertEqual(T1_read, {"1": MutableStuff(1, 1)})
                read_object: object = T1_read["1"]
                assert isinstance(read_object, MutableStuff)
                read_object.a = 2
                read_object.c.append(2)

                # T1 aborts; T2 still reads "1" as it was loaded and commits:
                store.abort_transaction(T1)
                self.assertEqual(
                    dict(store.read_objects(T2)), {"1": MutableStuff(1, 1)}
                )
                store.commit_transaction(T2)

    def test_read_objects_through_an_index_returns_copies(self) -> None:
        """Changing an object that a read through an equality index returns does not change the store: a later
        transaction still finds the object through the index under its old value, and a scan of all objects agrees.

        T1                              T2
        begin
        read a == 1 -> "1": (1, 1)
        change a of "1" to 2 in place
        commit
                                        begin
                                        read a == 1 -> "1": (1, 1)
                                        read all -> "1": (1, 1)
                                        commit
        """
        # an indexed store with an equality index on a, loaded with "1":
        store: IndexedTransactionalKeyValueStore = IndexedTransactionalKeyValueStore()
        store.create_index("a_idx", "a", "=")
        store.put("1", MutableStuff(1, 1))

        # the read-only T1 reads a == 1 through the index:
        T1: int = store.begin_transaction()
        T1_read: dict[str, object] = dict(
            store.read_objects(T1, WHERE_Clause("a", "==", 1))
        )
        self.assertEqual(T1_read, {"1": MutableStuff(1, 1)})

        # T1 changes the object it read in place and commits:
        read_object: object = T1_read["1"]
        assert isinstance(read_object, MutableStuff)
        read_object.a = 2
        store.commit_transaction(T1)

        # T2 still finds "1" through the index under a == 1, unchanged:
        T2: int = store.begin_transaction()
        self.assertEqual(
            dict(store.read_objects(T2, WHERE_Clause("a", "==", 1))),
            {"1": MutableStuff(1, 1)},
        )

        # a scan of all objects agrees, "1" is unchanged:
        self.assertEqual(dict(store.read_objects(T2)), {"1": MutableStuff(1, 1)})
        store.commit_transaction(T2)

    def test_read_objects_returns_a_copy_of_its_own_work_in_progress_version(
        self,
    ) -> None:
        """Changing the object that read_objects returns for the transaction's own work-in-progress version does not
        change that version: the transaction reads it again unchanged, commits it unchanged, and a new transaction
        finds it under its written value (in the indexed store through an equality index on a).

        T1                              T2
        begin
        update "1" to (2, 2)
        read all -> "1": (2, 2)
        change a of "1" to 3 in place
        read all -> "1": (2, 2)
        commit
                                        begin
                                        read a == 2 -> "1": (2, 2)
                                        commit
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in StoreReadsReturnCopiesTest.TRANSACTIONAL_STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                # load "1"; the indexed store gets an equality index on a first, so that T2 reads through it:
                store: TransactionalKeyValueStore = store_class()
                if isinstance(store, IndexedTransactionalKeyValueStore):
                    store.create_index("a_idx", "a", "=")
                store.put("1", MutableStuff(1, 1))

                # T1 updates "1" and reads its own work-in-progress version:
                T1: int = store.begin_transaction()
                store.update_object("1", MutableStuff(2, 2), T1)
                T1_read: dict[str, object] = dict(store.read_objects(T1))
                self.assertEqual(T1_read, {"1": MutableStuff(2, 2)})

                # T1 changes the object it read in place and reads "1" again, unchanged:
                read_object: object = T1_read["1"]
                assert isinstance(read_object, MutableStuff)
                read_object.a = 3
                self.assertEqual(
                    dict(store.read_objects(T1)), {"1": MutableStuff(2, 2)}
                )
                store.commit_transaction(T1)

                # T2 finds "1" under a == 2 with the version T1 wrote:
                T2: int = store.begin_transaction()
                self.assertEqual(
                    dict(store.read_objects(T2, WHERE_Clause("a", "==", 2))),
                    {"1": MutableStuff(2, 2)},
                )
                store.commit_transaction(T2)


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
