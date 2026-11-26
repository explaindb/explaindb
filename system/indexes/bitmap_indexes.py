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

"""Concrete bitmap index implementations: sorted/unsorted, equality-encoded, and range-encoded."""

from __future__ import annotations
from abc import ABC
from system.interfaces.indexing.bitmap_indexes import (
    BitmapIndex,
)
from typing import Any, Protocol, Type, Iterator
from system.interfaces.bit_sequence import (
    BitSequence,
    UncompressedBitSequence,
    CompressedBitSequence,
)
from system.indexes.bit_sequences import IntegerBitSequence


class _Comparable(Protocol):
    """A key type whose values can be ordered with ``<``, e.g. ``str`` or ``int``: sorted and range-encoded
    bitmap indexes keep their keys in sorted order."""

    def __lt__(self, other: Any, /) -> bool: ...


class SortedBitmapIndex[Key: _Comparable, Value](BitmapIndex[Key, Value], ABC):
    """
    Abstract base class for a sorted bitmap index.
    """

    def __init__(
        self,
        bit_sequence_type: Type[UncompressedBitSequence] = IntegerBitSequence,
        compression_type: Type[CompressedBitSequence] | None = None,
    ):
        """See :meth:`BitmapIndex.__init__`.

        Additionally initializes the sorted list of key/bit-sequence tuples and
        the map from key to its position in that list.
        """
        super().__init__(bit_sequence_type, compression_type)

        # List of tuples, storing key values and their corresponding bit sequences
        self.key_bit_sequence_list: list[tuple[Key, BitSequence]] = []

        # Maps key values to positions in the bit_sequence list
        self.key_to_index: dict[Key, int] = {}

    def _create_empty_bit_sequence_for_key(self, key: Key) -> None:
        """See :meth:`BitmapIndex._create_empty_bit_sequence_for_key`.

        Appends a ``(key, empty bit sequence)`` tuple to the list and records the
        key's position in the key-to-index map.
        """
        self.key_to_index[key] = len(self.key_bit_sequence_list)
        self.key_bit_sequence_list.append((key, self._create_empty_bit_sequence()))

    def _update_number_of_bits_for_bit_sequences(self, number_of_bits: int) -> None:
        """See :meth:`BitmapIndex._update_number_of_bits_for_bit_sequences`.

        Updates every bit sequence in the list.
        """
        for _, bit_sequence in self.key_bit_sequence_list:
            bit_sequence.update_represented_number_of_bits(number_of_bits)

    def _compress_bit_sequences(self) -> None:
        """See :meth:`BitmapIndex._compress_bit_sequences`.

        Replaces each list entry's bit sequence with its compressed form.
        """
        # Go through each stored bit sequence
        for idx in range(len(self.key_bit_sequence_list)):
            # the bit sequences are compressed once, after the bulkload, so they are still uncompressed:
            bit_sequence: BitSequence = self.key_bit_sequence_list[idx][1]
            assert isinstance(bit_sequence, UncompressedBitSequence)
            # Update the tuple stored by reusing the existing key, and compressing the bit sequence
            self.key_bit_sequence_list[idx] = (
                self.key_bit_sequence_list[idx][0],
                self.compression_type.compress_bit_sequence(bit_sequence),
            )

    def bulkload(
        self, input_data: Iterator[tuple[Key, Value]], key_prefix: str = ""
    ) -> None:
        """See :meth:`Index.bulkload`.

        After the base bulkload, sorts the key/bit-sequence list by key (raising
        :class:`ValueError` if the keys are not sortable) and rebuilds the
        key-to-index map to reflect the sorted order.
        """
        # Bulkload bit sequences
        super().bulkload(input_data, key_prefix)

        # Check whether key is sortable
        if not BitmapIndex.key_is_sortable(self.key_bit_sequence_list[0][0]):
            raise ValueError("The key is not sortable!")

        # Sort list of bit sequences
        self.key_bit_sequence_list.sort(key=lambda x: x[0])  # Sort by key

        # Update key->bit sequence mapping
        for idx, (key, _) in enumerate(self.key_bit_sequence_list):
            self.key_to_index[key] = idx

    def __getitem__(self, key: Key) -> BitSequence:
        """See :meth:`BitmapIndex.__getitem__`.

        Resolves the key to its list position via the key-to-index map and
        returns the bit sequence stored there.
        """
        # Get index for key
        index: int = self.key_to_index[key]

        # Return bit_sequence stored under the index
        return self.key_bit_sequence_list[index][1]

    def size(self) -> int:
        """See :meth:`Index.size`.

        Unlike the base bitmap index, sorted bitmap indexes support this and
        return the number of distinct keys.
        """
        return len(self.key_bit_sequence_list)

    def get_number_of_bits(self) -> int:
        """See :meth:`BitmapIndex.get_number_of_bits`.

        Sums the number of bits over every bit sequence in the list.
        """
        return sum(
            bit_sequence.get_number_of_bits()
            for (_, bit_sequence) in self.key_bit_sequence_list
        )

    def __contains__(self, key: Key) -> bool:
        """See :meth:`BitmapIndex.__contains__`.

        Checks the key-to-index map.
        """
        return key in self.key_to_index


