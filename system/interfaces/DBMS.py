from abc import ABC

from system.interfaces.query_processing.query_processing import (
    QueryableComponent,
    QueryOptimizer,
)
from system.interfaces.stores import ACIDStore, QEPQueryableACIDStore
from system.interfaces.indexing.Index import KeyValueStore


class DBMS(ACIDStore, QueryableComponent, ABC):
    """DataBase Management System interface (DBMS)

    A DBMS is a decorator for an ACID store that adds query processing capabilities (cf. decorator design pattern).

    A DBMS may use a persistence layer different from the one used in the QEP_queryable_ACID_store. This may be useful for
    persisting data temporarily outside MVCC, e.g. for query processing to store temporary data/intermediate results.
    """

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
