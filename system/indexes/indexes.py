"""Simple index implementation backed by a Python dictionary."""

from typing import Iterator

from system.interfaces.indexing.Index import KeyValueStore, PutInfo


class PythonDictionaryIndex[Key, Value](KeyValueStore[Key, Value]):
    """A simple key-value store implemented using a Python dictionary (yes, a Python dictionary is a key/value
    store). Supports duplicates by mapping a key to a list of Values, i.e. multiple values can be associated with the
    same key.
    """

    def __init__(self):
        """Initializes an empty index backed by a Python dictionary that maps each key to a list of values,
        so that multiple values can be associated with the same key.
        """
        self.index: dict[Key, list[Value]] = dict[Key, list[Value]]()

    def size(self) -> int:
        """See :meth:`Index.size`."""
        return len(self.index)

    def put(self, key: Key, value: Value) -> PutInfo | None:
        """See :meth:`Index.put`.

        Appends the value to the list stored for the key, so duplicates are kept rather than overwritten.
        """
        self.index.setdefault(key, []).append(value)

    def delete(self, key: Key, value: Value = None) -> None:
        """See :meth:`Index.delete`.

        Removes the given value from the list stored for the key and drops the key entirely once its last
        value has been removed. Raises ``KeyError`` if the key or the value is not present.
        """
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
        """See :meth:`Index.flush`.

        No-op: a Python dictionary lives in volatile memory and is not backed by persistent storage. Raises
        ``KeyError`` if the given key is not present.
        """
        if key not in self.index:
            raise KeyError(f"Key {key} not found")

        # no action needed, as we are using a Python dictionary which is not backed by persistent storage
        pass

    def show(self) -> None:
        """See :meth:`Index.show`.

        Prints the underlying dictionary.
        """
        print(self.index)

    def get(self, key: Key) -> Iterator[Value]:
        """See :meth:`PointQueryMixIn.get`.

        Raises ``KeyError`` if the key is not present.
        """
        if key not in self.index:
            raise KeyError(f"Key {key} not found")

        for el in self.index[key]:
            yield el
