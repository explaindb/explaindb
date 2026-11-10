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
"""Tests for basic key-value store operations."""

import contextlib
import io
import re
import unittest
from collections.abc import Callable, Iterator

from system.interfaces.indexing.Index import IndexProperties, KeyValueStore
from system.query_processing.predicates import WHERE_Clause
from system.stores.IndexedMVCC import IndexedTransactionalKeyValueStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore
from system.stores.MVCC import (
    TransactionAbortedException,
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
        # run the same checks on all three store variants; the indexed store overrides the loading only to maintain
        # its indexes and has none here, so all three must behave identically:
        kvs: VersionedKeyValueStore
        for kvs in [
            VersionedKeyValueStore(),
            TransactionalKeyValueStore(),
            IndexedTransactionalKeyValueStore(),
        ]:
            # bulkload 100 (key, Stuff) pairs outside of any transaction:
            kvs.bulkload(self._create_fake_data().__iter__())
            self.assertEqual(kvs.size(), 100)

            # inspect the internal layout of every object: the key is a string, and the object has exactly
            # one committed version (no history yet, as nothing was updated):
            for key, value in kvs.key_value_store.items():
                self.assertIsInstance(key, str)
                entries = value.committed
                self.assertIsInstance(entries, list)
                self.assertEqual(len(entries), 1)

                # this single version is an update entry holding a Stuff object; it is valid from timestamp 0 on,
                # i.e. it is visible to every transaction:
                entry = entries[0]
                self.assertIsInstance(entry, VersionedKeyValueStore.UpdateEntry)
                self.assertIsInstance(entry.value, StoreTestBasics.Stuff)
                self.assertEqual(entry.start_validity, 0)

                # the public get() returns the same value as the internal version entry:
                self.assertEqual(list(kvs.get(key))[0], entry.value)

    def test_TransactionalKeyValueStore(self):
        """A new transactional store is empty and hands out the transaction ids 1, 2, ... in this order."""
        tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore()
        self.assertEqual(tkvs.size(), 0)

        # the transaction id counter starts at 1; each call returns the current value and then increments it:
        self.assertEqual(tkvs.TA_id, 1)
        self.assertEqual(tkvs._get_next_TA_id(), 1)
        self.assertEqual(tkvs._get_next_TA_id(), 2)

        # handing out ids starts no transaction: the transaction dictionary TD, the trace of committed transactions
        # and the journal stay empty:
        self.assertEqual(tkvs.TD, {})
        self.assertEqual(tkvs.committed_transactions_trace, [])
        self.assertEqual(tkvs.journal.size(), 0)

    def test_begin_transaction(self):
        """`begin_transaction` adds the TA to the transaction dictionary with a read clause set, a write set and no
        commit timestamp. It also stores the position in the commit trace of the last TA that had committed when it
        began (-1 if none); this position does not change when the TA itself commits while a second TA runs.

        TA 1                                TA 2
        begin
                                            begin
        commit
        """
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

        # start a second TA, then commit TA 1 while TA 2 is still running:
        tkvs.begin_transaction()
        tkvs.commit_transaction(TA_ID)

        # TA 1's own commit does not change the trace position it stored at its begin:
        self.assertEqual(tkvs.TD[TA_ID].last_committed_TA_index_in_TA_trace, -1)

    def test_show_transaction_dictionary_prints_one_entry_per_transaction(self) -> None:
        """`show_transaction_dictionary` prints a heading and then the transaction dictionary: one entry per TA,
        sorted by transaction id, with its write set and its commit timestamp.

        TA 1                                TA 2
        begin
                                            begin
                                            insert B
                                            commit
        """
        tkvs: TransactionalKeyValueStore = TransactionalKeyValueStore()
        TA_1: int = tkvs.begin_transaction()
        TA_2: int = tkvs.begin_transaction()

        # TA 2 inserts B and commits, while TA 1 is still running:
        tkvs.update_object("B", StoreTestBasics.Stuff(1, 0), TA_2)
        tkvs.commit_transaction(TA_2)

        # capture what the method prints:
        output: io.StringIO = io.StringIO()
        with contextlib.redirect_stdout(output):
            tkvs.show_transaction_dictionary()
        printed: str = output.getvalue()

        # the heading comes first, then one entry per TA, sorted by transaction id:
        self.assertTrue(printed.startswith("Transaction dictionary:\n"))
        self.assertEqual(
            re.findall(r"(\d+): TDEntry\(", printed), [str(TA_1), str(TA_2)]
        )

        # TA 1 wrote nothing and has no commit timestamp yet; TA 2 wrote B and got the commit timestamp 3 from the
        # counter that also hands out the transaction ids:
        self.assertIn("write_set=set()", printed)
        self.assertIn("committed_timestamp=None", printed)
        self.assertIn("write_set={'B'}", printed)
        self.assertIn("committed_timestamp=3", printed)

    def test_journaling(self):
        """The journal holds one list of entries per TA: `Begin` at the start, then `Update` and `Delete` for its
        writes, and `Commit` with the commit timestamp or `Abort` at the end.

        TA 1                                TA 2
        begin
                                            begin
        commit (timestamp 3)
                                            update "a" to "b"
                                            update "b" to "c"
                                            delete "b"
                                            abort
        """

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
        # check commit; TA ids and commit timestamps share one counter, so after the two begins (ids 1 and 2)
        # the commit of TA 1 gets timestamp 3:
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
        """A new indexed store has no indexes; `create_index` adds an index to both catalogues, `drop_index` removes
        it from both.
        """
        # a new store has no indexes: both index catalogues, by name and by (attribute, operator), are empty:
        itkvs: IndexedTransactionalKeyValueStore = IndexedTransactionalKeyValueStore()
        self.assertEqual(itkvs.indexes_by_name, {})
        self.assertEqual(itkvs.indexes_by_properties, {})

        # create an index for equality predicates on attribute "a"; it is listed in both catalogues:
        itkvs.create_index("a_idx", "a", "=")
        self.assertEqual(list(itkvs.indexes_by_name), ["a_idx"])
        self.assertEqual(
            itkvs.indexes_by_properties, {IndexProperties("a", "="): "a_idx"}
        )

        # dropping it removes it from both catalogues again:
        itkvs.drop_index("a_idx")
        self.assertEqual(itkvs.indexes_by_name, {})
        self.assertEqual(itkvs.indexes_by_properties, {})


class OperationsWithoutTransactionTest(AbstractUnitTest):
    """put, bulkload, get and delete without a transaction id, and read_objects, update_object and delete_object with
    the transaction id None, in the transactional stores: without autocommit, put, bulkload and get load the initial
    state before the first transaction and are refused afterwards, while delete and the three calls with None are
    always refused; with autocommit each one runs as a transaction of its own.
    """

    # the store classes the tests run on (the indexed store must behave like its base class here):
    STORE_CLASSES: list[type[TransactionalKeyValueStore]] = [
        TransactionalKeyValueStore,
        IndexedTransactionalKeyValueStore,
    ]

    @staticmethod
    def _open_transactions(store: TransactionalKeyValueStore) -> set[int]:
        """Returns the ids of the transactions of <store> that have begun and have neither committed nor aborted.

        @param store: the store to inspect
        @return: the ids of the open transactions
        """
        return {
            TA_id
            for TA_id, entry in store.TD.items()
            if entry.committed_timestamp is None
        }

    @staticmethod
    def _read_all_in_new_transaction(
        store: TransactionalKeyValueStore,
    ) -> dict[str, object]:
        """Reads all objects in a new transaction of <store>, commits it and returns what it saw.

        @param store: the store to read
        @return: a dictionary from the object id to the object visible to the new transaction
        """
        TA_id: int = store.begin_transaction()
        visible: dict[str, object] = dict(store.read_objects(TA_id))
        store.commit_transaction(TA_id)
        return visible

    @staticmethod
    def _create_index_on_a(
        store: TransactionalKeyValueStore,
    ) -> KeyValueStore[object, str] | None:
        """Creates an equality index on attribute a if <store> is an indexed store.

        @param store: the store to create the index in
        @return: the new index; None if <store> cannot have indexes
        """
        if not isinstance(store, IndexedTransactionalKeyValueStore):
            return None
        store.create_index("a_idx", "a", "=")
        return store.indexes_by_name["a_idx"].index

    @staticmethod
    def _objects_then(error: BaseException) -> Iterator[tuple[str, object]]:
        """Yields object "1" and then raises <error>, like an input that fails while it is read.

        @param error: the exception to raise after the first object
        @return: an iterator over the (object id, object) pairs read before the error
        """
        yield "1", AbstractUnitTest.Stuff(1, 1)
        raise error

    def test_load_phase_stores_the_initial_state(self):
        """Without autocommit, put and bulkload before the first transaction store committed versions with start
        timestamp 0 and use up no transaction id; get returns them, and the first transaction gets id 1 and sees them.
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                store: TransactionalKeyValueStore = store_class()

                # load three objects with put and bulkload; no transaction id is used up:
                store.put("1", self.Stuff(1, 1))
                store.bulkload(iter([("2", self.Stuff(2, 2)), ("3", self.Stuff(3, 3))]))
                self.assertEqual(store.TA_id, 1)

                # each object has a single committed version with start timestamp 0, and get returns it:
                object_id: str
                for object_id in ["1", "2", "3"]:
                    self.assertEqual(
                        [
                            version.start_validity
                            for version in store.key_value_store[object_id].committed
                        ],
                        [0],
                    )
                self.assertEqual(list(store.get("2")), [self.Stuff(2, 2)])

                # the first transaction gets id 1 and sees all three objects:
                T1: int = store.begin_transaction()
                self.assertEqual(T1, 1)
                self.assertEqual(
                    dict(store.read_objects(T1)),
                    {
                        "1": self.Stuff(1, 1),
                        "2": self.Stuff(2, 2),
                        "3": self.Stuff(3, 3),
                    },
                )

    def test_load_phase_get_reads_at_the_call(self):
        """Without autocommit, get before the first transaction reads at the call, not when the returned iterator is
        advanced: it raises KeyError at the call for a missing object, and an iterator kept from the load phase still
        returns the loaded object after a transaction deleted it.

        load phase                  T1
        put "2" as (2, 2)
        get "missing" -> KeyError
        kept = get "2"
                                    begin
                                    delete "2"
                                    commit
        list(kept) -> the loaded "2"
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                store: TransactionalKeyValueStore = store_class()
                store.put("2", self.Stuff(2, 2))

                # get of a missing object raises KeyError at the call, not only when the iterator is advanced:
                with self.assertRaisesRegex(KeyError, "not found"):
                    store.get("missing")

                # keep an iterator over "2" from the load phase:
                kept: Iterator[object] = store.get("2")

                # T1 deletes "2" and commits; a new transaction no longer sees "2":
                T1: int = store.begin_transaction()
                store.delete_object("2", T1)
                store.commit_transaction(T1)
                self.assertEqual(self._read_all_in_new_transaction(store), {})

                # the kept iterator still returns the loaded object:
                self.assertEqual(list(kept), [self.Stuff(2, 2)])

    def test_without_autocommit_operations_are_refused_once_a_transaction_has_begun(
        self,
    ):
        """Without autocommit, put, bulkload, get and delete, and read_objects, update_object and delete_object with
        the transaction id None, raise RuntimeError at the call once a transaction has begun, whether it is still
        open, committed or aborted; the refused calls begin no transaction and change nothing, and an open
        transaction still commits.

        T1                          without transaction id
                                    put "1" as (1, 1)
        begin
        insert "2" as (2, 2)
        commit, abort or stay open
                                    put "3" -> RuntimeError
                                    bulkload "4" -> RuntimeError
                                    get "1" -> RuntimeError
                                    delete "1" -> RuntimeError
                                    read_objects all -> RuntimeError
                                    update_object "1" to (9, 9) -> RuntimeError
                                    delete_object "1" -> RuntimeError
        commit (if still open)
        """
        store_class: type[TransactionalKeyValueStore]
        situation: str
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            for situation in ["open", "committed", "aborted"]:
                with self.subTest(store_class=store_class.__name__, T1=situation):
                    store: TransactionalKeyValueStore = store_class()
                    store.put("1", self.Stuff(1, 1))

                    # T1 inserts "2" and then stays open, commits or aborts:
                    T1: int = store.begin_transaction()
                    store.update_object("2", self.Stuff(2, 2), T1)
                    if situation == "committed":
                        store.commit_transaction(T1)
                    elif situation == "aborted":
                        store.abort_transaction(T1)
                    counter: int = store.TA_id

                    # each operation without a transaction id is refused at the call; put, bulkload and get name
                    # the begun transaction as the reason:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "^put without a transaction id needs autocommit=True once a transaction has begun$",
                    ):
                        store.put("3", self.Stuff(3, 3))
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "^bulkload without a transaction id needs autocommit=True once a transaction has begun$",
                    ):
                        store.bulkload(iter([("4", self.Stuff(4, 4))]))
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "^get without a transaction id needs autocommit=True once a transaction has begun$",
                    ):
                        store.get("1")
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "^delete without a transaction id needs autocommit=True$",
                    ):
                        store.delete("1")

                    # so is each transactional call with the transaction id None:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "^read_objects without a transaction id needs autocommit=True$",
                    ):
                        store.read_objects(None)
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "^update_object without a transaction id needs autocommit=True$",
                    ):
                        store.update_object("1", self.Stuff(9, 9), None)
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "^delete_object without a transaction id needs autocommit=True$",
                    ):
                        store.delete_object("1", None)

                    # the refused calls began no transaction and left "1" with its single version:
                    self.assertEqual(store.TA_id, counter)
                    self.assertEqual(
                        self._open_transactions(store),
                        {T1} if situation == "open" else set(),
                    )
                    self.assertEqual(len(store.key_value_store["1"].committed), 1)

                    # an open T1 still commits; a new transaction sees "1", and "2" unless T1 aborted:
                    if situation == "open":
                        store.commit_transaction(T1)
                    expected: dict[str, object] = {"1": self.Stuff(1, 1)}
                    if situation != "aborted":
                        expected["2"] = self.Stuff(2, 2)
                    self.assertEqual(self._read_all_in_new_transaction(store), expected)

    def test_without_autocommit_delete_and_calls_with_id_none_are_refused_in_the_load_phase(
        self,
    ):
        """Without autocommit, delete, and read_objects, update_object and delete_object with the transaction id
        None, raise RuntimeError also before the first transaction begins; the object keeps its single version and
        gets no work-in-progress version, and no transaction has begun.
        """
        # each refused call, by the name of its operation:
        refused_calls: dict[str, Callable[[TransactionalKeyValueStore], object]] = {
            "delete": lambda store: store.delete("1"),
            "read_objects": lambda store: store.read_objects(None),
            "update_object": lambda store: store.update_object(
                "1", self.Stuff(9, 9), None
            ),
            "delete_object": lambda store: store.delete_object("1", None),
        }
        store_class: type[TransactionalKeyValueStore]
        operation: str
        refused_call: Callable[[TransactionalKeyValueStore], object]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            for operation, refused_call in refused_calls.items():
                with self.subTest(
                    store_class=store_class.__name__, operation=operation
                ):
                    store: TransactionalKeyValueStore = store_class()
                    store.put("1", self.Stuff(1, 1))

                    # the call is refused with a message that names the operation:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        f"^{operation} without a transaction id needs autocommit=True$",
                    ):
                        refused_call(store)

                    # "1" keeps its single version with start timestamp 0 and has no work-in-progress version, no
                    # transaction has begun, and get still returns the object:
                    versions: list[VersionedKeyValueStore.VersionEntry] = (
                        store.key_value_store["1"].committed
                    )
                    self.assertEqual(len(versions), 1)
                    self.assertIsInstance(
                        versions[0], VersionedKeyValueStore.UpdateEntry
                    )
                    self.assertEqual(versions[0].start_validity, 0)
                    self.assertIsNone(store.key_value_store["1"].wip)
                    self.assertEqual(store.TA_id, 1)
                    self.assertEqual(list(store.get("1")), [self.Stuff(1, 1)])

    def test_transactional_calls_have_no_default_transaction_id(self):
        """read_objects, update_object and delete_object have no default for the transaction id: also with
        autocommit, a call that leaves it out raises TypeError and begins no transaction, so a forgotten id never
        runs as a transaction of its own.
        """
        # each call that leaves out the transaction id, by the name of its operation:
        calls_without_id: dict[str, Callable[[TransactionalKeyValueStore], object]] = {
            "read_objects": lambda store: store.read_objects(),
            "update_object": lambda store: store.update_object("1", self.Stuff(9, 9)),
            "delete_object": lambda store: store.delete_object("1"),
        }
        store_class: type[TransactionalKeyValueStore]
        operation: str
        call_without_id: Callable[[TransactionalKeyValueStore], object]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            for operation, call_without_id in calls_without_id.items():
                with self.subTest(
                    store_class=store_class.__name__, operation=operation
                ):
                    store: TransactionalKeyValueStore = store_class(autocommit=True)
                    store.put("1", self.Stuff(1, 1))
                    counter: int = store.TA_id

                    # the call lacks the transaction id as a required argument:
                    with self.assertRaisesRegex(
                        TypeError,
                        f"{operation}\\(\\) missing 1 required positional argument: 'TA_id'$",
                    ):
                        call_without_id(store)

                    # no transaction has begun, and "1" keeps its single version:
                    self.assertEqual(store.TA_id, counter)
                    self.assertEqual(self._open_transactions(store), set())
                    self.assertEqual(len(store.key_value_store["1"].committed), 1)

    def test_autocommit_put_inserts_in_a_transaction_of_its_own(self):
        """With autocommit, put inserts the object in a transaction of its own, also before any other transaction, so
        its version gets a commit timestamp; a put of a visible object raises KeyError, adds no version and leaves no
        transaction open: its transaction is aborted and uses up one value of the counter (its begin).
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                store: TransactionalKeyValueStore = store_class(autocommit=True)

                # the put runs as transaction 1, which commits at timestamp 2:
                store.put("1", self.Stuff(1, 1))
                self.assertEqual(
                    [
                        version.start_validity
                        for version in store.key_value_store["1"].committed
                    ],
                    [2],
                )
                self.assertEqual(store.TA_id, 3)
                self.assertEqual(store.committed_transactions_trace, [1])
                self.assertEqual(self._open_transactions(store), set())

                # a later transaction sees "1":
                self.assertEqual(
                    self._read_all_in_new_transaction(store), {"1": self.Stuff(1, 1)}
                )

                # a second put of "1" raises KeyError, adds no version and leaves no transaction open:
                counter: int = store.TA_id
                trace: list[int] = list(store.committed_transactions_trace)
                with self.assertRaisesRegex(KeyError, "already exists"):
                    store.put("1", self.Stuff(9, 9))
                self.assertEqual(len(store.key_value_store["1"].committed), 1)
                self.assertEqual(self._open_transactions(store), set())

                # the failed put used up one counter value (its begin) and was aborted, not committed; a new
                # transaction still sees the first version of "1":
                self.assertEqual(store.TA_id, counter + 1)
                self.assertEqual(store.committed_transactions_trace, trace)
                self.assertEqual(
                    self._read_all_in_new_transaction(store), {"1": self.Stuff(1, 1)}
                )

    def test_autocommit_delete_after_put_and_update_keeps_the_versions_in_order(self):
        """With autocommit, put, an update in an explicit transaction and delete write versions with increasing
        timestamps, so reads afterwards work: the deleted object is not visible, get and delete raise KeyError (the
        failed delete aborts its transaction, which uses up one value of the counter), and put inserts it again.

        T1                          autocommit
                                    put "1" as (1, 1), commit
        begin
        update "1" to (2, 2)
        commit
                                    delete "1", commit
                                    get "1" -> KeyError
                                    delete "1" -> KeyError
                                    put "1" as (3, 3), commit
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                store: TransactionalKeyValueStore = store_class(autocommit=True)

                # put "1", update it in T1, and delete it:
                store.put("1", self.Stuff(1, 1))
                T1: int = store.begin_transaction()
                store.update_object("1", self.Stuff(2, 2), T1)
                store.commit_transaction(T1)
                store.delete("1")

                # a new transaction reads without an error and sees nothing:
                self.assertEqual(self._read_all_in_new_transaction(store), {})

                # get raises KeyError at the call and leaves no transaction open:
                with self.assertRaisesRegex(KeyError, "not found"):
                    store.get("1")
                self.assertEqual(self._open_transactions(store), set())

                # a second delete raises KeyError at the call and leaves no transaction open:
                counter: int = store.TA_id
                trace: list[int] = list(store.committed_transactions_trace)
                with self.assertRaisesRegex(KeyError, "not found"):
                    store.delete("1")
                self.assertEqual(self._open_transactions(store), set())

                # the failed delete used up one counter value (its begin) and was aborted, not committed:
                self.assertEqual(store.TA_id, counter + 1)
                self.assertEqual(store.committed_transactions_trace, trace)

                # put inserts "1" again:
                store.put("1", self.Stuff(3, 3))
                self.assertEqual(list(store.get("1")), [self.Stuff(3, 3)])
                self.assertEqual(
                    self._read_all_in_new_transaction(store), {"1": self.Stuff(3, 3)}
                )

                # "1" has four committed versions (put, update, delete, put) with strictly increasing start
                # timestamps:
                versions: list[VersionedKeyValueStore.VersionEntry] = (
                    store.key_value_store["1"].committed
                )
                self.assertEqual(
                    [type(version) for version in versions],
                    [
                        VersionedKeyValueStore.UpdateEntry,
                        VersionedKeyValueStore.UpdateEntry,
                        VersionedKeyValueStore.DeleteEntry,
                        VersionedKeyValueStore.UpdateEntry,
                    ],
                )
                starts: list[int] = [version.start_validity for version in versions]
                self.assertEqual(starts, sorted(set(starts)))

    def test_autocommit_get_returns_the_newest_committed_version(self):
        """With autocommit, get reads in a transaction of its own and returns the newest committed version of an
        object, not the work-in-progress version of an open transaction; it raises KeyError at the call for a missing
        object.

        T1                          autocommit
                                    put "1" as (1, 1), commit
        begin
        update "1" to (2, 2)
                                    get "1" -> (1, 1), commit
                                    get "2" -> KeyError
        commit
                                    get "1" -> (2, 2), commit
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                store: TransactionalKeyValueStore = store_class(autocommit=True)
                store.put("1", self.Stuff(1, 1))

                # while T1 holds a work-in-progress version of "1", get returns the committed one; its own
                # transaction uses up two values of the counter, one at the begin and one at the commit:
                T1: int = store.begin_transaction()
                store.update_object("1", self.Stuff(2, 2), T1)
                counter: int = store.TA_id
                self.assertEqual(list(store.get("1")), [self.Stuff(1, 1)])
                self.assertEqual(store.TA_id, counter + 2)

                # get of a missing object raises KeyError; only T1 is open:
                with self.assertRaisesRegex(KeyError, "not found"):
                    store.get("2")
                self.assertEqual(self._open_transactions(store), {T1})

                # after the commit of T1, get returns its version:
                store.commit_transaction(T1)
                self.assertEqual(list(store.get("1")), [self.Stuff(2, 2)])
                self.assertEqual(self._open_transactions(store), set())

    def test_autocommit_bulkload_inserts_all_objects_or_none(self):
        """With autocommit, bulkload inserts all objects in one transaction; if an object is visible already or
        occurs twice in the input, it raises KeyError and inserts none of its objects; a later put of one of them that
        is not visible succeeds.

        On the indexed store, with an equality index on a, the index lists the objects of the successful bulkload and
        none of the failed ones.
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                store: TransactionalKeyValueStore = store_class(autocommit=True)
                index: KeyValueStore[object, str] | None = self._create_index_on_a(
                    store
                )
                loaded: dict[str, object] = {
                    "1": self.Stuff(1, 1),
                    "2": self.Stuff(2, 2),
                }

                # both objects are committed by transaction 1 at timestamp 2:
                store.bulkload(iter(loaded.items()))
                self.assertEqual(
                    store.key_value_store["1"].committed[0].start_validity, 2
                )
                self.assertEqual(
                    store.key_value_store["2"].committed[0].start_validity, 2
                )
                self.assertEqual(store.committed_transactions_trace, [1])

                # the index lists both objects:
                if index is not None:
                    self.assertEqual(list(index.get(1)), ["1"])
                    self.assertEqual(list(index.get(2)), ["2"])

                # a bulkload with the visible "2" raises KeyError; "3", inserted before, does not become visible and
                # is not indexed:
                with self.assertRaisesRegex(KeyError, "already exists"):
                    store.bulkload(
                        iter([("3", self.Stuff(3, 3)), ("2", self.Stuff(9, 9))])
                    )
                self.assertEqual(self._open_transactions(store), set())
                self.assertEqual(self._read_all_in_new_transaction(store), loaded)
                if index is not None:
                    with self.assertRaises(KeyError):
                        list(index.get(3))

                # a bulkload that contains "4" twice raises KeyError and inserts and indexes nothing:
                with self.assertRaisesRegex(KeyError, "already exists"):
                    store.bulkload(
                        iter([("4", self.Stuff(4, 4)), ("4", self.Stuff(5, 5))])
                    )
                self.assertEqual(self._open_transactions(store), set())
                self.assertEqual(self._read_all_in_new_transaction(store), loaded)
                if index is not None:
                    with self.assertRaises(KeyError):
                        list(index.get(4))

                # a put of "3", which the first failed bulkload had inserted, succeeds and indexes "3":
                store.put("3", self.Stuff(3, 3))
                self.assertEqual(
                    self._read_all_in_new_transaction(store),
                    loaded | {"3": self.Stuff(3, 3)},
                )
                if index is not None:
                    self.assertEqual(list(index.get(3)), ["3"])

    def test_autocommit_empty_bulkload_runs_an_empty_transaction(self):
        """With autocommit, a bulkload of an empty input still begins and commits a transaction of its own; it makes
        nothing visible and leaves no transaction open.
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                store: TransactionalKeyValueStore = store_class(autocommit=True)

                # the empty bulkload runs as transaction 1, which commits; begin and commit use up two values of the
                # counter:
                counter: int = store.TA_id
                store.bulkload(iter([]))
                self.assertEqual(store.TA_id, counter + 2)
                self.assertEqual(store.committed_transactions_trace, [1])

                # no transaction is open, and a new transaction sees nothing:
                self.assertEqual(self._open_transactions(store), set())
                self.assertEqual(self._read_all_in_new_transaction(store), {})

    def test_autocommit_bulkload_whose_input_raises_inserts_nothing(self):
        """With autocommit, if reading the input of a bulkload raises after the first object, also with
        KeyboardInterrupt (Ctrl-C), bulkload aborts its transaction and passes the exception on; the first object is
        not visible, and no transaction stays open.

        On the indexed store, with an equality index on a, the index does not list the first object either.
        """
        store_class: type[TransactionalKeyValueStore]
        error_class: type[BaseException]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            for error_class in [ValueError, KeyboardInterrupt]:
                with self.subTest(
                    store_class=store_class.__name__, error=error_class.__name__
                ):
                    store: TransactionalKeyValueStore = store_class(autocommit=True)
                    index: KeyValueStore[object, str] | None = self._create_index_on_a(
                        store
                    )

                    # the input yields "1" and then raises; bulkload passes the exception on:
                    with self.assertRaisesRegex(error_class, "input broken"):
                        store.bulkload(self._objects_then(error_class("input broken")))

                    # no transaction is open, "1" is not visible, and the index does not list it:
                    self.assertEqual(self._open_transactions(store), set())
                    self.assertEqual(self._read_all_in_new_transaction(store), {})
                    if index is not None:
                        with self.assertRaises(KeyError):
                            list(index.get(1))

    def test_autocommit_read_objects_returns_the_committed_objects_in_a_transaction_of_its_own(
        self,
    ):
        """With autocommit, read_objects with the transaction id None reads in a transaction of its own, also before
        any other transaction: it returns the list of committed objects that match the where clause, without the
        work-in-progress versions of an open transaction; its transaction commits and uses up two values of the
        counter.

        T1                          autocommit
                                    read all -> nothing, commit
                                    bulkload "1" as (1, 1), "5" as (5, 5), commit
        begin
        update "1" to (5, 1)
        insert "3" as (5, 3)
                                    read all -> "1" as (1, 1), "5", commit
                                    read a == 5 -> "5", commit
        commit
                                    read a == 5 -> "1" as (5, 1), "5", "3", commit
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                store: TransactionalKeyValueStore = store_class(autocommit=True)
                where_a_5: WHERE_Clause = WHERE_Clause("a", "==", 5)

                # on the empty store, the read runs as transaction 1, which commits at timestamp 2:
                self.assertEqual(store.read_objects(None), [])
                self.assertEqual(store.TA_id, 3)
                self.assertEqual(store.committed_transactions_trace, [1])

                # T1 writes work-in-progress versions of the committed "1" and the new "3", both with a == 5:
                store.bulkload(iter([("1", self.Stuff(1, 1)), ("5", self.Stuff(5, 5))]))
                T1: int = store.begin_transaction()
                store.update_object("1", self.Stuff(5, 1), T1)
                store.update_object("3", self.Stuff(5, 3), T1)

                # a read of all objects returns the committed versions only; its transaction commits with the next
                # two counter values, and only T1 stays open:
                counter: int = store.TA_id
                trace: list[int] = list(store.committed_transactions_trace)
                self.assertEqual(
                    store.read_objects(None),
                    [("1", self.Stuff(1, 1)), ("5", self.Stuff(5, 5))],
                )
                self.assertEqual(store.TA_id, counter + 2)
                self.assertEqual(store.committed_transactions_trace, trace + [counter])
                self.assertEqual(self._open_transactions(store), {T1})

                # a read with a where clause returns only the committed object that matches it:
                self.assertEqual(
                    store.read_objects(None, where_a_5), [("5", self.Stuff(5, 5))]
                )

                # after the commit of T1, the read returns its versions too:
                store.commit_transaction(T1)
                self.assertEqual(
                    store.read_objects(None, where_a_5),
                    [
                        ("1", self.Stuff(5, 1)),
                        ("5", self.Stuff(5, 5)),
                        ("3", self.Stuff(5, 3)),
                    ],
                )
                self.assertEqual(self._open_transactions(store), set())

    def test_autocommit_update_object_inserts_or_writes_a_new_version_in_a_transaction_of_its_own(
        self,
    ):
        """With autocommit, update_object with the transaction id None inserts a missing object and writes a new
        version of an existing or a deleted one, each time in a transaction of its own that commits: every call uses
        up two values of the counter and adds a committed version with its commit timestamp, so the versions stay in
        order.
        """

        def update_in_own_transaction(
            store: TransactionalKeyValueStore, _object: object
        ) -> None:
            """Writes "1" as <_object> with update_object and the transaction id None, and checks that its
            transaction committed the new version with the next two counter values.

            @param store: the store to write to
            @param _object: the new version of "1"
            """
            # the write runs as transaction <counter>, which commits at timestamp <counter + 1>:
            counter: int = store.TA_id
            trace: list[int] = list(store.committed_transactions_trace)
            store.update_object("1", _object, None)
            self.assertEqual(store.TA_id, counter + 2)
            self.assertEqual(store.committed_transactions_trace, trace + [counter])
            self.assertEqual(
                store.key_value_store["1"].committed[-1].start_validity, counter + 1
            )

            # no transaction is open, and a new transaction sees the new version:
            self.assertEqual(self._open_transactions(store), set())
            self.assertEqual(self._read_all_in_new_transaction(store), {"1": _object})

        store_class: type[TransactionalKeyValueStore]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                store: TransactionalKeyValueStore = store_class(autocommit=True)

                # update_object inserts the missing "1", then writes a new version of it:
                update_in_own_transaction(store, self.Stuff(1, 1))
                update_in_own_transaction(store, self.Stuff(2, 2))

                # after a delete, update_object writes a new version of the deleted "1":
                store.delete("1")
                update_in_own_transaction(store, self.Stuff(3, 3))

                # "1" has four committed versions (two updates, the delete, an update) with strictly increasing start
                # timestamps:
                versions: list[VersionedKeyValueStore.VersionEntry] = (
                    store.key_value_store["1"].committed
                )
                self.assertEqual(
                    [type(version) for version in versions],
                    [
                        VersionedKeyValueStore.UpdateEntry,
                        VersionedKeyValueStore.UpdateEntry,
                        VersionedKeyValueStore.DeleteEntry,
                        VersionedKeyValueStore.UpdateEntry,
                    ],
                )
                starts: list[int] = [version.start_validity for version in versions]
                self.assertEqual(starts, sorted(set(starts)))

    def test_autocommit_delete_object_deletes_in_a_transaction_of_its_own(self):
        """With autocommit, delete_object with the transaction id None deletes an object in a transaction of its own
        that commits; on an object deleted already it commits another delete marker, where delete raises KeyError; for
        an object id that was never stored it raises KeyError and aborts its transaction, which uses up one value of
        the counter (its begin).
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                store: TransactionalKeyValueStore = store_class(autocommit=True)
                store.put("1", self.Stuff(1, 1))

                # delete_object deletes "1" in a transaction that commits with the next two counter values:
                counter: int = store.TA_id
                trace: list[int] = list(store.committed_transactions_trace)
                store.delete_object("1", None)
                self.assertEqual(store.TA_id, counter + 2)
                self.assertEqual(store.committed_transactions_trace, trace + [counter])
                self.assertEqual(self._read_all_in_new_transaction(store), {})

                # a second delete_object of the deleted "1" commits too, and "1" stays deleted:
                counter = store.TA_id
                trace = list(store.committed_transactions_trace)
                store.delete_object("1", None)
                self.assertEqual(store.committed_transactions_trace, trace + [counter])
                self.assertEqual(self._read_all_in_new_transaction(store), {})

                # delete of the deleted "1" raises KeyError instead:
                with self.assertRaisesRegex(KeyError, "not found"):
                    store.delete("1")

                # "1" has the version of the put and two delete markers, with strictly increasing start timestamps:
                versions: list[VersionedKeyValueStore.VersionEntry] = (
                    store.key_value_store["1"].committed
                )
                self.assertEqual(
                    [type(version) for version in versions],
                    [
                        VersionedKeyValueStore.UpdateEntry,
                        VersionedKeyValueStore.DeleteEntry,
                        VersionedKeyValueStore.DeleteEntry,
                    ],
                )
                starts: list[int] = [version.start_validity for version in versions]
                self.assertEqual(starts, sorted(set(starts)))

                # delete_object of an object id that was never stored raises KeyError (which names only the object
                # id), adds no entry and leaves no transaction open:
                counter = store.TA_id
                trace = list(store.committed_transactions_trace)
                with self.assertRaisesRegex(KeyError, "missing"):
                    store.delete_object("missing", None)
                self.assertNotIn("missing", store.key_value_store)
                self.assertEqual(self._open_transactions(store), set())

                # its transaction used up one counter value (its begin) and was aborted, not committed:
                self.assertEqual(store.TA_id, counter + 1)
                self.assertEqual(store.committed_transactions_trace, trace)

    def test_autocommit_write_to_an_object_an_open_transaction_writes_is_aborted(self):
        """With autocommit, a put, delete or bulkload, or an update_object or delete_object with the transaction id
        None, that writes an object an open transaction is writing raises TransactionAbortedException and makes
        nothing visible; the open transaction is not affected and commits.

        T1                          autocommit
                                    put "1" as (1, 1), commit
        begin
        update "1" to (1, 2)
        insert "2" as (2, 2)
                                    put "2" as (8, 8) -> aborted
                                    delete "1" -> aborted
                                    bulkload "3", "2" -> aborted
                                    update_object "2" to (7, 7) -> aborted
                                    delete_object "1" -> aborted
        commit

        On the indexed store, with an equality index on a, the aborted bulkload leaves "3" out of the index, and the
        aborted update_object leaves the value 7 out of it.
        """
        store_class: type[TransactionalKeyValueStore]
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            with self.subTest(store_class=store_class.__name__):
                store: TransactionalKeyValueStore = store_class(autocommit=True)
                store.put("1", self.Stuff(1, 1))
                index: KeyValueStore[object, str] | None = self._create_index_on_a(
                    store
                )

                # T1 updates the committed "1" and inserts the new "2":
                T1: int = store.begin_transaction()
                store.update_object("1", self.Stuff(1, 2), T1)
                store.update_object("2", self.Stuff(2, 2), T1)

                # the put of "2" is aborted, as T1 is inserting "2"; T1 stays open:
                with self.assertRaises(TransactionAbortedException):
                    store.put("2", self.Stuff(8, 8))
                self.assertEqual(self._open_transactions(store), {T1})

                # the delete of "1" is aborted; T1 stays open:
                with self.assertRaises(TransactionAbortedException):
                    store.delete("1")
                self.assertEqual(self._open_transactions(store), {T1})

                # the bulkload inserts "3" and is aborted at "2"; T1 stays open, and the index has no entry for "3":
                with self.assertRaises(TransactionAbortedException):
                    store.bulkload(
                        iter([("3", self.Stuff(3, 3)), ("2", self.Stuff(9, 9))])
                    )
                self.assertEqual(self._open_transactions(store), {T1})
                if index is not None:
                    with self.assertRaises(KeyError):
                        list(index.get(3))

                # update_object of "2" is aborted; T1 stays open, and the index has no entry for the value 7:
                with self.assertRaises(TransactionAbortedException):
                    store.update_object("2", self.Stuff(7, 7), None)
                self.assertEqual(self._open_transactions(store), {T1})
                if index is not None:
                    with self.assertRaises(KeyError):
                        list(index.get(7))

                # delete_object of "1" is aborted; T1 stays open:
                with self.assertRaises(TransactionAbortedException):
                    store.delete_object("1", None)
                self.assertEqual(self._open_transactions(store), {T1})

                # T1 commits both of its writes; "3" is not visible:
                store.commit_transaction(T1)
                self.assertEqual(
                    self._read_all_in_new_transaction(store),
                    {"1": self.Stuff(1, 2), "2": self.Stuff(2, 2)},
                )

    def test_autocommit_write_fails_the_validation_of_an_open_transaction_that_read_it(
        self,
    ):
        """Under serializable, an open transaction that read a == 5 and wrote an object fails validation at its
        commit if a put with autocommit inserted an object with a == 5 (phantom), an update_object with the
        transaction id None changed the object it read, or a delete with autocommit, or a delete_object with the
        transaction id None, removed that object; with validation method 1 and method 2.

        T1                          autocommit
                                    bulkload "1" as (1, 1), "5" as (5, 5), commit
        begin
        read a == 5 -> sees "5"
                                    put "7" as (5, 7), commit
                                    (or: update_object "5" to (5, 6), commit)
                                    (or: delete "5", commit)
                                    (or: delete_object "5", commit)
        write "9"
        commit -> aborted
        """
        store_class: type[TransactionalKeyValueStore]
        use_brute_force_validation: bool
        write: str
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            for use_brute_force_validation in [False, True]:
                for write in ["put", "update_object", "delete", "delete_object"]:
                    with self.subTest(
                        store_class=store_class.__name__,
                        use_brute_force_validation=use_brute_force_validation,
                        write=write,
                    ):
                        store: TransactionalKeyValueStore = store_class(
                            use_brute_force_validation=use_brute_force_validation,
                            autocommit=True,
                        )
                        store.bulkload(
                            iter([("1", self.Stuff(1, 1)), ("5", self.Stuff(5, 5))])
                        )

                        # T1 reads a == 5:
                        T1: int = store.begin_transaction()
                        self.assertEqual(
                            store.read_objects(T1, WHERE_Clause("a", "==", 5)),
                            [("5", self.Stuff(5, 5))],
                        )

                        # a write with autocommit changes the result of that read and commits:
                        expected: dict[str, object] = {
                            "1": self.Stuff(1, 1),
                            "5": self.Stuff(5, 5),
                        }
                        if write == "put":
                            store.put("7", self.Stuff(5, 7))
                            expected["7"] = self.Stuff(5, 7)
                        elif write == "update_object":
                            store.update_object("5", self.Stuff(5, 6), None)
                            expected["5"] = self.Stuff(5, 6)
                        elif write == "delete":
                            store.delete("5")
                            del expected["5"]
                        else:
                            store.delete_object("5", None)
                            del expected["5"]

                        # T1 writes "9" and fails validation at its commit:
                        store.update_object("9", self.Stuff(9, 9), T1)
                        with self.assertRaises(TransactionAbortedException):
                            store.commit_transaction(T1)
                        self.assertNotIn(T1, store.TD)

                        # the write with autocommit stays, the write of T1 is not visible:
                        self.assertEqual(
                            self._read_all_in_new_transaction(store), expected
                        )

    def test_autocommit_write_passes_the_validation_of_an_open_transaction_that_did_not_read_it(
        self,
    ):
        """Under serializable, an open transaction that read a == 5 and wrote an object passes validation at its
        commit if a put with autocommit inserted an object with a != 5, an update_object with the transaction id None
        changed one with a != 5 to another a != 5, or a delete with autocommit, or a delete_object with the
        transaction id None, removed one with a != 5 in the meantime; with validation method 1 and method 2.

        T1                          autocommit
                                    bulkload "1" as (1, 1), "5" as (5, 5), commit
        begin
        read a == 5 -> sees "5"
                                    put "7" as (2, 7), commit
                                    (or: update_object "1" to (2, 1), commit)
                                    (or: delete "1", commit)
                                    (or: delete_object "1", commit)
        write "9"
        commit
        """
        store_class: type[TransactionalKeyValueStore]
        use_brute_force_validation: bool
        write: str
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            for use_brute_force_validation in [False, True]:
                for write in ["put", "update_object", "delete", "delete_object"]:
                    with self.subTest(
                        store_class=store_class.__name__,
                        use_brute_force_validation=use_brute_force_validation,
                        write=write,
                    ):
                        store: TransactionalKeyValueStore = store_class(
                            use_brute_force_validation=use_brute_force_validation,
                            autocommit=True,
                        )
                        store.bulkload(
                            iter([("1", self.Stuff(1, 1)), ("5", self.Stuff(5, 5))])
                        )

                        # T1 reads a == 5:
                        T1: int = store.begin_transaction()
                        self.assertEqual(
                            store.read_objects(T1, WHERE_Clause("a", "==", 5)),
                            [("5", self.Stuff(5, 5))],
                        )

                        # a write with autocommit of an object outside that read commits:
                        expected: dict[str, object] = {
                            "1": self.Stuff(1, 1),
                            "5": self.Stuff(5, 5),
                        }
                        if write == "put":
                            store.put("7", self.Stuff(2, 7))
                            expected["7"] = self.Stuff(2, 7)
                        elif write == "update_object":
                            store.update_object("1", self.Stuff(2, 1), None)
                            expected["1"] = self.Stuff(2, 1)
                        elif write == "delete":
                            store.delete("1")
                            del expected["1"]
                        else:
                            store.delete_object("1", None)
                            del expected["1"]

                        # T1 writes "9" and commits without an exception:
                        store.update_object("9", self.Stuff(9, 9), T1)
                        store.commit_transaction(T1)
                        expected["9"] = self.Stuff(9, 9)

                        # a new transaction sees the writes of both:
                        self.assertEqual(
                            self._read_all_in_new_transaction(store), expected
                        )

    def test_autocommit_write_aborts_a_later_update_under_snapshot_isolation(
        self,
    ):
        """Under snapshot isolation, an open transaction still reads the version of an object it began with after a
        delete with autocommit, or an update_object or delete_object with the transaction id None, wrote the object,
        but its own update of the object is aborted (first updater wins).

        T1                          autocommit
                                    put "1" as (1, 1), commit
        begin
                                    delete "1", commit
                                    (or: update_object "1" to (3, 3), commit)
                                    (or: delete_object "1", commit)
        read all -> sees (1, 1)
        update "1" to (2, 2) -> aborted
        """
        store_class: type[TransactionalKeyValueStore]
        write: str
        for store_class in OperationsWithoutTransactionTest.STORE_CLASSES:
            for write in ["delete", "update_object", "delete_object"]:
                with self.subTest(store_class=store_class.__name__, write=write):
                    store: TransactionalKeyValueStore = store_class(
                        isolation_level="snapshot isolation", autocommit=True
                    )
                    store.put("1", self.Stuff(1, 1))

                    # T1 begins, then "1" is written with autocommit; T1 still sees (1, 1) in its snapshot:
                    T1: int = store.begin_transaction()
                    expected: dict[str, object]
                    if write == "delete":
                        store.delete("1")
                        expected = {}
                    elif write == "update_object":
                        store.update_object("1", self.Stuff(3, 3), None)
                        expected = {"1": self.Stuff(3, 3)}
                    else:
                        store.delete_object("1", None)
                        expected = {}
                    self.assertEqual(store.read_objects(T1), [("1", self.Stuff(1, 1))])

                    # the update of "1" by T1 is aborted:
                    with self.assertRaises(TransactionAbortedException):
                        store.update_object("1", self.Stuff(2, 2), T1)
                    self.assertEqual(self._open_transactions(store), set())

                    # a new transaction sees the write with autocommit, not the update of T1:
                    self.assertEqual(self._read_all_in_new_transaction(store), expected)


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
