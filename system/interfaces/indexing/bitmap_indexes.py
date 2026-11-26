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

"""Abstract interface for bitmap indexes."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Type, Iterator
from system.interfaces.bit_sequence import BitSequence, CompressedBitSequence
from system.indexes.bit_sequences import IntegerBitSequence, UncompressedBitSequence
from system.interfaces.indexing.Index import Index, PointQueryMixIn, RangeQueryMixIn


class BitmapIndex[Key, Value](
    Index[Key, Value], PointQueryMixIn[Key, Value], RangeQueryMixIn[Key, Value], ABC
):
    """
    Abstract base class for bitmap index structures that allow for efficient filtering.

    Every loaded key/value pair gets its own bit position, i.e. one bit per row as in the textbook: the bit sequence
    of a key has the bits of its pairs set. A value loaded under several keys, or the same pair loaded twice,
    occupies several positions.
    """

    def __init__(
        self,
        bit_sequence_type: Type[UncompressedBitSequence] = IntegerBitSequence,
        compression_type: Type[CompressedBitSequence] | None = None,
    ):
        """
        Initializes a bitmap structure.
        :param bit_sequence_type: The type of bit sequence to use.
        :param compression_type: The compression type to use. None if no compression should be used.
        """
        # Bit sequence Type to create new, uncompressed bit sequences
        self.uncompressed_bit_sequence_type: Type[UncompressedBitSequence] = (
            bit_sequence_type
        )

        # Maps each bit position to the value of the key/value pair loaded at that position
        self.position_to_value: list[Value] = []

        # The compression type to use during bulkloading, if desired
        if compression_type:
            self.use_compression: bool = True
            self.compression_type: Type[CompressedBitSequence] = compression_type
        else:
            self.use_compression: bool = False

    def _get_values_for_bit_sequence(
        self, bit_sequence: BitSequence
    ) -> Iterator[Value]:
        """
        This function iterates through all set bits in the bit sequence and yields the values represented by these bits.
        :param bit_sequence: The bit sequence to iterate through.
        :return: An iterator over the values represented by these bits.
        """
        for pos in bit_sequence:
            yield self.position_to_value[pos]

    def size(self) -> int:
        """See :meth:`Index.size`.

        Not supported by bitmap indexes; raises :class:`NotImplementedError`.
        """
        raise NotImplementedError(
            "Size Operation is not supported by this bitmap index."
        )

    def put(self, key: Key, value: Value) -> None:
        """See :meth:`Index.put`.

        Not supported by bitmap indexes; raises :class:`NotImplementedError`.
        """
        raise NotImplementedError(
            "Put Operation is not supported by this bitmap index."
        )

    def delete(self, key: Key, value: Value | None = None) -> None:
        """See :meth:`Index.delete`.

        Not supported by bitmap indexes; raises :class:`NotImplementedError`.
        """
        raise NotImplementedError(
            "Delete Operation is not supported by this bitmap index."
        )

    def flush(self, key: Key | None = None) -> None:
        """See :meth:`Index.flush`.

        Not supported by bitmap indexes; raises :class:`NotImplementedError`.
        """
        raise NotImplementedError(
            "Flush Operation is not supported by this bitmap index."
        )

    def show(self) -> None:
        """See :meth:`Index.show`.

        Not supported by bitmap indexes; raises :class:`NotImplementedError`.
        """
        raise NotImplementedError(
            "Show Operation is not supported by this bitmap index."
        )

    def bulkload(
        self, input_data: Iterator[tuple[Key, Value]], key_prefix: str = ""
    ) -> None:
        """See :meth:`Index.bulkload`.

        Gives every loaded key/value pair the next bit position, records the pair's
        value in the position-to-value list and sets the bit in the bit sequence of
        the pair's key (one bit sequence per distinct key), then adjusts the number
        of bits represented by each bit sequence to the number of loaded pairs.

        :param key_prefix: Reserved for subclasses that key their bit sequences by a prefix; this base
            implementation does not use it.
        """
        # Iterate through all key/value pairs and insert them into the index
        for key, value in input_data:
            # Give the pair the next bit position, even if its value or the whole pair was loaded before
            self.position_to_value.append(value)
            if key not in self:
                self._create_empty_bit_sequence_for_key(key)
            self._insert(key, len(self.position_to_value) - 1)

        # During bulkloading we do not know yet how many key/value pairs we will need to store, so we have to manually
        # adjust the number of bits at the end. This is necessary for some bitwise operations (e.g. inversion)
        self._update_number_of_bits_for_bit_sequences(len(self.position_to_value))

    @abstractmethod
    def _update_number_of_bits_for_bit_sequences(self, number_of_bits: int) -> None:
        """
        Abstract method for setting number of bits all bit sequences represent. This is necessary given that during
        the bulkloading we do not know the number of key/value pairs, and thus the number of bits we have to represent
        in each bit sequence.
        :param number_of_bits: The new number of bits to represent.
        """

    @abstractmethod
    def _compress_bit_sequences(self) -> None:
        """
        Compresses all bit sequences stored in the bitmap index.
        """

    @abstractmethod
    def __getitem__(self, key: Key) -> BitSequence:
        """
        Returns the bit_sequence stored at the given key.
        :param key: The key to retrieve the bit_sequence from.
        :return: The bit_sequence stored at the given key.
        """

    @abstractmethod
    def __contains__(self, key: Key) -> bool:
        """
        Checks whether the key is contained in the index.
        :param key: The key to check.
        :return: True, if it is contained, False otherwise.
        """

    def _create_empty_bit_sequence_for_key(self, key: Key) -> None:
        """
        Creates an empty bit_sequence for the given key.
        :param key: The key.
        """

    def _create_empty_bit_sequence(
        self, use_compression_if_possible: bool = False
    ) -> BitSequence:
        """
        Returns an empty bit_sequence with the length of the number of key/value pairs stored with this bitmap index.
        :param use_compression_if_possible: Returns a compressed bit sequence.
        :return: The empty bit_sequence.
        """
        uncompressed_bit_sequence: UncompressedBitSequence = (
            self.uncompressed_bit_sequence_type.create_all_false_bit_sequence(
                len(self.position_to_value)
            )
        )
        if use_compression_if_possible and self.use_compression:
            return self.compression_type.compress_bit_sequence(
                uncompressed_bit_sequence
            )
        return uncompressed_bit_sequence

    def _insert(self, key: Key, position: int) -> None:
        """
        Sets the bit at the given position in the bit_sequence representing the key.
        :param key: The key
        :param position: The bit position of the key/value pair
        """
        if len(self[key]) < len(self.position_to_value):
            # Bit sequence too small
            self[key].update_represented_number_of_bits(len(self.position_to_value))
        self[key].set_bit(position)

    def get(self, key: Key) -> Iterator[Value]:
        """See :meth:`PointQueryMixIn.get`.

        Yields the values represented by the set bits of the equal bit sequence
        for the given key, i.e. a value once for every loaded pair with this key.
        """
        yield from self._get_values_for_bit_sequence(self.get_equal(key))

    def get_all_in_range(self, min_key: Key, max_key: Key) -> Iterator[Value]:
        """See :meth:`RangeQueryMixIn.get_all_in_range`.

        Yields the values of the intersection (bitwise AND) of the
        greater-or-equal ``min_key`` and smaller-or-equal ``max_key`` bit
        sequences, i.e. the values whose key lies in ``[min_key, max_key]``; a
        value is yielded once for every loaded pair whose key lies in the range.
        """
        yield from self._get_values_for_bit_sequence(
            self.get_greater_or_equal(min_key) & self.get_smaller_or_equal(max_key)
        )

    @abstractmethod
    def get_number_of_bits(self) -> int:
        """
        Return the number of stored bits in this bitmap index.
        :return: The number of stored bits.
        """

    @abstractmethod
    def get_equal(self, key: Key) -> BitSequence:
        """
        Get a bit_sequence for all values that are equal the given key.
        :param key: The key
        """

    def get_smaller(self, key: Key) -> BitSequence:
        """
        Get a bit_sequence for all values that are smaller than the given key.
        :param key: The key
        """
        if not BitmapIndex.key_is_sortable(key):
            raise ValueError("The given key is not sortable.")
        return self._get_smaller(key)

    @abstractmethod
    def _get_smaller(self, key: Key) -> BitSequence:
        """
        Private method to get a bit_sequence for all values that are smaller than the given key. Assumes a sortable key.
        :param key: The key to be sorted.
        :return:
        """

    def get_smaller_or_equal(self, key: Key) -> BitSequence:
        """
        Get a bit_sequence for all values that are smaller or equal than the given key.
        """
        if not BitmapIndex.key_is_sortable(key):
            raise ValueError("The given key is not sortable.")
        return self._get_smaller_or_equal(key)

    @abstractmethod
    def _get_smaller_or_equal(self, key: Key) -> BitSequence:
        """
        Private method to get a bit_sequence for all values that are smaller than or equal to the given key. Assumes a sortable key.
        :param key: The key to be sorted.
        :return:
        """

    def get_greater(self, key: Key) -> BitSequence:
        """
        Get a bit_sequence for all values that are greater than the given key.
        """
        return ~self.get_smaller_or_equal(key)

    def get_greater_or_equal(self, key: Key) -> BitSequence:
        """
        Get a bit_sequence for all values that are greater than or equal the given attribute value.
        """
        return ~self.get_smaller(key)

    @staticmethod
    def key_is_sortable(key: Any) -> bool:
        """
        Checks whether the key can be sorted.
        :param key: The key.
        :return: True, if the key can be sorted, False if not.
        """
        try:
            _ = key < key
            return True
        except TypeError:
            return False