class UnsortedBitmapIndex[Key, Value](BitmapIndex[Key, Value], ABC):
    """
    Abstract base class for an unsorted bitmap index.
    """

    def __init__(
        self,
        bit_sequence_type: Type[UncompressedBitSequence] = IntegerBitSequence,
        compression_type: Type[CompressedBitSequence] | None = None,
    ):
        """See :meth:`BitmapIndex.__init__`.

        Additionally initializes the map from key to its bit sequence.
        """
        super().__init__(bit_sequence_type, compression_type)
        # Maps key values to bit sequences
        self.bit_sequence_map: dict[Key, BitSequence] = {}

    def size(self) -> int:
        """See :meth:`Index.size`.

        Unlike the base bitmap index, unsorted bitmap indexes support this and
        return the number of distinct keys.
        """
        return len(self.bit_sequence_map)

    def _update_number_of_bits_for_bit_sequences(self, number_of_bits: int) -> None:
        """See :meth:`BitmapIndex._update_number_of_bits_for_bit_sequences`.

        Updates every bit sequence in the key-to-bit-sequence map.
        """
        for value in self.bit_sequence_map.values():
            value.update_represented_number_of_bits(number_of_bits)

    def _compress_bit_sequences(self) -> None:
        """See :meth:`BitmapIndex._compress_bit_sequences`.

        Replaces each mapped bit sequence with its compressed form.
        """
        # Go through each stored bit sequence
        for key in self.bit_sequence_map:
            # the bit sequences are compressed once, after the bulkload, so they are still uncompressed:
            bit_sequence: BitSequence = self.bit_sequence_map[key]
            assert isinstance(bit_sequence, UncompressedBitSequence)
            # Compress the bit sequence for each key
            self.bit_sequence_map[key] = self.compression_type.compress_bit_sequence(
                bit_sequence
            )

    def get_number_of_bits(self) -> int:
        """See :meth:`BitmapIndex.get_number_of_bits`.

        Sums the number of bits over every bit sequence in the map.
        """
        return sum(
            bit_sequence.get_number_of_bits()
            for bit_sequence in self.bit_sequence_map.values()
        )

    def _create_empty_bit_sequence_for_key(self, key: Key) -> None:
        """See :meth:`BitmapIndex._create_empty_bit_sequence_for_key`.

        Stores a fresh empty bit sequence for the key in the map.
        """
        # Insert all keys
        self.bit_sequence_map[key] = self._create_empty_bit_sequence()

    def __getitem__(self, key: Key) -> BitSequence:
        """See :meth:`BitmapIndex.__getitem__`.

        Looks the key up directly in the key-to-bit-sequence map.
        """
        # Return bit_sequence stored under the index
        return self.bit_sequence_map[key]

    def __contains__(self, key: Key) -> bool:
        """See :meth:`BitmapIndex.__contains__`.

        Checks the key-to-bit-sequence map.
        """
        return key in self.bit_sequence_map


