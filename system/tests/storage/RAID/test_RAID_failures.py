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
"""Tests for the failure tolerance of RAID arrays: which combinations of failed devices an array survives."""

from math import comb

from system.storage.RAID.cost_model import (
    Device,
    FailureCount,
    RAID_0,
    RAID_1,
    RAID_5,
    ResilienceScenario,
    SubSystem,
    count_survived_failures,
)
from system.tests.abstract_unit_test import AbstractUnitTest


def _devices(number_of_devices: int) -> list[Device]:
    """Returns the given number of distinct Device objects, all with the same performance characteristics.

    @param number_of_devices: How many devices to create.
    @return: A list of new, distinct devices.
    """
    return [Device(100, 100, 1000, 1000) for _ in range(number_of_devices)]


class DeviceFailureTest(AbstractUnitTest):

    def test_device_survives_only_the_failure_of_other_devices(self):
        """A device survives when no device or only other devices fail, but not when it fails itself."""
        device, other = _devices(2)

        # no failure and the failure of another device with the same performance characteristics leave it intact:
        self.assertTrue(device.survives(set()))
        self.assertTrue(device.survives({other}))

        # its own failure does not, also not together with another one:
        self.assertFalse(device.survives({device}))
        self.assertFalse(device.survives({device, other}))

    def test_devices_of_a_device_and_of_a_nested_array(self):
        """A device yields only itself; a nested array yields the devices of its members, member by member."""
        a, b, c, d = _devices(4)
        self.assertEqual(list(a.devices()), [a])

        # the order follows the members, not the order in which the devices were created:
        array: SubSystem = RAID_1([RAID_0([c, d]), RAID_0([a, b])])
        self.assertEqual(list(array.devices()), [c, d, a, b])


