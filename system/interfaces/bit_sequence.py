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

"""Abstract interfaces for bit sequences (uncompressed and compressed variants)."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable, Iterator


class BitSequence(ABC):
    """
    Defines a bit sequence. Also called bitvector, bitarray, bitlist, etc.
    """

    def __init__(self, represented_number_of_bits: int):
        """
        Create bit-sequence representing the given number of bits.
        :param represented_number_of_bits: The number of bits to represent.
        """
        self.represented_number_of_bits = represented_number_of_bits

    def __add__(self, other: BitSequence) -> BitSequence:
        """
        Combine two BitSequences, i.e., compute their union.
        :param other: The other bit-sequence.
        :return: The union of self and other as a bit-sequence.
        """
        return self | other

    def __sub__(self, other: BitSequence) -> BitSequence:
        """
        Subtracts other from self, i.e., computes self & not other.
        :param other: The other bit-sequence.
        :return: The subtraction of self and other as a bit-sequence.
        """
        return self & (~other)

    def __str__(self) -> str:
        """
        Returns the string representation of the bit-sequence.
        :return: The string representation.
        """
        return str(self.as_set())

    def __repr__(self) -> str:
        """
        Returns the string representation of the bit-sequence.
        :return: The string representation.
        """
        return str(self)

    def __len__(self) -> int:
        """
        Returns the number of bits represented by this bit-sequence.
        :return: The number of bits represented by this bit-sequence.
        """
        return self.represented_number_of_bits

    @abstractmethod
    def __contains__(self, index: int) -> bool:
        """
        Checks if the bit at the index is set in this bit-sequence.
        :param index: The index whose bit is to be checked.
        :return: True if the bit is set.
        """

    @abstractmethod
    def __getitem__(self, index: int) -> bool:
        """
        Returns whether the bit at the given index is set to true or not.
        :param index: The index to be checked.
        :return: True, if the bit is set, False otherwise.
        """

    @abstractmethod
    def __setitem__(self, index: int, value: bool) -> None:
        """
        Sets the bit at the given index to the given value.
        :param index: The index to be set.
        :param value: The value to be set.
        """

    @abstractmethod
    def __eq__(self, other: BitSequence) -> bool:
        """
        Checks two bit-sequences for equality.
        :param other: The other bit-sequence.
        :return: True, if both bit-sequences are equal, False if not.
        """

    @abstractmethod
    def __and__(self, other: BitSequence) -> BitSequence:
        """
        Returns the bitwise & between this and the other bit-sequence
        :return: The bitwise & as a bit-sequence.
        """

    @abstractmethod
    def __or__(self, other: BitSequence) -> BitSequence:
        """
        Returns the bitwise | between this and the other bit-sequence
        :return: The bitwise | as a bit-sequence.
        """

    @abstractmethod
    def __xor__(self, other: BitSequence) -> BitSequence:
        """
        Returns the bitwise ^ between this and the other bit-sequence
        :return: The bitwise ^ as a bit-sequence.
        """

    @abstractmethod
    def __invert__(self) -> BitSequence:
        """
        Returns the bitwise inversion/negation of this bit-sequence
        :return: The bitwise ~ as a bit-sequence.
        """

    def get_number_of_bits(self) -> int:
        """
        Returns the number of bits in this bit-sequence.
        :return: The number of bits.
        """
        return len(self)

    def as_set(self) -> set[int]:
        """
        Returns the bit-sequence as a set of integer positions, i.e. the set of integer positions set to true.
        :return: A set containing all positions that are set to 1.
        """
        return set(bit for bit in self)

    def _out_of_bounds(self, index: int) -> bool:
        """
        Checks whether a given index is out-of-bounds for the bit sequence.
        :param index: The index to check.
        :return: True, if index is out of bounds, False otherwise.
        """
        return index < 0 or index >= len(self)

    def get_bit_sequence_for_range(
        self,
        lower_idx: int,
        upper_idx: int,
        represented_number_of_bits: int | None = None,
    ) -> BitSequence:
        """
        Returns a bit sequence representing the given range.
        :param lower_idx: The lower index (including) of the range.
        :param upper_idx: The upper index (including) of the range.
        :param represented_number_of_bits: Number of bits represented by new the range. If None, the difference between both
        indices is used
        :return: The bit sequence for the range.
        """
        if any(self._out_of_bounds(idx) for idx in [lower_idx, upper_idx]):
            raise ValueError("Range out of bounds.")
        return self._get_bit_sequence_for_range(
            lower_idx, upper_idx, represented_number_of_bits
        )

    def set_bit(self, index: int) -> None:
        """
        Set the bit at the given index to true.
        :param index: The index of the bit to set.
        """
        if self._out_of_bounds(index):
            raise ValueError("Key out of bounds for this bit-sequence.")
        self[index] = True

    def unset_bit(self, index: int) -> None:
        """
        Unset the bit at the given index.
        :param index: The index of the bit to unset.
        """
        if self._out_of_bounds(index):
            raise ValueError("Key out of bounds for this bit-sequence.")
        self[index] = False

    @staticmethod
    @abstractmethod
    def create_all_false_bit_sequence(
        number_of_bits: int = 0,
    ) -> BitSequence:
        """
        Creates a bit-sequence where all bits are set to false.
        :param number_of_bits: The number of bits in the bit-sequence.
        :return: A bit-sequence of length number_of_bits and all bits set to False.
        """

    @abstractmethod
    def update_represented_number_of_bits(
        self, updated_represented_number_of_bits: int
    ) -> None:
        """
        Updates the number of bits to be represented by this bit-sequence.
        :param updated_represented_number_of_bits: The number of bits to represent.
        """

    @abstractmethod
    def intersects(self, other: BitSequence) -> bool:
        """
        Checks whether bit sequences intersect with each other.

        :param other: The other bit sequence.
        :return: True, if the bit sequences intersect, False if not.
        """

    @abstractmethod
    def _get_bit_sequence_for_range(
        self,
        lower_idx: int,
        upper_idx: int,
        represented_number_of_bits: int | None = None,
    ) -> BitSequence:
        """
        Returns a bit sequence representing the given range. Assumes out-of-bounds errors were checked.
        :param lower_idx: The lower index (including) of the range.
        :param upper_idx: The upper index (including) of the range.
        :param represented_number_of_bits: Number of bits represented by new the range. If None, the difference between both
        indices is used
        :return: The bit sequence for the range.
        """

    @abstractmethod
    def all_bits_set_to_false(self) -> bool:
        """
        A predicate checking if all bits in the bit-sequence are set to False.
        :return: True, if all bits in the bit-sequence are set to False, False if not.
        """

    @abstractmethod
    def all_bits_set_to_true(self) -> bool:
        """
        A predicate checking if all bits in the bit-sequence are set to True.
        :return: True, if all bits in the bit-sequence are set to True, False if not.
        """

    @abstractmethod
    def get_least_significant_bit(self) -> BitSequence:
        """
        Returns a bit sequence only containing the least significant bit of this bit sequence.
        :return: The bit sequence only containing the least significant bit of this bit sequence.
        """

    @abstractmethod
    def get_most_significant_bit(self) -> BitSequence:
        """
        Returns a bit sequence only containing the most significant bit of this bit sequence.
        :return: The bit sequence only containing the most significant bit of this bit sequence.
        """

    @abstractmethod
    def contains_bit_sequence(self, other: BitSequence) -> bool:
        """
        Checks whether the other bit sequence is contained in self.
        :param other: The other bit sequence.
        :return: True, if other is contained in self, False if not.
        """

    @abstractmethod
    def bit_count(self) -> int:
        """Returns the number of set bits in the bit sequence."""

    @abstractmethod
    def increase_represented_integer(self, number: int) -> None:
        """
        Increase the integer represented by the bit sequence by the given number.
        """

    @abstractmethod
    def get_represented_integer(self) -> int:
        """
        Returns the integer represented by this bit sequence.
        :return: The integer represented by this bit sequence.
        """

    class SetBitsIterator(ABC, Iterator[int]):
        """
        An iterator to traverse through all set bits in the given bit-sequence. This iterator returns the integer
        positions of all bits that are set to True in the bit_sequence.
        """

        @abstractmethod
        def __init__(self, bit_sequence: BitSequence):
            """
            :param bit_sequence: The bit sequence to iterate.
            """

        def __iter__(self):
            return self

        @abstractmethod
        def __next__(self) -> int:
            pass

    def __iter__(self) -> Iterator[int]:
        """
        Returns an iterator to iterate through set bits, from the least significant bit to the most significant bit.
        :return: An iterator to iterate through all set bits.
        """
        return self.SetBitsIterator(self)

    class SetBitsReverseIterator(ABC, Iterator[int]):
        """
        An iterator to traverse the set bits in a bit sequence in reverse order, i.e., starting
        with the most significant bit.
        """

        @abstractmethod
        def __init__(self, bit_sequence: BitSequence):
            """
            :param bit_sequence: The bit_sequence to iterate.
            """

        def __iter__(self):
            return self

        @abstractmethod
        def __next__(self) -> int:
            pass

    def __reversed__(self):
        """
        Returns an iterator to iterate through set bits in reversed order, from the
        most significant bit to the least significant bit.
        :return: An iterator to iterate through all set bits.
        """
        return self.SetBitsReverseIterator(self)


class UncompressedBitSequence(BitSequence, ABC):
    """
    Abstract class to represent an uncompressed bit sequence
    """

    @abstractmethod
    def _perform_binary_operation(
        self, other: BitSequence, operation: Callable
    ) -> UncompressedBitSequence:
        """
        Applies a bitwise binary operation between this and the other bit-sequence, position by position.
        :param other: The other bit-sequence.
        :param operation: A callable taking two operands and returning the result of the bitwise operation.
        :return: The result of the operation as an uncompressed bit-sequence.
        """

    def __and__(self, other: UncompressedBitSequence) -> UncompressedBitSequence:
        """See :meth:`BitSequence.__and__`."""
        return self._perform_binary_operation(other, lambda x, y: x & y)

    def __or__(self, other: UncompressedBitSequence) -> UncompressedBitSequence:
        """See :meth:`BitSequence.__or__`."""
        return self._perform_binary_operation(other, lambda x, y: x | y)

    def __xor__(self, other: UncompressedBitSequence) -> UncompressedBitSequence:
        """See :meth:`BitSequence.__xor__`."""
        return self._perform_binary_operation(other, lambda x, y: x ^ y)

    @staticmethod
    def create_all_false_bit_sequence(
        number_of_bits: int = 0,
    ) -> UncompressedBitSequence:
        """See :meth:`BitSequence.create_all_false_bit_sequence`.

        Uncompressed variant: the returned bit-sequence is an :class:`UncompressedBitSequence`.
        """


class CompressedBitSequence(BitSequence, ABC):
    """
    Abstract class to represent compressed bit sequences.
    """

    @staticmethod
    @abstractmethod
    def compress_bit_sequence(
        bit_sequence: UncompressedBitSequence,
    ) -> CompressedBitSequence:
        """
        Compresses the given bit sequence.
        :param bit_sequence: The bit sequence to compress.
        :return: The compressed bit sequence.
        """

    @staticmethod
    def create_all_false_bit_sequence(
        number_of_bits: int = 0,
    ) -> CompressedBitSequence:
        """See :meth:`BitSequence.create_all_false_bit_sequence`.

        Compressed variant: the returned bit-sequence is a :class:`CompressedBitSequence`.
        """
