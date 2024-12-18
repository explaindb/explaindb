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
from system.storage.storage_layer import StorageLayer
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
