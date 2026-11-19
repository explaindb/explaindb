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

"""RAID reliability and performance cost model for various RAID levels."""

from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence, Set
from enum import Enum
from itertools import combinations
from statistics import mean
from typing import NamedTuple


class ResilienceScenario(Enum):
    """Resilience scenarios for a storage subsystem. This is used to model the resilience of a storage subsystem
    against errors."""

    # any single subsystem may fail, and we can still recover all data:
    ANY_SINGLE_SUBSYSTEM_MAY_FAIL = 1

    # all but one subsystem may fail, and we can still recover all data:
    ALL_BUT_ONE_SUBSYSTEM_MAY_FAIL = 42

    def __str__(self):
        """Render as the bare member name (e.g. ``ANY_SINGLE_SUBSYSTEM_MAY_FAIL``)
        rather than the default ``ResilienceScenario.<name>`` form."""
        return self.name


class SubSystem(ABC):
    """A cost model for an abstract subsystem used to model the performance of storage devices. This can be anything
    from a single chip of an SSD to a whole RAID subsystem. The subsystem has to provide information about its performance
    characteristics.
    """

    def __init__(self):
        pass

    @abstractmethod
    def get_sequential_read_performance(self) -> int:
        """Returns the sequential read performance of the subsystem in MB/s."""

    @abstractmethod
    def get_sequential_write_performance(self) -> int:
        """Returns the sequential write performance of the subsystem in MB/s."""

    @abstractmethod
    def get_read_IO_performance(self) -> int:
        """Returns the read-IOPs (random read I/O operations per second) of the subsystem. Assumes uniform distribution
        of read requests over the data, i.e. every block is equally likely to be read; an array that splits the data
        into equal shares, one per subsystem (as in RAID 0 and RAID 5), thus sends every subsystem the same share of
        the reads."""

    @abstractmethod
    def get_write_IO_performance(self) -> int:
        """Returns the write-IOPs (random write I/O operations per second) of the subsystem. Assumes uniform
        distribution of write requests over the data, i.e. every block is equally likely to be written; an array that
        splits the data into equal shares, one per subsystem (as in RAID 0 and RAID 5), thus sends every subsystem the
        same share of the writes."""

    @abstractmethod
    def get_storage_blow_up(self) -> float:
        """Returns the storage blow-up in terms of the extra storage space introduced by the subsystem. This means,
        if we return 1.1 this means we add 10% more storage space to the original storage space, 1.0 means no extra
        storage space is added. A value below 1.0 means space is saved, e.g. by compression.
        """

    @abstractmethod
    def get_resilience_scenario(
        self,
    ) -> tuple[ResilienceScenario, Iterator[SubSystem] | None] | None:
        """Returns the scenario this SubSystem is resilient against, i.e. this scenario may happen, still
        this subsystem instance can recover all data.

        @return: None if this subsystem is not resilient against any failure, otherwise a tuple of
            0. the resilience scenario and
            1. an iterator over the member subsystems that may fail, or None.
        """

    def get_resilience_scenarios(
        self, rec_depth: int = 0
    ) -> Iterator[
        tuple[int, SubSystem, ResilienceScenario, Iterator[SubSystem] | None]
    ]:
        """Returns an Iterator over the resilience scenarios of this subsystem and, recursively, of all subsystems
        nested in it. A subsystem that is not resilient against any failure contributes no tuple.

        @param rec_depth: The recursion depth of this subsystem, 0 for the outermost subsystem.
        @return: An iterator over tuples, each containing:
            0. the recursion depth of the subsystem,
            1. the subsystem instance,
            2. the resilience scenario for that instance, and
            3. an iterator over the member subsystems that may fail, or None.
        """

        # return the resilience scenario of this subsystem:
        resilience_scenario: (
            tuple[ResilienceScenario, Iterator[SubSystem] | None] | None
        ) = self.get_resilience_scenario()

        if resilience_scenario is not None:
            yield rec_depth, self, *resilience_scenario

    @abstractmethod
    def devices(self) -> Iterator[Device]:
        """Returns the devices at the bottom of this subsystem, from left to right.

        @return: An iterator over the devices of this subsystem in the order of its members.
        """

    @abstractmethod
    def survives(self, failed_devices: Set[Device]) -> bool:
        """Returns whether all data of this subsystem can still be read when exactly the given devices have failed
        and all other devices still work.

        Devices are told apart by identity: two Device objects with the same performance characteristics are two
        different devices. Failed devices that are not part of this subsystem are ignored.

        The model treats an array member that loses any data as failed as a whole, so an array never combines the
        surviving parts of two of its members. This is how a nested array is usually treated, e.g. a RAID 1 built
        over RAID 0 sets: once one device of a RAID 0 set fails, the whole set counts as failed. For example, a
        RAID 0+1 array with the stripes (a, b) and (c, d) counts the failure of a and d as data loss, although
        every block still exists once (in b and c).

        @param failed_devices: The devices that have failed.
        @return: True if all data of this subsystem can still be read, False otherwise.
        """

    def __str__(self):
        """Render as the concrete subsystem's class name."""
        return f"{self.__class__.__name__}"


