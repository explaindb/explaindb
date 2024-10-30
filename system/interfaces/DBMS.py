from abc import ABC

from system.interfaces.query_processing.query_processing import (
    QueryInterface,
    QueryOptimizer,
)
from system.interfaces.stores import ACIDStore, QEPQueryableACIDStore, KeyValueStore


class DBMS(QueryInterface, ACIDStore, ABC):
    """Database Management System interface"""

    def __init__(
        self,
        QEP_queryable_ACID_store: QEPQueryableACIDStore,
        persistence_layer: KeyValueStore,
        query_optimizer: QueryOptimizer,
    ):
        """Initialize the DBMS with a store and a query optimizer.

        @param QEP_queryable_ACID_store: The store to use
        @param persistence_layer: The persistence layer to use for durability
        @param query_optimizer: The query optimizer to use
        """
        ACIDStore.__init__(self, persistence_layer)
        self.QEP_queryable_ACID_store: QEPQueryableACIDStore = QEP_queryable_ACID_store
        self.query_optimizer: QueryOptimizer = query_optimizer
