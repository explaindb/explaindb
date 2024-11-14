from system.interfaces.indexing.Index import KeyValueStore
from system.query_processing.predicates import Clause


class PythonDictionaryWithoutDuplicates[Key, Value](KeyValueStore[Key, Value]):
    """A simple key-value store implemented using a Python dictionary (yes, a Python dictionary is a key/value
    store). Does not support duplicates"""

    def __init__(self):
        self.index: dict[Key, Value] = dict[Key, Value]()

    def size(self) -> int:
        return len(self.index)

    def put(self, key: Key, value: Value) -> None:
        self.index[key] = value

    def delete(self, key: Key, value: Value = None) -> None:
        if key not in self.index:
            raise KeyError(f"Key {key} not found")
        del self.index[key]

    def flush(self, key: Key | None = None) -> None:
        if key not in self.index:
            raise KeyError(f"Key {key} not found")
        pass

    def bulkload(self, data: list[Value], key_prefix: str = "") -> None:
        for i in range(len(data)):
            self.put(i, data[i])

    def show(self) -> None:
        print(self.index)

    def get(self, key: Key) -> Value:
        if key not in self.index:
            raise KeyError(f"Key {key} not found")

        return self.index[key]


class PythonDictionaryWithDuplicates[Key, Value](
    PythonDictionaryWithoutDuplicates[Key, list[Value]]
):
    """A simple key-value store implemented using a Python dictionary (yes, a Python dictionary is a key/value
    store). Supports duplicates by mapping a key to a list of Values, i.e. multiple values can be associated with the
    same key.
    """

    def put(self, key: Key, value: Value) -> None:
        """Inserts (puts) a new key->value mapping into the store overwriting any existing mapping."""
        self.index.setdefault(key, []).append(value)

    def delete(self, key: Key, value: Value = None) -> None:
        """Deletes the key and all its associated values."""
        assert value is not None

        if key not in self.index:
            raise KeyError(f"Key {key} not found")

        # remove entry from index list
        list_of_values = self.index[key]
        list_of_values.remove(value)
        # any other entry?
        if len(list_of_values) == 0:
            # then delete the key
            del self.index[key]
        else:
            self.index[key] = list_of_values

    def get(self, key: Key) -> list[Value]:
        """Returns the list of values associated with the given key."""
        if key not in self.index:
            raise KeyError(f"Key {key} not found")

        return self.index[key]

    def get_all(self, where: Clause) -> list[Value]:
        """Returns all values that satisfy the given where clause. IN this case a list of all lists of values that
        satisfy the condition."""
        return [
            value
            for key in self.index
            for value in self.index[key]
            if where.evaluate(value)
        ]
