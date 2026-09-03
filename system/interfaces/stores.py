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

"""Abstract ACID store interfaces: ACID, indexed, and QEP-queryable stores."""

from abc import ABC
from typing import Iterator

from system.interfaces.indexing.Index import KeyValueStore, IndexProperties
from system.interfaces.query_processing.query_processing import QEPQueryable


class ACIDStore(ABC):
    """Interface for an ACID store"""

    def __init__(self, persistence_layer: KeyValueStore):
        """Initialize the ACID store with a persistence layer, i.e. the layer that actually stores the data."""
        self.persistence_layer: KeyValueStore = persistence_layer

    def begin_transaction(self) -> int:
        """Starts a new transaction and returns its transaction id.
        Also adds a new entry with metadata for this transaction in the transaction dictionary.
        """
        pass

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


class IndexedACIDStore(ACIDStore, ABC):
    """Interface for an indexed ACID store"""

    def create_index(self, index_name: str, attribute: str, operator: str) -> None:
        """Creates an index on the store with the given name. Adds the metadata to the catalog and bulkloads the index

        @param index_name: the name of the index
        @param attribute: the attribute to create the index on
        @param operator: the operator to use for the index
        """

    def drop_index(self, index_name: str) -> None:
        """Drops the index with the given name.

        @param index_name: the name of the index to drop
        """
        pass

    def get_suitable_indexes(
        self, attribute: str, operator: str
    ) -> Iterator[IndexProperties]:
        """Returns a list of suitable indexes for the given clause.

        @param attribute: the attribute of the clause
        @param operator: the operator of the clause
        @return: a list of suitable indexes
        """


class QEPQueryableIndexedACIDStore(QEPQueryable, IndexedACIDStore, ABC):
    """Interface for a QEP-queryable indexed ACID store"""

    pass
