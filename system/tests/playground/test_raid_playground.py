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
"""Tests for the RAID playground's model: building arrays, their metrics, the blocks on the disks and their states."""

from __future__ import annotations

import unittest
from collections import Counter
from itertools import combinations
from typing import cast

from system.playground.raid_playground import (
    DEFAULT_DEVICE_TYPES,
    LEVELS,
    MAX_MEMBERS,
    MIN_MEMBERS,
    PRESETS,
    BlockState,
    Configuration,
    DeviceKind,
    Level,
    Metrics,
    Structure,
    all_blocks_readable,
    all_data_readable,
    block_rows,
    build,
    check_members,
    configuration,
    disk_blocks,
    failure_counts,
    layout,
    metrics,
)
from system.storage.RAID.cost_model import (
    RAID_0,
    RAID_1,
    Device,
    FailureCount,
    SubSystem,
    SubSystemArray,
)


def preset(name: str, kinds: tuple[DeviceKind, ...] | None = None) -> Configuration:
    """Returns the configuration of the preset called ``name``, with all disks fast unless ``kinds`` says otherwise."""
    return configuration(PRESETS[name], kinds)


def single(level: Level, disks: int) -> Configuration:
    """Returns a single-level configuration of ``level`` over ``disks`` fast disks."""
    return configuration(Structure(level, disks, None, 1))


def shape(subsystem: SubSystem) -> object:
    """Returns the class of a device, or the class of an array together with the shapes of its members."""
    if isinstance(subsystem, SubSystemArray):
        return type(subsystem), [shape(member) for member in subsystem.subsystems]
    return type(subsystem)


def texts(config: Configuration, rows: int) -> list[list[str]]:
    """Returns the text of every block of the first ``rows`` rows, disk by disk."""
    return [[block.text for block in column] for column in layout(config, rows)]


def states(config: Configuration, failed: set[int]) -> list[list[BlockState]]:
    """Returns the state of every block in the disk columns, disk by disk."""
    return [[cell.state for cell in column] for column in disk_blocks(config, failed)]


def every_subset(disks: int) -> list[set[int]]:
    """Returns every set of slots out of ``disks`` slots, from the empty set to all of them."""
    return [
        set(subset)
        for size in range(disks + 1)
        for subset in combinations(range(disks), size)
    ]


def structures_up_to(disks: int) -> list[Structure]:
    """Returns every single-level and two-level structure with at most ``disks`` disks."""
    found: list[Structure] = []
    for outer in LEVELS:
        for outer_members in range(MIN_MEMBERS[outer], MAX_MEMBERS + 1):
            if outer_members <= disks:
                found.append(Structure(outer, outer_members, None, 1))
            for inner in LEVELS:
                for inner_members in range(MIN_MEMBERS[inner], MAX_MEMBERS + 1):
                    if outer_members * inner_members <= disks:
                        found.append(
                            Structure(outer, outer_members, inner, inner_members)
                        )
    return found


class SlotOrderTest(unittest.TestCase):
    """Which disks a slot is in, and therefore which failures an array survives."""

    def test_0_plus_1_and_1_plus_0_survive_opposite_pairs(self) -> None:
        """RAID 0+1 (a mirror of the stripes (a, b) and (c, d)) survives the failure of disks a and b but not of a
        and c; RAID 1+0 (a stripe over the mirrored pairs (a, b) and (c, d)) the other way round.

        Would fail if the slots were assigned to the inner arrays column by column (slot i in inner array
        ``i % outer_members``) or if the presets swapped the inner and the outer level.
        """
        for name, survives_a_b, survives_a_c in (
            ("RAID 0+1", True, False),
            ("RAID 1+0", False, True),
        ):
            with self.subTest(preset=name):
                config: Configuration = preset(name)
                self.assertEqual(survives_a_b, all_data_readable(config, {0, 1}))
                self.assertEqual(survives_a_c, all_data_readable(config, {0, 2}))


