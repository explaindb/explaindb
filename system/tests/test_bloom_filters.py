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

# Test modules use self-documenting method/class names and module-level
# fixtures, so pylint's naming and docstring checks are relaxed here.
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring
"""Tests for the Bloom filter implementation."""

import unittest
from system.indexes.bloom_filters import BloomFilter
from system.bit_sequences import (
    BitListBitSequence,
    IntegerBitSequence,
)
from system.data_classes import Address
from system.interfaces.bit_sequence import BitSequence


class BloomFilterTests(unittest.TestCase):
    def test_bloom_filters(self):
        """
        Checks functionality of BloomFilter.
        """

        class DeterministicHashIterator(BloomFilter.HashIterator):
            """
            Dummy Iterator for testing.
            """

            def __init__(
                self,
                key: int,
                number_of_hash_functions: int,
                number_of_available_bits: int,
            ):
                self.key: int = key
                self.number_of_hash_functions: int = number_of_hash_functions
                self.number_of_available_bits: int = number_of_available_bits
                self.evaluated_hash_function: int = 0

            def __next__(self):
                if self.evaluated_hash_function == self.number_of_hash_functions:
                    raise StopIteration
                result: int = (
                    self.key + self.evaluated_hash_function
                ) % self.number_of_available_bits
                self.evaluated_hash_function += 1
                return result

        # Create data objects to be used.
        all_addresses: list[Address] = [
            Address(0, "ac", "as", 1),
            Address(1, "bc", "bs", 2),
            Address(4, "cc", "cs", 3),
        ]
        bit_sequence_type: type[BitSequence]
        for bit_sequence_type in [
            BitListBitSequence,
            IntegerBitSequence,
        ]:
            bloom_filter_1: BloomFilter = BloomFilter(
                data_objects=all_addresses,
                key_attribute_name="id",
                number_of_available_bits=1,
                bit_sequence_type=bit_sequence_type,
                hash_iterator_type=DeterministicHashIterator,
            )
            self.assertEqual(bloom_filter_1.bit_sequence.as_set(), {0})
            self.assertEqual(bloom_filter_1.number_of_hash_functions, 1)

            # All keys must be contained
            adr: Address
            for adr in all_addresses:
                self.assertTrue(bloom_filter_1.contains_key(adr.id))

            # False positive
            self.assertTrue(bloom_filter_1.contains_key(2))

            # Create bigger bloom filter
            bloom_filter_5: BloomFilter = BloomFilter(
                data_objects=all_addresses,
                key_attribute_name="id",
                number_of_available_bits=5,
                bit_sequence_type=bit_sequence_type,
                hash_iterator_type=DeterministicHashIterator,
            )

            # All keys must be contained
            adr: Address
            for adr in all_addresses:
                self.assertTrue(bloom_filter_5.contains_key(adr.id))
            self.assertEqual(bloom_filter_5.bit_sequence.as_set(), {0, 1, 2, 4})
            # False positive
            self.assertTrue(bloom_filter_1.contains_key(2))
            # True negative
            self.assertFalse(bloom_filter_5.contains_key(3))

            # Check whether rng-based bloom filter also works
            bloom_filter_rng: BloomFilter = BloomFilter(
                data_objects=all_addresses,
                key_attribute_name="id",
                number_of_available_bits=10,
                bit_sequence_type=bit_sequence_type,
                hash_iterator_type=BloomFilter.RNGHashIterator,
            )

            # All keys must be contained
            adr: Address
            for adr in all_addresses:
                self.assertTrue(bloom_filter_rng.contains_key(adr.id))


if __name__ == "__main__":
    unittest.main(
        argv=["ignored", "-v"],
        defaultTest="BloomFilterTests",
        verbosity=2,
        exit=False,
    )
