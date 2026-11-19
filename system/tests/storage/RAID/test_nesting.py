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
"""Tests for nested RAID 0 arrays built from factorisations of the number of devices."""

import math
from collections.abc import Sequence

from system.storage.RAID.cost_model import Device, RAID_0, SubSystem, SubSystemArray
from system.storage.RAID.nesting import (
    arrangements_of_mixed_devices,
    build_nested_raid_0,
    count_devices,
    factorisations,
)
from system.tests.abstract_unit_test import AbstractUnitTest


def make_device() -> Device:
    """Returns a device with 100 MB/s sequential read and write and 1000 IOPS."""
    return Device(100, 100, 1000, 1000)


def devices_of(subsystem: SubSystem) -> list[SubSystem]:
    """Returns the devices at the bottom of a subsystem, from left to right.

    @param subsystem: a device or an array of subsystems.
    @return: the subsystem itself if it is not an array, else the devices of all its members.
    """
    if isinstance(subsystem, SubSystemArray):
        return [
            device for member in subsystem.subsystems for device in devices_of(member)
        ]
    return [subsystem]


def speeds(subsystem: SubSystem) -> list[int]:
    """Returns the sorted sequential read speeds of the devices of a subsystem.

    @param subsystem: a device or an array of subsystems.
    @return: the speeds in MB/s, ascending.
    """
    return sorted(
        device.get_sequential_read_performance() for device in devices_of(subsystem)
    )


class FactorisationsTest(AbstractUnitTest):

    def test_factorisations_of_12(self) -> None:
        """factorisations(12) yields the seven ordered factorisations of 12 into factors of at least 2, all except
        the trivial [12]."""
        self.assertListEqual(
            sorted(factorisations(12)),
            [[2, 2, 3], [2, 3, 2], [2, 6], [3, 2, 2], [3, 4], [4, 3], [6, 2]],
        )

    def test_factorisations_of_a_prime(self) -> None:
        """A prime has no factorisation into factors of at least 2 other than itself."""
        self.assertListEqual(list(factorisations(13)), [])

    def test_factorisations_of_32(self) -> None:
        """factorisations(32) yields 15 distinct ordered factorisations, all except the trivial [32]; each one
        multiplies to 32 and has only factors of at least 2."""
        configs: list[list[int]] = list(factorisations(32))
        self.assertEqual(len(configs), 15)
        self.assertEqual(len({tuple(config) for config in configs}), 15)
        for config in configs:
            self.assertEqual(math.prod(config), 32)
            self.assertTrue(all(factor >= 2 for factor in config))


class CountDevicesTest(AbstractUnitTest):

    def test_count_devices(self) -> None:
        """count_devices counts the devices at the bottom of a subsystem, however deeply it is nested."""

        # a single device and a flat stripe of five devices:
        self.assertEqual(count_devices(make_device()), 1)
        self.assertEqual(count_devices(RAID_0([make_device() for _ in range(5)])), 5)

        # a hand-built nesting of a stripe of four and a stripe of two devices:
        nested: RAID_0 = RAID_0(
            [
                RAID_0([make_device() for _ in range(4)]),
                RAID_0([make_device() for _ in range(2)]),
            ]
        )
        self.assertEqual(count_devices(nested), 6)


