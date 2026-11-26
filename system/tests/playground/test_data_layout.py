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
"""Tests for the row and column layout of a relation stored one value per line and for reading it in blocks."""

import os
import tempfile
import unittest

from system.playground.data_layout import (
    BLOCK_SIZE,
    BlockRead,
    ValueFile,
    column_major_line,
    row_major_line,
)

# a relation of 4 tuples with 3 attributes, as (title, author, price):
TUPLES: list[tuple[str, str, str]] = [
    ("Dracula", "Stoker", "12.99"),
    ("Emma", "Austen", "7.5"),
    ("Ulysses", "Joyce", "14.2"),
    ("Beloved", "Morrison", "11.25"),
]


class LayoutLineTest(unittest.TestCase):
    """The line of a value in the row and in the column layout."""

    def test_row_layout_stores_tuple_after_tuple(self) -> None:
        """In the row layout, the values of one tuple are on consecutive lines, one tuple after the other."""
        lines: list[list[int]] = [
            [row_major_line(t, a, number_of_attributes=3) for a in range(3)]
            for t in range(4)
        ]
        self.assertEqual([[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11]], lines)

    def test_column_layout_stores_column_after_column(self) -> None:
        """In the column layout, the values of one attribute are on consecutive lines, one attribute after the
        other."""
        lines: list[list[int]] = [
            [column_major_line(t, a, number_of_tuples=4) for t in range(4)]
            for a in range(3)
        ]
        self.assertEqual([[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]], lines)


