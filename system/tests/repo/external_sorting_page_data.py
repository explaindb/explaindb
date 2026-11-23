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

"""The runs, merges and page counts of the external sorting page (``visualizations/external-sorting.html``).

The page sorts table R, the 576 keys of ``INPUT`` in its script, on pages of 16 values, with a main memory of 4 pages
(64 values) and fan-in 3, as the code's ``ExternalMergeSort`` (``system/query_processing/sorting.py``) does. Pass 0
sorts R in pieces of 64 values into 9 runs; merge level 1 merges them in the three groups ``GROUPS`` of its script
into 3 runs; the final merge merges those 3 and writes nothing. Its counter then shows 108 pages read and 72 written.
Two tests compare these with what this module expects: ``test_external_sorting_page_data.py`` checks that the real
``ExternalMergeSort`` makes these runs and merges from ``INPUT`` and reads and writes as many pages, and
``ExternalSortingPageTest`` in ``test_visualizations.py`` checks that the page's counter shows these numbers and that
the runs the page sorts and merges itself (``data-made``) are these. The same
two compare the heap of each merge, as ``merge_heaps`` replays it, with the real ``SingleStreamMerge``'s heap and with
the page's heap stand.

This module uses the standard library only, as ``b_tree_page_trees.py`` does: the CI job ``visualization_test``
installs nothing but Playwright. The browser test compares the page with the fixed numbers here, not with the code
itself, as that job runs only when a page or its tests change; the unit test, which runs with the repository's other
tests, compares the code with the same numbers.
"""

import heapq
import json
import math
import re
from pathlib import Path
from typing import NamedTuple

# Anchored to this file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
EXTERNAL_SORTING_PAGE: Path = REPO_ROOT / "visualizations" / "external-sorting.html"

# a page holds 16 values; main memory holds 4 pages, so pass 0 sorts 64 values at a time; a merge reads 3 runs:
VALUES_PER_PAGE: int = 16
MEMORY_PAGES: int = 4
MEMORY_VALUES: int = VALUES_PER_PAGE * MEMORY_PAGES
FAN_IN: int = 3

# the groups of pass 0's runs that merge level 1 merges, in the order of the merges: each the places of its runs
# among the 9 runs of pass 0, counted from 0 (so run r1 is 0), in the order the merge reads them, which is the order
# of its heap's first entries. All runs have the same size, and the code merges runs of the same size in the order
# they were made: runs 1 to 3, 4 to 6, 7 to 9. The runs merged from them are r10, r11 and r12, in this order:
EXPECTED_GROUPS: list[list[int]] = [
    [0, 1, 2],
    [3, 4, 5],
    [6, 7, 8],
]


class PageCounts(NamedTuple):
    """How many pages a pass of the sort reads and how many it writes."""

    reads: int
    writes: int


# the pages each pass reads and writes, in order: pass 0, merge level 1, the final merge. Each pass reads all 36 pages
# of the data; all but the final merge, whose output goes to the query, write all 36 again:
EXPECTED_PASS_COUNTS: list[PageCounts] = [
    PageCounts(reads=36, writes=36),
    PageCounts(reads=36, writes=36),
    PageCounts(reads=36, writes=0),
]

# what the page's counter shows at the end: 36 pages read in each of the 3 passes, 36 written in each of the first 2:
EXPECTED_READS: int = 108
EXPECTED_WRITES: int = 72


def read_input(page: Path = EXTERNAL_SORTING_PAGE) -> list[int]:
    """Reads table R from the page's script.

    @param page: the HTML file of the external sorting page
    @return: ``INPUT``, the keys of R in the order in which they lie on its pages (16 per page)
    @raise ValueError: if the script has no array ``const INPUT = [...];`` of whole numbers
    """
    html: str = page.read_text(encoding="utf-8")
    # the array spans many lines and ends with a comma before its closing bracket, so it is not JSON; it holds only
    # digits, commas and white space:
    match: re.Match[str] | None = re.search(
        r"^\s*const INPUT = \[([\d\s,]*)\];", html, re.MULTILINE
    )
    if match is None:
        raise ValueError(
            f"{page.name} has no array 'const INPUT = [...];' of whole numbers"
        )
    return [int(key) for key in match.group(1).split(",") if key.strip()]


