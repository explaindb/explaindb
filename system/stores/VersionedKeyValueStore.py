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

    def __hash__(self):
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

        pass

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

    def __init__(self, persistence_layer: KeyValueStore = None):
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

        self.persistence_layer: KeyValueStore = persistence_layer
        self.key_value_store: Dict[str, VersionedKeyValueStore.KVStoreEntry] = {}

    def size(self) -> int:
        """See :meth:`Index.size`."""
        return len(self.key_value_store)

    def put(self, object_id: str, _object: object) -> None | PutInfo:
        """See :meth:`Index.put`.

        Non-transactional insert: the object is deep-copied and recorded as a single committed version with
        start timestamp 0, bypassing the store's transactional semantics (use
        :class:`~system.stores.MVCC.TransactionalKeyValueStore` for those). Raises if the object_id already exists.
        """
        if object_id in self.key_value_store:
            raise Exception(f"object {object_id} already exists in the store")

        self.key_value_store[object_id] = VersionedKeyValueStore.KVStoreEntry(
            committed=[
                VersionedKeyValueStore.UpdateEntry(
                    start_validity=0, value=copy.deepcopy(_object)
                )
            ],
            wip=None,
        )

    def get(self, object_id: str) -> Iterator[object]:
        """See :meth:`PointQueryMixIn.get`.

        Yields only the value of the most recent committed version; delete markers are not taken into account.
        Raises if the object_id is not present.
        """

        if object_id not in self.key_value_store:
            raise Exception(f"object {object_id} not found in the store")

        # get the most recent committed version of the object available:
        # note: deleted entry not considered here
        yield self.key_value_store[object_id].committed[-1].value

    def delete(self, object_id: str, _object: object = None) -> None:
        """See :meth:`Index.delete`.

        Non-transactional delete: requires ``_object`` to be None and appends a delete marker as a committed
        version with start timestamp 0. Raises if the object_id is not present.
        """
        assert _object is None

        if object_id not in self.key_value_store:
            raise Exception(f"object {object_id} not found in the store")

        # create a new entry for the kv store that marks the object as deleted:
        new_entry: VersionedKeyValueStore.DeleteEntry = (
            VersionedKeyValueStore.DeleteEntry(start_validity=0)
        )

        # add the new entry to the kv store as committed:
        self.key_value_store[object_id].committed.append(new_entry)

    def flush(self, object_id: int | None = None) -> None:
        """See :meth:`Index.flush`.

        No-op: this store keeps its data in volatile memory only and is not backed by persistent storage.
        """
        pass

    def show(self) -> None:
        """See :meth:`Index.show`.

        Pretty-prints the underlying key-value store.
        """
        pp = pprint.PrettyPrinter(depth=3)
        pp.pprint(self.key_value_store)
