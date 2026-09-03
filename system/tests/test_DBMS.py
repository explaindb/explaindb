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

"""Tests for the PyDBMS implementation."""

import unittest

from system.DBMS import PyDBMS
from system.interfaces.DBMS import DBMS
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore


class DBMSTests(unittest.TestCase):
    def test_DBMS(self) -> None:
        object_store: VersionedKeyValueStore = VersionedKeyValueStore()
        dbms: DBMS = PyDBMS(
            QEP_queryable_indexed_ACID_store=None,  # the MVCC store
            persistence_layer=object_store,  # here an object store, but could be any other store like a file system
            query_optimizer=None,  # the query optimizer
        )
        self.assertIsInstance(dbms, DBMS)
        self.assertIsInstance(dbms, PyDBMS)
        self.assertTrue(hasattr(dbms, "query_optimizer"))
        self.assertTrue(hasattr(dbms, "QEP_queryable_ACID_store"))
        self.assertTrue(hasattr(dbms, "persistence_layer"))

        self.assertTrue(hasattr(dbms, "prepared_queries"))
        # self.assertIsInstance(dbms.query_optimizer, QueryOptimizer)
        # self.assertIsInstance(dbms.store, Store)


if __name__ == "__main__":
    unittest.main(
        argv=["ignored", "-v"],
        verbosity=2,
        exit=False,
    )
