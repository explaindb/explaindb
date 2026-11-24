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
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring,too-many-lines
"""Tests for the widgets of the replacement selection playground, driven without a kernel via values and clicks."""

from __future__ import annotations

import html
import json
import re
import unittest
from pathlib import Path
from typing import Any, NamedTuple, cast
from unittest import mock

import ipywidgets as widgets

from system.playground.replacement_selection_playground import (
    DEFAULT_COUNT,
    DEFAULT_SEED,
    HALF_ORDER,
    LIST_TO_FRONT,
    RANDOM,
    SLIDES,
    SLIDES_MEMORY,
    SLIDES_VALUES,
    SORTED,
    Element,
    Frame,
    Mark,
    ReplayError,
    format_values,
    preset_values,
    trace,
    without_maintenance_steps,
)
from system.playground.replacement_selection_widgets import (
    BOX_STYLE,
    CELL_HEIGHT,
    COMPARED_FRAME,
    COMPARISON_COLOURS,
    ERROR_COLOUR,
    INPUT_COLOUR,
    LEGEND,
    LINE_COLOUR,
    MARK_FRAME,
    NODE_HEIGHT,
    NODE_WIDTH,
    OWN_INPUT,
    ROOT_FRAMES,
    RUN_COLOURS,
    ReplacementSelectionPlayground,
    comparison_html,
    error_html,
    frame_html,
    heap_svg,
    heap_title,
    input_html,
    memory_html,
    memory_text,
    node_anchor,
    output_html,
    run_colour,
)
from system.tests.playground.test_mvcc_widgets import THEMES, blend, contrast, rgba
from system.tests.playground.test_raid_widgets import descendants, distance, press
from system.tests.playground.test_replacement_selection_playground import (
    SLIDES_OUTPUTS,
)

# the number of frames of the slides' example: the playground starts with the 34 without the steps of heap maintenance,
# as the checkbox "Heap maintenance step by step" is off; with it on, it shows all 85 (both counted by hand in
# test_replacement_selection_playground.py):
SLIDES_ALL_FRAMES: int = 85
SLIDES_FRAMES_WITHOUT_STEPS: int = 34


def shown_frames(
    values: tuple[int, ...], memory: int, maintenance_steps: bool = False
) -> list[Frame]:
    """Returns the frames the playground shows for an input and M: the frames without the steps of heap maintenance
    with the checkbox "Heap maintenance step by step" off, as it is at the start, else all frames of the trace.
    """
    frames: list[Frame] = trace(values, memory)
    return frames if maintenance_steps else without_maintenance_steps(frames)[0]


def disabled(
    playground: ReplacementSelectionPlayground,
) -> tuple[bool, bool, bool, bool, bool]:
    """Returns which of the buttons start, back, forward, next output and end are disabled."""
    return (
        playground.start_button.disabled,
        playground.back_button.disabled,
        playground.forward_button.disabled,
        playground.next_output_button.disabled,
        playground.end_button.disabled,
    )


def generator_disabled(playground: ReplacementSelectionPlayground) -> tuple[bool, bool]:
    """Returns whether n and the seed are disabled."""
    return playground.count.disabled, playground.seed.disabled


class State(NamedTuple):
    """What the playground holds and shows, except its frames; the last three fields are named after its controls
    (preset, text, memory), so that a test can replace a field by the control's name."""

    values: tuple[int, ...]
    traced_memory: int
    position: int
    step: str
    caption: str
    view: str
    error: str
    generator: tuple[bool, bool]
    buttons: tuple[bool, bool, bool, bool, bool]
    preset: str
    text: str
    memory: int


def state_of(playground: ReplacementSelectionPlayground) -> State:
    """Returns what the playground holds and shows, except its frames."""
    return State(
        playground.values,
        playground.traced_memory,
        playground.position,
        playground.step_label.value,
        playground.caption.value,
        playground.view.value,
        playground.error.value,
        generator_disabled(playground),
        disabled(playground),
        playground.preset.value,
        playground.text.value,
        playground.memory.value,
    )


def frame_with(frames: list[Frame], start: str) -> int:
    """Returns the position of the only frame whose caption starts with ``start``."""
    positions: list[int] = [
        position
        for position, frame in enumerate(frames)
        if frame.caption.startswith(start)
    ]
    if len(positions) != 1:
        raise AssertionError(
            f"{len(positions)} frames have a caption that starts with {start!r}"
        )
    return positions[0]


def cells(shown: str) -> list[tuple[str, str, str]]:
    """Returns the cells of some HTML: per cell its classes, its background (empty if none) and its text."""
    return re.findall(
        r'<div class="(rs-cell[^"]*)"(?: style="background:([^"]+)")?>([^<]*)</div>',
        shown,
    )


def decisions(shown: str) -> list[tuple[str, str]]:
    """Returns the decisions of the comparison box in some HTML: per decision the style of its background and its
    text."""
    return re.findall(r'<span style="(background:[^"]*)">([^<]*)</span>', shown)


class Box(NamedTuple):
    """What the comparison box shows, its texts unescaped: the last output and whether it is marked, the next element
    of the input, and the bottom line: a decision (its background and text), a note, or neither.
    """

    last: str
    marked: bool
    drawn: str
    decision: tuple[str, str] | None
    note: str | None


# the comparison box, with its rows and the parts that change from frame to frame as groups:
BOX: re.Pattern[str] = re.compile(
    r'<div class="rs-compare"><span>last element on output</span><b( class="rs-mark")?>([^<]*)</b>'
    r'<span>next element of input</span><b>([^<]*)</b><div class="rs-decision">(.*?)</div></div>'
)


def box_of(shown: str) -> Box:
    """Returns what the only comparison box of some HTML shows; raises AssertionError if the HTML holds no box or more
    than one, or a box whose bottom line is neither a decision nor a note nor empty."""
    found: list[tuple[str, str, str, str]] = BOX.findall(shown)
    if len(found) != 1:
        raise AssertionError(f"{len(found)} comparison boxes in {shown!r}")
    marked, last, drawn, bottom = found[0]
    decided: re.Match[str] | None = re.fullmatch(
        r'<span style="background:([^;"]+);[^"]*">([^<]*)</span>', bottom
    )
    noted: re.Match[str] | None = re.fullmatch(
        r'<span class="rs-note">([^<]*)</span>', bottom
    )
    if decided is None and noted is None and bottom != "&nbsp;":
        raise AssertionError(f"the bottom line {bottom!r} is no decision and no note")
    return Box(
        html.unescape(last),
        bool(marked),
        html.unescape(drawn),
        (
            None
            if decided is None
            else (decided.group(1), html.unescape(decided.group(2)))
        ),
        None if noted is None else html.unescape(noted.group(1)),
    )


def run_boxes(shown: str) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """Returns the boxes of the output runs in some HTML, from left to right: per box its label and its cells."""
    return [
        (label, cells(row))
        for row, label in re.findall(
            r'<div class="rs-run"><div class="rs-row">(.*?)</div><small>([^<]*)</small></div>',
            shown,
        )
    ]


# a place of the row of memory (its cell's classes, background and text, and its number) and the bar between heap
# and list:
SLOT: str = (
    r'<div class="rs-slot"><div class="(rs-cell[^"]*)"(?: style="background:([^"]+)")?>([^<]*)</div>'
    r'<div class="rs-index">([^<]*)</div></div>'
)
DIVIDER: str = '<div class="rs-divider"></div>'
# the row of memory, made of places and the bar only (the place without its groups, which only the items need):
MEMORY_ROW: re.Pattern[str] = re.compile(
    r'<div class="rs-row rs-memory">((?:'
    + re.sub(r"\((?!\?)", "(?:", SLOT)
    + "|"
    + re.escape(DIVIDER)
    + r")*)</div>"
)


def memory_row(shown: str) -> list[tuple[str, str, str, str] | str]:
    """Returns the only row of memory of some HTML, from left to right: per place its cell's classes, background
    (empty if none) and text and its number, and ``"|"`` for the bar between heap and list; raises AssertionError if
    the HTML holds no row of memory or more than one."""
    rows: list[str] = MEMORY_ROW.findall(shown)
    if len(rows) != 1:
        raise AssertionError(f"{len(rows)} rows of memory in {shown!r}")
    return [
        (
            "|"
            if found.group(0) == DIVIDER
            else cast(
                tuple[str, str, str, str],
                tuple(group or "" for group in found.groups()),
            )
        )
        for found in re.finditer(f"{SLOT}|{re.escape(DIVIDER)}", rows[0])
    ]


def row_text(shown: str) -> str:
    """Returns the row of memory of some HTML as text: the values of its places, ``_`` for an empty one, and ``|``
    for the bar between heap and list, e.g. ``30 40 73 | 16``."""
    return " ".join(
        item if isinstance(item, str) else item[2] or "_" for item in memory_row(shown)
    )


def attributes(inside: str) -> dict[str, str]:
    """Returns the attributes of the inside of a tag, e.g. ``x="1" fill="none"``, by name."""
    return dict(re.findall(r'([\w-]+)="([^"]*)"', inside))


def rects(svg: str) -> list[dict[str, str]]:
    """Returns the attributes of every ``<rect>`` of an SVG, in order."""
    return [attributes(inside) for inside in re.findall(r"<rect ([^>]*?)/>", svg)]


def lines(svg: str) -> list[dict[str, str]]:
    """Returns the attributes of every ``<line>`` of an SVG, in order."""
    return [attributes(inside) for inside in re.findall(r"<line ([^>]*?)/>", svg)]


def texts(svg: str) -> list[tuple[dict[str, str], str]]:
    """Returns the attributes and the text of every ``<text>`` of an SVG, in order."""
    return [
        (attributes(inside), text)
        for inside, text in re.findall(r"<text ([^>]*)>([^<]*)</text>", svg)
    ]


def has_class(found: dict[str, str], name: str) -> bool:
    """Returns whether the attributes of a tag give it the class ``name``, alone or among others."""
    return name in found.get("class", "").split()


def declarations(style: str, selector: str) -> list[dict[str, str]]:
    """Returns the declarations, by property, of every innermost rule of a style whose selector list holds
    ``selector``."""
    found: list[dict[str, str]] = []
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", style):
        if selector in [part.strip() for part in selectors.split(",")]:
            found.append(dict(re.findall(r"([\w-]+)\s*:\s*([^;]+?)\s*(?:;|$)", body)))
    return found


def is_light(page: tuple[float, float, float]) -> bool:
    """Returns whether a page colour is light by its relative luminance: black stands out more on it than white."""
    return contrast(page, (0, 0, 0)) > contrast(page, (255, 255, 255))


# the backgrounds of the decision of the comparison box: green into the heap, red to the list:
GREEN: str = COMPARISON_COLOURS[True]
RED: str = COMPARISON_COLOURS[False]
# the captions of the outputs of the slides' example, in order, in bold as the caption widget shows them:
SLIDES_OUTPUT_LABELS: list[str] = [f"<b>{caption}</b>" for caption in SLIDES_OUTPUTS]
# the rule of BOX_STYLE that colours the root's frame where the system's colour scheme is dark:
DARK_SCHEME: re.Pattern[str] = re.compile(
    r"@media \(prefers-color-scheme: dark\)\s*\{[^{}]*\{[^{}]*\}\s*\}"
)
# the background of the box of the view, from the rule for .rs-box in BOX_STYLE:
BOX_RULE: re.Match[str] | None = re.search(
    r"\.rs-box\s*\{[^}]*background:\s*([^;}\s]+)", BOX_STYLE
)
assert BOX_RULE, "BOX_STYLE has no rule for .rs-box with a background"
BOX_BACKGROUND: str = BOX_RULE.group(1)
# every background the playground puts behind text, by name, as the tints that lie on the page, the lowest first: the
# legend and the error lie on the page; the cells of the input, the heap, the list and the output and the decision of
# the comparison box lie in the box of the view:
BACKGROUNDS: dict[str, tuple[str, ...]] = {
    "box": (BOX_BACKGROUND,),
    **{
        f"run {run}": (BOX_BACKGROUND, colour) for run, colour in enumerate(RUN_COLOURS)
    },
    "input": (BOX_BACKGROUND, INPUT_COLOUR),
    **{
        f"comparison {'into the heap' if into_heap else 'to the list'}": (
            BOX_BACKGROUND,
            colour,
        )
        for into_heap, colour in COMPARISON_COLOURS.items()
    },
    **{f"legend run {run}": (colour,) for run, colour in enumerate(RUN_COLOURS)},
    "error": (ERROR_COLOUR,),
}


class PaletteTest(unittest.TestCase):
    """The playground's colours are readable in light and dark themes, as its text keeps the theme's colour."""

    def test_text_is_readable_on_every_background(self) -> None:
        """The theme's text has a contrast of at least 4.5 (WCAG AA) on every background in every theme: the run
        colours, the input's colour and both colours of the comparison, in the box of the view.

        Would fail if a background were opaque and light, so that the light text of a dark theme vanished on it, or
        if a tint were so strong that the theme's text no longer stood out.
        """
        for theme, (page, text) in THEMES.items():
            for name, tints in BACKGROUNDS.items():
                with self.subTest(theme=theme, background=name):
                    background: tuple[float, float, float] = page
                    for tint in tints:
                        background = blend(tint, background)
                    self.assertGreaterEqual(
                        contrast(blend(text, background), background), 4.5
                    )

    def test_neighbouring_runs_differ(self) -> None:
        """Run i and run i + 1 have different colours, which differ clearly in every theme, also where the colours
        start again after the last one.

        Would fail if two run colours looked alike, so that two runs side by side in the output, or the heap and the
        list, seemed to belong to the same run.
        """
        # the colour of the next run is never the same:
        for run in range(30):
            with self.subTest(run=run):
                self.assertNotEqual(run_colour(run), run_colour(run + 1))
        # and it differs clearly from the one before, over the box:
        neighbours: list[tuple[str, str]] = [
            (colour, RUN_COLOURS[(index + 1) % len(RUN_COLOURS)])
            for index, colour in enumerate(RUN_COLOURS)
        ]
        for theme, (page, _) in THEMES.items():
            box: tuple[float, float, float] = blend(BOX_BACKGROUND, page)
            for first, second in neighbours:
                with self.subTest(theme=theme, first=first, second=second):
                    # at least 25 of the distance 441 between black and white, so the two look different at a glance:
                    self.assertGreaterEqual(distance(first, second, box), 25)

    def test_no_fixed_text_colour(self) -> None:
        """Neither the style, the legend, the caption, the view (with the comparison box) nor the error sets a text
        colour of its own, in any frame of the slides' example, with heap maintenance shown without and with its
        steps; the tree's text uses the theme's colour (``currentColor``).

        Would fail if black text were set anywhere, which is unreadable on the dark backgrounds of a dark theme.
        """
        # a text colour in CSS, but not a background-color (nor SVG's fill="currentColor"):
        text_colour = re.compile(r"(?<![-\w])color\s*:")
        self.assertIsNone(text_colour.search(BOX_STYLE))
        self.assertIsNone(text_colour.search(LEGEND))
        # every frame, from the start to the end, without and with the steps of heap maintenance:
        playground = ReplacementSelectionPlayground()
        views: list[str] = []
        for steps, count in (
            (False, SLIDES_FRAMES_WITHOUT_STEPS),
            (True, SLIDES_ALL_FRAMES),
        ):
            playground.maintenance_steps.value = steps
            press(playground.start_button)
            for _ in range(count):
                with self.subTest(
                    maintenance_steps=steps, step=playground.step_label.value
                ):
                    self.assertIsNone(text_colour.search(playground.caption.value))
                    self.assertIsNone(text_colour.search(playground.view.value))
                views.append(playground.view.value)
                press(playground.forward_button)
            # the last frame was among those checked:
            self.assertEqual(f"step {count} of {count}", playground.step_label.value)
        # the tree's values and, in every frame, the comparison box were among the text checked:
        self.assertTrue(any('fill="currentColor"' in view for view in views))
        self.assertEqual(
            [1] * (SLIDES_FRAMES_WITHOUT_STEPS + SLIDES_ALL_FRAMES),
            [view.count('<div class="rs-compare">') for view in views],
        )
        # the error in the input text:
        playground.text.value = "30 x"
        self.assertEqual(
            error_html("'x' is not a whole number."), playground.error.value
        )
        self.assertIsNone(text_colour.search(playground.error.value))

    def test_compared_frame_stands_out(self) -> None:
        """The blue of the two compared elements has a contrast of at least 3 (WCAG, for what is not text) on the box
        of the view in every theme, and differs clearly from both ambers of the root and from the grey of a change.

        Would fail if the blue were too dark for a dark page or too light for a light one, or if it looked like the
        amber or the grey, so that a compared node could not be told from the root or from a node a step changes.
        """
        for theme, (page, _) in THEMES.items():
            box: tuple[float, float, float] = blend(BOX_BACKGROUND, page)
            with self.subTest(theme=theme):
                self.assertGreaterEqual(contrast(blend(COMPARED_FRAME, box), box), 3)
            # at least 25 of the distance 441 between black and white from every other frame:
            for other in (ROOT_FRAMES["light"], ROOT_FRAMES["dark"], MARK_FRAME):
                with self.subTest(theme=theme, other=other):
                    self.assertGreaterEqual(distance(COMPARED_FRAME, other, box), 25)

    def test_legend_samples_have_the_frames_of_the_tree(self) -> None:
        """The legend's grey and blue samples have the colours of the grey frame of a change and of the blue frame of
        the two compared elements.

        Would fail if the legend showed another blue or grey than the tree, or named the two the other way round.
        """
        self.assertEqual(
            [(MARK_FRAME, "grey"), (COMPARED_FRAME, "blue")],
            re.findall(
                r'<span style="box-shadow:inset 0 0 0 3px ([^;"]+);[^"]*">([^<]*)</span>',
                LEGEND,
            ),
        )


