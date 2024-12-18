from dataclasses import dataclass
from functools import total_ordering


@total_ordering
@dataclass(eq=False)
class Person:
    name: str
    birthday: str

    def __eq__(self, other):
        return self.name == other.name

    def __lt__(self, other):
        return self.name > other.name


@total_ordering
@dataclass(eq=False)
class Book:
    title: str
    author: str
    price: float

    def __eq__(self, other):
        return self.title == other.title

    def __lt__(self, other):
        return self.title > other.title


@dataclass(eq=False)
class Order:
    person_name: str
    book_title: str

    def __eq__(self, other):
        return (
            self.person_name == other.person_name
            and self.book_title == other.book_title
        )


@dataclass(eq=False)
class Address:
    id: int
    city: str
    street: str
    house_number: int

    def __eq__(self, other):
        return self.id == other.id
