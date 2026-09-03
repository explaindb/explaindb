#
#    This is ExplainDB, educational database systems materials.
#
#    Copyright (C) 2026 Prof. Dr. Jens Dittrich, Saarland University
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
#

"""Abstract query-processing interfaces: QEP, queryable components, and query optimizer."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

import deprecation


class QEP(ABC):
    """Query Execution Plan"""

    # TODO: sync with existing QEP implementation

    @abstractmethod
    def __init__(self):
        """Initialize the query execution plan."""


class QEPQueryable(ABC):
    """A simplified interface of a component that can be queried using a QEP. In other words, a component that can
    execute a query execution plan."""

    @abstractmethod
    def execute_query(self, qep: QEP, TA_ID: int | None = None) -> Iterator[object]:
        """Execute a query execution plan.

        @param qep: The query execution plan to execute
        @param TA_ID: The TA_ID of the transaction that is executing the query. If not provided, the query is executed
        as a separate transaction, i.e. it will automatically be wrapped into a transaction.
        @return: The result of the query as an Iterator of objects. The objects can be of any type.
        """


class QueryableComponent(ABC):
    """A component that can be queried using textual queries. In other words, a component that can execute queries."""

    @abstractmethod
    @deprecation.deprecated(details="Use the prepare_query function instead!")
    def execute_unprepared_query(
        self, query: str, TA_ID: int | None = None
    ) -> Iterator[object]:
        """Execute a query, non-prepared version on a textual query string. DO NOT USE THIS METHOD. Only provided for
        backward compatability or cases where sanitizing the query is not required or done outside the DBMS.

        @param query: The query to execute as a string. Technically, we are not specifying the query language at this
        point.
        @param TA_ID: The TA_ID of the transaction that is executing the query. If not provided, the query is executed
        as a separate transaction, i.e. it will automatically be wrapped into a transaction.
        @return: The result of the query as an iterator of objects. The objects can be of any type.
        """

    def prepare_query(self, query: str, parameters: list[str]) -> int:
        """Prepare a query to be executed multiple times with different parameters.

        @param query: The query to execute as a string. Technically, we are not specifying the query language at this
        point.
        @param parameters: The parameters to use in the query
        @return: The id of the prepared query. This id can be used to execute the query multiple times with different
        parameters using method :func `execute_prepared_query`.
        """

    @abstractmethod
    def execute_prepared_query(
        self, query_id: int, parameters: dict[str, object], TA_ID: int | None = None
    ) -> Iterator[object]:
        """Execute a query, prepared version. Always use this method to execute a query.

        @param query_id: The id of the prepared query to execute
        @param parameters: The parameters to use in the query
        @param TA_ID: The TA_ID of the transaction that is executing the query. If not provided, the query is executed
        as a separate transaction, i.e. it will automatically be wrapped into a transaction.
        @return: The result of the query as an iterator of objects. The objects can be of any type.
        """

    @dataclass
    class QueryEntry:
        """A dataclass to hold the parameters of a prepared query and the transaction id of the transaction that is
        executing the query. This is used to execute multiple prepared queries with different parameters as a batch.
        """

        # the parameters to use in the query
        parameters: dict[str, object]

        # the transaction id of the transaction that is executing the query
        # if not provided, the query is executed as a separate transaction
        # i.e. it will automatically be wrapped into a transaction
        TA_ID: int = None

    def execute_prepared_queries(
        self, queries: dict[int, QueryEntry]
    ) -> dict[int, Iterator[object]]:
        """Execute multiple prepared queries with different parameters as a batch. Useful for multi-query
        processing and optimization (MQO). For the moment, we simply call the method :func `execute_prepared_query` for
        each query id, parameters, and TA_ID. However, this method can be overwritten to do real MQO.

        @param queries: A dictionary of prepared query ids and QueryEntries. The keys are the query ids and the
        values is the QueryEntry for this prepared query.

        @return: A dictionary of query ids and the result of the query as an iterator of objects. The objects can be of
        any type.
        """
        return {
            query_id: self.execute_prepared_query(
                query_id, query_entry.parameters, query_entry.TA_ID
            )
            for query_id, query_entry in queries.items()
        }


class QueryOptimizer(ABC):
    """Query Optimizer interface"""

    @abstractmethod
    def create_QEP(self, query: str) -> QEP:
        """Create a query execution plan (QEP) from the query string.
        @param query: The query to create a plan for
        @return: The QEP
        """

    @abstractmethod
    def prepare_query(self, query: str, parameters: list[str]) -> QEP:
        """Prepare a query to be executed multiple times with different parameters.
        @param query: The query to prepare
        @param parameters: The list of parameters the query has.
        @return: The query execution plan (QEP).
        """

    @abstractmethod
    def bind_parameters(
        self, prepared_query_QEP: QEP, parameters: dict[str, object]
    ) -> QEP:
        """Bind parameters to a prepared qep.

        @param prepared_query_QEP: The QEP of the prepared query to bind parameters to
        @param parameters: The parameters to bind
        @return: The QEP with the parameters bound
        """
