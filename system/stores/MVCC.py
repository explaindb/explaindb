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

"""Multi-version concurrency control transactional key-value store with journaling."""

from __future__ import annotations

import copy
import hashlib
import pprint
from abc import ABC
from dataclasses import dataclass
from typing import Dict, ItemsView, Literal, cast

from pydantic import BaseModel

from system.indexes.indexes import PythonDictionaryIndex
from system.interfaces.indexing.Index import KeyValueStore
from system.interfaces.stores import ACIDStore
from system.query_processing.predicates import Clause
from system.stores.VersionedKeyValueStore import HashableDict, VersionedKeyValueStore

# the isolation levels the store supports:
IsolationLevel = Literal["serializable", "snapshot isolation"]
ISOLATION_LEVELS: tuple[IsolationLevel, ...] = ("serializable", "snapshot isolation")


class TransactionAbortedException(Exception):
    """An exception that is raised when a transaction is aborted by the store."""


class JournalEntry(ABC, BaseModel):
    """An abstract class for journal entries."""

    # the transaction id of the transaction that created this journal entry
    # note: depending on how these journal entries are used, this might be redundant:
    TA_id: int


class Begin(JournalEntry):
    """A journal entry marking the start of a transaction."""


class Commit(JournalEntry):
    """A journal entry marking the commit of a transaction, recording its commit timestamp."""

    # the timestamp at which the transaction committed
    commit_timestamp: int


class Abort(JournalEntry):
    """A journal entry marking the abort of a transaction."""


class Update[Key, Value](JournalEntry):
    """A journal entry for an update operation."""

    # the object id of the object that was updated
    object_id: Key

    # the new value object
    nev_value: Value


class Delete[Key](JournalEntry):
    """A journal entry for a delete operation."""

    # the object id of the object that was deleted
    object_id: Key


