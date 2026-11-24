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

"""The merge tree of one external merge sort, drawn as inline SVG as on the slides of lecture 09b (22 and 23).

The input is a row of pages at the top. Below it, each level (the slides' pass) starts with a line labelled
``PASS k``; the runs of the level are columns of pages, and arrows lead from each merge's input runs to its output
run. The final merge writes no run: its arrows lead to the result, drawn with dashed pages. Everything is drawn from
the runs and merges :func:`sort_counted` recorded, so the tree shows what :class:`ExternalMergeSort` did.

The drawing sets no fixed text colour: text, outlines and arrows use the colour of the surrounding text
(``currentColor``), and the pages are filled with translucent tints, so it reads on light and dark pages alike.
Every value is escaped. Each part carries a ``class`` and ``data-*`` attributes that name what it shows, so that
tests can read the tree's structure from the SVG.
"""

from __future__ import annotations

import html
import math
from collections.abc import Sequence
from dataclasses import dataclass

from system.playground.sort_counting import FinalMerge, Merge, Run, SortCounts
from system.query_processing.sorting import Comparable

# the most input values the tree is drawn for; larger trees do not fit on a screen:
MAX_VALUES: int = 40

# sizes in pixels: a page's height and least width, the room beside a page's text (both sides together), the width of
# one character of a text, the height of a text's baseline above the bottom of its page or row:
PAGE_HEIGHT: int = 20
MIN_PAGE_WIDTH: int = 34
PAGE_PADDING: int = 12
CHARACTER_WIDTH: float = 7.5
BASELINE: int = 6
# the gap between the input's pages, the least gap between columns of runs, the least distance between a column
# and an arrow that passes down beside it, and how far above its target an arrow turns straight down, so that its
# slanted part stays at least that far above the tops of the columns next to its target:
INPUT_GAP: int = 6
COLUMN_GAP: int = 26
ARROW_CLEARANCE: int = 14
ARROW_END: int = 10
# the distance between the ends of neighbouring arrows into one run, a little more than an arrow head is wide:
ARROW_END_GAP: float = 8.0
# an arrow's head: its length along the arrow and half its width; the gap between an arrow and the page it starts
# below or ends above:
ARROW_HEAD_LENGTH: float = 7.0
ARROW_HEAD_HALF_WIDTH: float = 3.5
ARROW_GAP: int = 3
# the margin around the tree, the height of the title, the room between the title (or the top) and the input row:
MARGIN: int = 10
TITLE_HEIGHT: int = 22
ABOVE_INPUT: int = 16
# the room left of the tree for the labels of the levels and the input row; the label of the result, its gap to the
# result's pages, and the room right of the tree for gap, label and margin:
LABEL_WIDTH: int = 72
RESULT_LABEL: str = "result (not written)"
RESULT_LABEL_GAP: int = 8
RESULT_LABEL_ROOM: float = (
    RESULT_LABEL_GAP + CHARACTER_WIDTH * len(RESULT_LABEL) + MARGIN
)
# the width of one character of the title, which is bold and so wider than the other texts:
TITLE_CHARACTER_WIDTH: float = 9.0
# the space above a level's line and from the line to the level's runs:
ABOVE_LINE: int = 24
BELOW_LINE: int = 22

# translucent tints, which show light over a light page and dark over a dark one, and the outlines of the pages
# (dashed for the result, which is not written):
INPUT_STYLE: str = (
    'fill="rgba(255,152,0,0.35)" stroke="currentColor" stroke-opacity="0.5"'
)
RUN_STYLE: str = (
    'fill="rgba(66,133,244,0.30)" stroke="currentColor" stroke-opacity="0.5"'
)
RESULT_STYLE: str = (
    'fill="rgba(66,133,244,0.10)" stroke="currentColor" stroke-opacity="0.5" stroke-dasharray="3 2"'
)
LINE_COLOUR: str = "rgba(76,175,80,0.9)"


@dataclass(frozen=True)
class _Column:
    """Where a column of pages is drawn: the horizontal centre and the top of its first page."""

    centre: float
    top: float


@dataclass(frozen=True)
class _Levels:
    """Where the levels are drawn, from top to bottom: each level's line, then its runs."""

    # for each level: the height of its line and the top of its runs:
    line_y: tuple[float, ...]
    runs_top: tuple[float, ...]
    # the bottom of the lowest run:
    bottom: float


