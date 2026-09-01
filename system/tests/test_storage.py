from typing import Iterator

from system.storage.RAID.block_assignment import compute_assignment
from system.storage.RAID.cost_model import (
    Device,
    SubSystem,
    RAID_0,
    RAID_1,
    RAID_5,
    ResilienceScenario,
)
from system.storage.storage_layer import StorageLayer, AddressConversionStrategy
from system.tests.abstract_unit_test import AbstractUnitTest


class RAIDAssignmentTest(AbstractUnitTest):

    def test_RAID_0(self):
        ret: list[str] = compute_assignment(3, 3, 0)
        self.assertEqual(len(ret), 3)
        self.assertEqual(ret[0], "0          1          2")
        self.assertEqual(ret[1], "3          4          5")
        self.assertEqual(ret[2], "6          7          8")

    def test_RAID_1(self):
        ret: list[str] = compute_assignment(3, 3, 1)
        self.assertEqual(len(ret), 3)
        self.assertEqual(ret[0], "0          0          0")
        self.assertEqual(ret[1], "1          1          1")
        self.assertEqual(ret[2], "2          2          2")

    def test_RAID_4(self):
        ret: list[str] = compute_assignment(3, 3, 4)
        self.assertEqual(len(ret), 3)
        self.assertEqual(ret[0], "0          1          P[0^1]")
        self.assertEqual(ret[1], "2          3          P[2^3]")
        self.assertEqual(ret[2], "4          5          P[4^5]")

    def test_RAID_5(self):
        ret: list[str] = compute_assignment(2, 3, 5)
        self.assertEqual(len(ret), 2)
        self.assertEqual(ret[0], "0          1          P[0^1]")
        self.assertEqual(ret[1], "P[2^3]     2          3")

        # Output for debugging purposes
        # ret: list[str] = compute_assignment(20, 3, 5)
        # for row in ret:
        #    print(row)


