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
