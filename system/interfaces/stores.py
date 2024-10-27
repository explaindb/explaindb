from abc import ABC

from system.interfaces.query_processing.query_processing import Queryable


class ACIDStore(ABC):
    """Interface for an ACID store"""

    def begin_transaction(self) -> int:
        """Starts a new transaction and returns its transaction id.
        Also adds a new entry with metadata for this transaction in the transaction dictionary.
        """

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


class QueryableACIDStore(Queryable, ACIDStore, ABC):
    """Interface for a queryable ACID store"""

    pass
