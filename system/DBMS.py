"""Python DBMS implementation managing prepared queries, stores, and query optimization."""

from typing import Iterator

import deprecation

from system.interfaces.DBMS import DBMS
from system.interfaces.query_processing.query_processing import QEP, QueryOptimizer
from system.interfaces.stores import QEPQueryableIndexedACIDStore
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore


class PyDBMS(DBMS):
    """Python implementation of a DBMS"""

    def __init__(
        self,
        QEP_queryable_indexed_ACID_store: QEPQueryableIndexedACIDStore | None,
        persistence_layer: VersionedKeyValueStore,
        query_optimizer: QueryOptimizer | None,
    ):
        """Initialize the DBMS with a store and a query optimizer.

        @param QEP_queryable_indexed_ACID_store: The store to use
        @param persistence_layer: The persistence layer to use for durability
        @param query_optimizer: The query optimizer to use
        """
        super().__init__(
            QEP_queryable_indexed_ACID_store, persistence_layer, query_optimizer
        )

        # dict for prepared queries: query_id -> query
        self.prepared_queries: dict[int, QEP] = dict[int, QEP]()

        # counter for unique prepared query ids:
        self.prepared_queries_counter: int = 0

    def _get_next_prepared_query_id(self) -> int:
        """Get the next prepared query id"""

        ret: int = self.prepared_queries_counter
        self.prepared_queries_counter += 1
        return ret

    @deprecation.deprecated(details="Use the prepare_query function instead!")
    def execute_unprepared_query(
        self, query: str, TA_ID: int | None = None
    ) -> Iterator[object]:
        """See :meth:`QueryableComponent.execute_unprepared_query`."""

        qep = self.query_optimizer.create_QEP(query)
        return self.QEP_queryable_ACID_store.execute_query(qep, TA_ID)

    def prepare_query(self, query: str, parameters: list[str]) -> int:
        """See :meth:`QueryableComponent.prepare_query`."""

        prepared_query_id: int = self._get_next_prepared_query_id()
        self.prepared_queries[prepared_query_id] = self.query_optimizer.prepare_query(
            query, parameters
        )
        return prepared_query_id

    def execute_prepared_query(
        self, query_id: int, parameters: dict[str, object], TA_ID: int | None = None
    ) -> Iterator[object]:
        """See :meth:`QueryableComponent.execute_prepared_query`.

        Raises :class:`ValueError` if no prepared query is registered under ``query_id``.
        """

        if query_id not in self.prepared_queries:
            raise ValueError(f"No prepared QEP found for query id {query_id}.")

        # retrieve the prepared QEP:
        qep_without_bound_parameters: QEP = self.prepared_queries[query_id]

        # bind the parameters:
        qep_with_bound_parameters: QEP = self.query_optimizer.bind_parameters(
            qep_without_bound_parameters, parameters
        )

        # execute the query and return the result iterator:
        return self.QEP_queryable_ACID_store.execute_query(
            qep_with_bound_parameters, TA_ID
        )
