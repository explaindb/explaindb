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
"""Tests for the merge tree of an external merge sort, drawn as SVG: read back by parsing the SVG."""

from __future__ import annotations

import math
import random
import re
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from typing import Any

from system.playground.merge_tree import (
    MAX_VALUES,
    merge_tree_svg,
    page_labels,
)
from system.playground.sort_counting import Merge, Run, SortCounts, sort_counted

# the SVG namespace, as ElementTree puts it in front of every tag:
SVG: str = "{http://www.w3.org/2000/svg}"

# the input row of slides 22 (quicksort) and 23 (replacement selection) of lecture 09b:
SLIDES: tuple[int, ...] = (3, 4, 6, 2, 9, 4, 8, 7, 5, 6, 3, 1, 1, 4, 6, 7)
# the sorts of slides 22 and 23 (M = 4, F = 2), and of 20 ascending values with quicksort (M = 4, F = 2):
SLIDE_22: SortCounts[int] = sort_counted(SLIDES, 4, 2, False)
SLIDE_23: SortCounts[int] = sort_counted(SLIDES, 4, 2, True)
TWENTY: SortCounts[int] = sort_counted(range(20), 4, 2, False)
# a copy of the small example of the notebook External-Merge-Sort.ipynb (whose own tests check the notebook's copy;
# system/tests/repo/test_external_merge_sort_notebook.py checks that both are the same):
# 36 values on 18 pages of two, sorted with M = 4 and F = 3, so that every merge reads three runs:
SMALL_EXAMPLE: tuple[int, ...] = (
    4, 5, 1, 4, 2, 5, 7, 5, 6, 5, 5, 2, 2, 1, 9, 8, 8, 6,
    2, 4, 5, 1, 6, 7, 4, 9, 8, 2, 4, 1, 3, 9, 4, 6, 6, 5,
)  # fmt: skip
SMALL_EXAMPLE_CHUNKS: SortCounts[int] = sort_counted(SMALL_EXAMPLE, 4, 3, False)
SMALL_EXAMPLE_SELECTION: SortCounts[int] = sort_counted(SMALL_EXAMPLE, 4, 3, True)
# the trees shown to readers, in the notebook and in the preview of its trees: every merge reads three runs, the runs
# merged are neighbours (runs of equal size, whose smallest are merged first, or no merge before the final one), and
# no two arrows lie on top of each other:
EXAMPLE_CASES: dict[str, SortCounts[int]] = {
    "small example, quicksort": SMALL_EXAMPLE_CHUNKS,
    "small example, replacement selection": SMALL_EXAMPLE_SELECTION,
    # runs of 4: runs 0-2 merge at level 1, runs 3 and 4 pass down through level 1 to the final merge:
    "20 ascending, quicksort, F = 3": sort_counted(range(20), 4, 3, False),
    # runs of 4: runs 0-2 and 3-5 merge at level 1, run 6 passes down through level 1 to the final merge:
    "28 ascending, quicksort, F = 3": sort_counted(range(28), 4, 3, False),
}
# 39 ascending values with M = 4 and F = 3, quicksort: runs 0 to 8 of 4 and run 9 of 3; the first merge reads run 9, at
# the right end of the runs, and runs 0 and 1, at the left end, into run 10:
FAR_APART: SortCounts[int] = sort_counted(range(39), 4, 3, False)
# sorts whose trees have merges that read earlier merges' outputs and arrows that pass down through levels: the
# examples and other data, on which the code may merge runs that are far apart, where arrows may cross:
LAYOUT_CASES: dict[str, SortCounts[int]] = {
    "slide 22": SLIDE_22,
    "slide 23": SLIDE_23,
    **EXAMPLE_CASES,
    "20 ascending": TWENTY,
    # the slides' row with the 1 and the 7 of its last two pages swapped:
    "swapped slide row, replacement selection": sort_counted(
        (3, 4, 6, 2, 9, 4, 8, 7, 5, 6, 3, 1, 7, 4, 6, 1), 4, 2, True
    ),
    "40 descending, replacement selection, F = 3": sort_counted(
        range(39, -1, -1), 4, 3, True
    ),
    "40 random, quicksort, M = 5, F = 2": sort_counted(
        random.Random(46).sample(range(100), 40), 5, 2, False
    ),
    "one value": sort_counted((5,), 4, 2, False),
    # runs of 4, 4 and 2: runs 2 and 0 merge, and their output, centred between them, would sit right under run 1,
    # whose arrow passes down through level 1 to the final merge:
    "10 ascending, quicksort, M = 4, F = 2": sort_counted(range(10), 4, 2, False),
    # runs of 3, 3, 3 and 1: the outputs of runs 3 and 0 and of runs 1 and 2, centred, would overlap:
    "10 ascending, quicksort, M = 3, F = 2": sort_counted(range(10), 3, 2, False),
    "39 ascending, quicksort, M = 4, F = 3": FAR_APART,
}
# the estimated width of one character of a text in the drawing (12-pixel sans-serif), the test's own estimate, so
# that a smaller estimate in the code makes the test fail:
TEXT_CHARACTER_WIDTH: float = 7.5
# the same for the title, which is bold:
TITLE_CHARACTER_WIDTH: float = 9.0
# a colour given as rgba(red,green,blue,alpha), with the channels as groups 1 to 3 and the alpha as group 4:
RGBA: re.Pattern[str] = re.compile(r"rgba\((\d+),(\d+),(\d+),([0-9.]+)\)")


@dataclass(frozen=True)
class Box:
    """A page box: its left, top, right and bottom edge."""

    left: float
    top: float
    right: float
    bottom: float

    def overlaps(self, other: Box) -> bool:
        """Whether the insides of the two boxes overlap."""
        return (
            self.left < other.right
            and other.left < self.right
            and self.top < other.bottom
            and other.top < self.bottom
        )

    def gap(self, x: float, y: float) -> float:
        """How far a point outside the box is from it, along the axis on which it is furthest away (negative
        inside)."""
        return max(self.left - x, x - self.right, self.top - y, y - self.bottom)


@dataclass(order=True, frozen=True)
class Markup:
    """A value ordered by its key whose text, as ``str`` gives it, is markup with every character that SVG needs
    escaped: ``<``, ``>``, ``&``, ``'`` and ``"``."""

    key: int

    def __str__(self) -> str:
        """The key between bold tags, then an ampersand, an apostrophe and a quote, e.g. ``<b>1</b>&'"``."""
        return f"<b>{self.key}</b>&'\""