class SubSystemArray(SubSystem, ABC):
    """A cost model for an abstract subsystem keeping a list of references to nested subsystems."""

    def __init__(self, subsystems: Sequence[SubSystem]):
        """Create the array over the given nested subsystems.

        @param subsystems: The subsystems aggregated by this array.
        """
        super().__init__()
        self.subsystems: Sequence[SubSystem] = subsystems

    def get_resilience_scenarios(
        self, rec_depth: int = 0
    ) -> Iterator[
        tuple[int, SubSystem, ResilienceScenario, Iterator[SubSystem] | None]
    ]:
        """See :meth:`SubSystem.get_resilience_scenarios`.

        Yields the scenario of this array first, then the scenarios of each member subsystem, which is called
        recursively with ``rec_depth + 1``, so the depth grows by one per nesting level.
        """

        # return the resilience scenario of this subsystem:
        yield from super().get_resilience_scenarios(rec_depth=rec_depth)

        # return the resilience scenarios of all children subsystems:
        subsystem: SubSystem
        for subsystem in self.subsystems:
            yield from subsystem.get_resilience_scenarios(rec_depth=rec_depth + 1)

    def devices(self) -> Iterator[Device]:
        """See :meth:`SubSystem.devices`.

        Yields the devices of all member subsystems, member by member in the order of the members.
        """
        subsystem: SubSystem
        for subsystem in self.subsystems:
            yield from subsystem.devices()


class Device(SubSystem):
    """A device in a storage subsystem. This class must provide information about its performance characteristics."""

    def __init__(
        self,
        sequential_read_performance: int,
        sequential_write_performance: int,
        read_IO_performance: int,
        write_IO_performance: int,
        storage_blow_up: float = 1,
    ):
        """Create a device from its measured performance characteristics.

        @param sequential_read_performance: Sequential read throughput in MB/s.
        @param sequential_write_performance: Sequential write throughput in MB/s.
        @param read_IO_performance: Random read I/O operations per second (IOPs).
        @param write_IO_performance: Random write I/O operations per second (IOPs).
        @param storage_blow_up: Storage blow-up factor (1.0 = no overhead, 1.1 =
            10% extra, < 1.0 = space saved, e.g. via compression).
        """
        super().__init__()
        self.sequential_read_performance: int = sequential_read_performance
        self.sequential_write_performance: int = sequential_write_performance
        self.read_IO_performance: int = read_IO_performance
        self.write_IO_performance: int = write_IO_performance
        self.storage_blow_up: float = storage_blow_up

    def get_sequential_read_performance(self) -> int:
        """Returns the sequential read performance of the device in MB/s."""
        return self.sequential_read_performance

    def get_sequential_write_performance(self) -> int:
        """Returns the sequential write performance of the device in MB/s."""
        return self.sequential_write_performance

    def get_read_IO_performance(self) -> int:
        """Returns the read-IOPs (read I/O operations per second) of the device."""
        return self.read_IO_performance

    def get_write_IO_performance(self) -> int:
        """Returns the write-IOPs (write I/O operations per second) of the device."""
        return self.write_IO_performance

    def get_storage_blow_up(self) -> float:
        """See :meth:`SubSystem.get_storage_blow_up`.

        Returns the blow-up factor the device was configured with.
        """
        return self.storage_blow_up

    def get_resilience_scenario(
        self,
    ) -> tuple[ResilienceScenario, Iterator[SubSystem] | None] | None:
        """A device is not resilient against any failure."""
        return None

    def devices(self) -> Iterator[Device]:
        """See :meth:`SubSystem.devices`.

        A device yields only itself.
        """
        yield self

    def survives(self, failed_devices: Set[Device]) -> bool:
        """See :meth:`SubSystem.survives`.

        A device survives unless it is one of the failed devices.
        """
        return self not in failed_devices


