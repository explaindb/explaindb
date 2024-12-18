from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable


class BitSequence(ABC):
    """
    Defines a bit sequence. Also called bitvector, bitarray, bitlist, etc.
    """

    def __init__(self, number_of_bits: int):
        """
        Create bit-sequence with given number of bits.
        :param number_of_bits: The number of bits to use.
        """
        self.number_of_bits = number_of_bits

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
        return self.number_of_bits

    @abstractmethod
    def __eq__(self, other: BitSequence) -> bool:
        """
        Checks two bit-sequences for equality.
        :param other: The other bit-sequence.
        :return: True, if both bit-sequences are equal, False if not.
        """
        pass

    @abstractmethod
    def _perform_binary_operation(
        self, other: BitSequence, operation: Callable
    ) -> BitSequence:
        """
        Performs the given binary operation upon the bits of the bit-sequence.
        :param other: The other bit-sequence.
        :param operation: The operation to be performed.
        :return: The resulting bit-sequence.
        """
        pass

    def __and__(self, other: BitSequence) -> BitSequence:
        """
        Returns the bitwise & between this and the other bit-sequence
        :return: The bitwise & as a bit-sequence.
        """
        return self._perform_binary_operation(other, lambda x, y: x & y)

    def __or__(self, other: BitSequence) -> BitSequence:
        """
        Returns the bitwise | between this and the other bit-sequence
        :return: The bitwise | as a bit-sequence.
        """
        return self._perform_binary_operation(other, lambda x, y: x | y)

    def __xor__(self, other: BitSequence) -> BitSequence:
        """
        Returns the bitwise ^ between this and the other bit-sequence
        :return: The bitwise ^ as a bit-sequence.
        """
        return self._perform_binary_operation(other, lambda x, y: x ^ y)

    @abstractmethod
    def __invert__(self) -> BitSequence:
        """
        Returns the bitwise invert of this bit-sequence
        :return: The bitwise ~ as a bit-sequence.
        """
        pass

    def stored_bits(self) -> int:
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

    @abstractmethod
    def update_number_of_bits(self, number_of_bits: int) -> None:
        """
        Updates the number of bits stored in this bit-sequence.
        :param number_of_bits: The number of bits to use.
        """
        pass

    @abstractmethod
    def __getitem__(self, index: int) -> bool:
        """
        Returns whether the bit at the given index is set or not.
        :param index: The index to be checked.
        :return: True, if the bit is set, False otherwise.
        """
        pass

    @abstractmethod
    def __setitem__(self, index: int, value: bool) -> None:
        """
        Sets the bit at the given index to the given value.
        :param index: The index to be set.
        :param value: The value to be set.
        """
        pass

    def set_bit(self, index: int) -> None:
        """
        Set the bit at the given index.
        :param index: The index of the bit to set.
        """
        if index < 0 or index >= len(self):
            raise ValueError("Key out of bounds for this bit-sequence.")
        self[index] = True

    @abstractmethod
    def __contains__(self, index: int) -> bool:
        """
        Checks if the bit at the index is set in this bit-sequence.
        :param index: The index whose bit is to be checked.
        :return: True if the bit is set.
        """
        pass

    @staticmethod
    @abstractmethod
    def create_empty_bit_sequence(number_of_bits: int = 0) -> BitSequence:
        """
        Creates an empty bit-sequence.
        :param number_of_bits: The number of bits in the bit-sequence.
        :return: The empty bit-sequence.
        """
        pass

    @abstractmethod
    def no_bits_set(self) -> bool:
        """
        Checks if the bit-sequence is empty.
        :return: True, if the bit-sequence is empty, False if not.
        """
        pass

    @abstractmethod
    def all_bits_set(self) -> bool:
        """
        Checks if the bit-sequence is full.
        :return: True, if the bit-sequence is full, False if not.
        """
        pass

    class SetBitsIterator(ABC):
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

    @abstractmethod
    def __iter__(self) -> SetBitsIterator:
        """
        Returns an iterator to iterate through set bits, from the least significant bit to the most significant bit.
        :return: An iterator to iterate through all set bits.
        """
        pass
