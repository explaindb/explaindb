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
from collections.abc import MutableSequence
from typing import Any, Protocol, SupportsIndex, SupportsInt

from system.interfaces.indexing.Index import Index

# an offset within a page as returned by AddressConversionStrategy.split_address: anything that int() accepts,
# e.g. "3" or 3:
type Offset = str | SupportsInt | SupportsIndex


class _Comparable(Protocol):
    """A type whose values can be ordered with ``<``, e.g. ``str`` or ``int``: the addresses of a
    :class:`StorageLayer` must be comparable, as :meth:`StorageLayer.choose_eviction_candidate` picks the largest
    one."""

    def __lt__(self, other: Any, /) -> bool: ...


class AddressConversionStrategy[Address](ABC):
    """A strategy to split an address used by one storage layer into the address
    of the layer below plus an offset within the fetched storage unit."""

    @abstractmethod
    def split_address(self, address: Address) -> tuple[Address, Offset]:
        """Split the given address into two parts.

        @param address: The address as seen by this storage layer.
        @return: A pair (layer_below_address, offset): the first element is the
            address to look up in the layer below (e.g. a page id); the second is
            the offset of the wanted sub-unit inside the fetched page. The offset
            must be accepted by ``int()``, and the page fetched from the layer
            below must support ``page[int(offset)]``. For :meth:`StorageLayer.put`,
            which writes the unit into the page, a page must be a ``str`` (each
            unit is one character) or a mutable sequence such as a list; other
            pages that do not support item assignment, e.g. ``bytes`` or a tuple,
            raise ``TypeError`` there. Each unit
            of a page should have only one address: the upper layer caches every
            address on its own, so a put under one address does not change the
            copy cached under another address of the same unit.
        """
        raise NotImplementedError


def _page_with_unit[Unit](
    page: str | MutableSequence[Unit], offset: int, unit: Unit
) -> str | MutableSequence[Unit]:
    """Return a copy of the page in which the unit at the offset is replaced by the given unit; the given page itself
    is not changed.

    @param page: the page: a ``str``, whose units are its characters, or a mutable sequence such as a list.
    @param offset: the position of the unit in the page; a negative offset counts from the end, as in
        ``page[offset]``.
    @param unit: the new unit; for a ``str`` page, a single character.
    @return: the changed copy of the page.
    @raise IndexError: if the offset lies outside the page.
    @raise ValueError: if the page is a ``str`` and the unit is not a single character.
    """
    if isinstance(page, str):
        # a unit of a str page is one character: a longer or shorter unit would shift every later unit:
        if not isinstance(unit, str) or len(unit) != 1:
            raise ValueError(
                f"A unit of a str page must be a single character, got {unit!r}"
            )
        # map a negative offset to its position and reject an offset outside the page (slicing would not):
        position: int = offset + len(page) if offset < 0 else offset
        if not 0 <= position < len(page):
            raise IndexError(
                f"Offset {offset} lies outside the page of length {len(page)}"
            )
        # a str is immutable: build the new page from the text before and after the unit:
        return page[:position] + unit + page[position + 1 :]

    # change a copy of a mutable page, so that the page stored in the layer below changes only when it is put back:
    new_page: MutableSequence[Unit] = copy.copy(page)
    new_page[offset] = unit
    return new_page


