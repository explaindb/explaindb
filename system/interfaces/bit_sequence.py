from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable, Iterator


class BitSequence(ABC):
    """
    Defines a bit sequence. Also called bitvector, bitarray, bitlist, etc.
    """

    def __init__(self, represented_number_of_bits: int):
        """
        Create bit-sequence with given number of bits.
        :param represented_number_of_bits: The number of bits to use.
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
        :return: The number of set bits.
        """
        return self.represented_number_of_bits

    @abstractmethod
    def __eq__(self, other: BitSequence) -> bool:
        """
        Checks two bit-sequences for equality.
        :param other: The other bit-sequence.
        :return: True, if both bit-sequences are equal, False if not.
        """
        pass

    @abstractmethod
    def __and__(self, other: BitSequence) -> BitSequence:
        """
        Returns the bitwise & between this and the other bit-sequence
        :return: The bitwise & as a bit-sequence.
        """
        pass

    @abstractmethod
    def __or__(self, other: BitSequence) -> BitSequence:
        """
        Returns the bitwise | between this and the other bit-sequence
        :return: The bitwise | as a bit-sequence.
        """
        pass

    @abstractmethod
    def __xor__(self, other: BitSequence) -> BitSequence:
        """
        Returns the bitwise ^ between this and the other bit-sequence
        :return: The bitwise ^ as a bit-sequence.
        """
        pass

    @abstractmethod
    def __invert__(self) -> BitSequence:
        """
        Returns the bitwise invert of this bit-sequence
        :return: The bitwise ~ as a bit-sequence.
        """
        pass

    def get_number_of_bits(self) -> int:
        """
        Returns the number of bits stored in this bit-sequence.
        :return: The number of bits stored.
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

    def __contains__(self, index: int) -> bool:
        """
        Checks if the bit at the index is set in this bit-sequence.
        :param index: The index whose bit is to be checked.
        :return: True if the bit is set.
        """
        raise NotImplementedError("This function is not yet implemented")

    @staticmethod
    def create_all_false_bit_sequence(
        number_of_bits: int = 0,
    ) -> UncompressedBitSequence:
        """
        Creates a bit-sequence where all bits are set to false.
        :param number_of_bits: The number of bits in the bit-sequence.
        :return: A bit-sequence of length number_of_bits and all bits set to False.
        """
        raise NotImplementedError("This function is not yet implemented")

    def update_represented_number_of_bits(
        self, updated_represented_number_of_bits: int
    ) -> None:
        """
        Updates the number of bits stored in this bit-sequence.
        :param updated_represented_number_of_bits: The number of bits to represent.
        """
        raise NotImplementedError("This function is not yet implemented")

    def all_bits_set_to_false(self) -> bool:
        """
        A predicate checking if all bits in the bit-sequence are set to True.
        :return: True, if all bits in the bit-sequence are set to True, False if not.
        """
        raise NotImplementedError("This function is not yet implemented")

    def all_bits_set_to_true(self) -> bool:
        """
        A predicate checking if all bits in the bit-sequence are set to True.
        :return: True, if all bits in the bit-sequence are set to True, False if not.
        """
        raise NotImplementedError("This function is not yet implemented")

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
        raise NotImplementedError("This function is not yet implemented")

    def __getitem__(self, index: int) -> bool:
        """
        Returns whether the bit at the given index is set or not.
        :param index: The index to be checked.
        :return: True, if the bit is set, False otherwise.
        """
        raise NotImplementedError("This function is not yet implemented")

    def __setitem__(self, index: int, value: bool) -> None:
        """
        Sets the bit at the given index to the given value.
        :param index: The index to be set.
        :param value: The value to be set.
        """
        raise NotImplementedError("This function is not yet implemented")

    def set_bit(self, index: int) -> None:
        """
        Set the bit at the given index.
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

    def increase_represented_integer(self, number: int) -> None:
        """
        Increase the integer represented by the bit sequence by the given number.
        """
        raise NotImplementedError("This function is not yet implemented")

    def get_represented_integer(self) -> int:
        """
        Returns the integer represented by this bit sequence.
        :return: The integer represented by this bit sequence.
        """
        raise NotImplementedError("This function is not yet implemented")

    class SetBitsIterator(ABC, Iterator[int]):
        """
        An iterator to traverse through all set bits in the given bit-sequence. This iterator returns the integer
        positions of all set bits in the bit-sequence.
        """

        @abstractmethod
        def __init__(self, bit_sequence: BitSequence):
            pass

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
        return type(self).SetBitsIterator(self)


class UncompressedBitSequence(BitSequence, ABC):
    """
    Abstract class to represent an uncompressed bit sequence
    """

    @abstractmethod
    def _perform_binary_operation(
        self, other: BitSequence, operation: Callable
    ) -> BitSequence:
        pass

    def __and__(self, other: BitSequence) -> BitSequence:
        return self._perform_binary_operation(other, lambda x, y: x & y)

    def __or__(self, other: BitSequence) -> BitSequence:
        return self._perform_binary_operation(other, lambda x, y: x | y)

    def __xor__(self, other: BitSequence) -> BitSequence:
        return self._perform_binary_operation(other, lambda x, y: x ^ y)


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
        pass
