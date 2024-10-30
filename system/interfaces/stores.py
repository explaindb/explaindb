from abc import ABC, abstractmethod
from dataclasses import dataclass

from system.interfaces.query_processing.query_processing import QEPQueryable


class KeyValueStore(ABC):
    """An interface for a store managing key/value mappings."""

    @abstractmethod
    def size(self) -> int:
        """Returns the number of objects_ids mapped by the store."""
        pass

    @abstractmethod
    def put(self, object_id: str, _object: object) -> None:
        """Inserts (puts) a new object_id->_object mapping into the store overwriting any existing mapping.

        Note that the object is copied before it is stored in the store to avoid accidental modifications of the object
        outside the store.

        The data is recorded as a committed version with a start timestamp of 0.
        So this put is NOT transactional, it is just a simple insert bypassing the transactional semantics of the store.

        @param object_id: the object id
        @param _object: the object to store
        """

        pass

    @abstractmethod
    def get(self, object_id: str) -> object:
        """Returns the object with the given object_id.

        @param object_id: the object id
        @return: the object
        """

        pass

    @abstractmethod
    def delete(self, object_id: str) -> None:
        """Deletes the object with the given object_id.

        @param object_id: the object id
        """

        pass

    @abstractmethod
    def flush(self, object_id: int | None = None) -> None:
        """Persists all changes, i.e. any changes done so far in volatile memory only are now made durable.

        @param object_id: if given, only the object with the given object_id is flushed, otherwise all objects are
        flushed.
        """
        pass

    @abstractmethod
    def bulkload(self, data: list[object], object_id_prefix: str = ""):
        """Bulkloads the given list of data objects into the store. Inserts (puts) a new object_id->_object mappings
        into the store overwriting any existing mapping.

        Notice that we DO copy the data objects, so modifying them outside the store will NOT accidentally affect the
        data in the store.

        @param data: a list of data objects
        @param object_id_prefix: a prefix to be added as prefix to the object ids, default is an empty string
        """

        # we use <object_id_prefix> to allow for multiple bulkloads into the same key value store:
        # like that we can easily mimic different tables in a database
        # Notice, if you bulkloaded before with the same prefix, an exception is thrown.

        pass

    @abstractmethod
    def show(self) -> None:
        """Shows the content of the store."""

        pass


class ACIDStore(ABC):
    """Interface for an ACID store"""

    def __init__(self, persistence_layer: KeyValueStore):
        """Initialize the ACID store with a persistence layer, i.e. the layer that actually stores the data."""
        self.persistence_layer: KeyValueStore = persistence_layer

    def begin_transaction(self) -> int:
        """Starts a new transaction and returns its transaction id.
        Also adds a new entry with metadata for this transaction in the transaction dictionary.
        """
        pass

    def commit_transaction(self, TA_id: int) -> None:
        """Commit a transaction.

        @param TA_id: The id of the transaction to commit
        """
        pass

    def abort_transaction(self, TA_id: int) -> None:
        """Abort a transaction.

        @param TA_id: The id of the transaction to abort
        """
        pass

    def update_object(self, object_id: str, updated_object: object, TA_id: int) -> None:
        """Update an object.

        @param object_id: The id of the object to update
        @param updated_object: The updated object
        @param TA_id: The id of the transaction to update the object in
        """
        pass

    def delete_object(self, object_id: str, TA_id: int) -> None:
        """Delete an object.

        @param object_id: The id of the object to delete
        @param TA_id: The id of the transaction to delete the object in
        """
        pass


class QEPQueryableACIDStore(QEPQueryable, ACIDStore, ABC):
    """Interface for a QEP-queryable ACID store"""

    pass
