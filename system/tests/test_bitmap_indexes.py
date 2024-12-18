from __future__ import annotations
import unittest
from system.interfaces.bit_sequence import BitSequence
from typing import Type, Generator
from system.bit_sequences import (
    BitListBitSequence,
    IntegerBitSequence,
)
from system.indexes.bitmap_indexes import (
    BitmapIndex,
    SortedEqualityEncodedBitmapIndex,
    UnsortedEqualityEncodedBitmapIndex,
    RangeEncodedBitmapIndex,
)
from system.data_classes import Address


class BitmapIndexTests(unittest.TestCase):
    all_addresses: list[Address] = [
        Address(0, "ac", "as", -2),
        Address(1, "bc", "bs", 1),
        Address(2, "cc", "cs", 2),
        Address(3, "dc", "ds", 3),
        Address(4, "ec", "es", 4),
        Address(5, "fc", "fs", 5),
        Address(6, "gc", "gs", 6),
        Address(7, "hc", "hs", 7),
        Address(8, "ic", "is", 8),
        Address(9, "jc", "js", 9),
        Address(10, "lc", "ls", 11),
        Address(11, "qc", "qs", 13),
    ]

    def _test_for_different_settings(
        self,
        bit_sequence_type: Type[BitSequence],
        index_type: Type[BitmapIndex],
    ):
        """
        Dedicated test to allow for testing all possible setup variations.
        :param bit_sequence_type: The bit-sequence type to use.
        """

        city_bulkload: Generator = (
            (address.city, address.id) for address in self.all_addresses
        )

        house_number_bulkload: Generator = (
            (address.house_number, address.id) for address in self.all_addresses
        )

        # Check for cities
        city_index: index_type = index_type(bit_sequence_type)

        city_index.bulkload(city_bulkload)

        # Equal
        self.assertEqual(city_index.get_equal("fc").as_set(), {5})
        self.assertEqual(city_index.get_equal("ac").as_set(), {0})
        self.assertEqual(city_index.get_equal("gg").as_set(), set())
        self.assertEqual(city_index.get_equal("gs").as_set(), set())

        # Smaller
        self.assertEqual(
            city_index.get_smaller("ac").as_set(),
            set(),
        )
        self.assertEqual(
            city_index.get_smaller("hc").as_set(),
            set(i for i in range(7)),
        )
        self.assertEqual(
            city_index.get_smaller("a").as_set(),
            set(),
        )
        self.assertEqual(
            city_index.get_smaller("zc").as_set(),
            set(i for i in range(12)),
        )
        self.assertEqual(
            city_index.get_smaller("kc").as_set(),
            set(i for i in range(10)),
        )
        self.assertEqual(
            city_index.get_smaller("mc").as_set(),
            set(i for i in range(11)),
        )
        self.assertEqual(
            city_index.get_smaller("qc").as_set(),
            set(i for i in range(11)),
        )

        # Smaller or Equal
        self.assertEqual(
            city_index.get_smaller_or_equal("ac").as_set(),
            {0},
        )
        self.assertEqual(
            city_index.get_smaller_or_equal("hc").as_set(),
            set(i for i in range(8)),
        )
        self.assertEqual(
            city_index.get_smaller_or_equal("a").as_set(),
            set(),
        )
        self.assertEqual(
            city_index.get_smaller_or_equal("zc").as_set(),
            set(i for i in range(12)),
        )
        self.assertEqual(
            city_index.get_smaller_or_equal("kc").as_set(),
            set(i for i in range(10)),
        )
        self.assertEqual(
            city_index.get_smaller_or_equal("mc").as_set(),
            set(i for i in range(11)),
        )
        self.assertEqual(
            city_index.get_smaller_or_equal("qc").as_set(),
            set(i for i in range(12)),
        )

        # Greater
        self.assertEqual(
            city_index.get_greater("ac").as_set(),
            set(i for i in range(1, 12)),
        )
        self.assertEqual(
            city_index.get_greater("hc").as_set(),
            {8, 9, 10, 11},
        )
        self.assertEqual(
            city_index.get_greater("a").as_set(),
            set(i for i in range(12)),
        )
        self.assertEqual(
            city_index.get_greater("zc").as_set(),
            set(),
        )
        self.assertEqual(
            city_index.get_greater("kc").as_set(),
            {10, 11},
        )
        self.assertEqual(
            city_index.get_greater("mc").as_set(),
            {11},
        )
        self.assertEqual(
            city_index.get_greater("qc").as_set(),
            set(),
        )

        # Greater or Equal
        self.assertEqual(
            city_index.get_greater_or_equal("ac").as_set(),
            set(i for i in range(12)),
        )
        self.assertEqual(
            city_index.get_greater_or_equal("hc").as_set(),
            {7, 8, 9, 10, 11},
        )
        self.assertEqual(
            city_index.get_greater_or_equal("a").as_set(),
            set(i for i in range(12)),
        )
        self.assertEqual(
            city_index.get_greater_or_equal("zc").as_set(),
            set(),
        )
        self.assertEqual(
            city_index.get_greater_or_equal("kc").as_set(),
            {10, 11},
        )
        self.assertEqual(
            city_index.get_greater_or_equal("mc").as_set(),
            {11},
        )
        self.assertEqual(
            city_index.get_greater_or_equal("qc").as_set(),
            {11},
        )

        # Check for house numbers
        house_number_index: index_type = index_type(bit_sequence_type)

        house_number_index.bulkload(house_number_bulkload)

        # Equal
        self.assertEqual(house_number_index.get_equal(3).as_set(), {3})
        self.assertEqual(house_number_index.get_equal(-2).as_set(), {0})
        self.assertEqual(house_number_index.get_equal(17).as_set(), set())
        # Smaller
        self.assertEqual(house_number_index.get_smaller(0).as_set(), {0})
        self.assertEqual(
            house_number_index.get_smaller(4).as_set(),
            set(i for i in range(4)),
        )
        self.assertEqual(
            house_number_index.get_smaller(10).as_set(),
            set(i for i in range(10)),
        )
        self.assertEqual(
            house_number_index.get_smaller(14).as_set(),
            set(i for i in range(12)),
        )

        # Smaller or Equal
        self.assertEqual(house_number_index.get_smaller_or_equal(0).as_set(), {0})
        self.assertEqual(
            house_number_index.get_smaller_or_equal(4).as_set(),
            set(i for i in range(5)),
        )
        self.assertEqual(
            house_number_index.get_smaller_or_equal(10).as_set(),
            set(i for i in range(10)),
        )
        self.assertEqual(
            house_number_index.get_smaller_or_equal(14).as_set(),
            set(i for i in range(12)),
        )

        # Greater
        self.assertEqual(
            house_number_index.get_greater(0).as_set(),
            set(i for i in range(1, 12)),
        )
        self.assertEqual(
            house_number_index.get_greater(4).as_set(),
            set(i for i in range(5, 12)),
        )
        self.assertEqual(
            house_number_index.get_greater(10).as_set(),
            {10, 11},
        )
        self.assertEqual(
            house_number_index.get_greater(14).as_set(),
            set(),
        )

        # Greater or Equal
        self.assertEqual(
            house_number_index.get_greater_or_equal(0).as_set(),
            set(i for i in range(1, 12)),
        )
        self.assertEqual(
            house_number_index.get_greater_or_equal(4).as_set(),
            set(i for i in range(4, 12)),
        )
        self.assertEqual(
            house_number_index.get_greater_or_equal(10).as_set(),
            {10, 11},
        )
        self.assertEqual(
            house_number_index.get_greater_or_equal(14).as_set(),
            set(),
        )

    def test_index_creation_and_operations(self):
        """
        Test whether bitmap indexes work as expected.
        """
        # Create data objects to be used.

        # Go through all possible combinations
        index_type: Type[BitmapIndex]
        for index_type in [
            SortedEqualityEncodedBitmapIndex,
            UnsortedEqualityEncodedBitmapIndex,
            RangeEncodedBitmapIndex,
        ]:
            bit_sequence_type: Type[BitSequence]
            for bit_sequence_type in [
                IntegerBitSequence,
                BitListBitSequence,
            ]:
                self._test_for_different_settings(bit_sequence_type, index_type)

        index_type: Type[BitmapIndex]
        for index_type in [
            SortedEqualityEncodedBitmapIndex,
            UnsortedEqualityEncodedBitmapIndex,
            RangeEncodedBitmapIndex,
        ]:
            bit_sequence_type: Type[BitSequence]
            for bit_sequence_type in [
                IntegerBitSequence,
                BitListBitSequence,
            ]:
                # Check for house numbers
                house_number_index: index_type = index_type(bit_sequence_type)

                house_number_bulkload: Generator = (
                    (address.house_number, address.id) for address in self.all_addresses
                )

                house_number_index.bulkload(house_number_bulkload)
                self.assertEqual(
                    house_number_index.stored_bits(), len(self.all_addresses) * 12
                )

    def test_unsorted_bit_sequence_list(self):
        """
        Check the correctness of an unsorted bit-sequence list
        """

        # Create unsortable object type
        class UnsortableObject:
            def __init__(self, value: int):
                self.value: int = value

            def __hash__(self):
                return self.value

        # Create Object containing an unsortable element
        class DataObject:
            def __init__(self, id_: int, value: int):
                self.id = id_
                self.value = UnsortableObject(value)

        # Create test data
        test_data: list[DataObject] = []
        for idx, ele in enumerate([5, 10, 15, 20]):
            test_data.append(DataObject(idx, ele))

        def generator():
            yield from (
                (data_object.value, data_object.id) for data_object in test_data
            )

        bit_sequence_type: Type[BitSequence]
        for bit_sequence_type in [
            IntegerBitSequence,
            BitListBitSequence,
        ]:
            # Create equality based index
            equ_index: UnsortedEqualityEncodedBitmapIndex = (
                UnsortedEqualityEncodedBitmapIndex(bit_sequence_type)
            )
            equ_index.bulkload(generator())

            self.assertEqual(equ_index.get_equal(test_data[0].value).as_set(), {0})
            self.assertEqual(equ_index.get_equal(test_data[1].value).as_set(), {1})
            self.assertEqual(equ_index.get_equal(test_data[2].value).as_set(), {2})
            self.assertEqual(equ_index.get_equal(test_data[3].value).as_set(), {3})
            self.assertEqual(equ_index.get_equal(UnsortableObject(8)).as_set(), set())

            # No comparison based operations allowed
            with self.assertRaises(ValueError):
                equ_index.get_smaller(UnsortableObject(8))
            with self.assertRaises(ValueError):
                equ_index.get_smaller_or_equal(UnsortableObject(8))
            with self.assertRaises(ValueError):
                equ_index.get_greater(UnsortableObject(8))
            with self.assertRaises(ValueError):
                equ_index.get_smaller_or_equal(UnsortableObject(8))

            # Creation of range encoded bitmap index not allowed
            with self.assertRaises(ValueError):
                range_index: RangeEncodedBitmapIndex = RangeEncodedBitmapIndex(
                    bit_sequence_type
                )
                range_index.bulkload(generator())


if __name__ == "__main__":
    unittest.main(
        argv=["ignored", "-v"],
        defaultTest="BitmapIndexTests",
        verbosity=2,
        exit=False,
    )
