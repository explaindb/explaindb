"""Abstract indexing interfaces: Index, key-value store, B-tree, and point/range/predicate query mix-ins."""

from abc import abstractmethod, ABC
from dataclasses import dataclass
from typing import Iterator

from system.query_processing.predicates import Clause


@dataclass(frozen=True)
class IndexProperties:
    """A class representing metadata of an index."""

    # the attribute that is indexed
    attribute: str
    # the operator supported by this index
    # TODO: this should be extended to a a list of operators
    # TODO: clarify/integrate with the two MixIns below
    operator: str


@dataclass
class PutInfo:
    pass


class Index[Key, Value](ABC):
    """An API representing an index."""

    @abstractmethod
    def size(self) -> int:
        """Returns the number of keys mapped by this index."""
        pass

    @abstractmethod
    def put(self, key: Key, value: Value) -> None | PutInfo:
        """Adds (puts) a new key->value mapping into the store.

        Note that the value should be copied in your implementation before it is stored in the store to avoid
        accidental modifications of the value outside the index.

        @param key: the key
        @param value: the value to associate with the key
        @return: None or a PutInfo object
        """

        pass

    @abstractmethod
    def delete(self, key: Key, value: Value = None) -> None:
        """Deletes the key->value mapping from the index.

        @param key: the key
        @param value: the value to delete

        """

        pass

    @abstractmethod
    def flush(self, key: Key | None = None) -> None:
        """Persists all changes, i.e. any changes done so far in volatile memory only are now made durable.

        @param key: if given, only the key/value pair is flushed, otherwise all key/value-mappings are
        flushed.
        """
        pass

    def bulkload(self, input_data: Iterator[tuple[Key, Value]]) -> None:
        """Bulkloads the given list of key->value mappings into the index.

        Notice that we DO copy the values, so modifying them outside the index will NOT accidentally affect the
        data in the index.

        @param input_data: an iterator of key-values pairs to be loaded into the index; in this implementation, for
        each pair (key, value), we simply call put(key, value) to add the key-value pair to the index.
        """
        for item in input_data:
            self.put(item[0], item[1])

    @abstractmethod
    def show(self) -> None:
        """Shows the content of the index."""

        pass


class PointQueryMixIn[Key, Value](ABC):
    """An interface mixing in point queries."""

    @abstractmethod
    def get(self, key: Key) -> Iterator[Value]:
        """Returns the values associated with the given key as in iterator. Note that the iterator is NOT STABLE, i.e.
        it may change if the underlying data changes concurrently.

        @param key: the key
        @return: an iterator of the values associated with the given key
        """
        pass


class RangeQueryMixIn[Key, Value](ABC):
    @abstractmethod
    def get_all_in_range(self, min_key: Key, max_key: Key) -> Iterator[Value]:
        """Returns all values that satisfy the given where clause. Note that the iterator is NOT STABLE, i.e.
        it may change if the underlying data changes concurrently.

        @param min_key: the minimum key including
        @param max_key: the maximum key including

        @return: an iterator of values
        """
        pass


class PredicateQueryMixIn[Key, Value](ABC):
    """An interface mixing in range queries."""

    @abstractmethod
    def get_all(self, where: Clause) -> Iterator[Value]:
        """Returns all values that satisfy the given where clause. Note that the iterator is NOT STABLE, i.e.
        it may change if the underlying data changes concurrently.

        @param where: the condition
        @return: an iterator of values
        """

        pass


class KeyValueStore[Key, Value](Index[Key, Value], PointQueryMixIn[Key, Value], ABC):
    """An interface for an index additionally supporting point queries."""

    pass


class AbstractBTree[Key, Value](
    KeyValueStore[Key, Value],
    RangeQueryMixIn[Key, Value],
    ABC,
):
    """An abstract class representing a B-Tree, i.e. an index supporting both point and range queries."""

    pass