class BuildTest(unittest.TestCase):
    """Building the cost model's array of a configuration."""

    def test_raid_0_plus_1_is_a_mirror_of_stripes(self) -> None:
        """The preset RAID 0+1 builds a RAID 1 over two RAID 0 arrays of two devices each.

        Would fail if the preset's levels were swapped, so that RAID 0+1 built a stripe over mirrored pairs.
        """
        self.assertEqual(
            (RAID_1, [(RAID_0, [Device, Device]), (RAID_0, [Device, Device])]),
            shape(build(preset("RAID 0+1"), DEFAULT_DEVICE_TYPES)),
        )

    def test_devices_are_distinct_and_in_slot_order(self) -> None:
        """Every slot gets its own Device object, of the kind the configuration gives the slot, and the array lists
        the devices in slot order.

        Would fail if one Device object were shared by several slots, so that a failure counted for all of them, or
        if the devices were built in another order than the kinds.
        """
        kinds: tuple[DeviceKind, ...] = ("slow", "fast", "fast", "slow")
        devices: list[Device] = list(
            build(preset("RAID 0+1", kinds), DEFAULT_DEVICE_TYPES).devices()
        )
        # four distinct objects:
        self.assertEqual(4, len({id(device) for device in devices}))
        # slow disks read 100 MB/s, fast ones 200 MB/s:
        self.assertEqual(
            [100, 200, 200, 100],
            [device.get_sequential_read_performance() for device in devices],
        )


class ConfigurationTest(unittest.TestCase):
    """Checking and normalising a configuration."""

    def test_member_counts_are_checked(self) -> None:
        """RAID 5 needs at least 3 members and no array has more than 6, in the outer as in the inner level.

        Would fail if a RAID 5 of two disks, which the cost model cannot build, or an array wider than the sliders
        allow were accepted.
        """
        for structure in (
            Structure(5, 2, None, 1),
            Structure(0, 7, None, 1),
            Structure(1, 2, 5, 2),
            Structure(0, 2, 1, 7),
        ):
            with self.subTest(structure=structure):
                with self.assertRaises(ValueError):
                    configuration(structure)

    def test_member_limits_of_each_level(self) -> None:
        """RAID 0 and RAID 1 take 2 to 6 members, RAID 5 takes 3 to 6: ``check_members`` accepts both ends and
        rejects one member fewer and one more.

        Would fail if a limit were off by one, e.g. if RAID 0 accepted a single member, if RAID 5 rejected three
        members, or if no level accepted six, the most the sliders offer.
        """
        limits: tuple[tuple[Level, int], ...] = ((0, 2), (1, 2), (5, 3))
        for level, fewest in limits:
            with self.subTest(level=level):
                # both ends are accepted:
                check_members(level, fewest)
                check_members(level, 6)
                # one member fewer and one more are not:
                for members in (fewest - 1, 7):
                    with self.assertRaises(ValueError):
                        check_members(level, members)

    def test_unknown_levels_and_kinds_are_rejected(self) -> None:
        """A level other than 0, 1 and 5, in the outer or the inner level, and a kind other than slow and fast raise
        a ValueError, not a KeyError from a lookup.

        Would fail if an unknown level or kind were only noticed when the array is built.
        """
        # RAID 4 as the outer level, RAID 3 as the inner one:
        for structure in (
            Structure(cast(Level, 4), 3, None, 1),
            Structure(1, 2, cast(Level, 3), 2),
        ):
            with self.subTest(structure=structure):
                with self.assertRaises(ValueError):
                    configuration(structure)
        # a disk of a third kind:
        with self.assertRaises(ValueError):
            configuration(PRESETS["RAID 1"], ("fast", cast(DeviceKind, "medium")))

    def test_kinds_must_match_the_disks(self) -> None:
        """A configuration needs exactly one kind per disk.

        Would fail if a configuration with too few kinds were accepted, so that building it lost disks.
        """
        with self.assertRaises(ValueError):
            Configuration(1, 2, 0, 2, ("fast",) * 3)

    def test_inner_members_without_inner_level_is_one(self) -> None:
        """Without an inner level, ``inner_members`` becomes 1, whatever was given, so every disk is an outer member.

        Would fail if a leftover value of the inner slider multiplied the number of disks of a single-level array.
        """
        config = Configuration(5, 4, None, 3, ("fast",) * 4)
        self.assertEqual(1, config.inner_members)
        self.assertEqual(4, config.disks)
        self.assertEqual(Structure(5, 4, None, 1), config.structure)