class RAID_0(SubSystemArray):
    """RAID 0: Striping without parity"""

    def get_sequential_read_performance(self) -> int:
        """Read performance is the read performance of the slowest subsystem (the minimum) times the number of
        subsystems, since striping reads from all subsystems in parallel."""
        return min(
            subsystem.get_sequential_read_performance() for subsystem in self.subsystems
        ) * len(self.subsystems)

    def get_sequential_write_performance(self) -> int:
        """Write performance is the write performance of the slowest subsystem (the minimum) times the number
        of subsystems, since striping writes to all subsystems in parallel."""
        return min(
            subsystem.get_sequential_write_performance()
            for subsystem in self.subsystems
        ) * len(self.subsystems)

    def get_read_IO_performance(self) -> int:
        """See :meth:`SubSystem.get_read_IO_performance`.

        Read IOPs is the read IOPs of the slowest subsystem (the minimum) times the number of subsystems: striping puts
        the same share of the data on every subsystem, so every subsystem gets the same share of the reads, and a read
        can only go to the subsystem that holds its block. The array is thus saturated as soon as its slowest subsystem
        is, as for sequential reads.
        """
        return min(
            subsystem.get_read_IO_performance() for subsystem in self.subsystems
        ) * len(self.subsystems)

    def get_write_IO_performance(self) -> int:
        """See :meth:`SubSystem.get_write_IO_performance`.

        Write IOPs is the write IOPs of the slowest subsystem (the minimum) times the number of subsystems: striping
        puts the same share of the data on every subsystem, so every subsystem gets the same share of the writes, and a
        write can only go to the subsystem that holds its block. The array is thus saturated as soon as its slowest
        subsystem is, as for sequential writes.
        """
        return min(
            subsystem.get_write_IO_performance() for subsystem in self.subsystems
        ) * len(self.subsystems)

    def get_storage_blow_up(self) -> float:
        """See :meth:`SubSystem.get_storage_blow_up`.

        Returns the mean of the blow-ups of the subsystems, since striping splits the data evenly across them.
        """
        return 1.0 * mean(
            subsystem.get_storage_blow_up() for subsystem in self.subsystems
        )

    def get_resilience_scenario(
        self,
    ) -> tuple[ResilienceScenario, Iterator[SubSystem] | None] | None:
        """RAID 0 is not resilient against any failure."""
        return None

    def survives(self, failed_devices: Set[Device]) -> bool:
        """See :meth:`SubSystem.survives`.

        RAID 0 has no redundancy, so it survives only if all its member subsystems survive.
        """
        return all(subsystem.survives(failed_devices) for subsystem in self.subsystems)


class RAID_1(SubSystemArray):
    """RAID 1: Mirroring"""

    def get_sequential_read_performance(self) -> int:
        """Read performance is the sum of the read performances of all subsystems: RAID 1 mirrors the data, so
        every subsystem holds a full copy and can serve reads in parallel.
        """

        return sum(
            subsystem.get_sequential_read_performance() for subsystem in self.subsystems
        )

    def get_sequential_write_performance(self) -> int:
        """Write performance is the minimum of all write performances of the subsystems, i.e. we have to wait for
        the slowest subsystem. No real speedup here."""
        return min(
            subsystem.get_sequential_write_performance()
            for subsystem in self.subsystems
        )

    def get_read_IO_performance(self) -> int:
        """See :meth:`SubSystem.get_read_IO_performance`.

        Read IOPs is the sum of the read IOPs of all subsystems: every subsystem holds all the data, so a read can go
        to any of them, and faster subsystems can take more reads. (RAID 0 and RAID 5 must send a read to the one
        subsystem that holds its block and are therefore limited by their slowest subsystem.)
        """

        return sum(subsystem.get_read_IO_performance() for subsystem in self.subsystems)

    def get_write_IO_performance(self) -> int:
        """Returns the minimum of the write-IOPs of all subsystems."""
        return min(
            subsystem.get_write_IO_performance() for subsystem in self.subsystems
        )

    def get_storage_blow_up(self) -> float:
        """See :meth:`SubSystem.get_storage_blow_up`.

        Returns the sum of the blow-ups of the subsystems, since every subsystem stores a full copy of the data.
        """
        return sum(subsystem.get_storage_blow_up() for subsystem in self.subsystems)

    def get_resilience_scenario(
        self,
    ) -> tuple[ResilienceScenario, Iterator[SubSystem] | None] | None:
        """RAID 1 is resilient against an error where all but one subsystem fails."""
        return ResilienceScenario.ALL_BUT_ONE_SUBSYSTEM_MAY_FAIL, iter(self.subsystems)

    def survives(self, failed_devices: Set[Device]) -> bool:
        """See :meth:`SubSystem.survives`.

        RAID 1 survives if at least one member subsystem survives, since every member holds a full copy of the
        data.
        """
        return any(subsystem.survives(failed_devices) for subsystem in self.subsystems)


