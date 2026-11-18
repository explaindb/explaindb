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
"""Tests for the storage layer."""

from system.storage.storage_layer import StorageLayer, AddressConversionStrategy
from system.tests.abstract_unit_test import AbstractUnitTest


class StorageLayerTest(AbstractUnitTest):

    def test_storage_layer_basics(self):

        # simple storage hierarchy with only two layers:
        sl_ssd: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=100, name="SSD"
        )
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=5, name="DRAM", layer_below=sl_ssd
        )
        # insert 10 entries to force eviction; eviction always picks the largest key, so from "5" on each put
        # evicts the key put just before it: DRAM keeps "0"-"3" and "9", the SSD receives "4"-"8":
        for i in range(10):
            sl_DRAM.put(str(i), str(i))

        # sl_DRAM.show()
        # sl_ssd.show()

        self.assertEqual(sl_DRAM.size(), 5)
        self.assertEqual(sl_ssd.size(), 5)

        self.assertListEqual(list(sl_DRAM.storage.keys()), ["0", "1", "2", "3", "9"])
        self.assertListEqual(list(sl_ssd.storage.keys()), ["4", "5", "6", "7", "8"])

        # test get: "0" is a hit; the miss on "5" copies it up from the SSD (it stays there too) and evicts
        # the largest DRAM key "9" to the SSD:
        self.assertEqual(sl_DRAM.get("0"), "0")
        self.assertEqual(sl_DRAM.get("5"), "5")

        self.assertListEqual(list(sl_DRAM.storage.keys()), ["0", "1", "2", "3", "5"])
        self.assertListEqual(
            list(sl_ssd.storage.keys()), ["4", "5", "6", "7", "8", "9"]
        )

        # sl_DRAM.show()
        # sl_ssd.show()

        # test fix: "5" is the largest key and hence the eviction candidate, so the next put cannot make room:
        sl_DRAM.fix("5")
        with self.assertRaises(ValueError):
            sl_DRAM.put("42", "42")

    def test_storage_layer_prefix_addressing(self):

        class PrefixConversion(AddressConversionStrategy[str]):
            def split_address(self, address: str) -> tuple[str, str]:
                """Split into (page id = first character, offset = rest of the address)."""
                return address[:1], address[1:]

        # simple storage hierarchy with only two layers:
        # adding a prefix conversion strategy to the DRAM layer
        sl_ssd: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=100, name="SSD"
        )
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=5,
            name="DRAM",
            layer_below=sl_ssd,
            address_conversion_strategy=PrefixConversion(),
        )

        # insert some "pages"
        # a page id is a 1-digit character -> only 10 different pages possible
        # each page contains only 4-characters (you can interpret each character to symbolise a byte of data in storage)
        sl_ssd.put("0", "p7z7")
        sl_ssd.put("1", "d567")
        sl_ssd.put("2", "090s")
        sl_ssd.put("3", "0(2$")

        # from the point of view of DRAM, an address is a 2-digit string
        # the prefix is the first digit of the address, it signals the page id
        # the second digit signals the offset within the page

        self.assertEqual(sl_DRAM.get("21"), "9")
        self.assertEqual(sl_DRAM.get("23"), "s")
        self.assertEqual(sl_DRAM.get("33"), "$")

        # sl_DRAM.show()
        # sl_ssd.show()

    def test_storage_layer_prefix_addressing_eviction_keeps_layer_below_intact(self):
        """Under an address-conversion strategy, eviction drops the cached sub-unit locally and leaves every
        page in the layer below unchanged."""

        class PrefixConversion(AddressConversionStrategy[str]):
            def split_address(self, address: str) -> tuple[str, str]:
                """Split into (page id, offset within the page)."""
                return address[:1], address[1:]

        sl_ssd: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=100, name="SSD"
        )
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=2,
            name="DRAM",
            layer_below=sl_ssd,
            address_conversion_strategy=PrefixConversion(),
        )
        sl_ssd.put("0", "p0aa")
        sl_ssd.put("1", "p1bb")
        sl_ssd.put("2", "p2cc")

        # DRAM holds at most 2 entries; the third distinct get forces one
        # eviction (the eviction candidate is the max key, "12").
        self.assertEqual(sl_DRAM.get("01"), "0")  # "p0aa"[1]
        self.assertEqual(sl_DRAM.get("12"), "b")  # "p1bb"[2]
        self.assertEqual(sl_DRAM.get("23"), "c")  # "p2cc"[3]

        # the evicted key is dropped locally ...
        self.assertNotIn("12", sl_DRAM.storage)
        # ... and every page in the layer below is untouched.
        self.assertEqual(sl_ssd.get("0"), "p0aa")
        self.assertEqual(sl_ssd.get("1"), "p1bb")
        self.assertEqual(sl_ssd.get("2"), "p2cc")

    def test_storage_layer_prefix_addressing_caches_in_upper_layer(self):
        """
        The extracted sub-unit is cached in the upper layer, so a second get is
        served locally without consulting the layer below again.
        """

        class PrefixConversion(AddressConversionStrategy[str]):
            def split_address(self, address: str) -> tuple[str, str]:
                """Split into (page id, offset within the page)."""
                return address[:1], address[1:]

        sl_ssd: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=100, name="SSD"
        )
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=5,
            name="DRAM",
            layer_below=sl_ssd,
            address_conversion_strategy=PrefixConversion(),
        )
        sl_ssd.put("2", "090s")

        # first get populates the DRAM cache from the SSD page ...
        self.assertEqual(sl_DRAM.get("21"), "9")
        self.assertIn("21", sl_DRAM.storage)

        # ... so it is still served after the SSD entry is removed.
        sl_ssd.delete("2")
        self.assertEqual(sl_DRAM.get("21"), "9")
