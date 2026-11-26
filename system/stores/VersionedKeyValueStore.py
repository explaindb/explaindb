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

"""Versioned (copy-on-write) key-value store."""

from __future__ import annotations

import copy
import pprint
from abc import ABC
from dataclasses import dataclass
from itertools import chain
from typing import Dict, Iterator

from system.interfaces.indexing.Index import KeyValueStore, PutInfo

from pydantic import BaseModel


class HashableDict(dict):
    """A hashable dictionary class that can be used as a key in a dictionary. In particular, you can create a set of
    these dictionaries."""

    # dict sets __hash__ to None, as a dict can change; this class is hashable on purpose:
    def __hash__(self):  # pyright: ignore[reportIncompatibleVariableOverride]
        """Hashes the dictionary by its sorted ``(key, value)`` items, so that two dictionaries
        with equal contents hash equally and instances can be used as set members or dictionary keys.
        """
        return hash(tuple(sorted(self.items())))


class VersionedKeyValueStore(KeyValueStore[str, object]):
    """A versioned store managing key/value mappings."""

    class VersionEntry(ABC, BaseModel):
        """An abstract class representing a version entry in the store, i.e. an entry of a single object/value
        plus start_validity information, i.e. when the object was created or updated."""

        # start_validity of the entry
        start_validity: int

    class UpdateEntry(VersionEntry):
        """A class representing an update or creation entry in the store, i.e. an entry of a single object/value
        plus start_validity information, i.e. when the object was updated or created."""

        # the value of the object, i. the updated value/object
        value: object

    class DeleteEntry(VersionEntry):
        """A class representing a delete version entry in the store, i.e. just the start_validity information,
        i.e. since when the object is considered deleted."""

    # TODO:: could refactor KVStoreEntry.wip with a type like this:
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

    def __init__(self, persistence_layer: KeyValueStore | None = None):
        """Initialize the versioned store.

        :param persistence_layer: the underlying persistence layer used to make the data durable.
        """

        # the actual data kept by this store:
        # a mapping from an object_id (which is a string to allow for prefixes) to a list of versions
        # we keep a mapping from object_id_prefix + object_id to KVStoreEntry
        # in other words: we may have MULTIPLE committed versions valid at different points in time
        # (if they were not garbage collected yet due to ongoing reading TAs)
        # plus AT MOST ONE optional work in progress (wip) entry, i.e. an object currently being modified by an
        # ongoing transaction

        self.persistence_layer: KeyValueStore | None = persistence_layer
        self.key_value_store: Dict[str, VersionedKeyValueStore.KVStoreEntry] = {}

    def size(self) -> int:
        """See :meth:`Index.size`."""
        return len(self.key_value_store)

    # the parameters are named object_id (as in the transactional operations of the store) and _object, not key
    # and value as in Index:
    def put(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, object_id: str, _object: object
    ) -> None | PutInfo:
        """See :meth:`Index.put`.

        Non-transactional insert: the object is deep-copied and recorded as a single committed version with
        start timestamp 0, bypassing the store's transactional semantics (use
        :class:`~system.stores.MVCC.TransactionalKeyValueStore` for those). Raises if the object_id already exists.
        """
        if object_id in self.key_value_store:
            raise KeyError(f"object {object_id} already exists in the store")

        self.key_value_store[object_id] = VersionedKeyValueStore.KVStoreEntry(
            committed=[
                VersionedKeyValueStore.UpdateEntry(
                    start_validity=0, value=copy.deepcopy(_object)
                )
            ],
            wip=None,
        )

    # the parameter is named object_id (not key as in PointQueryMixIn), as in the transactional operations of the store:
    def get(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, object_id: str
    ) -> Iterator[object]:
        """See :meth:`PointQueryMixIn.get`.

        Yields only a deep copy of the value of the most recent committed version (like put, which stores a deep copy),
        so a caller that changes it does not change the store. Raises KeyError, when the returned iterator is advanced,
        not at the call, if the object_id is not present, or if it has no committed value: its most recent committed
        version is a delete marker, or it has no committed version at all, as an insert of a transaction of
        :class:`~system.stores.MVCC.TransactionalKeyValueStore` leaves it before the transaction commits or after it
        aborts.
        """

        if object_id not in self.key_value_store:
            raise KeyError(f"object {object_id} not found in the store")

        # get the most recent committed version of the object, None if it has no committed version:
        committed: list[VersionedKeyValueStore.VersionEntry] = self.key_value_store[
            object_id
        ].committed
        newest: VersionedKeyValueStore.VersionEntry | None = (
            committed[-1] if committed else None
        )

        # a delete marker or no committed version at all: the object has no value to yield:
        if not isinstance(newest, VersionedKeyValueStore.UpdateEntry):
            raise KeyError(f"object {object_id} has no committed value in the store")

        # a deep copy, so that a caller that changes it does not change the committed version:
        yield copy.deepcopy(newest.value)

    # the parameters are named object_id (as in the transactional operations of the store) and _object (which
    # must be None), not key and value as in Index:
    def delete(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, object_id: str, _object: object = None
    ) -> None:
        """See :meth:`Index.delete`.

        Non-transactional delete: requires ``_object`` to be None and appends a delete marker as a committed
        version with start timestamp 0. Raises if the object_id is not present.
        """
        assert _object is None

        if object_id not in self.key_value_store:
            raise KeyError(f"object {object_id} not found in the store")

        # create a new entry for the kv store that marks the object as deleted:
        new_entry: VersionedKeyValueStore.DeleteEntry = (
            VersionedKeyValueStore.DeleteEntry(start_validity=0)
        )

        # add the new entry to the kv store as committed:
        self.key_value_store[object_id].committed.append(new_entry)

    # the parameter is named object_id (not key as in Index), as in the transactional operations of the store:
    def flush(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, object_id: str | None = None
    ) -> None:
        """See :meth:`Index.flush`.

        No-op: this store keeps its data in volatile memory only and is not backed by persistent storage.
        """

    def show(self) -> None:
        """See :meth:`Index.show`.

        Pretty-prints the underlying key-value store.
        """
        pp = pprint.PrettyPrinter(depth=3)
        pp.pprint(self.key_value_store)