class EqualityEncodedBitmapIndex[Key, Value](BitmapIndex[Key, Value], ABC):
    """
    Implements an equality encoded bitmap index structure.
    """

    def bulkload(
        self, input_data: Iterator[tuple[Key, Value]], key_prefix: str = ""
    ) -> None:
        """See :meth:`Index.bulkload`.

        After the base bulkload, compresses all bit sequences in one pass if
        compression is enabled (cheaper than inserting into compressed sequences).
        """
        super().bulkload(input_data, key_prefix)

        # We could also directly insert and compress, which causes notable overhead, thus we first bulkload the
        # uncompressed bit sequences, and compress them afterward.
        if self.use_compression:
            self._compress_bit_sequences()

    def get_equal(self, key: Key) -> BitSequence:
        """See :meth:`BitmapIndex.get_equal`.

        Equality-encoded variant: returns the key's stored bit sequence directly,
        or an empty bit sequence if the key is absent.
        """
        if key not in self:
            # Key is not contained
            return self._create_empty_bit_sequence(True)
        return self[key]

    def _get_smaller_or_equal(self, key: Key) -> BitSequence:
        """See :meth:`BitmapIndex._get_smaller_or_equal`.

        Equality-encoded variant: OR of the smaller and the equal bit sequences.
        """
        return self.get_smaller(key) | self.get_equal(key)


class SortedEqualityEncodedBitmapIndex[Key: _Comparable, Value](
    EqualityEncodedBitmapIndex[Key, Value], SortedBitmapIndex[Key, Value]
):
    """
    Implements a sorted equality encoded bitmap index structure.
    """

    def _get_smaller(self, key: Key) -> BitSequence:
        """See :meth:`BitmapIndex._get_smaller`.

        Sorted equality-encoded variant: walks the sorted list from the smallest
        key, OR-ing bit sequences, and stops at the first key not smaller.
        """
        final_result: BitSequence = self._create_empty_bit_sequence(
            use_compression_if_possible=True
        )

        # Go through and stop when a value was found
        curr_idx: int = 0
        while (
            curr_idx < len(self.key_bit_sequence_list)
            and self.key_bit_sequence_list[curr_idx][0] < key
        ):
            final_result |= self.key_bit_sequence_list[curr_idx][1]
            curr_idx += 1
        return final_result


class UnsortedEqualityEncodedBitmapIndex[Key, Value](
    EqualityEncodedBitmapIndex[Key, Value], UnsortedBitmapIndex[Key, Value]
):
    """
    Implements an unsorted equality encoded bitmap index structure.
    """

    def _get_smaller(self, key: Key) -> BitSequence:
        """See :meth:`BitmapIndex._get_smaller`.

        Unsorted equality-encoded variant: scans every stored key and OR-s the
        bit sequences of those smaller than the given key.
        """
        final_result: BitSequence = self._create_empty_bit_sequence(
            use_compression_if_possible=True
        )

        # Go through each stored and check whether it is smaller
        for stored_key in self.bit_sequence_map:
            # the keys of an unsorted index need not be sortable, so the type checker cannot verify `<`;
            # get_smaller only calls this method after checking that the key is sortable:
            if stored_key < key:  # pyright: ignore[reportOperatorIssue]
                final_result |= self.bit_sequence_map[stored_key]

        return final_result