class RAIDPerformanceTest(AbstractUnitTest):

    def test_Device(self):
        dev: Device = Device(100, 100, 1000, 1000)
        self.assertEqual(dev.get_sequential_read_performance(), 100)
        self.assertEqual(dev.get_sequential_write_performance(), 100)
        self.assertEqual(dev.get_read_IO_performance(), 1000)
        self.assertEqual(dev.get_write_IO_performance(), 1000)
        self.assertEqual(dev.get_storage_blow_up(), 1)

    def test_RAID_0(self):
        dev: Device = Device(100, 100, 1000, 1000)
        number_of_subsystems: int = 6
        array: SubSystem = RAID_0([dev] * number_of_subsystems)

        self.assertEqual(
            array.get_sequential_read_performance(), number_of_subsystems * 100
        )
        self.assertEqual(
            array.get_sequential_write_performance(), number_of_subsystems * 100
        )
        self.assertEqual(array.get_read_IO_performance(), number_of_subsystems * 1000)
        self.assertEqual(array.get_write_IO_performance(), number_of_subsystems * 1000)
        self.assertEqual(array.get_storage_blow_up(), 1)

    def test_RAID_1(self):
        dev: Device = Device(100, 100, 1000, 1000)
        number_of_subsystems: int = 6
        array: SubSystem = RAID_1([dev] * number_of_subsystems)

        self.assertEqual(
            array.get_sequential_read_performance(), number_of_subsystems * 100
        )
        self.assertEqual(array.get_sequential_write_performance(), 100)
        self.assertEqual(array.get_read_IO_performance(), number_of_subsystems * 1000)
        self.assertEqual(array.get_write_IO_performance(), 1000)
        self.assertEqual(array.get_storage_blow_up(), number_of_subsystems)

        # resilience test:
        resilience_scenario: tuple[ResilienceScenario, Iterator[SubSystem] | None] = (
            array.get_resilience_scenario()
        )
        resilience_subsystems = list(resilience_scenario[1])
        self.assertEqual(
            resilience_scenario[0],
            ResilienceScenario.ALL_BUT_ONE_SUBSYSTEM_MAY_FAIL,
        )
        self.assertEqual(
            resilience_subsystems, list[Device]([dev] * number_of_subsystems)
        )

    def test_RAID_0_with_misconfigured_heterogeneous_devices(self):
        # create an unbalanced RAID 0 array with different devices:
        dev_type_1: Device = Device(100, 100, 1000, 1000)
        dev_type_2: Device = Device(200, 200, 2000, 2000)
        array: SubSystem = RAID_0([dev_type_1, dev_type_2])
        self.assertEqual(array.get_sequential_read_performance(), 200)
        self.assertEqual(array.get_sequential_write_performance(), 200)
        self.assertEqual(array.get_read_IO_performance(), 3000)
        self.assertEqual(array.get_write_IO_performance(), 3000)

    def test_RAID_0_with_well_configured_heterogeneous_devices(self):
        # create an unbalanced RAID 0 array with different devices to compensate different performance characteristics:
        dev_type_1: Device = Device(100, 100, 1000, 1000)
        dev_type_2: Device = Device(200, 200, 2000, 2000)
        sub_array_1: SubSystem = RAID_0([dev_type_1] * 4)
        sub_array_2: SubSystem = RAID_0([dev_type_2] * 2)
        array: SubSystem = RAID_0([sub_array_1, sub_array_2])
        self.assertEqual(array.get_sequential_read_performance(), 800)
        self.assertEqual(array.get_sequential_write_performance(), 800)
        self.assertEqual(array.get_read_IO_performance(), 8000)
        self.assertEqual(array.get_write_IO_performance(), 8000)

    def test_RAID_1_with_misconfigured_heterogeneous_devices(self):
        dev_type_1: Device = Device(100, 100, 1000, 1000)
        dev_type_2: Device = Device(200, 200, 2000, 2000)
        array: SubSystem = RAID_1([dev_type_1, dev_type_2])
        self.assertEqual(array.get_sequential_read_performance(), 300)
        self.assertEqual(array.get_sequential_write_performance(), 100)
        self.assertEqual(array.get_read_IO_performance(), 3000)
        self.assertEqual(array.get_write_IO_performance(), 1000)

    def test_RAID_1_with_well_configured_heterogeneous_devices(self):
        # create an unbalanced RAID 1 array with different devices to compensate different performance characteristics:
        dev_type_1: Device = Device(100, 100, 1000, 1000)
        dev_type_2: Device = Device(200, 200, 2000, 2000)
        sub_array_1: SubSystem = RAID_1([dev_type_1] * 4)
        sub_array_2: SubSystem = RAID_1([dev_type_2] * 2)
        array: SubSystem = RAID_1([sub_array_1, sub_array_2])
        self.assertEqual(array.get_sequential_read_performance(), 800)
        self.assertEqual(array.get_sequential_write_performance(), 100)
        self.assertEqual(array.get_read_IO_performance(), 8000)
        self.assertEqual(array.get_write_IO_performance(), 1000)

    def test_RAID_5(self):
        dev: Device = Device(100, 100, 1000, 1000)
        number_of_subsystems: int = 6
        array: SubSystem = RAID_5([dev] * number_of_subsystems)

        self.assertEqual(
            array.get_sequential_read_performance(), (number_of_subsystems - 1) * 100
        )
        self.assertEqual(
            array.get_sequential_write_performance(), (number_of_subsystems - 1) * 100
        )
        self.assertEqual(
            array.get_read_IO_performance(), (number_of_subsystems - 1) * 1000
        )
        self.assertEqual(
            array.get_write_IO_performance(), (number_of_subsystems - 1) * 1000
        )
        self.assertEqual(
            array.get_storage_blow_up(),
            number_of_subsystems / (number_of_subsystems - 1),
        )

        # resilience test:
        resilience_scenario: tuple[ResilienceScenario, Iterator[SubSystem] | None] = (
            array.get_resilience_scenario()
        )
        resilience_subsystems = list(resilience_scenario[1])
        self.assertEqual(
            resilience_scenario[0],
            ResilienceScenario.ANY_SINGLE_SUBSYSTEM_MAY_FAIL,
        )
        self.assertEqual(
            resilience_subsystems, list[Device]([dev] * number_of_subsystems)
        )

    def test_RAID_01(self):
        # RAID 0+1: RAID 0 arrays in a RAID 1 subsystem (i.e. bottom layer is RAID 0)
        dev: Device = Device(100, 100, 1000, 1000)
        scale_factor: int
        for scale_factor in [1, 2, 10]:
            number_of_subsystems: int = 6 * scale_factor
            array: SubSystem = RAID_1([RAID_0([dev] * 2 * scale_factor)] * 3)

            self.assertEqual(
                array.get_sequential_read_performance(), number_of_subsystems * 100
            )
            self.assertEqual(
                array.get_sequential_write_performance(),
                (number_of_subsystems / 3) * 100,
            )
            self.assertEqual(
                array.get_read_IO_performance(), number_of_subsystems * 1000
            )
            self.assertEqual(
                array.get_write_IO_performance(), (number_of_subsystems / 3) * 1000
            )
            self.assertEqual(
                array.get_storage_blow_up(),
                3,
            )

            # same with different number of disks:
            dev: Device = Device(100, 100, 1000, 1000)
            array: SubSystem = RAID_1([RAID_0([dev] * 3 * scale_factor)] * 2)

            self.assertEqual(
                array.get_sequential_read_performance(), number_of_subsystems * 100
            )
            self.assertEqual(
                array.get_sequential_write_performance(),
                (number_of_subsystems / 2) * 100,
            )
            self.assertEqual(
                array.get_read_IO_performance(), number_of_subsystems * 1000
            )
            self.assertEqual(
                array.get_write_IO_performance(), (number_of_subsystems / 2) * 1000
            )
            self.assertEqual(
                array.get_storage_blow_up(),
                2,
            )

    def test_RAID_10(self):
        # RAID 1+0: RAID 1 arrays in a RAID 0 subsystem (i.e. bottom layer is RAID 1)
        dev: Device = Device(100, 100, 1000, 1000)
        scale_factor: int
        for scale_factor in [1, 2, 10]:
            number_of_subsystems: int = 6 * scale_factor
            array: SubSystem = RAID_0([RAID_1([dev] * 2 * scale_factor)] * 3)

            self.assertEqual(
                array.get_sequential_read_performance(), number_of_subsystems * 100
            )
            self.assertEqual(
                array.get_sequential_write_performance(),
                (number_of_subsystems / (2 * scale_factor)) * 100,
            )
            self.assertEqual(
                array.get_read_IO_performance(), number_of_subsystems * 1000
            )
            self.assertEqual(
                array.get_write_IO_performance(),
                (number_of_subsystems / (2 * scale_factor)) * 1000,
            )
            self.assertEqual(
                array.get_storage_blow_up(),
                2 * scale_factor,
            )

            # same with different number of disks:
            dev: Device = Device(100, 100, 1000, 1000)
            array: SubSystem = RAID_0([RAID_1([dev] * 3 * scale_factor)] * 2)

            self.assertEqual(
                array.get_sequential_read_performance(), number_of_subsystems * 100
            )
            self.assertEqual(
                array.get_sequential_write_performance(),
                (number_of_subsystems / (3 * scale_factor)) * 100,
            )
            self.assertEqual(
                array.get_read_IO_performance(), number_of_subsystems * 1000
            )
            self.assertEqual(
                array.get_write_IO_performance(),
                (number_of_subsystems / (3 * scale_factor)) * 1000,
            )
            self.assertEqual(
                array.get_storage_blow_up(),
                3 * scale_factor,
            )

    def test_RAID_55(self):
        # RAID 5+5: RAID 5 arrays in a RAID 5 subsystem (i.e. bottom layer is RAID 5)
        dev: Device = Device(100, 100, 1000, 1000)
        scale_factor: int
        for scale_factor in [2]:
            disks_inner: int = 2 * scale_factor
            disks_outer: int = 3
            array: SubSystem = RAID_5([RAID_5([dev] * disks_inner)] * disks_outer)
            self.assertEqual(
                array.get_sequential_read_performance(),
                (disks_inner - 1) * (disks_outer - 1) * 100,
            )
            self.assertEqual(
                array.get_sequential_read_performance(),
                (disks_inner - 1) * (disks_outer - 1) * 100,
            )
            self.assertEqual(
                array.get_read_IO_performance(),
                (disks_inner - 1) * (disks_outer - 1) * 1000,
            )
            self.assertEqual(
                array.get_write_IO_performance(),
                (disks_inner - 1) * (disks_outer - 1) * 1000,
            )
            self.assertEqual(
                array.get_storage_blow_up(),
                disks_inner / (disks_inner - 1) * disks_outer / (disks_outer - 1),
            )

    @staticmethod
    def _print_resilient_info(subsystem: SubSystem):
        """Prints the resilience scenarios of a subsystem and its children."""

        # get all possible error scenarios:
        resilience_scenarios_infos: list[
            tuple[int, SubSystem, ResilienceScenario, Iterator[SubSystem] | None]
        ] = list(subsystem.get_resilience_scenarios())

        # print the resilience scenarios:
        rsi: tuple[int, SubSystem, ResilienceScenario, Iterator[SubSystem] | None]
        for rsi in resilience_scenarios_infos:
            rec_depth: int = rsi[0]
            sub_system: SubSystem = rsi[1]
            resilience_scenario: ResilienceScenario = rsi[2]
            print(
                "\t" * (rec_depth) + str(sub_system) + ": " + str(resilience_scenario)
            )

    def test_RAID_55_resilience_scenarios(self):
        dev: Device = Device(100, 100, 1000, 1000)
        array: SubSystem = RAID_0([RAID_1([RAID_5([dev] * 3)] * 3)] * 3)

        # get all possible error scenarios:
        resilience_scenarios_infos: list[
            tuple[int, SubSystem, ResilienceScenario, Iterator[SubSystem] | None]
        ] = list(array.get_resilience_scenarios())

        # Output resilience scenarios for debugging purposes:
        # RAIDPerformanceTest._print_resilient_info(array)

        self.assertEqual(len(resilience_scenarios_infos), 12)

        for rsi in resilience_scenarios_infos:
            rec_depth: int = rsi[0]
            sub_system: SubSystem = rsi[1]
            resilience_scenario: ResilienceScenario = rsi[2]
            if rec_depth == 1:
                self.assertTrue(
                    resilience_scenario
                    == ResilienceScenario.ALL_BUT_ONE_SUBSYSTEM_MAY_FAIL
                )
            elif rec_depth == 2:
                self.assertTrue(
                    resilience_scenario
                    == ResilienceScenario.ANY_SINGLE_SUBSYSTEM_MAY_FAIL
                )
            else:
                raise ValueError("Unexpected recursion depth")

    def test_RAID_5005105(self):
        # RAID 5+0+0+5+...: RAID 5 arrays in a RAID 0 subsystem (i.e. bottom layer is RAID 5)
        dev: Device = Device(100, 100, 1000, 1000)
        scale_factor: int
        number_of_subsystems: int = 3
        array: SubSystem = RAID_5(
            [
                RAID_0(
                    [
                        RAID_1(
                            [
                                RAID_5(
                                    [
                                        RAID_0(
                                            [
                                                RAID_0(
                                                    [
                                                        RAID_5(
                                                            [dev] * number_of_subsystems
                                                        )
                                                    ]
                                                    * number_of_subsystems
                                                )
                                            ]
                                            * number_of_subsystems
                                        )
                                    ]
                                    * number_of_subsystems
                                )
                            ]
                            * number_of_subsystems
                        )
                    ]
                    * number_of_subsystems
                )
            ]
            * number_of_subsystems
        )
        self.assertEqual(
            array.get_sequential_read_performance(),
            100
            * (number_of_subsystems - 1)  # RAID 5 (starting from innermost)
            * number_of_subsystems  # RAID 0
            * number_of_subsystems  # RAID 0
            * (number_of_subsystems - 1)  # RAID 5
            * number_of_subsystems  # RAID 1
            * number_of_subsystems  # RAID 0
            * (number_of_subsystems - 1),  # RAID 5
        )

        # Output resilience scenarios for debugging purposes:
        # RAIDPerformanceTest._print_resilient_info(array)