def parse(counts: SortCounts[Any], page_size: int = 2, title: str = "") -> ET.Element:
    """Draws the merge tree of a sort and parses it."""
    return ET.fromstring(merge_tree_svg(counts, page_size=page_size, title=title))


def groups(root: ET.Element, kind: str) -> list[ET.Element]:
    """Returns the groups of one kind (their ``class``), in the order they are drawn."""
    return [group for group in root.iter(f"{SVG}g") if group.get("class") == kind]


def run_group(root: ET.Element, number: str) -> ET.Element:
    """Returns the group of the run with this number."""
    return next(
        group for group in groups(root, "run") if group.get("data-run") == number
    )


def labels(group: ET.Element) -> list[str]:
    """Returns the label of every page box in a group, from the first box on: the text right after each box."""
    children: list[ET.Element] = list(group)
    return [
        children[index + 1].text or ""
        for index, child in enumerate(children)
        if child.tag == f"{SVG}rect" and child.get("class") == "page"
    ]


def boxes(group: ET.Element) -> list[Box]:
    """Returns every page box in a group."""
    return [
        Box(
            float(rect.get("x", "")),
            float(rect.get("y", "")),
            float(rect.get("x", "")) + float(rect.get("width", "")),
            float(rect.get("y", "")) + float(rect.get("height", "")),
        )
        for rect in group.iter(f"{SVG}rect")
    ]


def drawn_runs(root: ET.Element) -> list[tuple[str, str, list[str]]]:
    """Returns every run drawn as its number, its level and the labels of its pages."""
    return [
        (group.get("data-run", ""), group.get("data-level", ""), labels(group))
        for group in groups(root, "run")
    ]


def arrows(root: ET.Element) -> list[tuple[str, str]]:
    """Returns every arrow as what it comes from and what it leads to."""
    return [
        (group.get("data-from", ""), group.get("data-to", ""))
        for group in groups(root, "arrow")
    ]


def points(arrow: ET.Element) -> list[tuple[float, float]]:
    """Returns the points of an arrow's line, from its start to its head."""
    line: ET.Element = next(arrow.iter(f"{SVG}polyline"))
    return [
        (float(x), float(y))
        for x, y in (point.split(",") for point in line.get("points", "").split())
    ]