class RAID_5(SubSystemArray):
    """RAID 5: Striping with distributed (round-robin) parity"""

    def __init__(self, subsystems: Sequence[SubSystem]):
        """See :meth:`SubSystemArray.__init__`.

        RAID 5 additionally requires at least three subsystems and asserts this.
        """
        super().__init__(subsystems)
        assert len(subsystems) >= 3, "RAID 5 needs at least 3 subsystems."

    def get_sequential_read_performance(self) -> int:
        """See :meth:`SubSystem.get_sequential_read_performance`.

        Read performance is the read performance of the slowest subsystem (the minimum) times the number of
        subsystems minus 1: when streaming, every subsystem also passes over its parity blocks, so of the n * min
        bandwidth only (n - 1) / n is data, i.e. min * (n - 1). (Random reads never touch the parity and therefore use
        all n subsystems, see :meth:`get_read_IO_performance`.)
        """
        min_read_performance: int = min(
            subsystem.get_sequential_read_performance() for subsystem in self.subsystems
        )
        return min_read_performance * (len(self.subsystems) - 1)

    def get_sequential_write_performance(self) -> int:
        """See :meth:`SubSystem.get_sequential_write_performance`.

        Write performance is the write performance of the slowest subsystem (the minimum) times the number of
        subsystems minus 1: when streaming, every subsystem also writes its share of the parity blocks, so of the
        n * min bandwidth only (n - 1) / n carries data, i.e. min * (n - 1).
        """
        min_write_performance: int = min(
            subsystem.get_sequential_write_performance()
            for subsystem in self.subsystems
        )
        return min_write_performance * (len(self.subsystems) - 1)

    def get_read_IO_performance(self) -> int:
        """See :meth:`SubSystem.get_read_IO_performance`.

        Read IOPs is the read IOPs of the slowest subsystem (the minimum) times the number of subsystems: a random
        read touches only the subsystem that holds the block, and as the parity rotates over all subsystems, every
        subsystem holds the same share of the data and serves the same share of the reads, so the slowest subsystem
        limits the array, as in RAID 0. (RAID 4 would lose one subsystem's worth here, as its dedicated parity
        subsystem never serves reads.)
        """
        return min(
            subsystem.get_read_IO_performance() for subsystem in self.subsystems
        ) * len(self.subsystems)

    def get_write_IO_performance(self) -> int:
        """See :meth:`SubSystem.get_write_IO_performance`.

        Assumes that every write is a small write of a single block, done as a read-modify-write: read the old data
        block and the old parity block, then write the new data block and the new parity block. As the parity rotates
        and the blocks are chosen uniformly at random, every subsystem holds the data block of 1 / n of the small
        writes and the parity block of another 1 / n, and each costs it one read and one write: subsystem i with read
        IOPs R_i and write IOPs W_i is busy (2 / R_i + 2 / W_i) / n seconds per small write on average. The array is
        saturated as soon as its busiest subsystem is, so write IOPs is
        round(min over all i of n / (2 / R_i + 2 / W_i)). With R_i = W_i = W for all i this is the textbook n * W / 4.
        If a subsystem has 0 read or 0 write IOPs, write IOPs is 0.
        """
        # R_i and W_i, the read and write IOPs of every subsystem i (asked once, as a nested array computes them anew
        # on every call):
        read_IOPs: list[int] = [
            subsystem.get_read_IO_performance() for subsystem in self.subsystems
        ]
        write_IOPs: list[int] = [
            subsystem.get_write_IO_performance() for subsystem in self.subsystems
        ]

        # a subsystem that cannot read or cannot write serves no read-modify-write, so the array serves none:
        if 0 in read_IOPs or 0 in write_IOPs:
            return 0

        # subsystem i alone keeps up with n / (2 / R_i + 2 / W_i) small writes per second; the busiest subsystem, i.e.
        # the one with the fewest, limits the array:
        n: int = len(self.subsystems)
        return round(
            min(
                n / (2 / subsystem_read_IOPs + 2 / subsystem_write_IOPs)
                for subsystem_read_IOPs, subsystem_write_IOPs in zip(
                    read_IOPs, write_IOPs
                )
            )
        )

    def get_storage_blow_up(self) -> float:
        """See :meth:`SubSystem.get_storage_blow_up`.

        Returns the mean of the blow-ups of the subsystems times n / (n - 1) for n subsystems, since one
        subsystem's worth of space holds parity.
        """
        mean_storage_blow_up: float = mean(
            subsystem.get_storage_blow_up() for subsystem in self.subsystems
        )

        return mean_storage_blow_up * len(self.subsystems) / (len(self.subsystems) - 1)

    def get_resilience_scenario(
        self,
    ) -> tuple[ResilienceScenario, Iterator[SubSystem] | None] | None:
        """RAID 5 is resilient against a single subsystem failure."""
        return ResilienceScenario.ANY_SINGLE_SUBSYSTEM_MAY_FAIL, iter(self.subsystems)

    def survives(self, failed_devices: Set[Device]) -> bool:
        """See :meth:`SubSystem.survives`.

        RAID 5 survives if at most one member subsystem does not survive, since the parity can rebuild the data
        of one lost member.
        """
        lost_members: int = sum(
            1 for subsystem in self.subsystems if not subsystem.survives(failed_devices)
        )
        return lost_members <= 1