class RAIDFailureTest(AbstractUnitTest):

    def test_RAID_0_survives_no_failure_of_a_device(self):
        """RAID 0 of 4 devices loses data whenever any one of its devices fails."""
        array: SubSystem = RAID_0(_devices(4))
        self.assertEqual(count_survived_failures(array, 1), FailureCount(0, 4))

    def test_RAID_1_survives_all_but_one_failure(self):
        """RAID 1 of 3 devices survives any 2 failed devices, but not the failure of all 3."""
        array: SubSystem = RAID_1(_devices(3))
        self.assertEqual(count_survived_failures(array, 2), FailureCount(3, 3))
        self.assertEqual(count_survived_failures(array, 3), FailureCount(0, 1))

    def test_RAID_5_survives_a_single_but_no_double_failure(self):
        """RAID 5 of 4 devices survives any single failed device, but no 2 failed devices."""
        array: SubSystem = RAID_5(_devices(4))
        self.assertEqual(count_survived_failures(array, 1), FailureCount(4, 4))
        self.assertEqual(count_survived_failures(array, 2), FailureCount(0, 6))

    def test_RAID_01_with_4_devices(self):
        """RAID 0+1 (a RAID 1 over the two stripes (a, b) and (c, d)) survives every single failed device, but
        only 2 of the 6 double failures: those that hit one stripe only, {a, b} and {c, d}.
        """
        a, b, c, d = _devices(4)
        array: SubSystem = RAID_1([RAID_0([a, b]), RAID_0([c, d])])

        # every single failure leaves the other stripe intact:
        self.assertEqual(count_survived_failures(array, 1), FailureCount(4, 4))

        # a double failure is survived only if both failed devices are in the same stripe:
        double_failures: FailureCount = count_survived_failures(array, 2)
        self.assertEqual(double_failures.survived, 2)
        self.assertEqual(double_failures.total, 6)
        self.assertTrue(array.survives({a, b}))
        self.assertTrue(array.survives({c, d}))

    def test_RAID_01_counts_failures_in_both_stripes_as_data_loss(self):
        """RAID 0+1 over the stripes (a, b) and (c, d) counts the failure of a and d as data loss.

        Every block still exists once (in b and c), but the model treats a stripe that loses a device as failed
        as a whole and never combines the surviving parts of the two stripes, see :meth:`SubSystem.survives`.
        """
        a, b, c, d = _devices(4)
        array: SubSystem = RAID_1([RAID_0([a, b]), RAID_0([c, d])])
        self.assertFalse(array.survives({a, d}))

    def test_RAID_10_with_4_devices(self):
        """RAID 1+0 (a RAID 0 over the two mirrored pairs (a, b) and (c, d)) survives every single failed device
        and 4 of the 6 double failures: all except those that hit both devices of a pair, {a, b} and {c, d}.
        """
        a, b, c, d = _devices(4)
        array: SubSystem = RAID_0([RAID_1([a, b]), RAID_1([c, d])])

        # every single failure leaves a copy in the same pair:
        self.assertEqual(count_survived_failures(array, 1), FailureCount(4, 4))

        # a double failure loses data only if it hits both devices of one pair:
        self.assertEqual(count_survived_failures(array, 2), FailureCount(4, 6))
        self.assertFalse(array.survives({a, b}))
        self.assertTrue(array.survives({a, d}))

    def test_RAID_01_and_RAID_10_with_6_devices(self):
        """With 6 devices, RAID 0+1 as two stripes of 3 survives 6 of the 15 double failures, RAID 1+0 as three
        mirrored pairs survives 12 of them."""
        # RAID 0+1: a double failure is survived only within one stripe, i.e. in 2 * C(3, 2) = 6 combinations:
        devices: list[Device] = _devices(6)
        raid_01: SubSystem = RAID_1([RAID_0(devices[0:3]), RAID_0(devices[3:6])])
        self.assertEqual(count_survived_failures(raid_01, 2), FailureCount(6, 15))

        # RAID 1+0: a double failure loses data only if it hits both devices of one of the 3 pairs:
        devices = _devices(6)
        raid_10: SubSystem = RAID_0(
            [RAID_1(devices[0:2]), RAID_1(devices[2:4]), RAID_1(devices[4:6])]
        )
        self.assertEqual(count_survived_failures(raid_10, 2), FailureCount(12, 15))

    def test_nested_RAID_5_over_RAID_0_pairs(self):
        """A RAID 5 over three RAID 0 pairs (6 devices) survives a double failure only if both failed devices
        are in the same pair, which is then the one lost member: 3 of the 15 combinations.
        """
        devices: list[Device] = _devices(6)
        array: SubSystem = RAID_5(
            [RAID_0(devices[0:2]), RAID_0(devices[2:4]), RAID_0(devices[4:6])]
        )
        self.assertEqual(count_survived_failures(array, 2), FailureCount(3, 15))

    def test_survives_agrees_with_the_resilience_scenario(self):
        """RAID 1 of n devices survives every combination of n - 1 failed devices, as its resilience scenario
        ALL_BUT_ONE_SUBSYSTEM_MAY_FAIL states; RAID 5 survives every single failed device, as
        ANY_SINGLE_SUBSYSTEM_MAY_FAIL states."""
        number_of_devices: int
        for number_of_devices in [2, 3, 5]:
            with self.subTest(level="RAID 1", number_of_devices=number_of_devices):
                # RAID 1: the scenario says all but one device may fail, and every such combination is survived:
                raid_1: SubSystem = RAID_1(_devices(number_of_devices))
                scenario = raid_1.get_resilience_scenario()
                assert scenario is not None
                self.assertEqual(
                    scenario[0], ResilienceScenario.ALL_BUT_ONE_SUBSYSTEM_MAY_FAIL
                )
                combinations: int = comb(number_of_devices, number_of_devices - 1)
                self.assertEqual(
                    count_survived_failures(raid_1, number_of_devices - 1),
                    FailureCount(combinations, combinations),
                )

        for number_of_devices in [3, 4, 6]:
            with self.subTest(level="RAID 5", number_of_devices=number_of_devices):
                # RAID 5: the scenario says any single device may fail, and every single failure is survived:
                raid_5: SubSystem = RAID_5(_devices(number_of_devices))
                scenario = raid_5.get_resilience_scenario()
                assert scenario is not None
                self.assertEqual(
                    scenario[0], ResilienceScenario.ANY_SINGLE_SUBSYSTEM_MAY_FAIL
                )
                self.assertEqual(
                    count_survived_failures(raid_5, 1),
                    FailureCount(number_of_devices, number_of_devices),
                )


class FailureCountEdgeCaseTest(AbstractUnitTest):

    def test_no_failed_device_is_always_survived(self):
        """Without any failed device there is exactly one combination, and every subsystem survives it."""
        self.assertEqual(
            count_survived_failures(RAID_0(_devices(3)), 0), FailureCount(1, 1)
        )
        self.assertEqual(count_survived_failures(_devices(1)[0], 0), FailureCount(1, 1))

    def test_number_of_failed_devices_out_of_range_raises(self):
        """A negative number of failed devices or more failed devices than the subsystem has raise ValueError."""
        array: SubSystem = RAID_1(_devices(3))
        with self.assertRaises(ValueError):
            count_survived_failures(array, -1)
        with self.assertRaises(ValueError):
            count_survived_failures(array, 4)

    def test_reused_device_raises(self):
        """count_survived_failures raises ValueError for an array that contains the same Device object several
        times, since such an array does not model distinct devices."""
        a, b, c = _devices(3)

        # the same device as several members, as built with [device] * n:
        with self.assertRaises(ValueError):
            count_survived_failures(RAID_1([a] * 3), 1)

        # the same device in two different inner arrays:
        with self.assertRaises(ValueError):
            count_survived_failures(RAID_1([RAID_0([a, b]), RAID_0([a, c])]), 1)

    def test_reused_inner_array_raises(self):
        """count_survived_failures raises ValueError for an array that uses the same inner array as several
        members, since the devices of that inner array appear several times."""
        inner: SubSystem = RAID_0(_devices(2))
        with self.assertRaises(ValueError):
            count_survived_failures(RAID_1([inner, inner]), 1)
