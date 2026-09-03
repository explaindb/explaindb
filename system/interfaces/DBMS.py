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

"""Abstract interface for a DBMS."""

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
        """See :meth:`IndexedACIDStore.create_index`.

        Delegates to the wrapped QEP-queryable indexed ACID store.
        """
        self.QEP_queryable_ACID_store.create_index(index_name, attribute, operator)

    def drop_index(self, index_name: str) -> None:
        """See :meth:`IndexedACIDStore.drop_index`.

        Delegates to the wrapped QEP-queryable indexed ACID store.
        """
        self.QEP_queryable_ACID_store.drop_index(index_name)

    def get_suitable_indexes(
        self, attribute: str, operator: str
    ) -> Iterator[IndexProperties]:
        """See :meth:`IndexedACIDStore.get_suitable_indexes`.

        Delegates to the wrapped QEP-queryable indexed ACID store.
        """
        return self.QEP_queryable_ACID_store.get_suitable_indexes(attribute, operator)
