from __future__ import annotations

import copy
import pprint
from dataclasses import dataclass
from itertools import chain
from typing import Dict, Iterator

from system.interfaces.indexing.Index import KeyValueStore, PutInfo


class HashableDict(dict):
    """A hashable dictionary class that can be used as a key in a dictionary. In particular, you can create a set of
    these dictionaries."""

    def __hash__(self):
        return hash(tuple(sorted(self.items())))


class VersionedKeyValueStore(KeyValueStore[str, object]):
    """A versioned store managing key/value mappings.
    On the slides we this store a "key value store".
    """

    @dataclass
    class VersionEntry:
        """A class representing a version entry in the store, i.e. an entry of a single object/value
        plus validity information, i.e. when the object was created/updated/deleted."""

        # valid from start until the next version in the list of committed entries
        # this is used to determine the visible version of the object for a given transaction
        # start: while in the wip-list used to signal which TA is working on this object
        # start: when committed used to signal when the object was committed (this is NEVER the same thing!)
        start_validity: int

        # the value of the object
        value: object

        # was this entry deleted?
        deleted: bool = False

    # TODO:: could refactor KVStoreEntry.wip with a type like this:
    # @dataclass
    # class WIPEntry:

    # TA_id: int

    # kv_store_entry: KeyValueStore.ValueEntry

    @dataclass
    class KVStoreEntry:
        """A class representing a key value store entry."""

        # list of committed versions of the object
        committed: list[VersionedKeyValueStore.VersionEntry]

        # optional (SINGLE!) work in progress entry
        wip: VersionedKeyValueStore.VersionEntry | None = None

        def __iter__(self):
            """Returns an iterator over the committed versions plus the wip entry if it exists."""
            return chain(
                self.committed.__iter__(), [self.wip] if self.wip is not None else []
            )

    def __init__(self, persistence_layer: KeyValueStore = None):
        """
        :param persistence_layer: Constructor for the VersionedKeyValueStore class.
        """

        # the actual data kept by this store:
        # a mapping from an object_id (which is a string to allow for prefixes) to a list of versions
        # we keep a mapping from object_id_prefix + object_id to KVStoreEntry
        # in other words: we may have MULTIPLE committed versions valid at different points in time
        # (if they were not garbage collected yet due to ongoing reading TAs)
        # plus AT MOST ONE optional work in progress (wip) entry, i.e. an object currently being modified by an
        # ongoing transaction

        self.persistence_layer: KeyValueStore = persistence_layer
        self.key_value_store: Dict[str, VersionedKeyValueStore.KVStoreEntry] = {}

    def size(self) -> int:
        """Returns the number of objects_ids mapped by the store."""
        return len(self.key_value_store)

    def put(self, object_id: str, _object: object) -> None | PutInfo:
        """Inserts (puts) a new object_id->_object mapping into the store overwriting any existing mapping.

        Note that the object is copied before it is stored in the store to avoid accidental modifications of the object
        outside the store.

        The data is recorded as a committed version with a start timestamp of 0.
        So this put is NOT transactional, it is just a simple insert bypassing any transactional semantics of the store.
        You get transactional semantics by using the TransactionalKeyValueStore.

        @param object_id: the object id
        @param _object: the object to use as the value
        """
        if object_id in self.key_value_store:
            raise Exception(f"object {object_id} already exists in the store")

        self.key_value_store[object_id] = VersionedKeyValueStore.KVStoreEntry(
            committed=[
                VersionedKeyValueStore.VersionEntry(
                    start_validity=0, value=copy.deepcopy(_object)
                )
            ],
            wip=None,
        )

    def get(self, object_id: str) -> Iterator[object]:
        """Returns the values associated with the given key as in iterator. Note that the iterator is NOT STABLE, i.e.
        it may change if the underlying data changes concurrently.

        @param object_id: the key used in this store
        @return: an iterator of the values associated with the given key
        """

        if object_id not in self.key_value_store:
            raise Exception(f"object {object_id} not found in the store")

        # get the most recent committed version of the object available:
        # note: deleted entry not considered here
        yield self.key_value_store[object_id].committed[-1].value

    def delete(self, object_id: str, _object: object = None) -> None:
        """Deletes the object with the given object_id.

        @param object_id: the object id
        @param _object: the object to use as the value
        """
        assert _object is None

        if object_id not in self.key_value_store:
            raise Exception(f"object {object_id} not found in the store")

        # create a new entry for the kv store that marks the object as deleted:
        new_entry: VersionedKeyValueStore.VersionEntry = (
            VersionedKeyValueStore.VersionEntry(
                start_validity=0, value=None, deleted=True
            )
        )

        # add the new entry to the kv store as committed:
        self.key_value_store[object_id].committed.append(new_entry)

    def flush(self, object_id: int | None = None) -> None:
        """Persists all changes, i.e. any changes done so far in volatile memory only are now made durable.

        @param object_id: if given, only the object with the given object_id is flushed, otherwise all objects are
        flushed.
        """
        pass

    def show(self) -> None:
        """Shows the content of the store."""
        pp = pprint.PrettyPrinter(depth=3)
        pp.pprint(self.key_value_store)