class StorageLayerTest(AbstractUnitTest):

    def test_storage_layer_basics(self):

        # simple storage hierarchy with only two layers:
        sl_ssd: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=100, name="SSD"
        )
        sl_DRAM: StorageLayer[str, str] = StorageLayer[str, str](
            max_capacity=5, name="DRAM", layer_below=sl_ssd
        )
        # insert some entries to force eviction
        for i in range(10):
            sl_DRAM.put(str(i), str(i))

        # sl_DRAM.show()
        # sl_ssd.show()

        self.assertEqual(sl_DRAM.size(), 5)
        self.assertEqual(sl_ssd.size(), 5)

        self.assertListEqual(list(sl_DRAM.storage.keys()), ["0", "1", "2", "3", "9"])
        self.assertListEqual(list(sl_ssd.storage.keys()), ["4", "5", "6", "7", "8"])

        # test get:
        self.assertEqual(sl_DRAM.get("0"), "0")
        self.assertEqual(sl_DRAM.get("5"), "5")

        self.assertListEqual(list(sl_DRAM.storage.keys()), ["0", "1", "2", "3", "5"])
        self.assertListEqual(
            list(sl_ssd.storage.keys()), ["4", "5", "6", "7", "8", "9"]
        )

        # sl_DRAM.show()
        # sl_ssd.show()

        # test fix:
        sl_DRAM.fix("5")
        with self.assertRaises(ValueError):
            sl_DRAM.put("42", "42")

    def test_storage_layer_prefix_addressing(self):

        class PrefixConversion(AddressConversionStrategy[str]):
            def split_address(self, address: str) -> tuple[str, str]:
                """Split the given address into two parts and return both parts.
                Returns the first character of the address, second character of the address
                """
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
        """
        Eviction from a layer that uses an address-conversion strategy must not
        corrupt the layer below.

        Symptom: with a conversion strategy, eviction used the wrong half of the
        split address and wrote a single extracted sub-unit back to the layer
        below, clobbering a whole page there.
        Expected: under a conversion strategy the upper layer is a read cache;
        eviction drops the entry locally and leaves the layer below unchanged.
        Observed (before the fix): the page below is overwritten with one byte.
        """

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
