from abc import ABC

from system.interfaces.query_processing import Queryable


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

    # TODO wait for merge request 7
    # def read_objects(
    #    self, TA_id: int, where: Clause = None, collect_read_clause: bool = True
    # ) -> list[tuple[str, object]]:

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


class QueryableACIDStore(ACIDStore, Queryable, ABC):
    """Interface for a queryable ACID store"""

    pass