class ValueFileTest(unittest.TestCase):
    """Reading the values of a file block by block, and what it costs."""

    def setUp(self) -> None:
        """Writes TUPLES in the row and in the column layout into two files of a temporary directory."""
        # enterContext removes the directory after each test, which pylint does not see:
        # pylint: disable-next=consider-using-with
        self.directory: str = self.enterContext(tempfile.TemporaryDirectory())
        self.row_path: str = os.path.join(self.directory, "row.csv")
        self.column_path: str = os.path.join(self.directory, "column.csv")
        # row layout: tuple after tuple:
        with open(self.row_path, "w", encoding="utf-8", newline="\n") as file:
            for values in TUPLES:
                file.writelines(value + "\n" for value in values)
        # column layout: column after column:
        with open(self.column_path, "w", encoding="utf-8", newline="\n") as file:
            for attribute in range(3):
                file.writelines(values[attribute] + "\n" for values in TUPLES)

    def write(self, text: str) -> str:
        """Writes the file ``values.csv`` with the given text, encoded in UTF-8 (a character takes one to four bytes),
        into the temporary directory; it replaces the file of an earlier call.

        @param text: the content of the file
        @return: the path of the file
        """
        path: str = os.path.join(self.directory, "values.csv")
        with open(path, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        return path

    def test_positions_size_and_blocks(self) -> None:
        """The file knows the bytes at which each value starts and ends, its size and how many blocks it takes."""
        # values "ab" (bytes 0-1), "c" (byte 3) and "defg" (bytes 5-8), each followed by a line break:
        value_file: ValueFile = ValueFile(self.write("ab\nc\ndefg\n"), block_size=4)
        self.assertEqual(([0, 3, 5], [2, 4, 9]), (value_file.starts, value_file.ends))
        self.assertEqual((10, 3), (value_file.size, value_file.number_of_lines))
        # blocks of 4 bytes: 0-3, 4-7 and the short last block 8-9:
        self.assertEqual(3, value_file.number_of_blocks)
        # the default block size is BLOCK_SIZE:
        self.assertEqual(BLOCK_SIZE, ValueFile(value_file.path).block_size)

    def test_a_value_inside_one_block(self) -> None:
        """A value inside one block costs that block."""
        value_file: ValueFile = ValueFile(self.write("ab\nc\ndefg\n"), block_size=4)
        # "ab" is bytes 0-1, inside block 0:
        self.assertEqual(
            BlockRead(
                values=("ab",), bytes_needed=2, blocks_read=1, bytes_read=4, places=1
            ),
            value_file.read([0]),
        )

    def test_a_value_spanning_two_blocks(self) -> None:
        """A value that crosses the end of a block costs both blocks and is put together from them."""
        value_file: ValueFile = ValueFile(self.write("ab\nc\ndefg\n"), block_size=4)
        # "defg" is bytes 5-8: block 1 (bytes 4-7) and the short last block 2 (bytes 8-9):
        self.assertEqual(
            BlockRead(
                values=("defg",), bytes_needed=4, blocks_read=2, bytes_read=6, places=1
            ),
            value_file.read([2]),
        )

    def test_a_value_longer_than_a_block(self) -> None:
        """A value longer than a block costs every block it touches."""
        # "abcdefghij" is bytes 0-9: blocks 0, 1 and the first two bytes of block 2 (bytes 8-10):
        value_file: ValueFile = ValueFile(self.write("abcdefghij\n"), block_size=4)
        self.assertEqual(
            BlockRead(
                values=("abcdefghij",),
                bytes_needed=10,
                blocks_read=3,
                bytes_read=11,
                places=1,
            ),
            value_file.read([0]),
        )

    def test_the_last_line_needs_no_line_break(self) -> None:
        """The last line of a file may lack its line break; a file of whole blocks has no short last block."""
        # "ab" (bytes 0-1) with its line break, then "c" (byte 3) without one: 4 bytes, exactly one block:
        value_file: ValueFile = ValueFile(self.write("ab\nc"), block_size=4)
        self.assertEqual(([0, 3], [2, 4]), (value_file.starts, value_file.ends))
        self.assertEqual((4, 1), (value_file.size, value_file.number_of_blocks))
        self.assertEqual(
            BlockRead(
                values=("c",), bytes_needed=1, blocks_read=1, bytes_read=4, places=1
            ),
            value_file.read([1]),
        )

    def test_the_line_break_is_not_read(self) -> None:
        """A value that ends at the end of a block costs only this block, although its line break lies in the next
        one; a line break of two bytes is no part of the value either."""
        # "abcd" fills block 0 (bytes 0-3), its line break is byte 4, in block 1:
        value_file: ValueFile = ValueFile(self.write("abcd\ne\n"), block_size=4)
        self.assertEqual(
            BlockRead(
                values=("abcd",), bytes_needed=4, blocks_read=1, bytes_read=4, places=1
            ),
            value_file.read([0]),
        )
        # line breaks "\r\n", as written on Windows:
        value_file = ValueFile(self.write("ab\r\nc\r\n"), block_size=4)
        self.assertEqual(([0, 4], [2, 5]), (value_file.starts, value_file.ends))
        self.assertEqual(("ab", "c"), value_file.read([0, 1]).values)

    def test_positions_count_bytes_not_characters(self) -> None:
        """A character of two bytes in UTF-8 counts two bytes, and is read correctly when its bytes lie in two
        blocks."""
        # "é" takes two bytes: "aé" is bytes 0-2, so its "é" is split between block 0 (bytes 0-1) and block 1:
        value_file: ValueFile = ValueFile(self.write("aé\nb\n"), block_size=2)
        self.assertEqual(
            ([0, 4], [3, 5], 6), (value_file.starts, value_file.ends, value_file.size)
        )
        self.assertEqual(
            BlockRead(
                values=("aé",), bytes_needed=3, blocks_read=2, bytes_read=4, places=1
            ),
            value_file.read([0]),
        )

    def test_values_in_the_same_block_cost_it_once(self) -> None:
        """Two values in the same block cost that block once; the values come back in the order asked for and a
        value asked for twice comes back twice, but its bytes are needed once."""
        value_file: ValueFile = ValueFile(self.write("ab\nc\ndefg\n"), block_size=4)
        # "c" (byte 3) and "ab" (bytes 0-1) both lie in block 0:
        read: BlockRead = value_file.read([1, 0, 1])
        self.assertEqual(("c", "ab", "c"), read.values)
        self.assertEqual(
            (3, 1, 4), (read.bytes_needed, read.blocks_read, read.bytes_read)
        )

    def test_places_are_runs_of_consecutive_blocks(self) -> None:
        """Blocks that follow each other in the file are one place, blocks with a gap between them two places."""
        # "a", "b" and "c" lie in blocks 0, 1 and 2:
        value_file: ValueFile = ValueFile(self.write("a\nb\nc\n"), block_size=2)
        self.assertEqual(1, value_file.read([0, 1, 2]).places)
        self.assertEqual(2, value_file.read([2, 0]).places)
        # the places do not depend on the order in which the lines are asked for:
        self.assertEqual(1, value_file.read([2, 0, 1]).places)

    def test_an_empty_value_reads_nothing(self) -> None:
        """An empty value and an empty list of lines read no block, also when the empty value lies inside a block,
        not at its start."""
        # the empty value is at byte 3, inside block 0 (bytes 0-3):
        value_file: ValueFile = ValueFile(self.write("ab\n\nc\n"), block_size=4)
        self.assertEqual(([0, 3, 4], [2, 3, 5]), (value_file.starts, value_file.ends))
        # no line asked for:
        nothing: BlockRead = BlockRead(
            values=(), bytes_needed=0, blocks_read=0, bytes_read=0, places=0
        )
        self.assertEqual(nothing, value_file.read([]))
        # only the empty value:
        self.assertEqual(
            BlockRead(
                values=("",), bytes_needed=0, blocks_read=0, bytes_read=0, places=0
            ),
            value_file.read([1]),
        )

    def test_an_empty_file(self) -> None:
        """An empty file has no lines and takes no block; reading no line reads nothing, and its first line does not
        exist."""
        value_file: ValueFile = ValueFile(self.write(""), block_size=4)
        self.assertEqual(
            (0, 0, 0),
            (value_file.size, value_file.number_of_lines, value_file.number_of_blocks),
        )
        # no line asked for:
        self.assertEqual(
            BlockRead(values=(), bytes_needed=0, blocks_read=0, bytes_read=0, places=0),
            value_file.read([]),
        )
        # the first line lies outside the file:
        with self.assertRaises(IndexError):
            value_file.read([0])

    def test_a_line_outside_the_file_raises(self) -> None:
        """A line before the first or after the last line of the file raises an IndexError."""
        value_file: ValueFile = ValueFile(self.write("ab\nc\n"), block_size=4)
        for line in (-1, 2):
            with self.subTest(line=line):
                with self.assertRaises(IndexError):
                    value_file.read([line])

    def test_a_whole_tuple_costs_fewer_blocks_in_the_row_layout(self) -> None:
        """All values of one tuple lie together in the row layout but in three places of the column layout."""
        # blocks of 16 bytes; each file holds 79 bytes; tuple 1 is ("Emma", "Austen", "7.5"):
        row_file: ValueFile = ValueFile(self.row_path, block_size=16)
        column_file: ValueFile = ValueFile(self.column_path, block_size=16)
        row_read: BlockRead = row_file.read(
            row_major_line(1, a, number_of_attributes=3) for a in range(3)
        )
        column_read: BlockRead = column_file.read(
            column_major_line(1, a, number_of_tuples=4) for a in range(3)
        )
        # both return the same values and need the same 13 bytes:
        self.assertEqual(("Emma", "Austen", "7.5"), row_read.values)
        self.assertEqual(row_read.values, column_read.values)
        self.assertEqual((13, 13), (row_read.bytes_needed, column_read.bytes_needed))
        # the row layout reads blocks 1 and 2 (the tuple is bytes 21-35), the column layout blocks 0, 2 and 4:
        self.assertEqual((2, 1), (row_read.blocks_read, row_read.places))
        self.assertEqual((3, 3), (column_read.blocks_read, column_read.places))

    def test_one_attribute_of_all_tuples_costs_fewer_blocks_in_the_column_layout(
        self,
    ) -> None:
        """The prices of all tuples lie together in the column layout but between the other values in the row
        layout."""
        # blocks of 16 bytes; each file holds 79 bytes in 5 blocks:
        row_file: ValueFile = ValueFile(self.row_path, block_size=16)
        column_file: ValueFile = ValueFile(self.column_path, block_size=16)
        row_read: BlockRead = row_file.read(
            row_major_line(t, 2, number_of_attributes=3) for t in range(4)
        )
        column_read: BlockRead = column_file.read(
            column_major_line(t, 2, number_of_tuples=4) for t in range(4)
        )
        # both return the same prices and need the same 17 bytes:
        self.assertEqual(("12.99", "7.5", "14.2", "11.25"), row_read.values)
        self.assertEqual(row_read.values, column_read.values)
        self.assertEqual((17, 17), (row_read.bytes_needed, column_read.bytes_needed))
        # the row layout reads all 5 blocks of its file; the column layout reads the blocks 3 and 4 of the prices
        # (bytes 58-77), 31 bytes, as the last block is short:
        self.assertEqual((5, 5), (row_file.number_of_blocks, row_read.blocks_read))
        self.assertEqual((2, 31), (column_read.blocks_read, column_read.bytes_read))


class BlockReadTest(unittest.TestCase):
    """The one-line summary of a read."""

    def test_summary(self) -> None:
        """The summary gives the values and bytes needed and the blocks, bytes and places read, with thousands
        separators and the singular for one value, block or place, each on its own."""
        # one of each:
        self.assertEqual(
            "1 value (4 B) needed, 1 block read (4,096 B) from 1 place",
            BlockRead(
                values=("12.5",),
                bytes_needed=4,
                blocks_read=1,
                bytes_read=4096,
                places=1,
            ).summary(),
        )
        # several values from one block, as one whole book in the row layout:
        self.assertEqual(
            "3 values (50 B) needed, 1 block read (4,096 B) from 1 place",
            BlockRead(
                values=("a", "b", "c"),
                bytes_needed=50,
                blocks_read=1,
                bytes_read=4096,
                places=1,
            ).summary(),
        )
        # many values and blocks from one place, with thousands separators, as all prices in the row layout:
        self.assertEqual(
            "10,000 values (47,014 B) needed, 140 blocks read (571,549 B) from 1 place",
            BlockRead(
                values=("1",) * 10_000,
                bytes_needed=47_014,
                blocks_read=140,
                bytes_read=571_549,
                places=1,
            ).summary(),
        )
        # several blocks from several places, as one whole book in the column layout:
        self.assertEqual(
            "3 values (50 B) needed, 3 blocks read (12,288 B) from 3 places",
            BlockRead(
                values=("a", "b", "c"),
                bytes_needed=50,
                blocks_read=3,
                bytes_read=12_288,
                places=3,
            ).summary(),
        )


if __name__ == "__main__":
    unittest.main()
