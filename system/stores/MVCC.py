from __future__ import annotations

import copy
import pprint
from dataclasses import dataclass
from typing import Dict, ItemsView

from system.interfaces.indexing.Index import KeyValueStore
from system.interfaces.stores import ACIDStore
from system.query_processing import Clause
from system.stores.VersionedKeyValueStore import HashableDict, VersionedKeyValueStore


class TransactionAbortedException(Exception):
    """An exception that is raised when a transaction is aborted by the store."""

    pass


class TransactionalKeyValueStore(VersionedKeyValueStore, ACIDStore):
    """A fully transactional versioned key value store (formerly known as MVCCStore).

    Notice that this store goes far beyond the typical key value store, which typically is only transactional per
    SINGLE key update/insert/delete.
    In contrast, this store is FULLY transaction, i.e. it allows for multiple keys to be updated within a single
    transaction. Those changes are SERIALIZABLE. The write skew anomaly is detected and avoided.
    """

    @dataclass
    class TDEntry:
        """Entries used for the transaction dictionary."""

        # a set of where clauses used by the transaction to read objects from the store:
        read_clauses: set[HashableDict[str, Clause | int]]

        # a set of object_ids of objects that were modified by the transaction:
        write_set: set[str]

        # the timestamp when the transaction was committed, None if the transaction is still ongoing:
        committed_timestamp: int | None

        # the index of the last committed transaction in the committed transactions log when the transaction started:
        last_committed_TA_index_in_TA_log: int | None

    def __init__(
        self,
        use_brute_force_validation: bool = False,
        persistence_layer: KeyValueStore = None,
    ):
        """Initializes the store.

        @param use_brute_force_validation: if set to True, the store will use the brute force validation algorithm in
        the validation phase.
        @param persistence_layer: the persistence layer to use for the store
        """

        super().__init__(persistence_layer=persistence_layer)
        self.use_brute_force_validation: bool = use_brute_force_validation

        # transaction id counter:
        self.TA_id: int = 1

        # transaction dictionary mapping from TA_id to TDEntry
        self.TD: Dict[int, TransactionalKeyValueStore.TDEntry] = dict[
            int, TransactionalKeyValueStore.TDEntry
        ]()

        # a log of the committed transactions:
        self.committed_transactions_log: list[int] = list()

    def _get_visible_object_version(
        self, object_id: str, timestamp: int, ignore_wip=False
    ) -> object:
        """
        Gets the visible version of object <object_id> for TA <TA_id> under snapshot isolation.

        This entails:
        - getting the most recent committed version of the object that is visible to TA <TA_id> under snapshot isolation
        - this is either the wip entry created by TA <TA_id> or the most recent committed version of the object
        - if the most recent committed version was deleted, None is returned
        - the returned method must have a start < TA_id

        @param object_id: the object id of the object to be read
        @param timestamp: the timestamp, i.e. the transaction id of the transaction reading the object
        @param ignore_wip: if set to True, the wip entries are ignored, i.e. only committed versions are considered.

        @return: the visible version of the object for TA <TA_id> under snapshot isolation, None if it was deleted
        """

        if object_id not in self.key_value_store:
            raise Exception(f"object {object_id} not found in the store")

        # check whether TA <TA_id> already has a wip entry for this object:
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
                if wip_entry.deleted:
                    return None
                else:
                    # i.e. we return the version of the object that is currently being modified by this TA_id:
                    return wip_entry.value

            # else:
            # wip entry belongs to another transaction, nothing to do here

        # post/else: there is no wip entry for object <object_id> by TA <TA_id>

        # get all committed versions of this object (under snapshot isolation) from the system:
        committed_object_versions: list[VersionedKeyValueStore.VersionEntry] = (
            self.key_value_store[object_id].committed
        )

        if len(committed_object_versions) == 0:
            raise Exception("object {object_id} has no committed versions")

        # post: those object versions are ordered by their start timestamp:
        # Note: entries must be ordered by their commit timestamp, NOT by their start timestamp
        if any(
            committed_object_versions[i].start_validity
            >= committed_object_versions[i + 1].start_validity
            for i in range(len(committed_object_versions) - 1)
        ):
            raise Exception(
                "committed object versions are not ordered by their validity start"
            )

        # get the version of this object visible to TA <TA_id> under snapshot isolation:
        visible_version_to_TA_id_list: list[VersionedKeyValueStore.VersionEntry] = list(
            filter(
                # version must have existed (in the sense of committed! NOT started!) before TA_id started:
                # note: do not filter for deleted at this point!
                lambda entry: entry.start_validity < timestamp,
                committed_object_versions,
            )
        )

        # get the most recent visible version to this TA_id:
        # note that there may be multiple committed and also deleted versions of the object
        # that are visible to TA <TA_id> under snapshot isolation
        # so, we return the last one in the list:
        last_committed_version_visible_to_TA_id: VersionedKeyValueStore.VersionEntry = (
            visible_version_to_TA_id_list[-1]
        )

        # if the last committed version was deleted, we return None:
        if last_committed_version_visible_to_TA_id.deleted:
            return None
        else:
            # some asserts to (again) check the correctness of the implementation:
            assert last_committed_version_visible_to_TA_id.value is not None
            assert last_committed_version_visible_to_TA_id.start_validity is not None
            assert last_committed_version_visible_to_TA_id.start_validity < timestamp

            return last_committed_version_visible_to_TA_id.value

    def _read_more_recent_committed_versions_iterable(
        self, where: Clause = None
    ) -> ItemsView[object]:
        """Defines an iterable with all objects that were committed after TA_id <TA_id>.

        @param where: a where clause expression that is evaluated against the actual data (not the object ids), if it
        is None, all objects are returned

        @return: an iterable of the objects matching (not just the object_ids!)
        """

        # the following can be quite expensive to execute without indexes:
        # a better method would be to delegate to the query optimizer and make use of indexes
        # loop over all entries from tuples touched in the kv-store:
        object_id: str
        entry: VersionedKeyValueStore.KVStoreEntry
        for object_id, entry in self.key_value_store.items():
            # get the most recent committed version of the object available (rather than the version seen under
            # snapshot isolation), i.e. the last element in the committed list:
            most_recent_entry: VersionedKeyValueStore.VersionEntry = entry.committed[-1]

            # if the last committed version was deleted, we skip it:
            if most_recent_entry.deleted:
                continue

            # return the object if the where clause is None or the object matches the where clause:
            if where is None or where.evaluate(most_recent_entry.value):
                yield most_recent_entry.value

    def _read_objects_iterable(
        self, timestamp: int, where: Clause = None, ignore_wip=False
    ) -> ItemsView[str, list[object]]:
        """Returns an iterable with all objects that match the WHERE_clause.

        @param timestamp: the timestamp to use for reading data, typically a transaction ID,
        required for snapshot isolation
        @param where: a where clause expression that is evaluated against the actual data (not the object ids)
        @param ignore_wip: if set to True, the wip entries are ignored, i.e. only committed versions are considered.
        @return: an iterator over the object ids that match the given conditions
        """

        # TODO: following should be delegated to the query optimizer and make use of indexes:
        object_id: str
        for object_id in self.key_value_store.keys():
            # get the most recent visible version of the object to TA <TA_id> under snapshot isolation:
            _object: object = self._get_visible_object_version(
                object_id, timestamp, ignore_wip=ignore_wip
            )

            if _object is not None and (where is None or where.evaluate(_object)):
                yield object_id, _object

    def _read_snapshot(
        self, timestamp: int, where: Clause = None, ignore_wip=False
    ) -> tuple[list[tuple[str, object]], int]:
        """Returns a list with all (object_id,objects)-pairs that match the WHERE_clause for the given snapshot
        <timestamp> plus the checksum. If the store uses brute force validation, the checksum of the returned list
        is also computed.

        @param timestamp: the timestamp to use for reading data, typically a transaction ID, required for snapshot
        isolation
        @param where: a where clause expression that is evaluated against the actual data (not the object ids)
        @param ignore_wip: if set to True, the wip entries are ignored, i.e. only committed versions are considered

        @return: a pair with a list over the (object_id, object)-items in the result, plus a checksum
        """

        # materialize the iterable to a list in order to be able to compute checksums:
        ret_list: list[tuple[str, object]] = list(
            self._read_objects_iterable(timestamp, where, ignore_wip=ignore_wip)
        )

        checksum: int | None = None
        if self.use_brute_force_validation:
            # compute a checksum for the list of objects:
            checksum = sum(map(lambda x: x.__hash__(), ret_list))

        return ret_list, checksum

    def read_objects(
        self, TA_id: int, where: Clause = None, collect_read_clause: bool = True
    ) -> list[tuple[str, object]]:
        """Returns a list with all objects that match the WHERE_clause. If the store uses brute force validation, the
        checksum of the returned list is also computed.

        In any case, the where clause (and checksum) are added to the read set of TA <TA_id>.

        @param TA_id: the transaction id reading the data, required for snapshot isolation
        @param where: a where clause expression that is evaluated against the actual data (not the object ids)
        @param collect_read_clause: if set to True, the where clause is not added to the read set of TA <TA_id>

        @return: a list over the object ids that match the given conditions
        """

        if TA_id not in self.TD:
            raise Exception(f"transaction {TA_id} not found in the system")
        if self.TD[TA_id].committed_timestamp is not None:
            raise Exception(f"transaction {TA_id} committed already")

        ret: list[tuple[str, object]]
        checksum: int
        # issue the read twice to get correct checksums:
        # TODO: this is not efficient, and can be fixed using indexes
        # (1.) ignore the wip entries for the checksum computation
        _, checksum = self._read_snapshot(TA_id, where, ignore_wip=True)
        # (2.) consider the wip entries for the actual returned list
        ret, _ = self._read_snapshot(TA_id, where)

        if collect_read_clause:
            self.TD[TA_id].read_clauses.add(
                HashableDict({"where_clause": where, "checksum": checksum})
            )

        return ret

    def update_object(self, object_id: str, updated_object: object, TA_id: int) -> None:
        """Updates the object with the given <object_id>. If run in a concurrent environment, this method must be
        executed atomically.
        @param object_id: the object id of the object to be updated
        @param updated_object: the updated object, i.e. the new value to be associated with the object_id
        @param TA_id: the transaction id of the transaction that is updating (or trying to update) the object
        """
        if self.TD[TA_id].committed_timestamp is not None:
            raise Exception(f"transaction {TA_id} committed already")

        # check that there is no other ongoing version of this object in the system
        # being worked on by another transaction, i.e. no other writer on this object is allowed:
        if (
            self.key_value_store[object_id].wip is not None
            and self.key_value_store[object_id].wip.start_validity != TA_id
        ):
            raise TransactionAbortedException(
                f"another transaction is currently modifying object {object_id} already"
            )

        # create a new entry and copy of the updated object for the kv store:
        new_entry: VersionedKeyValueStore.VersionEntry = (
            VersionedKeyValueStore.VersionEntry(
                start_validity=TA_id, value=copy.deepcopy(updated_object)
            )
        )

        #  NEW: keep your hands off the old committed version:
        #  we do not want to modify the old committed version, because it is still visible to other transactions
        #  effect: now the store is purely append-only (in contrast to PostgreSQL, where old versions are updated)

        # add the new entry to the kv store as wip (work in progress):
        self.key_value_store[object_id].wip = new_entry

        # collect the object_id of the modified object for the validation phase in the write_set for TA <TA_id>:
        self.TD[TA_id].write_set.add(object_id)

    def delete_object(self, object_id: str, TA_id: int) -> None:
        """Deletes the object with the given <object_id>. If run in a concurrent environment, this method must be
        executed atomically.

        @param object_id: the object id of the object to be deleted
        @param TA_id: the transaction id of the transaction that is deleting (or trying to delete) the object
        """

        if self.TD[TA_id].committed_timestamp is not None:
            raise Exception(f"transaction {TA_id} committed already")

        # check that there is no other ongoing version of this object in the system
        # by another transaction, i.e. no other writer on this object is allowed:
        if (
            self.key_value_store[object_id].wip is not None
            and self.key_value_store[object_id].wip.start_validity != TA_id
        ):
            raise Exception(
                f"another transaction is currently modifying object {object_id} already"
            )

        # create a new entry for the kv store that marks the object as deleted:
        new_entry: VersionedKeyValueStore.VersionEntry = (
            VersionedKeyValueStore.VersionEntry(
                start_validity=TA_id, value=None, deleted=True
            )
        )

        # add the new entry to the kv store as wip (work in progress):
        self.key_value_store[object_id].wip = new_entry

        # collect the object_id of the modified object for the validation phase in the write_set for TA <TA_id>:
        self.TD[TA_id].write_set.add(object_id)

    def show_transaction_dictionary(self) -> None:
        """Shows the transaction dictionary (self.TD)."""

        print(f"Transaction dictionary:")

        pp = pprint.PrettyPrinter(depth=3)
        pp.pprint(self.TD)

    def _get_next_TA_id(self) -> int:
        """Returns the next transaction id."""
        next_TA_id: int = self.TA_id
        self.TA_id += 1

        return next_TA_id

    def begin_transaction(self) -> int:
        """Starts a new transaction and returns its transaction id.
        Also adds a new entry with metadata for this transaction in the transaction dictionary.
        """

        # obtain the next transaction id:
        next_TA_id: int = self._get_next_TA_id()

        # create a new metadata entry for this transaction, i.e. TA <next_TA_id>, in the transaction dictionary TD:
        self.TD[next_TA_id] = TransactionalKeyValueStore.TDEntry(
            read_clauses=set[HashableDict](),
            write_set=set[str](),
            committed_timestamp=None,
            last_committed_TA_index_in_TA_log=len(self.committed_transactions_log) - 1,
        )

        return next_TA_id

    def _validate_transaction(
        self, TA_id: int, commit_timestamp_for_this_TA: int
    ) -> bool:
        """Validates TA <TA_id> against all TAs that committed after TA <TA_id> started.

        @param TA_id: the transaction id to be validated
        efficient method 2 which only checks write sets of TAs that committed after TA <TA_id> started
        @param commit_timestamp_for_this_TA: the commit timestamp for this transaction

        @return True, None if the validation was successful, i.e. there was no conflict
        @return False, conflict_set|None if the validation failed, i.e. there was a conflict
        """

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

            # get read-clauses of self TA <TA_id> and compares the checksum of the returned set against the previously
            # recorded checksum:

            rc: HashableDict
            for rc in self.TD[TA_id].read_clauses:
                # re-execute each where clause independently against the current committed state of the DB,
                # NOT the snapshot used WHILE running the TA; and check whether the checksum is the same.
                # If the checksum is the same, the objects_ids returned are the same AND their contents are the same as
                # before, i.e. they were not modified by any other transaction. Note that checking for intersection
                # of the object_ids is not enough, as the contents of the objects might have changed.

                # cases:

                # per object_id argumentation:

                # 1. object <object_id> was not modified by any other transaction
                # i.e. the entry we saw in the snapshot is still the most recent committed version -> no conflict

                # 2. an object <object_id> was modified in any way, i.e. updated, deleted, or inserted and committed
                # by another transaction while TA <TA_id> was still running
                # -> there is a new version of this object in the committed list superseding the version we read under
                # snapshot isolation

                # There are the following subcases:
                # (2a.) the object was updated/inserted, but previously AND now it is NOT returned -> no conflict
                # Why? TA <TA_id> never saw object <object_id>, its state is irrelevant for TA <TA_id>

                # not a problem: we do not need to check for this case

                # (2b.) the object was updated/deleted, previously it was returned -> conflict
                #
                # Why? TA <TA_id> after reading object <object_id> possibly changed another object's state based on
                # this already outdated object.
                # It does not matter whether object <object_id> is returned now or not!

                # (2b.i.) now the object is returned with a different version
                # -> checksums will differ as a new version of the object is available
                # note that this also covers the case that a TA created a new version of the object with the exact same
                # content as before -> checksums will still differ due to the start_validity timestamp

                # (2b.ii.) now the object is NOT returned
                # -> checksums will still differ as this object is not returned anymore and not used for the checksum

                # (2c.) the object was updated/inserted, but previously it was NOT BUT now it IS returned -> conflict
                # (non-repeatable read/phantom read anomaly)
                # Why? TA <TA_id> possibly changed another object's state based on an object that was not visible before
                # but should have been considered in the first place.

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

                where: Clause = rc["where_clause"]
                checksum: int = rc["checksum"]

                ret_list, new_checksum = self._read_snapshot(
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
            # alternative method without exploiting the committed transactions log:
            # for TA_id_other in filter(
            #    # all TA_IDs of TAs that committed after TA <TA_id> started
            #    lambda TA: self.TD[TA].committed_timestamp
            #    and self.TD[TA].committed_timestamp > TA_id,
            #    self.TD.keys(),
            # ):
            # exploit the committed transactions log to get all TAs that committed after TA <TA_id> started:
            for TA_id_other in self.committed_transactions_log[
                (self.TD[TA_id].last_committed_TA_index_in_TA_log + 1) :
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

            # 2. check the combined write set against the read clauses of the TA <TA_id> to be validated:
            rc: HashableDict
            for rc in self.TD[TA_id].read_clauses:
                # for each where clause independently:
                # note: no disjunction here, e.g. a disjunction of where clauses would lead to errors
                where: Clause = rc["where_clause"]

                object_id: str
                for object_id in combined_write_set:
                    # for each object_id in the combined write set, we check whether the object was visible by
                    # TA <TA_id>
                    # get the most recent visible version of the object to TA <TA_id> under snapshot isolation:
                    _object_as_of_TA_ID: object = self._get_visible_object_version(
                        object_id, TA_id
                    )
                    # get the most recent committed version of the object available now:
                    # TODO: deleted entry not considered here
                    _object_as_of_now: object = (
                        self.key_value_store[object_id].committed[-1].value
                    )  # last version in the commited list

                    # compare the snapshot seen for TA <TA_id> with the most recent committed version,
                    # feed both in the where clause: if any where-clause returns an object, we have a conflict
                    # and validation fails:
                    if _object_as_of_now == _object_as_of_TA_ID:
                        # no conflict
                        continue

                    if where.evaluate(_object_as_of_TA_ID) or where.evaluate(
                        _object_as_of_now
                    ):
                        return False

        # validation was successful:
        return True

    def commit_transaction(self, TA_id: int) -> None:
        """Commits the given transaction.
        This includes the validation phase and the actual commit phase where the updated objects become visible
        to other TAs, i.e. they are moved from <wip> to the <committed> list.
        @param TA_id: the transaction id of the transaction to be committed
        """

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

            # either the value is not None or the entry is deleted:
            assert wip_entry.value is not None or wip_entry.deleted

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

        # log the committed transaction:
        self.committed_transactions_log.append(TA_id)

    def abort_transaction(self, TA_id: int) -> None:
        """Aborts the given transaction and removes all changes made by this transaction from the system.

        @param TA_id: the transaction id of the transaction to be aborted
        """

        # remove all wip-entries from the system for all objects updated by this TA (by setting the entry to None):
        # i.e. we do not want to keep any changes made by this TA, this is important to allow other TAs to modify
        # the objects again
        object_id: str
        for object_id in self.TD[TA_id].write_set:
            self.key_value_store[object_id].wip = None

        # remove the transaction from the transaction dictionary:
        del self.TD[TA_id]