def page_labels(values: Sequence[object], page_size: int = 2) -> list[str]:
    """Splits values into pages of ``page_size`` values and returns each page's values separated by commas, as the
    slides write them (``2,3``). The last page holds the values left and may be shorter.

    @param values: the values, in their order
    @param page_size: the number of values on a page
    @return: one label per page
    @raise ValueError: if page_size is less than 1
    """
    if page_size < 1:
        raise ValueError(f"page_size must be at least 1, got {page_size}")
    return [
        ",".join(str(value) for value in values[start : start + page_size])
        for start in range(0, len(values), page_size)
    ]


def _written[ObjectType: Comparable](
    counts: SortCounts[ObjectType],
) -> list[Run[ObjectType]]:
    """Every run the sort wrote: those of phase 0, then the merges' outputs, in the order they were made.

    @param counts: what the sort did
    @return: the runs
    """
    return [*counts.runs] + [merge.output for merge in counts.merges]


def _page_width[ObjectType: Comparable](
    counts: SortCounts[ObjectType], page_size: int
) -> float:
    """The width of every page: what the widest label needs, at least :data:`MIN_PAGE_WIDTH`.

    @param counts: what the sort did
    @param page_size: the number of values on a page
    @return: the width
    """
    return max(
        [MIN_PAGE_WIDTH]
        + [
            CHARACTER_WIDTH * len(label) + PAGE_PADDING
            for values in [counts.values, counts.output]
            + [run.elements for run in _written(counts)]
            for label in page_labels(values, page_size)
        ]
    )


def _levels[ObjectType: Comparable](
    counts: SortCounts[ObjectType], page_size: int, input_top: float
) -> _Levels:
    """Places the levels below the input row: each level's line, then its runs, as high as its longest run (for the
    final merge's level, the result).

    @param counts: what the sort did
    @param page_size: the number of values on a page
    @param input_top: the top of the input row
    @return: where the levels are drawn
    """
    written: list[Run[ObjectType]] = _written(counts)
    line_y: list[float] = []
    runs_top: list[float] = []
    bottom: float = input_top + PAGE_HEIGHT
    for level in range(counts.final_merge.level + 1):
        lengths: list[int] = [
            len(run.elements) for run in written if run.level == level
        ]
        if level == counts.final_merge.level:
            # the result, at least one page high, so that its label fits even for an empty input:
            lengths.extend((len(counts.output), page_size))
        line_y.append(bottom + ABOVE_LINE)
        runs_top.append(line_y[-1] + BELOW_LINE)
        pages: int = max(
            (math.ceil(length / page_size) for length in lengths), default=0
        )
        bottom = runs_top[-1] + pages * PAGE_HEIGHT
    return _Levels(tuple(line_y), tuple(runs_top), bottom)


def _place(
    wanted: Sequence[float],
    obstacles: Sequence[float],
    distance: float,
    clearance: float,
) -> list[float]:
    """Places columns from left to right as near as possible to where they are wanted, at least ``distance`` right
    of the column before and at least ``clearance`` away from each obstacle (an arrow passing straight down).

    @param wanted: the wanted centres, in ascending order
    @param obstacles: the horizontal positions of the arrows passing down
    @param distance: the least distance between the centres of neighbouring columns
    @param clearance: the least distance between a column's centre and an obstacle
    @return: the centres, in the order of ``wanted``
    """
    placed: list[float] = []
    for centre in wanted:
        lowest: float = placed[-1] + distance if placed else -math.inf
        # the candidates: the wanted place (moved right of the column before if needed), and the places right next
        # to each obstacle, on its left and on its right; the place right of the rightmost obstacle is always free of
        # obstacles, so at least one candidate is allowed:
        candidates: list[float] = [max(centre, lowest)] + [
            obstacle + side * clearance for obstacle in obstacles for side in (-1, 1)
        ]
        placed.append(
            min(
                (abs(candidate - centre), candidate)
                for candidate in candidates
                if candidate >= lowest
                and all(
                    # with a little room for rounding, as a candidate next to an obstacle is exactly clearance away:
                    abs(candidate - obstacle) >= clearance - 1e-9
                    for obstacle in obstacles
                )
            )[1]
        )
    return placed


