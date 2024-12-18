from __future__ import annotations
from system.interfaces.bit_sequence import BitSequence
from typing import Callable


class IntegerBitSequence(BitSequence):
    """
    Represents a bit-sequence as an integer type.
    """

    def __init__(self, number: int = 0, number_of_bits: int | None = None):
        """
        :param number: The internal integer representation of the bit-sequence.
        :param number_of_bits: The number of bits in the bit-sequence.
        """
        if number_of_bits and number_of_bits < number.bit_length():
            raise ValueError(
                f"Max Len can not be smaller than the passed bit-sequence number"
            )
        super().__init__(
            number_of_bits if number_of_bits is not None else number.bit_length()
        )
        self.number: int = number

    def __eq__(self, other: IntegerBitSequence) -> bool:
        return isinstance(other, IntegerBitSequence) and other.number == self.number

    def _perform_binary_operation(
        self, other: IntegerBitSequence, operation: Callable
    ) -> IntegerBitSequence:
        return type(self)(
            operation(self.number, other.number), max(len(self), len(other))
        )

    def update_number_of_bits(self, number_of_bits: int) -> None:
        """
        Updates the number of bits stored in this bit-sequence.
        :param number_of_bits: The number of bits to use.
        """
        if number_of_bits < self.number_of_bits:
            # Set all greater bits to 0
            self.number &= (1 << number_of_bits) - 1
        self.number_of_bits = number_of_bits

    def __invert__(self) -> BitSequence:
        return type(self)(self.number ^ ((1 << len(self)) - 1), len(self))

    def __getitem__(self, index: int) -> bool:
        mask: int = 1 << index
        return mask == self.number & mask

    def __setitem__(self, index: int, value: bool) -> None:
        if value:
            self.number |= 1 << index
        else:
            self.number &= 0 << index

    def __contains__(self, index: int) -> bool:
        return (self.number & 1 << index) != 0

    def no_bits_set(self) -> bool:
        return self.number == 0

    def all_bits_set(self) -> bool:
        return self.number.bit_count() == self.number_of_bits

    @staticmethod
    def create_empty_bit_sequence(max_len: int = 0) -> IntegerBitSequence:
        return IntegerBitSequence(0, max_len)

    class SetBitsIterator(BitSequence.SetBitsIterator):
        def __init__(self, bit_sequence: IntegerBitSequence):
            self.number: int = bit_sequence.number

        def __next__(self) -> int:
            if self.number == 0:
                raise StopIteration
            key: int = (self.number & -self.number).bit_length() - 1  # trailing zeroes
            self.number &= self.number - 1  # reset first set bet
            return key

    def __iter__(self) -> SetBitsIterator:
        return iter(IntegerBitSequence.SetBitsIterator(self))


