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

"""Model of the RAID playground: one- or two-level RAID arrays, their numbers, failures and blocks.

The playground builds one- or two-level arrays of slow and fast disks, computes what they cost and which failures they
survive, and shows which blocks lie on which disk.

The numbers come from the cost model in :mod:`system.storage.RAID.cost_model`, the placement of the blocks from
:mod:`system.storage.RAID.block_assignment`; this module builds the arrays, composes the placement of two levels and
collects the results.
"""

from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, NamedTuple

from system.storage.RAID.block_assignment import AssignedCell, assignment_cells
from system.storage.RAID.cost_model import (
    RAID_0,
    RAID_1,
    RAID_5,
    Device,
    FailureCount,
    SubSystem,
    SubSystemArray,
    count_survived_failures,
)

# the RAID levels a level of a configuration can have:
Level = Literal[0, 1, 5]
# the two device types every disk is one of:
DeviceKind = Literal["slow", "fast"]
# the state of a block in the column of its disk: on a working disk ("ok"), or on a failed disk and its data can still
# be read or rebuilt ("recoverable") or not ("lost"):
BlockState = Literal["ok", "recoverable", "lost"]

LEVELS: tuple[Level, ...] = (0, 1, 5)
DEVICE_KINDS: tuple[DeviceKind, ...] = ("slow", "fast")
# the fewest members an array of each level has: RAID 5 needs two data blocks and a parity block per row:
MIN_MEMBERS: dict[Level, int] = {0: 2, 1: 2, 5: 3}
# the most members an array of any level has:
MAX_MEMBERS: int = 6
# the failure counts are computed for this many failed disks at the same time:
FAILED_DISK_COUNTS: tuple[int, ...] = (1, 2, 3)
# the disk columns show at least and at most this many rows of blocks (see block_rows):
MIN_BLOCK_ROWS: int = 4
MAX_BLOCK_ROWS: int = 12

# the array class of each level in the cost model:
ARRAY_CLASSES: dict[Level, type[SubSystemArray]] = {0: RAID_0, 1: RAID_1, 5: RAID_5}


@dataclass(frozen=True)
class DeviceType:
    """The performance values of one kind of disk."""

    # sequential read and write throughput in MB/s:
    sequential_read: int
    sequential_write: int
    # random read and write I/O operations per second:
    read_IOPS: int
    write_IOPS: int

    def device(self) -> Device:
        """Returns a new Device with these values.

        @return: the device; every call returns a distinct object, so that each disk fails on its own
        """
        return Device(
            self.sequential_read,
            self.sequential_write,
            self.read_IOPS,
            self.write_IOPS,
        )


# the device types the playground starts with, those of the RAID tests (system/tests/storage/RAID/test_RAID.py): a
# fast disk is twice as fast as a slow one in all four values, and the four values of each differ, so that a formula
# that mixes them up shows:
DEFAULT_DEVICE_TYPES: dict[DeviceKind, DeviceType] = {
    "slow": DeviceType(100, 50, 1000, 400),
    "fast": DeviceType(200, 100, 2000, 800),
}
# the kind of a disk that has not been marked slow or fast:
DEFAULT_KIND: DeviceKind = "fast"


class Structure(NamedTuple):
    """The levels and member counts of a configuration, without the kinds of its disks.

    ``inner_level`` None means a single-level array; its ``inner_members`` is then 1, every disk being a member of
    the outer array.
    """

    outer_level: Level
    outer_members: int
    inner_level: Level | None
    inner_members: int