def read_groups(page: Path = EXTERNAL_SORTING_PAGE) -> list[list[int]]:
    """Reads the groups of runs that the page's merge level 1 merges from its script.

    @param page: the HTML file of the external sorting page
    @return: ``GROUPS``, for each merge of level 1 in its order, the places of its runs among pass 0's runs (from 0)
    @raise ValueError: if the script has no line ``const GROUPS = [...];``
    """
    html: str = page.read_text(encoding="utf-8")
    # one line, a JSON array of arrays:
    match: re.Match[str] | None = re.search(
        r"^\s*const GROUPS = (\[.*\]);", html, re.MULTILINE
    )
    if match is None:
        raise ValueError(f"{page.name} has no line 'const GROUPS = [...];'")
    return json.loads(match.group(1))


def pass_0_runs(values: list[int]) -> list[list[int]]:
    """Returns the runs that pass 0 writes: each piece of MEMORY_VALUES values of the input, in its order, sorted.

    @param values: the input (R)
    @return: the runs r1, r2, …, each its values in ascending order
    """
    return [
        sorted(values[start : start + MEMORY_VALUES])
        for start in range(0, len(values), MEMORY_VALUES)
    ]


def merged_runs(runs: list[list[int]], groups: list[list[int]]) -> list[list[int]]:
    """Returns the runs that merges make from groups of runs: for each group, the values of its runs, sorted.

    @param runs: the runs to merge, e.g. those of pass 0
    @param groups: for each merge, the places of its runs in runs (from 0)
    @return: for each group, in its order, the run its merge writes
    """
    return [
        sorted(value for place in group for value in runs[place]) for group in groups
    ]


def merge_heaps(runs: list[list[int]]) -> list[list[int]]:
    """Replays the heap of the code's SingleStreamMerge as it merges runs, and returns its values by place before each
    value it gives out.

    The heap holds an entry per run that is not used up, with the run's next value, ordered by value, as a list in
    heapq's layout: place 0 is the root, places 1 and 2 its children. It starts with each run's first value, in the
    order of runs, and is heapified. Each step gives out the root's value; the root's run's next value then takes the
    root's place and sinks (heapreplace), or, if the run is used up, its entry leaves the heap and the last entry takes
    the root's place and sinks (heappop). With 3 entries at most, heapq's sinking is the textbook's: the value at the
    root swaps with its smaller child while that child is smaller.

    @param runs: the runs the merge reads, in the order in which it takes them, each in ascending order; all values
        distinct
    @return: for each value the merge gives out, in order, the values on the heap by place just before: the root (the
        value given out) first, then its children: one value per run not used up yet
    @raise ValueError: if a value occurs twice
    """
    # the replay breaks ties between equal values as the code does only by chance, so it takes distinct values only:
    values: list[int] = [value for run in runs for value in run]
    if len(set(values)) != len(values):
        raise ValueError("merge_heaps takes runs of distinct values only")
    # an entry per run: its next value, the run (its place in runs) and the value's place in the run; the values
    # decide the order, as they are distinct:
    heap: list[tuple[int, int, int]] = [
        (run[0], r, 0) for r, run in enumerate(runs) if run
    ]
    heapq.heapify(heap)
    layouts: list[list[int]] = []
    while heap:
        layouts.append([value for value, _, _ in heap])
        _, r, place = heap[0]
        if place + 1 < len(runs[r]):
            # the run's next value takes the root's place and sinks:
            heapq.heapreplace(heap, (runs[r][place + 1], r, place + 1))
        else:
            # the run is used up: its entry leaves the heap:
            heapq.heappop(heap)
    return layouts


def pages_of(size: int) -> int:
    """Returns how many pages a table or run of size values fills: one page per 16 values, its last one perhaps not
    full (a run starts on a page of its own).

    @param size: how many values
    @return: how many pages they fill
    """
    return math.ceil(size / VALUES_PER_PAGE)


def pass_page_counts(read_sizes: list[int], written_sizes: list[int]) -> PageCounts:
    """Returns how many pages a pass reads and writes, from the sizes of the tables and runs it reads and writes.

    @param read_sizes: the number of values of each table or run that the pass reads
    @param written_sizes: the number of values of each run that it writes
    @return: the pages of the tables and runs read, and those of the runs written (see pages_of)
    """
    return PageCounts(
        reads=sum(pages_of(size) for size in read_sizes),
        writes=sum(pages_of(size) for size in written_sizes),
    )
