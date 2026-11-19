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

"""Storage-hierarchy layer abstraction (DRAM, caches, SSD, disk, ...) with address conversion."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod

from system.interfaces.indexing.Index import KeyValueStore


class AddressConversionStrategy[Address](ABC):
    """A strategy to split an address used by one storage layer into the address
    of the layer below plus an offset within the fetched storage unit."""

    @abstractmethod
    def split_address(self, address: Address) -> tuple[Address, Address]:
        """Split the given address into two parts.

        @param address: The address as seen by this storage layer.
        @return: A pair (layer_below_address, offset): the first element is the
            address to look up in the layer below (e.g. a page id); the second is
            the offset of the wanted sub-unit inside the fetched page. The offset
            must be accepted by ``int()``, and the page fetched from the layer
            below must support ``page[int(offset)]``.
        """
        raise NotImplementedError


class StorageLayer[Address, StorageUnit](KeyValueStore[Address, StorageUnit]):
    """A layer in a storage hierarchy, example incarnations of this are: DRAM, any L1, L2, L<whatever> cache, NVRAM,
    SSD, disk, tape, a CDN in a network, etc."""

    def __init__(
        self,
        max_capacity: int,
        name: str = "StorageLayer",
        layer_below: StorageLayer[Address, StorageUnit] | None = None,
        address_conversion_strategy: AddressConversionStrategy[Address] | None = None,
    ):
        """Create a new storage layer with the given capacity, name, as well optionally a reference to the layer below.

        @param max_capacity: The maximum number of key-value pairs that can be stored in this layer. Must be at
            least 1.
        @param name: The name of this storage layer.
        @param layer_below: The storage layer below this one in the hierarchy. Can be None. With an address
            conversion strategy, the layer below stores whole pages, not units of this layer's type.
        @param address_conversion_strategy: A strategy to convert addresses from one address space to another.
        @raise ValueError: if max_capacity is less than 1.
        """
        # a layer without a single slot could never store anything:
        if max_capacity < 1:
            raise ValueError(
                f"max_capacity of {name} must be at least 1, got {max_capacity}"
            )
        super().__init__()
        self.max_capacity: int = max_capacity
        self._name: str = name
        self.layer_below: StorageLayer[Address, StorageUnit] | None = layer_below
        self.address_conversion_strategy: AddressConversionStrategy[Address] | None = (
            address_conversion_strategy
        )
        self.storage: dict[Address, StorageUnit] = dict[Address, StorageUnit]()

        # the set of keys that are fixed in this storage layer and cannot be evicted:
        self.fixed: set[Address] = set[Address]()

    def get(self, address: Address) -> StorageUnit:
        """See :meth:`PointQueryMixIn.get`.

        Storage-hierarchy variant: returns the single stored unit for the
        address rather than an iterator. On a miss in this layer, the unit is
        fetched from the layer below; with an address conversion strategy, the
        page for the address prefix is fetched and only ``page[int(offset)]`` is
        kept. A deep copy is stored in this layer via :meth:`put`, which may
        evict another entry or raise ``ValueError``. Raises ``KeyError`` if the
        lookup misses in every layer down to the bottom one; with an address
        conversion strategy, the layer below is asked for the page address.
        """

        # do we have this address in the storage of this storage layer?
        if address not in self.storage:
            # ask the layer below if this address exists below:
            if self.layer_below is None:
                raise KeyError(f"Key {address} not found in {self._name}")

            res: StorageUnit | None = None
            prefix_address_for_layer_below: Address = address
            suffix_address_for_this_layer: Address = ""
            if self.address_conversion_strategy is not None:
                # convert the address to the addressing schema used by the layer below:
                prefix_address_for_layer_below, suffix_address_for_this_layer = (
                    self.address_conversion_strategy.split_address(address)
                )

            res = self.layer_below.get(prefix_address_for_layer_below)

            if self.address_conversion_strategy is not None:
                # store the result in this layer:
                self.put(
                    address, copy.deepcopy(res[int(suffix_address_for_this_layer)])
                )
            else:
                self.put(address, copy.deepcopy(res))

        return self.storage[address]

    def put(self, address: Address, storage_unit: StorageUnit):
        """See :meth:`Index.put`.

        Overwrites any previous mapping for the given key; the value is stored
        without copying. If the key is not stored here yet and this layer is at
        capacity, it first evicts one entry (see :meth:`evict`); a failed
        eviction raises ``ValueError``. Overwriting a key already stored here
        never evicts. With an address conversion strategy, evicted entries are
        dropped, so values put into this layer are lost on eviction.
        """

        if address not in self.storage and self.size() >= self.max_capacity:
            # evict some data to the layer below to make room for the new mapping:
            elements_evicted: int = self.evict()
            if elements_evicted == 0:
                raise ValueError(
                    f"Cannot store new key-value pair {address} -> {storage_unit} in {self._name} as eviction failed."
                )

        self.storage[address] = storage_unit

    def fix(self, address: Address):
        """Fix the key in this storage layer, i.e. this mapping is never evicted: :meth:`choose_eviction_candidate`
        skips fixed keys. The key need not be stored here; deleting it from this layer (:meth:`delete`) also unfixes
        it.
        """

        self.fixed.add(address)

    def unfix(self, address: Address):
        """Unfixes the key in this storage layer, i.e. this mapping may again be evicted. Raises
        ``KeyError`` if the key is not fixed."""

        self.fixed.remove(address)

    def choose_eviction_candidate(self) -> Address:
        """Choose a key to evict from this storage layer. This implementation always picks the largest key that is
        not fixed, so that tests are deterministic (which is stupid and just done here for educational purposes: a
        real implementation would have a more sophisticated eviction policy like LRU, LFU, etc.).

        @return: the largest key stored in this layer that is not fixed.
        @raise ValueError: if no key can be evicted, i.e. this layer is empty or every key stored here is fixed.
        """
        # TODO: implement a real eviction policy here
        # TODO: refactor to use strategy pattern
        # only keys that are not fixed may be evicted:
        candidates: list[Address] = [
            key for key in self.storage if key not in self.fixed
        ]
        if not candidates:
            raise ValueError(
                f"No key in {self._name} can be evicted: it is empty or all its keys are fixed"
            )
        return max(candidates)  # max key to have stability in tests

    def evict(self) -> int:
        """Evict the entry chosen by :meth:`choose_eviction_candidate` to make room for new data. Without an
        address conversion strategy, the entry is written to the layer below; with one, it is only dropped
        here, as the layer below holds the whole page.

        @return: 1 if an entry was evicted, 0 if there is no layer below (nothing is evicted then).
        @raise ValueError: if no key can be evicted (this layer is empty or every key stored here is fixed), or if
            writing the entry to the layer below fails (the entry then stays in this layer).
        """
        # evict only if there is a layer below:
        if self.layer_below is not None:
            # choose the key to evict (never a fixed one):
            key_to_evict: Address = self.choose_eviction_candidate()

            if self.address_conversion_strategy is not None:
                # Under a conversion strategy this layer only caches sub-units of
                # the pages held by the layer below (a read cache): the layer
                # below is authoritative. Evict by dropping the cached entry
                # locally -- writing a single extracted sub-unit back would
                # corrupt the whole page below.
                self.delete(key_to_evict)
            else:
                value_to_evict: StorageUnit = self.get(key_to_evict)
                # TODO: actually only needed if we changed the value in self
                self.layer_below.put(key_to_evict, value_to_evict)
                self.delete(key_to_evict)

            return 1

        return 0

    def size(self) -> int:
        """See :meth:`Index.size`.

        Counts only the entries held in this layer, not those in the layers
        below.
        """
        return len(self.storage)

    def delete(self, key: Address, value: StorageUnit | None = None) -> None:
        """See :meth:`Index.delete`.

        Removes the mapping from this layer's own storage only and unfixes the key
        (see :meth:`fix`); the ``value`` argument is ignored. Raises ``KeyError``
        if the key is not present here.
        """
        del self.storage[key]
        # a deleted key is no longer fixed, so it can be evicted once it is put again:
        self.fixed.discard(key)

    def flush(self, key: Address | None = None) -> None:
        """See :meth:`Index.flush`.

        Not implemented for this storage layer: always raises
        ``NotImplementedError``.
        """
        raise NotImplementedError

    def show(self) -> None:
        """See :meth:`Index.show`.

        Prints this layer's name followed by its raw storage dictionary.
        """
        print(f"Storage Layer: {self._name}")
        print(self.storage)
