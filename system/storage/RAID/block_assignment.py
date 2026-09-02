"""RAID block-assignment strategies (RAID 0/1/4/5) mapping logical to physical block positions."""

from abc import abstractmethod, ABC
from collections import defaultdict

from attr import dataclass


@dataclass
class PhysicalBlockPosition:
    """Data class to store the physical position of a block in the disk subsystem.
    Note that (disk_ID, internal_block_ID) is a unique identifier for a block in the disk subsystem.
    """

    # disk ID where to find this logical block
    disk_ID: int

    # internal block ID on that disk
    internal_block_ID: int

    # flag indicating if the block is a parity block
    is_parity: bool


class RAID_Level(ABC):
    """Abstract base for RAID data/parity block-placement strategies.

    Each subclass (RAID_0, RAID_1, RAID_4, RAID_5) implements
    :meth:`logical_id_to_physical_positions`, mapping a logical block ID onto
    the physical block position(s) it occupies for that RAID level.
    """

    @abstractmethod
    def logical_id_to_physical_positions(
        self, logical_block_ID: int, number_of_disks: int
    ) -> list[PhysicalBlockPosition]:
        """Given a logical block ID and the number of disks, returns a list of the physical block positions of the
        block in the underlying disk/SSD/whatever subsystem.

        @param logical_block_ID: The logical block ID
        @param number_of_disks: The number of available disks

        @return: A list of BlockPositionInformation instances containing the disk ID where to find this logical block,
        the internal block ID on that disk, as well as a flag indicating if the block is a parity block.
        """
        pass


class RAID_0(RAID_Level):
    """RAID 0: Striping without parity"""

    def logical_id_to_physical_positions(
        self, logical_block_ID: int, number_of_disks: int
    ) -> list[PhysicalBlockPosition]:
        """See :meth:`RAID_Level.logical_id_to_physical_positions`.

        Striping without parity: the logical block is placed round-robin on a
        single disk. Returns exactly one data position and no parity block.
        """

        disk_ID: int = logical_block_ID % number_of_disks

        # distribute logical blocks round-robin over all available disks:
        internal_block_ID: int = logical_block_ID // number_of_disks

        return [PhysicalBlockPosition(disk_ID, internal_block_ID, False)]


class RAID_1(RAID_Level):
    """RAID 1: Mirroring"""

    def logical_id_to_physical_positions(
        self, logical_block_ID: int, number_of_disks: int
    ) -> list[PhysicalBlockPosition]:
        """See :meth:`RAID_Level.logical_id_to_physical_positions`.

        Mirroring: the logical block is replicated on every disk at the same
        internal position. Returns one data position per disk and no parity.
        """

        # trivial: all blocks get replicated on all available disks:
        internal_block_ID: int = logical_block_ID

        return list[PhysicalBlockPosition](
            [
                PhysicalBlockPosition(disk_ID, internal_block_ID, False)
                for disk_ID in range(0, number_of_disks)
            ]
        )


class RAID_4(RAID_Level):
    """RAID 4: Striping with dedicated parity disk"""

    def logical_id_to_physical_positions(
        self, logical_block_ID: int, number_of_disks: int
    ) -> list[PhysicalBlockPosition]:
        """See :meth:`RAID_Level.logical_id_to_physical_positions`.

        Striping with a dedicated parity disk (always the last disk): the data
        block is striped round-robin over the remaining disks. Returns one data
        position plus one parity position (on the last disk) for its row.
        Requires at least three disks.
        """

        assert number_of_disks >= 3, "Not enough disks for this RAID-level"

        # disk_ID where to find this logical block, -1 due to parity disk (last disk)
        # in other words, we divide by the available disks per row (number_of_disks - 1)
        disk_ID: int = logical_block_ID % (number_of_disks - 1)

        # internal block ID on that disk
        internal_block_ID: int = logical_block_ID // (number_of_disks - 1)

        return [
            PhysicalBlockPosition(disk_ID, internal_block_ID, False),
            # parity is always on the last disk:
            PhysicalBlockPosition(number_of_disks - 1, internal_block_ID, True),
        ]


