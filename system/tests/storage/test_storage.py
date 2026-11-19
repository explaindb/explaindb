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


class PrefixConversion(AddressConversionStrategy[str]):
    """Splits an address into the page id (its first character) and the offset within the page (the rest)."""

    def split_address(self, address: str) -> tuple[str, str]:
        """See :meth:`AddressConversionStrategy.split_address`."""
        return address[:1], address[1:]


class StorageLayerTest(AbstractUnitTest):

    def test_storage_layer_basics(self) -> None:
        """A full layer evicts its largest key to the layer below, a miss copies the entry up from the layer
        below, and eviction skips fixed keys: it evicts the largest key that is not fixed.
        """

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

        # test fix: "5" is the largest key but fixed, so the next put evicts "3", the largest key that is not
        # fixed, to the SSD:
        sl_DRAM.fix("5")
        sl_DRAM.put("42", "42")
        self.assertListEqual(list(sl_DRAM.storage.keys()), ["0", "1", "2", "5", "42"])
        self.assertListEqual(
            list(sl_ssd.storage.keys()), ["4", "5", "6", "7", "8", "9", "3"]
        )

    def test_storage_layer_eviction_fails_if_all_keys_are_fixed(self) -> None:
        """If every key of a full layer is fixed, there is no eviction candidate: evicting or putting a new key
        raises ValueError and changes neither layer, while overwriting a stored key still works.
        """

        # a full DRAM layer whose two keys are both fixed:
        sl_ssd: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=100, name="SSD"
        )
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=2, name="DRAM", layer_below=sl_ssd
        )
        sl_DRAM.put("a", "a")
        sl_DRAM.put("b", "b")
        sl_DRAM.fix("a")
        sl_DRAM.fix("b")

        # there is no key to evict, so neither choosing a candidate nor evicting works:
        with self.assertRaisesRegex(ValueError, "can be evicted"):
            sl_DRAM.choose_eviction_candidate()
        with self.assertRaisesRegex(ValueError, "can be evicted"):
            sl_DRAM.evict()

        # so a put of a new key fails, and both layers keep their contents:
        with self.assertRaisesRegex(ValueError, "can be evicted"):
            sl_DRAM.put("c", "c")
        self.assertListEqual(list(sl_DRAM.storage.keys()), ["a", "b"])
        self.assertEqual(sl_ssd.size(), 0)

        # overwriting a stored key needs no eviction and succeeds:
        sl_DRAM.put("a", "A")
        self.assertEqual(sl_DRAM.get("a"), "A")
        self.assertListEqual(list(sl_DRAM.storage.keys()), ["a", "b"])
        self.assertEqual(sl_ssd.size(), 0)

    def test_storage_layer_empty_layer_has_no_eviction_candidate(self) -> None:
        """An empty layer has no key to evict: choosing an eviction candidate raises ValueError."""

        # an empty DRAM layer above an empty SSD:
        sl_ssd: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=100, name="SSD"
        )
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=2, name="DRAM", layer_below=sl_ssd
        )
        with self.assertRaisesRegex(ValueError, "can be evicted"):
            sl_DRAM.choose_eviction_candidate()

    def test_storage_layer_delete_unfixes_key(self) -> None:
        """Deleting a fixed key unfixes it: when the key is put again later, it can be evicted."""

        # a full DRAM layer with two entries, of which "b" is fixed:
        sl_ssd: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=100, name="SSD"
        )
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=2, name="DRAM", layer_below=sl_ssd
        )
        sl_DRAM.put("a", "a")
        sl_DRAM.put("b", "b")
        sl_DRAM.fix("b")

        # deleting "b" also unfixes it:
        sl_DRAM.delete("b")
        self.assertNotIn("b", sl_DRAM.fixed)

        # put "b" again and then a new key "c": "b" is the largest key and no longer fixed, so it is evicted:
        sl_DRAM.put("b", "b")
        sl_DRAM.put("c", "c")
        self.assertListEqual(list(sl_DRAM.storage.keys()), ["a", "c"])
        self.assertListEqual(list(sl_ssd.storage.keys()), ["b"])

    def test_storage_layer_capacity_must_be_at_least_one(self) -> None:
        """The constructor rejects a max_capacity below 1, as such a layer could never store anything."""

        # a capacity of 0 is rejected, both with and without a layer below:
        sl_ssd: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=100, name="SSD"
        )
        with self.assertRaisesRegex(ValueError, "max_capacity"):
            StorageLayer[str, str](max_capacity=0, name="DRAM", layer_below=sl_ssd)
        with self.assertRaisesRegex(ValueError, "max_capacity"):
            StorageLayer[str, str](max_capacity=0, name="DRAM")

        # a negative capacity is rejected as well:
        with self.assertRaisesRegex(ValueError, "max_capacity"):
            StorageLayer[str, str](max_capacity=-1, name="DRAM")

        # the smallest valid capacity, 1, is enough to store one entry:
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=1, name="DRAM"
        )
        sl_DRAM.put("a", "a")
        self.assertEqual(sl_DRAM.get("a"), "a")
        self.assertEqual(sl_DRAM.size(), 1)

    def test_storage_layer_prefix_addressing(self) -> None:
        """With a prefix address conversion, a get returns the character at the address's offset within the page
        that the layer below holds under the address's first character."""

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
        # each page contains only 4 characters (you can interpret each character to symbolise a byte of data in storage)
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

    def test_storage_layer_prefix_addressing_eviction_keeps_layer_below_intact(
        self,
    ) -> None:
        """Under an address-conversion strategy, eviction only drops the cached sub-unit locally: the layer below
        gains no entry, and every page in it stays unchanged."""

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
        # ... it is not written to the layer below, which still holds only the three pages ...
        self.assertNotIn("12", sl_ssd.storage)
        self.assertEqual(sl_ssd.size(), 3)
        # ... and every page in the layer below is untouched.
        self.assertEqual(sl_ssd.get("0"), "p0aa")
        self.assertEqual(sl_ssd.get("1"), "p1bb")
        self.assertEqual(sl_ssd.get("2"), "p2cc")

    def test_storage_layer_prefix_addressing_caches_in_upper_layer(self) -> None:
        """
        The extracted sub-unit is cached in the upper layer, so a second get is
        served locally without consulting the layer below again.
        """

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

    def test_storage_layer_overwrite_in_full_layer_does_not_evict(self) -> None:
        """Overwriting a stored key in a full layer keeps all its entries and evicts nothing to the layer below."""

        # a full DRAM layer with three entries above an empty SSD:
        sl_ssd: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=100, name="SSD"
        )
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=3, name="DRAM", layer_below=sl_ssd
        )
        for key in ["0", "1", "2"]:
            sl_DRAM.put(key, key)

        # overwrite "1": DRAM still holds all three keys, and nothing reaches the SSD:
        sl_DRAM.put("1", "one")
        self.assertListEqual(list(sl_DRAM.storage.keys()), ["0", "1", "2"])
        self.assertEqual(sl_DRAM.get("1"), "one")
        self.assertEqual(sl_ssd.size(), 0)

        # overwrite "2", the largest key and hence the eviction candidate: again nothing is evicted:
        sl_DRAM.put("2", "two")
        self.assertListEqual(list(sl_DRAM.storage.keys()), ["0", "1", "2"])
        self.assertEqual(sl_DRAM.get("2"), "two")
        self.assertEqual(sl_ssd.size(), 0)

    def test_storage_layer_overwrite_in_full_layer_without_layer_below(self) -> None:
        """Overwriting a key in a full layer without a layer below succeeds, as no room has to be made."""

        # a full single layer with two entries:
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=2, name="DRAM"
        )
        sl_DRAM.put("a", "a")
        sl_DRAM.put("b", "b")

        # overwrite "a": the new value is stored and the layer keeps both entries:
        sl_DRAM.put("a", "A")
        self.assertEqual(sl_DRAM.get("a"), "A")
        self.assertEqual(sl_DRAM.size(), 2)

    def test_storage_layer_overwrite_of_fixed_key_in_full_layer(self) -> None:
        """Overwriting a fixed key in a full layer succeeds and evicts nothing."""

        # a full DRAM layer with two entries above an empty SSD:
        sl_ssd: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=100, name="SSD"
        )
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=2, name="DRAM", layer_below=sl_ssd
        )
        sl_DRAM.put("a", "a")
        sl_DRAM.put("b", "b")

        # fix "b", the largest key:
        sl_DRAM.fix("b")

        # overwrite "b": the new value is stored in DRAM, and nothing reaches the SSD:
        sl_DRAM.put("b", "B")
        self.assertEqual(sl_DRAM.get("b"), "B")
        self.assertListEqual(list(sl_DRAM.storage.keys()), ["a", "b"])
        self.assertEqual(sl_ssd.size(), 0)
