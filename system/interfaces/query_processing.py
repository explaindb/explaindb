from abc import ABC, abstractmethod
from typing import Iterator, Self

import deprecation

from system.operators import Tuple


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


class Operator(ABC):
    """
    Abstract operator interface to construct QEPs.
    """

    def __init__(self, parent: Self | None, children: list[Self] | None):
        self.parent = parent
        self.children = children

    def set_parent(self, parent: Self) -> None:
        self.parent = parent

    @abstractmethod
    def interpret_open(self) -> None:
        """
        Interpreter: `open()` method in push-based iterator model, i.e., initializes the operator.
        """
        raise NotImplementedError

    @abstractmethod
    def interpret_next(self, tup: Tuple) -> None:
        """
        Interpreter: `next()` method in push-based iterator model, i.e., processes the given tuple and
        optionally pushes the next tuple to the parent operator.
        :param tup: Pushed tuple to process.
        """
        raise NotImplementedError

    @abstractmethod
    def interpret_close(self) -> None:
        """
        Interpreter: `close()` method in push-based iterator model, i.e., closes the operator.
        """
        raise NotImplementedError

    @abstractmethod
    def compile(self, emit: str = None) -> str:
        """
        Compiler: Compiles the QEP rooted at `self` into Python code.
        :param emit: Parent code to emit.
        :return: Compiled QEP.
        """
        raise NotImplementedError

    @abstractmethod
    def dump(self, indent: int = 0) -> None:
        """
        Prints the QEP rooted at `self`.
        :param indent: Indentation level.
        """
        raise NotImplementedError

    @staticmethod
    def indent_emit_(emit: str, n: int = 1) -> str:
        """
        Indents the given code to emit.
        :param emit: Code to emit.
        :param n: Indentation level.
        :return: Indented code to emit.
        """
        indent = "    " * n
        return f"\n{indent}".join(emit.split("\n"))

    @staticmethod
    def indent_(n: int = 1) -> str:
        """
        Creates an indentation.
        :param n: Indentation level.
        :return: Indentation.
        """
        return " " * n