class RAID_5(RAID_Level):
    """RAID 5: Striping with distributed (round-robin) parity"""

    def logical_id_to_physical_positions(
        self, logical_block_ID: int, number_of_disks: int
    ) -> list[PhysicalBlockPosition]:
        """See :meth:`RAID_Level.logical_id_to_physical_positions`.

        Striping with distributed (round-robin) parity: the parity disk rotates
        per row (the diagonal pattern) instead of being fixed, and the data-disk
        index is shifted right by one whenever it is greater than or equal to the
        parity-disk index, so the round-robin skips over the parity disk.
        Returns one data position plus one parity position for its row.
        Requires at least three disks.
        """

        assert number_of_disks >= 3, "Not enough disks for this RAID-level"

        # (1.) internal block ID (aka row) on that disk:
        # no post-correction required
        internal_block_ID_data_block: int = logical_block_ID // (number_of_disks - 1)

        # (2.) parity block:
        # disk ID of the parity block affected by this data block:
        # this computes the "diagonal pattern", i.e. the actual round-robin distribution of the parity block:
        disk_ID_parity_block: int = (internal_block_ID_data_block - 1) % number_of_disks

        # internal block ID of the parity block affected by this data block:
        internal_block_ID_parity_block: int = internal_block_ID_data_block

        # (3.) data block:
        # disk ID where to find this logical block (assuming RAID 4-style assignment), -1 due to parity disk
        # in other words, we divide by the available disks per row (number_of_disks - 1)
        # post-correction required, as the parity disk is skipped in the round-robin distribution:
        disk_ID_data_block: int = logical_block_ID % (number_of_disks - 1)

        # post correction: is the disk ID greater equal the parity disk ID?
        if disk_ID_data_block >= disk_ID_parity_block:
            # then we need to shift the disk ID by one to the right to skip the parity disk:
            disk_ID_data_block += 1

        assert disk_ID_data_block < number_of_disks, "Disk ID out of bounds"

        return [
            PhysicalBlockPosition(
                disk_ID_data_block, internal_block_ID_data_block, False
            ),
            PhysicalBlockPosition(
                disk_ID_parity_block,
                internal_block_ID_parity_block,
                True,
            ),
        ]


def compute_assignment(
    rows: int = 7, number_of_disks: int = 3, RAID_level: int = 0
) -> list[str]:
    """Computes the assignment of logical block IDs to physical block IDs for a given RAID level.

    @param rows: The number of rows in the disk subsystem, i.e. the number of internal blocks per disk tom compute for
    all disks
    @param number_of_disks: The number of disks in the disk subsystem
    @param RAID_level: The RAID level to compute the assignment for, possible values: 0, 1, 4, 5

    @return: A list of strings representing the assignment of logical block IDs to physical block IDs
    """

    assert RAID_level in [0, 1, 4, 5]
    assert rows > 0
    assert number_of_disks > 0
    assert number_of_disks >= 3 or RAID_level in [0, 1]

    # matrix collecting in each cell the list of logical block IDs assigned to this physical block:
    physical_disk_blocks = defaultdict(dict)

    # matrix init:
    for disk in range(0, number_of_disks):
        for row in range(0, rows):
            physical_disk_blocks[disk][row] = list()

    # maximum logical block ID:
    logical_block_ID_max: int = rows * number_of_disks

    # mapping of RAID level to strategy instance:
    int_to_class_dict: dict[int, RAID_Level] = dict[int, RAID_Level](
        {
            0: RAID_0(),
            1: RAID_1(),
            4: RAID_4(),
            5: RAID_5(),
        }
    )

    # get the appropriate instance of the <RAID_level> strategy:
    strategy: RAID_Level = int_to_class_dict[RAID_level]

    # call assign for each logical_block_ID:
    for logical_block_ID in range(0, logical_block_ID_max):

        # for this logical block ID, compute the list of physical positions affected under this RAID level:
        ret: list[PhysicalBlockPosition] = strategy.logical_id_to_physical_positions(
            logical_block_ID, number_of_disks
        )

        # assign the results to the matrix:
        entry: PhysicalBlockPosition
        for entry in ret:
            if entry.internal_block_ID >= rows:
                break
            # append to cell
            physical_disk_blocks[entry.disk_ID][entry.internal_block_ID].append(
                (logical_block_ID, entry.is_parity)
            )

    ret: list[str] = list[str]()

    # create nice string-output:
    row: int
    for row in range(0, rows):
        ret_row = ""
        disk: int
        for disk in range(0, number_of_disks):
            entry_list: list[tuple] = physical_disk_blocks[disk][row]
            if len(entry_list) == 1 and entry_list[0][1] is False:
                ret_row += str(entry_list[0][0]).ljust(11)
            else:
                entry_list_mapped = list(map(lambda x: str(x[0]), entry_list))
                # parity block using XOR-symbol "^":
                ret_row += str("P[" + "^".join(entry_list_mapped) + "]").ljust(11)
        ret.append(ret_row.strip())

    return ret
