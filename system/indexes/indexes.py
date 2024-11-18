from typing import Iterator

from system.interfaces.indexing.Index import KeyValueStore


class PythonDictionaryIndex[Key, Value](KeyValueStore[Key, Value]):
    """A simple key-value store implemented using a Python dictionary (yes, a Python dictionary is a key/value
    store). Supports duplicates by mapping a key to a list of Values, i.e. multiple values can be associated with the
    same key.
    """

    def __init__(self):
        self.index: dict[Key, list[Value]] = dict[Key, list[Value]]()

    def size(self) -> int:
        return len(self.index)

    def put(self, key: Key, value: Value) -> None:
        """Inserts (puts) a new key->value mapping into the store overwriting any existing mapping."""
        self.index.setdefault(key, []).append(value)

    def delete(self, key: Key, value: Value = None) -> None:
        if key not in self.index:
            raise KeyError(f"Key {key} not found")

        # get value list:
        list_of_values = self.index[key]

        # key was found but value not available in list?
        if value not in list_of_values:
            raise KeyError(f"Value {value} not found for key {key}")

        # remove entry from index list:
        list_of_values.remove(value)

        # any other entry in list?
        if len(list_of_values) == 0:
            # then delete the key:
            del self.index[key]
        else:
            # otherwise update the index (not really needed, but for completeness):
            self.index[key] = list_of_values

    def flush(self, key: Key | None = None) -> None:
        if key not in self.index:
            raise KeyError(f"Key {key} not found")

        # no action needed, as we are using a Python dictionary which is not backed by persistent storage
        pass

    def show(self) -> None:
        print(self.index)

    def get(self, key: Key) -> Iterator[Value]:
        """Returns the values associated with the given key as in iterator. Note that the iterator is NOT STABLE, i.e.
        it may change if the underlying data changes concurrently.

        @param key: the key
        @return: an iterator of the values associated with the given key
        """
        if key not in self.index:
            raise KeyError(f"Key {key} not found")

        for el in self.index[key]:
            yield el