def _columns[ObjectType: Comparable](
    counts: SortCounts[ObjectType], levels: _Levels, width: float, input_width: float
) -> dict[int, _Column]:
    """Places the runs: those of phase 0 spread under the input row, each under about the pages it was made from;
    the output of a merge centred below its input runs, then moved aside if it would overlap another column or come
    closer than :data:`ARROW_CLEARANCE` to an arrow that passes down through its level to a later merge.

    @param counts: what the sort did
    @param levels: where the levels are drawn
    @param width: the width of a page
    @param input_width: the width of the input row
    @return: the column of every run written, by the run's number
    """
    columns: dict[int, _Column] = {}
    # the distance between the centres of neighbouring runs of phase 0: the input row's width shared among them, at
    # least a page and a gap:
    step: float = max(width + COLUMN_GAP, input_width / max(len(counts.runs), 1))
    for index, run in enumerate(counts.runs):
        columns[run.number] = _Column(
            LABEL_WIDTH + (index + 0.5) * step, levels.runs_top[0]
        )
    every_merge: list[Merge[ObjectType] | FinalMerge[ObjectType]] = [
        *counts.merges,
        counts.final_merge,
    ]
    for level in range(1, counts.final_merge.level):
        # where the arrows pass down through this level: those of runs of a lower level read by a merge of a higher
        # one:
        passing: list[float] = [
            columns[run.number].centre
            for merge in every_merge
            if merge.level > level
            for run in merge.inputs
            if run.level < level
        ]
        wanted: list[tuple[float, int]] = sorted(
            (
                sum(columns[run.number].centre for run in merge.inputs)
                / len(merge.inputs),
                merge.output.number,
            )
            for merge in counts.merges
            if merge.level == level
        )
        centres: list[float] = _place(
            [centre for centre, _ in wanted],
            passing,
            width + COLUMN_GAP,
            width / 2 + ARROW_CLEARANCE,
        )
        for (_, number), centre in zip(wanted, centres):
            columns[number] = _Column(centre, levels.runs_top[level])
    return columns


def _text(x: float, y: float, text: str, anchor: str = "start") -> str:
    """An SVG text element in the colour of the surrounding text, with its text escaped.

    @param x: the horizontal position of the anchor
    @param y: the baseline
    @param text: the text
    @param anchor: start, middle or end
    @return: the element
    """
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" fill="currentColor">'
        f"{html.escape(text)}</text>"
    )


def _page(label: str, left: float, top: float, width: float, style: str) -> str:
    """A page as a box with its label in the middle.

    @param label: the values on the page
    @param left: the left edge
    @param top: the top edge
    @param width: the width
    @param style: the attributes that set its fill and outline
    @return: the SVG elements
    """
    return (
        f'<rect class="page" x="{left:.1f}" y="{top:.1f}" width="{width:.1f}" height="{PAGE_HEIGHT}" {style}/>'
        + _text(left + width / 2, top + PAGE_HEIGHT - BASELINE, label, anchor="middle")
    )


def _column(labels: Sequence[str], column: _Column, width: float, style: str) -> str:
    """Pages one below the other, as a run is drawn.

    @param labels: the labels of the pages, from top to bottom
    @param column: where the column is drawn
    @param width: the width of a page
    @param style: the attributes that set the pages' fill and outline
    @return: the SVG elements
    """
    return "".join(
        _page(
            label,
            column.centre - width / 2,
            column.top + index * PAGE_HEIGHT,
            width,
            style,
        )
        for index, label in enumerate(labels)
    )


