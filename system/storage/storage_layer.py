from __future__ import annotations
from system.interfaces.indexing.Index import KeyValueStore


class StorageLayer[Address, StorageUnit](KeyValueStore[Address, StorageUnit]):
    """A layer in a storage hierarchy, example incarnations of this are: DRAM, any L1, L2, L<whatever> cache, NVRAM,
    SSD, disk, tape, a CDN in a network, etc."""

    def __init__(
        self,
        max_capacity: int,
        name: str = "StorageLayer",
        layer_below: StorageLayer[Address, StorageUnit] | None = None,
    ):
        """Create a new storage layer with the given capacity, name, as well optionally a reference to the layer below.

        @param max_capacity: The maximum number of key-value pairs that can be stored in this layer.
        @param name: The name of this storage layer.
        @param layer_below: The storage layer below this one in the hierarchy. Can be None.
        """
        super().__init__()
        self.max_capacity: int = max_capacity
        self._name: str = name
        self.layer_below: StorageLayer[Address, StorageUnit] | None = layer_below
        self.storage: dict[Address, StorageUnit] = dict[Address, StorageUnit]()

        # the set of keys that are fixed in this storage layer and cannot be evicted:
        self.fixed: set[Address] = set[Address]()

    def get(self, address: Address) -> StorageUnit:
        """Get the value associated with the given key. If the key is not found in this storage layer, we will ask the
        layer below if it has the key and put it in this layer if found."""

        # do we have this address in our storage?
        if address not in self.storage:
            # ask the layer below if it exists:
            if self.layer_below is not None:
                res: StorageUnit = self.layer_below.get(address)
                self.put(address, res)
            else:
                raise KeyError(f"Key {address} not found in {self._name}")

        return self.storage[address]

    def put(self, address: Address, storage_unit: StorageUnit):
        """Store a new key-value pair in this storage layer.
        This implementation will overwrite any previous mapping for the given key.
        """

        if self.size() >= self.max_capacity:
            # evict some data to the layer below to make room for the new mapping:
            elements_evicted: int = self.evict()
            if elements_evicted == 0:
                raise ValueError(
                    f"Cannot store new key-value pair {address} -> {storage_unit} in {self._name} as eviction failed."
                )

        self.storage[address] = storage_unit

    def fix(self, address: Address):
        """Fix the key-value pair in this storage layer, i.e. this mapping may not be evicted anymore"""

        self.fixed.add(address)

    def unfix(self, address: Address):
        """Unfixes the key-value pair in this storage layer, i.e. this mapping may again be evicted"""

        self.fixed.remove(address)

    def choose_eviction_candidate(self) -> Address:
        """Choose a key to evict from this storage layer. This implementation chooses a random key to evict
        (which is stupid and just done here for educational purposes: a real implementation would have a more
        sophisticated eviction policy like LRU, LFU, etc.).
        """
        # TODO: implement a real eviction policy here
        # TODO: refactor to use strategy pattern
        return max(self.storage.keys())  # max key to have stability in tests

    def evict(self) -> int:
        """Evict some data from this storage layer to the layer below to make room for new data.

        @return: The number of key-value pairs evicted from this storage layer.
        """
        # if we have a layer below, evict some data to it:
        if self.layer_below is not None:
            # evict a key:
            key_to_evict: Address = self.choose_eviction_candidate()

            if key_to_evict in self.fixed:
                raise ValueError(
                    f"Cannot evict key {key_to_evict} as it is fixed in {self._name}"
                )
            value_to_evict: StorageUnit = self.get(key_to_evict)
            # TODO: actually only needed if we changed the value in self
            self.layer_below.put(key_to_evict, value_to_evict)
            self.delete(key_to_evict)

            return 1

        return 0

    def size(self) -> int:
        return len(self.storage)

    def delete(self, key: Address, value: StorageUnit | None = None) -> None:
        del self.storage[key]

    def flush(self, key: Address | None = None) -> None:
        raise NotImplementedError

    def show(self) -> None:
        print(f"Storage Layer: {self._name}")
        print(self.storage)
