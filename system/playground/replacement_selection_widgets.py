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

"""Widgets of the replacement selection playground: replacement selection on one's own input, sub-step by sub-step.

The view shows the rows of the lecture's slides: the input R with the comparison of the current output step below
it; main memory, one row of M places that holds the heap at its front and the list behind it, with the heap drawn as a
tree above it; and the output runs, into which every new element enters on the left.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from typing import cast

import ipywidgets as widgets

from system.playground.replacement_selection_playground import (
    DEFAULT_COUNT,
    DEFAULT_SEED,
    MAX_MEMORY,
    MAX_VALUES,
    MIN_MEMORY,
    PRESETS,
    SLIDES,
    SLIDES_MEMORY,
    SLIDES_VALUES,
    Comparison,
    Element,
    Frame,
    Mark,
    format_values,
    next_output,
    parse_values,
    preset_values,
    run_lengths,
    trace,
    without_maintenance_steps,
)

# the preset dropdown shows this when the reader chooses it, after the input text was changed by hand (valid or not),
# and after M was changed while the slides' example was shown:
OWN_INPUT: str = "own input"
# the largest seed of the generated presets:
MAX_SEED: int = 999_999

# The playground sets no text colour, so its text keeps the colour of the theme; its backgrounds are translucent
# tints, as in the MVCC and RAID playgrounds (see mvcc_widgets.py), that show light over a light page and dark over a
# dark one.

# the colours of the runs, which repeat after three runs, so that neighbouring runs always differ: pink, cyan and
# violet, the run colours of the external sorting film. The heap's elements have the colour of the current run, the
# list's that of the next run, the output's that of their run:
RUN_COLOURS: tuple[str, ...] = (
    "rgba(255,95,162,0.35)",
    "rgba(47,211,230,0.35)",
    "rgba(182,140,255,0.35)",
)
# the background of the elements still in the input:
INPUT_COLOUR: str = "rgba(128,128,128,0.15)"
# the background of the decision of the comparison box: green if the next element of the input goes into the heap,
# red if it goes to the list, as on the slides:
COMPARISON_COLOURS: dict[bool, str] = {
    True: "rgba(76,175,80,0.35)",
    False: "rgba(244,67,54,0.35)",
}
# the background of an error in the input text, the red of the decision:
ERROR_COLOUR: str = COMPARISON_COLOURS[False]
# the frame of the heap's root by the theme: on dark pages the amber of the external sorting film; on light pages,
# where that amber stands out too little, a darker amber, which stands out from dark pages too:
ROOT_FRAMES: dict[str, str] = {"light": "#b07d00", "dark": "#f2c230"}
# the frame of what a sub-step changes or reads, a grey that shows on light and dark pages:
MARK_FRAME: str = "#808080"
# the frames of the two elements a sift compares and the edge between them, where one is the other's parent: a blue
# that stands out from light and dark pages and differs from the amber of the root and the grey of a change:
COMPARED_FRAME: str = "#1e88e5"
# the width of an edge of the tree, and of the edge between the two compared elements, four times as wide:
EDGE_WIDTH: float = 1.5
COMPARED_EDGE_WIDTH: float = 4 * EDGE_WIDTH
# the lines of the cells and the edges of the tree:
LINE_COLOUR: str = "rgba(128,128,128,0.6)"
# the sizes in pixels of a cell of a row (input, memory, output), of the gap between two cells, and of the bar between
# the heap's places and the list's in the row of memory:
CELL_WIDTH: int = 38
CELL_HEIGHT: int = 28
CELL_GAP: int = 2
DIVIDER_WIDTH: int = 4
# the style of the view, shown once in a widget of its own (a style element in an HTML widget applies to the whole
# page): the box, its rows of cells, the frame of a marked cell, an empty place of memory, the bar between heap and
# list, the boxes of the runs, the comparison box and the amber of the root by the theme:
BOX_STYLE: str = (
    "<style>.rs-box {border:1px solid rgba(128,128,128,0.5); background:rgba(128,128,128,0.08); padding:6px; "
    "margin:6px 0; line-height:1.5} "
    f".rs-row {{display:flex; flex-wrap:wrap; gap:{CELL_GAP}px; align-items:flex-start}} "
    f".rs-cell {{box-sizing:border-box; width:{CELL_WIDTH}px; height:{CELL_HEIGHT}px; line-height:{CELL_HEIGHT - 2}px; "
    f"text-align:center; font-family:monospace; border:1px solid {LINE_COLOUR}}} "
    f".rs-mark {{box-shadow:inset 0 0 0 3px {MARK_FRAME}}} "
    ".rs-empty {border-style:dashed} "
    # a place of memory: its cell with its number below it; the bar has the theme's text colour, so that it shows on
    # light and dark pages:
    ".rs-slot {display:flex; flex-direction:column; align-items:center} "
    ".rs-index {font-size:0.75em; opacity:0.7; line-height:1.4} "
    f".rs-divider {{box-sizing:border-box; width:{DIVIDER_WIDTH}px; height:{CELL_HEIGHT}px; margin:0 3px; "
    "background:currentColor; opacity:0.6} "
    f".rs-run {{display:flex; flex-direction:column; align-items:center; border:1px solid {LINE_COLOUR}; "
    "padding:2px; margin:0 6px 4px 0; max-width:100%} "
    ".rs-title {font-weight:bold; margin:6px 0 2px} "
    # the input in the top row; below it, above heap and memory, the comparison box, which has the same place and size
    # in every frame:
    ".rs-top {display:flex; flex-wrap:wrap; gap:8px 24px; align-items:flex-start} "
    ".rs-input {flex:1 1 300px; min-width:0} "
    f".rs-compare {{box-sizing:border-box; width:330px; max-width:100%; height:7em; margin-top:8px; padding:4px 8px; "
    f"border:1px solid {LINE_COLOUR}; display:grid; grid-template-columns:max-content 1fr; column-gap:12px; "
    "row-gap:2px; align-content:start} "
    ".rs-compare .rs-decision {grid-column:1 / -1; margin-top:4px} "
    ".rs-compare b {padding:0 6px; justify-self:start} "
    ".rs-note {font-size:0.85em} "
    # the frame of the root (class rs-root) has the amber of the theme. JupyterLab and Jupyter Notebook mark the theme
    # on the page's body as data-jp-theme-light, VS Code as the class vscode-light or vscode-dark; their rules name the
    # body, so they are more specific than the rule for the system's colour scheme and win over it. Where the page
    # marks no theme (e.g. PyCharm), the system's colour scheme decides, and without one the darker amber is the
    # default. The plain rule must come before the one for the colour scheme, as both are equally specific. Every rule
    # sets the stroke, for the root's node in the tree, and the border colour, for the sample in the legend:
    f".rs-root {{stroke:{ROOT_FRAMES['light']}; border-color:{ROOT_FRAMES['light']}}} "
    "@media (prefers-color-scheme: dark) "
    f"{{.rs-root {{stroke:{ROOT_FRAMES['dark']}; border-color:{ROOT_FRAMES['dark']}}}}} "
    'body[data-jp-theme-light="true"] .rs-root, body.vscode-light .rs-root '
    f"{{stroke:{ROOT_FRAMES['light']}; border-color:{ROOT_FRAMES['light']}}} "
    'body[data-jp-theme-light="false"] .rs-root, body.vscode-dark .rs-root '
    f"{{stroke:{ROOT_FRAMES['dark']}; border-color:{ROOT_FRAMES['dark']}}}</style>"
)
# the sizes of the tree in pixels: a node, the room per node at the lowest level, the distance of two levels, and the
# room around the tree for the frames of marked nodes:
NODE_WIDTH: int = 40
NODE_HEIGHT: int = 28
SLOT_WIDTH: int = 60
LEVEL_HEIGHT: int = 50
MARGIN: int = 6
# the distance of a grey or blue frame from its node, the gap between a node and its place number, the font sizes of
# a node's element and of its place number, the place number's opacity, the dashes of an inner node in a bulk load,
# and the widths of the lines of a node, of the root and of the frames:
FRAME_OFFSET: int = 4
PLACE_GAP: int = 6
VALUE_FONT_SIZE: int = 14
PLACE_FONT_SIZE: int = 10
PLACE_OPACITY: float = 0.7
INNER_DASHES: str = "5 3"
NODE_STROKE_WIDTH: float = 1
ROOT_STROKE_WIDTH: float = 3
MARK_STROKE_WIDTH: float = 2.5
COMPARED_STROKE_WIDTH: float = 3
# the height of the caption: two lines of an HTML widget, each as high as --jp-widgets-inline-height, the line height
# ipywidgets gives an HTML widget's text, so that the view below the caption stays in place when a caption wraps in a
# narrow window; a caption that needs more lines scrolls within it:
CAPTION_HEIGHT: str = "calc(2 * var(--jp-widgets-inline-height))"


def run_colour(run: int) -> str:
    """Returns the colour of a run.

    @param run: the run's number, from 0
    @return: a value of :data:`RUN_COLOURS`; run i and run i + 1 always differ
    """
    return RUN_COLOURS[run % len(RUN_COLOURS)]


def swatch(colour: str, text: str) -> str:
    """Shows a short text on a background, as an example of a colour in the legend.

    @param colour: the background
    @param text: the text
    @return: the HTML
    """
    return (
        f'<span style="background:{colour}; padding:0 4px">{html.escape(text)}</span>'
    )


# the legend above the view:
LEGEND: str = (
    "<b>Colours</b> by run: "
    f"{swatch(RUN_COLOURS[0], 'run 0, 3, 6, …')} {swatch(RUN_COLOURS[1], 'run 1, 4, 7, …')} "
    f"{swatch(RUN_COLOURS[2], 'run 2, 5, 8, …')}; "
    "the heap holds elements of the current run, the list those of the next run. Main memory is one row of M "
    "places: the heap's places first, then a bar, then the list's; a dashed cell is an empty place. Above it, the "
    "heap is drawn as a tree. "
    f'<span class="rs-root" style="border-width:{ROOT_STROKE_WIDTH}px; border-style:solid; padding:0 4px">amber</span> '
    "frames the root, "
    "the top element of the heap; "
    f'<span style="box-shadow:inset 0 0 0 3px {MARK_FRAME}; padding:0 6px">grey</span> marks what a step changes and '
    "the elements of the input it reads; "
    f'<span style="box-shadow:inset 0 0 0 3px {COMPARED_FRAME}; padding:0 6px">blue</span> marks the two elements a '
    "sift compares: the two children of the sinking element, or the sinking element and its smaller child (joined by "
    "a thick edge), only with “Heap maintenance step by step” on; a dashed node is an inner node, which a bulk load "
    "sifts down (also only with it on). The small number left of a node is its place in memory: the same number "
    "stands below its cell in the row of memory."
)


def cell(
    text: str,
    background: str | None = None,
    marked: bool = False,
    empty: bool = False,
) -> str:
    """Shows one element, or an empty place, as a cell of a row.

    @param text: the element's value, empty for an empty place
    @param background: the cell's background, None for none
    @param marked: whether to frame the cell grey
    @param empty: whether to dash the cell's lines (``rs-empty``), as for an empty place of memory
    @return: the HTML
    """
    classes: str = (
        "rs-cell" + (" rs-empty" if empty else "") + (" rs-mark" if marked else "")
    )
    style: str = "" if background is None else f' style="background:{background}"'
    return f'<div class="{classes}"{style}>{html.escape(text)}</div>'


def input_html(frame: Frame, values: Sequence[int]) -> str:
    """Shows the input R: the elements taken from it as empty cells, the others with their values. Marked are those
    the frame reads, as on the slides: at the start the M elements the next step loads, and, when an element is
    written, the next element, which is compared with it.

    @param frame: the frame
    @param values: the input
    @return: the HTML
    """
    cells: str = "".join(
        (
            cell("")
            if index < frame.taken
            else cell(str(value), INPUT_COLOUR, Mark("input", index) in frame.marks)
        )
        for index, value in enumerate(values)
    )
    return f'<div class="rs-input"><div class="rs-title">Input R</div><div class="rs-row">{cells}</div></div>'


def node_anchor(place: int, slots: int) -> tuple[float, float]:
    """Returns where a place of the heap is drawn in the tree: the middle of its node's top edge.

    @param place: the place in the heap's array; level d holds the places 2^d − 1 to 2^(d+1) − 2
    @param slots: the number of places of the tree's lowest level, each :data:`SLOT_WIDTH` wide
    @return: the x of the node's centre and the y of its top edge
    """
    level: int = (place + 1).bit_length() - 1
    # the places of a level share the width evenly:
    span: float = slots / 2**level * SLOT_WIDTH
    x: float = MARGIN + (place - (2**level - 1) + 0.5) * span
    y: float = MARGIN + level * LEVEL_HEIGHT
    return x, y


def tree_width(slots: int) -> int:
    """Returns the width of the heap's SVG.

    @param slots: the number of places of the tree's lowest level
    @return: the width in pixels
    """
    return 2 * MARGIN + slots * SLOT_WIDTH


def node_svg(frame: Frame, place: int, slots: int) -> str:
    """Draws one node of the heap's tree.

    @param frame: the frame
    @param place: the node's place in the heap's array, which is its place in memory
    @param slots: the number of places of the tree's lowest level
    @return: the SVG elements, each with a class that names it: the node (``rs-node``) in the colour of the current
        run (empty if the root's place is empty), framed amber if it is the root (``rs-root``) and dashed if it is an
        inner node of a bulk load (``rs-inner``); a grey frame around it if its place of memory is marked
        (``rs-marked``), a blue one if a sift compares it (``rs-compared``); its element (``rs-value``); its place in
        the array, left of it (``rs-place``)
    """
    element: Element | None = frame.heap[place]
    x, y = node_anchor(place, slots)
    left: float = x - NODE_WIDTH / 2
    middle: float = y + NODE_HEIGHT / 2
    fill: str = "none" if element is None else run_colour(frame.run)
    # the root's frame has the amber of the theme: the stroke attribute gives the darker amber where BOX_STYLE is
    # missing, and the rule for the class rs-root overrides it; an inner node of a bulk load is dashed (rs-inner):
    inner_node: bool = place in frame.inner
    node_class: str = (
        "rs-node"
        + (" rs-root" if place == 0 else "")
        + (" rs-inner" if inner_node else "")
    )
    node_attributes: str = (
        f'class="{node_class}" stroke="{ROOT_FRAMES["light"]}" stroke-width="{ROOT_STROKE_WIDTH}"'
        if place == 0
        else f'class="{node_class}" stroke="{LINE_COLOUR}" stroke-width="{NODE_STROKE_WIDTH}"'
    )
    dashes: str = f' stroke-dasharray="{INNER_DASHES}"' if inner_node else ""
    parts: list[str] = [
        f'<rect x="{left:.1f}" y="{y}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" fill="{fill}" '
        f"{node_attributes}{dashes}/>"
    ]
    # the grey and the blue frame stand FRAME_OFFSET around the node:
    frame_box: str = (
        f'x="{left - FRAME_OFFSET:.1f}" y="{y - FRAME_OFFSET}" width="{NODE_WIDTH + 2 * FRAME_OFFSET}" '
        f'height="{NODE_HEIGHT + 2 * FRAME_OFFSET}" fill="none"'
    )
    if Mark("memory", place) in frame.marks:
        parts.append(
            f'<rect class="rs-marked" {frame_box} stroke="{MARK_FRAME}" stroke-width="{MARK_STROKE_WIDTH}"/>'
        )
    if place in frame.compared:
        parts.append(
            f'<rect class="rs-compared" {frame_box} stroke="{COMPARED_FRAME}" '
            f'stroke-width="{COMPARED_STROKE_WIDTH}"/>'
        )
    if element is not None:
        parts.append(
            f'<text class="rs-value" x="{x:.1f}" y="{middle}" text-anchor="middle" dominant-baseline="central" '
            f'font-family="monospace" font-size="{VALUE_FONT_SIZE}" fill="currentColor">'
            f"{html.escape(str(element))}</text>"
        )
    # the place in the array, PLACE_GAP left of the node:
    parts.append(
        f'<text class="rs-place" x="{left - PLACE_GAP:.1f}" y="{middle}" text-anchor="end" dominant-baseline="central" '
        f'font-size="{PLACE_FONT_SIZE}" fill="currentColor" opacity="{PLACE_OPACITY}">{html.escape(str(place))}'
        "</text>"
    )
    return "".join(parts)


def edge_svg(frame: Frame, place: int, slots: int) -> str:
    """Draws the edge from a place's parent down to it.

    @param frame: the frame
    @param place: the place of the child, from 1
    @param slots: the number of places of the tree's lowest level
    @return: the SVG line: blue and wide between the two elements a sift compares (``rs-compared-edge``), else grey
        (``rs-edge``)
    """
    x, y = node_anchor(place, slots)
    parent: int = (place - 1) // 2
    parent_x, parent_y = node_anchor(parent, slots)
    edge_attributes: str = (
        f'class="rs-compared-edge" stroke="{COMPARED_FRAME}" stroke-width="{COMPARED_EDGE_WIDTH}"'
        if frame.compared == (parent, place)
        else f'class="rs-edge" stroke="{LINE_COLOUR}" stroke-width="{EDGE_WIDTH}"'
    )
    return f'<line x1="{parent_x:.1f}" y1="{parent_y + NODE_HEIGHT}" x2="{x:.1f}" y2="{y}" {edge_attributes}/>'


def heap_svg(frame: Frame, memory: int) -> str:
    """Draws the heap, the first ``heap_size`` places of memory, as a tree: the root on top, the children of every
    place below it (see :func:`node_svg`).

    The tree has room for M places, so that it keeps its size from frame to frame.

    @param frame: the frame
    @param memory: M
    @return: the SVG, whose text has the colour of the theme (``currentColor``)
    """
    # M places fill this many levels (level d holds the places 2^d − 1 to 2^(d+1) − 2, so place M − 1 is on level
    # M.bit_length() − 1); the lowest level has room for 2^(levels − 1) places:
    levels: int = max(1, memory.bit_length())
    slots: int = 2 ** (levels - 1)
    width: int = tree_width(slots)
    height: int = 2 * MARGIN + (levels - 1) * LEVEL_HEIGHT + NODE_HEIGHT
    # the edges first, so that the nodes lie on them:
    parts: list[str] = [
        edge_svg(frame, place, slots) for place in range(1, len(frame.heap))
    ]
    parts += [node_svg(frame, place, slots) for place in range(len(frame.heap))]
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="the heap as a tree">{"".join(parts)}</svg>'
    )


def heap_title(frame: Frame) -> str:
    """Says which places of memory the tree draws.

    @param frame: the frame
    @return: e.g. ``heap: places 0 to 2 of memory, as a tree``, or ``heap: empty``
    """
    if frame.heap_size == 0:
        return "heap: empty"
    if frame.heap_size == 1:
        return "heap: place 0 of memory, as a tree"
    return f"heap: places 0 to {frame.heap_size - 1} of memory, as a tree"


def memory_html(frame: Frame) -> str:
    """Shows main memory as one row of M cells, each with its place below it: the heap's places first, in the colour
    of the current run, then a bar (``rs-divider``), then the list's places, in the colour of the next run; an empty
    place is dashed and has no colour. Cell i in front of the bar is node i of the heap's tree.

    @param frame: the frame
    @return: the HTML
    """
    divider: str = '<div class="rs-divider"></div>'
    parts: list[str] = []
    for place, element in enumerate(frame.memory):
        if place == frame.heap_size:
            parts.append(divider)
        colour: str | None = None
        if element is not None:
            colour = run_colour(frame.run if place < frame.heap_size else frame.run + 1)
        parts.append(
            '<div class="rs-slot">'
            + cell(
                "" if element is None else str(element),
                colour,
                Mark("memory", place) in frame.marks,
                empty=element is None,
            )
            + f'<div class="rs-index">{html.escape(str(place))}</div></div>'
        )
    # a heap that fills memory has the bar after its last place:
    if frame.heap_size == len(frame.memory):
        parts.append(divider)
    return f'<div class="rs-row rs-memory">{"".join(parts)}</div>'


def memory_text(frame: Frame, memory: int) -> str:
    """Says how many elements heap and list hold, which is never more than M.

    @param frame: the frame
    @param memory: M
    @return: e.g. ``|heap| + |list| = 3 + 1 ≤ M = 4``
    """
    in_heap: int = sum(element is not None for element in frame.heap)
    return f"|heap| + |list| = {in_heap} + {len(frame.pending)} ≤ M = {memory}"


# what the comparison box says where no output step is under way: before the first output, during the bulk load of a
# new run, while the input is empty already, and at the start of an input that fits into memory as a whole; in the
# last two no comparison will follow:
FIRST_NOTE: str = "(first comparison at the first output)"
NEW_RUN_NOTE: str = "(new run: next comparison at its first output)"
NOTHING_LEFT_NOTE: str = "(R is empty: nothing left to compare)"
ALL_FITS_NOTE: str = "(all of R fits into memory: nothing to compare)"
# where the next element of the input would stand once the input is empty:
EMPTY_INPUT: str = "— (R is empty)"


def comparison_html(
    frame: Frame, input_empty: bool = False, input_fits: bool = False
) -> str:
    """Shows the comparison box: the last element on output, the next element of the input and, as on the slides,
    whether that element goes into the heap (green) or to the list (red).

    The box belongs to an output step: from the frame that writes the root to the output to the last frame before the
    next output, move of the list to the front or bulk load, it shows the element written and the next element of the
    input, also through the
    comparisons and swaps of the new root's sift, as the box compares with the last output, not with the current
    root. Outside of an output step it shows dashes and a note.

    @param frame: the frame
    @param input_empty: whether the input is empty in the frame, which matters only outside of an output step: then
        no comparison follows, and the note says so
    @param input_fits: whether the whole input fits into memory (n ≤ M), so that no comparison will follow; matters
        only outside of an output step
    @return: the HTML, a box with the same rows in every frame
    """
    last: str = "—"
    drawn: str = "—"
    # the class of the last output's value: grey on the frame that writes it, as the slides highlight it:
    last_class: str = (
        ' class="rs-mark"'
        if frame.output and Mark("output", len(frame.output) - 1) in frame.marks
        else ""
    )
    bottom: str
    comparison: Comparison | None = frame.comparison
    if comparison is None:
        # before the first output, or during the bulk load of a new run:
        note: str = FIRST_NOTE if not frame.output else NEW_RUN_NOTE
        if input_empty:
            drawn = EMPTY_INPUT
            note = NOTHING_LEFT_NOTE
        elif input_fits:
            note = ALL_FITS_NOTE
        bottom = f'<span class="rs-note">{html.escape(note)}</span>'
    else:
        last = str(comparison.last)
        if comparison.drawn is None:
            drawn = EMPTY_INPUT
            # an empty line, so that the box keeps its rows:
            bottom = "&nbsp;"
        else:
            drawn = str(comparison.drawn)
            # into_heap is a bool here, as an element was drawn:
            into_heap: bool = bool(comparison.into_heap)
            # written as on the slides, ">=" also on red, where the element goes to the list:
            decision: str = f"{comparison.drawn} >= {comparison.last}  →  " + (
                "heap (this run)" if into_heap else "list (next run)"
            )
            bottom = (
                f'<span style="background:{COMPARISON_COLOURS[into_heap]}; padding:1px 8px; white-space:pre">'
                f"{html.escape(decision)}</span>"
            )
    return (
        '<div class="rs-compare">'
        f"<span>last element on output</span><b{last_class}>{html.escape(last)}</b>"
        f"<span>next element of input</span><b>{html.escape(drawn)}</b>"
        f'<div class="rs-decision">{bottom}</div>'
        "</div>"
    )


def output_html(frame: Frame) -> str:
    """Shows the output runs as a conveyor that flows away from the heap: every new element enters on the left and
    pushes the elements already written one place to the right, and a new run's box stands left of the older runs'.
    Each run is a box of its own, its elements in its colour, with its number below.

    @param frame: the frame
    @return: the HTML
    """
    runs: list[str] = []
    start: int = 0
    for run, length in enumerate(run_lengths(frame.output)):
        # the run's elements, the newest first:
        cells: str = "".join(
            cell(
                str(frame.output[index].element),
                run_colour(run),
                Mark("output", index) in frame.marks,
            )
            for index in reversed(range(start, start + length))
        )
        runs.append(
            f'<div class="rs-run"><div class="rs-row">{cells}</div>'
            f"<small>Run {html.escape(str(run))}</small></div>"
        )
        start += length
    # the newest run first; before the first output, an empty cell holds the row's place:
    return (
        '<div class="rs-title">Output runs R′ (each new element enters on the left)</div>'
        f'<div class="rs-row">{"".join(reversed(runs)) or cell("")}</div>'
    )


def frame_html(frame: Frame, values: Sequence[int], memory: int) -> str:
    """Shows a frame in a box: the input, below it the comparison box, then the heap as a tree, main memory as a row
    of cells and what heap and list hold, then the output.

    @param frame: the frame
    @param values: the input
    @param memory: M
    @return: the HTML
    """
    return (
        '<div class="rs-box">'
        + f'<div class="rs-top">{input_html(frame, values)}</div>'
        + comparison_html(
            frame,
            input_empty=frame.taken == len(values),
            input_fits=len(values) <= memory,
        )
        + f'<div class="rs-title">{html.escape(heap_title(frame))}</div>'
        + heap_svg(frame, memory)
        + f'<div class="rs-title">main memory (M = {html.escape(str(memory))} places): the heap in front, the list '
        "behind the bar</div>"
        + memory_html(frame)
        + f"<div>{html.escape(memory_text(frame, memory))}</div>"
        + output_html(frame)
        + "</div>"
    )


def error_html(message: str) -> str:
    """Shows an error in the input text, on red.

    @param message: what is wrong
    @return: the HTML
    """
    return (
        f'<div style="background:{ERROR_COLOUR}; padding:4px 8px">{html.escape(message)} '
        "The playground still shows the last valid input.</div>"
    )


class ReplacementSelectionPlayground:  # pylint: disable=too-many-instance-attributes
    """The playground's widgets: the input and M, the buttons that step through the frames, the caption and the view;
    :attr:`widget` is what the notebook shows."""

    def __init__(self) -> None:
        """Builds the widgets with the slides' example at its start."""
        # set while the playground sets its own controls, whose observers would otherwise react:
        self.refreshing: bool = False
        full_label: dict[str, str] = {"description_width": "initial"}
        self.preset = widgets.Dropdown(
            options=[*PRESETS, OWN_INPUT], value=SLIDES, description="preset"
        )
        self.count = widgets.IntSlider(
            value=DEFAULT_COUNT,
            min=1,
            max=MAX_VALUES,
            description="n",
            continuous_update=False,
        )
        self.seed = widgets.BoundedIntText(
            value=DEFAULT_SEED,
            min=0,
            max=MAX_SEED,
            description="seed",
            layout=widgets.Layout(width="180px"),
        )
        self.text = widgets.Text(
            value=format_values(SLIDES_VALUES),
            description="input R",
            continuous_update=False,
            layout=widgets.Layout(width="95%"),
        )
        self.memory = widgets.IntSlider(
            value=SLIDES_MEMORY,
            min=MIN_MEMORY,
            max=MAX_MEMORY,
            description="M (elements in memory)",
            continuous_update=False,
            style=full_label,
        )
        self.error = widgets.HTML()
        # whether heap maintenance shows each step: a bulk load its order, and every sift, in a bulk load or after an
        # output, each comparison, swap and end; or (the default) a bulk load only the heap before and after it, and a
        # sift after an output only its result, in the frame in which an element took the root's place:
        self.maintenance_steps = widgets.Checkbox(
            value=False, description="Heap maintenance step by step", style=full_label
        )
        # the variation selector U+FE0E draws ⏮, ⏩ and ⏭ as text, like ◀ and ▶, not as coloured emoji:
        self.start_button = widgets.Button(description="⏮\ufe0e start")
        self.back_button = widgets.Button(description="◀ back")
        self.forward_button = widgets.Button(description="forward ▶")
        # jumps to the next output, past draws, comparisons, swaps and bulk loads:
        self.next_output_button = widgets.Button(description="next output ⏩\ufe0e")
        self.end_button = widgets.Button(description="end ⏭\ufe0e")
        self.step_label = widgets.Label()
        self.caption = widgets.HTML(
            layout=widgets.Layout(height=CAPTION_HEIGHT, overflow="auto")
        )
        self.view = widgets.HTML()
        # the input and the M the frames were traced with, all frames of the trace, the frames shown (all of them, or
        # those without the steps of heap maintenance) with their positions among all frames, and the one shown:
        self.values: tuple[int, ...] = SLIDES_VALUES
        self.traced_memory: int = SLIDES_MEMORY
        self.traced_frames: list[Frame] = []
        self.frames: list[Frame] = []
        self.traced_positions: list[int] = []
        self.position: int = 0
        # the observers of the controls and the buttons:
        self.preset.observe(lambda _: self.apply_preset(), names="value")
        for control in (self.count, self.seed):
            control.observe(lambda _: self.generator_changed(), names="value")
        self.text.observe(lambda _: self.text_changed(), names="value")
        self.memory.observe(lambda _: self.memory_changed(), names="value")
        self.maintenance_steps.observe(lambda _: self.steps_changed(), names="value")
        self.start_button.on_click(lambda _: self.go(0))
        self.back_button.on_click(lambda _: self.go(self.position - 1))
        self.forward_button.on_click(lambda _: self.go(self.position + 1))
        self.next_output_button.on_click(
            lambda _: self.go(next_output(self.frames, self.position))
        )
        self.end_button.on_click(lambda _: self.go(len(self.frames) - 1))
        self.widget = widgets.VBox(
            [
                widgets.HTML(BOX_STYLE),
                widgets.HBox([self.preset, self.count, self.seed]),
                self.text,
                widgets.HBox([self.memory, self.maintenance_steps]),
                self.error,
                widgets.HTML(LEGEND),
                widgets.HBox(
                    [
                        self.start_button,
                        self.back_button,
                        self.forward_button,
                        self.next_output_button,
                        self.end_button,
                        self.step_label,
                    ]
                ),
                self.caption,
                self.view,
            ]
        )
        self.enable_generator()
        self.show_trace(
            SLIDES_VALUES, SLIDES_MEMORY, trace(SLIDES_VALUES, SLIDES_MEMORY)
        )

    def enable_generator(self) -> None:
        """Enables n and the seed for the generated presets only, not for the slides' example or one's own input."""
        fixed: bool = self.preset.value in (SLIDES, OWN_INPUT)
        self.count.disabled = fixed
        self.seed.disabled = fixed

    def apply_preset(self) -> None:
        """Puts the chosen preset's input into the text (and, for the slides' example, M = 4) and traces it anew;
        choosing ``own input`` only disables n and the seed."""
        if self.refreshing:
            return
        if self.preset.value == OWN_INPUT:
            self.enable_generator()
            return
        name: str = cast(str, self.preset.value)
        values: tuple[int, ...] = preset_values(name, self.count.value, self.seed.value)
        memory: int = SLIDES_MEMORY if name == SLIDES else self.memory.value
        # traced first, so that nothing changes if tracing fails:
        frames: list[Frame] = trace(values, memory)
        self.refreshing = True
        try:
            self.text.value = format_values(values)
            self.memory.value = memory
            self.error.value = ""
        finally:
            self.refreshing = False
        self.enable_generator()
        self.show_trace(values, memory, frames)

    def generator_changed(self) -> None:
        """Draws the input of a generated preset anew after a change of n or the seed."""
        if self.preset.value not in (SLIDES, OWN_INPUT):
            self.apply_preset()

    def text_changed(self) -> None:
        """Reads the input text: if it is valid, traces it anew, else shows what is wrong and keeps the frames of the
        last valid input. Either way the text is no longer the preset's, so the preset shows ``own input``, and
        choosing the preset again puts its input back."""
        if self.refreshing:
            return
        try:
            values: tuple[int, ...] = parse_values(self.text.value)
        except ValueError as error:
            self.error.value = error_html(str(error))
            self.show_own_input()
            return
        # traced first, so that nothing changes if tracing fails:
        memory: int = self.memory.value
        frames: list[Frame] = trace(values, memory)
        self.error.value = ""
        self.show_own_input()
        self.show_trace(values, memory, frames)

    def memory_changed(self) -> None:
        """Traces the input anew with the M of the slider. The slides' example comes with M = 4, so another M makes the
        preset show ``own input``, and choosing the slides' example again puts M = 4 back.
        """
        if self.refreshing:
            return
        # traced first, so that nothing changes if tracing fails:
        memory: int = self.memory.value
        frames: list[Frame] = trace(self.values, memory)
        if self.preset.value == SLIDES and memory != SLIDES_MEMORY:
            self.show_own_input()
        self.show_trace(self.values, memory, frames)

    def show_own_input(self) -> None:
        """Lets the preset show ``own input``, without reacting to it, and disables n and the seed."""
        self.refreshing = True
        try:
            self.preset.value = OWN_INPUT
        finally:
            self.refreshing = False
        self.enable_generator()

    def show_trace(
        self, values: tuple[int, ...], memory: int, frames: list[Frame]
    ) -> None:
        """Shows the first frame of a new trace.

        @param values: the input that was traced
        @param memory: the M it was traced with, with which the view draws its frames
        @param frames: its frames
        """
        self.values = values
        self.traced_memory = memory
        self.traced_frames = frames
        self.select_frames()
        self.go(0)

    def select_frames(self) -> None:
        """Chooses the frames shown, as the checkbox "Heap maintenance step by step" says: all frames of the trace, or
        those without the steps of heap maintenance (see :func:`without_maintenance_steps`).
        """
        if self.maintenance_steps.value:
            self.frames = list(self.traced_frames)
            self.traced_positions = list(range(len(self.traced_frames)))
        else:
            self.frames, self.traced_positions = without_maintenance_steps(
                self.traced_frames
            )

    def steps_changed(self) -> None:
        """Shows heap maintenance step by step or not, without tracing anew, and stays at the same place: at the same
        frame, or, where a step of heap maintenance is no longer shown, at the frame before that maintenance (the
        start of a bulk load, or the frame in which an element took the root's place).
        """
        # the frame shown, as a position among all frames of the trace:
        traced: int = self.traced_positions[self.position]
        self.select_frames()
        # the last frame shown now that does not come after it:
        self.go(
            max(
                index
                for index, kept in enumerate(self.traced_positions)
                if kept <= traced
            )
        )

    def go(self, position: int) -> None:
        """Shows a frame and enables the buttons that lead somewhere from it.

        @param position: the frame's position, from 0; a position outside the frames (from a late click, before the
            browser has disabled the button) shows the first or the last frame
        """
        self.position = max(0, min(position, len(self.frames) - 1))
        frame: Frame = self.frames[self.position]
        self.step_label.value = f"step {self.position + 1} of {len(self.frames)}"
        self.caption.value = f"<b>{html.escape(frame.caption)}</b>"
        self.view.value = frame_html(frame, self.values, self.traced_memory)
        at_start: bool = self.position == 0
        at_end: bool = self.position == len(self.frames) - 1
        self.start_button.disabled = at_start
        self.back_button.disabled = at_start
        self.forward_button.disabled = at_end
        self.next_output_button.disabled = at_end
        self.end_button.disabled = at_end