def _arrow(points: Sequence[tuple[float, float]], source: str, target: str) -> str:
    """An arrow along a polyline, with its head at the last point, in the colour of the surrounding text.

    @param points: the points of the polyline, at least two
    @param source: what the arrow comes from, for its ``data-from`` attribute (a run's number or ``input``)
    @param target: what the arrow leads to, for its ``data-to`` attribute (a run's number or ``result``)
    @return: the SVG group of line and head
    """
    (x_0, y_0), (x_1, y_1) = points[-2], points[-1]
    length: float = math.hypot(x_1 - x_0, y_1 - y_0) or 1.0
    # unit vector along the last segment and the head's corners, ARROW_HEAD_LENGTH back and ARROW_HEAD_HALF_WIDTH to
    # either side:
    u_x, u_y = (x_1 - x_0) / length, (y_1 - y_0) / length
    back_x, back_y = x_1 - ARROW_HEAD_LENGTH * u_x, y_1 - ARROW_HEAD_LENGTH * u_y
    corners: list[tuple[float, float]] = [
        (back_x - ARROW_HEAD_HALF_WIDTH * u_y, back_y + ARROW_HEAD_HALF_WIDTH * u_x),
        (x_1, y_1),
        (back_x + ARROW_HEAD_HALF_WIDTH * u_y, back_y - ARROW_HEAD_HALF_WIDTH * u_x),
    ]
    line: str = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    head: str = " ".join(f"{x:.1f},{y:.1f}" for x, y in corners)
    return (
        f'<g class="arrow" data-from="{html.escape(source)}" data-to="{html.escape(target)}" opacity="0.75">'
        f'<polyline points="{line}" fill="none" stroke="currentColor" stroke-width="1.3"/>'
        f'<polygon points="{head}" fill="currentColor"/></g>'
    )


def _merge_arrows[ObjectType: Comparable](
    counts: SortCounts[ObjectType],
    levels: _Levels,
    columns: dict[int, _Column],
    result: _Column,
    page_size: int,
) -> list[str]:
    """The arrows from each merge's input runs to its output run or, for the final merge, to the result: straight
    down from the bottom of the input run to just above the line of the merge's level, then across to
    :data:`ARROW_END` pixels above the output, and straight down to its top.
    The arrows of one merge end side by side above the output's top, :data:`ARROW_END_GAP` apart, from left to right
    in the order of their runs' columns, so that their heads do not overlap; with more than four input runs, the
    outer heads reach beyond the edges of the output's page.

    @param counts: what the sort did
    @param levels: where the levels are drawn
    @param columns: the column of every run written, by the run's number
    @param result: the column of the result
    @param page_size: the number of values on a page
    @return: the SVG groups of the arrows
    """
    arrows: list[str] = []
    for merge in [*counts.merges, counts.final_merge]:
        # the output run of a merge, or the result for the final merge:
        target: _Column = (
            columns[merge.output.number] if isinstance(merge, Merge) else result
        )
        name: str = str(merge.output.number) if isinstance(merge, Merge) else "result"
        for index, run in enumerate(
            sorted(merge.inputs, key=lambda run: columns[run.number].centre)
        ):
            end: float = (
                target.centre + (index - (len(merge.inputs) - 1) / 2) * ARROW_END_GAP
            )
            source: _Column = columns[run.number]
            start: float = (
                source.top
                + math.ceil(len(run.elements) / page_size) * PAGE_HEIGHT
                + ARROW_GAP
            )
            # down to just above the line of the merge's level (or not at all if the run ends lower), across to
            # ARROW_END above the target, then straight down to it:
            arrows.append(
                _arrow(
                    [
                        (source.centre, start),
                        (
                            source.centre,
                            max(start, levels.line_y[merge.level] - ABOVE_LINE / 2),
                        ),
                        (end, target.top - ARROW_END),
                        (end, target.top - ARROW_GAP),
                    ],
                    str(run.number),
                    name,
                )
            )
    return arrows


def _svg(parts: Sequence[str], svg_width: float, svg_height: float, label: str) -> str:
    """The SVG element around the parts of a drawing, in the font and colour of the surrounding text, scaled down
    to the width available.

    @param parts: the SVG elements inside
    @param svg_width: the width in pixels
    @param svg_height: the height in pixels
    @param label: what the drawing shows, for screen readers; escaped here
    @return: the SVG element
    """
    escaped: str = html.escape(label)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{escaped}" width="{svg_width:.0f}" '
        f'height="{svg_height:.0f}" viewBox="0 0 {svg_width:.0f} {svg_height:.0f}" '
        f'font-family="sans-serif" font-size="12" '
        f'style="max-width: 100%; height: auto"><title>{escaped}</title>'
        + "".join(parts)
        + "</svg>"
    )


