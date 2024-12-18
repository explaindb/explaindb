import unittest
from system.interfaces.bit_sequence import BitSequence
from system.bit_sequences import (
    IntegerBitSequence,
    BitListBitSequence,
)


class BitSequenceTests(unittest.TestCase):
    def test_BitSequenceOperations(self):
        """
        Test whether BitSequence operations work as expected.
        """

        def test_operations(x: BitSequence, y: BitSequence):
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
            self.assertEqual(x.stored_bits(), 5)
            self.assertEqual(y.stored_bits(), 5)

        # Check for compressed bit-sequence versions
        bit_sequence_type: type[BitSequence]
        for bit_sequence_type in [
            IntegerBitSequence,
            BitListBitSequence,
        ]:
            bit_sequence_1: bit_sequence_type = (
                bit_sequence_type.create_empty_bit_sequence(5)
            )
            i: int
            for i in [1, 3]:
                bit_sequence_1.set_bit(i)
            bit_sequence_2: bit_sequence_type = (
                bit_sequence_type.create_empty_bit_sequence(5)
            )
            i: int
            for i in [1, 4]:
                bit_sequence_2.set_bit(i)
            test_operations(bit_sequence_1, bit_sequence_2)

    def test_Iterators(self):
        """
        Test Iterators explicitly for bit-sequences.
        """
        expected_bits: list[int] = [0, 1, 3]

        def test_iteration(bit_sequence: BitSequence):
            enumerated_bits: list[int] = []

            next_bit: int
            for next_bit in bit_sequence:
                enumerated_bits.append(next_bit)

            self.assertListEqual(expected_bits, enumerated_bits)

        # Check for compressed bit-sequence versions
        bit_sequence_type: type[BitSequence]
        for bit_sequence_type in [
            IntegerBitSequence,
            BitListBitSequence,
        ]:
            compressed_bit_sequence: bit_sequence_type = (
                bit_sequence_type.create_empty_bit_sequence(4)
            )
            i: int
            for i in [0, 1, 3]:
                compressed_bit_sequence.set_bit(i)
            test_iteration(compressed_bit_sequence)


if __name__ == "__main__":
    unittest.main(
        argv=["ignored", "-v"],
        defaultTest="BitSequenceTests",
        verbosity=2,
        exit=False,
    )
