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
from system.stores.MVCC import TransactionalKeyValueStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore


class IndexedTransactionalKeyValueStore(TransactionalKeyValueStore, IndexedACIDStore):
    """A fully transactional versioned (MVCC) key value store adding support for indexes."""

    @dataclass
    class IndexCatalogueEntry:
        """Entries used for the index catalog."""

        # the index properties of the index:
        index_properties: IndexProperties

        # the index itself:
        index: KeyValueStore[object, str]

    def __init__(self, use_brute_force_validation: bool = False):
        """Initialize the store and its (initially empty) index catalogues.

        :param use_brute_force_validation: if True, the underlying store uses the brute-force validation
            algorithm in the validation phase (see :class:`~system.stores.MVCC.TransactionalKeyValueStore`).
        """
        # a dictionary of indexes:
        super().__init__(use_brute_force_validation=use_brute_force_validation)

        # a dictionary mapping from the index name to (IndexProperties, Index):
        self.indexes_by_name: Dict[
            str, IndexedTransactionalKeyValueStore.IndexCatalogueEntry
        ] = dict[str, IndexedTransactionalKeyValueStore.IndexCatalogueEntry]()

        # a dictionary mapping from IndexProperties to the index name:
        self.indexes_by_properties: Dict[IndexProperties, str] = dict[
            IndexProperties, str
        ]()

    @staticmethod
    def _deindex_object(
        index: Index, attribute: str, object_id: str, old_object: object
    ) -> None:
        """De-indexes the object with the given object_id and object.
        @param index: the index to use for indexing
        @param attribute: the attribute to index
        @param object_id: the object id of the object to be indexed
        @param old_object: the old object version of the object to be indexed
        """
        # does the _object have that attribute:
        if hasattr(old_object, attribute):
            # only then we can add the object_id to the index:
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
        # does the _object have that attribute:
        if hasattr(new_object, attribute):
            # only then we can add the object_id to the index:
            # get the value of that attribute:
            attribute_value: object = getattr(new_object, attribute)

            # add an entry to the index:
            # here is where the inversion happens,
            # i.e. the index maps from the attribute value (key) of the object to the object_id (value)
            # whereas the store maps from the object_id (key) to the object (value)
            index.put(attribute_value, object_id)

    def create_index(self, index_name: str, attribute: str, operator: str) -> None:
        """See :meth:`IndexedACIDStore.create_index`.

        Only equality indexes (operator ``"="``) are supported; any other operator raises. Raises as well if an
        index with the given name already exists. The index is backed by a
        :class:`~system.indexes.indexes.PythonDictionaryIndex` and acts as a filter index, i.e. lookups return a
        superset of matches that still has to be post-filtered.
        """
        if index_name in self.indexes_by_name:
            raise KeyError(f"index {index_name} already exists")

        # only equality indexes are supported at the moment:
        if operator not in ["="]:
            raise NotImplementedError(f"operator {operator} not supported")

        # an index (to start only a python dict) maps from an attribute value to the list of object_ids where there is
        # at least one version in the committed list or the wip-entry qualifying (not all have to match)
        # This means, that every index is a filter index, i.e. it does not return the precise result set but a superset
        # of the result set which then has to be post-filtered.

        # So an index lookup works like this:
        # 1. call the index to get the object_ids with potential matches
        # 2. for each object_id returned, get the most recent visible version of the object to TA <TA_id> under
        # snapshot isolation
        # 3. check whether the object matches the where clause
        # 4. if it does, add it to the result set

        # add metadata to the catalog:
        index_properties: IndexProperties = IndexProperties(
            attribute=attribute, operator=operator
        )

        # the only type of index supported at the moment is a PythonDictionary (wrapping a python dict) with support
        # for duplicates:
        index: KeyValueStore[str, object] = PythonDictionaryIndex()
        self.indexes_by_name[index_name] = (
            IndexedTransactionalKeyValueStore.IndexCatalogueEntry(
                index_properties, index
            )
        )
        self.indexes_by_properties[index_properties] = index_name

        # bulkload the index:
        # get all (current) items from the store:
        # TODO: delegate to bulkload method of the index?
        object_id: str
        _object: object

        kv_entry: VersionedKeyValueStore.KVStoreEntry
        for object_id, kv_entry in self.key_value_store.items():

            version_entry: VersionedKeyValueStore.UpdateEntry
            for version_entry in kv_entry:
                IndexedTransactionalKeyValueStore._index_object(
                    index, attribute, object_id, version_entry.value
                )

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
            wip_entry: VersionedKeyValueStore.UpdateEntry = self.key_value_store[
                object_id
            ].wip
            assert wip_entry is not None
            assert wip_entry.start_validity == TA_id

            # get the old object version of the wip entry:
            old_object: object = wip_entry.value

            # maintain the indexes for this change, i.e. remove this wip entry from all indexes:
            self._maintain_indexes(
                object_id,
                object_to_index=None,  # we are deleting the object
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

    def _maintain_indexes(
        self,
        object_id: str,
        object_to_index: object = None,
        object_to_deindex: object = None,
    ) -> None:
        """Maintains (index de-indexes) the given entries for all indexes.

        @param object_id: the object id of the object to maintain/reindex
        @param object_to_index: the new object version to be indexed in all existing indexes
        @param object_to_deindex: an old version of the object to be deindexed from all existing indexes. This can only
        happen when...
        1. pruning a committed version from the committed list (pruning not implemeneted yet)
        2. superseding a wip-entry from the same TA, i.e. the TA is updating and/or deleting the object multiple times
        3. aborting a transaction
        """

        # update all indexes, i.e. call _reindex() for each index for the given object_id:
        # index the new object version only (recall: we are in an append-only store!):
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

    def update_object(self, object_id: str, updated_object: object, TA_id: int) -> None:
        """See :meth:`TransactionalKeyValueStore.update_object`.

        After delegating to the base implementation, maintains all indexes for the change: the new object version
        is indexed and any superseded work-in-progress version of the same transaction is de-indexed.
        """

        # pre-condition: this is not a delete operation: the object must exist in the store either in the commited list
        # or in the wip entry
        assert object_id in self.key_value_store

        # 1. get the existing wip entry if it exists:
        wip_entry: VersionedKeyValueStore.UpdateEntry = self.key_value_store[
            object_id
        ].wip

        existing_wip_entry_object: object = (
            wip_entry.value if wip_entry is not None else None
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
        wip_entry: VersionedKeyValueStore.UpdateEntry = self.key_value_store[
            object_id
        ].wip
        existing_wip_entry_object: object = (
            wip_entry.value if wip_entry is not None else None
        )

        # 2. call kv store method to delete the object_id (which actually adds a wip entry marking the deleted object):
        super().delete_object(object_id, TA_id)

        # 3. if we overwrote an existing wip entry, maintain all indexes for this object_id:
        if existing_wip_entry_object is not None:
            self._maintain_indexes(
                object_id,
                object_to_index=None,  # again: we keep all versions even under deletes!
                object_to_deindex=existing_wip_entry_object,
            )
