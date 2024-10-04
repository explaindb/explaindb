from abc import abstractmethod, ABC
from typing import Iterator

import deprecation


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


class QEP(ABC):
    """Query Execution Plan"""

    # TODO: sync with existing QEP implementation

    @abstractmethod
    def __init__(self):
        pass


class Queryable(ABC):
    """Simplified interface of a queryable object"""

    @abstractmethod
    def execute_query(self, qep: QEP) -> Iterator[object]:
        """Execute a query execution plan.

        @param qep: The query execution plan to execute
        @return: The result of the query as a list of objects. The objects can be of any type.
        """
        pass


class QueryableACIDStore(ACIDStore, Queryable, ABC):
    """Interface for a queryable ACID store"""

    pass


class QueryInterface(ABC):

    @abstractmethod
    @deprecation.deprecated(details="Use the prepare_query function instead!")
    def execute_query(self, query: str) -> Iterator[object]:
        """Execute a query, non-prepared version. DO NOT USE THIS METHOD. Only provided for backward compatability or
        cases for sanitizing the query is not required or done outside the DBMS.

        @param query: The query to execute as a string. Technically, we are not specifying the query language at this
        point.
        @return: The result of the query as a list of objects. The objects can be of any type.
        """
        pass

    def prepare_query(self, query: str) -> int:
        """Prepare a query to be executed multiple times with different parameters.

        @param query: The query to execute as a string. Technically, we are not specifying the query language at this
        point.
        @return: The id of the prepared query. This id can be used to execute the query multiple times with different
        parameters using method :func `execute_prepared_query`.
        """
        pass

    @abstractmethod
    def execute_prepared_query(
        self, query_id: int, parameters: dict[str, object]
    ) -> Iterator[object]:
        """Execute a query, prepared version. Always use this method to execute a query.

        @param query_id: The id of the prepared query to execute
        @param parameters: The parameters to use in the query

        """
        pass

    def execute_prepared_queries(
        self, query_ids_and_parameters: dict[int, dict[str, object]]
    ) -> dict[int, Iterator[object]]:
        """Execute multiple prepared queries with different parameters as a batch. Useful for multi-query
        processing and optimization (MQO). For the moment, we simply call the method :func `execute_prepared_query` for
        each query id and parameters. However, this method can be overwritten to do real MQO.

        @param query_ids_and_parameters: A dictionary of query ids and parameters. The keys are the query ids and the
        values are the parameters for the query.
        """
        return {
            query_id: self.execute_prepared_query(query_id, entry)
            for query_id, entry in query_ids_and_parameters.items()
        }


class DBMS(QueryInterface, ABC):
    """Database Management System interface"""

    pass


class QueryOptimizer(ABC):

    @abstractmethod
    def create_plan(self, query: str) -> QEP:
        """Create a query execution plan from the query string.
        @param query: The query to create a plan for
        @return: The QEP
        """
        pass

    @abstractmethod
    def prepare_query(self, query: str) -> QEP:
        """Prepare a query to be executed multiple times with different parameters.
        @param query: The query to prepare
        @return: The id of the prepared query as well as the QEP.
        """
        pass

    @abstractmethod
    def bind_parameters(
        self, prepared_query: object, parameters: dict[str, object]
    ) -> QEP:
        """Bind parameters to a prepared qep.

        @param prepared_query: The prepared query to bind parameters to
        @param parameters: The parameters to bind
        @return: The QEP with the parameters bound
        """
        pass


class PyDBMS(DBMS):
    """Python implementation of a DBMS"""

    def __init__(self, store: QueryableACIDStore, query_optimizer: QueryOptimizer):
        """Initialize the DBMS with a store and a query optimizer.

        @param store: The store to use
        @param query_optimizer: The query optimizer to use
        """

        self.store = store
        self.query_optimizer = query_optimizer

        # dict for prepared queries: query_id -> query
        self.prepared_queries = dict[int, QEP]()

        # counter for unique prepared query ids:
        self.prepared_queries_counter = 0

    def _get_next_prepared_query_id(self) -> int:
        """Get the next prepared query id"""

        ret: int = self.prepared_queries_counter
        self.prepared_queries_counter += 1
        return ret

    def execute_query(self, query: str) -> Iterator[object]:
        qep = self.query_optimizer.create_plan(query)
        return self.store.execute_query(qep)

    def prepare_query(self, query: str) -> int:
        prepared_query_id: int = self._get_next_prepared_query_id()
        self.prepared_queries[prepared_query_id] = self.query_optimizer.prepare_query(
            query
        )
        return prepared_query_id

    def execute_prepared_query(
        self, query_id: int, parameters: dict[str, object]
    ) -> Iterator[object]:

        if query_id not in self.prepared_queries:
            raise ValueError(f"No prepared QEP found for query id {query_id}.")

        # retrieve the prepared QEP:
        qep_without_bound_parameters: QEP = self.prepared_queries[query_id]

        # bind the parameters:
        qep_with_bound_parameters: QEP = self.query_optimizer.bind_parameters(
            qep_without_bound_parameters, parameters
        )

        # execute the query and return the result iterator:
        return self.store.execute_query(qep_with_bound_parameters)