class StorageLayer[Address: _Comparable, StorageUnit](Index[Address, StorageUnit]):
    """A layer in a storage hierarchy, example incarnations of this are: DRAM, any L1, L2, L<whatever> cache, NVRAM,
    SSD, disk, tape, a CDN in a network, etc."""

    def __init__(
        self,
        max_capacity: int,
        name: str = "StorageLayer",
        layer_below: StorageLayer[Address, Any] | None = None,
        address_conversion_strategy: AddressConversionStrategy[Address] | None = None,
    ) -> None:
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
        # the layer below stores units of this layer's type, or whole pages under an address conversion strategy
        # (hence Any):
        self.layer_below: StorageLayer[Address, Any] | None = layer_below
        self.address_conversion_strategy: AddressConversionStrategy[Address] | None = (
            address_conversion_strategy
        )
        self.storage: dict[Address, StorageUnit] = dict[Address, StorageUnit]()

        # the set of keys that are fixed in this storage layer and cannot be evicted:
        self.fixed: set[Address] = set[Address]()

    def get(self, key: Address) -> StorageUnit:
        """Returns the single unit stored under the key (an address).

        A storage layer returns one unit, not an iterator as :meth:`PointQueryMixIn.get` does, so StorageLayer is an
        :class:`Index` without the point-query mix-in. On a miss in this layer, the
        unit is fetched from the layer below; with an address conversion strategy, the
        page for the address prefix is fetched and only ``page[int(offset)]`` is
        kept. A deep copy is stored in this layer, which may evict another
        entry or raise ``ValueError``; filling the cache never writes the
        fetched unit or its page back to the layer below (only evicting another
        entry may write that entry there, see :meth:`evict`). Raises
        ``KeyError`` if the lookup misses in every layer down to the bottom one;
        with an address conversion strategy, the layer below is asked for the
        page address.
        """

        # do we have this address in the storage of this storage layer?
        if key not in self.storage:
            # ask the layer below if this address exists below:
            if self.layer_below is None:
                raise KeyError(f"Key {key} not found in {self._name}")

            prefix_address_for_layer_below: Address = key
            suffix_address_for_this_layer: Offset = ""
            if self.address_conversion_strategy is not None:
                # convert the address to the addressing schema used by the layer below:
                prefix_address_for_layer_below, suffix_address_for_this_layer = (
                    self.address_conversion_strategy.split_address(key)
                )

            # a unit of this layer's type, or a whole page under an address conversion strategy:
            res: Any = self.layer_below.get(prefix_address_for_layer_below)

            if self.address_conversion_strategy is not None:
                # store the result in this layer (without writing it back below):
                self._store(key, copy.deepcopy(res[int(suffix_address_for_this_layer)]))
            else:
                self._store(key, copy.deepcopy(res))

        return self.storage[key]

    def put(self, key: Address, value: StorageUnit) -> None:
        """See :meth:`Index.put`.

        Overwrites any previous mapping for the given key and stores a deep copy
        of the value, so later changes to the caller's object, also to objects
        nested inside it, do not change the stored value. If the key is not
        stored here yet and this layer is at capacity, it first evicts one entry
        (see :meth:`evict`); a failed eviction raises ``ValueError``.
        Overwriting a key already stored here never evicts.

        With an address conversion strategy and a layer below, put writes
        through: it splits the address, replaces the unit at the offset in a
        copy of the page that the layer below holds under the page address (see
        :meth:`AddressConversionStrategy.split_address` for what a page must
        support), puts the changed copy back into the layer below (whose put
        stores its own copy of the page) and then stores a copy of the unit
        here. Raises ``KeyError`` if no layer below holds the page,
        ``IndexError`` if the offset lies outside the page, and ``ValueError``
        if the page is a ``str`` and the unit is not a single character; no
        stored value changes then. If this layer then cannot make room for a new
        key (``ValueError``), the unit is not lost: the layer below already
        holds the changed page, from which a get fetches the unit once this
        layer has room again.
        """

        if (
            self.address_conversion_strategy is not None
            and self.layer_below is not None
        ):
            # write through: split the address into the page address below and the offset of the unit in the page
            # (int() rejects a malformed offset before anything is read or written):
            page_address, offset = self.address_conversion_strategy.split_address(key)
            position: int = int(offset)
            # replace the unit in a copy of the page and put the changed page back into the layer below:
            page: str | MutableSequence[StorageUnit] = self.layer_below.get(
                page_address
            )
            self.layer_below.put(page_address, _page_with_unit(page, position, value))

        # store a deep copy of the unit in this layer as well, so that later changes to the caller's object do not
        # change it:
        self._store(key, copy.deepcopy(value))

    def _store(self, key: Address, value: StorageUnit) -> None:
        """Store the value under the key in this layer only: unlike :meth:`put`, it never writes the value through
        to the layer below. :meth:`get` uses it to cache a unit fetched from the layer below.

        @param key: the key in this layer.
        @param value: the value to store; it is not copied here, as :meth:`put` and :meth:`get` already pass a copy.
        @raise ValueError: if the key is not stored here yet, this layer is full, and no entry can be evicted (see
            :meth:`evict`).
        """
        if key not in self.storage and self.size() >= self.max_capacity:
            # make room for the new mapping by evicting one entry (see evict):
            elements_evicted: int = self.evict()
            if elements_evicted == 0:
                raise ValueError(
                    f"Cannot store new key-value pair {key} -> {value} in {self._name} as eviction failed."
                )

        self.storage[key] = value

    def fix(self, address: Address) -> None:
        """Fix the key in this storage layer, i.e. this mapping is never evicted: :meth:`choose_eviction_candidate`
        skips fixed keys. The key need not be stored here; deleting it from this layer (:meth:`delete`) also unfixes
        it.
        """

        self.fixed.add(address)

    def unfix(self, address: Address) -> None:
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
        here, as the layer below already holds the current unit in its page (:meth:`put` writes through).

        @return: 1 if an entry was evicted, 0 if there is no layer below (nothing is evicted then).
        @raise ValueError: if no key can be evicted (this layer is empty or every key stored here is fixed), or if
            writing the entry to the layer below fails (the entry then stays in this layer).
        """
        # evict only if there is a layer below:
        if self.layer_below is not None:
            # choose the key to evict (never a fixed one):
            key_to_evict: Address = self.choose_eviction_candidate()

            if self.address_conversion_strategy is not None:
                # under a conversion strategy, put writes every unit through to its page in the layer below, so the
                # layer below already holds the current unit: drop the entry here only (putting the unit below under
                # this layer's address would add a stray entry there):
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
