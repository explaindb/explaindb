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

# Test modules use self-documenting method/class names and module-level
# fixtures, so pylint's naming and docstring checks are relaxed here.
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring
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