class BitListBitSequence(BitSequence):
    """
    Represents a bit-sequence as a list of bits.
    """

    def __init__(
        self,
        bit_list: list[bool] | None = None,
        number_of_bits: int | None = None,
    ):
        """
        :param bit_list: The list of words.
        :param number_of_bits: The number of bits represented by the word list.
        """
        if not bit_list:
            self.bit_list = BitListBitSequence._create_empty_bit_list(number_of_bits)
        else:
            self.bit_list = bit_list

        bits_in_passed_list: int = len(self.bit_list)

        if number_of_bits and number_of_bits != bits_in_passed_list:
            raise ValueError(f"Number of bits do not match with the passed bit list!")
        super().__init__(bits_in_passed_list)

    def __eq__(self, other: BitListBitSequence) -> bool:
        return isinstance(other, BitListBitSequence) and other.bit_list == self.bit_list

    def __len__(self) -> int:
        return self.number_of_bits

    def __getitem__(self, index: int) -> bool:
        return self.bit_list[index]

    def __setitem__(self, index: int, value: bool) -> None:
        self.bit_list[index] = value

    def stored_bits(self):
        return len(self)

    def update_number_of_bits(self, number_of_bits: int) -> None:
        """
        Updates the number of bits stored in this bit-sequence.
        :param number_of_bits: The number of bits to use.
        """
        if number_of_bits < self.number_of_bits:
            # Remove all bits greater than the given the number of bits
            self.bit_list = self.bit_list[0:number_of_bits]
        else:
            for _ in range(self.number_of_bits, number_of_bits):
                # Append as many bits as required
                self.bit_list.append(False)
        self.number_of_bits = number_of_bits

    def _get_largest_and_smallest_set(
        self, other: BitListBitSequence
    ) -> tuple[BitListBitSequence, BitListBitSequence]:
        """
        Computes the smallest and the largest bit-sequence, and returns them as a tuple. The first element of the tuple is the
        smallest bit-sequence and the second is the largest bit-sequence.
        :param other: The other bit-sequence.
        :return: A tuple in the form (The smallest bit-sequence, the largest bit-sequence).
        """
        # Get largest and smallest lists
        return (self, other) if len(self) < len(other) else (other, self)

    def _perform_binary_operation(
        self, other: BitListBitSequence, operation: Callable
    ) -> BitListBitSequence:
        """
        Create the resulting bit-sequence from the given operation.
        :param other: The other list bit-sequence.
        :param operation: The operation to be called.
        :return: The resulting list bit-sequence.
        """
        # Get largest and smallest lists
        smallest_bit_sequence, largest_bit_sequence = (
            self._get_largest_and_smallest_set(other)
        )

        # Prepare result bit-sequence:
        result_bit_sequence: BitListBitSequence = type(self).create_empty_bit_sequence(
            len(largest_bit_sequence)
        )

        # Compute bitwise operation for each index
        for idx in range(len(smallest_bit_sequence)):
            result_bit_sequence[idx] = operation(
                largest_bit_sequence[idx], smallest_bit_sequence[idx]
            )

        # Fill remaining spots in the result list
        for idx in range(
            len(smallest_bit_sequence),
            len(largest_bit_sequence),
        ):
            result_bit_sequence[idx] = operation(largest_bit_sequence[idx], False)

        return result_bit_sequence

    def __contains__(self, index: int) -> bool:
        return self[index]

    @staticmethod
    def create_empty_bit_sequence(number_of_bits: int = 0) -> BitListBitSequence:
        return BitListBitSequence(
            bit_list=BitListBitSequence._create_empty_bit_list(),
            number_of_bits=number_of_bits,
        )

    @staticmethod
    def _create_empty_bit_list(number_of_bits: int = 0) -> list[bool]:
        """
        Creates a list of bits represented by the word list, where all bits are set to 0.
        :param number_of_bits: The number of bits.
        :return: A list of 0-bits.
        """
        return [False for _ in range(number_of_bits)]

    class SetBitsIterator(BitSequence.SetBitsIterator):
        def __init__(self, bitlist: BitListBitSequence):
            self.bitlist: BitListBitSequence = bitlist
            self.curr_bit_idx: int = 0

        def __next__(self) -> int:
            while (
                self.curr_bit_idx < len(self.bitlist)
                and not self.bitlist[self.curr_bit_idx]
            ):
                self.curr_bit_idx += 1
            if self.curr_bit_idx >= len(self.bitlist):
                raise StopIteration
            next_result: int = self.curr_bit_idx
            self.curr_bit_idx += 1
            return next_result

    def __iter__(self) -> BitListBitSequence.SetBitsIterator:
        return iter(BitListBitSequence.SetBitsIterator(self))

    def __invert__(self) -> BitSequence:
        return type(self)._create_bit_sequence_with_list(
            [not value for value in self.bit_list], len(self)
        )

    def no_bits_set(self) -> bool:
        return all(not bit for bit in self.bit_list)

    def all_bits_set(self) -> bool:
        return all(bit for bit in self.bit_list)

    @staticmethod
    def _create_bit_sequence_with_list(
        bit_list: list[bool], number_of_bits: int
    ) -> BitListBitSequence:
        """
        Private method to create a new list bit-sequence by passing the given bit list.
        :param bit_list: The value list.
        :param number_of_bits: The number of bits in the new bit-sequence.
        :return: The new bit-sequence.
        """
        return BitListBitSequence(
            bit_list,
            number_of_bits,
        )
