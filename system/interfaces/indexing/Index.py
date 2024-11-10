from abc import abstractmethod, ABC
from dataclasses import dataclass

from system.query_processing import Clause


@dataclass(frozen=True)
class IndexProperties:
    """A class representing metadata of an index."""

    # the attribute that is indexed
    attribute: str
    # the operator supported by this index
    # TODO: this should be extended to a a list of operators
    # TODO: clarify/integrate with the two MixIns below
    operator: str


class Index[Key, Value](ABC):
    """An API representing an index."""

    @abstractmethod
    def size(self) -> int:
        """Returns the number of keys mapped by this index."""
        pass

    @abstractmethod
    def put(self, key: Key, value: Value) -> None:
        """Inserts (puts) a new key->value mapping into the store overwriting any existing mapping.

        Note that the value is copied before it is stored in the store to avoid accidental modifications of the value
        outside the index.

        @param key: the key
        @param value: the value to associate with the key
        """

        pass

    @abstractmethod
    def delete(self, key: Key, value: Value) -> None:
        """Deletes the key and its associated value from the index.

        @param key: the key
        """

        pass

    @abstractmethod
    def flush(self, key: Key | None = None) -> None:
        """Persists all changes, i.e. any changes done so far in volatile memory only are now made durable.

        @param key: if given, only the key/value pair is flushed, otherwise all key/value-mappings are
        flushed.
        """
        pass

    @abstractmethod
    def bulkload(self, data: list[Value], key_prefix: str = ""):
        """Bulkloads the given list of values into the index. Inserts (puts) new key->value mappings
        into the store overwriting any existing mapping.

        Notice that we DO copy the values, so modifying them outside the index will NOT accidentally affect the
        data in the index.

        @param data: a list of data values
        @param key_prefix: a prefix to be added as prefix to the object ids, default is an empty string
        """

        pass

    @abstractmethod
    def show(self) -> None:
        """Shows the content of the store."""

        pass


class PointQueryMixIn[Key, Value](ABC):
    @abstractmethod
    def get(self, key: Key) -> Value:
        """Returns the value associated with the given object_id.

        @param key: the key
        @return: the value
        """
        pass


class PredicateQueryMixIn[Key, Value](ABC):
    @abstractmethod
    def get_all(self, where: Clause) -> list[Value]:
        """Returns all values that satisfy the given where clause.

        @param where: the condition
        @return: a list of values
        """

        pass


class KeyValueStore[Key, Value](Index[Key, Value], PointQueryMixIn[Key, Value], ABC):
    """An interface for a store managing key/value mappings."""

    pass


class AbstractBTree[Key, Value](
    Index[Key, Value],
    PointQueryMixIn[Key, Value],
    PredicateQueryMixIn[Key, Value],
    ABC,
):
    pass
