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
from collections.abc import Sequence
from enum import Enum
from statistics import mean
from typing import Iterator


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
        of read requests to the different subsystems."""

    @abstractmethod
    def get_write_IO_performance(self) -> int:
        """Returns the write-IOPs (random write I/O operations per second) of the subsystem. Assumes uniform
        distribution of write requests to the different subsystems."""

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
        """Read IOPs is the sum of all read IOPs of the subsystems. Assumes uniform distribution of read requests to the
        different subsystems."""
        return sum(subsystem.get_read_IO_performance() for subsystem in self.subsystems)

    def get_write_IO_performance(self) -> int:
        """Write IOPs is the sum of all write IOPs of the subsystems. Assumes uniform distribution of write requests to
        the different subsystems."""
        return sum(
            subsystem.get_write_IO_performance() for subsystem in self.subsystems
        )

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
        """Returns the sum of the read IOPs of all subsystems."""

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


class RAID_5(SubSystemArray):
    """RAID 5: Striping with distributed (round-robin) parity"""

    def __init__(self, subsystems: Sequence[SubSystem]):
        """See :meth:`SubSystemArray.__init__`.

        RAID 5 additionally requires at least three subsystems and asserts this.
        """
        super().__init__(subsystems)
        assert len(subsystems) >= 3, "RAID 5 needs at least 3 subsystems."

    def get_sequential_read_performance(self) -> int:
        """Read performance is the read performance of the slowest subsystem (the minimum) times the number of
        subsystems minus 1 (one subsystem's worth of throughput is spent on parity)."""
        min_read_performance: int = min(
            subsystem.get_sequential_read_performance() for subsystem in self.subsystems
        )
        return min_read_performance * (len(self.subsystems) - 1)

    def get_sequential_write_performance(self) -> int:
        """Write performance is the write performance of the slowest subsystem (the minimum) times the number
        of subsystems minus 1 (one subsystem's worth of throughput is spent on parity).
        """
        min_write_performance: int = min(
            subsystem.get_sequential_write_performance()
            for subsystem in self.subsystems
        )
        return min_write_performance * (len(self.subsystems) - 1)

    def get_read_IO_performance(self) -> int:
        """Read IOPs is the average read IOPs of the subsystems times (the number of subsystems minus 1)."""
        mean_read_IOPs: int = int(
            round(
                mean(
                    subsystem.get_read_IO_performance() for subsystem in self.subsystems
                ),
                0,
            )
        )

        return mean_read_IOPs * (len(self.subsystems) - 1)

    def get_write_IO_performance(self) -> int:
        """Write IOPs is the average write IOPs of the subsystems times (the number of subsystems minus 1)."""
        mean_write_IOPs: int = int(
            round(
                mean(
                    subsystem.get_write_IO_performance()
                    for subsystem in self.subsystems
                ),
                0,
            )
        )

        return mean_write_IOPs * (len(self.subsystems) - 1)

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