@dataclass(frozen=True)
class Configuration:
    """A RAID array of one or two levels and the kind of each of its disks.

    The outer level stripes or mirrors over ``outer_members`` inner arrays, each of level ``inner_level`` over
    ``inner_members`` disks; without an inner level, the outer level is over ``outer_members`` disks. Disk slots are
    numbered inner array by inner array: slot i is in inner array ``i // inner_members`` at position
    ``i % inner_members``.
    """

    outer_level: Level
    outer_members: int
    inner_level: Level | None
    inner_members: int
    # the kind of every disk, by slot:
    kinds: tuple[DeviceKind, ...]

    def __post_init__(self) -> None:
        """Sets ``inner_members`` to 1 without an inner level and checks the levels, the member counts and the kinds.

        @raise ValueError: if a level is not one of :data:`LEVELS` or a member count does not fit its level (see
            :func:`check_members`), if a kind is not one of :data:`DEVICE_KINDS`, or if there is not one kind per
            disk
        """
        # a frozen dataclass forbids setting a field, so the field is set the way the dataclass's own __init__ sets
        # it, past the check of the frozen class:
        if self.inner_level is None:
            object.__setattr__(self, "inner_members", 1)
        else:
            check_members(self.inner_level, self.inner_members)
        check_members(self.outer_level, self.outer_members)
        # one known kind per disk:
        unknown: list[str] = [kind for kind in self.kinds if kind not in DEVICE_KINDS]
        if unknown:
            raise ValueError(
                f"Every kind must be one of {DEVICE_KINDS}, got {unknown}."
            )
        if len(self.kinds) != self.disks:
            raise ValueError(
                f"{self.disks} disks need {self.disks} kinds, got {len(self.kinds)}."
            )

    @property
    def disks(self) -> int:
        """The number of disks."""
        return self.outer_members * self.inner_members

    @property
    def structure(self) -> Structure:
        """The levels and member counts, without the kinds."""
        return Structure(
            self.outer_level, self.outer_members, self.inner_level, self.inner_members
        )

    @property
    def name(self) -> str:
        """The usual name, lower level first, e.g. ``RAID 5`` or ``RAID 0+1`` for RAID 1 over RAID 0 arrays."""
        if self.inner_level is None:
            return f"RAID {self.outer_level}"
        return f"RAID {self.inner_level}+{self.outer_level}"


def check_members(level: Level, members: int) -> None:
    """Checks that an array of ``level`` may have ``members`` members.

    @param level: the RAID level of the array
    @param members: the number of its members
    @raise ValueError: if ``level`` is not one of :data:`LEVELS`, or if ``members`` is below the
        :data:`MIN_MEMBERS` of the level or above :data:`MAX_MEMBERS`
    """
    if level not in LEVELS:
        raise ValueError(f"The level must be one of {LEVELS}, got {level}.")
    if not MIN_MEMBERS[level] <= members <= MAX_MEMBERS:
        raise ValueError(
            f"RAID {level} has {MIN_MEMBERS[level]} to {MAX_MEMBERS} members, got {members}."
        )


def configuration(
    structure: Structure, kinds: tuple[DeviceKind, ...] | None = None
) -> Configuration:
    """Returns the configuration of a structure with the given kinds of disks.

    @param structure: the levels and member counts
    @param kinds: the kind of every disk, by slot; by default every disk is of :data:`DEFAULT_KIND`
    @return: the configuration
    @raise ValueError: as :class:`Configuration` does for invalid levels, member counts or kinds
    """
    outer_level, outer_members, inner_level, inner_members = structure
    disks: int = outer_members * (inner_members if inner_level is not None else 1)
    return Configuration(
        outer_level,
        outer_members,
        inner_level,
        inner_members,
        kinds if kinds is not None else (DEFAULT_KIND,) * disks,
    )


# the presets, named lower level first: "0+1" is RAID 1 over RAID 0 stripes, "1+0" RAID 0 over RAID 1 pairs:
PRESETS: dict[str, Structure] = {
    "RAID 0": Structure(0, 4, None, 1),
    "RAID 1": Structure(1, 2, None, 1),
    "RAID 5": Structure(5, 4, None, 1),
    "RAID 0+1": Structure(1, 2, 0, 2),
    "RAID 1+0": Structure(0, 2, 1, 2),
    "RAID 5+0": Structure(0, 2, 5, 3),
    "RAID 5+1": Structure(1, 2, 5, 3),
}


