import unittest

from system.DBMS import PyDBMS
from system.interfaces.DBMS import DBMS
from system.stores.VersionedKeyValueStore import VersionedKeyValueStore


class DBMSTests(unittest.TestCase):
    def test_DBMS(self):
        object_store: VersionedKeyValueStore = VersionedKeyValueStore()
        dbms: DBMS = PyDBMS(
            QEP_queryable_ACID_store=None,  # the MVCC store
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
