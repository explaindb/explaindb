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