class MetricsTest(unittest.TestCase):
    """The metrics of a configuration, with the default device types (slow: 100 MB/s, 50 MB/s, 1000 IOPS, 400 IOPS;
    fast: twice that)."""

    def test_moving_slow_disks_changes_sequential_read(self) -> None:
        """In RAID 0+1, two slow disks in the same stripe cost less sequential read than one slow disk in each
        stripe: 2 * 100 + 2 * 200 = 600 MB/s against 2 * 100 + 2 * 100 = 400 MB/s.

        Would fail if the kinds were assigned to other slots than the ones marked, so that the grouping of slow
        disks did not matter.
        """
        same_stripe = preset("RAID 0+1", ("slow", "slow", "fast", "fast"))
        both_stripes = preset("RAID 0+1", ("slow", "fast", "slow", "fast"))
        self.assertEqual(
            600, metrics(same_stripe, DEFAULT_DEVICE_TYPES).sequential_read
        )
        self.assertEqual(
            400, metrics(both_stripes, DEFAULT_DEVICE_TYPES).sequential_read
        )

    def test_raid_5_over_four_fast_disks(self) -> None:
        """RAID 5 over four fast disks: a blow-up of 4/3, three disks' worth of sequential speed, four disks' worth
        of read IOPS, round(4 / (2/2000 + 2/800)) = 1143 write IOPS; it survives every single failure and no double
        or triple one.

        Would fail if the playground passed the device types or the members to the cost model wrongly.
        """
        self.assertEqual(
            Metrics(
                storage_blow_up=4 / 3,
                usable_share=0.75,
                sequential_read=600,
                sequential_write=300,
                read_IOPS=8000,
                write_IOPS=1143,
                failure_counts=(
                    FailureCount(4, 4),
                    FailureCount(0, 6),
                    FailureCount(0, 4),
                ),
            ),
            metrics(preset("RAID 5"), DEFAULT_DEVICE_TYPES),
        )

    def test_raid_1_over_two_disks_has_no_third_failure_count(self) -> None:
        """RAID 1 over two fast disks survives each single failure, not the double one, and has no count for three
        failed disks.

        Would fail if a count were computed for more failed disks than the array has, which raises a ValueError.
        """
        self.assertEqual(
            Metrics(
                storage_blow_up=2,
                usable_share=0.5,
                sequential_read=400,
                sequential_write=100,
                read_IOPS=4000,
                write_IOPS=800,
                failure_counts=(FailureCount(2, 2), FailureCount(0, 1), None),
            ),
            metrics(preset("RAID 1"), DEFAULT_DEVICE_TYPES),
        )

    def test_0_plus_1_and_1_plus_0_differ_only_in_failures(self) -> None:
        """RAID 0+1 and RAID 1+0 over four fast disks perform the same, but survive 2 and 4 of the 6 double failures.

        Would fail if the failure counts were cached for both structures under one key, or if the two presets built
        the same array.
        """
        zero_one: Metrics = metrics(preset("RAID 0+1"), DEFAULT_DEVICE_TYPES)
        one_zero: Metrics = metrics(preset("RAID 1+0"), DEFAULT_DEVICE_TYPES)
        # the performance numbers are the same:
        performance: tuple[float | int, ...] = (2.0, 0.5, 800, 200, 8000, 1600)
        for result in (zero_one, one_zero):
            self.assertEqual(
                performance,
                (
                    result.storage_blow_up,
                    result.usable_share,
                    result.sequential_read,
                    result.sequential_write,
                    result.read_IOPS,
                    result.write_IOPS,
                ),
            )
        # only the double failures differ:
        self.assertEqual(
            (FailureCount(4, 4), FailureCount(2, 6), FailureCount(0, 4)),
            zero_one.failure_counts,
        )
        self.assertEqual(
            (FailureCount(4, 4), FailureCount(4, 6), FailureCount(0, 4)),
            one_zero.failure_counts,
        )

    def test_metrics_count_the_failures_of_a_structure_once(self) -> None:
        """All slow and all fast disks give the same failure counts, and metrics() counts them only for the first of
        the two configurations; for the second it takes them from the cache.

        Would fail if the cache were keyed by something other than the structure, so that every change of a kind
        counted all failures again, or if metrics() did not use the cached function.
        """
        structure: Structure = PRESETS["RAID 5+1"]
        failure_counts.cache_clear()
        # the first configuration of the structure counts the failures:
        slow: Metrics = metrics(
            configuration(structure, ("slow",) * 6), DEFAULT_DEVICE_TYPES
        )
        first = failure_counts.cache_info()
        self.assertEqual((0, 1), (first.hits, first.misses))
        # the second one, with other kinds, takes them from the cache:
        fast: Metrics = metrics(
            configuration(structure, ("fast",) * 6), DEFAULT_DEVICE_TYPES
        )
        second = failure_counts.cache_info()
        self.assertEqual((1, 1), (second.hits, second.misses))
        self.assertEqual(slow.failure_counts, fast.failure_counts)


