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

"""Reads the values a query needs from a relation stored one value per line, block by block, and counts the blocks.

A relation can be stored in a row layout (all values of the first tuple, then all values of the second tuple, and so
on) or in a column layout (the values of the first attribute of all tuples, then those of the second attribute, and
so on). :func:`row_major_line` and :func:`column_major_line` give the line of a value in each layout. A
:class:`ValueFile` reads the lines a query needs the way a disk, an SSD (solid-state drive) or the operating system
reads a file: in whole blocks. Which blocks it has to read, and how many, depends on the layout. The notebook
``Data-Layout.ipynb`` uses it.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

# the number of bytes a disk, an SSD or the operating system reads at once, a common size of a block (page):
BLOCK_SIZE: int = 4096


def row_major_line(
    tuple_index: int, attribute_index: int, *, number_of_attributes: int
) -> int:
    """Returns the line of a value in the row layout, which stores all values of tuple 0, then all values of tuple 1,
    and so on.

    @param tuple_index: the position of the tuple in the relation, from 0
    @param attribute_index: the position of the attribute in the schema, from 0
    @param number_of_attributes: the number of attributes in the schema
    @return: the line of the value, from 0
    """
    return tuple_index * number_of_attributes + attribute_index


def column_major_line(
    tuple_index: int, attribute_index: int, *, number_of_tuples: int
) -> int:
    """Returns the line of a value in the column layout, which stores the values of attribute 0 of all tuples, then
    those of attribute 1, and so on.

    @param tuple_index: the position of the tuple in the relation, from 0
    @param attribute_index: the position of the attribute in the schema, from 0
    @param number_of_tuples: the number of tuples in the relation
    @return: the line of the value, from 0
    """
    return attribute_index * number_of_tuples + tuple_index


@dataclass(frozen=True)
class BlockRead:
    """The values one call of :meth:`ValueFile.read` returned and how much of the file it read."""

    # the values of the lines asked for, in that order:
    values: tuple[str, ...]
    # the bytes of these values, without their line breaks, each line counted once: the least the query has to read:
    bytes_needed: int
    # the blocks read, each once, and their bytes (the last block of a file can be shorter than a whole block):
    blocks_read: int
    bytes_read: int
    # the separate places of the file these blocks lie in: each run of consecutive blocks is one place, which a
    # hard disk reaches with one seek if the file lies in one piece on the disk:
    places: int

    def summary(self) -> str:
        """Returns one line with the number of values and the bytes needed, and the blocks, bytes and places read.

        @return: e.g. ``"3 values (50 B) needed, 3 blocks read (12,288 B) from 3 places"``
        """
        values: str = "value" if len(self.values) == 1 else "values"
        blocks: str = "block" if self.blocks_read == 1 else "blocks"
        places: str = "place" if self.places == 1 else "places"
        return (
            f"{len(self.values):,} {values} ({self.bytes_needed:,} B) needed, "
            f"{self.blocks_read:,} {blocks} read ({self.bytes_read:,} B) from {self.places:,} {places}"
        )


class ValueFile:
    """A file that stores one value per line, e.g. a relation written as CSV (comma-separated values) in a row or a
    column layout, and is read in whole blocks.

    It knows the bytes at which each of its values starts and ends, as a database knows where each value lies (it
    stores values of a fixed width or keeps the position of each value). It finds these positions once, when it is
    made, by reading the whole file; :meth:`read` does not count that read. A value is its line without the line
    break (``\\n`` or ``\\r\\n``): the line break only separates the values in the file, so a query does not need it.
    """

    def __init__(self, path: str, block_size: int = BLOCK_SIZE) -> None:
        """Finds the bytes at which each value of the file starts and ends.

        @param path: the file, one value per line, encoded in UTF-8 (a character takes one to four bytes)
        @param block_size: the number of bytes of a block, the unit in which :meth:`read` reads the file, at least 1
        """
        assert block_size >= 1
        self.path: str = path
        self.block_size: int = block_size
        # the byte at which each value starts and the byte after its last byte, both counted from 0:
        self.starts: list[int] = []
        self.ends: list[int] = []
        # the file is read in binary mode, so that a position counts bytes, not characters; the last line may lack
        # a line break:
        position: int = 0
        with open(path, "rb") as file:
            for line in file:
                line_break: int = (
                    2 if line.endswith(b"\r\n") else 1 if line.endswith(b"\n") else 0
                )
                self.starts.append(position)
                self.ends.append(position + len(line) - line_break)
                position += len(line)
        # the number of bytes of the file:
        self.size: int = position

    @property
    def number_of_lines(self) -> int:
        """The number of lines (values) in the file."""
        return len(self.starts)

    @property
    def number_of_blocks(self) -> int:
        """The number of blocks the file takes; the last one can be shorter than a whole block."""
        return math.ceil(self.size / self.block_size)

    def _blocks_of(self, line_number: int) -> range:
        """Returns the blocks that hold a byte of a value: from the block of its first byte to that of its last byte.

        @param line_number: the line of the value, from 0
        @return: the numbers of these blocks, from 0; none for an empty value
        @raise IndexError: if the file has no such line
        """
        # a negative line number would count from the end of the lists, so it is rejected, too:
        if not 0 <= line_number < self.number_of_lines:
            raise IndexError(
                f"line {line_number} is not in {self.path} ({self.number_of_lines} lines)"
            )
        start: int = self.starts[line_number]
        end: int = self.ends[line_number]
        # an empty value has no byte, so no block holds it:
        if start == end:
            return range(0)
        return range(start // self.block_size, (end - 1) // self.block_size + 1)

    def read(self, line_numbers: Iterable[int]) -> BlockRead:
        """Reads the values of the given lines block by block: reads every block that holds a byte of one of the
        values, each block once, and takes the values from these blocks.

        @param line_numbers: the lines whose values are read, from 0, in the order their values are returned; a line
        may occur more than once, but its bytes are needed only once
        @return: the values and how much was needed and read
        @raise IndexError: if the file has no such line
        """
        wanted: list[int] = list(line_numbers)
        # the blocks to read, each once:
        block_numbers: set[int] = set()
        for line_number in wanted:
            block_numbers.update(self._blocks_of(line_number))
        # read these blocks, in the order they lie in the file:
        blocks: dict[int, bytes] = {}
        with open(self.path, "rb") as file:
            for number in sorted(block_numbers):
                file.seek(number * self.block_size)
                blocks[number] = file.read(self.block_size)
        # take each value from the block or the blocks that hold it; a character of several bytes can be split
        # between two blocks, so the bytes are joined before they are decoded:
        values: list[str] = []
        for line_number in wanted:
            value_blocks: range = self._blocks_of(line_number)
            data: bytes = b"".join(blocks[number] for number in value_blocks)
            # the positions of the value's first byte and of the byte after its last byte, within these blocks:
            start: int = self.starts[line_number] - value_blocks.start * self.block_size
            end: int = self.ends[line_number] - value_blocks.start * self.block_size
            values.append(data[start:end].decode("utf-8"))
        # a block starts a new place unless the block before it is read, too:
        places: int = sum(
            1 for number in block_numbers if number - 1 not in block_numbers
        )
        return BlockRead(
            values=tuple(values),
            bytes_needed=sum(
                self.ends[line_number] - self.starts[line_number]
                for line_number in set(wanted)
            ),
            blocks_read=len(blocks),
            bytes_read=sum(len(block) for block in blocks.values()),
            places=places,
        )