def build(
    config: Configuration, device_types: Mapping[DeviceKind, DeviceType]
) -> SubSystem:
    """Builds the cost model's array of a configuration from a distinct Device per slot.

    @param config: the configuration
    @param device_types: the performance values of each kind of disk
    @return: the array; ``list(build(...).devices())[i]`` is the device in slot i
    """
    devices: list[Device] = [device_types[kind].device() for kind in config.kinds]
    outer_class: type[SubSystemArray] = ARRAY_CLASSES[config.outer_level]
    if config.inner_level is None:
        return outer_class(devices)
    # inner array j holds the slots j * inner_members up to (j + 1) * inner_members - 1:
    inner_class: type[SubSystemArray] = ARRAY_CLASSES[config.inner_level]
    size: int = config.inner_members
    return outer_class(
        [
            inner_class(devices[start : start + size])
            for start in range(0, config.disks, size)
        ]
    )


def all_data_readable(config: Configuration, failed: Set[int]) -> bool:
    """Returns whether all data of a configuration can still be read, as :meth:`SubSystem.survives` decides it: an
    array member that lost any data counts as failed as a whole.

    @param config: the configuration
    @param failed: the slots of the failed disks
    @return: True if all data can still be read
    """
    # the device types do not matter for failures:
    array: SubSystem = build(config, DEFAULT_DEVICE_TYPES)
    devices: list[Device] = list(array.devices())
    return array.survives({devices[slot] for slot in failed})


@lru_cache(maxsize=None)
def failure_counts(structure: Structure) -> tuple[FailureCount | None, ...]:
    """Returns how many combinations of 1, 2 and 3 failed disks (see :data:`FAILED_DISK_COUNTS`) an array of a
    structure survives.

    Cached per structure, as the counts depend neither on the kinds of the disks nor on the device types.

    @param structure: the levels and member counts
    @return: one count per entry of :data:`FAILED_DISK_COUNTS`, None where the array has fewer disks
    """
    array: SubSystem = build(configuration(structure), DEFAULT_DEVICE_TYPES)
    disks: int = len(list(array.devices()))
    return tuple(
        count_survived_failures(array, failed) if failed <= disks else None
        for failed in FAILED_DISK_COUNTS
    )


@dataclass(frozen=True)
class Metrics:
    """What a configuration costs, how fast it is and which failures it survives."""

    # the raw capacity divided by the usable capacity, e.g. 2.0 for a mirror of two disks:
    storage_blow_up: float
    # the usable share of the raw capacity, 1 / storage_blow_up:
    usable_share: float
    # sequential read and write throughput in MB/s:
    sequential_read: int
    sequential_write: int
    # random read and write I/O operations per second:
    read_IOPS: int
    write_IOPS: int
    # how many combinations of 1, 2 and 3 failed disks the array survives, None where it has fewer disks:
    failure_counts: tuple[FailureCount | None, ...]


def metrics(
    config: Configuration, device_types: Mapping[DeviceKind, DeviceType]
) -> Metrics:
    """Returns the metrics of a configuration; the performance numbers assume that every disk works.

    @param config: the configuration
    @param device_types: the performance values of each kind of disk
    @return: the metrics
    """
    array: SubSystem = build(config, device_types)
    blow_up: float = array.get_storage_blow_up()
    return Metrics(
        storage_blow_up=blow_up,
        usable_share=1 / blow_up,
        sequential_read=array.get_sequential_read_performance(),
        sequential_write=array.get_sequential_write_performance(),
        read_IOPS=array.get_read_IO_performance(),
        write_IOPS=array.get_write_IO_performance(),
        failure_counts=failure_counts(config.structure),
    )


