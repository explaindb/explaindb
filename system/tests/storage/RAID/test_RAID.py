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
"""Tests for RAID block assignment and RAID performance."""

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

    def test_RAID_5_wide_parity_cells_keep_columns_separated(self):
        """With seven disks the parity cells are wider than 11 characters, and every column is still
        separated from the next one by at least one space."""
        ret: list[str] = compute_assignment(3, 7, 5)
        self.assertEqual(len(ret), 3)

        # every row splits on whitespace into exactly one cell per disk:
        for row in ret:
            self.assertEqual(len(row.split()), 7)

        # row 1 in full: the widest cell, P[12^13^14^15^16^17] in row 2, has 20 characters, so every cell except
        # the last one of a row is padded to 21 characters:
        self.assertEqual(
            ret[1],
            "P[6^7^8^9^10^11]     "
            "6                    "
            "7                    "
            "8                    "
            "9                    "
            "10                   "
            "11",
        )

    def test_RAID_5_parity_rotates_over_five_disks(self):
        """With five disks, the RAID 5 parity block starts on the last disk and moves on by one disk
        per row (disk 4, 0, 1, 2, 3 in rows 0 to 4), while the data blocks fill the other disks in
        order."""
        ret: list[str] = compute_assignment(5, 5, 5)

        # split every row into its cells and compare the whole layout; the parity cells form a diagonal:
        self.assertEqual(
            [row.split() for row in ret],
            [
                ["0", "1", "2", "3", "P[0^1^2^3]"],
                ["P[4^5^6^7]", "4", "5", "6", "7"],
                ["8", "P[8^9^10^11]", "9", "10", "11"],
                ["12", "13", "P[12^13^14^15]", "14", "15"],
                ["16", "17", "18", "P[16^17^18^19]", "19"],
            ],
        )


