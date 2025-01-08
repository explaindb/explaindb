from __future__ import annotations

import copy
from system.interfaces.bit_sequence import (
    BitSequence,
    UncompressedBitSequence,
    CompressedBitSequence,
)
from typing import Callable, Type, Iterator


class IntegerBitSequence(UncompressedBitSequence):
    """
    Represents a bit-sequence as an integer type.
    """

    def __init__(self, number: int = 0, represented_number_of_bits: int | None = None):
        """
        :param number: The internal integer representation of the bit-sequence.
        :param represented_number_of_bits: The number of bits in the bit-sequence.
        """
        if (
            represented_number_of_bits
            and represented_number_of_bits < number.bit_length()
        ):
            raise ValueError(
                f"Number of bits can not be smaller than the passed bit-sequence number"
            )
        super().__init__(
            represented_number_of_bits
            if represented_number_of_bits is not None
            else number.bit_length()
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

    def update_represented_number_of_bits(
        self, updated_represented_number_of_bits: int
    ) -> None:
        if updated_represented_number_of_bits < self.represented_number_of_bits:
            # Set all greater bits to 0
            self.number &= (1 << updated_represented_number_of_bits) - 1
        self.represented_number_of_bits = updated_represented_number_of_bits

    def __invert__(self) -> BitSequence:
        return type(self)(self.number ^ ((1 << len(self)) - 1), len(self))

    def __getitem__(self, index: int) -> bool:
        mask: int = 1 << index
        return mask == self.number & mask

    def __setitem__(self, index: int, value: bool) -> None:
        if value:
            self.number |= 1 << index
        else:
            self.number &= ~(1 << index)

    def __contains__(self, index: int) -> bool:
        return (self.number & 1 << index) != 0

    def all_bits_set_to_false(self) -> bool:
        return self.number == 0

    def all_bits_set_to_true(self) -> bool:
        return self.number == (1 << len(self)) - 1

    @staticmethod
    def _full_bitmask_for_range(lower_idx: int, upper_idx: int) -> int:
        """
        Create a bitmask used for checking whether all or no bits are set in the given range.
        :param lower_idx: The lower index (inclusive) of the range.
        :param upper_idx: The upper index (inclusive) of the range.
        :return: The bitmask for the range.
        """

        # We want a bitmask that has every bit in the given range set to 1. For that we first create a number
        # with the first (number of bits in the range-) bits set
        helper_mask: int = (1 << (upper_idx - lower_idx + 1)) - 1

        # This helper mask is then pushed to the actual range positions, i.e., (left_idx) times.
        return helper_mask << lower_idx

    def _get_bit_sequence_for_range(
        self,
        lower_idx: int,
        upper_idx: int,
        represented_number_of_bits: int | None = None,
    ) -> IntegerBitSequence:
        mask: int = IntegerBitSequence._full_bitmask_for_range(lower_idx, upper_idx)

        # Account for offset in number
        return IntegerBitSequence(
            (self.number & mask) >> lower_idx,
            (
                upper_idx - lower_idx + 1
                if not represented_number_of_bits
                else represented_number_of_bits
            ),
        )

    @staticmethod
    def create_all_false_bit_sequence(max_len: int = 0) -> IntegerBitSequence:
        return IntegerBitSequence(0, max_len)

    def increase_represented_integer(self, number: int) -> None:
        self.number += number

    def get_represented_integer(self) -> int:
        """
        Returns the integer represented by this bit sequence.
        :return: The integer represented by this bit sequence.
        """
        return self.number

    class SetBitsIterator(BitSequence.SetBitsIterator):
        def __init__(self, bit_sequence: IntegerBitSequence):
            self.number: int = bit_sequence.number

        def __next__(self) -> int:
            if self.number == 0:
                raise StopIteration
            key: int = (self.number & -self.number).bit_length() - 1  # trailing zeroes
            self.number &= self.number - 1  # reset first set bet
            return key


class BitListBitSequence(UncompressedBitSequence):
    """
    Represents a bit-sequence as a list of bits.
    """

    def __init__(
        self,
        bit_list: list[bool] | None = None,
        represented_number_of_bits: int | None = None,
    ):
        """
        :param bit_list: The list of words.
        :param represented_number_of_bits: The number of bits represented by the word list.
        """
        if not bit_list:
            self.bit_list = BitListBitSequence._create_empty_bit_list(
                represented_number_of_bits
            )
        else:
            self.bit_list = bit_list

        bits_in_passed_list: int = len(self.bit_list)

        if (
            represented_number_of_bits
            and represented_number_of_bits != bits_in_passed_list
        ):
            raise ValueError(f"Number of bits do not match with the passed bit list!")
        super().__init__(bits_in_passed_list)

    def __eq__(self, other: BitListBitSequence) -> bool:
        return isinstance(other, BitListBitSequence) and other.bit_list == self.bit_list

    def __getitem__(self, index: int) -> bool:
        return self.bit_list[index]

    def __setitem__(self, index: int, value: bool) -> None:
        self.bit_list[index] = value

    def update_represented_number_of_bits(
        self, updated_represented_number_of_bits: int
    ) -> None:
        if updated_represented_number_of_bits < len(self):
            # Remove all bits greater than the given the number of bits
            self.bit_list = self.bit_list[0:updated_represented_number_of_bits]
        else:
            for _ in range(len(self), updated_represented_number_of_bits):
                # Append as many bits as required
                self.bit_list.append(False)
        self.represented_number_of_bits = updated_represented_number_of_bits

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
        # Get largest and smallest lists
        (
            smallest_bit_sequence,
            largest_bit_sequence,
        ) = self._get_largest_and_smallest_set(other)

        # Prepare result bit-sequence:
        result_bit_sequence: BitListBitSequence = type(
            self
        ).create_all_false_bit_sequence(len(largest_bit_sequence))

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
    def create_all_false_bit_sequence(
        represented_number_of_bits: int = 0,
    ) -> BitListBitSequence:
        return BitListBitSequence(
            bit_list=BitListBitSequence._create_empty_bit_list(),
            represented_number_of_bits=represented_number_of_bits,
        )

    @staticmethod
    def _create_empty_bit_list(represented_number_of_bits: int = 0) -> list[bool]:
        """
        Creates a list of bits represented by the word list, where all bits are set to 0.
        :param represented_number_of_bits: The number of bits.
        :return: A list of 0-bits.
        """
        return [False for _ in range(represented_number_of_bits)]

    def _get_bit_sequence_for_range(
        self,
        lower_idx: int,
        upper_idx: int,
        represented_number_of_bits: int | None = None,
    ) -> BitListBitSequence:
        bit_sequence: BitListBitSequence = type(self).create_all_false_bit_sequence(
            upper_idx - lower_idx + 1
            if not represented_number_of_bits
            else represented_number_of_bits
        )
        for idx in range(lower_idx, upper_idx + 1):
            bit_sequence[idx - lower_idx] = self[
                idx
            ]  # Compensate for offset between new bit sequence and existing one
        return bit_sequence

    def increase_represented_integer(self, number: int) -> None:
        # Get bitlist for the number to be added
        number_bitlist: BitListBitSequence = type(self).create_all_false_bit_sequence(
            len(self)
        )
        for bit in IntegerBitSequence(number, len(self)):
            number_bitlist.set_bit(bit)

        # Binary addition
        carry_over: int = 0
        result_bitlist: list[bool] = []
        for idx in range(len(self)):
            result: int = number_bitlist[idx] + self[idx] + carry_over
            if result & 1:
                result_bitlist.append(True)
            else:
                result_bitlist.append(False)
            if result & 2:
                carry_over = 1
            else:
                carry_over = 0
        self.bit_list = result_bitlist

    def get_represented_integer(self) -> int:
        """
        Returns the integer represented by this bit sequence.
        :return: The integer represented by this bit sequence.
        """
        resulting_number: int = 0
        for bit in self:
            resulting_number += 1 << bit
        return resulting_number

    class SetBitsIterator(BitSequence.SetBitsIterator):
        def __init__(
            self,
            bitlist: BitListBitSequence,
        ):
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

    def __invert__(self) -> BitSequence:
        return type(self)._create_bit_sequence_with_list(
            [not value for value in self.bit_list], len(self)
        )

    def all_bits_set_to_false(self) -> bool:
        return all(not bit for bit in self.bit_list)

    def all_bits_set_to_true(self) -> bool:
        return all(bit for bit in self.bit_list)

    @staticmethod
    def _create_bit_sequence_with_list(
        bit_list: list[bool], represented_number_of_bits: int
    ) -> BitListBitSequence:
        """
        Private method to create a new list bit-sequence by passing the given bit list.
        :param bit_list: The value list.
        :param represented_number_of_bits: The number of bits in the new bit-sequence.
        :return: The new bit-sequence.
        """
        return BitListBitSequence(
            bit_list,
            represented_number_of_bits,
        )


class WAHBitSequence(CompressedBitSequence):
    """
    Compressed bit sequence implementing Word-Aligned-Hybrid Encoding.
    """

    WORD_LENGTH: int = 64  # 64 Bits per Word

    class WordListCreator:
        """
        Helper class to create a list of words. Used during compression and bit-wise operations. The idea that we keep
        an inner counter that tracks how many consecutive fills we already found. Whenever we find a new represented
        fill bit, a literal is found, or the fill word becomes fill, we add a single fill word containing all these
        fill words to the list of words.
        """

        def __init__(
            self, bit_sequence_type: Type[UncompressedBitSequence] = IntegerBitSequence
        ):
            # The current word list, will later be used to create the compressed bit sequence
            self.words: list[UncompressedBitSequence] = []

            # How many fills can be stored within one fill word?
            self.max_number_of_merged_fills_in_one_word: int = (
                WAHBitSequence.max_number_of_merged_fills_in_one_word()
            )

            # Used to determine when to create a new fill word merging all consecutive fills
            self.current_number_of_consecutive_equal_fills: int = 0

            # What underlying bit sequence type should be used to represent words
            self.bit_sequence_type: Type[UncompressedBitSequence] = bit_sequence_type

        def _merge_consecutive_equal_fills(self) -> None:
            """
            Adds all consecutive equal fills to the last word in the word list. Assumes that all fills fit into this
            single fill word.
            """
            # Only if we already a fill at the last position is it possible to actually combine them
            if len(self.words) > 0 and WAHBitSequence.is_fill(self.words[-1]):
                self.words[-1].increase_represented_integer(
                    self.current_number_of_consecutive_equal_fills
                )

            # We just merged all current fills, so our number of consecutive fills must be 0 now
            self.current_number_of_consecutive_equal_fills = 0

        def add_fills(self, new_fill_bit: bool, number_of_added_fills: int = 1) -> None:
            """
            Creates a new fill word if necessary, or increments current number of consecutive fills if possible.
            :param new_fill_bit: The bit represented by the new fill word. True if it represents a 1-fill,
            False otherwise.
            :param number_of_added_fills: The number of consecutive fills to add.
            """
            # Decide whether we need to create a fill word. This is the case, if the previous word is a
            # literal or not existent, if the last fill word is full,
            # or if the new fill to be inserted represents different bits than the existing one.
            if (
                len(self.words) == 0  # No words created yet
                or not WAHBitSequence.is_fill(
                    self.words[-1]
                )  # The last bit sequence is not a fill
                or WAHBitSequence.get_represented_bit_of_fill_word(self.words[-1])
                != new_fill_bit  # The last fill represents a different fill
                or self.current_number_of_consecutive_equal_fills  # No more fills can merge
                == self.max_number_of_merged_fills_in_one_word
            ):
                self._merge_consecutive_equal_fills()
                self.words.append(
                    WAHBitSequence.create_fill_word(
                        new_fill_bit, self.bit_sequence_type
                    )
                )

            # Add new fill words, until all added fills were merged, or can be merged in the future
            while (
                number_of_added_fills + self.current_number_of_consecutive_equal_fills
                > self.max_number_of_merged_fills_in_one_word
            ):
                # Add as many fills as possible to the current fill chain
                number_of_fills_fitting_into_current_word: int = (
                    self.max_number_of_merged_fills_in_one_word
                    - self.current_number_of_consecutive_equal_fills
                )
                self.current_number_of_consecutive_equal_fills += (
                    number_of_fills_fitting_into_current_word
                )
                self._merge_consecutive_equal_fills()
                self.words.append(
                    WAHBitSequence.create_fill_word(
                        new_fill_bit, self.bit_sequence_type
                    )
                )
                number_of_added_fills -= number_of_fills_fitting_into_current_word

            # Increase number of consecutive same fills, assumes will not be overflown by than number!
            self.current_number_of_consecutive_equal_fills += number_of_added_fills

        def get_resulting_word_list(self) -> list[UncompressedBitSequence]:
            """
            Obtains the final word list.
            :return: The final compressed word list.
            """
            # Merge any remaining fills
            self._merge_consecutive_equal_fills()
            return self.words

        def add_literal(self, literal_word: UncompressedBitSequence) -> None:
            """
            Adds the given literal word to the word list.
            :param literal_word: The literal word to add.
            """
            # Upon seeing a new literal, we need to merge all previous fills.
            self._merge_consecutive_equal_fills()
            self.words.append(literal_word)

        def add_uncompressed_bit_sequence_as_literal(
            self, uncompressed_bit_sequence: UncompressedBitSequence
        ) -> None:
            """
            Adds the given uncompressed bit sequence as literal to the word list.
            :param uncompressed_bit_sequence: The bit sequence to add.
            """
            # Make it a literal, i.e., add another represented bit, which is just 0.
            uncompressed_bit_sequence.update_represented_number_of_bits(
                WAHBitSequence.WORD_LENGTH
            )
            self.add_literal(uncompressed_bit_sequence)

        def add_from_uncompressed_bit_sequence(
            self, bit_sequence: UncompressedBitSequence
        ) -> None:
            """
            Obtains a bit sequence of length (WORD_LENGTH - 1) and either compresses it into a literal of fill word.
            :param bit_sequence: The uncompressed bit sequence to add.
            """
            if bit_sequence.all_bits_set_to_false():
                # We found a 0-fill
                self.add_fills(False)
            elif bit_sequence.all_bits_set_to_true():
                # We found a 1-fill word
                self.add_fills(True)
            else:
                # No fill word can be identified, create a literal word
                self.add_uncompressed_bit_sequence_as_literal(bit_sequence)

    def __init__(
        self,
        represented_number_of_bits: int,
        words: list[UncompressedBitSequence],
        bit_sequence_type: Type[UncompressedBitSequence] = IntegerBitSequence,
    ):
        """
        :param words: The words represented by bit sequences.
        :param represented_number_of_bits: The number of bits represented by this bit sequence.
        :param bit_sequence_type: The bit sequence to represent the underlying bit sequence. Only used if no word are passed.
        """
        super().__init__(represented_number_of_bits)

        if not words:  # None or empty list
            self.bit_sequence_type: Type[UncompressedBitSequence] = bit_sequence_type
        else:
            self.bit_sequence_type: Type[UncompressedBitSequence] = type(words[0])
        self.words: list[UncompressedBitSequence] = words

    @staticmethod
    def max_number_of_merged_fills_in_one_word() -> int:
        """
        Returns the maximal number of fill words that can be merged into a single fill word.
        :return: The maximal number of fill words that can be merged into a single fill word.
        """

        # In a fill word, we have (word_length) bits, 1 bit is used for identifying a fill word, 1 bit is used to decide
        # whether the fill word represent 1's or 0's and the remaining (word_length - 2) represent the number of
        # merged fill words
        return (1 << (WAHBitSequence.WORD_LENGTH - 2)) - 1

    @staticmethod
    def create_fill_word(
        represented_bit: bool, bit_sequence_type: Type[UncompressedBitSequence]
    ) -> UncompressedBitSequence:
        """
        Creates a fill word representing (WORD_LENGTH - 1) of the represented bit.
        :param represented_bit: The represented bit.
        :param bit_sequence_type: The bit sequence type to represent the underlying bit sequence.
        :return: The fill word.
        """
        new_fill_word: UncompressedBitSequence = (
            bit_sequence_type.create_all_false_bit_sequence(WAHBitSequence.WORD_LENGTH)
        )

        # Fill words are signaled with the last bit set to 1
        new_fill_word[WAHBitSequence.WORD_LENGTH - 1] = True

        # The second-to-last bit represents which bit the fill represents
        new_fill_word[WAHBitSequence.WORD_LENGTH - 2] = represented_bit
        return new_fill_word

    @staticmethod
    def create_literal_word(
        bit_sequence_type: Type[UncompressedBitSequence],
    ) -> UncompressedBitSequence:
        """
        Creates a literal word representing (WORD_LENGTH - 1) bits
        :param bit_sequence_type: The bit sequence to represent the underlying bit sequence.
        :return: The literal word.
        """
        # We do not need to set anything, as literals are represented by a 0 at the last bit, and an empty
        # bit sequence has no set bits by default
        return bit_sequence_type.create_all_false_bit_sequence(
            WAHBitSequence.WORD_LENGTH
        )

    @staticmethod
    def get_represented_bit_of_fill_word(fill_word: UncompressedBitSequence) -> bool:
        """
        Returns the represented bit of a fill word. Assumes that the passed word is a fill!
        :param fill_word: The fill word.
        :return: True, if 1 is represented, False if 0 is represented.
        """
        return fill_word[WAHBitSequence.WORD_LENGTH - 2]

    @staticmethod
    def get_number_of_fills_represented_by_fill_word(
        fill_word: UncompressedBitSequence,
    ) -> int:
        """
        Returns the number of fills represented by a fill word. Assumes that the passed word is a fill!
        :param fill_word: The fill word.
        :return: The number of represented fills.
        """
        return fill_word.get_bit_sequence_for_range(
            0, WAHBitSequence.WORD_LENGTH - 3
        ).get_represented_integer()

    @staticmethod
    def compress_bit_sequence(bit_sequence: UncompressedBitSequence) -> WAHBitSequence:
        # The compression works as follows:
        # Traverse the bit sequence above in chunks of (WORD_LENGTH - 1) bits, and decide for each whether it is
        # possible to compress it into a fill, or whether a literal is required to present it.
        # In order to simplify the logic, a helper class called a word list creator is utilized in order to deal with
        # deciding how chunks can be processes, so this function only traverses the uncompressed bit sequence and lets
        # the word list creator deal with the rest

        # Left range index (including) of the bit sequence
        lower_bit_sequence_idx: int = 0

        # Right range index (including) of the bit sequence. Note that the compressed bit sequence has words of length
        # WORD_LENGTH, meaning the uncompressed bit sequence will be split along (WORD_LENGTH - 1)!
        upper_bit_sequence_idx: int = WAHBitSequence.WORD_LENGTH - 2

        # Helper structure to create the final list of words
        word_list_creator: WAHBitSequence.WordListCreator = (
            WAHBitSequence.WordListCreator(type(bit_sequence))
        )

        # Traverse through all bit sequence chunks
        while upper_bit_sequence_idx < len(bit_sequence):
            word_list_creator.add_from_uncompressed_bit_sequence(
                bit_sequence.get_bit_sequence_for_range(
                    lower_bit_sequence_idx,
                    upper_bit_sequence_idx,
                )
            )

            # We switch to a new chunk in the uncompressed bit sequence, i.e., the new lower end of the range starts
            # right after the previous upper end, whereas the new upper end has to be increased by the number of bits
            # than can be compressed by a single word, which is (WORD_LENGTH - 1)
            lower_bit_sequence_idx = upper_bit_sequence_idx + 1
            upper_bit_sequence_idx += WAHBitSequence.WORD_LENGTH - 1

        # There might be one chunk left, which does not contain (WORD_LENGTH - 1)
        # which will be treated as a literal, as all words must have the same length
        if lower_bit_sequence_idx < len(bit_sequence):

            # The upper idx should be at the position where the uncompressed bit sequence ends
            # That means we take current lower index - 1, and add how much of the uncompressed bit sequence is left
            upper_bit_sequence_idx: int = (
                lower_bit_sequence_idx
                - 1
                + (len(bit_sequence) % (WAHBitSequence.WORD_LENGTH - 1))
            )

            word_list_creator.add_uncompressed_bit_sequence_as_literal(
                bit_sequence.get_bit_sequence_for_range(
                    lower_idx=lower_bit_sequence_idx,
                    upper_idx=upper_bit_sequence_idx,
                    represented_number_of_bits=WAHBitSequence.WORD_LENGTH - 1,
                )
            )

        # Bit sequence is compressed now
        return WAHBitSequence(
            represented_number_of_bits=bit_sequence.represented_number_of_bits,
            bit_sequence_type=type(bit_sequence),
            words=word_list_creator.get_resulting_word_list(),
        )

    def __eq__(self, other: WAHBitSequence) -> bool:
        return isinstance(other, WAHBitSequence) and self.words == other.words

    def __and__(self, other: WAHBitSequence) -> WAHBitSequence:
        return self._perform_binary_operation(
            other, lambda x, y: x & y, WAHBitSequence.and_literal_fill
        )

    def __or__(self, other: WAHBitSequence) -> WAHBitSequence:
        return self._perform_binary_operation(
            other, lambda x, y: x | y, WAHBitSequence.or_literal_fill
        )

    def __xor__(self, other: WAHBitSequence) -> WAHBitSequence:
        return self._perform_binary_operation(
            other, lambda x, y: x ^ y, WAHBitSequence.xor_literal_fill
        )

    @staticmethod
    def is_fill(word: UncompressedBitSequence) -> bool:
        """
        Checks if the given word is a fill word.
        :param word: The index of the word.
        :return: True, if the word is a fill word.
        """
        return word[
            WAHBitSequence.WORD_LENGTH - 1
        ]  # A fill is represented by a set last bit

    @staticmethod
    def xor_literal_fill(
        literal: UncompressedBitSequence,
        fill: UncompressedBitSequence,
        word_list_creator: WAHBitSequence.WordListCreator,
    ) -> None:
        """
        Computes the logical xor between the literal and fill word.
        :param literal: The literal word.
        :param fill: The fill word.
        :param word_list_creator: Helper structure to create the underlying word list.
        :return: The resulting word, either as fill or as literal.
        """
        if WAHBitSequence.get_represented_bit_of_fill_word(fill):
            # X ^ 1 = ~X
            inverted_literal: UncompressedBitSequence = ~literal

            # Unset last bit since it still represents a literal
            inverted_literal.unset_bit(WAHBitSequence.WORD_LENGTH - 1)
            word_list_creator.add_literal(inverted_literal)
        else:
            # X ^ 0 = X
            word_list_creator.add_literal(copy.deepcopy(literal))

    @staticmethod
    def and_literal_fill(
        literal: UncompressedBitSequence,
        fill: UncompressedBitSequence,
        word_list_creator: WAHBitSequence.WordListCreator,
    ) -> None:
        """
        Computes the logical and between the literal and fill word.
        :param literal: The literal word.
        :param fill: The fill word.
        :param word_list_creator: Helper structure to create the underlying word list.
        :return: The resulting word, either as fill or as literal.
        """
        if WAHBitSequence.get_represented_bit_of_fill_word(fill):
            # X & 1 = X
            word_list_creator.add_literal(copy.deepcopy(literal))
        else:
            # X & 0 = 0
            word_list_creator.add_fills(False)

    @staticmethod
    def or_literal_fill(
        literal: UncompressedBitSequence,
        fill: UncompressedBitSequence,
        word_list_creator: WAHBitSequence.WordListCreator,
    ) -> None:
        """
        Computes the logical or between the literal and fill word.
        :param literal: The literal word.
        :param fill: The fill word.
        :param word_list_creator: Helper structure to create the underlying word list.
        :return: The resulting word, either as fill or as literal.
        """
        if WAHBitSequence.get_represented_bit_of_fill_word(fill):
            # X | 1 = 1
            word_list_creator.add_fills(True)
        else:
            # X | 0 = X
            word_list_creator.add_literal(copy.deepcopy(literal))

    def _perform_binary_operation(
        self,
        other: WAHBitSequence,
        operation: Callable,
        literal_fill_operation: Callable,
    ) -> WAHBitSequence:
        # The general idea of the algorithm is as follows:
        # Traverse both compressed bit sequences word by word (storing an index for both operands)
        # and apply the bitwise-operation on both of these words.
        # The resulting bit sequences are then further processed by the word list creator in order to compress them.
        # Special consideration have to made for operations involving both a literal and a fill, for which dedicated
        # operation functions have been implemented to optimize the computation.
        # Another important factor is how many fills of a fill word have been processed already, such that when you
        # compare two words of the compressed bit sequence, they always refer to the same bits in the respective
        # uncompressed bit sequence. For this, another index is established. In order to manage both indices for both
        # operands, a dedicated index helper class, defined below, is utilized.

        assert len(self) == len(
            other
        ), "Both compressed bit sequences must have the same length"

        class IndexHelper:
            """
            Helper class storing which at which index the operands are, and how many of their current fills (if any)
            still need to be processed.
            """

            def __init__(
                self,
                words: list[UncompressedBitSequence],
            ):
                """
                :param words: The words of the operand in question.
                """
                # What is the current index in the word index
                self.word_index: int = 0

                # The words of the corresponding operand
                self.words: list[UncompressedBitSequence] = words

                # How many fills of the current fill word still need to be processed
                self.remaining_fills: int = (
                    0
                    if not WAHBitSequence.is_fill(self.get_current_word())
                    else WAHBitSequence.get_number_of_fills_represented_by_fill_word(
                        self.get_current_word()
                    )
                )

            def index_within_bounds(self) -> bool:
                """
                Decides whether the current word index is within the bounds of the word list.
                :return: True, if the index is within bounds, False otherwise.
                """
                return self.word_index < len(self.words)

            def get_current_word(self) -> UncompressedBitSequence:
                """
                Returns the word at the current index in the word list.
                :return: The word at the current index in the word list.
                """
                return self.words[self.word_index]

        # Create helper structures to store additional information we need about both lists during the traversal
        self_index_helper: IndexHelper = IndexHelper(self.words)
        other_index_helper: IndexHelper = IndexHelper(other.words)

        # Helper structure to create the final word list
        word_list_creator: WAHBitSequence.WordListCreator = (
            WAHBitSequence.WordListCreator(self.bit_sequence_type)
        )

        # Go through each word of both indices, as long as both are still within bounds
        while all(
            index_helper.index_within_bounds()
            for index_helper in [self_index_helper, other_index_helper]
        ):
            # Which words are fills
            self_fill, other_fill = WAHBitSequence.is_fill(
                self_index_helper.get_current_word()
            ), WAHBitSequence.is_fill(other_index_helper.get_current_word())

            # Check which kind of words we are dealing with
            if not self_fill and not other_fill:
                # Easy case, both are literals, just perform the binary operation on both
                result_word: UncompressedBitSequence = operation(
                    self_index_helper.get_current_word(),
                    other_index_helper.get_current_word(),
                )

                # Ignore last bit in word
                result_word.update_represented_number_of_bits(
                    WAHBitSequence.WORD_LENGTH - 1
                )

                # Use word list creator in order to deal with any compression techniques
                word_list_creator.add_from_uncompressed_bit_sequence(result_word)

            elif self_fill and other_fill:
                # Both are fills

                # This decides how many merged fills can be processed within this single step
                min_remaining_fills: int = min(
                    self_index_helper.remaining_fills,
                    other_index_helper.remaining_fills,
                )

                # Add resulting fill to word list
                word_list_creator.add_fills(
                    operation(
                        WAHBitSequence.get_represented_bit_of_fill_word(
                            self.words[self_index_helper.word_index]
                        ),
                        WAHBitSequence.get_represented_bit_of_fill_word(
                            other.words[other_index_helper.word_index]
                        ),
                    ),
                    min_remaining_fills,
                )
                for index_helper in [self_index_helper, other_index_helper]:
                    # Never below 0, because we took the minimum of both
                    index_helper.remaining_fills -= min_remaining_fills

            elif self_fill:
                # Other is literal
                # Perform dedicated operation combining a literal and a fill
                literal_fill_operation(
                    literal=other_index_helper.get_current_word(),
                    fill=self_index_helper.get_current_word(),
                    word_list_creator=word_list_creator,
                )
                self_index_helper.remaining_fills -= 1

            elif other_fill:
                # Self is literal
                # Perform dedicated operation combining a literal and a fill
                literal_fill_operation(
                    literal=self_index_helper.get_current_word(),
                    fill=other_index_helper.get_current_word(),
                    word_list_creator=word_list_creator,
                )
                other_index_helper.remaining_fills -= 1

            # Now increase indexes, and adapt remaining fills
            for index_helper in [self_index_helper, other_index_helper]:
                if index_helper.remaining_fills == 0:
                    # We either processed a literal, or the current fill has no remaining fills to process
                    # -> go the next word
                    index_helper.word_index += 1

                    # Update remaining fills in case the next word is a fill
                    if index_helper.index_within_bounds() and WAHBitSequence.is_fill(
                        index_helper.get_current_word()
                    ):
                        # Process all fills in the word
                        index_helper.remaining_fills = (
                            WAHBitSequence.get_number_of_fills_represented_by_fill_word(
                                index_helper.get_current_word()
                            )
                        )

        # Computation is finished, as both indexes are exhausted
        return WAHBitSequence(
            represented_number_of_bits=len(self),
            bit_sequence_type=self.bit_sequence_type,
            words=word_list_creator.get_resulting_word_list(),
        )

    def __invert__(self) -> WAHBitSequence:
        # Go through each word invert it. We have two cases there:
        # 1. We have a literal word -> invert everything except the signal bit
        # 2. We have a fill word -> invert only the bit signaling whether we have a 0- or 1-fill

        # Create deep copy to prevent changing the existing bit sequence
        inverted_words: list[UncompressedBitSequence] = []

        # Position in fill words that represents which bit was compressed
        fill_bit_position: int = WAHBitSequence.WORD_LENGTH - 2

        # Iterate through each word
        for word in self.words:
            if WAHBitSequence.is_fill(word):
                # We have a fill -> copy original word and invert represented bit
                inverted_words.append(copy.deepcopy(word))
                inverted_words[-1][fill_bit_position] = not word[fill_bit_position]
            else:
                # We have a literal -> invert all bits but the signal bit
                inverted_words.append(~word)
                inverted_words[-1][WAHBitSequence.WORD_LENGTH - 1] = False

        return WAHBitSequence(
            words=inverted_words,
            represented_number_of_bits=len(self),
        )

    def get_number_of_bits(self) -> int:
        """
        Returns the number of bits stored in this bit-sequence.
        :return: The number of bits stored.
        """
        return WAHBitSequence.WORD_LENGTH * len(self.words)

    class FillIterator(BitSequence.SetBitsIterator):
        """
        An iterator to traverse a fill word.
        """

        def __init__(self, fill_word: UncompressedBitSequence, bit_index: int):
            # How many fills are represented by this word?
            self.number_of_fills: int = (
                WAHBitSequence.get_number_of_fills_represented_by_fill_word(fill_word)
            )

            # Starting index of the iteration
            self.bit_idx: int = bit_index

            # The index of the current fill we are processing
            self.curr_fill_idx: int = 0

            # Which bit are we processing in the current fill?
            self.idx_within_curr_fill: int = 0

        def __next__(self) -> int:
            if self.idx_within_curr_fill == WAHBitSequence.WORD_LENGTH - 1:
                # We have processed all bits of a fill -> move to next fill
                self.curr_fill_idx += 1
                self.idx_within_curr_fill = 0

            # Check whether all fills have been processed
            if self.curr_fill_idx == self.number_of_fills:
                raise StopIteration

            # Move to next bit
            result_bit: int = self.bit_idx
            self.bit_idx += 1
            self.idx_within_curr_fill += 1
            return result_bit

    class LiteralIterator(BitSequence.SetBitsIterator):
        def __init__(self, literal_word: UncompressedBitSequence, bit_index: int):
            # Use regular iterator of an uncompressed bit sequence
            self.set_bit_iterator: Iterator[int] = iter(literal_word)

            # Set starting index
            self.bit_idx: int = bit_index

        def __next__(self) -> int:
            return self.bit_idx + next(self.set_bit_iterator)

    class SetBitsIterator(BitSequence.SetBitsIterator):
        def __init__(
            self,
            compressed_bit_sequence: WAHBitSequence,
        ):
            self.compressed_bit_sequence: WAHBitSequence = compressed_bit_sequence
            self.curr_word_idx: int = -1

            # We require a second idx in order to account for offsets created by fill words storing multiple fills
            # This index is only used to decide which bits are represented by the current word
            self.bit_idx: int = -(WAHBitSequence.WORD_LENGTH - 1)

            # Either iterating through a fill, where it just repeats the represented bit as many times as represented
            # by the fill or a literal, which is just a literal iterator
            self.curr_word_iterator: BitSequence.SetBitsIterator | None = (
                self.get_next_iterator()
            )

        def get_current_word(self) -> UncompressedBitSequence:
            """
            Returns the current word.
            :return: The current word.
            """
            return self.compressed_bit_sequence.words[self.curr_word_idx]

        def get_next_iterator(self) -> BitSequence.SetBitsIterator | None:
            """
            Returns the next iterator.
            :return: The iterator.
            """
            if self.curr_word_idx >= 0 and WAHBitSequence.is_fill(
                self.get_current_word()
            ):
                # Advance this index by as many fills are represented by this fill word
                self.bit_idx += (
                    WAHBitSequence.get_number_of_fills_represented_by_fill_word(
                        self.get_current_word()
                    )
                    * (WAHBitSequence.WORD_LENGTH - 1)
                )
            else:
                # We have a literal, thus we also only have to move one step here
                self.bit_idx += WAHBitSequence.WORD_LENGTH - 1

            # Move to next word in list
            self.curr_word_idx += 1

            # Do have traversed all words?
            if self.curr_word_idx == len(self.compressed_bit_sequence.words):
                # No iterator can found anymore
                return None

            # Check whether we have to traverse a fill or a literal
            if WAHBitSequence.is_fill(self.get_current_word()):
                if WAHBitSequence.get_represented_bit_of_fill_word(
                    self.get_current_word()
                ):
                    # If we have a fill representing 1's, create an iterator for it
                    return WAHBitSequence.FillIterator(
                        self.get_current_word(), self.bit_idx
                    )

                # Only 0's are represented, meaning we can skip this word entirely, try next word
                return self.get_next_iterator()

            # Return literal iterator
            return WAHBitSequence.LiteralIterator(self.get_current_word(), self.bit_idx)

        def __next__(self) -> int:
            while True:
                # No next iterator was found -> we are done
                if self.curr_word_iterator is None:
                    raise StopIteration
                try:
                    next_bit = next(self.curr_word_iterator)

                    # The last word might contain too many bits, which we should not iterate
                    if next_bit >= len(self.compressed_bit_sequence):
                        raise StopIteration
                    return next_bit

                # When the current iterator has completed its run, move to the next
                except StopIteration:
                    self.curr_word_iterator = self.get_next_iterator()
