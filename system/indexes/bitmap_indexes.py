from __future__ import annotations
from abc import ABC
from system.interfaces.indexing.bitmap_indexes import (
    BitmapIndex,
)
from typing import Type, Iterator
from system.interfaces.bit_sequence import BitSequence
from system.bit_sequences import IntegerBitSequence


class SortedBitmapIndex[Key, Value](BitmapIndex[Key, Value], ABC):
    """
    Abstract base class for a sorted bitmap index.
    """

    def __init__(self, bit_sequence_type: Type[BitSequence] = IntegerBitSequence):
        super().__init__(bit_sequence_type)

        # List of tuples, storing key values and their corresponding bit sequences
        self.key_bit_sequence_list: list[tuple[Key, BitSequence]] = []

        # Maps key values to positions in the bit_sequence list
        self.key_to_index: dict[Key, int] = dict()

    def _create_empty_bit_sequence_for_key(self, key: Key) -> None:
        self.key_to_index[key] = len(self.key_bit_sequence_list)
        self.key_bit_sequence_list.append((key, self._create_empty_bit_sequence()))

    def _update_number_of_bits_for_bit_sequences(self, number_of_bits: int) -> None:
        for _, value in self.key_bit_sequence_list:
            value.update_number_of_bits(number_of_bits)

    def bulkload(self, data: Iterator[tuple[Key, Value]], key_prefix: str = "") -> None:
        # Bulkload bit sequences
        super().bulkload(data, key_prefix)

        # Check whether key is sortable
        if not BitmapIndex.key_is_sortable(self.key_bit_sequence_list[0][0]):
            raise ValueError(f"The key is not sortable!")

        # Sort list of bit sequences
        self.key_bit_sequence_list.sort(key=lambda x: x[0])  # Sort by key

        # Update key mapping
        for idx, (key, _) in enumerate(self.key_bit_sequence_list):
            self.key_to_index[key] = idx

    def __getitem__(self, key: Key) -> BitSequence:
        # Get index for key
        index: int = self.key_to_index[key]

        # Return bit_sequence stored under the index
        return self.key_bit_sequence_list[index][1]

    def size(self) -> int:
        return len(self.key_bit_sequence_list)

    def stored_bits(self) -> int:
        return sum(
            [
                bit_sequence.stored_bits()
                for (_, bit_sequence) in self.key_bit_sequence_list
            ]
        )

    def __contains__(self, key: Key) -> bool:
        return key in self.key_to_index


class UnsortedBitmapIndex[Key, Value](BitmapIndex[Key, Value], ABC):
    """
    Abstract base class for an unsorted bitmap index.
    """

    def __init__(self, bit_sequence_type: Type[BitSequence] = IntegerBitSequence):
        super().__init__(bit_sequence_type)
        # Maps key values to bit sequences
        self.bit_sequence_map: dict[Key, BitSequence] = dict()

    def size(self) -> int:
        return len(self.bit_sequence_map)

    def _update_number_of_bits_for_bit_sequences(self, number_of_bits: int) -> None:
        for value in self.bit_sequence_map.values():
            value.update_number_of_bits(number_of_bits)

    def stored_bits(self) -> int:
        return sum(
            [
                bit_sequence.stored_bits()
                for bit_sequence in self.bit_sequence_map.values()
            ]
        )

    def _create_empty_bit_sequence_for_key(self, key: Key) -> None:
        # Insert all keys
        self.bit_sequence_map[key] = self._create_empty_bit_sequence()

    def __getitem__(self, key: Key) -> BitSequence:
        # Return bit_sequence stored under the index
        return self.bit_sequence_map[key]

    def __contains__(self, key: Key) -> bool:
        return key in self.bit_sequence_map


class EqualityEncodedBitmapIndex[Key, Value](BitmapIndex[Key, Value], ABC):
    """
    Implements an equality encoded bitmap index structure.
    """

    def get_equal(self, key: Key) -> BitSequence:
        if key not in self:
            # Key is not contained
            return self._create_empty_bit_sequence()
        return self[key]

    def _get_smaller_or_equal(self, key: Key) -> BitSequence:
        return self.get_smaller(key) | self.get_equal(key)


class SortedEqualityEncodedBitmapIndex[Key, Value](
    EqualityEncodedBitmapIndex[Key, Value], SortedBitmapIndex[Key, Value]
):
    """
    Implements a sorted equality encoded bitmap index structure.
    """

    def _get_smaller(self, key: Key) -> BitSequence:
        final_result: BitSequence = self._create_empty_bit_sequence()

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
        final_result: BitSequence = self._create_empty_bit_sequence()

        # Go through each stored and check whether it is smaller
        for stored_key in self.bit_sequence_map:
            if stored_key < key:
                final_result |= self.bit_sequence_map[stored_key]

        return final_result


class RangeEncodedBitmapIndex[Key, Value](SortedBitmapIndex[Key, Value]):
    """
    Implements range encoded bitmap index structure. Each bit_sequence contains all values whose keys are less or equal to the
    keys represented by the bit_sequence.
    """

    def bulkload(self, data: Iterator[tuple[Key, Value]], key_prefix: str = "") -> None:
        # Create a regular sorted bitmap
        super().bulkload(data, key_prefix)

        # Fill up the range for all greater keys
        for key, _ in reversed(self.key_bit_sequence_list):
            self._fill_up_range_for_key(key)

    def _fill_up_range_for_key(self, key: Key) -> None:
        """
        Inserts a value to all keys which are greater than the current key
        """
        # Get index for the key
        key_index: int = self.key_to_index[key]

        # Go through all values that are set for a given key
        for value in self.key_bit_sequence_list[key_index][1]:
            # Go through all keys that are greater/equal and the value to the key bit_sequence
            for index in range(key_index, len(self.key_bit_sequence_list)):
                self.key_bit_sequence_list[index][1].set_bit(
                    self.value_to_position[value]
                )

    def get_equal(self, key: Key) -> BitSequence:
        if key not in self:
            return self._create_empty_bit_sequence()

        # Check index under which the bit_sequence is stored
        index: int = self.key_to_index[key]

        if index > 0:
            # If we have an index higher than 0, then we need to remove all values which have a smaller key, i.e.,
            # the bit_sequence stored under (index - 1)
            return (
                self.key_bit_sequence_list[index][1]
                - self.key_bit_sequence_list[index - 1][1]
            )
        return self.key_bit_sequence_list[index][1]

    def _get_smaller(self, key: Key) -> BitSequence:
        return self.get_smaller_or_equal(key) - self.get_equal(key)

    def _get_smaller_or_equal(self, key: Key) -> BitSequence:
        if key in self:
            # The key is present in the bitmap
            return self[key]

        # Key is bigger than every key in the bitmap index -> Return the largest bit sequence
        if key > self.key_bit_sequence_list[-1][0]:
            return self.key_bit_sequence_list[-1][1]

        # Attribute is smaller than all others -> Empty Result
        if key < self.key_bit_sequence_list[0][0]:
            return self._create_empty_bit_sequence()

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
