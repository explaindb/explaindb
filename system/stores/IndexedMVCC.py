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

"""Indexed transactional key-value store built on MVCC."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator

from system.indexes.indexes import PythonDictionaryIndex
from system.interfaces.indexing.Index import IndexProperties, Index, KeyValueStore
from system.interfaces.stores import IndexedACIDStore
from system.query_processing.predicates import Clause, WHERE_Clause
from system.stores.MVCC import IsolationLevel, TransactionalKeyValueStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore


class IndexedTransactionalKeyValueStore(TransactionalKeyValueStore, IndexedACIDStore):
    """A fully transactional versioned (MVCC) key value store with indexes on object attributes.

    An index maps an attribute value to the ids of the objects that have it (the store maps an object id to the
    versions of the object). Every version whose object has the indexed attribute is in that index: committed versions
    and the work-in-progress versions of running transactions; delete markers carry no object. A version leaves the
    index only when its transaction writes the object again or aborts.

    So an index is a filter index: for a value it returns the ids of a superset of the objects whose version visible
    to a transaction has that value, and an object id appears once per indexed version with that value. A read with
    the where clause ``attribute == constant`` on an indexed attribute uses the index: it takes the distinct
    candidate ids, gets the version visible to the transaction (snapshot read) and checks it against the where
    clause. The index names the candidates, the snapshot decides. Any other read scans all objects. Both return the
    same objects.

    This relies on two assumptions: attribute values hash consistently with ``==`` (as Python's built-in types do),
    and callers do not change the objects a read returns (reads return the stored versions, not copies), as the index
    would then still list the old value.

    At most one index per attribute and operator; only equality indexes are supported.
    """

    @dataclass
    class IndexCatalogueEntry:
        """Entries used for the index catalog."""

        # the index properties of the index:
        index_properties: IndexProperties

        # the index itself:
        index: KeyValueStore[object, str]

    def __init__(
        self,
        use_brute_force_validation: bool = False,
        isolation_level: IsolationLevel = "serializable",
        autocommit: bool = False,
    ):
        """Initialize the store and its (initially empty) index catalogues.

        :param use_brute_force_validation: if True, the underlying store uses the brute-force validation
            algorithm in the validation phase (see :class:`~system.stores.MVCC.TransactionalKeyValueStore`).
        :param isolation_level: the isolation level of the underlying store, "serializable" or "snapshot isolation"
            (see :class:`~system.stores.MVCC.TransactionalKeyValueStore`).
        :param autocommit: if True, put, bulkload, get and delete without a transaction id each run as a transaction
            of their own (see :class:`~system.stores.MVCC.TransactionalKeyValueStore`).
        """
        # set up the transactional store:
        super().__init__(
            use_brute_force_validation=use_brute_force_validation,
            isolation_level=isolation_level,
            autocommit=autocommit,
        )

        # a dictionary mapping from the index name to (IndexProperties, Index):
        self.indexes_by_name: Dict[
            str, IndexedTransactionalKeyValueStore.IndexCatalogueEntry
        ] = dict[str, IndexedTransactionalKeyValueStore.IndexCatalogueEntry]()

        # a dictionary mapping from IndexProperties to the index name:
        self.indexes_by_properties: Dict[IndexProperties, str] = dict[
            IndexProperties, str
        ]()

    @staticmethod
    def _object_of(
        version_entry: VersionedKeyValueStore.VersionEntry | None,
    ) -> object | None:
        """Returns the object stored in a version entry.

        @param version_entry: a committed or work-in-progress version entry, or None
        @return: the value of an UpdateEntry; None for a DeleteEntry (a delete marker carries no object) or no entry
        """
        if isinstance(version_entry, VersionedKeyValueStore.UpdateEntry):
            return version_entry.value
        return None

    @staticmethod
    def _deindex_object(
        index: Index, attribute: str, object_id: str, old_object: object
    ) -> None:
        """De-indexes the object with the given object_id and object.
        @param index: the index to remove the entry from
        @param attribute: the indexed attribute
        @param object_id: the object id of the object to be de-indexed
        @param old_object: the version of the object to be de-indexed
        """
        # does the old object have that attribute (only then it was indexed):
        if hasattr(old_object, attribute):
            # get the value of that attribute
            attribute_value: object = getattr(old_object, attribute)

            # delete the entry from the index:
            index.delete(attribute_value, object_id)

    @staticmethod
    def _index_object(
        index: Index, attribute: str, object_id: str, new_object: object
    ) -> None:
        """Indexes the object with the given object_id and object.
        @param index: the index to use for indexing
        @param attribute: the attribute to index
        @param object_id: the object id of the object to be indexed
        @param new_object: the new version of the object to be indexed
        """
        # does the new object have that attribute:
        if hasattr(new_object, attribute):
            # only then we can add the object_id to the index:
            # get the value of that attribute:
            attribute_value: object = getattr(new_object, attribute)

            # add an entry to the index:
            # here is where the inversion happens,
            # i.e. the index maps from the attribute value (key) of the object to the object_id (value)
            # whereas the store maps from the object_id (key) to the versions of the object (value)
            index.put(attribute_value, object_id)

    def create_index(self, index_name: str, attribute: str, operator: str) -> None:
        """See :meth:`IndexedACIDStore.create_index`.

        Only equality indexes (operator ``"="``) are supported; any other operator raises. Raises as well if an
        index with the given name, or an index on the same attribute with the same operator, already exists. The
        index is backed by a :class:`~system.indexes.indexes.PythonDictionaryIndex` and acts as a filter index, i.e.
        lookups return a superset of matches that still has to be post-filtered. If filling the index fails, no index
        is created.
        """
        if index_name in self.indexes_by_name:
            raise KeyError(f"index {index_name} already exists")

        # only equality indexes are supported at the moment:
        if operator not in ["="]:
            raise NotImplementedError(f"operator {operator} not supported")

        # the catalogue maps the index properties to a single index name, so at most one index per attribute and
        # operator:
        index_properties: IndexProperties = IndexProperties(
            attribute=attribute, operator=operator
        )
        if index_properties in self.indexes_by_properties:
            raise KeyError(
                f"index {self.indexes_by_properties[index_properties]} on {attribute} with operator {operator} "
                "already exists"
            )

        # the only type of index supported at the moment is a PythonDictionary (wrapping a python dict) with support
        # for duplicates:
        index: KeyValueStore[object, str] = PythonDictionaryIndex()

        # bulkload the index with every version of every object in the store:
        # TODO: delegate to bulkload method of the index?
        object_id: str
        _object: object

        kv_entry: VersionedKeyValueStore.KVStoreEntry
        for object_id, kv_entry in self.key_value_store.items():

            # index every version that carries an object (delete markers carry none):
            version_entry: VersionedKeyValueStore.VersionEntry
            for version_entry in kv_entry:
                version_object: object | None = (
                    IndexedTransactionalKeyValueStore._object_of(version_entry)
                )
                if version_object is not None:
                    IndexedTransactionalKeyValueStore._index_object(
                        index, attribute, object_id, version_object
                    )

        # register the index only now that it is complete, so a failing bulkload (e.g. an attribute value that cannot
        # be hashed) leaves no index behind:
        self.indexes_by_name[index_name] = (
            IndexedTransactionalKeyValueStore.IndexCatalogueEntry(
                index_properties, index
            )
        )
        self.indexes_by_properties[index_properties] = index_name

    def drop_index(self, index_name: str) -> None:
        """See :meth:`IndexedACIDStore.drop_index`.

        Removes the index from both catalogues (by name and by properties). Raises if no index with the given
        name exists.
        """
        if index_name not in self.indexes_by_name:
            raise KeyError(f"index {index_name} does not exist")

        entry: IndexedTransactionalKeyValueStore.IndexCatalogueEntry = (
            self.indexes_by_name[index_name]
        )
        del self.indexes_by_name[index_name]
        del self.indexes_by_properties[entry.index_properties]

    def abort_transaction(self, TA_id: int) -> None:
        """See :meth:`TransactionalKeyValueStore.abort_transaction`.

        Before delegating to the base implementation, de-indexes every work-in-progress version created by the
        transaction from all indexes, so the indexes stay consistent with the reverted store.
        """

        # iterate over all wip entries of this TA, i.e. all objects that were updated by this TA but not yet committed:
        # -> for each object_id in the write set of this TA:
        object_id: str
        for object_id in self.TD[TA_id].write_set:
            # get the wip entry of this object_id:
            wip_entry: VersionedKeyValueStore.VersionEntry | None = (
                self.key_value_store[object_id].wip
            )
            assert wip_entry is not None
            assert wip_entry.start_validity == TA_id

            # get the old object version of the wip entry (None for a delete marker, nothing to de-index):
            old_object: object | None = IndexedTransactionalKeyValueStore._object_of(
                wip_entry
            )

            # maintain the indexes for this change, i.e. remove this wip entry from all indexes:
            self._maintain_indexes(
                object_id,
                object_to_index=None,  # nothing new to index
                object_to_deindex=old_object,  # object to be de-indexed
            )

        # call super method to remove all changes made by this transaction from the system including the wip entries:
        super().abort_transaction(TA_id)

    def get_suitable_indexes(
        self, attribute: str, operator: str
    ) -> Iterator[IndexProperties]:
        """See :meth:`IndexedACIDStore.get_suitable_indexes`."""

        # predicate to check for suitability of an index:
        # TODO: well,yes, we could directly use the index here:
        def is_suitable(index_properties: IndexProperties) -> bool:
            """True iff the index matches both the requested attribute and operator."""
            return (
                index_properties.attribute == attribute
                and index_properties.operator == operator
            )

        return filter(is_suitable, self.indexes_by_properties.keys())

    def _index_for(self, where: Clause | None) -> KeyValueStore[object, str] | None:
        """Returns the index that can answer a read with the given where clause.

        @param where: the where clause of the read; None selects all objects
        @return: the equality index on the attribute of a clause ``attribute == constant``; None for any other clause
        or if there is no index on that attribute
        """
        # only a single equality comparison can use an equality index:
        if not isinstance(where, WHERE_Clause) or where.operator != "==":
            return None

        # the where clause writes equality as "==", the index properties as "="; there is at most one index per
        # attribute and operator (see create_index):
        index_properties: IndexProperties | None = next(
            self.get_suitable_indexes(where.attribute, "="), None
        )
        if index_properties is None:
            return None
        return self.indexes_by_name[self.indexes_by_properties[index_properties]].index

    def _read_objects_iterable(
        self, timestamp: int, where: Clause | None = None, ignore_wip: bool = False
    ) -> Iterator[tuple[str, object]]:
        """See :meth:`TransactionalKeyValueStore._read_objects_iterable`.

        Reads through the index if the where clause is ``attribute == constant`` and there is an index on the
        attribute; any other read scans all objects. A read through the index yields its results in ascending order
        of the object ids (as strings) instead of the order of the store. It never looks at objects that are no
        candidates, so it does not raise where the scan raises for such an object (e.g. one without the attribute).
        """
        index: KeyValueStore[object, str] | None = self._index_for(where)
        if index is None:
            yield from super()._read_objects_iterable(
                timestamp, where, ignore_wip=ignore_wip
            )
            return

        # the index names the candidates: every object with an indexed version that has the constant, each id once
        # and sorted, as a fixed order keeps the checksum of the brute force validation independent of the order in
        # which the versions entered the index (get is a generator that raises KeyError for a value that no version
        # has, so only this line is guarded):
        try:
            candidate_ids: list[str] = sorted(set(index.get(where.constant)))
        except KeyError:
            return

        # the snapshot decides: keep a candidate only if its version visible at <timestamp> exists and matches:
        object_id: str
        for object_id in candidate_ids:
            _object: object | None = self._get_visible_object_version(
                object_id, timestamp, ignore_wip=ignore_wip
            )
            if _object is not None and where.evaluate(_object):
                yield object_id, _object

    def _maintain_indexes(
        self,
        object_id: str,
        object_to_index: object = None,
        object_to_deindex: object = None,
    ) -> None:
        """Indexes and/or de-indexes the given versions of an object in all indexes.

        @param object_id: the object id of the object to maintain/reindex
        @param object_to_index: the new object version to be indexed in all existing indexes
        @param object_to_deindex: an old version of the object to be deindexed from all existing indexes. This can only
        happen when...
        1. pruning a committed version from the committed list (pruning not implemented yet)
        2. superseding a wip-entry from the same TA, i.e. the TA is updating and/or deleting the object multiple times
        3. aborting a transaction
        """

        # in every index, add the new version and remove the old one, if given (the other versions stay indexed):
        for index in self.indexes_by_name.values():
            if object_to_index is not None:
                IndexedTransactionalKeyValueStore._index_object(
                    index.index,
                    index.index_properties.attribute,
                    object_id,
                    object_to_index,
                )
            if object_to_deindex is not None:
                IndexedTransactionalKeyValueStore._deindex_object(
                    index.index,
                    index.index_properties.attribute,
                    object_id,
                    object_to_deindex,
                )

    def _load(self, object_id: str, _object: object) -> None:
        """See :meth:`TransactionalKeyValueStore._load`.

        After delegating to the base implementation, indexes the new committed version in all indexes.
        """
        # store the object as a committed version (raises if the object_id exists already, before any index work):
        super()._load(object_id, _object)

        # index the stored copy like every other version:
        self._maintain_indexes(
            object_id,
            object_to_index=IndexedTransactionalKeyValueStore._object_of(
                self.key_value_store[object_id].committed[-1]
            ),
        )

    def update_object(self, object_id: str, updated_object: object, TA_id: int) -> None:
        """See :meth:`TransactionalKeyValueStore.update_object`.

        After delegating to the base implementation, maintains all indexes for the change: the new object version
        is indexed and any superseded work-in-progress version of the same transaction is de-indexed.
        """

        # 1. get the existing wip entry if there is one (an insert of a new object_id has none yet):
        wip_entry: VersionedKeyValueStore.VersionEntry | None = (
            self.key_value_store[object_id].wip
            if object_id in self.key_value_store
            else None
        )

        # the object of that wip entry (None for no wip entry or a delete marker):
        existing_wip_entry_object: object | None = (
            IndexedTransactionalKeyValueStore._object_of(wip_entry)
        )

        # 2. call super method to update the object_id as before:
        super().update_object(object_id, updated_object, TA_id)

        # post condition: the committed list of the KVStoreEntry of this object_id is unchanged
        # (only the wip entry was updated and must exist):
        assert self.key_value_store[object_id].wip is not None

        # 3. get the NEW object version visible to this TA_id (no copy required):
        new_object: object = self._get_visible_object_version(object_id, TA_id)

        # 4. finally, maintain all indexes for this change:
        # index the new version; de-index only a superseded wip version of this TA (committed versions stay indexed):
        self._maintain_indexes(
            object_id,
            object_to_index=new_object,
            object_to_deindex=existing_wip_entry_object,
        )

    def delete_object(self, object_id: str, TA_id: int) -> None:
        """See :meth:`TransactionalKeyValueStore.delete_object`.

        After delegating to the base implementation, de-indexes a superseded work-in-progress version of the same
        transaction (if any) from all indexes.
        """

        # 1. get the existing wip entry if it exists:
        wip_entry: VersionedKeyValueStore.VersionEntry | None = self.key_value_store[
            object_id
        ].wip
        # the object of that wip entry (None for no wip entry or a delete marker):
        existing_wip_entry_object: object | None = (
            IndexedTransactionalKeyValueStore._object_of(wip_entry)
        )

        # 2. call kv store method to delete the object_id (which actually adds a wip entry marking the deleted object):
        super().delete_object(object_id, TA_id)

        # 3. if we overwrote an existing wip entry, maintain all indexes for this object_id:
        if existing_wip_entry_object is not None:
            self._maintain_indexes(
                object_id,
                object_to_index=None,  # a delete marker carries no object to index
                object_to_deindex=existing_wip_entry_object,
            )
