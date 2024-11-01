from abc import ABC

from system.interfaces.indexing.Index import Index, PointQueryMixIn
from system.interfaces.query_processing.query_processing import QEPQueryable


class KeyValueStore(Index, PointQueryMixIn, ABC):
    """An interface for a store managing key/value mappings."""

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
