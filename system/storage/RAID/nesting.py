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

"""Nested RAID 0 arrays built from a factorisation of the number of devices, for experiments with the cost model."""

from collections.abc import Callable, Iterator, Sequence

from system.storage.RAID.cost_model import RAID_0, SubSystem, SubSystemArray


def factorisations(k: int) -> Iterator[list[int]]:
    """Yields every factorisation of ``k`` into factors >= 2 (order matters),
    excluding the trivial single-factor ``[k]``.

    @param k: the number to factorise, at least 1.
    @return: an iterator over the factorisations, each a list of factors whose product is ``k``.
    """
    assert isinstance(k, int) and k >= 1
    # every proper divisor can be the first factor:
    for divisor in range(2, k):
        quotient, remainder = divmod(k, divisor)
        if remainder != 0 or quotient < 2:
            continue
        # the remaining factors are a factorisation of the quotient; the recursive call leaves out the single
        # factor [quotient], so that case is yielded on its own:
        for rest in factorisations(quotient):
            yield [divisor] + rest
        yield [divisor, quotient]


def build_nested_raid_0(
    config: Sequence[int], make_device: Callable[[], SubSystem]
) -> RAID_0:
    """Builds a RAID 0 nested by the factors in ``config``, outermost level first.

    Level ``i`` has ``config[i]`` members. Every member of the innermost level is a new device from
    ``make_device``; every member of any other level is a separate array built from the remaining factors. The
    result therefore contains the product of all factors as devices, e.g. ``[4, 8]`` builds a RAID 0 of four
    RAID 0 arrays with eight devices each, 32 devices in all.

    @param config: the number of members per level, outermost first.
    @param make_device: called once per device to create it.
    @return: the outermost RAID 0 array.
    @raise ValueError: if ``config`` is empty or contains a factor below 1.
    """
    # a nesting needs at least one level, and every level at least one member:
    if len(config) == 0 or any(factor < 1 for factor in config):
        raise ValueError(
            f"config must be a non-empty list of factors of at least 1, got {list(config)}"
        )

    # the innermost level stripes over devices:
    if len(config) == 1:
        return RAID_0([make_device() for _ in range(config[0])])

    # every member of an outer level is its own array, nested by the remaining factors:
    return RAID_0(
        [build_nested_raid_0(config[1:], make_device) for _ in range(config[0])]
    )


def count_devices(subsystem: SubSystem) -> int:
    """Counts the devices at the bottom of a subsystem, however deeply it is nested.

    @param subsystem: a device or an array of subsystems.
    @return: 1 for a subsystem that is not an array, else the sum over all members.
    """
    # an array has the devices of all its members; anything else is a single device:
    if isinstance(subsystem, SubSystemArray):
        return sum(count_devices(member) for member in subsystem.subsystems)
    return 1


def arrangements_of_mixed_devices(
    make_slow_device: Callable[[], SubSystem],
    make_fast_device: Callable[[], SubSystem],
) -> dict[str, RAID_0]:
    """Builds three RAID 0 arrangements of the same four slow and two fast devices.

    - ``"flat"``: one RAID 0 over all six devices.
    - ``"grouped by speed"``: a RAID 0 of two arrays, one RAID 0 of the four slow devices and one RAID 0 of the
      two fast devices.
    - ``"mixed groups"``: a RAID 0 of two arrays, one RAID 0 of three slow devices and one fast device and one
      RAID 0 of one slow and one fast device.

    @param make_slow_device: called once per slow device to create it.
    @param make_fast_device: called once per fast device to create it.
    @return: the three arrangements by name, in the order listed above.
    """
    # all six devices in a single stripe:
    flat: RAID_0 = RAID_0(
        [make_slow_device() for _ in range(4)] + [make_fast_device() for _ in range(2)]
    )

    # the slow devices in one array, the fast devices in the other:
    grouped_by_speed: RAID_0 = RAID_0(
        [
            RAID_0([make_slow_device() for _ in range(4)]),
            RAID_0([make_fast_device() for _ in range(2)]),
        ]
    )

    # both arrays mix slow and fast devices:
    mixed_groups: RAID_0 = RAID_0(
        [
            RAID_0([make_slow_device() for _ in range(3)] + [make_fast_device()]),
            RAID_0([make_slow_device(), make_fast_device()]),
        ]
    )
    return {
        "flat": flat,
        "grouped by speed": grouped_by_speed,
        "mixed groups": mixed_groups,
    }