def overlapping_stretch(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    """Returns the length of the longest stretch of the first segment that lies within 2 pixels of the second one,
    measured at points one pixel apart: two segments on top of each other share a long stretch, two that cross at a
    clear angle only a few pixels."""
    (x_0, y_0), (x_1, y_1) = first
    (a_x, a_y), (b_x, b_y) = second
    length: float = math.hypot(x_1 - x_0, y_1 - y_0)
    steps: int = max(1, int(length))
    longest: int = 0
    current: int = 0
    for step in range(steps + 1):
        # the point on the first segment and its distance to the nearest point of the second one:
        x: float = x_0 + (x_1 - x_0) * step / steps
        y: float = y_0 + (y_1 - y_0) * step / steps
        d_x, d_y = b_x - a_x, b_y - a_y
        squared: float = d_x * d_x + d_y * d_y
        t: float = (
            0.0
            if squared == 0
            else max(0.0, min(1.0, ((x - a_x) * d_x + (y - a_y) * d_y) / squared))
        )
        near: bool = math.hypot(x - a_x - t * d_x, y - a_y - t * d_y) <= 2
        current = current + 1 if near else 0
        longest = max(longest, current)
    return longest * length / steps


def line_heights(root: ET.Element) -> list[float]:
    """Returns the height of each level's line, in the order the levels are drawn."""
    return [
        float(next(group.iter(f"{SVG}line")).get("y1", ""))
        for group in groups(root, "level")
    ]


class SlideTreeTest(unittest.TestCase):
    """The trees of slides 22 and 23: the input row 3,4 6,2 9,4 8,7 5,6 3,1 1,4 6,7 with M = 4 and F = 2."""

    def test_slide_22_runs_and_pages(self) -> None:
        """The tree of slide 22 draws the input as 8 pages in its order, the 4 runs of phase 0 at level 0 with 2 pages
        each, the 2 merges' outputs (runs 4 and 5) at level 1 with 4 pages each, and the result of the final merge at
        level 2 with 8 pages, two values per page.

        Would fail if a run were drawn twice or not at all, at the wrong level, or with its values split into pages
        other than the slides' pages of two.
        """
        root: ET.Element = parse(SLIDE_22)
        # the input row, in the input's order:
        self.assertEqual(
            ["3,4", "6,2", "9,4", "8,7", "5,6", "3,1", "1,4", "6,7"],
            labels(groups(root, "input")[0]),
        )
        # one group per run written, with its number, level and pages:
        self.assertEqual(
            [
                ("0", "0", ["2,3", "4,6"]),
                ("1", "0", ["4,7", "8,9"]),
                ("2", "0", ["1,3", "5,6"]),
                ("3", "0", ["1,4", "6,7"]),
                ("4", "1", ["2,3", "4,4", "6,7", "8,9"]),
                ("5", "1", ["1,1", "3,4", "5,6", "6,7"]),
            ],
            drawn_runs(root),
        )
        # the result at level 2:
        result: ET.Element = groups(root, "result")[0]
        self.assertEqual("2", result.get("data-level"))
        self.assertEqual(
            ["1,1", "2,3", "3,4", "4,4", "5,6", "6,6", "7,7", "8,9"], labels(result)
        )

    def test_slide_22_arrows(self) -> None:
        """The tree of slide 22 has 4 arrows from the input to the runs of phase 0, 2 into each merge's output (runs 0
        and 1 into run 4, runs 2 and 3 into run 5) and 2 into the result (from runs 4 and 5).

        Would fail if an arrow led from a merge's input to another merge's output, or if the final merge's arrows led
        to a run instead of the result.
        """
        self.assertCountEqual(
            [
                ("input", "0"),
                ("input", "1"),
                ("input", "2"),
                ("input", "3"),
                ("0", "4"),
                ("1", "4"),
                ("2", "5"),
                ("3", "5"),
                ("4", "result"),
                ("5", "result"),
            ],
            arrows(parse(SLIDE_22)),
        )

    def test_slide_23_has_only_the_final_merge(self) -> None:
        """The tree of slide 23 draws the 2 runs of replacement selection at level 0 with 4 pages each, and only the
        final merge: 2 arrows from the input, 2 into the result at level 1, none into a run of a merge.

        Would fail if the final merge were drawn as a merge that writes a run.
        """
        root: ET.Element = parse(SLIDE_23)
        # the two runs of phase 0, nothing else written:
        self.assertEqual(
            [
                ("0", "0", ["2,3", "4,4", "6,7", "8,9"]),
                ("1", "0", ["1,1", "3,4", "5,6", "6,7"]),
            ],
            drawn_runs(root),
        )
        # arrows from the input and into the result only, which is at level 1:
        self.assertCountEqual(
            [("input", "0"), ("input", "1"), ("0", "result"), ("1", "result")],
            arrows(root),
        )
        self.assertEqual("1", groups(root, "result")[0].get("data-level"))


class LevelTest(unittest.TestCase):
    """The levels of a tree (the slides' passes), each a line with the label ``PASS k`` above its runs."""

    def test_levels_from_top_to_bottom(self) -> None:
        """A tree has one level per pass, from 0 to the final merge's level (2 for slide 22, 1 for slide 23, 3 for 20
        ascending values), labelled ``PASS 0``, ``PASS 1``, ... and drawn from top to bottom in this order.

        Would fail if the final merge's level were left out, or the levels were drawn out of order.
        """
        for counts, final in ((SLIDE_22, 2), (SLIDE_23, 1), (TWENTY, 3)):
            with self.subTest(final_level=final):
                root: ET.Element = parse(counts)
                levels: list[ET.Element] = groups(root, "level")
                # one level per pass, labelled with its number:
                self.assertEqual(
                    [str(level) for level in range(final + 1)],
                    [group.get("data-level") for group in levels],
                )
                self.assertEqual(
                    [f"PASS {level}" for level in range(final + 1)],
                    [group.findtext(f"{SVG}text") for group in levels],
                )
                # each line below the one before:
                heights: list[float] = line_heights(root)
                self.assertEqual(sorted(set(heights)), heights)

    def test_twenty_ascending_levels(self) -> None:
        """20 ascending values (M = 4, F = 2, quicksort): runs 0 to 4 at level 0, the merges' outputs 5 and 6 at level 1
        and 7 at level 2, the result at level 3; run 7 is merged from run 4 and run 5, the result from runs 6 and 7.

        Would fail if a run's level were taken from the number of merges before it instead of the merge's inputs.
        """
        root: ET.Element = parse(TWENTY)
        # the runs and their levels:
        self.assertEqual(
            [("0", "0"), ("1", "0"), ("2", "0"), ("3", "0"), ("4", "0")]
            + [("5", "1"), ("6", "1"), ("7", "2")],
            [(number, level) for number, level, _ in drawn_runs(root)],
        )
        self.assertEqual("3", groups(root, "result")[0].get("data-level"))
        # the arrows into run 7 and into the result:
        self.assertCountEqual(
            [("4", "7"), ("5", "7")],
            [arrow for arrow in arrows(root) if arrow[1] == "7"],
        )
        self.assertCountEqual(
            [("6", "result"), ("7", "result")],
            [arrow for arrow in arrows(root) if arrow[1] == "result"],
        )

    def test_each_run_is_drawn_within_its_level(self) -> None:
        """Every page of a run lies below the line of the run's level and above the line of the next level; the pages
        of the result lie below the line of the final level.

        Would fail if a merge's output were drawn at the level of one of its inputs.
        """
        for name, counts in LAYOUT_CASES.items():
            with self.subTest(case=name):
                root: ET.Element = parse(counts)
                heights: list[float] = line_heights(root) + [
                    float(root.get("height", ""))
                ]
                # each run between its level's line and the next:
                for group in groups(root, "run"):
                    level: int = int(group.get("data-level", ""))
                    for box in boxes(group):
                        self.assertGreater(box.top, heights[level])
                        self.assertLess(box.bottom, heights[level + 1])
                # the result below the last line:
                for box in boxes(groups(root, "result")[0]):
                    self.assertGreater(box.top, heights[-2])


class ResultTest(unittest.TestCase):
    """The result of the final merge, which is not written."""

    def test_result_pages_are_dashed_and_hold_the_sorted_output(self) -> None:
        """The result's pages hold the sorted output in pages of two and are dashed, with the label ``result (not
        written)``; the pages of the input and of the runs are not dashed.

        Would fail if the result were drawn as a written run, or held another run than the output.
        """
        root: ET.Element = parse(SLIDE_22)
        result: ET.Element = groups(root, "result")[0]
        # the sorted output, in pages of two, and the label:
        self.assertEqual(page_labels(sorted(SLIDES)), labels(result))
        self.assertIn(
            "result (not written)", [text.text for text in result.iter(f"{SVG}text")]
        )
        # dashed pages for the result only:
        dashed: list[str] = [
            group.get("class", "")
            for group in root.iter(f"{SVG}g")
            for rect in group.findall(f"{SVG}rect")
            if rect.get("stroke-dasharray") is not None
        ]
        self.assertEqual(["result"] * 8, dashed)


class RecordedMergesTest(unittest.TestCase):
    """The runs and arrows drawn are those of the runs and merges :func:`sort_counted` recorded."""

    def test_runs_and_arrows_are_those_recorded(self) -> None:
        """In every layout case, the runs drawn are the runs written, those of phase 0 and then the merges' outputs,
        each with its number, its level and its elements in pages of two; one arrow leads from the input to each run
        of phase 0, one from each input run of a merge to the merge's output, and one from each input run of the
        final merge to the result.

        Would fail if an arrow led from a run its merge did not read, or to another merge's output, or if a run
        written or an arrow were left out.
        """
        for name, counts in LAYOUT_CASES.items():
            with self.subTest(case=name):
                root: ET.Element = parse(counts)
                # the runs written, in the order they were made, with their numbers, levels and pages:
                written: list[Run[int]] = [*counts.runs] + [
                    merge.output for merge in counts.merges
                ]
                self.assertEqual(
                    [
                        (str(run.number), str(run.level), page_labels(run.elements))
                        for run in written
                    ],
                    drawn_runs(root),
                )
                # an arrow into every run of phase 0, and one from every input run of a merge into its output:
                expected: list[tuple[str, str]] = [
                    ("input", str(run.number)) for run in counts.runs
                ] + [
                    (
                        str(run.number),
                        (
                            str(merge.output.number)
                            if isinstance(merge, Merge)
                            else "result"
                        ),
                    )
                    for merge in (*counts.merges, counts.final_merge)
                    for run in merge.inputs
                ]
                self.assertCountEqual(expected, arrows(root))

    def test_a_merge_of_runs_that_lie_far_apart(self) -> None:
        """In the tree of 39 ascending values (M = 4, F = 3, quicksort), the runs of phase 0 are drawn from left to
        right in the order 0 to 9, and the first merge reads run 9, the rightmost, and runs 0 and 1, the leftmost:
        their three arrows lead into run 10 at level 1. Runs 2-4 and 5-7 lead into runs 11 and 12 at level 1, runs 8
        and 10 into run 13 at level 2, and runs 11, 12 and 13 into the result at level 3. Arrows of this tree may
        cross; that every arrow keeps 10 pixels away from the boxes it passes is checked for this tree too, by the
        layout tests over ``LAYOUT_CASES``.

        Would fail if a merge's arrows were drawn from neighbouring runs instead of the runs it read, or if the arrow
        of the run at the far end of the row were left out or led into another run.
        """
        root: ET.Element = parse(FAR_APART)
        # the runs of phase 0 from left to right:
        lefts: list[tuple[float, str]] = sorted(
            (boxes(group)[0].left, group.get("data-run", ""))
            for group in groups(root, "run")
            if group.get("data-level") == "0"
        )
        self.assertEqual(
            [str(number) for number in range(10)], [number for _, number in lefts]
        )
        # the merges' outputs and the result, with their levels:
        self.assertEqual(
            [("10", "1"), ("11", "1"), ("12", "1"), ("13", "2")],
            [(number, level) for number, level, _ in drawn_runs(root)[10:]],
        )
        self.assertEqual("3", groups(root, "result")[0].get("data-level"))
        # the runs whose arrows lead into each merge's output and into the result:
        sources: dict[str, list[str]] = {}
        for source, target in arrows(root):
            if source != "input":
                sources.setdefault(target, []).append(source)
        self.assertEqual(
            {
                "10": ["0", "1", "9"],
                "11": ["2", "3", "4"],
                "12": ["5", "6", "7"],
                "13": ["8", "10"],
                "result": ["11", "12", "13"],
            },
            {target: sorted(runs, key=int) for target, runs in sources.items()},
        )

    def test_a_single_run_with_both_run_generations(self) -> None:
        """A sort that makes a single run is drawn with the levels 0 and 1 only: run 0 at level 0 and the result at
        level 1 right below it, both holding the values sorted, one arrow from the input into run 0 and one from run 0
        into the result; for one value with both run generations, for 3 values that fit into M = 4 (quicksort), and for
        10 sorted values that replacement selection writes into one run longer than M.

        Would fail if the final merge of a single run were drawn as a merge that writes a run, or if the result were
        not placed below its only input run.
        """
        cases: dict[str, SortCounts[int]] = {
            "one value, quicksort": sort_counted((5,), 4, 2, False),
            "one value, replacement selection": sort_counted((5,), 4, 2, True),
            "3 values, quicksort": sort_counted((3, 1, 2), 4, 2, False),
            "10 sorted values, replacement selection": sort_counted(
                range(10), 4, 2, True
            ),
        }
        for name, counts in cases.items():
            with self.subTest(case=name):
                root: ET.Element = parse(counts)
                pages: list[str] = page_labels(sorted(counts.values))
                result: ET.Element = groups(root, "result")[0]
                # the levels 0 and 1, run 0 at level 0 and the result at level 1, both holding the values sorted:
                self.assertEqual(
                    ["0", "1"],
                    [group.get("data-level") for group in groups(root, "level")],
                )
                self.assertEqual([("0", "0", pages)], drawn_runs(root))
                self.assertEqual(
                    ("1", pages), (result.get("data-level"), labels(result))
                )
                # one arrow into run 0 and one from run 0 into the result:
                self.assertEqual([("input", "0"), ("0", "result")], arrows(root))
                # the result's pages below run 0's, in the same column:
                run_boxes: list[Box] = boxes(run_group(root, "0"))
                result_boxes: list[Box] = boxes(result)
                self.assertEqual(run_boxes[0].left, result_boxes[0].left)
                self.assertGreater(result_boxes[0].top, run_boxes[-1].bottom)


class LayoutTest(unittest.TestCase):
    """Where the parts of a tree are drawn."""

    def test_no_boxes_overlap_and_no_arrow_passes_through_a_box(self) -> None:
        """No two page boxes overlap, and no arrow passes straight down through a page box on its way to the level of
        its merge, also where an arrow passes down through a level to a later merge.

        Would fail if a merge's output were placed where the column of another run is, or where an arrow to a later
        merge passes down.
        """
        for name, counts in LAYOUT_CASES.items():
            with self.subTest(case=name):
                root: ET.Element = parse(counts)
                every_box: list[Box] = boxes(root)
                # no two boxes overlap:
                for index, box in enumerate(every_box):
                    for other in every_box[index + 1 :]:
                        self.assertFalse(box.overlaps(other), f"{box} and {other}")
                # the straight part of each arrow, from its start down to its bend, misses every box:
                for arrow in groups(root, "arrow"):
                    (x, start), (_, bend) = points(arrow)[:2]
                    for box in every_box:
                        self.assertFalse(
                            box.left < x < box.right
                            and start < box.bottom
                            and box.top < bend,
                            f"arrow {arrow.attrib} through {box}",
                        )

    def test_arrows_keep_clear_of_the_boxes_they_pass(self) -> None:
        """Every arrow keeps at least 10 pixels away from every page box but those of the run (or input row) it comes
        from and the run (or result) it leads to, also where it passes down beside a column or over the columns
        next to its target.

        Would fail if an arrow passing down to a later merge ran along the edge of a column, if the end of an arrow
        came in flat over the neighbouring columns of its target, or if an arrow bent too close under the columns of
        the level above.
        """
        for name, counts in LAYOUT_CASES.items():
            with self.subTest(case=name):
                root: ET.Element = parse(counts)
                run_boxes: dict[str, list[Box]] = {
                    group.get("data-run", ""): boxes(group)
                    for group in groups(root, "run")
                }
                run_boxes["result"] = boxes(groups(root, "result")[0])
                run_boxes["input"] = boxes(groups(root, "input")[0])
                for arrow in groups(root, "arrow"):
                    # the boxes of everything but the arrow's own source and target:
                    own: set[str] = {
                        arrow.get("data-from", ""),
                        arrow.get("data-to", ""),
                    }
                    others: list[Box] = [
                        box
                        for key, group_boxes in run_boxes.items()
                        if key not in own
                        for box in group_boxes
                    ]
                    # the points along the arrow's line, one pixel apart, that come closer than 10 pixels to them:
                    line: list[tuple[float, float]] = points(arrow)
                    too_close: list[tuple[float, float]] = []
                    for (x_0, y_0), (x_1, y_1) in zip(line, line[1:]):
                        steps: int = max(1, int(max(abs(x_1 - x_0), abs(y_1 - y_0))))
                        for step in range(steps + 1):
                            x: float = x_0 + (x_1 - x_0) * step / steps
                            y: float = y_0 + (y_1 - y_0) * step / steps
                            if any(box.gap(x, y) < 10 for box in others):
                                too_close.append((round(x, 1), round(y, 1)))
                    self.assertEqual([], too_close, f"arrow {arrow.attrib}")

    def test_slanted_parts_keep_clear_of_the_levels(self) -> None:
        """The slanted part of every arrow between runs starts at least 10 pixels below the lowest box above the line
        of its merge's level and ends at least 10 pixels above the boxes of that level, so that it stays clear of
        both, whatever runs lie next to its way.

        Would fail if the arrows bent closer under the level above (less room above a level's line) or turned
        straight down closer above their target (a shorter straight end).
        """
        for name, counts in LAYOUT_CASES.items():
            with self.subTest(case=name):
                root: ET.Element = parse(counts)
                every_box: list[Box] = boxes(root)
                for arrow in groups(root, "arrow"):
                    if arrow.get("data-from") == "input":
                        continue
                    # the slanted part: from where the arrow leaves its straight way down to where it turns down:
                    (_, start), (_, end) = points(arrow)[-3:-1]
                    # the boxes above and below the line between them:
                    line: float = next(
                        height for height in line_heights(root) if start < height < end
                    )
                    above: float = max(
                        box.bottom for box in every_box if box.bottom < line
                    )
                    below: float = min(box.top for box in every_box if box.top > line)
                    self.assertGreaterEqual(start - above, 10, arrow.attrib)
                    self.assertGreaterEqual(below - end, 10, arrow.attrib)

    def test_no_two_arrows_lie_on_top_of_each_other(self) -> None:
        """In the trees shown to readers (the notebook's small example with both run generations and the preview's
        examples), no part of an arrow lies within 2 pixels of another arrow for 12 pixels or more: arrows may cross
        at a clear angle, but never run on top of each other.

        Would fail for data on which the code merges runs that are far apart, e.g. 39 ascending values with M = 4 and
        F = 3, whose first merge reads the short last run and the first two runs: the arrows of runs 0 and 1 then run
        on top of each other for about 66 pixels.
        """
        for name, counts in EXAMPLE_CASES.items():
            with self.subTest(case=name):
                # every merge in the examples reads at least three runs:
                self.assertEqual(
                    [],
                    [
                        len(merge.inputs)
                        for merge in (*counts.merges, counts.final_merge)
                        if len(merge.inputs) < 3
                    ],
                )
                # every pair of segments of two different arrows shares less than 12 pixels:
                lines: list[list[tuple[float, float]]] = [
                    points(arrow) for arrow in groups(parse(counts), "arrow")
                ]
                shared: list[float] = [
                    round(overlapping_stretch(first, second), 1)
                    for index, line in enumerate(lines)
                    for other in lines[index + 1 :]
                    for first in zip(line, line[1:])
                    for second in zip(other, other[1:])
                    if overlapping_stretch(first, second) >= 12
                ]
                self.assertEqual([], shared)
        # the check finds arrows on top of each other where they are: in the tree of 39 ascending values, whose first
        # merge reads runs that lie far apart, the arrows of runs 0 and 1 share a long stretch:
        far_apart: list[list[tuple[float, float]]] = [
            points(arrow) for arrow in groups(parse(FAR_APART), "arrow")
        ]
        self.assertGreaterEqual(
            max(
                overlapping_stretch(first, second)
                for index, line in enumerate(far_apart)
                for other in far_apart[index + 1 :]
                for first in zip(line, line[1:])
                for second in zip(other, other[1:])
            ),
            60,
        )

    def test_arrows_start_below_their_source_and_end_above_their_target(self) -> None:
        """Each arrow starts just below the run it comes from (or the input row), in the middle of the run's column,
        and its head ends just above the first page of the run it leads to (or the result), on that page.

        Would fail if an arrow's ``data-from`` or ``data-to`` named another run than the one it is drawn between.
        """
        for name, counts in LAYOUT_CASES.items():
            with self.subTest(case=name):
                root: ET.Element = parse(counts)
                for arrow in groups(root, "arrow"):
                    # the pages of what the arrow comes from and leads to:
                    source_name: str = arrow.get("data-from", "")
                    target_name: str = arrow.get("data-to", "")
                    source: list[Box] = boxes(
                        groups(root, "input")[0]
                        if source_name == "input"
                        else run_group(root, source_name)
                    )
                    target: Box = boxes(
                        groups(root, "result")[0]
                        if target_name == "result"
                        else run_group(root, target_name)
                    )[0]
                    # the start: just below the source, in the middle of its column (any column below the input):
                    start_x, start_y = points(arrow)[0]
                    below: float = start_y - max(box.bottom for box in source)
                    self.assertTrue(0 < below <= 5, f"{below} px below {source_name}")
                    if source_name != "input":
                        self.assertAlmostEqual(
                            (source[0].left + source[0].right) / 2, start_x, delta=0.1
                        )
                    # the end: just above the target's first page, on that page:
                    end_x, end_y = points(arrow)[-1]
                    above: float = target.top - end_y
                    self.assertTrue(0 < above <= 5, f"{above} px above {target_name}")
                    self.assertTrue(
                        target.left < end_x < target.right,
                        f"{end_x} beside {target_name}'s page {target}",
                    )

    def test_arrows_into_one_run_end_side_by_side(self) -> None:
        """The arrows into one run (or into the result) end side by side on its top, from left to right in the order
        of the columns they come from, at least 7 px apart, the width of an arrow head (3.5 px to either side of its
        line), so that their heads do not overlap; also for a final merge of 5 runs (40 ascending values, M = 6,
        F = 5, quicksort).

        Would fail if the heads of one merge's arrows met in one point, if two arrows crossed just above the run, or
        if the heads were closer together than a head is wide.
        """
        cases: dict[str, SortCounts[int]] = {
            **LAYOUT_CASES,
            "40 ascending, quicksort, M = 6, F = 5": sort_counted(
                range(40), 6, 5, False
            ),
        }
        for name, counts in cases.items():
            with self.subTest(case=name):
                # where every arrow starts and ends, horizontally, by what it leads to:
                ends: dict[str, list[tuple[float, float]]] = {}
                for arrow in groups(parse(counts), "arrow"):
                    line: list[tuple[float, float]] = points(arrow)
                    ends.setdefault(arrow.get("data-to", ""), []).append(
                        (line[0][0], line[-1][0])
                    )
                # in the order of their starts, the ends of the arrows into one run lie a head's width apart or more:
                for target, starts_and_ends in ends.items():
                    ordered: list[float] = [end for _, end in sorted(starts_and_ends)]
                    gaps: list[float] = [
                        right - left for left, right in zip(ordered, ordered[1:])
                    ]
                    self.assertEqual(
                        [],
                        [round(gap, 1) for gap in gaps if gap < 7 - 0.1],
                        f"gaps between the arrows into {target}",
                    )

    def test_every_part_lies_inside_the_drawing(self) -> None:
        """Every page box, every text, every point of an arrow and every level's line lies inside the SVG's width and
        height, each tree drawn without and with a title, also for the empty input. A text's extent is estimated with
        ``TEXT_CHARACTER_WIDTH`` per character (``TITLE_CHARACTER_WIDTH`` for the bold title), from its anchor to the
        right (``start``), to both sides (``middle``) or to the left (``end``).

        Would fail if the drawing were cut off at the bottom or the right, e.g. if its height ignored a label below the
        lowest page, or its width the label of the result or a long title.
        """
        cases: dict[str, SortCounts[int]] = {
            **LAYOUT_CASES,
            "empty input": sort_counted((), 4, 2, False),
            # each case's name is drawn as its title, so a long name checks a long title:
            "one value, with a title wider than the tree and its result's label": sort_counted(
                (5,), 4, 2, False
            ),
        }
        # the part of a text's estimated width left and right of its anchor, by its text-anchor:
        sides: dict[str, tuple[float, float]] = {
            "start": (0, 1),
            "middle": (-0.5, 0.5),
            "end": (-1, 0),
        }
        for name, counts in cases.items():
            for title in ("", name):
                with self.subTest(case=name, title=bool(title)):
                    root: ET.Element = parse(counts, title=title)
                    # the title's texts, which are bold:
                    bold: set[int] = {
                        id(text)
                        for group in groups(root, "title")
                        for text in group.iter(f"{SVG}text")
                    }
                    width: float = float(root.get("width", ""))
                    height: float = float(root.get("height", ""))
                    # both ends of the texts (x is bound once per text), the corners of the boxes, the ends of the
                    # lines and the arrows' points:
                    text_ends: list[tuple[float, float]] = [
                        (
                            x
                            + side
                            * (
                                TITLE_CHARACTER_WIDTH
                                if id(text) in bold
                                else TEXT_CHARACTER_WIDTH
                            )
                            * len(text.text or ""),
                            float(text.get("y", "")),
                        )
                        for text in root.iter(f"{SVG}text")
                        for x in [float(text.get("x", ""))]
                        for side in sides[text.get("text-anchor", "")]
                    ]
                    corners: list[tuple[float, float]] = [
                        corner
                        for box in boxes(root)
                        for corner in ((box.left, box.top), (box.right, box.bottom))
                    ]
                    lines: list[tuple[float, float]] = [
                        (float(line.get(f"x{end}", "")), float(line.get(f"y{end}", "")))
                        for line in root.iter(f"{SVG}line")
                        for end in (1, 2)
                    ]
                    arrow_points: list[tuple[float, float]] = [
                        point
                        for arrow in groups(root, "arrow")
                        for point in points(arrow)
                    ]
                    # every one of them inside the drawing:
                    outside: list[tuple[float, float]] = [
                        (x, y)
                        for x, y in text_ends + corners + lines + arrow_points
                        if not (0 <= x <= width and 0 <= y <= height)
                    ]
                    self.assertEqual([], outside, f"drawing of {width} × {height}")

    def test_empty_input(self) -> None:
        """The tree of the empty input has an input row without pages, the levels 0 and 1, a result at level 1
        without pages, no runs and no arrows, with both run generations and with pages of 1, 2 and 3 values.

        Would fail if the empty input were drawn with an empty page or run, or if the drawing failed on it, e.g. for
        a page size other than 2.
        """
        for selection in (False, True):
            for page_size in (1, 2, 3):
                with self.subTest(selection=selection, page_size=page_size):
                    root: ET.Element = parse(
                        sort_counted((), 4, 2, selection), page_size=page_size
                    )
                    # no pages, runs or arrows:
                    self.assertEqual([], boxes(root))
                    self.assertEqual([], drawn_runs(root))
                    self.assertEqual([], arrows(root))
                    # the levels 0 and 1, and the result at level 1:
                    self.assertEqual(
                        ["0", "1"],
                        [group.get("data-level") for group in groups(root, "level")],
                    )
                    self.assertEqual("1", groups(root, "result")[0].get("data-level"))


class SmallExampleTest(unittest.TestCase):
    """The small example of the notebook: 36 values, M = 4, F = 3, drawn with merges of three runs only."""

    def test_every_merge_reads_three_runs(self) -> None:
        """Quicksort makes 9 runs of 4, three merges of three runs at level 1 and a final merge of their three
        outputs at level 2; replacement selection makes 3 runs of 12, 13 and 11 values, read by the final merge at
        level 1. In both trees, three arrows lead into every merge's output and into the result.

        Would fail if the small example's input or the code's merge order changed so that a merge read only two runs,
        e.g. with 4 or 6 runs of phase 0, where the code's last merge before the final one takes two.
        """
        # quicksort: 9 runs of 4, merged 3 by 3, then a final merge of 3 runs:
        chunks: SortCounts[int] = SMALL_EXAMPLE_CHUNKS
        self.assertEqual((4,) * 9, chunks.run_lengths)
        self.assertEqual([3, 3, 3], [len(merge.inputs) for merge in chunks.merges])
        self.assertEqual((12, 12, 12), chunks.merge_outputs)
        self.assertEqual((3, 2), (chunks.final_fan_in, chunks.final_merge.level))
        # replacement selection: 3 runs, read by the final merge at level 1:
        selection: SortCounts[int] = SMALL_EXAMPLE_SELECTION
        self.assertEqual((12, 13, 11), selection.run_lengths)
        self.assertEqual(
            ((), 3, 1),
            (selection.merges, selection.final_fan_in, selection.final_merge.level),
        )
        # in both trees, three arrows into every merge's output and into the result:
        for counts in (chunks, selection):
            targets: Counter[str] = Counter(
                target for source, target in arrows(parse(counts)) if source != "input"
            )
            self.assertEqual({3}, set(targets.values()))
            self.assertEqual(len(counts.merges) + 1, len(targets))


class PageLabelsTest(unittest.TestCase):
    """Values split into pages, labelled as the slides write them."""

    def test_pages_of_two_the_last_shorter(self) -> None:
        """Values are split into pages of two, each labelled with its values separated by a comma; the last page
        holds the value left; no values give no pages.

        Would fail if the last, shorter page were dropped.
        """
        self.assertEqual(["2,3", "4,6", "1"], page_labels([2, 3, 4, 6, 1]))
        self.assertEqual(["2,3", "4,6"], page_labels((2, 3, 4, 6)))
        self.assertEqual([], page_labels(()))

    def test_other_page_sizes(self) -> None:
        """Pages of 3 hold three values each, the last one fewer; pages of 1 hold one value each.

        Would fail if the page size were fixed at two.
        """
        self.assertEqual(
            ["1,2,3", "4,5,6", "7"], page_labels((1, 2, 3, 4, 5, 6, 7), page_size=3)
        )
        self.assertEqual(["a", "b"], page_labels(("a", "b"), page_size=1))

    def test_page_size_below_1_is_rejected(self) -> None:
        """A page size of 0 or less raises a ValueError, in ``page_labels`` and in ``merge_tree_svg``.

        Would fail if the page size were not checked: a page size of −1 would then give no pages at all.
        """
        for page_size in (0, -1):
            with self.subTest(page_size=page_size):
                with self.assertRaises(ValueError):
                    page_labels((1, 2, 3), page_size)
                with self.assertRaises(ValueError):
                    merge_tree_svg(SLIDE_22, page_size=page_size)

    def test_tree_draws_pages_of_the_page_size(self) -> None:
        """With pages of 4, the tree of slide 22 draws the input as 4 pages, each run of phase 0 as one page, each
        merge's output and the result as 2 and 4 pages.

        Would fail if the drawing ignored the page size given.
        """
        root: ET.Element = parse(SLIDE_22, page_size=4)
        # the input and the runs in pages of 4:
        self.assertEqual(
            ["3,4,6,2", "9,4,8,7", "5,6,3,1", "1,4,6,7"],
            labels(groups(root, "input")[0]),
        )
        self.assertEqual(
            [
                ["2,3,4,6"],
                ["4,7,8,9"],
                ["1,3,5,6"],
                ["1,4,6,7"],
                ["2,3,4,4", "6,7,8,9"],
                ["1,1,3,4", "5,6,6,7"],
            ],
            [pages for _, _, pages in drawn_runs(root)],
        )
        # the result in pages of 4:
        self.assertEqual(
            ["1,1,2,3", "3,4,4,4", "5,6,6,6", "7,7,8,9"],
            labels(groups(root, "result")[0]),
        )


class TitleAndEscapingTest(unittest.TestCase):
    """The title of a tree and the escaping of its texts."""

    def test_values_and_title_are_escaped(self) -> None:
        """Values with ``<``, ``>``, ``&`` and ``"`` and a title with them are escaped in the SVG, which still parses,
        and read back unchanged: in the pages of the input, the runs and the result, in the title above the tree, in
        the SVG's ``<title>`` and in its ``aria-label``.

        Would fail if a value or the title were written into the SVG unescaped: the SVG would not parse, or the
        ``aria-label`` attribute would end at the title's quote.
        """
        title: str = 'Merge <b>& "tree"'
        counts: SortCounts[str] = sort_counted(("b&", "a<", '"c', "d>"), 3, 2, False)
        svg: str = merge_tree_svg(counts, title=title)
        # the escaped forms in the SVG:
        for escaped in ("a&lt;", "b&amp;", "&quot;c", "d&gt;", "&lt;b&gt;&amp;"):
            self.assertIn(escaped, svg)
        # read back unchanged: the values in the pages:
        root: ET.Element = ET.fromstring(svg)
        self.assertEqual(["b&,a<", '"c,d>'], labels(groups(root, "input")[0]))
        self.assertEqual(
            [("0", "0", ['"c,a<', "b&"]), ("1", "0", ["d>"])], drawn_runs(root)
        )
        self.assertEqual(['"c,a<', "b&,d>"], labels(groups(root, "result")[0]))
        # and the title, in all three places:
        self.assertEqual(
            [title, title, title],
            [
                groups(root, "title")[0].findtext(f"{SVG}text"),
                root.findtext(f"{SVG}title"),
                root.get("aria-label"),
            ],
        )

    def test_without_a_title_the_drawing_is_labelled_merge_tree(self) -> None:
        """Without a title, no title is drawn above the tree, and the SVG's ``<title>`` and ``aria-label`` say
        ``merge tree``.

        Would fail if a screen reader got an empty label for a tree without a title.
        """
        root: ET.Element = parse(SLIDE_22)
        self.assertEqual([], groups(root, "title"))
        self.assertEqual(
            ["merge tree", "merge tree"],
            [root.findtext(f"{SVG}title"), root.get("aria-label")],
        )

    def test_markup_in_values_and_title_is_escaped_with_pages_of_1_and_3(self) -> None:
        """Values whose text (``str``) is markup with ``<``, ``>``, ``&``, ``'`` and ``"``, and a title with all of
        them, are escaped with pages of 1 and of 3 values: the SVG parses, holds no element but those the tree is
        drawn with, and reads back the values' texts on the pages of the input, the runs and the result, and the
        title above the tree, in the SVG's ``<title>`` and in its ``aria-label``.

        Would fail if a page's label or the title were written unescaped: the values' ``<b>`` and the title's ``<i>``
        would become elements of the SVG, and the bare ``&`` would keep it from parsing.
        """
        title: str = 'Tom\'s <i>tree</i> & "runs"'
        values: tuple[Markup, ...] = tuple(Markup(key) for key in (3, 1, 2, 5, 4))
        counts: SortCounts[Markup] = sort_counted(values, 3, 2, False)
        for page_size in (1, 3):
            with self.subTest(page_size=page_size):
                svg: str = merge_tree_svg(counts, page_size=page_size, title=title)
                root: ET.Element = ET.fromstring(svg)
                # the escaped forms in the SVG, and only the elements the tree is drawn with:
                self.assertIn("&lt;b&gt;3&lt;/b&gt;&amp;", svg)
                self.assertIn("&lt;i&gt;tree&lt;/i&gt; &amp;", svg)
                self.assertEqual(
                    {
                        f"{SVG}{tag}"
                        for tag in (
                            "svg",
                            "title",
                            "g",
                            "text",
                            "rect",
                            "line",
                            "polyline",
                            "polygon",
                        )
                    },
                    {element.tag for element in root.iter()},
                )
                # the values' texts read back on the pages of the input, the runs and the result:
                self.assertEqual(
                    page_labels(values, page_size), labels(groups(root, "input")[0])
                )
                self.assertEqual(
                    [page_labels(run.elements, page_size) for run in counts.runs],
                    [pages for _, _, pages in drawn_runs(root)],
                )
                self.assertEqual(
                    page_labels(sorted(values), page_size),
                    labels(groups(root, "result")[0]),
                )
                # the title read back in all three places:
                self.assertEqual(
                    [title, title, title],
                    [
                        groups(root, "title")[0].findtext(f"{SVG}text"),
                        root.findtext(f"{SVG}title"),
                        root.get("aria-label"),
                    ],
                )
        # a page of one value holds its text, a page of three values joins their texts with commas:
        self.assertEqual(["<b>3</b>&'\""], page_labels(values[:1], 1))
        self.assertEqual(
            ["<b>3</b>&'\",<b>1</b>&'\",<b>2</b>&'\""], page_labels(values[:3], 3)
        )


class SizeLimitTest(unittest.TestCase):
    """Trees are drawn for at most 40 input values."""

    def test_at_most_40_values_are_drawn(self) -> None:
        """41 values raise a ValueError; 40 values are drawn, with 20 input pages and 10 runs of phase 0 (M = 4).

        Would fail if the limit were off by one in either direction.
        """
        with self.assertRaisesRegex(ValueError, "at most 40 values, got 41"):
            merge_tree_svg(sort_counted(range(41), 4, 2, False))
        # 40 values: all of the input and all runs drawn:
        root: ET.Element = parse(sort_counted(range(40), 4, 2, False))
        self.assertEqual(20, len(labels(groups(root, "input")[0])))
        self.assertEqual(10, len([run for run in drawn_runs(root) if run[1] == "0"]))

    def test_the_limit_counts_values_for_pages_of_1_and_3(self) -> None:
        """The limit, MAX_VALUES = 40, counts values, not pages: with pages of 1 and of 3 values, 40 values are drawn
        on 40 and 14 input pages, with every value in the input row and in the result, and 41 values raise a
        ValueError whose message names the limit and the number of values given.

        Would fail if the limit counted pages, so that it allowed more values on larger pages or fewer on smaller ones.
        """
        self.assertEqual(40, MAX_VALUES)
        for page_size, input_pages in ((1, 40), (3, 14)):
            with self.subTest(page_size=page_size):
                # 40 values: every one of them in the input row and in the result:
                root: ET.Element = parse(
                    sort_counted(range(40), 4, 2, False), page_size=page_size
                )
                drawn: list[str] = labels(groups(root, "input")[0])
                self.assertEqual(input_pages, len(drawn))
                self.assertEqual(page_labels(range(40), page_size), drawn)
                self.assertEqual(
                    page_labels(range(40), page_size), labels(groups(root, "result")[0])
                )
                # 41 values: rejected, with the limit and the number given in the message:
                with self.assertRaisesRegex(
                    ValueError,
                    r"^the merge tree is drawn for at most 40 values, got 41$",
                ):
                    merge_tree_svg(
                        sort_counted(range(41), 4, 2, False), page_size=page_size
                    )


class ThemeTest(unittest.TestCase):
    """Trees read on light and dark pages alike."""

    def test_no_fixed_colours(self) -> None:
        """Every fill and stroke of a tree, title included, either follows the colour of the surrounding text
        (``currentColor``), is ``none``, or is an rgba colour that is neither close to black (all channels below 40)
        nor close to white (all above 215); every fill in rgba is a translucent tint, with an alpha of at most 0.5.
        Every text is filled with ``currentColor``, and no style sets a colour or a background.

        Would fail if a part were drawn in black or white, even slightly transparent, which disappears on a page of
        that colour, or if a page were filled with an opaque colour, which hides the text on a dark page.
        """
        root: ET.Element = parse(SLIDE_22, title="Quicksort (slide 22)")
        # every fill and stroke used, with the attribute that sets it:
        colours: set[tuple[str, str]] = {
            (attribute, element.get(attribute, ""))
            for element in root.iter()
            for attribute in ("fill", "stroke")
            if element.get(attribute) is not None
        }
        # none of them a fixed colour, black or white, or an opaque fill:
        fixed: list[tuple[str, str]] = []
        for attribute, colour in colours:
            if colour in ("currentColor", "none"):
                continue
            match: re.Match[str] | None = RGBA.fullmatch(colour)
            if match is None:
                fixed.append((attribute, colour))
                continue
            channels: list[int] = [int(channel) for channel in match.group(1, 2, 3)]
            near_black_or_white: bool = max(channels) < 40 or min(channels) > 215
            opaque_fill: bool = attribute == "fill" and float(match.group(4)) > 0.5
            if near_black_or_white or opaque_fill:
                fixed.append((attribute, colour))
        self.assertEqual([], fixed)
        # the texts follow the text colour, and no style sets a colour:
        self.assertEqual(
            {"currentColor"}, {text.get("fill") for text in root.iter(f"{SVG}text")}
        )
        self.assertEqual(
            [],
            [
                style
                for element in root.iter()
                if (style := element.get("style")) is not None
                and ("color" in style or "background" in style)
            ],
        )


if __name__ == "__main__":
    unittest.main()
