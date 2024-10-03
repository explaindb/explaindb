from abc import abstractmethod, ABC
from typing import Iterator

import deprecation


class DBMS(ABC):
    """Simplified interface of a DBMS"""

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


class QEP(ABC):
    """Query Execution Plan"""

    @abstractmethod
    def __init__(self):
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


class Store(ABC):
    """Store interface
    TODO: Add more methods to this interface as needed.
    TODO: integrate with MVCC after merging MR 7
    """

    @abstractmethod
    def execute_query(self, qep: QEP) -> Iterator[object]:
        """Execute a query execution plan.

        @param qep: The query execution plan to execute
        @return: The result of the query as a list of objects. The objects can be of any type.
        """
        pass


class PyDBMS(DBMS):
    def __init__(self, store: Store, query_optimizer: QueryOptimizer):
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
