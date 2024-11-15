from abc import ABC
from typing import Iterator

from system.interfaces.query_processing.query_processing import (
    QueryableComponent,
    QueryOptimizer,
)
from system.interfaces.stores import (
    ACIDStore,
    QEPQueryableIndexedACIDStore,
    IndexedACIDStore,
)
from system.interfaces.indexing.Index import KeyValueStore, IndexProperties


class DBMS(IndexedACIDStore, QueryableComponent, ABC):
    """DataBase Management System interface (DBMS)

    A DBMS is a decorator for an indexed ACID store that adds query processing capabilities (cf. decorator design pattern).

    A DBMS may use a persistence layer different from the one used in the QEP_queryable_indexed_ACID_store. This may be
    useful for persisting data temporarily outside MVCC, e.g. for query processing to store temporary data/intermediate
    results.
    """

    def __init__(
        self,
        QEP_queryable_indexed_ACID_store: QEPQueryableIndexedACIDStore,
        persistence_layer: KeyValueStore,
        query_optimizer: QueryOptimizer,
    ):
        """Initialize the DBMS with a store and a query optimizer.

        @param QEP_queryable_indexed_ACID_store: The indexed store to use
        @param persistence_layer: The persistence layer to use for durability
        @param query_optimizer: The query optimizer to use
        """

        ACIDStore.__init__(self, persistence_layer)
        self.QEP_queryable_ACID_store: QEPQueryableIndexedACIDStore = (
            QEP_queryable_indexed_ACID_store
        )
        self.query_optimizer: QueryOptimizer = query_optimizer

    def create_index(self, index_name: str, attribute: str, operator: str) -> None:
        """Creates an index on the store with the given name. Adds the metadata to the catalog and bulkloads the index

        @param index_name: the name of the index
        @param attribute: the attribute to create the index on
        @param operator: the operator to use for the index
        """
        self.QEP_queryable_ACID_store.create_index(index_name, attribute, operator)

    def drop_index(self, index_name: str) -> None:
        """Drops the index with the given name.

        @param index_name: the name of the index to drop
        """
        self.QEP_queryable_ACID_store.drop_index(index_name)

    def get_suitable_indexes(
        self, attribute: str, operator: str
    ) -> Iterator[IndexProperties]:
        """Returns a list of suitable indexes for the given clause.

        @param attribute: the attribute of the clause
        @param operator: the operator of the clause
        @return: a list of suitable indexes
        """
        return self.QEP_queryable_ACID_store.get_suitable_indexes(attribute, operator)
