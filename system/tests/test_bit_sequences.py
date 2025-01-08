import unittest
from typing import Type
from system.interfaces.bit_sequence import (
    UncompressedBitSequence,
)
from system.bit_sequences import IntegerBitSequence, BitListBitSequence, WAHBitSequence


class BitSequenceTests(unittest.TestCase):
    def test_UncompressedBitSequenceOperations(self):
        """
        Test whether BitSequence operations work as expected.
        """

        def test_operations(x: UncompressedBitSequence, y: UncompressedBitSequence):
            """
            Dedicated test to allow for testing both integer and list representations.
            :param x: The left bit-sequence.
            :param y: The right bit-sequence.
            """
            with self.assertRaises(ValueError):
                x.set_bit(50)
            with self.assertRaises(ValueError):
                x.set_bit(-1)
            self.assertNotEqual(x, y)
            self.assertEqual((~x).as_set(), {0, 2, 4})
            self.assertEqual((~y).as_set(), {0, 2, 3})
            self.assertEqual(x.as_set(), {1, 3})
            self.assertEqual((x + y).as_set(), {1, 3, 4})
            self.assertEqual((~(x + y)).as_set(), {0, 2})
            self.assertEqual((x | y).as_set(), {1, 3, 4})
            self.assertEqual((~(x | y)).as_set(), {0, 2})
            self.assertEqual((x & y).as_set(), {1})
            self.assertEqual((~(x & y)).as_set(), {0, 2, 3, 4})
            self.assertEqual((x - y).as_set(), {3})
            self.assertEqual((~(x - y)).as_set(), {0, 1, 2, 4})
            self.assertEqual((x ^ y).as_set(), {3, 4})
            self.assertEqual((~(x ^ y)).as_set(), {0, 1, 2})
            self.assertEqual((y - x).as_set(), {4})
            self.assertEqual(len(x), 5)
            self.assertEqual(len(x), len(y))
            self.assertEqual(str(x), str(x.as_set()))
            self.assertEqual(x.get_number_of_bits(), 5)
            self.assertEqual(y.get_number_of_bits(), 5)

        # Check for compressed bit-sequence versions
        bit_sequence_type: type[UncompressedBitSequence]
        for bit_sequence_type in [
            IntegerBitSequence,
            BitListBitSequence,
        ]:
            bit_sequence_1: bit_sequence_type = (
                bit_sequence_type.create_all_false_bit_sequence(5)
            )
            i: int
            for i in [1, 3]:
                bit_sequence_1.set_bit(i)
            bit_sequence_2: bit_sequence_type = (
                bit_sequence_type.create_all_false_bit_sequence(5)
            )
            i: int
            for i in [1, 4]:
                bit_sequence_2.set_bit(i)
            test_operations(bit_sequence_1, bit_sequence_2)

    def test_UncompressedIterators(self):
        """
        Test Iterators explicitly for bit-sequences.
        """
        expected_bits: list[int] = [0, 1, 3]

        def test_iteration(bit_sequence: UncompressedBitSequence):
            enumerated_bits: list[int] = []

            next_bit: int
            for next_bit in bit_sequence:
                enumerated_bits.append(next_bit)

            self.assertListEqual(expected_bits, enumerated_bits)

        # Check for compressed bit-sequence versions
        bit_sequence_type: type[UncompressedBitSequence]
        for bit_sequence_type in [
            IntegerBitSequence,
            BitListBitSequence,
        ]:
            compressed_bit_sequence: bit_sequence_type = (
                bit_sequence_type.create_all_false_bit_sequence(4)
            )
            i: int
            for i in [0, 1, 3]:
                compressed_bit_sequence.set_bit(i)
            test_iteration(compressed_bit_sequence)

    def _create_bit_sequence_and_compressed_bit_sequence(
        self,
        bit_sequence_type: type[UncompressedBitSequence],
        bit_list: list[int],
        number_of_bits: int,
    ) -> tuple[UncompressedBitSequence, WAHBitSequence]:
        bit_sequence: bit_sequence_type = (
            bit_sequence_type.create_all_false_bit_sequence(number_of_bits)
        )
        for bit in bit_list:
            bit_sequence.set_bit(bit)
        compressed_bit_sequence: WAHBitSequence = WAHBitSequence.compress_bit_sequence(
            bit_sequence
        )
        return bit_sequence, compressed_bit_sequence

    def test_Compression(self):
        def test_for_different_types(bit_sequence_type: Type[UncompressedBitSequence]):
            # Start with simple case
            simple_test_bits: list[int] = [0, 1, 3, 4, 5, 7, 8]
            (
                bit_sequence,
                compressed_bit_sequence,
            ) = self._create_bit_sequence_and_compressed_bit_sequence(
                bit_sequence_type, simple_test_bits, 9
            )

            # Assert that the compressed bit sequence contains exactly the desired bits
            self.assertEqual(compressed_bit_sequence.as_set(), set(simple_test_bits))

            # Now use compression by setting the word length to 4
            WAHBitSequence.WORD_LENGTH = 4
            compressed_bit_sequence = WAHBitSequence.compress_bit_sequence(bit_sequence)

            # The stored bits should still be equal
            self.assertEqual(compressed_bit_sequence.as_set(), set(simple_test_bits))

            # Check whether compression was utilized correctly
            self.assertEqual(3, len(compressed_bit_sequence.words))

            # First and third are literals, second is a fill
            self.assertFalse(WAHBitSequence.is_fill(compressed_bit_sequence.words[0]))
            self.assertTrue(WAHBitSequence.is_fill(compressed_bit_sequence.words[1]))
            self.assertFalse(WAHBitSequence.is_fill(compressed_bit_sequence.words[2]))

            # First contains bits 0 and 1
            self.assertEqual({0, 1}, compressed_bit_sequence.words[0].as_set())

            # Second contains bits 0, 2, and 3
            self.assertEqual({0, 2, 3}, compressed_bit_sequence.words[1].as_set())

            # Third contains bits 1 and 2
            self.assertEqual({1, 2}, compressed_bit_sequence.words[2].as_set())

            # We need to store 12 bits (we actually require more bits than in the original bit sequence!)
            self.assertEqual(12, compressed_bit_sequence.get_number_of_bits())

            # We now use more complicated examples
            # The one below verifies whether fills can be recognized correctly
            test_bits_different_merged_fills: list[int] = [
                0,
                1,
                2,
                6,
                7,
                8,
                12,
                13,
                14,
                18,
                19,
                20,
                21,
                22,
                23,
                30,
                31,
                32,
            ]

            (
                test_bits_different_merged_fills,
                compressed_bit_sequence,
            ) = self._create_bit_sequence_and_compressed_bit_sequence(
                bit_sequence_type, test_bits_different_merged_fills, 33
            )

            # They should store the same bits
            self.assertEqual(
                compressed_bit_sequence.as_set(), set(test_bits_different_merged_fills)
            )

            self.assertEqual(9, len(compressed_bit_sequence.words))

            # 1-fill word storing one fill
            self.assertEqual({0, 2, 3}, compressed_bit_sequence.words[0].as_set())

            # 0-fill word storing one fill
            self.assertEqual({0, 3}, compressed_bit_sequence.words[1].as_set())

            # 1-fill word storing one fill
            self.assertEqual({0, 2, 3}, compressed_bit_sequence.words[2].as_set())

            # 0-fill word storing one fill
            self.assertEqual({0, 3}, compressed_bit_sequence.words[3].as_set())

            # 1-fill word storing one fill
            self.assertEqual({0, 2, 3}, compressed_bit_sequence.words[4].as_set())

            # 0-fill word storing one fill
            self.assertEqual({0, 3}, compressed_bit_sequence.words[5].as_set())

            # 1-fill word storing two fills
            self.assertEqual({1, 2, 3}, compressed_bit_sequence.words[6].as_set())

            # 0-fill word storing two fills
            self.assertEqual({1, 3}, compressed_bit_sequence.words[7].as_set())

            # 1-fill word storing one fill
            self.assertEqual({0, 2, 3}, compressed_bit_sequence.words[8].as_set())

            # Still no compression
            self.assertEqual(36, compressed_bit_sequence.get_number_of_bits())

            # Test what happens when merged fills do not fit into one single filled word
            test_bits_overflow_merged_fills: list[int] = []

            for bit in range(33):
                test_bits_overflow_merged_fills.append(bit)
            for bit in range(66, 99):
                test_bits_overflow_merged_fills.append(bit)

            (
                bit_sequence_overflow_merged_fills,
                compressed_bit_sequence,
            ) = self._create_bit_sequence_and_compressed_bit_sequence(
                bit_sequence_type, test_bits_overflow_merged_fills, 101
            )

            # Compressed bit sequence and original should represent the same bits
            self.assertEqual(
                compressed_bit_sequence.as_set(), set(test_bits_overflow_merged_fills)
            )

            self.assertEqual(13, len(compressed_bit_sequence.words))

            # 3 full 1-fill words
            for i in range(0, 3):
                self.assertEqual(
                    {0, 1, 2, 3}, compressed_bit_sequence.words[i].as_set()
                )

            # 1-fill word with 2 fills
            self.assertEqual({1, 2, 3}, compressed_bit_sequence.words[3].as_set())

            # 3 full 0-fill words
            for i in range(4, 7):
                self.assertEqual({0, 1, 3}, compressed_bit_sequence.words[i].as_set())

            # 0-fill word with 2 fills
            self.assertEqual({1, 3}, compressed_bit_sequence.words[7].as_set())

            # 3 full 1-fill words
            for i in range(8, 11):
                self.assertEqual(
                    {0, 1, 2, 3}, compressed_bit_sequence.words[i].as_set()
                )

            # 1-fill word with 2 fills
            self.assertEqual({1, 2, 3}, compressed_bit_sequence.words[11].as_set())

            # Literal storing only 0-bits
            self.assertEqual(set(), compressed_bit_sequence.words[12].as_set())

            # Finally some compression
            self.assertEqual(52, compressed_bit_sequence.get_number_of_bits())

            # Check with only 0's
            empty_bit_sequence: bit_sequence_type = (
                bit_sequence_type.create_all_false_bit_sequence(1000)
            )
            compressed_bit_sequence = WAHBitSequence.compress_bit_sequence(
                empty_bit_sequence
            )

            self.assertEqual(
                empty_bit_sequence.as_set(), compressed_bit_sequence.as_set()
            )

        for bit_sequence_type in [IntegerBitSequence, BitListBitSequence]:
            test_for_different_types(bit_sequence_type)

    def test_compressed_operations(self):
        def test_for_different_types(bit_sequence_type: Type[UncompressedBitSequence]):
            def test_all_operations_for_bit_lists(
                x_bit_list: list[int], y_bit_list: list[int], number_of_bits: int
            ):
                (
                    x_bit_sequence,
                    x_compressed_bit_sequence,
                ) = self._create_bit_sequence_and_compressed_bit_sequence(
                    bit_sequence_type, x_bit_list, number_of_bits
                )
                (
                    y_bit_sequence,
                    y_compressed_bit_sequence,
                ) = self._create_bit_sequence_and_compressed_bit_sequence(
                    bit_sequence_type, y_bit_list, number_of_bits
                )

                self.assertEqual(
                    (x_bit_sequence | y_bit_sequence).as_set(),
                    (x_compressed_bit_sequence | y_compressed_bit_sequence).as_set(),
                )
                self.assertEqual(
                    (x_bit_sequence & y_bit_sequence).as_set(),
                    (x_compressed_bit_sequence & y_compressed_bit_sequence).as_set(),
                )
                self.assertEqual(
                    (x_bit_sequence ^ y_bit_sequence).as_set(),
                    (x_compressed_bit_sequence ^ y_compressed_bit_sequence).as_set(),
                )
                self.assertEqual(
                    (~x_bit_sequence).as_set(), (~x_compressed_bit_sequence).as_set()
                )
                self.assertEqual(
                    (~y_bit_sequence).as_set(), (~y_compressed_bit_sequence).as_set()
                )

            # Use small word length for easier testing
            WAHBitSequence.WORD_LENGTH = 4

            # Start with easy bit sequences, just two literals
            test_all_operations_for_bit_lists([0, 1], [0, 2, 3], 4)

            # Two fills
            test_all_operations_for_bit_lists([0, 1, 2], [3, 4, 5], 6)

            # Combine literals with fills
            test_all_operations_for_bit_lists([0, 1, 2, 3, 4], [2, 4, 5, 6, 7], 8)

            # Combine multiple fills in fill word with literals in between
            test_all_operations_for_bit_lists(
                x_bit_list=[6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 461, 462, 463],
                y_bit_list=[1, 4, 8, 9, 10, 11, 65, 101, 102, 103, 104, 105],
                number_of_bits=1000,
            )

        for bit_sequence_type in [IntegerBitSequence, BitListBitSequence]:
            test_for_different_types(bit_sequence_type)


if __name__ == "__main__":
    unittest.main(
        argv=["ignored", "-v"],
        defaultTest="BitSequenceTests",
        verbosity=2,
        exit=False,
    )
