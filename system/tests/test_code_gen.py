from system.data_classes import *
from faker import Faker
from system.operators import *
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


if __name__ == "__main__":
    # only execute a specific test class
    unittest.main(argv=["ignored", "-v"], defaultTest="MyTest", verbosity=2, exit=False)