class RangeEncodedBitmapIndex[Key: _Comparable, Value](SortedBitmapIndex[Key, Value]):
    """
    Implements range encoded bitmap index structure. Each bit_sequence contains all values whose keys are less or equal to the
    keys represented by the bit_sequence. Since every loaded pair has its own bit position, get_equal recovers the pairs
    of a key by removing the bit sequence of the next-smaller key.
    """

    def bulkload(
        self, input_data: Iterator[tuple[Key, Value]], key_prefix: str = ""
    ) -> None:
        """See :meth:`Index.bulkload`.

        Range-encoded variant: after building the sorted bitmap, propagates each
        key's values into every bit sequence of the greater-or-equal keys so that
        each bit sequence holds all values with keys up to its own, then compresses
        if enabled.
        """
        # Create a regular sorted bitmap
        super().bulkload(input_data, key_prefix)

        # Fill up the range for all greater keys
        for key, _ in reversed(self.key_bit_sequence_list):
            self._fill_up_range_for_key(key)

        # We could also directly insert and compress, which causes notable overhead, thus we first bulkload the
        # uncompressed bit sequences, and compress them afterward.
        if self.use_compression:
            self._compress_bit_sequences()

    def _fill_up_range_for_key(self, key: Key) -> None:
        """
        Sets every bit that is set in the key's bit sequence also in the bit sequences of all greater keys.
        :param key: The key whose bits are copied.
        """
        # Get index for the key
        key_index: int = self.key_to_index[key]

        # Go through the positions of all bits that are set for the given key; iterating a bit sequence yields
        # these positions, not the values
        for position in self.key_bit_sequence_list[key_index][1]:
            # Set this bit in the bit sequences of the key and of all greater keys
            for index in range(key_index, len(self.key_bit_sequence_list)):
                self.key_bit_sequence_list[index][1].set_bit(position)

    def get_equal(self, key: Key) -> BitSequence:
        """See :meth:`BitmapIndex.get_equal`.

        Range-encoded variant: recovers the equal set by subtracting the previous
        (next-smaller) key's cumulative bit sequence from this key's, returning an
        empty sequence for an absent key and the raw sequence at index 0.
        """
        if key not in self:
            return self._create_empty_bit_sequence(use_compression_if_possible=True)

        # Check index under which the bit_sequence is stored
        index: int = self.key_to_index[key]

        if index > 0:
            # If we have an index higher than 0, then we need to remove the positions of all pairs with a smaller key,
            # i.e., the bit_sequence stored under (index - 1)
            return (
                self.key_bit_sequence_list[index][1]
                - self.key_bit_sequence_list[index - 1][1]
            )
        return self.key_bit_sequence_list[index][1]

    def _get_smaller(self, key: Key) -> BitSequence:
        """See :meth:`BitmapIndex._get_smaller`.

        Range-encoded variant: the smaller-or-equal set minus the equal set.
        """
        return self.get_smaller_or_equal(key) - self.get_equal(key)

    def _get_smaller_or_equal(self, key: Key) -> BitSequence:
        """See :meth:`BitmapIndex._get_smaller_or_equal`.

        Range-encoded variant: since each bit sequence is already the cumulative
        set of values up to its key, returns that sequence directly for a present
        key; otherwise returns the largest sequence (key above all), an empty
        sequence (key below all), or, via binary search, the cumulative sequence
        of the next-smaller key.
        """
        if key in self:
            # The key is present in the bitmap
            return self[key]

        # Key is bigger than every key in the bitmap index -> Return the largest bit sequence
        if key > self.key_bit_sequence_list[-1][0]:
            return self.key_bit_sequence_list[-1][1]

        # Attribute is smaller than all others -> Empty Result
        if key < self.key_bit_sequence_list[0][0]:
            return self._create_empty_bit_sequence(use_compression_if_possible=True)

        # We need to find the next-smallest value, use binary search for that
        left_idx: int = 0
        right_idx: int = len(self.key_bit_sequence_list) - 1
        while left_idx < right_idx:
            mid_idx: int = (left_idx + right_idx) // 2  # floored
            if self.key_bit_sequence_list[mid_idx][0] < key:
                left_idx = mid_idx + 1
            else:
                right_idx = mid_idx - 1

        # We might be off by one index
        if not self.key_bit_sequence_list[left_idx][0] < key:
            left_idx -= 1

        return self.key_bit_sequence_list[left_idx][1]