class RAIDPerformanceTest(AbstractUnitTest):
    """Unless a test needs special values, the tests build their arrays from devices whose four performance values
    all differ (sequential read and write speed, read and write IOPS), so a RAID formula that mixes up reads and
    writes yields a wrong value."""

    def test_Device(self) -> None:
        """A device reports the performance values it was created with and needs no extra storage."""

        # a device with 100 MB/s sequential read, 50 MB/s sequential write, 1000 read IOPS and 400 write IOPS:
        dev: Device = Device(100, 50, 1000, 400)

        # every getter returns its own value:
        self.assertEqual(dev.get_sequential_read_performance(), 100)
        self.assertEqual(dev.get_sequential_write_performance(), 50)
        self.assertEqual(dev.get_read_IO_performance(), 1000)
        self.assertEqual(dev.get_write_IO_performance(), 400)
        self.assertEqual(dev.get_storage_blow_up(), 1)

    def test_RAID_0(self) -> None:
        """RAID 0 multiplies the sequential speeds of its devices by their number and adds up their IOPS, for reads
        and writes alike, and needs no extra storage."""

        # stripe the data over six devices:
        dev: Device = Device(100, 50, 1000, 400)
        number_of_subsystems: int = 6
        array: SubSystem = RAID_0([dev] * number_of_subsystems)

        # all six devices work in parallel, for reads and for writes:
        self.assertEqual(
            array.get_sequential_read_performance(), number_of_subsystems * 100
        )
        self.assertEqual(
            array.get_sequential_write_performance(), number_of_subsystems * 50
        )
        self.assertEqual(array.get_read_IO_performance(), number_of_subsystems * 1000)
        self.assertEqual(array.get_write_IO_performance(), number_of_subsystems * 400)

        # every block is stored once:
        self.assertEqual(array.get_storage_blow_up(), 1)

    def test_RAID_1(self) -> None:
        """RAID 1 reads with all its devices but writes only as fast as one of them, stores one copy per device,
        and survives the failure of all but one device."""

        # mirror the data on six devices:
        dev: Device = Device(100, 50, 1000, 400)
        number_of_subsystems: int = 6
        array: SubSystem = RAID_1([dev] * number_of_subsystems)

        # every device can serve reads, but every write goes to all devices:
        self.assertEqual(
            array.get_sequential_read_performance(), number_of_subsystems * 100
        )
        self.assertEqual(array.get_sequential_write_performance(), 50)
        self.assertEqual(array.get_read_IO_performance(), number_of_subsystems * 1000)
        self.assertEqual(array.get_write_IO_performance(), 400)

        # every device holds a full copy of the data:
        self.assertEqual(array.get_storage_blow_up(), number_of_subsystems)

        # resilience test: the array reports a scenario, and any of its six devices may be among the failing ones:
        resilience_scenario: (
            tuple[ResilienceScenario, Iterator[SubSystem] | None] | None
        ) = array.get_resilience_scenario()
        assert resilience_scenario is not None and resilience_scenario[1] is not None
        resilience_subsystems = list(resilience_scenario[1])
        self.assertEqual(
            resilience_scenario[0],
            ResilienceScenario.ALL_BUT_ONE_SUBSYSTEM_MAY_FAIL,
        )
        self.assertEqual(
            resilience_subsystems, list[Device]([dev] * number_of_subsystems)
        )

    def test_RAID_0_with_misconfigured_heterogeneous_devices(self) -> None:
        """RAID 0 over a slow and a fast device streams at only twice the speed of the slow device."""

        # create an unbalanced RAID 0 array with different devices (the second one is twice as fast in every respect):
        dev_type_1: Device = Device(100, 50, 1000, 400)
        dev_type_2: Device = Device(200, 100, 2000, 800)
        array: SubSystem = RAID_0([dev_type_1, dev_type_2])

        # the slow device limits the sequential speeds; the IOPS add up:
        self.assertEqual(array.get_sequential_read_performance(), 200)
        self.assertEqual(array.get_sequential_write_performance(), 100)
        self.assertEqual(array.get_read_IO_performance(), 3000)
        self.assertEqual(array.get_write_IO_performance(), 1200)

    def test_RAID_0_with_well_configured_heterogeneous_devices(self) -> None:
        """Grouping four slow and two fast devices into two RAID 0 arrays of equal speed lets a RAID 0 array on top
        use the full speed of all six devices."""

        # create an unbalanced RAID 0 array with different devices to compensate different performance characteristics:
        dev_type_1: Device = Device(100, 50, 1000, 400)
        dev_type_2: Device = Device(200, 100, 2000, 800)
        sub_array_1: SubSystem = RAID_0([dev_type_1] * 4)
        sub_array_2: SubSystem = RAID_0([dev_type_2] * 2)
        array: SubSystem = RAID_0([sub_array_1, sub_array_2])

        # both sub-arrays read at 400 MB/s and write at 200 MB/s, so the top array doubles both:
        self.assertEqual(array.get_sequential_read_performance(), 800)
        self.assertEqual(array.get_sequential_write_performance(), 400)
        self.assertEqual(array.get_read_IO_performance(), 8000)
        self.assertEqual(array.get_write_IO_performance(), 3200)

    def test_RAID_1_with_misconfigured_heterogeneous_devices(self) -> None:
        """RAID 1 over a slow and a fast device reads with both but writes only as fast as the slow device."""

        # mirror the data on a slow and a fast device:
        dev_type_1: Device = Device(100, 50, 1000, 400)
        dev_type_2: Device = Device(200, 100, 2000, 800)
        array: SubSystem = RAID_1([dev_type_1, dev_type_2])

        # reads add up, writes wait for the slow device:
        self.assertEqual(array.get_sequential_read_performance(), 300)
        self.assertEqual(array.get_sequential_write_performance(), 50)
        self.assertEqual(array.get_read_IO_performance(), 3000)
        self.assertEqual(array.get_write_IO_performance(), 400)

    def test_RAID_1_with_well_configured_heterogeneous_devices(self) -> None:
        """Mirroring two RAID 1 arrays of equal read speed (four slow devices, two fast devices) reads with all six
        devices; writes still wait for the slowest device."""

        # create an unbalanced RAID 1 array with different devices to compensate different performance characteristics:
        dev_type_1: Device = Device(100, 50, 1000, 400)
        dev_type_2: Device = Device(200, 100, 2000, 800)
        sub_array_1: SubSystem = RAID_1([dev_type_1] * 4)
        sub_array_2: SubSystem = RAID_1([dev_type_2] * 2)
        array: SubSystem = RAID_1([sub_array_1, sub_array_2])

        # both sub-arrays read at 400 MB/s, and the sub-array of slow devices writes at only 50 MB/s:
        self.assertEqual(array.get_sequential_read_performance(), 800)
        self.assertEqual(array.get_sequential_write_performance(), 50)
        self.assertEqual(array.get_read_IO_performance(), 8000)
        self.assertEqual(array.get_write_IO_performance(), 400)

    def test_RAID_5(self) -> None:
        """RAID 5 over n devices streams at the speed of n - 1 devices, as one device's worth goes to parity, serves
        random reads with all n devices, pays two reads and two writes per small write, stores n / (n - 1) times
        the data, and survives the failure of any single device.
        """

        # stripe the data with parity over six devices:
        dev: Device = Device(100, 50, 1000, 400)
        number_of_subsystems: int = 6
        array: SubSystem = RAID_5([dev] * number_of_subsystems)

        # five devices' worth of sequential speed remains for the data, for reads and for writes:
        self.assertEqual(
            array.get_sequential_read_performance(), (number_of_subsystems - 1) * 100
        )
        self.assertEqual(
            array.get_sequential_write_performance(), (number_of_subsystems - 1) * 50
        )

        # a random read touches one device, and every device holds data, so all six devices serve reads:
        self.assertEqual(array.get_read_IO_performance(), number_of_subsystems * 1000)

        # a small write reads the old data and parity and writes both anew, which costs 2 / 1000 + 2 / 400 = 0.007
        # device-seconds; six devices serve 6 / 0.007 = 857.14 such writes per second, rounded to 857:
        self.assertEqual(array.get_write_IO_performance(), 857)

        # one parity block per five data blocks:
        self.assertEqual(
            array.get_storage_blow_up(),
            number_of_subsystems / (number_of_subsystems - 1),
        )

        # resilience test: the array reports a scenario, and any of its six devices may be the failing one:
        resilience_scenario: (
            tuple[ResilienceScenario, Iterator[SubSystem] | None] | None
        ) = array.get_resilience_scenario()
        assert resilience_scenario is not None and resilience_scenario[1] is not None
        resilience_subsystems = list(resilience_scenario[1])
        self.assertEqual(
            resilience_scenario[0],
            ResilienceScenario.ANY_SINGLE_SUBSYSTEM_MAY_FAIL,
        )
        self.assertEqual(
            resilience_subsystems, list[Device]([dev] * number_of_subsystems)
        )

    def test_RAID_5_write_IOPS_are_rounded(self) -> None:
        """RAID 5 rounds its write IOPS to the nearest integer instead of cutting off the fraction or always
        rounding up."""

        # 3 / (2 / 1000 + 2 / 400) = 3 / 0.007 = 428.57 rounds up to 429 (cutting off the fraction would give 428),
        # 4 / 0.007 = 571.43 rounds down to 571 (always rounding up would give 572):
        number_of_subsystems: int
        expected_write_IOPs: int
        for number_of_subsystems, expected_write_IOPs in [(3, 429), (4, 571)]:
            with self.subTest(number_of_subsystems=number_of_subsystems):
                # stripe the data with parity over distinct devices:
                array: SubSystem = RAID_5(
                    [Device(100, 50, 1000, 400) for _ in range(number_of_subsystems)]
                )
                self.assertEqual(array.get_write_IO_performance(), expected_write_IOPs)

    def test_RAID_5_with_mixed_devices(self) -> None:
        """RAID 5 over devices of different speeds adds up their read IOPS exactly and computes its small writes
        from the mean read and the mean write IOPS of its devices."""

        # stripe the data with parity over two slow devices and one twice as fast device:
        array: SubSystem = RAID_5(
            [
                Device(100, 50, 1000, 400),
                Device(100, 50, 1000, 400),
                Device(200, 100, 2000, 800),
            ]
        )

        # reads add up to 1000 + 1000 + 2000 = 4000 (rounding the mean 1333.33 first would give 3 * 1333 = 3999):
        self.assertEqual(array.get_read_IO_performance(), 4000)

        # the means are R = 4000 / 3 and W = 1600 / 3, so 3 / (2 / R + 2 / W) = 3 / (0.0015 + 0.00375) = 571.43,
        # rounded to 571 (the slowest device alone would give 429, the fastest 857):
        self.assertEqual(array.get_write_IO_performance(), 571)

    def test_RAID_5_write_IOPS_with_equal_read_and_write_IOPS(self) -> None:
        """With W read and W write IOPS per device, RAID 5 over n devices serves the textbook n * W / 4 small writes
        per second, as every small write costs four device I/Os."""

        # stripe the data with parity over six distinct devices with 400 read and 400 write IOPS each:
        array: SubSystem = RAID_5([Device(100, 50, 400, 400) for _ in range(6)])

        # 6 / (2 / 400 + 2 / 400) = 6 * 400 / 4 = 600:
        self.assertEqual(array.get_write_IO_performance(), 600)

    def test_RAID_5_serves_fewer_write_IOPS_than_RAID_10(self) -> None:
        """On six devices, RAID 5 serves fewer small writes per second than RAID 1+0: a RAID 5 write costs two reads
        and two writes, a RAID 1+0 write one write on each of the two devices of a mirrored pair, which work in
        parallel."""

        # RAID 5 over six distinct devices, and RAID 1+0 over three mirrored pairs of distinct devices:
        raid_5: SubSystem = RAID_5([Device(100, 50, 1000, 400) for _ in range(6)])
        raid_10: SubSystem = RAID_0(
            [RAID_1([Device(100, 50, 1000, 400) for _ in range(2)]) for _ in range(3)]
        )

        # RAID 5 serves 6 / (2 / 1000 + 2 / 400) = 857.14 -> 857 writes per second, RAID 1+0 three pairs * 400 = 1200:
        self.assertEqual(raid_5.get_write_IO_performance(), 857)
        self.assertEqual(raid_10.get_write_IO_performance(), 1200)
        self.assertLess(
            raid_5.get_write_IO_performance(), raid_10.get_write_IO_performance()
        )

    def test_RAID_5_write_IOPS_of_devices_without_IOPS(self) -> None:
        """RAID 5 over devices that serve no random reads, or no random writes, serves no small write and reports 0
        write IOPS."""

        # devices without read IOPS, then devices without write IOPS:
        read_IOPs: int
        write_IOPs: int
        for read_IOPs, write_IOPs in [(0, 400), (1000, 0)]:
            with self.subTest(read_IOPs=read_IOPs, write_IOPs=write_IOPs):
                # stripe the data with parity over three distinct such devices:
                array: SubSystem = RAID_5(
                    [Device(100, 50, read_IOPs, write_IOPs) for _ in range(3)]
                )

                # a small write needs both reads and writes, so the array serves none:
                self.assertEqual(array.get_write_IO_performance(), 0)

    def test_RAID_01(self) -> None:
        """RAID 0+1 reads with all its devices but writes only as fast as one of its RAID 0 arrays, and stores one
        copy per RAID 0 array."""

        # RAID 0+1: RAID 0 arrays in a RAID 1 subsystem (i.e. bottom layer is RAID 0)
        dev: Device = Device(100, 50, 1000, 400)
        scale_factor: int
        for scale_factor in [1, 2, 10]:
            # mirror three RAID 0 arrays of 2 * scale_factor devices each:
            number_of_subsystems: int = 6 * scale_factor
            array: SubSystem = RAID_1([RAID_0([dev] * 2 * scale_factor)] * 3)

            # reads use all devices, writes only the devices of one RAID 0 array, i.e. a third of them:
            self.assertEqual(
                array.get_sequential_read_performance(), number_of_subsystems * 100
            )
            self.assertEqual(
                array.get_sequential_write_performance(),
                (number_of_subsystems / 3) * 50,
            )
            self.assertEqual(
                array.get_read_IO_performance(), number_of_subsystems * 1000
            )
            self.assertEqual(
                array.get_write_IO_performance(), (number_of_subsystems / 3) * 400
            )
            self.assertEqual(
                array.get_storage_blow_up(),
                3,
            )

            # same with different number of disks:
            dev: Device = Device(100, 50, 1000, 400)
            array: SubSystem = RAID_1([RAID_0([dev] * 3 * scale_factor)] * 2)

            # reads use all devices, writes only the devices of one RAID 0 array, i.e. half of them:
            self.assertEqual(
                array.get_sequential_read_performance(), number_of_subsystems * 100
            )
            self.assertEqual(
                array.get_sequential_write_performance(),
                (number_of_subsystems / 2) * 50,
            )
            self.assertEqual(
                array.get_read_IO_performance(), number_of_subsystems * 1000
            )
            self.assertEqual(
                array.get_write_IO_performance(), (number_of_subsystems / 2) * 400
            )
            self.assertEqual(
                array.get_storage_blow_up(),
                2,
            )

    def test_RAID_01_resilience_scenarios(self) -> None:
        """RAID 0+1 recovers all data as long as one of its mirrored RAID 0 arrays survives; a RAID 0 array tolerates
        no failure, so a single failed device takes its whole RAID 0 array down."""

        # mirror three RAID 0 arrays of two devices each (bottom layer is RAID 0), all distinct objects:
        stripes: list[SubSystem] = [
            RAID_0([Device(100, 50, 1000, 400) for _ in range(2)]) for _ in range(3)
        ]
        array: SubSystem = RAID_1(stripes)

        # only the RAID 1 array on top reports a scenario; the RAID 0 arrays and the devices report none:
        resilience_scenarios_infos: list[
            tuple[int, SubSystem, ResilienceScenario, Iterator[SubSystem] | None]
        ] = list(array.get_resilience_scenarios())
        self.assertEqual(len(resilience_scenarios_infos), 1)

        # all but one of the three RAID 0 arrays may fail (the same objects, in member order):
        rec_depth, sub_system, resilience_scenario, failing_subsystems = (
            resilience_scenarios_infos[0]
        )
        self.assertEqual(rec_depth, 0)
        self.assertIs(sub_system, array)
        self.assertEqual(
            resilience_scenario, ResilienceScenario.ALL_BUT_ONE_SUBSYSTEM_MAY_FAIL
        )
        assert failing_subsystems is not None
        self.assertEqual(
            [id(subsystem) for subsystem in failing_subsystems],
            [id(stripe) for stripe in stripes],
        )

    def test_RAID_10(self) -> None:
        """RAID 1+0 reads with all its devices but writes only as fast as one device per RAID 1 array, and stores one
        copy per device of a RAID 1 array."""

        # RAID 1+0: RAID 1 arrays in a RAID 0 subsystem (i.e. bottom layer is RAID 1)
        dev: Device = Device(100, 50, 1000, 400)
        scale_factor: int
        for scale_factor in [1, 2, 10]:
            # stripe over three RAID 1 arrays of 2 * scale_factor devices each:
            number_of_subsystems: int = 6 * scale_factor
            array: SubSystem = RAID_0([RAID_1([dev] * 2 * scale_factor)] * 3)

            # reads use all devices, writes one device per RAID 1 array:
            self.assertEqual(
                array.get_sequential_read_performance(), number_of_subsystems * 100
            )
            self.assertEqual(
                array.get_sequential_write_performance(),
                (number_of_subsystems / (2 * scale_factor)) * 50,
            )
            self.assertEqual(
                array.get_read_IO_performance(), number_of_subsystems * 1000
            )
            self.assertEqual(
                array.get_write_IO_performance(),
                (number_of_subsystems / (2 * scale_factor)) * 400,
            )
            self.assertEqual(
                array.get_storage_blow_up(),
                2 * scale_factor,
            )

            # same with different number of disks:
            dev: Device = Device(100, 50, 1000, 400)
            array: SubSystem = RAID_0([RAID_1([dev] * 3 * scale_factor)] * 2)

            # reads use all devices, writes one device per RAID 1 array:
            self.assertEqual(
                array.get_sequential_read_performance(), number_of_subsystems * 100
            )
            self.assertEqual(
                array.get_sequential_write_performance(),
                (number_of_subsystems / (3 * scale_factor)) * 50,
            )
            self.assertEqual(
                array.get_read_IO_performance(), number_of_subsystems * 1000
            )
            self.assertEqual(
                array.get_write_IO_performance(),
                (number_of_subsystems / (3 * scale_factor)) * 400,
            )
            self.assertEqual(
                array.get_storage_blow_up(),
                3 * scale_factor,
            )

    def test_RAID_10_resilience_scenarios(self) -> None:
        """RAID 1+0 recovers all data as long as each of its mirrored pairs keeps one device; the RAID 0 array on
        top tolerates no failure, so losing both devices of one pair loses data."""

        # stripe over three mirrored pairs of devices (bottom layer is RAID 1), all distinct objects:
        pairs: list[list[SubSystem]] = [
            [Device(100, 50, 1000, 400) for _ in range(2)] for _ in range(3)
        ]
        mirrors: list[SubSystem] = [RAID_1(pair) for pair in pairs]
        array: SubSystem = RAID_0(mirrors)

        # the RAID 0 array on top and the devices report no scenario, each RAID 1 pair reports one:
        resilience_scenarios_infos: list[
            tuple[int, SubSystem, ResilienceScenario, Iterator[SubSystem] | None]
        ] = list(array.get_resilience_scenarios())
        self.assertEqual(len(resilience_scenarios_infos), 3)

        # in each pair (in member order), all but one of its two devices may fail:
        for rsi, mirror, pair in zip(resilience_scenarios_infos, mirrors, pairs):
            rec_depth, sub_system, resilience_scenario, failing_subsystems = rsi
            self.assertEqual(rec_depth, 1)
            self.assertIs(sub_system, mirror)
            self.assertEqual(
                resilience_scenario, ResilienceScenario.ALL_BUT_ONE_SUBSYSTEM_MAY_FAIL
            )
            assert failing_subsystems is not None
            self.assertEqual(
                [id(subsystem) for subsystem in failing_subsystems],
                [id(device) for device in pair],
            )

    def test_RAID_55(self) -> None:
        """RAID 5+5 loses one subsystem's worth of sequential speed on each of its two layers, serves random reads
        with all its devices, and applies the small-write formula of RAID 5 on each layer, rounded per layer.
        """

        # RAID 5+5: RAID 5 arrays in a RAID 5 subsystem (i.e. bottom layer is RAID 5)
        dev: Device = Device(100, 50, 1000, 400)
        scale_factor: int
        for scale_factor in [2]:
            # combine three RAID 5 arrays of 2 * scale_factor devices each with RAID 5:
            disks_inner: int = 2 * scale_factor
            disks_outer: int = 3
            inner_array: SubSystem = RAID_5([dev] * disks_inner)
            array: SubSystem = RAID_5([inner_array] * disks_outer)

            # each layer keeps the sequential speed of all but one of its subsystems for the data:
            self.assertEqual(
                array.get_sequential_read_performance(),
                (disks_inner - 1) * (disks_outer - 1) * 100,
            )
            self.assertEqual(
                array.get_sequential_write_performance(),
                (disks_inner - 1) * (disks_outer - 1) * 50,
            )

            # an inner RAID 5 reads with all its devices; with scale_factor 2, its four devices serve
            # 4 / (2 / 1000 + 2 / 400) = 571.43 small writes per second, rounded to 571:
            self.assertEqual(inner_array.get_read_IO_performance(), disks_inner * 1000)
            self.assertEqual(inner_array.get_write_IO_performance(), 571)

            # the outer RAID 5 reads with all inner arrays; its three inner arrays serve 3 / (2 / 4000 + 2 / 571)
            # = 749.508 small writes per second, just above 749.5, so it rounds to 750 (with the unrounded inner
            # value 571.43, the result would be exactly 750):
            self.assertEqual(
                array.get_read_IO_performance(), disks_inner * disks_outer * 1000
            )
            self.assertEqual(array.get_write_IO_performance(), 750)

            # each layer adds its own parity:
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

    def test_RAID_510_resilience_scenarios(self) -> None:
        """RAID 5+1+0 (RAID 5 arrays mirrored by RAID 1 arrays, which RAID 0 stripes over) reports one scenario per
        RAID 1 array (all but one of its RAID 5 arrays may fail) and one per RAID 5 array (any single device may
        fail); the RAID 0 array and the devices report none."""

        # RAID 0 over three RAID 1 arrays, each over three RAID 5 arrays of three devices (bottom layer is RAID 5):
        dev: Device = Device(100, 50, 1000, 400)
        array: SubSystem = RAID_0([RAID_1([RAID_5([dev] * 3)] * 3)] * 3)

        # get all possible error scenarios:
        resilience_scenarios_infos: list[
            tuple[int, SubSystem, ResilienceScenario, Iterator[SubSystem] | None]
        ] = list(array.get_resilience_scenarios())

        # Output resilience scenarios for debugging purposes:
        # RAIDPerformanceTest._print_resilient_info(array)

        # 3 RAID 1 arrays and 3 * 3 RAID 5 arrays report a scenario:
        self.assertEqual(len(resilience_scenarios_infos), 12)

        # the RAID 1 arrays sit one level below the top, the RAID 5 arrays two levels:
        for rsi in resilience_scenarios_infos:
            rec_depth: int = rsi[0]
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

    def test_RAID_5005105(self) -> None:
        """A deeply nested array applies the formula of each RAID level layer by layer, for sequential reads and
        writes and for read and write IOPS."""

        # RAID 5+0+0+5+...: RAID 5 arrays in a RAID 0 subsystem (i.e. bottom layer is RAID 5)
        dev: Device = Device(100, 50, 1000, 400)
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

        # sequential read: RAID 5 multiplies the speed by n - 1, RAID 0 and RAID 1 multiply it by n:
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

        # sequential write: as for reads, except that RAID 1 writes only as fast as one of its subsystems:
        self.assertEqual(
            array.get_sequential_write_performance(),
            50
            * (number_of_subsystems - 1)  # RAID 5 (starting from innermost)
            * number_of_subsystems  # RAID 0
            * number_of_subsystems  # RAID 0
            * (number_of_subsystems - 1)  # RAID 5
            * 1  # RAID 1
            * number_of_subsystems  # RAID 0
            * (number_of_subsystems - 1),  # RAID 5
        )

        # read IOPS: every level adds up the read IOPS of its subsystems, RAID 5 included, as its rotating parity
        # puts data on every subsystem; this gives 1000 * 3^7 = 2187000:
        self.assertEqual(
            array.get_read_IO_performance(),
            1000
            * number_of_subsystems  # RAID 5 (starting from innermost)
            * number_of_subsystems  # RAID 0
            * number_of_subsystems  # RAID 0
            * number_of_subsystems  # RAID 5
            * number_of_subsystems  # RAID 1
            * number_of_subsystems  # RAID 0
            * number_of_subsystems,  # RAID 5
        )

        # write IOPS, layer by layer from the innermost: RAID 0 adds up the write IOPS of its subsystems, RAID 1
        # takes their minimum, and RAID 5 serves round(3 / (2 / R + 2 / W)) small writes per second, where R and W
        # are the read and write IOPS of its subsystems (R is the read IOPS of the layer below, see above: 1000,
        # 1000 * 3^3 = 27000 and 1000 * 3^6 = 729000):
        #   RAID 5:  3 / (2 / 1000 + 2 / 400)     =   428.57 ->   429
        #   RAID 0:  3 * 429                                  =  1287
        #   RAID 0:  3 * 1287                                 =  3861
        #   RAID 5:  3 / (2 / 27000 + 2 / 3861)   =  5066.93 ->  5067
        #   RAID 1:  min(5067, 5067, 5067)                    =  5067
        #   RAID 0:  3 * 5067                                 = 15201
        #   RAID 5:  3 / (2 / 729000 + 2 / 15201) = 22335.76 -> 22336
        self.assertEqual(array.get_write_IO_performance(), 22336)

        # Output resilience scenarios for debugging purposes:
        # RAIDPerformanceTest._print_resilient_info(array)