@dataclass(frozen=True)
class Block:
    """What a block on a disk holds: a logical data block, or the parity of other blocks.

    The parity of the outer level, or of a single-level array, is written ``P[0^1]``: the XOR ("^") of the logical
    blocks 0 and 1. The parity of an inner RAID 5 array is written ``p[...]`` and lists the other blocks of its row in
    that inner array as they are written in their own cells: logical blocks, as in ``p[0^2]`` in RAID 5+0, or parity
    of the outer level, as in ``p[0^P[2^3]]`` in RAID 5+5.
    """

    # the logical block ID of a data block, None for a parity block:
    logical_block_ID: int | None
    # the blocks a parity block is computed from, empty for a data block:
    covered: tuple[Block, ...] = ()
    # whether a parity block is that of an inner RAID 5 array rather than that of the outer level:
    inner_parity: bool = False

    @property
    def text(self) -> str:
        """The block as its cell shows it: a data block as its logical block ID, a parity block as ``P[...]`` or
        ``p[...]`` (see the class)."""
        if self.logical_block_ID is not None:
            return str(self.logical_block_ID)
        letter: str = "p" if self.inner_parity else "P"
        return f"{letter}[{'^'.join(block.text for block in self.covered)}]"


@dataclass(frozen=True)
class BlockCell:
    """A block in the column of a disk, and its state."""

    block: Block
    # "ok" on a working disk; on a failed disk "recoverable" if what the block holds can still be read or rebuilt
    # (see readable_blocks), else "lost":
    state: BlockState


def block_rows(config: Configuration) -> int:
    """Returns how many rows of blocks the disk columns show.

    @param config: the configuration
    @return: as many rows as the array has disks, at least :data:`MIN_BLOCK_ROWS` and at most
        :data:`MAX_BLOCK_ROWS`; so the parity of every RAID 5 level goes round all its members at least once (a RAID 5
        has at most six members), while a large nested array does not show dozens of rows
    """
    return min(MAX_BLOCK_ROWS, max(MIN_BLOCK_ROWS, config.disks))


def outer_block(cell: AssignedCell) -> Block:
    """Returns what a cell of the outer level, or of a single-level array, holds.

    @param cell: the cell, from :func:`assignment_cells`
    @return: its data block, or its parity over the logical blocks it covers
    """
    if cell.is_parity:
        return Block(None, tuple(Block(ID) for ID in cell.logical_block_IDs))
    return Block(cell.logical_block_IDs[0])


def layout(config: Configuration, rows: int) -> list[list[Block]]:
    """Returns the first blocks of every disk of a configuration.

    The outer level places every logical block, and its parity, on internal blocks of its members (see
    :meth:`system.storage.RAID.block_assignment.RAID_Level.logical_id_to_physical_positions`). Without an inner level,
    its members are the disks. Otherwise, every member is an inner array, which places its internal blocks on its disks
    in the same way and adds parity of its own; a disk thus holds what the outer level put into the internal block
    that the inner array put on that disk.

    @param config: the configuration
    @param rows: how many blocks of every disk, from the first
    @return: the blocks by slot, each list from the first row to the last
    """
    # without an inner level, the outer level places its blocks on the disks:
    if config.inner_level is None:
        grid: list[list[AssignedCell]] = assignment_cells(
            rows, config.outer_members, config.outer_level
        )
        return [
            [outer_block(grid[row][slot]) for row in range(rows)]
            for slot in range(config.outer_members)
        ]
    # every inner array places its internal blocks on its disks alike, and the outer level fills as many internal
    # blocks of every member as the inner arrays place in these rows:
    inner_grid: list[list[AssignedCell]] = assignment_cells(
        rows, config.inner_members, config.inner_level
    )
    internal_blocks: int = 1 + max(
        ID
        for row_cells in inner_grid
        for cell in row_cells
        for ID in cell.logical_block_IDs
    )
    outer_grid: list[list[AssignedCell]] = assignment_cells(
        internal_blocks, config.outer_members, config.outer_level
    )
    # the disk at position d of member j holds, row by row, what the outer level put into the internal block of
    # member j that the inner level put there, or the inner parity over such internal blocks:
    columns: list[list[Block]] = []
    for member in range(config.outer_members):
        for disk in range(config.inner_members):
            column: list[Block] = []
            for row in range(rows):
                cell: AssignedCell = inner_grid[row][disk]
                held: tuple[Block, ...] = tuple(
                    outer_block(outer_grid[ID][member]) for ID in cell.logical_block_IDs
                )
                column.append(
                    Block(None, held, inner_parity=True) if cell.is_parity else held[0]
                )
            columns.append(column)
    return columns