class LayoutTest(unittest.TestCase):
    """Which blocks lie on which disk, composed from both levels of a nested array."""

    def test_rows_are_the_disks_between_four_and_twelve(self) -> None:
        """The disk columns show as many rows as the array has disks, but at least four and at most twelve.

        Would fail if a RAID 5 over five or six disks showed too few rows to let its parity go round all disks, or if
        a nested array of 36 disks showed 36 rows.
        """
        self.assertEqual(4, block_rows(preset("RAID 1")))
        self.assertEqual(4, block_rows(preset("RAID 0+1")))
        self.assertEqual(5, block_rows(single(5, 5)))
        self.assertEqual(6, block_rows(preset("RAID 5+0")))
        self.assertEqual(12, block_rows(configuration(Structure(0, 6, 1, 6))))

    def test_raid_5_parity_rotates(self) -> None:
        """RAID 5 over four disks puts the parity of row 0 on disk d, that of row 1 on disk a and so on, as
        ``compute_assignment`` does.

        Would fail if the columns were the rows of the assignment, or the parity did not list the blocks it covers.
        """
        self.assertEqual(
            [
                ["0", "P[3^4^5]", "6", "9"],
                ["1", "3", "P[6^7^8]", "10"],
                ["2", "4", "7", "P[9^10^11]"],
                ["P[0^1^2]", "5", "8", "11"],
            ],
            texts(preset("RAID 5"), 4),
        )

    def test_0_plus_1_and_1_plus_0(self) -> None:
        """RAID 0+1 stripes the blocks over a and b and mirrors the stripe on c and d; RAID 1+0 mirrors block 0 on
        a and b and block 1 on c and d.

        Would fail if the inner and the outer level were composed the wrong way round.
        """
        self.assertEqual(
            [["0", "2"], ["1", "3"], ["0", "2"], ["1", "3"]],
            texts(preset("RAID 0+1"), 2),
        )
        self.assertEqual(
            [["0", "2"], ["0", "2"], ["1", "3"], ["1", "3"]],
            texts(preset("RAID 1+0"), 2),
        )

    def test_raid_5_plus_0_groups_the_blocks_by_inner_array(self) -> None:
        """In RAID 5+0, the stripe puts the even blocks on the first RAID 5 array (disks a to c) and the odd ones on
        the second (disks d to f); each array adds its own parity ``p[...]`` over the blocks of its row.

        Would fail if the inner parity were written like the outer one, listed the internal block IDs of the inner
        array instead of the blocks they hold, or if the slots of one inner array were not next to each other.
        """
        self.assertEqual(
            [
                ["0", "p[4^6]"],
                ["2", "4"],
                ["p[0^2]", "6"],
                ["1", "p[5^7]"],
                ["3", "5"],
                ["p[1^3]", "7"],
            ],
            texts(preset("RAID 5+0"), 2),
        )

    def test_inner_parity_over_outer_parity(self) -> None:
        """In RAID 5+5 over three arrays of three disks, the first inner array holds block 0 and the outer parity
        ``P[2^3]`` in row 0, and its own parity over both is ``p[0^P[2^3]]``; the third holds the outer parity
        ``P[0^1]`` and block 3.

        Would fail if an inner parity flattened the outer parity it covers, or covered the wrong blocks.
        """
        # row 0 of the disks a to i, inner array by inner array:
        self.assertEqual(
            ["0", "P[2^3]", "p[0^P[2^3]]"]
            + ["1", "2", "p[1^2]"]
            + ["P[0^1]", "3", "p[P[0^1]^3]"],
            [column[0] for column in texts(configuration(Structure(5, 3, 5, 3)), 1)],
        )


