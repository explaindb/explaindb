"""Tests for WHERE-clause predicates and query processing."""

import unittest
from dataclasses import dataclass

from system.query_processing.predicates import WHERE_Clause, Disjunction


@dataclass
class Stuff:
    a: int
    b: int


class QueryProcessingTest(unittest.TestCase):
    def test_where_clause(self):
        for _a in [10, "10"]:
            # Create a mock object with attributes
            stuff = Stuff(a=_a, b=20)

            # Create a WHERE clause
            where_clause = WHERE_Clause(attribute="a", operator="==", constant=_a)

            # Evaluate the WHERE clause against the mock object
            result = where_clause.evaluate(stuff)

            # Assert the result
            self.assertTrue(result)

            # Create a WHERE clause
            where_clause = WHERE_Clause(attribute="a", operator="==", constant=11)

            # Evaluate the WHERE clause against the mock object
            result = where_clause.evaluate(stuff)

            # Assert the result
            self.assertFalse(result)

    def test_disjunction(self):
        # Create mock objects
        stuff1 = Stuff(a=10, b=20)
        stuff2 = Stuff(a=30, b=40)
        stuff3 = Stuff(a=20, b=30)

        # Create WHERE clauses
        where_clause1 = WHERE_Clause(attribute="a", operator="==", constant=10)
        where_clause2 = WHERE_Clause(attribute="a", operator="==", constant=30)

        # Create a disjunction of the WHERE clauses
        disjunction = Disjunction(where_clause1, where_clause2)

        # Evaluate the disjunction against the mock objects
        result1 = disjunction.evaluate(stuff1)
        result2 = disjunction.evaluate(stuff2)

        # Assert the results
        self.assertTrue(result1)
        self.assertTrue(result2)

        # negative test
        result3 = disjunction.evaluate(stuff3)
        self.assertFalse(result3)


if __name__ == "__main__":
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