def readable_blocks(columns: list[list[Block]], failed: Set[int]) -> set[Block]:
    """Returns the blocks of the disks that can still be read or rebuilt when some disks have failed.

    The rules of the RAID levels decide it, at the inner and the outer level alike: a block can be read from any of
    its copies on a working disk (RAID 0 keeps one copy, RAID 1 one per member), and the one block of a RAID 5 row that
    cannot be read is rebuilt as the XOR of the other blocks of its row, the parity among them. A block counts as
    readable however it was obtained, from a copy or rebuilt, so the levels can help each other: in RAID 5+1 with the
    failed disks a, b, d and f, block 1 is read from e, and block 0 is then rebuilt from block 1 and the parity
    ``p[0^1]`` on c, although neither RAID 5 array can rebuild it on its own. This is repeated until no further block
    can be rebuilt.

    Blocks are rebuilt row by row, as RAID controllers do. Only in rare cases of RAID 5 over RAID 5 with many failed
    disks could a block still be computed from several rows together, which this does not try: in RAID 5+5 over three
    arrays of three disks with a, c, d, e, g and h failed, block 0 counts as lost, although it is the XOR of ``P[2^3]``,
    ``p[1^2]`` and ``p[P[0^1]^3]`` on b, f and i.

    Every block is judged on its own, unlike in :func:`all_data_readable`, which counts an array member that lost
    some data as failed as a whole. A block may thus be readable although all_data_readable says that data is lost
    (in RAID 0+1 with the stripes (a, b) and (c, d) and the failed disks a and d, every block is still on b or c);
    where all_data_readable says that all data can be read, every block is readable.

    @param columns: the blocks by slot, from :func:`layout`
    @param failed: the slots of the failed disks
    @return: the blocks, data and parity, that can be read or rebuilt
    """
    # every block on a working disk can be read; equal blocks are copies of each other:
    readable: set[Block] = {
        block
        for slot, column in enumerate(columns)
        if slot not in failed
        for block in column
    }
    # every parity block forms a RAID 5 row with the blocks it is computed from, whose XOR is 0:
    parity_rows: set[frozenset[Block]] = {
        frozenset((block, *block.covered))
        for column in columns
        for block in column
        if block.logical_block_ID is None
    }
    # rebuild the one missing block of a row as the XOR of the others, until no row misses exactly one block:
    rebuilt: bool = True
    while rebuilt:
        rebuilt = False
        for row in parity_rows:
            missing: frozenset[Block] = row - readable
            if len(missing) == 1:
                readable |= missing
                rebuilt = True
    return readable


def disk_blocks(
    config: Configuration, failed: Set[int], rows: int | None = None
) -> list[list[BlockCell]]:
    """Returns the first blocks of every disk of a configuration (see :func:`layout`) with their states.

    @param config: the configuration
    @param failed: the slots of the failed disks
    @param rows: how many blocks of every disk, by default :func:`block_rows`
    @return: the blocks by slot, each list from the first row to the last
    """
    columns: list[list[Block]] = layout(
        config, block_rows(config) if rows is None else rows
    )
    readable: set[Block] = readable_blocks(columns, failed)
    return [
        [
            BlockCell(
                block,
                (
                    "ok"
                    if slot not in failed
                    else "recoverable" if block in readable else "lost"
                ),
            )
            for block in column
        ]
        for slot, column in enumerate(columns)
    ]


def all_blocks_readable(config: Configuration, failed: Set[int]) -> bool:
    """Returns whether every logical data block in the first :func:`block_rows` rows of the disks can still be read
    or rebuilt, block by block (see :func:`readable_blocks`).

    @param config: the configuration
    @param failed: the slots of the failed disks
    @return: True if every one of these blocks can be read or rebuilt
    """
    columns: list[list[Block]] = layout(config, block_rows(config))
    readable: set[Block] = readable_blocks(columns, failed)
    return all(
        block in readable
        for column in columns
        for block in column
        if block.logical_block_ID is not None
    )