def merge_tree_svg[ObjectType: Comparable](
    counts: SortCounts[ObjectType], page_size: int = 2, title: str = ""
) -> str:
    """Draws the merge tree of one sort as inline SVG: the input as a row of pages, then level by level (PASS 0,
    PASS 1, ...) the runs as columns of pages, with arrows from the input to the runs of phase 0, from each merge's
    input runs to its output run, and from the final merge's input runs to the result, which is drawn with dashed
    pages as it is not written.

    @param counts: what the sort did, from :func:`sort_counted`
    @param page_size: the number of values on a page, 2 as on the slides
    @param title: a heading above the tree; none if empty
    @return: the SVG element, as a string
    @raise ValueError: if the input has more than :data:`MAX_VALUES` values, or page_size is less than 1
    """
    if len(counts.values) > MAX_VALUES:
        raise ValueError(
            f"the merge tree is drawn for at most {MAX_VALUES} values, got {len(counts.values)}"
        )
    # the layout: the input row below the title, the levels below it, the runs and the result in the levels:
    width: float = _page_width(counts, page_size)
    input_labels: list[str] = page_labels(counts.values, page_size)
    input_top: float = MARGIN + (TITLE_HEIGHT if title else 0) + ABOVE_INPUT
    input_width: float = len(input_labels) * (width + INPUT_GAP) - INPUT_GAP
    levels: _Levels = _levels(counts, page_size, input_top)
    columns: dict[int, _Column] = _columns(counts, levels, width, input_width)
    # the result centred below the final merge's input runs:
    result: _Column = _Column(
        (
            sum(columns[run.number].centre for run in counts.final_merge.inputs)
            / len(counts.final_merge.inputs)
            if counts.final_merge.inputs
            else LABEL_WIDTH + width / 2
        ),
        levels.runs_top[-1],
    )
    right: float = max(
        [LABEL_WIDTH + input_width, result.centre + width / 2]
        + [column.centre + width / 2 for column in columns.values()]
    )

    # the title (its baseline 14 pixels below the margin) and the input row:
    parts: list[str] = []
    if title:
        parts.append(
            f'<g class="title" font-weight="bold">{_text(MARGIN, MARGIN + 14, title)}</g>'
        )
    parts.append(
        '<g class="input">'
        + _text(MARGIN, input_top + PAGE_HEIGHT - BASELINE, "input")
        + "".join(
            _page(
                label,
                LABEL_WIDTH + index * (width + INPUT_GAP),
                input_top,
                width,
                INPUT_STYLE,
            )
            for index, label in enumerate(input_labels)
        )
        + "</g>"
    )
    # the lines of the levels, reaching 8 pixels beyond the tree on either side, with their labels:
    for level, y in enumerate(levels.line_y):
        parts.append(
            f'<g class="level" data-level="{level}">'
            f'<line x1="{LABEL_WIDTH - 8}" y1="{y:.1f}" x2="{right + 8:.1f}" y2="{y:.1f}" stroke="{LINE_COLOUR}" '
            f'stroke-width="1.5"/>{_text(MARGIN, y + 4, f"PASS {level}")}</g>'
        )
    # the runs written, and the result of the final merge, which is not written (the numbers in the data attributes
    # go through int(), as they are not escaped):
    for run in _written(counts):
        parts.append(
            f'<g class="run" data-run="{int(run.number)}" data-level="{int(run.level)}">'
            + _column(
                page_labels(run.elements, page_size),
                columns[run.number],
                width,
                RUN_STYLE,
            )
            + "</g>"
        )
    parts.append(
        f'<g class="result" data-level="{int(counts.final_merge.level)}">'
        + _column(page_labels(counts.output, page_size), result, width, RESULT_STYLE)
        # the label RESULT_LABEL_GAP right of the result's first page, on the same baseline:
        + _text(
            result.centre + width / 2 + RESULT_LABEL_GAP,
            result.top + PAGE_HEIGHT - BASELINE,
            RESULT_LABEL,
        )
        + "</g>"
    )
    # the arrows from the input row to the runs of phase 0, then those of the merges:
    for run in counts.runs:
        parts.append(
            _arrow(
                [
                    (columns[run.number].centre, input_top + PAGE_HEIGHT + ARROW_GAP),
                    (columns[run.number].centre, columns[run.number].top - ARROW_GAP),
                ],
                "input",
                str(run.number),
            )
        )
    parts.extend(_merge_arrows(counts, levels, columns, result, page_size))
    # wide enough for the result's label and the title:
    return _svg(
        parts,
        max(right + RESULT_LABEL_ROOM, 2 * MARGIN + TITLE_CHARACTER_WIDTH * len(title)),
        levels.bottom + MARGIN,
        title or "merge tree",
    )
