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

"""Simple index implementation backed by a Python dictionary."""

from typing import Iterator

from system.interfaces.indexing.Index import KeyValueStore, PutInfo


class PythonDictionaryIndex[Key, Value](KeyValueStore[Key, Value]):
    """A simple key-value store implemented using a Python dictionary (yes, a Python dictionary is a key/value
    store). Supports duplicates by mapping a key to a list of Values, i.e. multiple values can be associated with the
    same key.
    """

    def __init__(self):
        """Initializes an empty index backed by a Python dictionary that maps each key to a list of values,
        so that multiple values can be associated with the same key.
        """
        self.index: dict[Key, list[Value]] = dict[Key, list[Value]]()

    def size(self) -> int:
        """See :meth:`Index.size`."""
        return len(self.index)

    def put(self, key: Key, value: Value) -> PutInfo | None:
        """See :meth:`Index.put`.

        Appends the value to the list stored for the key, so duplicates are kept rather than overwritten.
        """
        self.index.setdefault(key, []).append(value)

    def delete(self, key: Key, value: Value = None) -> None:
        """See :meth:`Index.delete`.

        Removes the given value from the list stored for the key and drops the key entirely once its last
        value has been removed. Raises ``KeyError`` if the key or the value is not present.
        """
        if key not in self.index:
            raise KeyError(f"Key {key} not found")

        # get value list:
        list_of_values = self.index[key]

        # key was found but value not available in list?
        if value not in list_of_values:
            raise KeyError(f"Value {value} not found for key {key}")

        # remove entry from index list:
        list_of_values.remove(value)

        # any other entry in list?
        if len(list_of_values) == 0:
            # then delete the key:
            del self.index[key]
        else:
            # otherwise update the index (not really needed, but for completeness):
            self.index[key] = list_of_values

    def flush(self, key: Key | None = None) -> None:
        """See :meth:`Index.flush`.

        No-op: a Python dictionary lives in volatile memory and is not backed by persistent storage. Raises
        ``KeyError`` if the given key is not present.
        """
        if key not in self.index:
            raise KeyError(f"Key {key} not found")

        # no action needed, as we are using a Python dictionary which is not backed by persistent storage

    def show(self) -> None:
        """See :meth:`Index.show`.

        Prints the underlying dictionary.
        """
        print(self.index)

    def get(self, key: Key) -> Iterator[Value]:
        """See :meth:`PointQueryMixIn.get`.

        Raises ``KeyError`` if the key is not present.
        """
        if key not in self.index:
            raise KeyError(f"Key {key} not found")

        yield from self.index[key]
