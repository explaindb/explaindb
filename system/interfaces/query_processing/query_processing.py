from abc import ABC, abstractmethod
from typing import Iterator

import deprecation


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