class RootFrameTest(unittest.TestCase):
    """The amber frame of the heap's root, which takes the amber of the theme."""

    def test_root_frame_stands_out_in_every_theme(self) -> None:
        """The darker amber has a contrast of at least 3 (WCAG, for what is not text) on the box of the view in
        every theme, light or dark, as it is the default where no theme is known; the film's amber has it in every
        dark theme.

        Would fail if the darker amber were too light for a light page or too dark for a dark one, or if the film's
        amber faded on a dark page.
        """
        light_themes: list[str] = [
            theme for theme, (page, _) in THEMES.items() if is_light(page)
        ]
        # the themes are light and dark ones, decided by the page's luminance:
        self.assertNotEqual([], light_themes)
        self.assertNotEqual(list(THEMES), light_themes)
        for theme, (page, _) in THEMES.items():
            box: tuple[float, float, float] = blend(BOX_BACKGROUND, page)
            shown: tuple[str, ...] = (
                ("light",) if theme in light_themes else ("light", "dark")
            )
            for name in shown:
                with self.subTest(theme=theme, frame=name):
                    self.assertGreaterEqual(
                        contrast(blend(ROOT_FRAMES[name], box), box), 3
                    )

    def test_style_chooses_the_amber_of_the_theme(self) -> None:
        """The style gives the root's frame (class rs-root) the darker amber by default and in the light themes of
        Jupyter and VS Code, and the film's amber in their dark themes and where the system's colour scheme is dark;
        the legend's amber sample has the same class.

        Would fail if a theme rule named the other amber, if a selector were misspelt, so that the theme's amber
        never applied, or if the legend showed another amber than the tree.
        """
        light: dict[str, str] = {
            "stroke": ROOT_FRAMES["light"],
            "border-color": ROOT_FRAMES["light"],
        }
        dark: dict[str, str] = {
            "stroke": ROOT_FRAMES["dark"],
            "border-color": ROOT_FRAMES["dark"],
        }
        # where the system's colour scheme is dark:
        scheme: re.Match[str] | None = DARK_SCHEME.search(BOX_STYLE)
        assert scheme, "BOX_STYLE has no rule for a dark colour scheme"
        self.assertEqual([dark], declarations(scheme.group(0), ".rs-root"))
        # by default and by the theme the page's body names:
        outside: str = DARK_SCHEME.sub("", BOX_STYLE)
        cases: tuple[tuple[str, dict[str, str]], ...] = (
            (".rs-root", light),
            ('body[data-jp-theme-light="true"] .rs-root', light),
            ("body.vscode-light .rs-root", light),
            ('body[data-jp-theme-light="false"] .rs-root', dark),
            ("body.vscode-dark .rs-root", dark),
        )
        for selector, expected in cases:
            with self.subTest(selector=selector):
                self.assertEqual([expected], declarations(outside, selector))
        # the legend's amber sample:
        self.assertEqual(
            ["rs-root"],
            re.findall(r'<span class="([^"]*)"[^>]*>amber</span>', LEGEND),
        )

    def test_plain_rule_comes_before_the_dark_scheme(self) -> None:
        """In the style, the plain rule for .rs-root comes before the rule for a dark colour scheme: both are equally
        specific, so the later one wins.

        Would fail if the two rules were swapped, so that the darker amber of the plain rule also framed the root
        where the system's colour scheme is dark.
        """
        # the plain rule names .rs-root alone, right after the end of another rule:
        plain: list[int] = [
            found.start() for found in re.finditer(r"\}\s*\.rs-root\s*\{", BOX_STYLE)
        ]
        self.assertEqual(1, len(plain))
        scheme: re.Match[str] | None = DARK_SCHEME.search(BOX_STYLE)
        assert scheme, "BOX_STYLE has no rule for a dark colour scheme"
        self.assertLess(plain[0], scheme.start())


