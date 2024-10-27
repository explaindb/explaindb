import unittest

from system.DBMS import PyDBMS
from system.interfaces.DBMS import DBMS


class DBMSTests(unittest.TestCase):
    def test_DBMS(self):
        dbms: DBMS = PyDBMS(QEP_queryable_ACID_store=None, query_optimizer=None)
        self.assertIsInstance(dbms, DBMS)
        self.assertIsInstance(dbms, PyDBMS)
        self.assertTrue(hasattr(dbms, "query_optimizer"))
        self.assertTrue(hasattr(dbms, "store"))
        self.assertTrue(hasattr(dbms, "prepared_queries"))
        # self.assertIsInstance(dbms.query_optimizer, QueryOptimizer)
        # self.assertIsInstance(dbms.store, Store)


if __name__ == "__main__":
    unittest.main(
        argv=["ignored", "-v"],
        verbosity=2,
        exit=False,
    )
