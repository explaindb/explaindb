from system.data_classes import *
from faker import Faker
import unittest


Faker.seed(42)
fake = Faker()

num_runs = 5
number_of_tuples = 1000


class MyTest(unittest.TestCase):
    @staticmethod
    def create_data():
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
        for i in range(num_runs):
            self.create_data()
            query_plan = self.create_qep()

            query_plan.interpret_open()
            res1 = query_plan.result

            code = query_plan.compile()
            loc = {"result": None}
            exec(code, dict(), loc)
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


if __name__ == "__main__":
    # only execute a specific test class
    unittest.main(argv=["ignored", "-v"], verbosity=2, exit=False)
