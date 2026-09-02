"""Sample data classes (Person, Book, Order, Address) used as example relations."""

from dataclasses import dataclass
from functools import total_ordering


@total_ordering
@dataclass(eq=False)
class Person:
    """A person with a name and a birthday, used as a sample relation."""

    name: str
    birthday: str

    def __eq__(self, other):
        """Two persons are equal iff their ``name`` fields are equal (``birthday`` is ignored)."""
        return self.name == other.name

    def __lt__(self, other):
        """Order persons by ``name`` in reverse (descending) alphabetical order."""
        return self.name > other.name


@total_ordering
@dataclass(eq=False)
class Book:
    """A book with a title, author, and price, used as a sample relation."""

    title: str
    author: str
    price: float

    def __eq__(self, other):
        """Two books are equal iff their ``title`` fields are equal (``author`` and ``price`` are ignored)."""
        return self.title == other.title

    def __lt__(self, other):
        """Order books by ``title`` in reverse (descending) alphabetical order."""
        return self.title > other.title


@dataclass(eq=False)
class Order:
    """An order linking a person to a book by name and title, used as a sample relation."""

    person_name: str
    book_title: str

    def __eq__(self, other):
        """Two orders are equal iff both ``person_name`` and ``book_title`` are equal."""
        return (
            self.person_name == other.person_name
            and self.book_title == other.book_title
        )


@dataclass(eq=False)
class Address:
    """A postal address identified by ``id``, used as a sample relation."""

    id: int
    city: str
    street: str
    house_number: int

    def __eq__(self, other):
        """Two addresses are equal iff their ``id`` fields are equal (all other fields are ignored)."""
        return self.id == other.id
