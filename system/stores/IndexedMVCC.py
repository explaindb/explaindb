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

            # delete tne entry from the index:
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
        """Creates an index on the store with the given name. Adds the metadata to the catalog and bulkloads the index

        @param index_name: the name of the index
        @param attribute: the attribute to create the index on
        @param operator: the operator to use for the index
        """
        if index_name in self.indexes_by_name:
            raise Exception(f"index {index_name} already exists")

        # only equality indexes are supported at the moment:
        if operator not in ["="]:
            raise Exception(f"operator {operator} not supported")

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
        """Drops the index with the given name.

        @param index_name: the name of the index to drop
        """
        if index_name not in self.indexes_by_name:
            raise Exception(f"index {index_name} does not exist")

        entry: IndexedTransactionalKeyValueStore.IndexCatalogueEntry = (
            self.indexes_by_name[index_name]
        )
        del self.indexes_by_name[index_name]
        del self.indexes_by_properties[entry.index_properties]

    def abort_transaction(self, TA_id: int) -> None:
        """Aborts the given transaction and removes all changes made by this transaction from the system.

        @param TA_id: the transaction id of the transaction to be aborted
        """

        # iterate over all wip entries of this TA, i.e. all objects that were updated by this TA but not yet committed:
        # -> for each object_id in the write set of this TA:
        object_id: str
        kv_entry: VersionedKeyValueStore.KVStoreEntry
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
        """Returns a list of suitable indexes for the given clause.

        @param attribute: the attribute of the clause
        @param operator: the operator of the clause
        @return: a list of suitable indexes
        """

        # predicate to check for suitability of an index:
        # TODO: well,yes, we could directly use the index here:
        def is_suitable(index_properties: IndexProperties) -> bool:
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
        """Updates the entry and maintains all indexes.

        @param object_id: the object id of the object to be updated
        @param updated_object: the updated object, i.e. the new value to be associated with the object_id
        @param TA_id: the transaction id of the transaction that is updating (or trying to update) the object
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
        # no need to pass the old object version as we are not going to de-index it:
        self._maintain_indexes(
            object_id,
            object_to_index=new_object,
            object_to_deindex=existing_wip_entry_object,
        )

    def delete_object(self, object_id: str, TA_id: int) -> None:
        """Deletes the entry for <object_id> and maintains all indexes.

        @param object_id: the object id of the object to be deleted
        @param TA_id: the transaction id of the transaction that is deleting (or trying to delete) the object
        @return: True if this object overwrote an already existing wip entry, False otherwise
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