class TreeTest(unittest.TestCase):
    """The heap drawn as a tree, read off the SVG's rectangles, lines and texts. Each part is found by the class that
    names it: node (rs-node, the root also rs-root, an inner node of a bulk load also rs-inner), grey mark (rs-marked),
    blue frame of a compared element (rs-compared), edge (rs-edge, between the two compared elements rs-compared-edge),
    value (rs-value) and place (rs-place). The sizes are written as numbers (a frame 4 around its node, a place 6 left
    of it, fonts of 14 and 10, node outlines of 3 (root) and 1, blue frames of 3, edges of 1.5 and, between the compared
    elements, 6.0), not taken from the module's constants, so that the tests pin the drawing as it is.
    """

    def setUp(self) -> None:
        """Traces the slides' example and finds where its four places are drawn, each at the middle of its node's top
        edge: with M = 4 the tree has three levels, the lowest with room for four places.
        """
        self.frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        self.anchors: list[tuple[float, float]] = [
            node_anchor(place, 4) for place in range(SLIDES_MEMORY)
        ]

    def test_bulk_load_frame(self) -> None:
        """While the bulk load compares 30 at place 0 with its smaller child 10 at place 2, the root is framed amber,
        the inner nodes 0 and 1 are dashed, a blue frame surrounds each of places 0 and 2, the values 30 20 10 40 stand
        in their nodes and the places 0 to 3 left of them, all in the theme's colour, the values in a larger font than
        the places.

        Would fail if the class rs-root or the amber moved to another node, if a leaf were dashed, if a blue frame
        surrounded another place than the two compared or had another size than the grey one, if a value or a place
        were drawn at another node than the heap array's, if a node, a value or a place changed its size, or if a part
        of the tree lost the class that names it.
        """
        frame: Frame = self.frames[
            frame_with(self.frames, "30 and its smaller child 10: 10 < 30")
        ]
        svg: str = heap_svg(frame, SLIDES_MEMORY)
        # every rectangle and text is one of the parts, node by node, a blue frame right after the nodes compared:
        self.assertEqual(
            [
                "rs-node rs-root rs-inner",
                "rs-compared",
                "rs-node rs-inner",
                "rs-node",
                "rs-compared",
                "rs-node",
            ],
            [rect.get("class") for rect in rects(svg)],
        )
        self.assertEqual(
            ["rs-value", "rs-place"] * SLIDES_MEMORY,
            [found.get("class") for found, _ in texts(svg)],
        )
        # the root framed amber (the darker amber without the style), the inner nodes 0 and 1 dashed:
        nodes: list[dict[str, str]] = [
            rect for rect in rects(svg) if has_class(rect, "rs-node")
        ]
        self.assertEqual(
            [
                (True, ROOT_FRAMES["light"], "3", True, "5 3"),
                (False, LINE_COLOUR, "1", True, "5 3"),
                (False, LINE_COLOUR, "1", False, None),
                (False, LINE_COLOUR, "1", False, None),
            ],
            [
                (
                    has_class(rect, "rs-root"),
                    rect["stroke"],
                    rect["stroke-width"],
                    has_class(rect, "rs-inner"),
                    rect.get("stroke-dasharray"),
                )
                for rect in nodes
            ],
        )
        # each node at its place, NODE_WIDTH wide and NODE_HEIGHT high:
        self.assertEqual(
            [
                (x - NODE_WIDTH / 2, y, str(NODE_WIDTH), str(NODE_HEIGHT))
                for x, y in self.anchors
            ],
            [
                (float(rect["x"]), float(rect["y"]), rect["width"], rect["height"])
                for rect in nodes
            ],
        )
        # a blue frame around each of places 0 and 2, 4 pixels outside the node, as the grey one:
        self.assertEqual(
            [
                (
                    self.anchors[place][0] - NODE_WIDTH / 2 - 4,
                    self.anchors[place][1] - 4,
                    str(NODE_WIDTH + 8),
                    str(NODE_HEIGHT + 8),
                    "none",
                    COMPARED_FRAME,
                    "3",
                )
                for place in (0, 2)
            ],
            [
                (
                    float(rect["x"]),
                    float(rect["y"]),
                    rect["width"],
                    rect["height"],
                    rect["fill"],
                    rect["stroke"],
                    rect["stroke-width"],
                )
                for rect in rects(svg)
                if has_class(rect, "rs-compared")
            ],
        )
        # the values in their nodes, in font size 14:
        self.assertEqual(
            [
                (value, x, y + NODE_HEIGHT / 2, "14")
                for value, (x, y) in zip(("30", "20", "10", "40"), self.anchors)
            ],
            [
                (text, float(found["x"]), float(found["y"]), found["font-size"])
                for found, text in texts(svg)
                if has_class(found, "rs-value")
            ],
        )
        # the places 6 pixels left of their nodes, in font size 10:
        self.assertEqual(
            [
                (str(place), x - NODE_WIDTH / 2 - 6, y + NODE_HEIGHT / 2, "10")
                for place, (x, y) in enumerate(self.anchors)
            ],
            [
                (text, float(found["x"]), float(found["y"]), found["font-size"])
                for found, text in texts(svg)
                if has_class(found, "rs-place")
            ],
        )
        # all text in the theme's colour:
        self.assertEqual(
            {"currentColor"}, {found.get("fill") for found, _ in texts(svg)}
        )

    def test_empty_root(self) -> None:
        """Once 10 is written, the root's node is drawn without fill and without a value, as large as the other
        nodes, and framed grey, as the slides mark the empty root; 20 30 40 stand at the places 1 to 3.

        Would fail if the empty root showed the element just written or a fill of the run's colour, if it lost the
        class rs-root, its grey frame or its size, or if the other values moved up a place.
        """
        frame: Frame = self.frames[frame_with(self.frames, "Remove top element 10")]
        svg: str = heap_svg(frame, SLIDES_MEMORY)
        nodes: list[dict[str, str]] = [
            rect for rect in rects(svg) if has_class(rect, "rs-node")
        ]
        # the root without fill, the others in the colour of run 0, all NODE_WIDTH wide and NODE_HEIGHT high:
        size: tuple[str, str] = (str(NODE_WIDTH), str(NODE_HEIGHT))
        self.assertEqual(
            [("none", *size)] + [(run_colour(0), *size)] * 3,
            [(rect["fill"], rect["width"], rect["height"]) for rect in nodes],
        )
        self.assertEqual("rs-node rs-root", nodes[0].get("class"))
        # one grey frame, around the empty root:
        root_x, root_y = self.anchors[0]
        self.assertEqual(
            [(root_x - NODE_WIDTH / 2 - 4, root_y - 4, MARK_FRAME)],
            [
                (float(rect["x"]), float(rect["y"]), rect["stroke"])
                for rect in rects(svg)
                if has_class(rect, "rs-marked")
            ],
        )
        # every place keeps its label, the empty root included, and only places 1 to 3 show a value:
        self.assertEqual(
            ["rs-place"] + ["rs-value", "rs-place"] * 3,
            [found.get("class") for found, _ in texts(svg)],
        )
        # the values of places 1 to 3 only, in font size 14:
        self.assertEqual(
            [
                (value, x, y + NODE_HEIGHT / 2, "14")
                for value, (x, y) in zip(("20", "30", "40"), self.anchors[1:])
            ],
            [
                (text, float(found["x"]), float(found["y"]), found["font-size"])
                for found, text in texts(svg)
                if has_class(found, "rs-value")
            ],
        )

    def test_compared_edge_is_blue_and_wide(self) -> None:
        """While the bulk load compares 30 at place 0 with 10 at place 2, the edge between the two is blue and four
        times as wide as the other edges; while it compares 20 at place 1 with 40 at place 3, the edge between those;
        and so after an output, while 25 at place 1 is compared with its only child 40 at place 3; every edge leads
        from the bottom of the parent's node to the top of the child's.

        Would fail if the wide edge led to the other child or to the parent's parent, if other edges were drawn blue
        or wide, if the sift after an output were drawn without it, or if an edge lost the class that names it.
        """
        # per frame: the classes of the edges to places 1, 2 and 3:
        cases: tuple[tuple[str, list[str]], ...] = (
            (
                "30 and its smaller child 10: 10 < 30",
                ["rs-edge", "rs-compared-edge", "rs-edge"],
            ),
            ("Sift down 20 from place 1", ["rs-edge", "rs-edge", "rs-compared-edge"]),
            (
                "25 at place 1: its only child is 40",
                ["rs-edge", "rs-edge", "rs-compared-edge"],
            ),
        )
        # the widths as written into the SVG, 1.5 and four times that:
        style: dict[str, tuple[str, str]] = {
            "rs-edge": (LINE_COLOUR, "1.5"),
            "rs-compared-edge": (COMPARED_FRAME, "6.0"),
        }
        for start, classes in cases:
            with self.subTest(frame=start):
                svg: str = heap_svg(
                    self.frames[frame_with(self.frames, start)], SLIDES_MEMORY
                )
                self.assertEqual(
                    [
                        (
                            name,
                            *style[name],
                            self.anchors[(place - 1) // 2][0],
                            self.anchors[(place - 1) // 2][1] + NODE_HEIGHT,
                            *self.anchors[place],
                        )
                        for name, place in zip(classes, range(1, SLIDES_MEMORY))
                    ],
                    [
                        (
                            line["class"],
                            line["stroke"],
                            line["stroke-width"],
                            float(line["x1"]),
                            float(line["y1"]),
                            float(line["x2"]),
                            float(line["y2"]),
                        )
                        for line in lines(svg)
                    ],
                )
                # the edge between the two compared elements is four times as wide as the others:
                widths: dict[str, float] = {
                    line["class"]: float(line["stroke-width"]) for line in lines(svg)
                }
                self.assertEqual(4 * widths["rs-edge"], widths["rs-compared-edge"])

    def test_compared_children_have_no_wide_edge(self) -> None:
        """While a sift compares the two children of the sinking element, a blue frame surrounds each of the two
        children's places, 1 and 2, and no edge is blue or wide, as neither child is the other's parent: in the bulk
        load (30's children 20 and 10), whose inner nodes are dashed, and after an output (25's children 20 and 30),
        where no node is dashed.

        Would fail if the blue frames surrounded the sinking element instead of a child, if an edge to one of the
        children were drawn wide although the parent is not compared, or if the sift after an output showed the
        dashes of a bulk load.
        """
        # per frame: the start of its caption and whether the inner nodes are dashed:
        cases: tuple[tuple[str, bool], ...] = (
            ("Sift down 30 from place 0: its children are 20 and 10", True),
            ("Sift down 25 from place 0: its children are 20 and 30", False),
        )
        for start, dashed in cases:
            with self.subTest(frame=start):
                svg: str = heap_svg(
                    self.frames[frame_with(self.frames, start)], SLIDES_MEMORY
                )
                # the blue frames, 4 pixels outside the nodes of places 1 and 2:
                self.assertEqual(
                    [
                        (
                            self.anchors[place][0] - NODE_WIDTH / 2 - 4,
                            self.anchors[place][1] - 4,
                            COMPARED_FRAME,
                        )
                        for place in (1, 2)
                    ],
                    [
                        (float(rect["x"]), float(rect["y"]), rect["stroke"])
                        for rect in rects(svg)
                        if has_class(rect, "rs-compared")
                    ],
                )
                # three plain edges, and the dashed inner nodes (class and dashes) only in the bulk load:
                self.assertEqual(
                    ([("rs-edge", LINE_COLOUR, "1.5")] * 3, dashed, dashed),
                    (
                        [
                            (line["class"], line["stroke"], line["stroke-width"])
                            for line in lines(svg)
                        ],
                        any(has_class(rect, "rs-inner") for rect in rects(svg)),
                        "stroke-dasharray" in svg,
                    ),
                )

    def test_swap_and_leaf_frames_mark_grey(self) -> None:
        """When 30 swaps with its smaller child 10, a grey frame surrounds each of places 0 and 2; when 30 has
        reached the leaf place 2, a grey frame surrounds place 2 only; neither frame has a blue frame or a wide edge.

        Would fail if a swap marked only one of its places, if the end of a sift marked another place than the one
        the element reached, or if the blue of the comparison stayed on after it.
        """
        swap: int = frame_with(self.frames, "30 swaps with its smaller child 10")
        cases: tuple[tuple[int, tuple[int, ...]], ...] = (
            (swap, (0, 2)),
            (swap + 1, (2,)),
        )
        for position, places in cases:
            frame: Frame = self.frames[position]
            with self.subTest(frame=frame.caption):
                svg: str = heap_svg(frame, SLIDES_MEMORY)
                self.assertEqual(
                    [
                        (
                            self.anchors[place][0] - NODE_WIDTH / 2 - 4,
                            self.anchors[place][1] - 4,
                        )
                        for place in places
                    ],
                    [
                        (float(rect["x"]), float(rect["y"]))
                        for rect in rects(svg)
                        if has_class(rect, "rs-marked")
                    ],
                )
                self.assertEqual(
                    ([], ["rs-edge"] * 3),
                    (
                        [rect for rect in rects(svg) if has_class(rect, "rs-compared")],
                        [line["class"] for line in lines(svg)],
                    ),
                )
        self.assertEqual(
            "30 at place 2 has reached a leaf", self.frames[swap + 1].caption
        )

    def test_empty_heap(self) -> None:
        """An empty heap, as at the start, draws no node and no text.

        Would fail if the tree drew the M places of an empty heap, which would look like a heap of empty elements.
        """
        svg: str = heap_svg(self.frames[0], SLIDES_MEMORY)
        self.assertEqual(([], []), (rects(svg), texts(svg)))


# the notebook that shows the playground:
NOTEBOOK: Path = (
    Path(__file__).parents[3] / "notebooks" / "Replacement-Selection-Playground.ipynb"
)


class NotebookTest(unittest.TestCase):
    """The notebook that shows the playground."""

    def test_code_cells_open_collapsed(self) -> None:
        """The notebook has two code cells, and each opens with its code collapsed, so that the playground comes
        first.

        Would fail if saving the notebook dropped the cells' "source_hidden" metadata.
        """
        notebook_cells: list[dict[str, Any]] = json.loads(
            NOTEBOOK.read_text(encoding="utf-8")
        )["cells"]
        code_cells: list[dict[str, Any]] = [
            cell for cell in notebook_cells if cell["cell_type"] == "code"
        ]
        self.assertEqual(2, len(code_cells))
        for cell in code_cells:
            self.assertEqual({"source_hidden": True}, cell["metadata"].get("jupyter"))

    def test_introduction_comes_before_the_setup(self) -> None:
        """The introduction, the one cell with the heading "# Replacement Selection Playground", stands before the
        first code cell, as in the MVCC and RAID playgrounds.

        Would fail if the notebook opened with the cell that sets up the import path, or if the heading moved below
        the code.
        """
        notebook_cells: list[dict[str, Any]] = json.loads(
            NOTEBOOK.read_text(encoding="utf-8")
        )["cells"]
        first_code: int = next(
            index
            for index, cell in enumerate(notebook_cells)
            if cell["cell_type"] == "code"
        )
        # the one cell with the heading as a line of its own, before the first code cell:
        headings: list[int] = [
            index
            for index, cell in enumerate(notebook_cells)
            if "# Replacement Selection Playground"
            in "".join(cell["source"]).splitlines()
        ]
        self.assertEqual(1, len(headings))
        self.assertLess(headings[0], first_code)


class ReplacementSelectionPlaygroundTest(unittest.TestCase):
    """The playground's widgets, driven through their values and button clicks."""

    def test_defaults(self) -> None:
        """The playground starts with the slides' example and M = 4 at the first of its 34 frames, which leave out the
        steps of heap maintenance, as the checkbox "Heap maintenance step by step" beside M is off; n and the seed are
        disabled, there is no error, and the style and the legend are shown.

        Would fail if the playground started with another preset or M, or with the steps of heap maintenance, if the
        checkbox had another label or were missing from the row of M, or if n and the seed could be changed for the
        slides' example, which they do not change.
        """
        playground = ReplacementSelectionPlayground()
        # the slides' example at its first frame:
        self.assertEqual(SLIDES, playground.preset.value)
        self.assertEqual("30 20 10 40 25 73 16 26 33 50 31", playground.text.value)
        self.assertEqual(
            (SLIDES_MEMORY, 3, 12),
            (playground.memory.value, playground.memory.min, playground.memory.max),
        )
        self.assertEqual(
            f"step 1 of {SLIDES_FRAMES_WITHOUT_STEPS}", playground.step_label.value
        )
        # the frames without the steps of heap maintenance, the checkbox off and beside M:
        self.assertEqual(
            without_maintenance_steps(playground.traced_frames)[0], playground.frames
        )
        self.assertEqual(
            (False, "Heap maintenance step by step"),
            (
                playground.maintenance_steps.value,
                playground.maintenance_steps.description,
            ),
        )
        self.assertIn(
            [playground.memory, playground.maintenance_steps],
            [
                list(widget.children)
                for widget in descendants(playground.widget)
                if isinstance(widget, widgets.HBox)
            ],
        )
        # n and the seed are off, there is no error:
        self.assertEqual((True, True), generator_disabled(playground))
        self.assertEqual("", playground.error.value)
        # the style and the legend are shown:
        shown: list[str] = [
            widget.value
            for widget in descendants(playground.widget)
            if isinstance(widget, widgets.HTML)
        ]
        self.assertIn(BOX_STYLE, shown)
        self.assertIn(LEGEND, shown)

    def test_buttons_step_through_the_frames(self) -> None:
        """Forward and back move one frame, end and start jump to the last and the first one; each button is
        disabled where it leads nowhere.

        Would fail if a button moved by another number of frames, if the view, the caption or the step label did not
        follow, or if back stayed enabled at the start or forward at the end.
        """
        playground = ReplacementSelectionPlayground()
        frames: list[Frame] = playground.frames
        # at the start, only forward, next output and end lead somewhere:
        self.assertEqual((True, True, False, False, False), disabled(playground))
        self.assertEqual(
            "<b>Start: M = 4 elements fit into main memory, heap and list together</b>",
            playground.caption.value,
        )
        # forward shows the second frame:
        press(playground.forward_button)
        self.assertEqual(
            f"step 2 of {SLIDES_FRAMES_WITHOUT_STEPS}", playground.step_label.value
        )
        self.assertEqual(
            "<b>Load next 4 elements from input sequence into the list</b>",
            playground.caption.value,
        )
        self.assertEqual(
            frame_html(frames[1], SLIDES_VALUES, SLIDES_MEMORY), playground.view.value
        )
        self.assertEqual((False, False, False, False, False), disabled(playground))
        # end shows the last frame, where forward, next output and end lead nowhere:
        press(playground.end_button)
        self.assertEqual(
            f"step {SLIDES_FRAMES_WITHOUT_STEPS} of {SLIDES_FRAMES_WITHOUT_STEPS}",
            playground.step_label.value,
        )
        self.assertEqual(
            "<b>Continue… and end: 11 elements in 2 runs (6 5), on average 5.5 = 1.4 × M</b>",
            playground.caption.value,
        )
        self.assertEqual((False, False, True, True, True), disabled(playground))
        # back goes one frame back:
        press(playground.back_button)
        self.assertEqual(
            f"step {SLIDES_FRAMES_WITHOUT_STEPS - 1} of {SLIDES_FRAMES_WITHOUT_STEPS}",
            playground.step_label.value,
        )
        self.assertEqual(
            "<b>Remove top element 50 from heap and write it to output run 1</b>",
            playground.caption.value,
        )
        # start goes back to the first frame:
        press(playground.start_button)
        self.assertEqual(
            f"step 1 of {SLIDES_FRAMES_WITHOUT_STEPS}", playground.step_label.value
        )
        self.assertEqual(
            frame_html(frames[0], SLIDES_VALUES, SLIDES_MEMORY), playground.view.value
        )
        self.assertEqual((True, True, False, False, False), disabled(playground))

    def test_next_output_button(self) -> None:
        """The button "next output ⏩" jumps from the start to the frame that writes 10, step 5 of 34 with heap
        maintenance shown without its steps (the default) and step 11 of 85 with them, and from there from output to
        output, in order, to the last frame, where it is disabled with forward and end.

        Would fail if the button stopped at draws, comparisons, swaps, half orders or bulk loads, skipped an output,
        jumped by the positions of all frames while the playground shows fewer, or stayed enabled at the end, where it
        leads nowhere.
        """
        playground = ReplacementSelectionPlayground()
        self.assertEqual(
            "next output ⏩\ufe0e", playground.next_output_button.description
        )
        # the caption of the last frame:
        end: str = (
            "<b>Continue… and end: 11 elements in 2 runs (6 5), on average 5.5 = 1.4 × M</b>"
        )
        # per setting of the checkbox: the number of frames shown and the step that writes 10:
        cases: tuple[tuple[bool, int, int], ...] = (
            (False, SLIDES_FRAMES_WITHOUT_STEPS, 5),
            (True, SLIDES_ALL_FRAMES, 11),
        )
        for steps, count, first_output in cases:
            with self.subTest(maintenance_steps=steps):
                playground.maintenance_steps.value = steps
                press(playground.start_button)
                self.assertEqual(
                    (True, True, False, False, False), disabled(playground)
                )
                # the first press skips the load and the bulk load:
                press(playground.next_output_button)
                self.assertEqual(
                    f"step {first_output} of {count}", playground.step_label.value
                )
                self.assertEqual(SLIDES_OUTPUT_LABELS[0], playground.caption.value)
                # the next presses visit the other outputs, then the end:
                captions: list[str] = [playground.caption.value]
                for _ in range(count):
                    if playground.next_output_button.disabled:
                        break
                    press(playground.next_output_button)
                    captions.append(playground.caption.value)
                self.assertEqual(SLIDES_OUTPUT_LABELS + [end], captions)
                # at the end, next output is off with forward and end:
                self.assertEqual(
                    f"step {count} of {count}", playground.step_label.value
                )
                self.assertEqual((False, False, True, True, True), disabled(playground))

    def test_go_outside_the_frames(self) -> None:
        """A position past the last frame shows the last frame, a position before the first one the first frame,
        with the buttons set for that frame.

        Would fail if a late click past either end raised an IndexError, or if a negative position showed a frame
        counted from the end.
        """
        playground = ReplacementSelectionPlayground()
        frames: list[Frame] = playground.frames
        # past the end:
        playground.go(SLIDES_FRAMES_WITHOUT_STEPS + 5)
        self.assertEqual(
            f"step {SLIDES_FRAMES_WITHOUT_STEPS} of {SLIDES_FRAMES_WITHOUT_STEPS}",
            playground.step_label.value,
        )
        self.assertEqual(
            frame_html(frames[-1], SLIDES_VALUES, SLIDES_MEMORY), playground.view.value
        )
        self.assertEqual((False, False, True, True, True), disabled(playground))
        # before the start:
        playground.go(-3)
        self.assertEqual(
            f"step 1 of {SLIDES_FRAMES_WITHOUT_STEPS}", playground.step_label.value
        )
        self.assertEqual(
            frame_html(frames[0], SLIDES_VALUES, SLIDES_MEMORY), playground.view.value
        )
        self.assertEqual((True, True, False, False, False), disabled(playground))

    def test_symbols_of_the_buttons_are_text(self) -> None:
        """The buttons read "⏮ start", "◀ back", "forward ▶", "next output ⏩" and "end ⏭", in this order: each of
        ⏮, ⏩ and ⏭ is followed by the variation selector U+FE0E, which asks for the symbol as text.

        Would fail if the start or the end button lost its variation selector, so that its symbol showed as a coloured
        emoji beside the plain ◀ and ▶, or if the selector stood before the symbol, where it selects nothing.
        """
        playground = ReplacementSelectionPlayground()
        self.assertEqual(
            (
                "⏮\ufe0e start",
                "◀ back",
                "forward ▶",
                "next output ⏩\ufe0e",
                "end ⏭\ufe0e",
            ),
            (
                playground.start_button.description,
                playground.back_button.description,
                playground.forward_button.description,
                playground.next_output_button.description,
                playground.end_button.description,
            ),
        )


class RetraceTest(unittest.TestCase):
    """A change of the preset, n, the seed, the input text or M traces the input anew."""

    def test_preset_retraces(self) -> None:
        """Choosing the sorted preset puts its input into the text, enables n and the seed, and shows the first of
        its frames; a change of n draws the input anew.

        Would fail if a preset did not reach the text or the frames, if the playground stayed at the step it showed,
        or if n were ignored.
        """
        playground = ReplacementSelectionPlayground()
        press(playground.forward_button)
        press(playground.forward_button)
        self.assertEqual(
            f"step 3 of {SLIDES_FRAMES_WITHOUT_STEPS}", playground.step_label.value
        )
        # the sorted preset, at its first frame:
        playground.preset.value = SORTED
        expected: tuple[int, ...] = preset_values(SORTED, DEFAULT_COUNT, DEFAULT_SEED)
        self.assertEqual(
            (expected, format_values(expected)),
            (playground.values, playground.text.value),
        )
        self.assertEqual(
            f"step 1 of {len(shown_frames(expected, SLIDES_MEMORY))}",
            playground.step_label.value,
        )
        self.assertEqual((False, False), generator_disabled(playground))
        # a sorted input is a single run:
        self.assertEqual({0}, {written.run for written in playground.frames[-1].output})
        # n = 10 draws ten values, shown from the first of their frames:
        press(playground.forward_button)
        self.assertEqual(
            f"step 2 of {len(shown_frames(expected, SLIDES_MEMORY))}",
            playground.step_label.value,
        )
        playground.count.value = 10
        ten: tuple[int, ...] = preset_values(SORTED, 10, DEFAULT_SEED)
        self.assertEqual((SORTED, ten), (playground.preset.value, playground.values))
        self.assertEqual(
            f"step 1 of {len(shown_frames(ten, SLIDES_MEMORY))}",
            playground.step_label.value,
        )

    def test_seed_redraws(self) -> None:
        """A change of the seed draws the input of a generated preset anew and shows the first of its frames.

        Would fail if the seed's observer were missing, so that a new seed left the old input in place.
        """
        playground = ReplacementSelectionPlayground()
        playground.preset.value = RANDOM
        press(playground.forward_button)
        self.assertEqual(
            f"step 2 of {len(shown_frames(preset_values(RANDOM, DEFAULT_COUNT, DEFAULT_SEED), SLIDES_MEMORY))}",
            playground.step_label.value,
        )
        # seed 2 draws another input than the default seed:
        playground.seed.value = 2
        expected: tuple[int, ...] = preset_values(RANDOM, DEFAULT_COUNT, 2)
        self.assertNotEqual(
            preset_values(RANDOM, DEFAULT_COUNT, DEFAULT_SEED), expected
        )
        self.assertEqual(
            (RANDOM, expected, format_values(expected)),
            (playground.preset.value, playground.values, playground.text.value),
        )
        self.assertEqual(
            f"step 1 of {len(shown_frames(expected, SLIDES_MEMORY))}",
            playground.step_label.value,
        )

    def test_choosing_own_input_disables_n_and_seed(self) -> None:
        """Choosing "own input" in the dropdown disables n and the seed and keeps the input and the frames.

        Would fail if n and the seed stayed enabled although they no longer change anything.
        """
        # the random preset, with n and the seed enabled:
        playground = ReplacementSelectionPlayground()
        playground.preset.value = RANDOM
        self.assertEqual((False, False), generator_disabled(playground))
        frames: list[Frame] = playground.frames
        # "own input" keeps the input and its frames, and disables both:
        playground.preset.value = OWN_INPUT
        self.assertEqual((True, True), generator_disabled(playground))
        self.assertIs(frames, playground.frames)

    def test_valid_text_switches_to_own_input(self) -> None:
        """A valid input text is traced, switches the preset to "own input" and disables n and the seed.

        Would fail if the dropdown still named the preset the text no longer holds, or if the text's values were not
        traced.
        """
        playground = ReplacementSelectionPlayground()
        playground.preset.value = RANDOM
        press(playground.forward_button)
        self.assertEqual(
            f"step 2 of {len(shown_frames(preset_values(RANDOM, DEFAULT_COUNT, DEFAULT_SEED), SLIDES_MEMORY))}",
            playground.step_label.value,
        )
        # type an input of one's own:
        playground.text.value = "5, 3 8"
        self.assertEqual(
            (OWN_INPUT, (5, 3, 8)), (playground.preset.value, playground.values)
        )
        self.assertEqual(
            f"step 1 of {len(shown_frames((5, 3, 8), SLIDES_MEMORY))}",
            playground.step_label.value,
        )
        self.assertEqual(
            [3, 5, 8],
            [written.element.value for written in playground.frames[-1].output],
        )
        self.assertEqual((True, True), generator_disabled(playground))
        self.assertEqual("", playground.error.value)

    def test_generated_preset_again_after_an_invalid_text(self) -> None:
        """An invalid text under a generated preset makes the preset "own input"; choosing that preset again draws
        its input anew with the same n and seed, clears the error and enables n and the seed again.

        Would fail if choosing the preset again changed nothing, as the dropdown would still have named it, or if the
        error stayed.
        """
        # the random preset at step 2, then an invalid text:
        playground = ReplacementSelectionPlayground()
        playground.preset.value = RANDOM
        press(playground.forward_button)
        drawn: tuple[int, ...] = preset_values(RANDOM, DEFAULT_COUNT, DEFAULT_SEED)
        playground.text.value = "30 x 10"
        self.assertEqual(
            f"step 2 of {len(shown_frames(drawn, SLIDES_MEMORY))}",
            playground.step_label.value,
        )
        self.assertEqual(
            (OWN_INPUT, drawn), (playground.preset.value, playground.values)
        )
        self.assertEqual(
            error_html("'x' is not a whole number."), playground.error.value
        )
        # the random preset again: its input, no error, n and the seed enabled, from the first frame:
        playground.preset.value = RANDOM
        self.assertEqual(
            (RANDOM, drawn, format_values(drawn), ""),
            (
                playground.preset.value,
                playground.values,
                playground.text.value,
                playground.error.value,
            ),
        )
        self.assertEqual((False, False), generator_disabled(playground))
        self.assertEqual(
            f"step 1 of {len(shown_frames(drawn, SLIDES_MEMORY))}",
            playground.step_label.value,
        )

    def test_memory_retraces(self) -> None:
        """Changing M traces the input anew with the new M, from the first frame; as the slides' example comes with
        M = 4, M = 6 turns it into an input of one's own: the preset shows "own input", n and the seed stay disabled,
        and the input and its text stay.

        Would fail if the frames kept the old M, if the playground stayed at the step it showed, or if the dropdown
        still named the slides' example, whose M the view no longer shows.
        """
        playground = ReplacementSelectionPlayground()
        for _ in range(3):
            press(playground.forward_button)
        self.assertEqual(
            f"step 4 of {SLIDES_FRAMES_WITHOUT_STEPS}", playground.step_label.value
        )
        # M = 6, from the first frame:
        playground.memory.value = 6
        self.assertEqual(
            f"step 1 of {len(shown_frames(SLIDES_VALUES, 6))}",
            playground.step_label.value,
        )
        self.assertEqual(
            "<b>Start: M = 6 elements fit into main memory, heap and list together</b>",
            playground.caption.value,
        )
        # the slides' values traced with M = 6, as an input of one's own:
        self.assertEqual(
            (OWN_INPUT, SLIDES_VALUES, 6),
            (playground.preset.value, playground.values, playground.traced_memory),
        )
        self.assertEqual(format_values(SLIDES_VALUES), playground.text.value)
        self.assertEqual((True, True), generator_disabled(playground))

    def test_slides_example_again_restores_memory(self) -> None:
        """Once M = 6 has made the slides' example an input of one's own, choosing the slides' example again sets M
        back to 4, traces its input once with M = 4 and shows step 1 of its 34 frames.

        Would fail if the dropdown had kept naming the slides' example after the change of M, so that choosing it
        again changed nothing and M stayed 6.
        """
        playground = ReplacementSelectionPlayground()
        playground.memory.value = 6
        self.assertEqual(OWN_INPUT, playground.preset.value)
        press(playground.forward_button)
        self.assertEqual(
            f"step 2 of {len(shown_frames(SLIDES_VALUES, 6))}",
            playground.step_label.value,
        )
        # the slides' example again, traced once with M = 4:
        with mock.patch(
            "system.playground.replacement_selection_widgets.trace", wraps=trace
        ) as traced:
            playground.preset.value = SLIDES
        traced.assert_called_once_with(SLIDES_VALUES, SLIDES_MEMORY)
        self.assertEqual(
            (SLIDES, SLIDES_MEMORY, SLIDES_MEMORY, format_values(SLIDES_VALUES)),
            (
                playground.preset.value,
                playground.memory.value,
                playground.traced_memory,
                playground.text.value,
            ),
        )
        # at the first of its frames:
        self.assertEqual(
            f"step 1 of {SLIDES_FRAMES_WITHOUT_STEPS}", playground.step_label.value
        )
        self.assertEqual(
            frame_html(
                shown_frames(SLIDES_VALUES, SLIDES_MEMORY)[0],
                SLIDES_VALUES,
                SLIDES_MEMORY,
            ),
            playground.view.value,
        )

    def test_memory_keeps_a_generated_preset(self) -> None:
        """With the random preset, whose input does not depend on M, a change of M traces the input anew with the new
        M and keeps the preset, with n and the seed enabled.

        Would fail if every change of M switched the preset to "own input", not only that of the slides' example.
        """
        playground = ReplacementSelectionPlayground()
        playground.preset.value = RANDOM
        random_values: tuple[int, ...] = preset_values(
            RANDOM, DEFAULT_COUNT, DEFAULT_SEED
        )
        press(playground.forward_button)
        self.assertEqual(
            f"step 2 of {len(shown_frames(random_values, SLIDES_MEMORY))}",
            playground.step_label.value,
        )
        # M = 6, from the first frame:
        playground.memory.value = 6
        self.assertEqual(
            (RANDOM, random_values, 6),
            (playground.preset.value, playground.values, playground.traced_memory),
        )
        self.assertEqual(
            f"step 1 of {len(shown_frames(random_values, 6))}",
            playground.step_label.value,
        )
        self.assertEqual((False, False), generator_disabled(playground))

    def test_invalid_text_keeps_the_frames(self) -> None:
        """An invalid input text shows what is wrong and keeps the frames and the step of the last valid input; as
        the text is no longer the preset's, the preset shows "own input", with n and the seed disabled. Choosing the
        slides' example again puts its text back, clears the error and shows step 1 of its frames. The next valid text
        clears the error as well.

        Would fail if an invalid text cleared the view or raised, if the dropdown still named the slides' example, so
        that choosing it could not put its text back, or if the error stayed after the slides' example or a valid
        text.
        """
        playground = ReplacementSelectionPlayground()
        press(playground.forward_button)
        press(playground.forward_button)
        frames: list[Frame] = playground.frames
        # an invalid text: the error, the same frames at the same step, and "own input":
        playground.text.value = "30 x 10"
        self.assertEqual(
            error_html("'x' is not a whole number."), playground.error.value
        )
        self.assertIs(frames, playground.frames)
        self.assertEqual(
            f"step 3 of {SLIDES_FRAMES_WITHOUT_STEPS}", playground.step_label.value
        )
        self.assertEqual(
            (OWN_INPUT, SLIDES_VALUES, "30 x 10"),
            (playground.preset.value, playground.values, playground.text.value),
        )
        self.assertEqual((True, True), generator_disabled(playground))
        # the slides' example again: its text, no error, step 1 of its frames:
        playground.preset.value = SLIDES
        self.assertEqual(
            (
                format_values(SLIDES_VALUES),
                "",
                f"step 1 of {SLIDES_FRAMES_WITHOUT_STEPS}",
            ),
            (
                playground.text.value,
                playground.error.value,
                playground.step_label.value,
            ),
        )
        self.assertEqual(
            frame_html(
                shown_frames(SLIDES_VALUES, SLIDES_MEMORY)[0],
                SLIDES_VALUES,
                SLIDES_MEMORY,
            ),
            playground.view.value,
        )
        # another invalid text, then a valid one, which clears the error:
        playground.text.value = "30 x 10"
        self.assertEqual(
            error_html("'x' is not a whole number."), playground.error.value
        )
        playground.text.value = "1 2 3"
        self.assertEqual("", playground.error.value)

    def test_text_after_a_failed_memory_change_takes_the_slider(self) -> None:
        """If tracing with a new M = 6 fails, the slider shows 6 while the view keeps drawing the slides' example
        with M = 4, the M it was traced with, and the preset stays the slides' example; a valid text 5 3 8 then traces
        with the slider's M = 6.

        Would fail if a valid text were traced with the M of the frames shown instead of the M the slider shows, or if
        a failed change of M switched the preset to "own input" before it traced.
        """
        playground = ReplacementSelectionPlayground()
        frames: list[Frame] = playground.frames
        # the first trace fails, the second gives the frames of 5 3 8 with M = 6:
        with mock.patch(
            "system.playground.replacement_selection_widgets.trace",
            side_effect=[
                ReplayError("The iterator did not start run 0."),
                trace((5, 3, 8), 6),
            ],
        ) as traced:
            # M = 6 fails: the slider shows 6, the view the slides' example with M = 4:
            with self.assertRaisesRegex(ReplayError, re.escape("did not start run 0")):
                playground.memory.value = 6
            self.assertEqual(
                (6, SLIDES_MEMORY, SLIDES),
                (
                    playground.memory.value,
                    playground.traced_memory,
                    playground.preset.value,
                ),
            )
            self.assertIs(frames, playground.frames)
            self.assertEqual(
                frame_html(frames[0], SLIDES_VALUES, SLIDES_MEMORY),
                playground.view.value,
            )
            # a valid text, traced with the slider's M:
            playground.text.value = "5 3 8"
        self.assertEqual(
            [mock.call(SLIDES_VALUES, 6), mock.call((5, 3, 8), 6)],
            traced.call_args_list,
        )
        self.assertEqual(
            ((5, 3, 8), 6, OWN_INPUT),
            (playground.values, playground.traced_memory, playground.preset.value),
        )
        self.assertEqual(
            frame_html(shown_frames((5, 3, 8), 6)[0], (5, 3, 8), 6),
            playground.view.value,
        )

    def test_slides_example_resets_memory(self) -> None:
        """Choosing the slides' example sets M back to 4, the M of the slides; another preset keeps M.

        Would fail if the slides' example were shown with another M than the slides', or if every preset reset M.
        """
        playground = ReplacementSelectionPlayground()
        playground.preset.value = RANDOM
        playground.memory.value = 9
        # another generated preset keeps M:
        playground.preset.value = SORTED
        self.assertEqual(9, playground.memory.value)
        press(playground.forward_button)
        self.assertEqual(
            f"step 2 of {len(shown_frames(preset_values(SORTED, DEFAULT_COUNT, DEFAULT_SEED), 9))}",
            playground.step_label.value,
        )
        # the slides' example sets it back to 4, traced once with M = 4, at the first frame:
        with mock.patch(
            "system.playground.replacement_selection_widgets.trace", wraps=trace
        ) as traced:
            playground.preset.value = SLIDES
        traced.assert_called_once_with(SLIDES_VALUES, SLIDES_MEMORY)
        self.assertEqual(SLIDES_MEMORY, playground.memory.value)
        self.assertEqual(format_values(SLIDES_VALUES), playground.text.value)
        self.assertEqual(
            f"step 1 of {SLIDES_FRAMES_WITHOUT_STEPS}", playground.step_label.value
        )
        self.assertEqual((True, True), generator_disabled(playground))

    def test_failing_trace_changes_nothing(self) -> None:
        """If tracing fails with ``ReplayError``, choosing another preset, typing a valid text or changing M raises
        it and changes nothing: the input, the frames, the M they were traced with, the step shown, the view and the
        other controls stay, only the control changed shows its new value; forward then shows the next of the old
        frames, drawn with the old M.

        With the random preset and M = 9, choosing the slides' example would set M to 4: the slider stays at 9. A
        valid text would switch the preset to "own input": the preset stays random. A new M = 6 shows on the slider,
        but the view keeps drawing the frames with M = 9, the M they were traced with.

        Would fail if a handler changed a control or the playground's state before it traced, so that the controls
        named another input or M than the frames shown, or if the view drew the frames with the slider's M.
        """
        random_values: tuple[int, ...] = preset_values(
            RANDOM, DEFAULT_COUNT, DEFAULT_SEED
        )
        # per control, its new value and the call of trace that fails:
        cases: tuple[tuple[str, str | int, tuple[tuple[int, ...], int]], ...] = (
            ("preset", SLIDES, (SLIDES_VALUES, SLIDES_MEMORY)),
            ("text", "5 3 8", ((5, 3, 8), 9)),
            ("memory", 6, (random_values, 6)),
        )
        for name, value, call in cases:
            with self.subTest(control=name):
                # the random preset with M = 9, at its fourth frame:
                playground = ReplacementSelectionPlayground()
                playground.preset.value = RANDOM
                playground.memory.value = 9
                for _ in range(3):
                    press(playground.forward_button)
                frames: list[Frame] = playground.frames
                before: State = state_of(playground)
                self.assertEqual(
                    (random_values, 9, 3),
                    (before.values, before.traced_memory, before.position),
                )
                # the change, whose trace fails:
                control: widgets.ValueWidget = getattr(playground, name)
                with mock.patch(
                    "system.playground.replacement_selection_widgets.trace",
                    side_effect=ReplayError("The iterator did not start run 0."),
                ) as traced:
                    with self.assertRaisesRegex(
                        ReplayError, re.escape("did not start run 0")
                    ):
                        control.value = value
                traced.assert_called_once_with(*call)
                # only the control changed shows its new value:
                self.assertIs(frames, playground.frames)
                self.assertEqual(before._replace(**{name: value}), state_of(playground))
                # forward shows the next of the old frames, drawn with the M they were traced with:
                press(playground.forward_button)
                self.assertEqual(
                    f"step 5 of {len(frames)}", playground.step_label.value
                )
                self.assertEqual(
                    frame_html(frames[4], random_values, 9), playground.view.value
                )


class MaintenanceStepsTest(unittest.TestCase):
    """The checkbox "Heap maintenance step by step", which shows the steps of heap maintenance or leaves them out."""

    def test_frames_without_and_with_the_steps(self) -> None:
        """Off, as at the start, the playground shows the 34 frames of the slides' example without the steps of heap
        maintenance, none of them with the blue pair, a wide edge or dashes; switched on, all 85 frames of the trace:
        21 compare two places and show the blue pair, 14 of them, which compare an element with its child, the wide
        edge between the two, and the 18 frames from the start of each bulk load to its last step (7 in run 0, 11 in
        run 1) show the dashes; switched off again, the 34 frames.

        By hand, the comparisons: the bulk load of run 0 makes 3 (20 with its only child 40; 30's children 20 and 10;
        30 with 10), the sifts after the outputs 10, 20, 25 and 30 make 3, 3, 2 and 1 (25's children, 25 with 20, 25
        with its only child 40; 73's children, 73 with 25, 73 with its only child 40; 73's children, 73 with 30; 73
        with its only child 40), the bulk load of run 1 makes 4 (33 with its only child 16; 50's children 16 and 26;
        50 with 16; 50 with its only child 33), and the sifts after the outputs 16, 26 and 31 make 2, 2 and 1 (31's
        children, 31 with 26; 50's children, 50 with 31; 50 with its only child 33): 21 in all, of which 7 compare two
        children, which no edge joins. The dashes: in run 0 the start, the order, the comparison of 20, the two of 30,
        its swap and its end at a leaf; in run 1 the start, the order, the comparison of 33, its swap and its end at a
        leaf, the two comparisons of 50 at the root, its swap, its comparison at place 1, its swap and its end at a
        leaf.

        Would fail if the checkbox changed nothing, if a step of heap maintenance or the dashes were shown while it
        is off, if two compared children were joined by a wide edge, or if switching it off again kept the frames with
        the steps.
        """
        playground = ReplacementSelectionPlayground()
        # per setting, in the order switched: the frames shown (all of the trace, or those without the steps of heap
        # maintenance), and how many of them show the blue pair, the wide edge and the dashes:
        cases: tuple[tuple[bool, list[Frame], int, int, int], ...] = (
            (False, without_maintenance_steps(playground.traced_frames)[0], 0, 0, 0),
            (True, playground.traced_frames, 21, 14, 18),
            (False, without_maintenance_steps(playground.traced_frames)[0], 0, 0, 0),
        )
        for steps, frames, compared, wide, dashed in cases:
            playground.maintenance_steps.value = steps
            press(playground.start_button)
            with self.subTest(maintenance_steps=steps):
                self.assertEqual(frames, playground.frames)
                self.assertEqual(
                    SLIDES_ALL_FRAMES if steps else SLIDES_FRAMES_WITHOUT_STEPS,
                    len(playground.frames),
                )
                # every frame shown, from the start to the end:
                views: list[str] = []
                for _ in frames:
                    views.append(playground.view.value)
                    press(playground.forward_button)
                self.assertEqual(
                    f"step {len(frames)} of {len(frames)}", playground.step_label.value
                )
                # the frames with the blue pair, with the wide edge, with inner nodes (rs-inner) and with dashes:
                self.assertEqual(
                    (compared, wide, dashed, dashed),
                    (
                        sum(
                            any(has_class(rect, "rs-compared") for rect in rects(view))
                            for view in views
                        ),
                        sum(
                            any(
                                has_class(line, "rs-compared-edge")
                                for line in lines(view)
                            )
                            for view in views
                        ),
                        sum(
                            any(has_class(rect, "rs-inner") for rect in rects(view))
                            for view in views
                        ),
                        sum("stroke-dasharray" in view for view in views),
                    ),
                )

    def test_bulk_load_in_two_frames(self) -> None:
        """Off, the bulk load of run 0 shows the list 30 20 10 40 in the tree, with a grey frame around each of its
        four places and no dashes (step 3 of 34), and then the heap 10 20 30 40 with grey frames around places 0 and
        2, whose elements 30 and 10 the bulk load swapped (step 4 of 34).

        Would fail if the view drew the dashes of inner nodes that no step sifts, or did not mark on the finished heap
        the places whose element the bulk load moved.
        """
        playground = ReplacementSelectionPlayground()
        playground.maintenance_steps.value = False
        # per frame: its step, its caption, the values in the tree and the places framed grey:
        cases: tuple[tuple[int, str, list[str], tuple[int, ...]], ...] = (
            (
                3,
                "Bulkload a heap from the list: new run 0 starts",
                ["30", "20", "10", "40"],
                (0, 1, 2, 3),
            ),
            (
                4,
                "Heap maintains half order: no child is smaller than its parent",
                ["10", "20", "30", "40"],
                (0, 2),
            ),
        )
        self.check_tree_frames(playground, cases)

    def test_sift_after_an_output_in_one_frame(self) -> None:
        """Off, the sift after an output is no step of its own: the frame in which an element takes the root's place
        shows the heap after the sift, says so in its caption and frames grey its own places and those whose element
        the sift moved. After 10 is written, 25 sinks: 20 25 30 40 with places 0 and 1 framed (step 6 of 34). After
        25 is written, 73 takes the root's place and sinks: 30 40 73 with places 0 and 2 framed in the tree (place 3,
        which the heap gave up, is no node of it), and in the next frame 16 goes into place 3, behind the tree, which
        frames nothing (steps 11 and 12 of 34). After 31 is written, 50 sinks below 33: 33 50 with places 0 and 1
        framed (step 30 of 34).

        Would fail if the view showed the heap before the sift or a half order of its own, marked a place whose element
        stayed, drew the place the heap gave up as a node, or showed a comparison of the sift although its steps are
        off.
        """
        playground = ReplacementSelectionPlayground()
        playground.maintenance_steps.value = False
        # per frame: its step, its caption, the values in the tree and the places framed grey:
        cases: tuple[tuple[int, str, list[str], tuple[int, ...]], ...] = (
            (
                6,
                "Draw next element 25 from input sequence: 25 ≥ 10, so it takes the root's place in the heap and "
                "sifts down",
                ["20", "25", "30", "40"],
                (0, 1),
            ),
            (
                11,
                "The heap gives up its last place, and its last element 73 takes the root's place and sifts down",
                ["30", "40", "73"],
                (0, 2),
            ),
            (
                12,
                "16 goes into the freed place: the list's newest element, next to the heap",
                ["30", "40", "73"],
                (),
            ),
            (
                30,
                "R is empty: the heap gives up its last place, and its last element 50 takes the root's place and "
                "sifts down",
                ["33", "50"],
                (0, 1),
            ),
        )
        self.check_tree_frames(playground, cases)

    def check_tree_frames(
        self,
        playground: ReplacementSelectionPlayground,
        cases: tuple[tuple[int, str, list[str], tuple[int, ...]], ...],
    ) -> None:
        """Checks frames of the slides' example as the playground shows them with the checkbox off: per frame its step
        among the 34, its caption, the values in the tree, the places framed grey in it, and that no node is dashed
        and no element framed blue.

        @param playground: the playground, with the checkbox off
        @param cases: per frame its step, its caption, the values in the tree and the places framed grey
        """
        # M = 4 fills three levels, whose lowest has room for 4 places:
        anchors: list[tuple[float, float]] = [
            node_anchor(place, 4) for place in range(SLIDES_MEMORY)
        ]
        for step, caption, tree, marked in cases:
            playground.go(step - 1)
            view: str = playground.view.value
            with self.subTest(step=step):
                self.assertEqual(
                    (
                        f"step {step} of {SLIDES_FRAMES_WITHOUT_STEPS}",
                        f"<b>{html.escape(caption)}</b>",
                    ),
                    (playground.step_label.value, playground.caption.value),
                )
                self.assertEqual(
                    tree,
                    [
                        text
                        for found, text in texts(view)
                        if has_class(found, "rs-value")
                    ],
                )
                # the grey frames, 4 pixels outside their nodes, no blue frame and no dashes:
                self.assertEqual(
                    [
                        (anchors[place][0] - NODE_WIDTH / 2 - 4, anchors[place][1] - 4)
                        for place in marked
                    ],
                    [
                        (float(rect["x"]), float(rect["y"]))
                        for rect in rects(view)
                        if has_class(rect, "rs-marked")
                    ],
                )
                self.assertEqual(
                    [], [rect for rect in rects(view) if has_class(rect, "rs-compared")]
                )
                self.assertEqual(
                    [], [rect for rect in rects(view) if has_class(rect, "rs-inner")]
                )
                self.assertNotIn("stroke-dasharray", view)

    def test_switching_keeps_the_place(self) -> None:
        """Switching the checkbox keeps the place, without tracing anew: a frame shown either way stays shown (the
        output of 10, step 5 of 34 off and step 11 of 85 on; the end); from a step of heap maintenance, switching off
        goes to the frame before that heap maintenance (from step 9 of 85, where 30 has reached a leaf, to the start
        of the bulk load of run 0, step 3 of 34; from step 55 of 85, where the children of 50 are compared, to the
        start of the bulk load of run 1, step 23 of 34; from step 23 of 85, where 73, drawn after 20 was written, is
        compared at place 1 with its only child 40, to the draw of 73, which shows the sift's result, step 8 of 34),
        and switching on again stays at that frame.

        Would fail if a switch went back to the first frame, kept the step's number instead of its frame (step 5 of
        85 is another frame than step 5 of 34), went to the frame after a heap maintenance instead of the one before
        it, or traced the input anew.
        """
        # per case: the setting before the switch, the caption of the frame shown and its step, the step and the
        # caption after the switch, and the step after switching back:
        cases: tuple[tuple[bool, str, str, str, str, str], ...] = (
            (
                False,
                "Remove top element 10",
                "step 5 of 34",
                "step 11 of 85",
                "Remove top element 10",
                "step 5 of 34",
            ),
            (
                True,
                "Remove top element 10",
                "step 11 of 85",
                "step 5 of 34",
                "Remove top element 10",
                "step 11 of 85",
            ),
            (
                False,
                "Continue… and end",
                "step 34 of 34",
                "step 85 of 85",
                "Continue… and end",
                "step 34 of 34",
            ),
            (
                True,
                "30 at place 2 has reached a leaf",
                "step 9 of 85",
                "step 3 of 34",
                "Bulkload a heap from the list: new run 0 starts",
                "step 3 of 85",
            ),
            (
                True,
                "Sift down 50 from place 0: its children are 16 and 26",
                "step 55 of 85",
                "step 23 of 34",
                "Bulkload a heap from the list: new run 1 starts",
                "step 50 of 85",
            ),
            (
                True,
                "73 at place 1: its only child is 40",
                "step 23 of 85",
                "step 8 of 34",
                "Draw next element 73",
                "step 19 of 85",
            ),
        )
        for steps, caption, before, after, shown, back in cases:
            with self.subTest(maintenance_steps=steps, frame=caption):
                # the frame, with the checkbox as before the switch:
                playground = ReplacementSelectionPlayground()
                playground.maintenance_steps.value = steps
                playground.go(frame_with(playground.frames, caption))
                self.assertEqual(before, playground.step_label.value)
                traced_frames: list[Frame] = playground.traced_frames
                with mock.patch(
                    "system.playground.replacement_selection_widgets.trace", wraps=trace
                ) as traced:
                    # the switch shows the same frame, or the one before the heap maintenance:
                    playground.maintenance_steps.value = not steps
                    self.assertEqual(after, playground.step_label.value)
                    self.assertEqual(
                        frame_with(playground.frames, shown), playground.position
                    )
                    self.assertEqual(
                        frame_html(
                            playground.frames[playground.position],
                            SLIDES_VALUES,
                            SLIDES_MEMORY,
                        ),
                        playground.view.value,
                    )
                    # switching back:
                    playground.maintenance_steps.value = steps
                    self.assertEqual(back, playground.step_label.value)
                # neither switch traced anew:
                traced.assert_not_called()
                self.assertIs(traced_frames, playground.traced_frames)

    def test_switching_on_the_finished_heap(self) -> None:
        """The half orders of the bulk loads, each kept as a copy (with the places that changed marked) rather than as
        itself, keep their place too: that of run 0, step 4 of 34 off, is step 10 of 85 on, and that of run 1, step 24
        of 34 off, is step 61 of 85 on, in both directions, without tracing anew.

        Would fail if a copy were not found again among all frames, so that the switch went to another frame.
        """
        # per case: the checkbox before the switch, the step and the number of frames before it and after it, and the
        # heap of the half order:
        cases: tuple[tuple[bool, str, str, str], ...] = (
            (False, "step 4 of 34", "step 10 of 85", "10 20 30 40"),
            (True, "step 10 of 85", "step 4 of 34", "10 20 30 40"),
            (False, "step 24 of 34", "step 61 of 85", "16 33 26 50"),
            (True, "step 61 of 85", "step 24 of 34", "16 33 26 50"),
        )
        for steps, before, after, heap in cases:
            with self.subTest(maintenance_steps=steps, step=before):
                # the half order, with the checkbox as before the switch:
                playground = ReplacementSelectionPlayground()
                playground.maintenance_steps.value = steps
                playground.go(int(before.split()[1]) - 1)
                self.assertEqual(before, playground.step_label.value)
                self.assertEqual(
                    f"<b>{html.escape(HALF_ORDER)}</b>", playground.caption.value
                )
                with mock.patch(
                    "system.playground.replacement_selection_widgets.trace", wraps=trace
                ) as traced:
                    # the switch shows the same half order in the other list, and switching back returns:
                    playground.maintenance_steps.value = not steps
                    self.assertEqual(after, playground.step_label.value)
                    self.assertEqual(
                        heap,
                        " ".join(
                            str(element)
                            for element in playground.frames[playground.position].heap
                        ),
                    )
                    playground.maintenance_steps.value = steps
                    self.assertEqual(before, playground.step_label.value)
                traced.assert_not_called()

    def test_switching_around_a_sift_after_an_output(self) -> None:
        """The frame that shows a sift after an output, kept as a copy that shows the sift's result, stands for the
        frame before the sift: switching the checkbox on goes there, to the draw of 73 with 73 at the root (step 8 of
        34 off, step 19 of 85 on); switching it off from the half order that ends that sift, which is left out then,
        goes to the copy, which shows the same heap (step 26 of 85 on, step 8 of 34 off); switching it on again goes to
        the frame before the sift.

        Would fail if the copy were not found again among all frames, or if the half order after an output were
        looked for among the frames shown with the checkbox off, where it is left out.
        """
        # per case: the checkbox before the switch, the step before and after it, the heap shown after it, and the
        # step after switching back:
        cases: tuple[tuple[bool, str, str, str, str], ...] = (
            (False, "step 8 of 34", "step 19 of 85", "73 25 30 40", "step 8 of 34"),
            (True, "step 26 of 85", "step 8 of 34", "25 40 30 73", "step 19 of 85"),
        )
        for steps, before, after, heap, back in cases:
            with self.subTest(maintenance_steps=steps, step=before):
                playground = ReplacementSelectionPlayground()
                playground.maintenance_steps.value = steps
                playground.go(int(before.split()[1]) - 1)
                self.assertEqual(before, playground.step_label.value)
                playground.maintenance_steps.value = not steps
                self.assertEqual(
                    (after, heap),
                    (
                        playground.step_label.value,
                        " ".join(
                            str(element)
                            for element in playground.frames[playground.position].heap
                        ),
                    ),
                )
                playground.maintenance_steps.value = steps
                self.assertEqual(back, playground.step_label.value)

    def test_new_trace_keeps_the_checkbox(self) -> None:
        """A change of the preset, the input text or M keeps the checkbox as it is and shows step 1 of the new
        trace's frames: all of them with the checkbox on, those without the steps of heap maintenance with it off.

        Would fail if a new trace set the checkbox back to its default, or showed the frames of the other setting.
        """
        # per change, in order: the control, its new value, and the input and M traced:
        changes: tuple[tuple[str, str | int, tuple[int, ...], int], ...] = (
            (
                "preset",
                SORTED,
                preset_values(SORTED, DEFAULT_COUNT, DEFAULT_SEED),
                SLIDES_MEMORY,
            ),
            ("text", "5 3 8", (5, 3, 8), SLIDES_MEMORY),
            ("memory", 6, (5, 3, 8), 6),
        )
        for steps in (False, True):
            playground = ReplacementSelectionPlayground()
            playground.maintenance_steps.value = steps
            # the frames shown before the first change:
            before: int = len(shown_frames(SLIDES_VALUES, SLIDES_MEMORY, steps))
            for name, value, input_values, memory in changes:
                with self.subTest(maintenance_steps=steps, control=name):
                    # one step on, then the change:
                    press(playground.forward_button)
                    self.assertEqual(f"step 2 of {before}", playground.step_label.value)
                    control: widgets.ValueWidget = getattr(playground, name)
                    control.value = value
                    # the checkbox as it was, at the first of the frames of its setting:
                    expected: list[str] = [
                        frame.caption
                        for frame in shown_frames(input_values, memory, steps)
                    ]
                    self.assertEqual(
                        (steps, expected, f"step 1 of {len(expected)}"),
                        (
                            playground.maintenance_steps.value,
                            [frame.caption for frame in playground.frames],
                            playground.step_label.value,
                        ),
                    )
                    before = len(expected)

    def test_bulk_load_checked_with_the_steps_off(self) -> None:
        """With the checkbox off, a new input is still traced in full, so that a bulk load of the iterator that
        differs from the one replayed raises ``ReplayError``, and the playground keeps the frames of the last valid
        input.

        For 3 1 2, Floyd's method gives 1 3 2 (3 swaps with its smaller child 1); an iterator that sorts the list
        instead builds 1 2 3, which is a heap as well.

        Would fail if the playground, as it leaves out the steps of heap maintenance, took the iterator's heap on
        trust instead of replaying the bulk load and checking it.
        """

        def sort_in_place(elements: list[Element], size: int | None = None) -> None:
            """Sorts the first ``size`` elements in place, a bulk load that builds another heap than Floyd's method."""
            elements[:size] = sorted(cast(list[Element], elements[:size]))

        playground = ReplacementSelectionPlayground()
        playground.maintenance_steps.value = False
        frames: list[Frame] = playground.frames
        # the input 3 1 2, with the iterator sorting the list:
        with mock.patch("system.query_processing.sorting.bulkload", sort_in_place):
            with self.assertRaisesRegex(
                ReplayError,
                re.escape(
                    "bulk-loaded memory [1, 3, 2] differs from the iterator's [1, 2, 3]"
                ),
            ):
                playground.text.value = "3 1 2"
        # the slides' example stays, without the steps:
        self.assertIs(frames, playground.frames)
        self.assertEqual(
            (False, SLIDES_VALUES, f"step 1 of {SLIDES_FRAMES_WITHOUT_STEPS}"),
            (
                playground.maintenance_steps.value,
                playground.values,
                playground.step_label.value,
            ),
        )


class ViewTest(unittest.TestCase):
    """The HTML of the view and of the error."""

    def test_error_is_escaped(self) -> None:
        """A token like ``<b>x</b>`` appears escaped in the error, not as markup.

        Would fail if the error showed the input text as HTML, which could make the rest of the page bold or worse.
        """
        playground = ReplacementSelectionPlayground()
        playground.text.value = "30 <b>x</b> 10"
        self.assertIn(
            "&#x27;&lt;b&gt;x&lt;/b&gt;&#x27; is not a whole number.",
            playground.error.value,
        )
        self.assertNotIn("<b>", playground.error.value)

    def test_rows_of_a_frame(self) -> None:
        """In the frame where 16 goes into the freed place, the input shows the seven elements taken as empty cells
        and marks none of the others, as the step read 16, whose cell is empty now; memory shows its four places
        numbered 0 to 3: the heap 30 40 73 in the colour of run 0, the bar, and 16 marked, in the colour of run 1.

        Would fail if the list had the colour of the current run, if the input marked an element the step does not
        read (e.g. always the next one), if the bar stood elsewhere than behind the heap, or if memory had other than
        M places.
        """
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        frame: Frame = frames[frame_with(frames, "16 goes into the freed place")]
        # the input: seven empty cells, then the rest, none marked:
        self.assertEqual(
            [("rs-cell", "", "")] * 7
            + [("rs-cell", INPUT_COLOUR, value) for value in ("26", "33", "50", "31")],
            cells(input_html(frame, SLIDES_VALUES)),
        )
        # memory: the heap in the colour of run 0, the bar, 16 in the colour of the next run, marked:
        self.assertEqual(
            [
                ("rs-cell", run_colour(0), "30", "0"),
                ("rs-cell", run_colour(0), "40", "1"),
                ("rs-cell", run_colour(0), "73", "2"),
                "|",
                ("rs-cell rs-mark", run_colour(1), "16", "3"),
            ],
            memory_row(memory_html(frame)),
        )

    def test_output_runs_in_their_colours(self) -> None:
        """The last frame shows run 1 left of run 0, each in a box of its own, its elements in its run's colour, the
        newest on the left: 50 33 31 26 16, then 73 40 30 25 20 10; the title says where new elements enter.

        Would fail if a run's elements had another run's colour, if the runs were not split into boxes, or if a run
        or its elements stood in the order they were written instead of the newest first.
        """
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        shown: str = output_html(frames[-1])
        self.assertEqual(
            [
                (
                    "Run 1",
                    [
                        ("rs-cell", run_colour(1), value)
                        for value in ("50", "33", "31", "26", "16")
                    ],
                ),
                (
                    "Run 0",
                    [
                        ("rs-cell", run_colour(0), value)
                        for value in ("73", "40", "30", "25", "20", "10")
                    ],
                ),
            ],
            run_boxes(shown),
        )
        # the title, and no cell outside the boxes of the runs:
        self.assertEqual(
            ["Output runs R′ (each new element enters on the left)"],
            re.findall(r'<div class="rs-title">([^<]*)</div>', shown),
        )
        self.assertEqual(11, len(cells(shown)))

    def test_output_marks_the_element_just_written(self) -> None:
        """The frame that writes 26 frames the output cell of 26 grey and no other; the next frame marks no output.

        Would fail if the mark sat on the oldest cell of the run or on the position within the run instead of among
        all elements written, or if it stayed on after the step that writes.
        """
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        written: int = frame_with(frames, "Remove top element 26")
        # 26 marked, the newest cell of run 1, on its left:
        self.assertEqual(
            [
                (
                    "Run 1",
                    [
                        ("rs-cell rs-mark", run_colour(1), "26"),
                        ("rs-cell", run_colour(1), "16"),
                    ],
                ),
                (
                    "Run 0",
                    [
                        ("rs-cell", run_colour(0), value)
                        for value in ("73", "40", "30", "25", "20", "10")
                    ],
                ),
            ],
            run_boxes(output_html(frames[written])),
        )
        # the next frame marks no output:
        self.assertEqual(
            {"rs-cell"},
            {classes for classes, _, _ in cells(output_html(frames[written + 1]))},
        )

    def test_newest_element_enters_on_the_left(self) -> None:
        """Every element written enters on the left: after 10 and 20 the output reads 20 10; once 16 starts run 1, its
        box stands left of run 0's, 73 40 30 25 20 10; in every frame that writes, the element written is the
        leftmost cell and the only one marked. Before the first output, one empty cell holds the row's place.

        Would fail if new elements were appended on the right, if a new run's box stood right of the older ones, or if
        the grey mark sat on another cell than the element just written.
        """
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        # before the first output:
        self.assertEqual(
            ([], [("rs-cell", "", "")]),
            (run_boxes(output_html(frames[0])), cells(output_html(frames[0]))),
        )
        # after 10 and 20, 20 marked:
        self.assertEqual(
            [
                (
                    "Run 0",
                    [
                        ("rs-cell rs-mark", run_colour(0), "20"),
                        ("rs-cell", run_colour(0), "10"),
                    ],
                )
            ],
            run_boxes(output_html(frames[frame_with(frames, "Remove top element 20")])),
        )
        # after 16, the first element of run 1, marked:
        self.assertEqual(
            [
                ("Run 1", [("rs-cell rs-mark", run_colour(1), "16")]),
                (
                    "Run 0",
                    [
                        ("rs-cell", run_colour(0), value)
                        for value in ("73", "40", "30", "25", "20", "10")
                    ],
                ),
            ],
            run_boxes(output_html(frames[frame_with(frames, "Remove top element 16")])),
        )
        # in every frame that writes, the element written is the leftmost cell, the only one marked:
        writes: list[Frame] = [
            frame for frame in frames if frame.caption.startswith("Remove top element")
        ]
        self.assertEqual(11, len(writes))
        self.assertEqual(
            [
                (str(frame.output[-1].element), [str(frame.output[-1].element)])
                for frame in writes
            ],
            [
                (
                    cells(output_html(frame))[0][2],
                    [
                        text
                        for classes, _, text in cells(output_html(frame))
                        if "rs-mark" in classes.split()
                    ],
                )
                for frame in writes
            ],
        )

    def test_start_marks_the_elements_the_load_takes(self) -> None:
        """At the start, the input marks its first four elements, 30 20 10 40, which the next step loads into the
        list, and none of the others.

        Would fail if the input marked only the next element, as if the start read one element, or marked the
        elements by another rule than the frame's marks.
        """
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        self.assertEqual(
            [
                ("rs-cell rs-mark", INPUT_COLOUR, value)
                for value in ("30", "20", "10", "40")
            ]
            + [
                ("rs-cell", INPUT_COLOUR, value)
                for value in ("25", "73", "16", "26", "33", "50", "31")
            ],
            cells(input_html(frames[0], SLIDES_VALUES)),
        )

    def test_memory_text_counts_no_empty_root(self) -> None:
        """While the root's place is empty, heap and list hold 3 + 0 elements after 10 is written, and after 25 is
        written while 16, drawn, waits in the comparison box; 3 + 1 once 16 is in the list.

        Would fail if the empty root's place were counted as an element, which would show 4 + 0 or 4 + 1 > M = 4, or
        if the element that waits were counted before it stands in memory.
        """
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        # per frame: the start of its caption and the text:
        cases: tuple[tuple[str, str], ...] = (
            ("Remove top element 10", "|heap| + |list| = 3 + 0 ≤ M = 4"),
            ("Draw next element 16", "|heap| + |list| = 3 + 0 ≤ M = 4"),
            ("16 goes into the freed place", "|heap| + |list| = 3 + 1 ≤ M = 4"),
        )
        for start, text in cases:
            with self.subTest(frame=start):
                self.assertEqual(
                    text,
                    memory_text(frames[frame_with(frames, start)], SLIDES_MEMORY),
                )

    def test_places_and_run_numbers_are_escaped(self) -> None:
        """The place left of each node, the place below each cell of memory and the number below each run go through
        ``html.escape``, as every other text of the view: with ``html.escape`` replaced by a function that puts its text
        in brackets, the tree and the row of memory of the bulk load of run 0 show the places [0] to [3], and the last
        frame the runs "Run [1]" and "Run [0]".

        Would fail if a place or a run number were put into the markup as it is, so that it alone skipped the
        escaping.
        """

        def bracket(text: str) -> str:
            """Marks a text as escaped by putting it in brackets."""
            return f"[{text}]"

        # html.escape leaves digits as they are, so only a stand-in that changes its text shows that a number went
        # through it:
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        bulk_load: Frame = frames[
            frame_with(frames, "Bulkload a heap from the list: new run 0")
        ]
        with mock.patch.object(html, "escape", side_effect=bracket):
            svg: str = heap_svg(bulk_load, SLIDES_MEMORY)
            row: str = memory_html(bulk_load)
            output: str = output_html(frames[-1])
        # the places in the tree and in the row of memory, and the run numbers, each escaped:
        self.assertEqual(
            ["[0]", "[1]", "[2]", "[3]"],
            [text for found, text in texts(svg) if has_class(found, "rs-place")],
        )
        self.assertEqual(
            ["[0]", "[1]", "[2]", "[3]"],
            [item[3] for item in memory_row(row) if not isinstance(item, str)],
        )
        self.assertEqual(
            ["Run [1]", "Run [0]"], [label for label, _ in run_boxes(output)]
        )

    def test_no_javascript(self) -> None:
        """Neither the style, the legend nor the view of any frame of the slides' example holds a script or an event
        handler, with heap maintenance shown without and with its steps: the view is HTML and CSS only.

        Would fail if anything in the view were started by JavaScript, which a notebook might not run.
        """
        # a script tag, or an event handler such as onclick=:
        script: re.Pattern[str] = re.compile(r"<script|\son\w+\s*=", re.IGNORECASE)
        self.assertIsNone(script.search(BOX_STYLE))
        self.assertIsNone(script.search(LEGEND))
        for steps in (False, True):
            for frame in shown_frames(SLIDES_VALUES, SLIDES_MEMORY, steps):
                with self.subTest(maintenance_steps=steps, caption=frame.caption):
                    self.assertIsNone(
                        script.search(frame_html(frame, SLIDES_VALUES, SLIDES_MEMORY))
                    )

    def test_caption_is_escaped(self) -> None:
        """The caption of a draw into the list shows its comparison escaped, as ``16 &lt; 25``.

        Would fail if the caption were put into the HTML widget unescaped, so that ``<`` opened a tag and cut the
        caption off.
        """
        playground = ReplacementSelectionPlayground()
        playground.go(frame_with(playground.frames, "Draw next element 16"))
        self.assertEqual(
            "<b>Draw next element 16 from input sequence: 16 &lt; 25, so it goes to the list, for the next run</b>",
            playground.caption.value,
        )

    def test_caption_is_two_lines_high(self) -> None:
        """The caption is two lines high, whatever it says: its layout has a fixed height of twice the height
        ipywidgets gives a line of an HTML widget (--jp-widgets-inline-height), and a caption that needs more lines
        scrolls within it, so that the view below it stays in place when a caption wraps in a narrow window. The
        height stays at the end and after the input is traced anew.

        Would fail if the caption's height followed its text, as an HTML widget's does by default, so that a caption
        that wraps pushed the view down, if it were one line high, or if a longer caption ran over the view.
        """
        playground = ReplacementSelectionPlayground()
        # the caption's height and overflow at the start, at the end and after a new input:
        shown: list[tuple[str, str]] = [
            (playground.caption.layout.height, playground.caption.layout.overflow)
        ]
        press(playground.end_button)
        shown.append(
            (playground.caption.layout.height, playground.caption.layout.overflow)
        )
        playground.text.value = "5, 3 8"
        shown.append(
            (playground.caption.layout.height, playground.caption.layout.overflow)
        )
        self.assertEqual(
            [("calc(2 * var(--jp-widgets-inline-height))", "auto")] * 3, shown
        )
        # the new input was traced:
        self.assertEqual((5, 3, 8), playground.values)


class MemoryRowTest(unittest.TestCase):
    """Main memory as one row of M cells below the heap's tree: the heap's places, the bar, the list's places."""

    def test_row_follows_the_heap_and_the_list(self) -> None:
        """In the slides' example the bar between heap and list moves as the heap gives up places and the list grows
        towards the front, newest first. By hand, frame by frame: at the start an empty memory, all list (| _ _ _ _);
        the load, all list (| 30 20 10 40); the bulk load takes all four places as the heap (30 20 10 40 |); after 25
        is written and 16 drawn, the root's place is empty and the heap keeps its four places (_ 40 30 73 |); then the
        heap gives up place 3 (73 40 30 | _), and 16 goes there (30 40 73 | 16); after 30, 26 goes into place 2
        (40 73 | 26 16); after 40, 33 into place 1 (73 | 33 26 16); after 73, 50 takes place 0, the heap is empty
        (| 50 33 26 16); the bulk load of run 1 takes all four places again (50 33 26 16 |); writing 26 empties the
        root's place (_ 33 31 50 |); once the input is empty, the places given up stay empty (_ 33 50 | _ while 31 is
        written); at the end, memory is empty (| _ _ _ _).

        Would fail if the bar stood at a fixed place, if the list grew towards the end of memory, if a place the heap
        gave up were drawn on the heap's side of the bar, or if the bulk load moved the list.
        """
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        # per frame: the start of its caption and the row of memory as text:
        cases: tuple[tuple[str, str], ...] = (
            ("Start", "| _ _ _ _"),
            ("Load next 4 elements", "| 30 20 10 40"),
            ("Bulkload a heap from the list: new run 0", "30 20 10 40 |"),
            ("Draw next element 16", "_ 40 30 73 |"),
            ("The heap gives up its last place", "73 40 30 | _"),
            ("16 goes into the freed place", "30 40 73 | 16"),
            ("26 goes into the freed place", "40 73 | 26 16"),
            ("33 goes into the freed place", "73 | 33 26 16"),
            ("Draw next element 50", "| 50 33 26 16"),
            ("Bulkload a heap from the list: new run 1", "50 33 26 16 |"),
            ("Remove top element 26", "_ 33 31 50 |"),
            ("Remove top element 31", "_ 33 50 | _"),
            ("Continue… and end", "| _ _ _ _"),
        )
        for start, row in cases:
            # the first frame with the caption, as several start alike:
            frame: Frame = next(
                frame for frame in frames if frame.caption.startswith(start)
            )
            with self.subTest(frame=frame.caption):
                self.assertEqual(row, row_text(memory_html(frame)))

    def test_every_frame_shows_its_memory(self) -> None:
        """On the slides' example, the input that moves the list to the front and an input shorter than M (7 3 with
        M = 5), in every frame with and without the steps of heap maintenance: the row has M places numbered 0 to
        M − 1, each showing its element of memory, the bar right after the heap's places; an empty place is dashed and
        has no colour, a place of the heap has the current run's colour, one of the list the next run's; exactly the
        places of memory the frame marks are framed grey. The tree draws the heap's places only, with the same values,
        and its title names them.

        Would fail if the row showed fewer or more places than M (e.g. only those the iterator holds for a short
        input), if a value, a colour, a dash or a grey frame differed from the frame's memory and marks, or if the tree
        drew another part of memory than the heap.
        """
        cases: tuple[tuple[tuple[int, ...], int], ...] = (
            (SLIDES_VALUES, SLIDES_MEMORY),
            (SLIDES_VALUES[:8], SLIDES_MEMORY),
            ((7, 3), 5),
        )
        for input_values, memory in cases:
            for steps in (False, True):
                for position, frame in enumerate(
                    shown_frames(input_values, memory, steps)
                ):
                    with self.subTest(
                        values=input_values, steps=steps, position=position
                    ):
                        view: str = frame_html(frame, input_values, memory)
                        expected: list[tuple[str, str, str, str] | str] = []
                        for place, element in enumerate(frame.memory):
                            if place == frame.heap_size:
                                expected.append("|")
                            classes: str = "rs-cell"
                            background: str = ""
                            if element is None:
                                classes += " rs-empty"
                            else:
                                background = run_colour(
                                    frame.run
                                    if place < frame.heap_size
                                    else frame.run + 1
                                )
                            if Mark("memory", place) in frame.marks:
                                classes += " rs-mark"
                            expected.append(
                                (
                                    classes,
                                    background,
                                    "" if element is None else str(element),
                                    str(place),
                                )
                            )
                        if frame.heap_size == memory:
                            expected.append("|")
                        self.assertEqual(memory, len(frame.memory))
                        self.assertEqual(expected, memory_row(view))
                        # the tree: the heap's values, none for the root's empty place:
                        self.assertEqual(
                            [
                                str(element)
                                for element in frame.memory[: frame.heap_size]
                                if element is not None
                            ],
                            [
                                text
                                for found, text in texts(view)
                                if has_class(found, "rs-value")
                            ],
                        )
                        self.assertEqual(
                            frame.heap_size,
                            sum(has_class(rect, "rs-node") for rect in rects(view)),
                        )
                        self.assertIn(
                            f'<div class="rs-title">{html.escape(heap_title(frame))}</div>',
                            view,
                        )

    def test_short_input_keeps_m_places(self) -> None:
        """An input shorter than M, 7 3 with M = 5, shows all five places of memory in every frame; places 2 to 4,
        which the input never fills, are always empty and dashed.

        Would fail if the row showed only the two places the iterator holds, so that M could not be seen.
        """
        for frame in trace((7, 3), 5):
            with self.subTest(frame=frame.caption):
                row: list[tuple[str, str, str, str] | str] = [
                    item for item in memory_row(memory_html(frame)) if item != "|"
                ]
                self.assertEqual(
                    [str(place) for place in range(5)],
                    [item[3] for item in row],
                )
                self.assertEqual(
                    [("rs-cell rs-empty", "", "")] * 3,
                    [item[:3] for item in row[2:]],
                )

    def test_list_moved_to_the_front(self) -> None:
        """With the first eight values of the slides' input, while 73 is written the list 26 16 stands behind two
        empty places, the root's among them (_ | _ 26 16); the next frame moves it to the front, every place framed
        grey (| 26 16 _ _), and the bulk load takes its two places as the heap (26 16 | _ _).

        Would fail if the move were not shown in the row, or if the bulk load drew the list's places behind the empty
        ones as the heap.
        """
        frames: list[Frame] = trace(SLIDES_VALUES[:8], SLIDES_MEMORY)
        move: int = frame_with(frames, LIST_TO_FRONT)
        self.assertEqual(
            ["_ | _ 26 16", "| 26 16 _ _", "26 16 | _ _"],
            [row_text(memory_html(frame)) for frame in frames[move - 1 : move + 2]],
        )
        self.assertEqual(
            ["rs-cell rs-mark", "rs-cell rs-mark"] + ["rs-cell rs-empty rs-mark"] * 2,
            [
                item[0]
                for item in memory_row(memory_html(frames[move]))
                if not isinstance(item, str)
            ],
        )

    def test_heap_title(self) -> None:
        """The title above the tree names the places of memory it draws: none, place 0, or places 0 to k − 1.

        Would fail if the title named one place too many or too few.
        """
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        # per frame: the start of its caption and the title:
        cases: tuple[tuple[str, str], ...] = (
            ("Start", "heap: empty"),
            (
                "Bulkload a heap from the list: new run 0",
                "heap: places 0 to 3 of memory, as a tree",
            ),
            (
                "The heap gives up its last place",
                "heap: places 0 to 2 of memory, as a tree",
            ),
            ("33 goes into the freed place", "heap: place 0 of memory, as a tree"),
        )
        for start, title in cases:
            frame: Frame = next(
                frame for frame in frames if frame.caption.startswith(start)
            )
            with self.subTest(frame=frame.caption):
                self.assertEqual(title, heap_title(frame))

    def test_parts_of_a_frame_in_order(self) -> None:
        """A frame shows, in this order: the input, the comparison box, the heap's title and tree, the title of main
        memory with M, the row of memory, what heap and list hold, and the output.

        Would fail if a part were missing or moved, e.g. the row of memory above the tree it explains.
        """
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        frame: Frame = frames[frame_with(frames, "16 goes into the freed place")]
        self.assertEqual(
            '<div class="rs-box"><div class="rs-top">'
            + input_html(frame, SLIDES_VALUES)
            + "</div>"
            + comparison_html(frame)
            + '<div class="rs-title">heap: places 0 to 2 of memory, as a tree</div>'
            + heap_svg(frame, SLIDES_MEMORY)
            + '<div class="rs-title">main memory (M = 4 places): the heap in front, the list behind the bar</div>'
            + memory_html(frame)
            + "<div>|heap| + |list| = 3 + 1 ≤ M = 4</div>"
            + output_html(frame)
            + "</div>",
            frame_html(frame, SLIDES_VALUES, SLIDES_MEMORY),
        )

    def test_style_of_the_row(self) -> None:
        """The style dashes an empty place's lines and draws the bar as high as a cell, in the theme's text colour,
        so that it shows on light and dark pages; the input's cells, taken or not, are never dashed.

        Would fail if the class rs-empty did not dash the cell, if the bar had a fixed colour that vanishes on a dark
        or a light page, or if a taken cell of the input looked like an empty place of memory.
        """
        self.assertEqual(
            [{"border-style": "dashed"}], declarations(BOX_STYLE, ".rs-empty")
        )
        divider: list[dict[str, str]] = declarations(BOX_STYLE, ".rs-divider")
        self.assertEqual(1, len(divider))
        self.assertEqual(
            ("currentColor", f"{CELL_HEIGHT}px"),
            (divider[0]["background"], divider[0]["height"]),
        )
        frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)
        self.assertNotIn("rs-empty", input_html(frames[-1], SLIDES_VALUES))


class ComparisonBoxTest(unittest.TestCase):
    """The comparison box between the input and the heap: the last element on output, the next element of the input
    and the decision, green or red, as on the slides."""

    def setUp(self) -> None:
        """Traces the slides' example."""
        self.frames: list[Frame] = trace(SLIDES_VALUES, SLIDES_MEMORY)

    def box_at(self, position: int) -> Box:
        """Returns what the box of the frame at ``position`` shows in the view, with the flags the view passes."""
        return box_of(frame_html(self.frames[position], SLIDES_VALUES, SLIDES_MEMORY))

    def test_into_the_heap_on_green(self) -> None:
        """When 10 is written, the box shows 10 marked as the last output, 25 as the next element and "25 >= 10  →
        heap (this run)" on green, and the input marks 25; once 25 is drawn, it stands at the root, its cell of the
        input is empty, no cell of the input is marked and the box is the same but 10 is no longer marked. In all
        seven frames of the sift of 73, drawn after 20, up to the half order (its children compared, 73 compared with
        25, the swap, 73 compared with 40, the swap, the leaf, the half order), the box shows 20, 73 and
        "73 >= 20  →  heap (this run)" on green.

        Would fail if the decision appeared only at the draw, a frame later than on the slides, if the box compared
        with the root or with an element of the sift during the sift instead of with the last output, if green and red
        were swapped, or if the input marked the next element after it was drawn.
        """
        # the colour for the heap is green:
        red, green, _, _ = rgba(GREEN)
        self.assertGreater(green, red)
        # the frame that writes 10 decides already, and the input marks 25:
        written: int = frame_with(self.frames, "Remove top element 10")
        decided: Box = Box(
            "10", True, "25", (GREEN, "25 >= 10  →  heap (this run)"), None
        )
        self.assertEqual(decided, self.box_at(written))
        rest: list[tuple[str, str, str]] = [
            ("rs-cell", INPUT_COLOUR, value)
            for value in ("73", "16", "26", "33", "50", "31")
        ]
        self.assertEqual(
            [("rs-cell", "", "")] * 4
            + [("rs-cell rs-mark", INPUT_COLOUR, "25")]
            + rest,
            cells(input_html(self.frames[written], SLIDES_VALUES)),
        )
        # the draw: 25 at the root, its cell of the input empty, no cell marked, the box the same but 10 unmarked:
        drawn: int = frame_with(self.frames, "Draw next element 25")
        self.assertEqual(decided._replace(marked=False), self.box_at(drawn))
        self.assertEqual(
            [("rs-cell", "", "")] * 5 + rest,
            cells(input_html(self.frames[drawn], SLIDES_VALUES)),
        )
        self.assertEqual(
            ["25", "20", "30", "40"],
            [
                text
                for found, text in texts(heap_svg(self.frames[drawn], SLIDES_MEMORY))
                if has_class(found, "rs-value")
            ],
        )
        # the sift of 73, drawn after 20, up to the next output, still compares 73 with the last output 20:
        sift: int = frame_with(self.frames, "Draw next element 73") + 1
        following: int = frame_with(self.frames, "Remove top element 25")
        self.assertEqual(
            [
                "Sift down 73 from place 0: its children are 25 and 30; 25 is smaller",
                "73 and its smaller child 25: 25 < 73, so they swap",
                "73 swaps with its smaller child 25",
                "73 at place 1: its only child is 40; 40 < 73, so they swap",
                "73 swaps with its smaller child 40",
                "73 at place 3 has reached a leaf",
                "Heap maintains half order: no child is smaller than its parent",
            ],
            [frame.caption for frame in self.frames[sift:following]],
        )
        self.assertEqual(
            [Box("20", False, "73", (GREEN, "73 >= 20  →  heap (this run)"), None)] * 7,
            [self.box_at(position) for position in range(sift, following)],
        )

    def test_into_the_list_on_red(self) -> None:
        """When 25 is written, the box shows "16 >= 25  →  list (next run)" on red, written as on the slides although
        16 < 25, and the input marks 16; once 16 is drawn, the box is the same but 25 is no longer marked, also while
        73 takes the root's place and sinks and when 16 goes into the freed place.

        Would fail if green and red were swapped, if the decision were written as 16 < 25 instead of in the slides'
        form, or if the box changed before the next output, e.g. during the sift.
        """
        # the colour for the list is red:
        red, green, _, _ = rgba(RED)
        self.assertGreater(red, green)
        # the frame that writes 25 decides already, and the input marks 16:
        written: int = frame_with(self.frames, "Remove top element 25")
        decided: Box = Box(
            "25", True, "16", (RED, "16 >= 25  →  list (next run)"), None
        )
        self.assertEqual(decided, self.box_at(written))
        self.assertEqual(
            [("rs-cell", "", "")] * 6
            + [("rs-cell rs-mark", INPUT_COLOUR, "16")]
            + [("rs-cell", INPUT_COLOUR, value) for value in ("26", "33", "50", "31")],
            cells(input_html(self.frames[written], SLIDES_VALUES)),
        )
        # the eight frames up to the next output: the draw, the heap giving up its last place to 73 at the root, the
        # sift of 73 (its children compared, 73 compared with 30, the swap, the leaf), the half order and 16 put into
        # the freed place:
        following: int = frame_with(self.frames, "Remove top element 30")
        self.assertEqual(8, following - written - 1)
        self.assertEqual(
            [decided._replace(marked=False)] * 8,
            [self.box_at(position) for position in range(written + 1, following)],
        )

    def test_dashes_outside_an_output_step(self) -> None:
        """From the start to the end of the bulk load of run 0, the box shows dashes and the note that the first
        comparison comes at the first output; during the bulk load of run 1, dashes and the note that the new run
        compares at its first output; neither has a decision, and the frame before the bulk load of run 1 still
        shows the step that drew 50.

        Would fail if the box kept the last step's comparison into the bulk load of the next run, which compares
        nothing with the last output, or showed the note of a new run before the first output.
        """
        first_output: int = frame_with(self.frames, "Remove top element 10")
        new_run: int = frame_with(
            self.frames, "Bulkload a heap from the list: new run 1"
        )
        run_1_output: int = frame_with(self.frames, "Remove top element 16")
        # before the first output: the start, the load, the bulk load of run 0 (its start, its order and its five
        # steps: 20 compared, 30's children compared, 30 compared with 10, the swap, the leaf) and the half order:
        self.assertEqual(10, first_output)
        self.assertEqual(
            [Box("—", False, "—", None, "(first comparison at the first output)")]
            * first_output,
            [self.box_at(position) for position in range(first_output)],
        )
        # the step that drew 50 into the list, up to the bulk load of run 1:
        self.assertEqual(
            Box("73", False, "50", (RED, "50 >= 73  →  list (next run)"), None),
            self.box_at(new_run - 1),
        )
        # the bulk load of run 1, from the new run to the half order (its start, its order, its nine steps: 33
        # compared with 16, swapped, at a leaf; 50's children compared, 50 compared with 16, swapped, compared with 33,
        # swapped, at a leaf; the half order):
        self.assertEqual(12, run_1_output - new_run)
        self.assertEqual(
            [
                Box(
                    "—",
                    False,
                    "—",
                    None,
                    "(new run: next comparison at its first output)",
                )
            ]
            * (run_1_output - new_run),
            [self.box_at(position) for position in range(new_run, run_1_output)],
        )

    def test_empty_input_decides_nothing(self) -> None:
        """Once the input is empty, from the frame that writes 26 on, the box shows "— (R is empty)" as the next
        element and no decision, while the last output follows the elements written: 26, marked when it is written,
        also while 50 takes the root's place and sinks, up to the half order; at the end 50.

        Would fail if the box showed a decision without a next element, named the element the step before drew (31)
        as the next one, or showed dashes once the input is empty.
        """
        written: int = frame_with(self.frames, "Remove top element 26")
        following: int = frame_with(self.frames, "Remove top element 31")
        self.assertEqual(
            [
                "R is empty: the heap gives up its last place, and its last element 50 takes the root's place",
                "Sift down 50 from place 0: its children are 33 and 31; 31 is smaller",
                "50 and its smaller child 31: 31 < 50, so they swap",
                "50 swaps with its smaller child 31",
                "50 at place 2 has reached a leaf",
                "Heap maintains half order: no child is smaller than its parent",
            ],
            [frame.caption for frame in self.frames[written + 1 : following]],
        )
        self.assertEqual(
            [Box("26", True, "— (R is empty)", None, None)]
            + [Box("26", False, "— (R is empty)", None, None)] * 6,
            [self.box_at(position) for position in range(written, following)],
        )
        # the end:
        self.assertEqual(
            Box("50", False, "— (R is empty)", None, None), self.box_at(-1)
        )

    def test_same_box_in_every_frame(self) -> None:
        """Every frame of the slides' example shows the box below the input and above the heap's tree, with the same
        rows: the two labels, the two values and one bottom line; exactly the frames that compare an element show one
        decision, and every decision keeps its double spaces around the arrow. The style gives the box a fixed width
        and height, so that it neither grows nor shrinks from frame to frame.

        Would fail if a frame left the box out or gave it other rows, if the box moved away from between the input and
        the heap, if the spaces of a decision collapsed, or if the box's size followed its content.
        """
        for position, frame in enumerate(self.frames):
            with self.subTest(position=position, caption=frame.caption):
                view: str = frame_html(frame, SLIDES_VALUES, SLIDES_MEMORY)
                # the box right after the input's row, and the title of the heap right after the box:
                top: str = (
                    '<div class="rs-box"><div class="rs-top">'
                    + input_html(frame, SLIDES_VALUES)
                    + "</div>"
                    + comparison_html(
                        frame,
                        input_empty=frame.taken == len(SLIDES_VALUES),
                        input_fits=False,
                    )
                    + f'<div class="rs-title">{html.escape(heap_title(frame))}</div>'
                )
                self.assertEqual(top, view[: len(top)])
                # the rows of the box (box_of raises if they differ), and the decision's spaces:
                box_of(view)
                # one decision exactly where an element is compared, and its spaces kept:
                shown: list[tuple[str, str]] = decisions(comparison_html(frame))
                compares: bool = (
                    frame.comparison is not None and frame.comparison.drawn is not None
                )
                self.assertEqual(1 if compares else 0, len(shown))
                for style, _ in shown:
                    self.assertIn("white-space:pre", style)
        # a fixed size that the content does not change (and never wider than the page):
        rules: list[dict[str, str]] = declarations(BOX_STYLE, ".rs-compare")
        self.assertEqual(1, len(rules))
        self.assertEqual(
            ("border-box", "100%"), (rules[0]["box-sizing"], rules[0]["max-width"])
        )
        for size in ("width", "height"):
            with self.subTest(size=size):
                self.assertRegex(rules[0][size], r"^\d+(\.\d+)?(px|em)$")

    def test_texts_are_escaped(self) -> None:
        """Both decisions show ``>=`` escaped, the red one on its colour, and the notes and the text for an empty
        input, here replaced by texts with markup, are escaped as well.

        Would fail if a text of the box were put into the HTML unescaped, so that ``<`` opened a tag.
        """
        written: str = comparison_html(
            self.frames[frame_with(self.frames, "Remove top element 10")]
        )
        self.assertEqual(
            ["25 &gt;= 10  →  heap (this run)"],
            [text for _, text in decisions(written)],
        )
        # the red decision as well:
        red: str = comparison_html(
            self.frames[frame_with(self.frames, "Remove top element 25")]
        )
        self.assertEqual(
            [(RED, "16 &gt;= 25  →  list (next run)")],
            [
                (style.split(";")[0].removeprefix("background:"), text)
                for style, text in decisions(red)
            ],
        )
        # per text: the frame that shows it:
        cases: tuple[tuple[str, int], ...] = (
            ("FIRST_NOTE", 0),
            (
                "NEW_RUN_NOTE",
                frame_with(self.frames, "Bulkload a heap from the list: new run 1"),
            ),
            ("EMPTY_INPUT", -1),
        )
        for name, position in cases:
            with self.subTest(text=name):
                with mock.patch(
                    f"system.playground.replacement_selection_widgets.{name}",
                    "<i>R & S</i>",
                ):
                    shown: str = comparison_html(self.frames[position])
                self.assertIn("&lt;i&gt;R &amp; S&lt;/i&gt;", shown)
                self.assertNotIn("<i>", shown)
        # the note for an empty input outside of an output step:
        with mock.patch(
            "system.playground.replacement_selection_widgets.NOTHING_LEFT_NOTE",
            "<i>R & S</i>",
        ):
            shown = comparison_html(self.frames[0], input_empty=True)
        self.assertIn("&lt;i&gt;R &amp; S&lt;/i&gt;", shown)
        self.assertNotIn("<i>", shown)

    def test_nothing_left_to_compare(self) -> None:
        """Where no output step is under way and no comparison will follow, the box says so: with the input empty
        already, "— (R is empty)" and the note that nothing is left to compare, during the bulk load of the last run of
        reversed input (12 values, M = 4: runs of 4, the third run's list filled by the last draws, newest first) and
        after loading an input shorter than M; at the start of such an input, the note that all of R fits into memory.
        Inside an output step with R empty, the box still shows the step's last output and no note.

        Would fail if the box promised a comparison at the next output that never comes.
        """
        nothing_left: Box = Box(
            "—", False, "— (R is empty)", None, "(R is empty: nothing left to compare)"
        )
        # reversed input: the bulk load of run 2 starts with the input used up:
        values: tuple[int, ...] = tuple(range(120, 0, -10))
        frames: list[Frame] = trace(values, 4)
        run_2: int = frame_with(frames, "Bulkload a heap from the list: new run 2")
        # run 2 holds 10 20 30 40 (drawn as 40 30 20 10, each into the place in front of the one before), so its first
        # output is 10:
        first_output: int = frame_with(frames, "Remove top element 10 from heap")
        self.assertEqual(len(values), frames[run_2].taken)
        self.assertEqual(
            ["10", "20", "30", "40"], [str(element) for element in frames[run_2].heap]
        )
        # the bulk load of 10 20 30 40, a heap already: the new run; its order; 20 compared with its only child 40,
        # stays (1 frame); 10's children 20 and 30 compared, 10 compared with 20, stays (2 frames); the half order:
        self.assertEqual(1 + 1 + 1 + 2 + 1, first_output - run_2)
        self.assertEqual(
            [nothing_left] * (first_output - run_2),
            [
                box_of(frame_html(frames[position], values, 4))
                for position in range(run_2, first_output)
            ],
        )
        # the bulk load of run 1 still had input left:
        run_1: int = frame_with(frames, "Bulkload a heap from the list: new run 1")
        self.assertEqual(
            "(new run: next comparison at its first output)",
            box_of(frame_html(frames[run_1], values, 4)).note,
        )
        # the first output of run 2 shows its comparison, with R empty, and no note:
        self.assertEqual(
            Box("10", True, "— (R is empty)", None, None),
            box_of(frame_html(frames[first_output], values, 4)),
        )
        # an input shorter than M: at the start all of R fits into memory, from the load to the first output nothing is
        # left:
        short: list[Frame] = trace((7, 3), 5)
        short_output: int = frame_with(short, "Remove top element 3")
        self.assertEqual(
            Box(
                "—", False, "—", None, "(all of R fits into memory: nothing to compare)"
            ),
            box_of(frame_html(short[0], (7, 3), 5)),
        )
        self.assertEqual(
            [nothing_left] * (short_output - 1),
            [
                box_of(frame_html(short[position], (7, 3), 5))
                for position in range(1, short_output)
            ],
        )

    def test_input_of_exactly_m_fits_into_memory(self) -> None:
        """An input of exactly M elements, 30 20 10 40 with M = 4, fits into memory as a whole: the load reads all
        of it, so no element is ever compared, and the start shows dashes and the note that all of R fits into
        memory. One element more, 30 20 10 40 25, is compared at the first output, and its start shows the note that
        the first comparison comes then.

        Would fail if the view took only an input shorter than M as fitting (n < M instead of n ≤ M), so that the
        start of an input of exactly M elements promised a comparison that never comes.
        """
        # per input: its note at the start, and whether an element is ever compared:
        cases: tuple[tuple[tuple[int, ...], str, bool], ...] = (
            (
                (30, 20, 10, 40),
                "(all of R fits into memory: nothing to compare)",
                False,
            ),
            ((30, 20, 10, 40, 25), "(first comparison at the first output)", True),
        )
        for input_values, note, compares in cases:
            with self.subTest(n=len(input_values)):
                frames: list[Frame] = trace(input_values, 4)
                self.assertEqual(
                    compares,
                    any(
                        frame.comparison is not None
                        and frame.comparison.drawn is not None
                        for frame in frames
                    ),
                )
                self.assertEqual(
                    Box("—", False, "—", None, note),
                    box_of(frame_html(frames[0], input_values, 4)),
                )