class TransactionalKeyValueStore(VersionedKeyValueStore, ACIDStore):
    """A fully transactional versioned key-value store using multi-version concurrency control (MVCC).

    A typical key-value store is transactional only for a single key, i.e. each insert, update or delete of one
    key is atomic. This store goes further: a transaction may read and write many keys, and all its writes become
    visible together at its commit or not at all.

    The store supports two isolation levels, chosen in ``__init__``. In both, a transaction reads the snapshot of its
    begin plus its own writes (snapshot read). In both, a transaction that writes an object which another transaction
    is still writing (not yet committed) is aborted. In addition:

    - serializable (default): at the commit of a transaction that wrote something, the store checks whether a
      transaction that committed in the meantime changed something it read; if so, it is aborted. The write skew
      anomaly is detected and avoided.
    - snapshot isolation: reads are not checked. Instead, a transaction that writes an object is aborted at once if
      another transaction changed that object and committed after the writer began. Together with the rule above,
      this means: if two concurrent transactions write the same object, the one that writes second is aborted at
      once ("first updater wins"). Lost updates cannot happen, but write skew can.

    Note: a blind write (one that does not read the object first) to an object that another transaction changed and
    committed since the writer began is aborted under snapshot isolation, but can commit under serializable. The
    tutorial page "MVCC & Versioned Stores" explains write skew and shows both schedules.
    """

    @dataclass
    class TDEntry:
        """Entries used for the transaction dictionary."""

        # the recorded reads of the transaction (see collect_read_clause in read_objects; equal reads are kept once),
        # each as {"where_clause": <where clause>, "checksum": <checksum>} (the checksum is None unless the store uses
        # brute force validation):
        read_clauses: set[HashableDict[str, Clause | str | None]]

        # a set of object_ids of objects that were modified by the transaction:
        write_set: set[str]

        # the timestamp when the transaction was committed, None if the transaction is still ongoing:
        committed_timestamp: int | None

        # the index of the last committed transaction in the committed transactions trace when the transaction started:
        last_committed_TA_index_in_TA_trace: int | None

    def __init__(
        self,
        use_brute_force_validation: bool = False,
        persistence_layer: KeyValueStore = None,
        isolation_level: IsolationLevel = "serializable",
    ):
        """Initializes the store.

        Raises ValueError if the isolation level is unknown, or if snapshot isolation is combined with brute force
        validation.

        @param use_brute_force_validation: if set to True, the store will use the brute force validation algorithm in
        the validation phase; only applies to the isolation level serializable.
        @param isolation_level: "serializable" (default) validates the reads of a transaction at its commit;
        "snapshot isolation" does not validate reads; instead, it aborts a transaction as soon as it writes an object
        that another transaction changed and committed after the writer began.
        @param persistence_layer: the persistence layer to use for the store
        """

        # reject an unknown isolation level and the combination of snapshot isolation with brute force validation:
        if isolation_level not in ISOLATION_LEVELS:
            raise ValueError(
                f"unknown isolation level {isolation_level!r}, expected one of {ISOLATION_LEVELS}"
            )
        if isolation_level == "snapshot isolation" and use_brute_force_validation:
            raise ValueError(
                "snapshot isolation does not validate reads, so use_brute_force_validation=True requires "
                "isolation_level='serializable'"
            )

        # set up the versioned store, the journal (it maps a transaction id to the list of its journal entries;
        # called journal to avoid confusion with Python's logging module) and the settings:
        super().__init__(persistence_layer=persistence_layer)

        self.journal: KeyValueStore[int, JournalEntry] = PythonDictionaryIndex[
            int, JournalEntry
        ]()
        self.use_brute_force_validation: bool = use_brute_force_validation
        self.isolation_level: IsolationLevel = isolation_level

        # counter for transaction ids and commit timestamps (both are taken from it, see _get_next_TA_id):
        self.TA_id: int = 1

        # transaction dictionary mapping from TA_id to TDEntry
        self.TD: Dict[int, TransactionalKeyValueStore.TDEntry] = dict[
            int, TransactionalKeyValueStore.TDEntry
        ]()

        # a trace of the committed transactions:
        # TODO: integrated with persisted journal
        self.committed_transactions_trace: list[int] = list[int]()

    def _get_visible_object_version(
        self, object_id: str, timestamp: int, ignore_wip=False
    ) -> object | None:
        """
        Gets the version of object <object_id> visible at <timestamp>, i.e. in the snapshot of the transaction whose
        id is <timestamp> (the validation also passes a commit timestamp).

        This entails:
        - the wip entry created by the transaction <timestamp>, if there is one and wip entries are not ignored;
        - otherwise the most recent committed version with a start before <timestamp>;
        - None if that version is a delete, or if there is no committed version with a start before <timestamp> (the
          object did not exist yet in this snapshot)

        @param object_id: the object id of the object to be read
        @param timestamp: the timestamp, typically the transaction id of the transaction reading the object
        @param ignore_wip: if set to True, the wip entries are ignored, i.e. only committed versions are considered.

        @return: the version of the object visible at <timestamp>, None if it was deleted or did not exist yet in
        this snapshot
        """

        if object_id not in self.key_value_store:
            raise KeyError(f"object {object_id} not found in the store")

        # check whether transaction <timestamp> has a wip entry for this object:
        if (
            not ignore_wip and self.key_value_store[object_id].wip is not None
        ):  # i.e. there is a wip entry for this object
            # get that wip entry:
            wip_entry: VersionedKeyValueStore.VersionEntry = self.key_value_store[
                object_id
            ].wip

            # was this wip entry created by TA <timestamp>?
            if wip_entry.start_validity == timestamp:
                # wip-entry marks a deleted object, return None
                if type(wip_entry) is VersionedKeyValueStore.DeleteEntry:
                    return None
                # otherwise return the value written by transaction <timestamp> itself:
                return cast(VersionedKeyValueStore.UpdateEntry, wip_entry).value

            # else:
            # wip entry belongs to another transaction, nothing to do here

        # here, no wip entry is returned: there is none, it belongs to another transaction, or wip entries are
        # ignored:

        # get all committed versions of this object from the system:
        committed_object_versions: list[VersionedKeyValueStore.VersionEntry] = (
            self.key_value_store[object_id].committed
        )

        # no committed version at all, e.g. the object is being inserted by a TA or its insert was aborted:
        # the object does not exist in this snapshot
        if len(committed_object_versions) == 0:
            return None

        # check that the committed versions are in strictly increasing order of their start_validity, which for a
        # committed version is the commit timestamp of the transaction that wrote it (not its begin), or 0 for a
        # version written outside a transaction:
        if any(
            committed_object_versions[i].start_validity
            >= committed_object_versions[i + 1].start_validity
            for i in range(len(committed_object_versions) - 1)
        ):
            raise RuntimeError(
                "committed object versions are not ordered by their validity start"
            )

        # keep only the committed versions that were committed before <timestamp>:
        visible_version_to_TA_id_list: list[VersionedKeyValueStore.UpdateEntry] = list(
            filter(
                # start_validity of a committed version is its commit timestamp (see above); delete markers are
                # kept here, as a delete newer than the visible update must hide it (checked below):
                lambda entry: entry.start_validity < timestamp,
                committed_object_versions,
            )
        )

        # all committed versions are newer than <timestamp>, e.g. the object was inserted by a transaction that
        # committed after <timestamp>: the object does not exist in this snapshot
        if len(visible_version_to_TA_id_list) == 0:
            return None

        # several committed versions (updates and delete markers) may be older than <timestamp>; the newest of
        # them, i.e. the last one in the list, is the visible one:
        last_committed_version_visible_to_TA_id: VersionedKeyValueStore.UpdateEntry = (
            visible_version_to_TA_id_list[-1]
        )

        # if the last committed version was deleted, we return None:
        if isinstance(
            last_committed_version_visible_to_TA_id, VersionedKeyValueStore.DeleteEntry
        ):
            return None
        # some asserts to (again) check the correctness of the implementation:
        assert last_committed_version_visible_to_TA_id.value is not None
        assert last_committed_version_visible_to_TA_id.start_validity is not None
        assert last_committed_version_visible_to_TA_id.start_validity < timestamp

        return last_committed_version_visible_to_TA_id.value

    def _read_objects_iterable(
        self, timestamp: int, where: Clause = None, ignore_wip=False
    ) -> ItemsView[str, list[object]]:
        """Yields the (object_id, object) pairs of all objects visible at <timestamp> that match the where clause
        <where>.

        @param timestamp: the timestamp to use for reading data, typically a transaction ID,
        required for the snapshot read
        @param where: a where clause expression that is evaluated against the actual data (not the object ids);
        None selects all objects
        @param ignore_wip: if set to True, the wip entries are ignored, i.e. only committed versions are considered.
        @return: an iterator over the (object_id, object) pairs that match the given conditions
        """

        # TODO: following should be delegated to the query optimizer and make use of indexes:
        object_id: str
        for object_id in self.key_value_store.keys():
            # get the version of the object visible at <timestamp> (None if it does not exist there):
            _object: object = self._get_visible_object_version(
                object_id, timestamp, ignore_wip=ignore_wip
            )

            if _object is not None and (where is None or where.evaluate(_object)):
                yield object_id, _object

    def _read_snapshot(
        self, timestamp: int, where: Clause = None, ignore_wip=False
    ) -> tuple[list[tuple[str, object]], str | None]:
        """Returns a list with all (object_id,objects)-pairs that match the WHERE_clause for the given snapshot
        <timestamp> plus the checksum. If the store uses brute force validation, the checksum of the returned list
        is also computed, otherwise the checksum is None.

        The checksum is the SHA-256 digest of the repr of the returned list, so it changes whenever the repr of the
        result changes. This requires that the repr of an object shows its full content; otherwise a change of the
        object can go undetected. Python's default repr shows the memory address of an object, so such objects are
        compared by identity; this is safe as committed versions are never removed, so no other object can get the
        address of a version that was read. Equal objects with different reprs only cause unnecessary aborts.

        @param timestamp: the timestamp to use for reading data, typically a transaction ID, required for the
        snapshot read
        @param where: a where clause expression that is evaluated against the actual data (not the object ids)
        @param ignore_wip: if set to True, the wip entries are ignored, i.e. only committed versions are considered

        @return: a pair with a list over the (object_id, object)-items in the result, plus the checksum as a hex string
        (None if the store does not use brute force validation)
        """

        # materialize the iterable to a list in order to be able to compute checksums:
        ret_list: list[tuple[str, object]] = list(
            self._read_objects_iterable(timestamp, where, ignore_wip=ignore_wip)
        )

        checksum: str | None = None
        if self.use_brute_force_validation:
            # compute a checksum for the list of objects: the repr contains the object_ids, contents, and order of
            # the items, a cryptographic hash makes it practically impossible that different results collide:
            checksum = hashlib.sha256(
                repr(ret_list).encode("utf-8", "surrogatepass")
            ).hexdigest()

        return ret_list, checksum

    def read_objects(
        self, TA_id: int, where: Clause = None, collect_read_clause: bool = True
    ) -> list[tuple[str, object]]:
        """Returns a list with all objects that match the WHERE_clause. If the store uses brute force validation, a
        checksum is also computed over the objects matching the WHERE_clause in the committed snapshot of TA <TA_id>,
        i.e. without TA <TA_id>'s own work-in-progress changes.

        Unless collect_read_clause is False, the where clause (and checksum) are added to the read set of TA <TA_id>.

        @param TA_id: the transaction id reading the data, required for the snapshot read
        @param where: a where clause expression that is evaluated against the actual data (not the object ids)
        @param collect_read_clause: if set to True (the default), the where clause is added to the read set of
        TA <TA_id>; False reads without adding it

        @return: a list of (object id, object) pairs that match the given conditions
        """

        if TA_id not in self.TD:
            raise KeyError(f"transaction {TA_id} not found in the system")
        if self.TD[TA_id].committed_timestamp is not None:
            raise RuntimeError(f"transaction {TA_id} committed already")

        ret: list[tuple[str, object]]
        checksum: str | None = None
        if self.use_brute_force_validation:
            # only validation method 1 uses a checksum; it is computed over the committed snapshot,
            # i.e. ignoring the wip entries of TA <TA_id>:
            # TODO: this is not efficient, and can be fixed using indexes
            _, checksum = self._read_snapshot(TA_id, where, ignore_wip=True)
        # the returned list includes the wip entries of TA <TA_id>:
        ret, _ = self._read_snapshot(TA_id, where)

        if collect_read_clause:
            self.TD[TA_id].read_clauses.add(
                HashableDict({"where_clause": where, "checksum": checksum})
            )

        return ret

    def _committed_after_begin(self, object_id: str, TA_id: int) -> bool:
        """Returns True if another transaction committed a version of object <object_id> after TA <TA_id> began.

        @param object_id: the object id of the object to be written
        @param TA_id: the transaction id of the writing transaction, i.e. its begin timestamp
        @return: True if the newest committed version of the object is newer than the begin of TA <TA_id>, False
        otherwise, in particular if there is no committed version
        """
        if object_id not in self.key_value_store:
            return False
        committed: list[VersionedKeyValueStore.VersionEntry] = self.key_value_store[
            object_id
        ].committed
        # transaction ids and commit timestamps come from the same counter (non-transactional writes use 0), so a
        # larger timestamp means "committed after TA <TA_id> began":
        return len(committed) > 0 and committed[-1].start_validity > TA_id

    def _abort_if_committed_after_begin(self, object_id: str, TA_id: int) -> None:
        """Under snapshot isolation, aborts TA <TA_id> if another transaction committed object <object_id> after
        TA <TA_id> began.

        Snapshot isolation does not validate reads, so it cannot tell whether TA <TA_id> read the object; to rule out
        lost updates, it aborts every write to an object committed after TA <TA_id> began, even a blind one. Raises
        :class:`TransactionAbortedException` after aborting the transaction; does nothing under serializable.

        @param object_id: the object id of the object to be written
        @param TA_id: the transaction id of the writing transaction, i.e. its begin timestamp
        """
        if (
            self.isolation_level == "snapshot isolation"
            and self._committed_after_begin(object_id, TA_id)
        ):
            self.abort_transaction(TA_id)
            raise TransactionAbortedException(
                f"transaction {TA_id} aborted under snapshot isolation: another transaction changed object "
                f"{object_id} and committed after transaction {TA_id} began"
            )

    def update_object(self, object_id: str, updated_object: object, TA_id: int) -> None:
        """See :meth:`ACIDStore.update_object`.

        Also supports inserts: a missing object_id creates a new entry, and writing a deleted object stores a new
        version of it. Must be executed atomically in a concurrent environment. Raises RuntimeError if the
        transaction has committed already. Aborts the transaction and raises :class:`TransactionAbortedException` if
        another transaction currently holds a work-in-progress version of the object; under the isolation level
        snapshot isolation, also if another transaction changed the object and committed after the transaction
        began. Otherwise writes an :class:`Update` journal entry, stores a deep copy of the value as the
        work-in-progress version of the object (a second write by the same transaction replaces it; the committed
        versions stay untouched), and records the object_id in the transaction's write set.
        """

        if self.TD[TA_id].committed_timestamp is not None:
            raise RuntimeError(f"transaction {TA_id} committed already")

        assert TA_id in self.TD, f"transaction {TA_id} not found in the system"

        # check that there is no other ongoing version of this object in the system
        # being worked on by another transaction, i.e. no other writer on this object is allowed:
        if (
            # do we even have an entry for this object_id?, needed to support inserts
            object_id in self.key_value_store
            # is there a wip entry for this object_id?
            and self.key_value_store[object_id].wip is not None
            # is the wip entry created by another transaction or by the same, i.e. TA_id, transaction?
            and self.key_value_store[object_id].wip.start_validity != TA_id
        ):
            self.abort_transaction(TA_id)
            raise TransactionAbortedException(
                f"another transaction is currently modifying object {object_id} already"
            )

        # under snapshot isolation, no other transaction may have committed the object since TA <TA_id> began:
        self._abort_if_committed_after_begin(object_id, TA_id)

        # 1. write to the journal:
        # update the journal for this TA:
        self.journal.put(
            TA_id,
            Update(TA_id=TA_id, object_id=object_id, nev_value=updated_object),
        )

        # post: the entry is now considered updated in the journal (might not have been flushed though)

        # 2. now update the actual store:

        # create a new entry and copy of the updated object for the kv store:
        new_entry: VersionedKeyValueStore.UpdateEntry = (
            VersionedKeyValueStore.UpdateEntry(
                start_validity=TA_id, value=copy.deepcopy(updated_object)
            )
        )

        # the committed versions stay untouched, as other transactions may still read them in their snapshots: the new
        # version goes into the wip slot, and the list of committed versions only grows (in contrast to PostgreSQL,
        # which marks the old version as outdated by writing into its header)

        # check whether this is an update or an insert:
        if object_id in self.key_value_store:
            # update the existing object:
            self.key_value_store[object_id].wip = new_entry
        else:
            # insert the new object:
            self.key_value_store[object_id] = VersionedKeyValueStore.KVStoreEntry(
                committed=list[VersionedKeyValueStore.VersionEntry](),
                wip=new_entry,
            )

        # collect the object_id of the modified object for the validation phase in the write_set for TA <TA_id>:
        self.TD[TA_id].write_set.add(object_id)

    def delete_object(self, object_id: str, TA_id: int) -> None:
        """See :meth:`ACIDStore.delete_object`.

        Must be executed atomically in a concurrent environment. Raises RuntimeError if the transaction has committed
        already. Aborts the transaction and raises :class:`TransactionAbortedException` if another transaction
        currently holds a work-in-progress version of the object; under the isolation level snapshot isolation, also
        if another transaction changed the object and committed after the transaction began. Otherwise writes a
        :class:`Delete` journal entry, adds a delete-marker work-in-progress version, and records the object_id in the
        transaction's write set.
        """

        assert TA_id in self.TD, f"transaction {TA_id} not found in the system"

        if self.TD[TA_id].committed_timestamp is not None:
            raise RuntimeError(f"transaction {TA_id} committed already")

        # check that there is no other ongoing version of this object in the system
        # by another transaction, i.e. no other writer on this object is allowed:
        if (
            self.key_value_store[object_id].wip is not None
            and self.key_value_store[object_id].wip.start_validity != TA_id
        ):
            self.abort_transaction(TA_id)
            raise TransactionAbortedException(
                f"another transaction is currently modifying object {object_id} already"
            )

        # under snapshot isolation, no other transaction may have committed the object since TA <TA_id> began:
        self._abort_if_committed_after_begin(object_id, TA_id)

        # 1. write to the journal:

        # update the journal for this TA:
        self.journal.put(TA_id, Delete(TA_id=TA_id, object_id=object_id))

        # post: the entry is now considered deleted in the journal (might not have been flushed though)

        # 2. now update the store:

        # create a new entry for the kv store that marks the object as deleted:
        new_entry: VersionedKeyValueStore.DeleteEntry = (
            VersionedKeyValueStore.DeleteEntry(start_validity=TA_id)
        )

        # add the new entry to the kv store as wip (work in progress):
        self.key_value_store[object_id].wip = new_entry

        # collect the object_id of the modified object for the validation phase in the write_set for TA <TA_id>:
        self.TD[TA_id].write_set.add(object_id)

    def show_transaction_dictionary(self) -> None:
        """Shows the transaction dictionary (self.TD)."""

        print("Transaction dictionary:")

        pp = pprint.PrettyPrinter(depth=3)
        pp.pprint(self.TD)

    def _get_next_TA_id(self) -> int:
        """Returns the next value of the counter for transaction ids and commit timestamps, and advances the counter."""
        next_TA_id: int = self.TA_id
        self.TA_id += 1

        return next_TA_id

    def begin_transaction(self) -> int:
        """See :meth:`ACIDStore.begin_transaction`.

        Additionally appends a :class:`Begin` entry to the journal.
        """
        # obtain the next transaction id:
        next_TA_id: int = self._get_next_TA_id()

        # append Begin entry to the journal:
        self.journal.put(next_TA_id, Begin(TA_id=next_TA_id))

        # post: the transaction is now marked as started in the journal (might not have been flushed though)

        # create a new metadata entry for this transaction, i.e. TA <next_TA_id>, in the transaction dictionary TD:
        self.TD[next_TA_id] = TransactionalKeyValueStore.TDEntry(
            read_clauses=set[HashableDict](),
            write_set=set[str](),
            committed_timestamp=None,
            last_committed_TA_index_in_TA_trace=len(self.committed_transactions_trace)
            - 1,
        )

        return next_TA_id

    def _validate_transaction(
        self, TA_id: int, commit_timestamp_for_this_TA: int
    ) -> bool:
        """Validates TA <TA_id> against all TAs that committed after TA <TA_id> started.

        If the store was created with use_brute_force_validation=True, uses method 1, which re-runs every read of
        TA <TA_id> on the committed state at its commit timestamp and compares checksums. Otherwise uses the more
        efficient method 2, which only checks the objects written by TAs that committed after TA <TA_id> started.
        Read-only transactions always pass. Under the isolation level snapshot isolation, validation always passes, as
        reads are not validated (conflicting writes are refused in update_object / delete_object).

        @param TA_id: the transaction id to be validated
        @param commit_timestamp_for_this_TA: the commit timestamp for this transaction

        @return True if the validation was successful, i.e. there was no conflict; False otherwise.
        """

        # snapshot isolation does not validate reads (write skew can happen):
        if self.isolation_level == "snapshot isolation":
            return True

        # "Our variation of precision locking tests discrete writes (updates, deletions, and insertions of
        # records) of recently committed transactions against predicate-oriented reads of the transaction that is
        # being validated. Thus, a validation fails if such an extensional write intersects with the intensional reads
        # of the transaction under validation"
        # [Fast Serializable Multi-Version Concurrency Control for Main-Memory Database Systems" by Neumann et al.]

        # read-only transactions do not need to be validated, they will always pass validation:
        if len(self.TD[TA_id].write_set) == 0:
            return True

        if self.use_brute_force_validation:
            # method 1 (brute force re-evaluation of all where-clauses used by TA <TA_id>):

            # re-run every read of TA <TA_id> and compare the checksum of its result with the checksum recorded when
            # TA <TA_id> read:

            rc: HashableDict
            for rc in self.TD[TA_id].read_clauses:
                # re-run each where clause on its own on the committed state at the commit timestamp of TA <TA_id>,
                # not on the snapshot that TA <TA_id> read, and compare the checksums. Equal checksums mean that the
                # read returns the same object_ids with the same contents as before, so what other transactions
                # committed in the meantime does not affect this read. Comparing only the object_ids is not enough,
                # as the contents may have changed.

                # cases:

                # per object_id argumentation:

                # 1. object <object_id> was not modified by any other transaction
                # i.e. the entry we saw in the snapshot is still the most recent committed version -> no conflict

                # 2. an object <object_id> was modified in any way, i.e. updated, deleted, or inserted and committed
                # by another transaction while TA <TA_id> was still running
                # -> there is a new version of this object in the committed list superseding the version in our
                # snapshot (if any)

                # There are the following subcases:
                # (2a.) the object is returned neither before nor now (whether it was updated, inserted, or deleted)
                # -> no conflict
                # Why? TA <TA_id> never saw object <object_id>, and would not see it now: its state is irrelevant for
                # TA <TA_id>. The checksum does not cover the object, so this object cannot change it.

                # (2b.) the object was updated/deleted, previously it was returned -> conflict
                #
                # Why? TA <TA_id> after reading object <object_id> possibly changed another object's state based on
                # this already outdated object.
                # It does not matter whether object <object_id> is returned now or not!

                # (2b.i.) now the object is returned with a different content (non-repeatable read)
                # -> the checksum differs, as it covers the repr of the (object_id, object)-pairs.
                # If another TA committed a new version with the same content, the checksum stays the same (it does not
                # cover the start_validity timestamp). This is fine: the read returns the same result as before, so
                # TA <TA_id> can be serialized after that TA. Method 2 below likewise skips objects whose old and new
                # versions compare equal with ==. Exception: for objects with Python's default repr (which shows the
                # memory address), the new version has a different repr, so the checksum differs and TA <TA_id> is
                # aborted although it need not be; likewise in method 2 for objects with the default == (identity).

                # (2b.ii.) now the object is NOT returned
                # -> checksums will still differ as this object is not returned anymore and not used for the checksum

                # (2c.) the object was not returned before, but is returned now, as it was inserted or updated to match
                # the where clause -> conflict (phantom)
                # Why? had TA <TA_id> read at its commit time, the read would return this object; TA <TA_id>'s writes
                # may depend on not having seen it.

                ####################################################################################
                # Object                    #                     Selected now                     #
                #                           #            no            #            yes            #
                ####################################################################################
                #                           #  (2a.)                   #  (2c.)                    #
                #                 no        #                          #                           #
                #                           #     no conflict          #    conflict               #
                # Selected                  #                          #                           #
                # before      ######################################################################
                #                           #  (2b.ii.)                #  (2b.i.)                  #
                #                 yes       #                          #                           #
                #                           #     conflict             #    conflict               #
                #                           #                          #                           #
                ####################################################################################

                # In summary, we catch all cases by checking the checksums of the read clauses under both snapshots.

                # re-run the read at the commit timestamp of TA <TA_id>: this sees the newest committed version of every
                # object and no wip entry, as no transaction id equals a commit timestamp:
                where: Clause = rc["where_clause"]
                checksum: str = rc["checksum"]

                _, new_checksum = self._read_snapshot(
                    commit_timestamp_for_this_TA, where=where
                )

                # checksums must be the same:
                if checksum != new_checksum:
                    # if the checksums are different, we have a conflict and thus validation fails:
                    return False
        else:
            # method 2 (only check write sets of TAs that committed after TA <TA_id> started)
            # and compare the objects returned without using checksums

            # 1. get all committed TAs that committed after TA <TA_id> started and combine their write sets:
            combined_write_set: set[str] = set[str]()

            TA_id_other: int
            # alternative without the trace of committed transactions (scans the whole transaction dictionary):
            # for TA_id_other in filter(
            #    # all TA_IDs of TAs that committed after TA <TA_id> started
            #    lambda TA: self.TD[TA].committed_timestamp
            #    and self.TD[TA].committed_timestamp > TA_id,
            #    self.TD.keys(),
            # ):
            # use the trace of committed transactions: the TAs after position last_committed_TA_index_in_TA_trace
            # committed after TA <TA_id> started:
            for TA_id_other in self.committed_transactions_trace[
                (self.TD[TA_id].last_committed_TA_index_in_TA_trace + 1) :
            ]:
                # for each qualifying TA <TA_id_other>, get the write set of that TA
                # i.e. all object_ids of objects that were written by TA <TA_id_other>
                # and add them to the combined write set:
                combined_write_set.update(self.TD[TA_id_other].write_set)

            # post: we have a combined write set of object_ids modified for all TAs that committed after TA <TA_id>
            # started

            # if that write set is empty, we can skip the validation phase successfully as there cannot be a conflict:
            if len(combined_write_set) == 0:
                return True

            def selected(where: Clause | None, _object: object | None) -> bool:
                """Returns True if <_object> is returned by a read with the where clause <where>.

                A missing object (not existing or deleted, i.e. None) is never returned; a read without a where
                clause (None) returns every existing object.
                """
                return _object is not None and (
                    where is None or where.evaluate(_object)
                )

            # 2. check the combined write set against the read clauses of the TA <TA_id> to be validated:
            rc: HashableDict
            for rc in self.TD[TA_id].read_clauses:
                # for each where clause independently:
                where: Clause | None = rc["where_clause"]

                object_id: str
                for object_id in combined_write_set:
                    # for each object_id in the combined write set, we check whether the object was visible by
                    # TA <TA_id>
                    # get the version of the object in the snapshot of TA <TA_id>, i.e. ignoring the wip
                    # entry of TA <TA_id> itself (None if it did not exist in or was deleted from the snapshot):
                    _object_as_of_TA_ID: object | None = (
                        self._get_visible_object_version(
                            object_id, TA_id, ignore_wip=True
                        )
                    )
                    # get the most recent committed version of the object available now, i.e. at the commit timestamp
                    # of TA <TA_id> (None if it was deleted):
                    _object_as_of_now: object | None = self._get_visible_object_version(
                        object_id, commit_timestamp_for_this_TA, ignore_wip=True
                    )

                    # compare the snapshot seen for TA <TA_id> with the most recent committed version,
                    # feed both in the where clause: if any where-clause returns an object, we have a conflict
                    # and validation fails:
                    if _object_as_of_now == _object_as_of_TA_ID:
                        # no conflict
                        continue

                    if selected(where, _object_as_of_TA_ID) or selected(
                        where, _object_as_of_now
                    ):
                        return False

        # validation was successful:
        return True

    def commit_transaction(self, TA_id: int) -> None:
        """See :meth:`ACIDStore.commit_transaction`.

        Runs the validation phase first: on a conflict the transaction is aborted and
        :class:`TransactionAbortedException` is raised. On success, a :class:`Commit` journal entry is written and
        flushed, and the transaction's work-in-progress versions become visible by moving them from ``wip`` to the
        ``committed`` list under the commit timestamp.

        This method must be executed serially in a concurrent environment, otherwise, write skew anomaly can go
        undetected.
        A multithreaded implementation of this method is not yet implemented and not required for a didactical
        implementation of MVCC.
        What MVCC does is in fact orthogonal to multithreading and in order to explain MVCC just adds unwarranted
        complexity which does not facilitate understanding of MVCC.

        E.g., both transactions pass validation and commit in this schedule, although each one read an object
        that the other one wrote, e.g. write skew::

            T1                              T2
            r(s), w(t)
                                            r(t), w(s)
            gets commit timestamp 6
                                            gets commit timestamp 7

                                            validation passes, as
                                            w(t) of T1 is not visible yet
            validation passes, as
            w(s) of T2 is not visible yet
                                            makes its versions visible
            makes its versions visible

        Under serializable, with serial commits, T1 is validated and installs its versions first. Afterwards, the
        validation of T2 sees the new value of t written by T1, which T2 read, so T2 fails validation and is aborted.

        With overlapping commits (e.g. in several threads), the validation of T2 may run before T1 has installed
        its versions, so it does not see them.

        To validate transactions in parallel, you need an extra mechanism that detects such cases.
        """

        assert TA_id in self.TD, f"transaction {TA_id} not found in the system"

        # get a unique commit timestamp just for validating and committing this TA:
        commit_timestamp_for_this_TA: int = self._get_next_TA_id()

        # 1. validation phase:
        successful: bool
        successful = self._validate_transaction(
            TA_id, commit_timestamp_for_this_TA=commit_timestamp_for_this_TA
        )

        # validation returned a conflict with another transaction:
        if not successful:
            self.abort_transaction(TA_id)
            raise TransactionAbortedException(
                f"validation failed, Transaction {TA_id} failed the validation phase and therefore was aborted due to"
                f" a conflict with another transaction"
            )

        # do not confuse the commit timestamp with the start timestamp of the transaction:
        assert commit_timestamp_for_this_TA > TA_id

        # I. write to the journal:

        # append Commit entry to the journal, also tracking the commit timestamp (needed for recovery):
        self.journal.put(
            TA_id, Commit(TA_id=TA_id, commit_timestamp=commit_timestamp_for_this_TA)
        )

        # flush the journal for the given key for WAL:
        self.journal.flush(TA_id)

        # post: the transaction is now marked as committed in the journal (and flushed!)

        # II. update the store:

        # 2. commit phase:
        # let all wip objects of TA <TA_id> become a new committed version:
        # i.e. we move all objects modified by this TA from wip to committed:
        for object_id in self.TD[TA_id].write_set:
            wip_entry: VersionedKeyValueStore.VersionEntry = self.key_value_store[
                object_id
            ].wip

            # so far, the start validity of the wip entry must be the TA_id:
            assert wip_entry.start_validity == TA_id

            # start timestamp of the wip entry must be less than the commit timestamp:
            assert wip_entry.start_validity < commit_timestamp_for_this_TA

            # the wip entry is either a new value (UpdateEntry) or a delete marker (DeleteEntry):
            assert isinstance(
                wip_entry, VersionedKeyValueStore.UpdateEntry
            ) or isinstance(wip_entry, VersionedKeyValueStore.DeleteEntry)

            # change start_validity to become the commit timestamp:
            wip_entry.start_validity = commit_timestamp_for_this_TA

            # move the wip entry to the committed list:
            self.key_value_store[object_id].committed.append(wip_entry)

            # delete the old wip entry from the kv store (by setting it to None):
            # this will allow other writers to modify the object again:
            # if we would not delete the wip entry, we would not allow other writers to modify the object ever again
            self.key_value_store[object_id].wip = None

        # mark TA <TA_Id> as committed by setting the committed timestamp:
        self.TD[TA_id].committed_timestamp = commit_timestamp_for_this_TA

        # append TA <TA_id> to the trace of committed transactions; validation method 2 uses it to find the
        # transactions that committed after a transaction began:
        self.committed_transactions_trace.append(TA_id)

    def abort_transaction(self, TA_id: int) -> None:
        """See :meth:`ACIDStore.abort_transaction`.

        Writes an :class:`Abort` journal entry, removes every work-in-progress version created by the transaction,
        and deletes the transaction from the transaction dictionary.
        """

        assert TA_id in self.TD, f"transaction {TA_id} not found in the system"

        # append Abort entry to the journal:
        # note: actually, this entry is of no use: it does not matter whether a transaction has no Commit journal entry
        # or an Abort journal entry, the transaction is still considered as aborted
        # so, technically we could also remove all journal entries ever created for this TA_id from the journal
        # and still be able to detect aborted transactions
        # del self.journal[TA_id]
        self.journal.put(TA_id, Abort(TA_id=TA_id))

        # post: the transaction is now marked as Aborted in the journal (might not have been flushed though)

        # and now for the store:

        # remove all wip-entries from the system for all objects updated by this TA (by setting these wip-entries to
        # None):
        # i.e. we do not want to keep any changes made by this TA, this is important to allow other TAs to modify
        # the objects again
        object_id: str
        for object_id in self.TD[TA_id].write_set:
            self.key_value_store[object_id].wip = None

        # remove the transaction from the transaction dictionary (TD):
        del self.TD[TA_id]