class BuildNestedRAID0Test(AbstractUnitTest):

    def assert_levels(self, subsystem: SubSystem, config: Sequence[int]) -> None:
        """Asserts that the subsystem is a RAID 0 with config[0] members, that each member is nested in the same
        way by the remaining factors, and that the members of the innermost level are devices.

        @param subsystem: the subsystem to check.
        @param config: the factors of the levels, outermost first.
        """
        # this level has as many members as its factor:
        self.assertIsInstance(subsystem, RAID_0)
        assert isinstance(subsystem, RAID_0)
        self.assertEqual(len(subsystem.subsystems), config[0])

        # every member is a device on the innermost level and an array of the next level otherwise:
        for member in subsystem.subsystems:
            if len(config) == 1:
                self.assertIsInstance(member, Device)
            else:
                self.assert_levels(member, config[1:])

    def test_nesting_contains_product_of_factors_devices(self) -> None:
        """A nesting built from a factorisation of 32 contains 32 separate devices, and each of its levels has as
        many members as the factor of that level."""
        configs: list[list[int]] = list(factorisations(32))
        self.assertEqual(len(configs), 15)
        for config in configs:
            with self.subTest(config=config):
                nesting: RAID_0 = build_nested_raid_0(config, make_device)
                self.assertEqual(count_devices(nesting), 32)
                self.assert_levels(nesting, config)
                # every slot holds a device of its own:
                self.assertEqual(
                    len({id(device) for device in devices_of(nesting)}), 32
                )

    def test_nestings_of_identical_devices_read_like_a_flat_stripe(self) -> None:
        """Every nesting built from a factorisation of 32 identical 100 MB/s devices, whose members of a level are
        all alike, reads 3200 MB/s sequentially, as one flat RAID 0 of all 32 devices does.
        """

        # the flat stripe of 32 devices:
        flat: RAID_0 = RAID_0([make_device() for _ in range(32)])
        self.assertEqual(flat.get_sequential_read_performance(), 3200)

        # every nesting of the same 32 devices reads as fast:
        configs: list[list[int]] = list(factorisations(32))
        self.assertEqual(len(configs), 15)
        for config in configs:
            with self.subTest(config=config):
                nesting: RAID_0 = build_nested_raid_0(config, make_device)
                self.assertEqual(nesting.get_sequential_read_performance(), 3200)

    def test_nesting_with_unequal_members_is_slower_than_a_flat_stripe(self) -> None:
        """A RAID 0 of a stripe of three identical devices and a fourth device reads 200 MB/s, half as much as a
        flat stripe of the four devices: the single device throttles the faster member.
        """
        unequal: RAID_0 = RAID_0(
            [RAID_0([make_device() for _ in range(3)]), make_device()]
        )
        flat: RAID_0 = RAID_0([make_device() for _ in range(4)])
        self.assertEqual(unequal.get_sequential_read_performance(), 200)
        self.assertEqual(flat.get_sequential_read_performance(), 400)

    def test_single_factor_is_a_flat_stripe(self) -> None:
        """A factorisation with a single factor builds one flat RAID 0 over that many devices."""
        self.assert_levels(build_nested_raid_0([5], make_device), [5])

    def test_factor_1_is_allowed(self) -> None:
        """A factor of 1 builds a level with a single member, here two RAID 0 arrays of one device each."""
        nesting: RAID_0 = build_nested_raid_0([2, 1], make_device)
        self.assert_levels(nesting, [2, 1])
        self.assertEqual(count_devices(nesting), 2)

    def test_invalid_config_is_rejected(self) -> None:
        """An empty factorisation and a factor below 1 are rejected."""
        with self.assertRaises(ValueError):
            build_nested_raid_0([], make_device)
        with self.assertRaises(ValueError):
            build_nested_raid_0([2, 0], make_device)


class ArrangementsOfMixedDevicesTest(AbstractUnitTest):

    def test_grouping_devices_by_speed(self) -> None:
        """With four slow (100 MB/s) and two fast (200 MB/s) devices, a flat stripe reads 600 MB/s, grouping the
        devices by speed reads 800 MB/s, and mixing slow and fast devices in both groups reads 400 MB/s.
        """

        # build the three arrangements of the same six devices:
        arrangements: dict[str, RAID_0] = arrangements_of_mixed_devices(
            lambda: Device(100, 100, 1000, 1000), lambda: Device(200, 200, 2000, 2000)
        )
        self.assertListEqual(
            list(arrangements), ["flat", "grouped by speed", "mixed groups"]
        )

        # each one uses all six devices, four slow and two fast ones:
        for arrangement in arrangements.values():
            self.assertEqual(count_devices(arrangement), 6)
            self.assertListEqual(speeds(arrangement), [100] * 4 + [200] * 2)

        # the members of each arrangement hold these devices:
        members: dict[str, list[list[int]]] = {
            name: [speeds(member) for member in arrangement.subsystems]
            for name, arrangement in arrangements.items()
        }
        self.assertDictEqual(
            members,
            {
                "flat": [[100]] * 4 + [[200]] * 2,
                "grouped by speed": [[100] * 4, [200] * 2],
                "mixed groups": [[100, 100, 100, 200], [100, 200]],
            },
        )

        # the slowest device throttles the flat stripe; grouping by speed gives two equally fast members:
        reads: dict[str, int] = {
            name: arrangement.get_sequential_read_performance()
            for name, arrangement in arrangements.items()
        }
        self.assertDictEqual(
            reads, {"flat": 600, "grouped by speed": 800, "mixed groups": 400}
        )
