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
"""Tests for query-plan code generation and operator execution."""

import pickle

from system.data_classes import *
from faker import Faker
import unittest
from unittest import mock

from system.query_processing.operators import (
    Scan,
    Filter,
    SHJ,
    Collect,
    Relation,
    SemiJ,
)

Faker.seed(42)
fake = Faker()

num_runs = 5
number_of_tuples = 1000


class MyTest(unittest.TestCase):
    @staticmethod
    def create_data() -> None:
        persons = [Person(fake.name(), fake.date()) for _ in range(number_of_tuples)]
        books = [
            Book(
                fake.sentence(),
                persons[i % number_of_tuples].name,
                fake.pyfloat(min_value=0, max_value=100, right_digits=2),
            )
            for i in range(number_of_tuples)
        ]
        with open("persons.pkl", "wb") as f:
            pickle.dump([vars(person) for person in persons], f)
        with open("books.pkl", "wb") as f:
            pickle.dump([vars(book) for book in books], f)

    @staticmethod
    def create_qep():
        scan_persons = Scan(
            "persons.pkl", fake.pyint(min_value=1, max_value=number_of_tuples)
        )
        scan_books = Scan(
            "books.pkl", fake.pyint(min_value=1, max_value=number_of_tuples)
        )
        filter_books = Filter(
            scan_books,
            f"price < {fake.pyfloat(min_value=0, max_value=100, right_digits=2)}",
        )
        join = SHJ(scan_persons, filter_books, "name", "author")
        return Collect(join)

    def test_codegen_results_end_to_end(self):
        for _ in range(num_runs):
            self.create_data()
            query_plan = self.create_qep()

            query_plan.interpret_open()
            res1 = query_plan.result

            code = query_plan.compile()
            loc = {"result": None}
            exec(code, {}, loc)
            res2 = loc["result"]

            self.assertListEqual(res1, res2)


class OperatorTest(unittest.TestCase):
    @staticmethod
    def create_data():
        persons = [
            Person("John", "1992-17-03"),
            Person("Bob", "1987-08-05"),
            Person("Jane", "1968-12-12"),
        ]
        orders = [
            Order("John", "Echoes of Time"),
            Order("Jane", "Echoes of Time"),
            Order("Bob", "Shadows of Dawn"),
            Order("Bob", "Echoes of Dawn"),
            Order("John", "Shadows of Dawn"),
            Order("Jane", "Beneath the Stars"),
        ]
        books = [
            Book("Forgotten Dreams", "Alice", 54.92),
            Book("Echoes of Time", "Marie", 44.09),
            Book("Shadows of Dawn", "Alan", 32.99),
            Book("Beneath the Stars", "Ted", 78.21),
        ]
        return persons, orders, books

    def test_relation(self):
        persons, _, _ = self.create_data()
        persons_tuples = [
            ("John", "1992-17-03"),
            ("Bob", "1987-08-05"),
            ("Jane", "1968-12-12"),
        ]
        rel_persons = Collect(Relation("persons", [vars(e) for e in persons]))
        rel_persons.interpret_open()
        self.assertListEqual(rel_persons.result, persons_tuples)

    def test_semij(self):
        _, orders, books = self.create_data()
        result_tuples = [
            ("Echoes of Time", "Marie", 44.09),
            ("Shadows of Dawn", "Alan", 32.99),
            ("Beneath the Stars", "Ted", 78.21),
        ]
        rel_orders = Relation("orders", [vars(e) for e in orders])
        rel_books = Relation("books", [vars(e) for e in books])
        semi_join = SemiJ(rel_books, rel_orders, "title", "book_title")
        query = Collect(semi_join)
        query.interpret_open()
        self.assertListEqual(query.result, result_tuples)

    def test_interpret_close_propagates_to_leaves(self):
        """Pins that ``interpret_close`` propagates DOWN through a join to both leaf relations.

        Would fail if the fix regressed and a leaf ``Relation.interpret_close`` raised the old
        ``AssertionError``, or if close ever stopped reaching every leaf under an inner operator.
        """
        _, orders, books = self.create_data()
        rel_orders = Relation("orders", [vars(e) for e in orders])
        rel_books = Relation("books", [vars(e) for e in books])
        join = SHJ(rel_books, rel_orders, "title", "book_title")
        query = Collect(join)
        query.interpret_open()

        # wrap each leaf's interpret_close to record whether close reaches the leaves
        with mock.patch.object(
            rel_orders, "interpret_close", wraps=rel_orders.interpret_close
        ) as orders_close, mock.patch.object(
            rel_books, "interpret_close", wraps=rel_books.interpret_close
        ) as books_close:
            # must not raise (before the fix the leaf Relation.interpret_close raised AssertionError)
            query.interpret_close()

        # close must reach BOTH leaves exactly once
        orders_close.assert_called_once()
        books_close.assert_called_once()

    def test_shj_build_and_probe_end_to_end(self):
        """Pins that ``SHJ.interpret_open`` opens build+probe and actually emits the joined rows.

        Would fail if the symmetric hash join regressed to only opening one child and thus
        produced an empty result (the pre-fix ``[]`` bug).
        """
        _, orders, books = self.create_data()
        rel_orders = Relation("orders", [vars(e) for e in orders])
        rel_books = Relation("books", [vars(e) for e in books])
        join = SHJ(rel_books, rel_orders, "title", "book_title")
        query = Collect(join)
        query.interpret_open()

        # independently derive the expected join via a plain nested-loop join over the raw data;
        # SHJ probes orders against books and emits order_dict | book_dict, which Collect turns
        # into (person_name, book_title, title, author, price)
        expected = [
            (
                order.person_name,
                order.book_title,
                book.title,
                book.author,
                book.price,
            )
            for order in orders
            for book in books
            if order.book_title == book.title
        ]

        # a hash join does not guarantee output order, so compare order-insensitively
        self.assertCountEqual(query.result, expected)
        # before the fix the join opened no probe input and produced []
        self.assertTrue(query.result)


if __name__ == "__main__":
    # only execute a specific test class
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