class BlockStateTest(unittest.TestCase):
    """Which blocks on failed disks can still be read or rebuilt (orange) and which are lost (red)."""

    def test_raid_5_one_failed_disk_recoverable_two_lost(self) -> None:
        """In RAID 5 over four disks, the blocks on the failed disk b, data and parity, can be rebuilt from the
        other disks; with c failed as well, the blocks of both are lost.

        Would fail if a block on a working disk were marked, or the blocks of a single failed disk under RAID 5 were
        marked lost.
        """
        self.assertEqual(
            [["ok"] * 4, ["recoverable"] * 4, ["ok"] * 4, ["ok"] * 4],
            states(preset("RAID 5"), {1}),
        )
        self.assertEqual(
            [["ok"] * 4, ["lost"] * 4, ["lost"] * 4, ["ok"] * 4],
            states(preset("RAID 5"), {1, 2}),
        )

    def test_0_plus_1_with_one_failed_disk_in_each_stripe(self) -> None:
        """In RAID 0+1 with the failed disks a and d, every block is still on b or c, so the blocks on a and d are
        orange, although the model says data is lost; with a and c failed, the even blocks are gone.

        Would fail if the blocks' states followed survives() instead of the blocks, or if a block were checked
        against the wrong copy.
        """
        config: Configuration = preset("RAID 0+1")
        # a and d: every block can be read, all_data_readable still says no:
        self.assertEqual(
            [["recoverable"] * 4, ["ok"] * 4, ["ok"] * 4, ["recoverable"] * 4],
            states(config, {0, 3}),
        )
        self.assertTrue(all_blocks_readable(config, {0, 3}))
        self.assertFalse(all_data_readable(config, {0, 3}))
        # a and c: both copies of the even blocks are gone:
        self.assertEqual(
            [["lost"] * 4, ["ok"] * 4, ["lost"] * 4, ["ok"] * 4],
            states(config, {0, 2}),
        )
        self.assertFalse(all_blocks_readable(config, {0, 2}))

    def test_orange_and_red_in_one_array(self) -> None:
        """In RAID 0+1 with a, b and d failed, the even blocks on a are still on c (orange), while the odd blocks on
        b and d have lost both copies (red).

        Would fail if all blocks on failed disks got one state, as decided for the whole array.
        """
        self.assertEqual(
            [["recoverable"] * 4, ["lost"] * 4, ["ok"] * 4, ["lost"] * 4],
            states(preset("RAID 0+1"), {0, 1, 3}),
        )

    def test_inner_parity_is_recoverable_while_the_mirror_has_the_data(self) -> None:
        """In RAID 5+1 with the failed disks a and b of the first RAID 5 array, every block is still in the mirror,
        so the data blocks and the parity ``p[...]`` on a and b are orange.

        Would fail if a parity block on a failed disk were judged by its own inner array alone, not by whether the
        blocks it is computed from can still be read.
        """
        config: Configuration = preset("RAID 5+1")
        self.assertEqual(
            [["recoverable"] * 6] * 2 + [["ok"] * 6] * 4, states(config, {0, 1})
        )
        self.assertTrue(all_data_readable(config, {0, 1}))

    def test_parity_is_lost_where_its_row_lost_data(self) -> None:
        """In RAID 5+0 with a and b failed, the parity ``p[4^6]`` on a is lost, as block 4 on b is lost.

        Would fail if a parity block were orange although a block it covers cannot be read.
        """
        cells = disk_blocks(preset("RAID 5+0"), {0, 1})
        # the parity on a and the block 4 on b, both in row 1:
        self.assertEqual("p[4^6]", cells[0][1].block.text)
        self.assertEqual("4", cells[1][1].block.text)
        self.assertEqual("lost", cells[0][1].state)
        self.assertEqual("lost", cells[1][1].state)

    def test_raid_5_plus_0_loses_the_blocks_of_one_array(self) -> None:
        """In RAID 5+0 with a and c failed, the first RAID 5 array lost two disks: the blocks on a and c are lost,
        as the stripe keeps no other copy of them, and the second array is untouched.

        Would fail if a RAID 5 row with two missing blocks were rebuilt, or a block of the first array counted as
        readable because of a block of the second one.
        """
        self.assertEqual(
            [["lost"] * 6, ["ok"] * 6, ["lost"] * 6] + [["ok"] * 6] * 3,
            states(preset("RAID 5+0"), {0, 2}),
        )

    def test_levels_help_each_other_to_rebuild(self) -> None:
        """In RAID 5+1 with a, b, d and f failed, neither RAID 5 array can rebuild its blocks alone, but together
        they can: block 1 is still on e, and block 0 is the XOR of block 1 and the parity ``p[0^1]`` on c. So every
        block on a failed disk is orange, although the model says that data is lost.

        Would fail if a block of an inner RAID 5 row counted as missing although the mirror can supply it, so that
        blocks that can still be rebuilt were shown as lost.
        """
        config: Configuration = preset("RAID 5+1")
        failed: set[int] = {0, 1, 3, 5}
        # every block on a failed disk can be rebuilt:
        self.assertEqual(
            [
                ["recoverable"] * 6,
                ["recoverable"] * 6,
                ["ok"] * 6,
                ["recoverable"] * 6,
                ["ok"] * 6,
                ["recoverable"] * 6,
            ],
            states(config, failed),
        )
        # the model, which counts both RAID 5 arrays as failed, disagrees:
        self.assertTrue(all_blocks_readable(config, failed))
        self.assertFalse(all_data_readable(config, failed))

    def test_outer_parity_rebuilds_across_inner_arrays(self) -> None:
        """In RAID 5 over three RAID 0 pairs with a and d failed, each block on a or d is rebuilt from the other two
        pairs, the parity ``P[...]`` of the outer level among them; the model counts two pairs as failed.

        Would fail if a parity block of the outer level in a nested array were not rebuilt, or the outer RAID 5 did
        not rebuild a block from the blocks of the other members.
        """
        config: Configuration = configuration(Structure(5, 3, 0, 2))
        failed: set[int] = {0, 3}
        # the blocks on a and d, outer parity among them, are all orange:
        cells = disk_blocks(config, failed)
        self.assertIn("P[8^9]", [cell.block.text for cell in cells[0]])
        for slot in (0, 3):
            self.assertEqual(["recoverable"] * 6, [cell.state for cell in cells[slot]])
        # every block can be read, but the model says that data is lost:
        self.assertTrue(all_blocks_readable(config, failed))
        self.assertFalse(all_data_readable(config, failed))

    def test_a_rebuilt_block_helps_to_rebuild_another(self) -> None:
        """In RAID 5+5 over three arrays of three disks, a block rebuilt at one level helps to rebuild another one.
        With the first inner array failed as a whole (a, b and c), the outer level rebuilds its blocks from the other
        two arrays, and from these the inner parity on its disks in turn, e.g. ``p[0^P[2^3]]`` on c from 0 and
        ``P[2^3]``. With a, c, e and f failed, every block can be rebuilt as well, although the model says that data
        is lost. One pass over the rows is not enough, as the rebuilds form a chain: a block that the outer level
        rebuilds completes a row of an inner array, whose rebuilt block in turn completes another row of the outer
        level, and so on.

        Would fail if the rows were gone through only once, so that a row whose missing blocks were rebuilt only
        later stayed incomplete.
        """
        config: Configuration = configuration(Structure(5, 3, 5, 3))
        # the first inner array failed: every block on a, b and c is orange, and the model agrees:
        self.assertEqual(
            [["recoverable"] * 9] * 3 + [["ok"] * 9] * 6, states(config, {0, 1, 2})
        )
        self.assertTrue(all_data_readable(config, {0, 1, 2}))
        # a, c, e and f failed: every block on them is orange, and the model disagrees:
        failed: set[int] = {0, 2, 4, 5}
        self.assertEqual(
            [["recoverable" if slot in failed else "ok"] * 9 for slot in range(9)],
            states(config, failed),
        )
        self.assertFalse(all_data_readable(config, failed))

    def test_rebuilding_row_by_row_has_a_limit(self) -> None:
        """In RAID 5+5 over three arrays of three disks with a, c, d, e, g and h failed, every RAID 5 row in the first
        row of the disks that misses a block misses at least two, so block 0 on a stays red, although it is the XOR
        of ``P[2^3]``, ``p[1^2]`` and ``p[P[0^1]^3]`` on the working disks b, f and i: blocks are rebuilt row by row,
        as RAID controllers do, not computed from several rows together.

        Would fail if the rebuild changed, e.g. to an exact computation from all rows, while the docstring of
        readable_blocks still describes this limit with this example and the notebook still states it.
        """
        cells = disk_blocks(configuration(Structure(5, 3, 5, 3)), {0, 2, 3, 4, 6, 7})
        # block 0 on a is red:
        self.assertEqual(("0", "lost"), (cells[0][0].block.text, cells[0][0].state))
        # the three blocks whose XOR it is lie in row 0 of b, f and i:
        self.assertEqual(
            ["P[2^3]", "p[1^2]", "p[P[0^1]^3]"],
            [cells[slot][0].block.text for slot in (1, 5, 8)],
        )

    def test_red_where_neither_a_copy_nor_a_row_helps(self) -> None:
        """Blocks stay red where neither a copy nor a RAID 5 row brings them back. In RAID 5 over three RAID 0 pairs
        with a and c failed, two pairs lost their first disk, so every row of the outer level with a block there
        misses two blocks. In RAID 5+1 with a, b, d and e failed, both RAID 5 arrays lost the disks at the same
        positions, so all copies of the blocks on them are gone, the inner parity among them.

        Would fail if a row with two missing blocks were rebuilt, or a block counted as readable because an equal
        block lay on another failed disk.
        """
        # RAID 5 over three RAID 0 pairs with a and c failed:
        pairs: Configuration = configuration(Structure(5, 3, 0, 2))
        self.assertEqual(
            [["lost"] * 6, ["ok"] * 6, ["lost"] * 6] + [["ok"] * 6] * 3,
            states(pairs, {0, 2}),
        )
        self.assertFalse(all_blocks_readable(pairs, {0, 2}))
        # RAID 5+1 with a, b, d and e failed:
        lost, ok = ["lost"] * 6, ["ok"] * 6
        self.assertEqual(
            [lost, lost, ok, lost, lost, ok],
            states(preset("RAID 5+1"), {0, 1, 3, 4}),
        )

    def test_without_parity_a_block_needs_a_copy_on_a_working_disk(self) -> None:
        """For every structure of RAID 0 and RAID 1 with up to 6 disks, every block has one copy per member of each
        RAID 1 level; and for every set of failed disks, a block on a failed disk is orange exactly if one of the
        working disks holds a copy of it.

        Would fail if a mirror kept too few or too many copies, a copy were looked for on the wrong disk, or a block
        were counted as rebuilt where no parity exists.
        """
        for structure in structures_up_to(6):
            if 5 in (structure.outer_level, structure.inner_level):
                continue
            config: Configuration = configuration(structure)
            columns: list[list[str]] = texts(config, block_rows(config))
            # one copy per member of each RAID 1 level:
            copies: int = (
                structure.outer_members if structure.outer_level == 1 else 1
            ) * (structure.inner_members if structure.inner_level == 1 else 1)
            with self.subTest(structure=structure):
                self.assertEqual(
                    {copies},
                    set(
                        Counter(text for column in columns for text in column).values()
                    ),
                )
            for failed in every_subset(config.disks):
                with self.subTest(structure=structure, failed=failed):
                    # the blocks the working disks hold:
                    on_working_disks: set[str] = {
                        text
                        for slot, column in enumerate(columns)
                        if slot not in failed
                        for text in column
                    }
                    # orange where a working disk holds a copy, red elsewhere on the failed disks:
                    expected: list[list[BlockState]] = [
                        [
                            (
                                "ok"
                                if slot not in failed
                                else (
                                    "recoverable"
                                    if text in on_working_disks
                                    else "lost"
                                )
                            )
                            for text in column
                        ]
                        for slot, column in enumerate(columns)
                    ]
                    self.assertEqual(expected, states(config, failed))

    def test_survives_implies_every_block_readable(self) -> None:
        """For every single-level and two-level structure with up to 6 disks, RAID 5+5 over three arrays of three
        disks, and every set of failed disks: where survives() says all data can be read, every block can be read on
        its own. Both answers agree exactly where no array member can lose some of its blocks while another member
        could stand in for them: in a single-level array, whose members are disks; in an array over inner mirrors,
        which lose either nothing or everything; and in an array under an outer stripe, whose members cannot stand in
        for each other.

        Would fail if the check block by block missed a copy or a rebuild that survives() counts, or if it differed
        from survives() in one of the arrays where both agree exactly.
        """
        for structure in [*structures_up_to(6), Structure(5, 3, 5, 3)]:
            config: Configuration = configuration(structure)
            for failed in every_subset(config.disks):
                with self.subTest(structure=structure, failed=failed):
                    survives: bool = all_data_readable(config, failed)
                    blocks: bool = all_blocks_readable(config, failed)
                    # where survives() says yes, every block is readable:
                    if survives:
                        self.assertTrue(blocks)
                    # in a single-level array, over inner mirrors and under an outer stripe, both agree:
                    if structure.inner_level in (None, 1) or structure.outer_level == 0:
                        self.assertEqual(survives, blocks)