class FailureCount(NamedTuple):
    """Of all ways of losing k devices, how many a subsystem survives (``survived``) and how many there are
    (``total``), see :func:`count_survived_failures`."""

    survived: int
    total: int


def count_survived_failures(
    subsystem: SubSystem, number_of_failed_devices: int
) -> FailureCount:
    """Counts in how many of all possible ways of losing k of its devices the subsystem can still read all its data.

    A subsystem with n devices can lose k of them in C(n, k) different ways; C(n, k), read "n choose k", is
    n! / (k! (n - k)!). For example, the 4 devices a, b, c, d can lose 2 of them in C(4, 2) = 6 ways: {a, b},
    {a, c}, {a, d}, {b, c}, {b, d} and {c, d}. This function tries each way and asks :meth:`SubSystem.survives`
    whether all data can still be read with exactly these devices failed, so the result follows the assumptions
    stated there. Which devices fail matters, as it decides which arrays lose members: RAID 1+0 over the mirrored
    pairs (a, b) and (c, d) survives every way except {a, b} and {c, d}, i.e. 4 of 6; RAID 0+1 over the stripes
    (a, b) and (c, d) survives only {a, b} and {c, d}, i.e. 2 of 6. As every way is tried, the run time grows with
    C(n, k).

    @param subsystem: The subsystem whose device failures are counted.
    @param number_of_failed_devices: k, how many devices fail at the same time.
    @return: The number of ways the subsystem survives (``survived``) and the number of all ways (``total``). For
        0 failed devices this is FailureCount(1, 1): the single way without any failure, which every subsystem
        survives.
    @raise ValueError: If the subsystem contains the same Device object more than once, e.g. because an array
        was built with ``[device] * n`` or the same inner array was used as several members; if
        number_of_failed_devices is negative or larger than the number of devices of the subsystem.
    """

    # check the input: every device is a distinct object, and the number of failed devices fits:
    devices: list[Device] = list(subsystem.devices())
    if len(set(devices)) != len(devices):
        raise ValueError(
            "The subsystem contains the same Device object more than once; build every array from distinct "
            "Device objects, not with [device] * n or by using the same inner array as several members."
        )
    if not 0 <= number_of_failed_devices <= len(devices):
        raise ValueError(
            f"number_of_failed_devices must be between 0 and the number of devices ({len(devices)}), "
            f"got {number_of_failed_devices}."
        )

    # try every combination of failed devices and count the ones the subsystem survives:
    survived: int = 0
    tried: int = 0
    failed_devices: tuple[Device, ...]
    for failed_devices in combinations(devices, number_of_failed_devices):
        tried += 1
        if subsystem.survives(set(failed_devices)):
            survived += 1
    return FailureCount(survived, tried)
