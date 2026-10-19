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
# This module's schedules resemble the scenarios on purpose (duplicate-code).
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring,duplicate-code
"""Tests for the widgets of the MVCC playground, driven without a kernel via values and clicks."""

from __future__ import annotations

import html
import json
import re
import unittest
from pathlib import Path

import ipywidgets as widgets

from system.playground.mvcc_playground import run_to
from system.playground.mvcc_scenarios import schedule_of
from system.playground.mvcc_widgets import (
    BOX_STYLE,
    CELL_COLOURS,
    CHOICES,
    FRAME,
    HEADER_STYLE,
    OWN,
    RUNNING_OPERATIONS,
    STATUS_COLOURS,
    VERDICT_COLOURS,
    MvccPlayground,
    next_operations,
)
from system.playground.schedules import DataOperation, Row

# the backgrounds of an operation's button by what it did:
RAN, RAN_LAST, PLANNED = (CELL_COLOURS[kind] for kind in ("ran", "ran last", "planned"))


def choose(playground: MvccPlayground, name: str) -> None:
    """Chooses the scenario called ``name`` in the dropdown, which loads it."""
    playground.scenario.value = next(i for i, s in enumerate(CHOICES) if s.name == name)


def loaded(name: str) -> MvccPlayground:
    """Returns a playground with the scenario called ``name`` loaded."""
    playground = MvccPlayground()
    choose(playground, name)
    return playground


def add(playground: MvccPlayground, transaction: int, operation: str) -> None:
    """Chooses ``transaction`` (0 is T1) and ``operation`` in the dropdowns and clicks add."""
    playground.transaction.value = transaction
    playground.operation.value = operation
    playground.add_button.click()


def why_column(playground: MvccPlayground) -> list[str]:
    """Returns the column "why" of the schedule grid, its header first, then one entry per operation; empty if the
    grid has no such column."""
    # a row has the operation's number, a column per transaction and, last, the column "why":
    transactions: int = 1 + max(s.transaction_index for s in playground.schedule)
    width: int = 1 + transactions + 1
    children = playground.grid.children
    if children[width - 1].value != "why":
        return []
    # the explanations are HTML (wrapped in a div), the header is a label; the text without tags:
    return [
        html.unescape(re.sub("<[^>]+>", "", child.value))
        for child in children[width - 1 :: width]
    ]


def backgrounds(playground: MvccPlayground) -> list[str]:
    """Returns the background colour of every operation's button, in schedule order."""
    return [cell.style.button_color for cell in playground.cells]


def rgba(colour: str) -> tuple[float, float, float, float]:
    """Returns red, green, blue (0 to 255) and alpha (0 to 1) of a colour written as ``#rrggbb`` or ``rgba(r,g,b,a)``."""
    if colour.startswith("#"):
        return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16), 1.0
    red, green, blue, alpha = (
        float(part) for part in colour[len("rgba(") : -1].split(",")
    )
    return red, green, blue, alpha


def blend(colour: str, under: tuple[float, float, float]) -> tuple[float, float, float]:
    """Returns the colour seen where ``colour``, maybe translucent, lies over the opaque colour ``under``."""
    red, green, blue, alpha = rgba(colour)
    return (
        alpha * red + (1 - alpha) * under[0],
        alpha * green + (1 - alpha) * under[1],
        alpha * blue + (1 - alpha) * under[2],
    )


def contrast(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> float:
    """Returns the contrast ratio of two opaque colours as WCAG 2 defines it, from 1 (equal) to 21 (black and
    white)."""

    def luminance(colour: tuple[float, float, float]) -> float:
        """Returns the relative luminance of an opaque colour."""
        channels: list[float] = []
        for channel in colour:
            value: float = channel / 255
            channels.append(
                value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
            )
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# the backgrounds of the light and dark themes the playground is read in, each with the text colour of its widgets:
# JupyterLab light, JupyterLab dark and PyCharm's dark themes. PyCharm's dark themes colour the text of HTML widgets
# and labels white (--jp-content-font-color1) and that of buttons 87 % white (--jp-ui-font-color1), as PyCharm 2025.2's
# darcula-new.css defines them; the fainter of the two is checked. JupyterLab's themes colour text 87 % black or
# white:
THEMES: dict[str, tuple[tuple[float, float, float], str]] = {
    "JupyterLab light": ((255, 255, 255), "rgba(0,0,0,0.87)"),
    "JupyterLab dark": ((17, 17, 17), "rgba(255,255,255,0.87)"),
    "PyCharm dark": ((30, 31, 34), "rgba(255,255,255,0.87)"),
    "PyCharm Darcula": ((43, 43, 43), "rgba(255,255,255,0.87)"),
}
# the background of the boxes, from the rule for .mvcc-box in BOX_STYLE:
BOX_RULE = re.search(r"\.mvcc-box\s*\{[^}]*background:\s*([^;}\s]+)", BOX_STYLE)
assert BOX_RULE, "BOX_STYLE has no rule for .mvcc-box with a background"
BOX_BACKGROUND: str = BOX_RULE.group(1)
# every background the playground puts behind text, by name, as the tints that lie on the page, the lowest first: the
# grid lies on the page, the tables and the verdict in a box, and a changed checksum in a transaction's row. It
# follows the nesting of state_html and show_grid; a tint added in either belongs here as well:
BACKGROUNDS: dict[str, tuple[str, ...]] = {
    **{
        f"status {kind}": (BOX_BACKGROUND, colour)
        for kind, colour in STATUS_COLOURS.items()
    },
    **{
        f"verdict {kind}": (BOX_BACKGROUND, colour)
        for kind, colour in VERDICT_COLOURS.items()
    },
    **{f"cell {kind}": (colour,) for kind, colour in CELL_COLOURS.items()},
    "header": (HEADER_STYLE["background"],),
    "box": (BOX_BACKGROUND,),
    **{
        f"changed checksum in the row of a {status} transaction": (
            BOX_BACKGROUND,
            STATUS_COLOURS[status],
            STATUS_COLOURS["aborted"],
        )
        for status in ("running", "committed", "aborted")
    },
}


def assert_in_boxes(test: unittest.TestCase, playground: MvccPlayground) -> None:
    """Checks that the playground shows the style of the boxes and puts the store's and the transactions' tables in
    boxes, so that the rules of :data:`BOX_STYLE` apply to them."""
    shown: list[str] = []
    pending: list[widgets.Widget] = [playground.widget]
    while pending:
        widget = pending.pop()
        pending.extend(getattr(widget, "children", ()))
        if isinstance(widget, widgets.HTML):
            shown.append(widget.value)
    test.assertTrue(any(BOX_STYLE in value for value in shown))
    for title in ("Store", "Transactions"):
        test.assertIn(
            f'<div class="mvcc-box"><b>{title}</b><table>', playground.state.value
        )


class PaletteTest(unittest.TestCase):
    """The playground's colours are readable in light and dark themes, as its text keeps the theme's colour."""

    def test_text_is_readable_on_every_background(self) -> None:
        """The theme's text has a contrast of at least 4.5 (WCAG AA) on every background in every theme, also where
        tints lie on each other.

        Would fail if a background were opaque and light, so that the light text of a dark theme vanished on it, or
        if a tint, or tints on each other, were so strong that the theme's text no longer stood out.
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

    def test_states_that_stand_side_by_side_differ(self) -> None:
        """The colours that stand side by side in the schedule grid differ clearly from each other in every theme: the
        operation that ran last, the others that ran, the planned and the skipped ones, the header, an error and an
        abort, the read that differs and the others that ran, and the frame of the operation that ran last against
        every colour that operation can have (ran last, error, aborted, committed, skipped).

        Would fail if two of these looked alike in a theme, e.g. a skipped operation and the grey header.
        """
        # the colour of the frame, e.g. "#808080" of "2px solid #808080":
        frame_colour: str = FRAME.split()[-1]
        pairs: list[tuple[str, str]] = [
            (CELL_COLOURS["ran last"], CELL_COLOURS["ran"]),
            (CELL_COLOURS["ran"], CELL_COLOURS["planned"]),
            (CELL_COLOURS["skipped"], CELL_COLOURS["planned"]),
            (CELL_COLOURS["skipped"], HEADER_STYLE["background"]),
            (HEADER_STYLE["background"], CELL_COLOURS["planned"]),
            (CELL_COLOURS["error"], CELL_COLOURS["aborted"]),
            (CELL_COLOURS["differs"], CELL_COLOURS["ran"]),
            (frame_colour, CELL_COLOURS["ran last"]),
            (frame_colour, CELL_COLOURS["error"]),
            (frame_colour, CELL_COLOURS["aborted"]),
            (frame_colour, CELL_COLOURS["committed"]),
            (frame_colour, CELL_COLOURS["skipped"]),
        ]
        for theme, (page, _) in THEMES.items():
            for first, second in pairs:
                with self.subTest(theme=theme, first=first, second=second):
                    distance: float = (
                        sum(
                            (a - b) ** 2
                            for a, b in zip(blend(first, page), blend(second, page))
                        )
                        ** 0.5
                    )
                    # at least 25 of the distance 441 between black and white: the two still look different at a glance
                    self.assertGreaterEqual(distance, 25)

    def test_no_fixed_text_colour(self) -> None:
        """Neither the boxes nor the schedule grid set a text colour of their own, so the text keeps the theme's.

        Would fail if black text were set anywhere, which is unreadable on the dark backgrounds of a dark theme.
        """
        # a text colour in CSS, but not a background-color:
        text_colour = re.compile(r"(?<![-\w])color\s*:")
        # in write skew via phantom with method 1, after T1's commit, T2's checksum has changed:
        playground = loaded("write skew via phantom (insert and delete)")
        playground.mode.value = "method 1"
        playground.cells[6].click()
        self.assertIn(
            f'<span style="background:{STATUS_COLOURS["aborted"]}">',
            playground.state.value,
        )
        self.assertIsNone(text_colour.search(BOX_STYLE))
        # the store, the transactions with the changed checksum, and the verdict:
        self.assertIsNone(text_colour.search(playground.state.value))
        # at the end T2 is aborted and the column "why" explains it:
        playground.cells[-1].click()
        labels = [
            child
            for child in playground.grid.children
            if isinstance(child, widgets.Label)
        ]
        why = [
            child
            for child in playground.grid.children
            if isinstance(child, widgets.HTML)
        ]
        self.assertTrue(labels)
        self.assertTrue(why)
        for child in playground.cells + labels + why:
            self.assertIsNone(child.style.text_color)
        for child in why:
            self.assertIsNone(text_colour.search(child.value))

    def test_theme_rows_do_not_colour_the_tables(self) -> None:
        """The theme gives the rows of the tables in the boxes no background, even where it stripes or highlights
        rows; a row's own background still shows. The rule is more specific than PyCharm's ``table
        tr:nth-child(even)`` and JupyterLab's ``.jp-RenderedHTMLCommon tbody tr:nth-child(odd)`` and ``tbody
        tr:hover``.

        Would fail if the rule lost its ``div`` prefix or its ``:nth-child(n)`` or ``:hover`` selector, so that a row
        of the store got the dark stripe of a dark theme, or if the tables were not in a box or the style were not
        shown.
        """
        self.assertIn(
            "div.mvcc-box table tr:nth-child(n), div.mvcc-box table tr:hover {background:transparent}",
            BOX_STYLE,
        )
        assert_in_boxes(self, MvccPlayground())


# the notebook that shows the playground:
NOTEBOOK: Path = Path(__file__).parents[3] / "notebooks" / "MVCC-Playground.ipynb"


class NotebookTest(unittest.TestCase):
    """The notebook that shows the playground."""

    def test_code_cells_open_collapsed(self) -> None:
        """Every code cell of the notebook opens with its code collapsed, so that the playground comes first.

        Would fail if saving the notebook dropped the cells' "source_hidden" metadata.
        """
        cells: list[dict] = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
        code_cells: list[dict] = [cell for cell in cells if cell["cell_type"] == "code"]
        self.assertEqual(2, len(code_cells))
        for cell in code_cells:
            self.assertEqual({"source_hidden": True}, cell["metadata"].get("jupyter"))


class NextOperationsTest(unittest.TestCase):
    """Which operations the playground offers next."""

    def test_choices(self) -> None:
        """The lowest transaction that has not begun may begin, running ones get any other operation, ended ones
        nothing, and at most four begin.

        Would fail if an ended transaction were offered operations, a fifth transaction could begin, or T1 could
        not begin after T2 (as in the scenario of Fekete et al.).
        """
        self.assertEqual({0: ["begin"]}, next_operations(()))
        self.assertEqual(
            {0: list(RUNNING_OPERATIONS), 1: ["begin"]},
            next_operations(schedule_of((1, "begin"))),
        )
        self.assertEqual(
            {1: ["begin"]}, next_operations(schedule_of((1, "begin"), (1, "commit")))
        )
        four = schedule_of(*((n, "begin") for n in (1, 2, 3, 4)))
        self.assertEqual([0, 1, 2, 3], sorted(next_operations(four)))
        self.assertEqual(
            {0: ["begin"], 1: list(RUNNING_OPERATIONS)},
            next_operations(schedule_of((2, "begin"))),
        )


class MvccPlaygroundTest(unittest.TestCase):
    """The playground's widgets, driven through their values and button clicks."""

    def test_choose_scenario(self) -> None:
        """Choosing a scenario, also again after an edit, loads it before its first operation; an edit, or choosing
        "own schedule" by hand, keeps the schedule and clears the scenario's description.

        Would fail if choosing a scenario kept the edited schedule or the position or did not show a button per
        operation, or if an edit or choosing "own schedule" replaced the schedule or kept the description.
        """
        playground = loaded("lost update")
        self.assertEqual((0, 8), (playground.position, len(playground.cells)))
        add(playground, 2, "begin")
        self.assertEqual(
            (OWN, ""), (playground.scenario.value, playground.description.value)
        )
        choose(playground, "lost update")
        lost_update = next(s for s in CHOICES if s.name == "lost update")
        self.assertEqual(list(lost_update.schedule), playground.schedule)
        self.assertEqual(0, playground.position)
        playground.scenario.value = OWN
        self.assertEqual(list(lost_update.schedule), playground.schedule)
        self.assertEqual("", playground.description.value)

    def test_click_cell_and_move(self) -> None:
        """Clicking an operation runs up to and including it; back and forward move by one, not past the ends.

        Would fail if a click ran one operation too few or too many, the cells were coloured, framed or set in italics
        by the wrong position, or back/forward stayed enabled at the start/end.
        """
        playground = loaded("lost update")
        self.assertTrue(playground.back_button.disabled)
        playground.cells[2].click()
        self.assertEqual(3, playground.position)
        self.assertEqual([RAN, RAN, RAN_LAST, PLANNED], backgrounds(playground)[:4])
        # only the operation that ran last is framed:
        self.assertEqual(
            ["none", "none", FRAME, "none"],
            [cell.layout.border for cell in playground.cells[:4]],
        )
        # only the operations that have not run are in italics:
        self.assertEqual(
            ["normal", "normal", "normal", "italic"],
            [cell.style.font_style for cell in playground.cells[:4]],
        )
        playground.forward_button.click()
        self.assertEqual(4, playground.position)
        playground.back_button.click()
        self.assertEqual(3, playground.position)
        playground.cells[-1].click()
        self.assertTrue(playground.forward_button.disabled)

    def test_mode_switch_changes_verdict(self) -> None:
        """At the end of write skew via phantom, switching the mode runs the schedule again: not serializable without
        validation, serializable with method 2 (T2 aborts), each in the colour of its kind.

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
                                    read a==1 → {x}
        update y ← (a=1, b=0)
                                    delete x
        commit
                                    commit -> committed without validation, aborted with method 2
        ```

        Would fail if switching the mode did not run the schedule again or the verdict box had the wrong colour.
        """
        playground = loaded("write skew via phantom (insert and delete)")
        playground.cells[-1].click()
        for mode, kind, start in (
            ("no validation", "not serializable", "Not serializable: "),
            ("method 2", "serializable", "Serializable: "),
        ):
            with self.subTest(mode=mode):
                playground.mode.value = mode
                self.assertIn(
                    f'background:{VERDICT_COLOURS[kind]}; padding:6px">{start}',
                    playground.state.value,
                )

    def test_mode_labels(self) -> None:
        """The mode buttons name the isolation level (where there is one) and how each mode decides which
        transactions to abort, while their values stay the modes.

        Would fail if a label named the wrong mode, or a value changed so that the store was made for another mode.
        """
        playground = MvccPlayground()
        self.assertEqual(
            (
                ("serializable - method 1 (re-run reads, checksums)", "method 1"),
                ("serializable - method 2 (write sets)", "method 2"),
                ("snapshot isolation - first updater wins", "snapshot isolation"),
                ("no validation", "no validation"),
            ),
            playground.mode.options,
        )

    def test_table_cells_are_separated_by_lines(self) -> None:
        """The cells of the store's and the transactions' tables are separated by lines.

        Would fail if the tables had no lines between their columns and rows, if the rule lost its ``div`` prefix, so
        that a theme's rule for td without a border were as specific and the order of the style sheets decided, or if
        the tables were not in a box or the style were not shown.
        """
        assert_in_boxes(self, MvccPlayground())
        self.assertIn("div.mvcc-box table {border-collapse:collapse}", BOX_STYLE)
        self.assertIn(
            "div.mvcc-box th, div.mvcc-box td {border:1px solid rgba(128,128,128,0.5)}",
            BOX_STYLE,
        )

    def test_verdict_box(self) -> None:
        """At the end of write skew without validation, the verdict has its own box headed "Verdict", with its
        sentence and one line per serial order.

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
        read a==2 → {y}
                                    read a==1 → {x}
                                    read a==2 → {y}
        update x ← (a=1, b=100)
                                    update y ← (a=2, b=200)
        commit
                                    commit
        ```

        Would fail if the heading were missing or the lines of the orders were not shown as a list after the sentence.
        """
        playground = loaded("write skew")
        playground.mode.value = "no validation"
        playground.cells[-1].click()
        # the verdict is the last box:
        verdict: str = playground.state.value.split('<div class="mvcc-box">')[-1]
        self.assertTrue(verdict.startswith("<b>Verdict</b>"), verdict)
        self.assertIn(
            "Not serializable: no serial order gives the same read results and final state.<ul",
            verdict,
        )
        self.assertIn(
            "<li>Order T1|T2: T2&#x27;s read a==1 would return {x: (a=1, b=100)}, but returned {x: (a=1, b=0)}.</li>",
            verdict,
        )
        self.assertEqual(2, verdict.count("<li>"))

    def test_read_that_differs_is_marked(self) -> None:
        """At the end of write skew without validation, T2's read a==1 (position 4, row 5) is marked in the schedule,
        and the column "why" says in its row what it would return in the order of the serialization points; with
        method 2 nothing is marked, and the column explains T2's aborted commit instead.

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
        read a==2 → {y}
                                    read a==1 → {x}
                                    read a==2 → {y}
        update x ← (a=1, b=100)
                                    update y ← (a=2, b=200)
        commit
                                    commit
        ```

        Would fail if another operation were marked, the explanation stood in another row or were missing, or a mark
        stayed when the run is serializable.
        """
        playground = loaded("write skew")
        playground.mode.value = "no validation"
        playground.cells[-1].click()
        differs: str = CELL_COLOURS["differs"]
        self.assertEqual(
            [4], [i for i, b in enumerate(backgrounds(playground)) if b == differs]
        )
        why: list[str] = why_column(playground)
        self.assertEqual("why", why[0])
        self.assertEqual(
            {4: "in the order T1|T2 this read would return {x: (a=1, b=100)}"},
            {position: text for position, text in enumerate(why[1:]) if text},
        )
        playground.mode.value = "method 2"
        self.assertNotIn(differs, backgrounds(playground))
        self.assertEqual(
            {
                9: "validation: T1 changed x, which read a==1 returns in the snapshot of T2's begin"
            },
            {
                position: text
                for position, text in enumerate(why_column(playground)[1:])
                if text
            },
        )

    def test_no_why_column_without_problems(self) -> None:
        """The serial scenario, where nothing goes wrong, has no column "why".

        Would fail if the column were shown although there is nothing to explain.
        """
        playground = loaded("serial")
        playground.cells[-1].click()
        self.assertEqual([], why_column(playground))

    def test_header_and_time_column_are_grey(self) -> None:
        """The header row and the column "time" of the schedule are grey, in every row.

        Would fail if a header or a number of the column "time" had no background, or if the operations' cells were
        grey as well.
        """
        playground = loaded("write skew")
        playground.mode.value = "no validation"
        playground.cells[-1].click()
        # a row has the column "time", a column per transaction and the column "why":
        width: int = 1 + 2 + 1
        children = playground.grid.children
        header_and_time = list(children[:width]) + list(children[width::width])
        self.assertEqual(
            ["time", "T1", "T2", "why"] + [str(n) for n in range(1, 11)],
            [label.value for label in header_and_time],
        )
        for label in header_and_time:
            self.assertEqual(HEADER_STYLE["background"], label.style.background)
        self.assertNotIn(HEADER_STYLE["background"], backgrounds(playground))

    def test_why_column_width(self) -> None:
        """The grid gets a fourth, wider column for "why" at the end of write skew without validation, and only the
        number column and a column per transaction for the serial scenario.

        Write skew, without validation:

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
        read a==2 → {y}
                                    read a==1 → {x}
                                    read a==2 → {y}
        update x ← (a=1, b=100)
                                    update y ← (a=2, b=200)
        commit
                                    commit
        ```

        Serial, with method 2:

        ```text
        T1                          T2
        begin
        read a==1 → {x}
        update y ← (a=1, b=0)
        commit
                                    begin
                                    read a==1 → {x, y}
                                    delete x
                                    commit
        ```

        Would fail if the grid's columns did not follow its rows, so that the explanations wrapped into the next
        row or an empty column were added.
        """
        for name, mode, columns in (
            ("write skew", "no validation", "45px repeat(2, 300px) minmax(250px, 1fr)"),
            ("serial", "method 2", "45px repeat(2, 300px)"),
        ):
            with self.subTest(scenario=name):
                playground = loaded(name)
                playground.mode.value = mode
                playground.cells[-1].click()
                self.assertEqual(columns, playground.grid.layout.grid_template_columns)

    def test_mark_and_why_column_only_with_a_verdict(self) -> None:
        """At the end of write skew without validation, the read that differs is marked and the column "why" shown;
        one step back, T2 has not committed and the verdict is pending, so both are gone; a serializable verdict (the
        serial scenario at its end) has no lines of orders.

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
        read a==2 → {y}
                                    read a==1 → {x}
                                    read a==2 → {y}
        update x ← (a=1, b=100)
                                    update y ← (a=2, b=200)
        commit
                                    commit                 <- back from here
        ```

        Would fail if the mark or the column stayed from the previous run while the verdict is pending, or if a
        serializable verdict showed an empty list of orders.
        """
        differs: str = CELL_COLOURS["differs"]
        playground = loaded("write skew")
        playground.mode.value = "no validation"
        playground.cells[-1].click()
        self.assertIn(differs, backgrounds(playground))
        self.assertEqual("why", why_column(playground)[0])
        playground.back_button.click()
        self.assertIn(
            "Pending: not every transaction has ended.", playground.state.value
        )
        self.assertNotIn(differs, backgrounds(playground))
        self.assertEqual([], why_column(playground))
        serial = loaded("serial")
        serial.cells[-1].click()
        self.assertIn("Serializable: ", serial.state.value)
        self.assertNotIn("<ul", serial.state.value)

    def test_skipped_operation_before_the_marked_read(self) -> None:
        """Without validation, T3's update aborts and its commit is skipped before T2's read a==1; the read is still
        marked in its own row (position 7), and the column "why" explains the abort and the read in their rows.

        Initially x = (a=1, b=0) and y = (a=0, b=0):

        ```text
        T1                          T2                          T3
        begin
                                    begin
                                                                begin
        read a==1 → {x}
        update y ← (a=1, b=0)
                                                                update y ← (a=1, b=5) -> aborted (T1 writes y)
                                                                commit -> skipped
                                    read a==1 → {x}
                                    delete x
        commit
                                    commit
        ```

        Would fail if the mark or an explanation were placed by counting only the operations that ran, so that it
        stood one row too early.
        """
        playground = MvccPlayground()
        playground.mode.value = "no validation"
        for transaction in (0, 1, 2):
            add(playground, transaction, "begin")
        playground.a.value = 1
        add(playground, 0, "read a==")
        playground.key.value = "y"
        playground.a.value, playground.b.value = 1, 0
        add(playground, 0, "update")
        playground.b.value = 5
        add(playground, 2, "update")
        add(playground, 2, "commit")
        add(playground, 1, "read a==")
        playground.key.value = "x"
        add(playground, 1, "delete")
        add(playground, 0, "commit")
        add(playground, 1, "commit")
        differs: str = CELL_COLOURS["differs"]
        self.assertEqual(
            [CELL_COLOURS["aborted"], CELL_COLOURS["skipped"], differs],
            backgrounds(playground)[5:8],
        )
        self.assertEqual(
            [7], [i for i, b in enumerate(backgrounds(playground)) if b == differs]
        )
        self.assertEqual(
            {
                5: "T1 is writing y and has not committed yet",
                7: "in the order T1|T2 this read would return {x: (a=1, b=0), y: (a=1, b=0)}",
            },
            {
                position: text
                for position, text in enumerate(why_column(playground)[1:])
                if text
            },
        )

    def test_build_by_clicks(self) -> None:
        """Clicking begin, update z, read all, read a==5 and commit for T1 builds that schedule, runs it to its end
        and leaves the chosen scenario.

        Initially x = (a=1, b=0) and y = (a=0, b=0):

        ```text
        T1
        begin
        update z ← (a=5, b=7)
        read all → {x, y, z}
        read a==5 → {z}
        commit
        ```

        Would fail if the dropdowns or the a/b fields were mapped to the wrong parts of the operation.
        """
        playground = MvccPlayground()
        add(playground, 0, "begin")
        playground.key.value = "z"
        playground.a.value, playground.b.value = 5, 7
        add(playground, 0, "update")
        add(playground, 0, "read all")
        add(playground, 0, "read a==")
        add(playground, 0, "commit")
        expected = schedule_of(
            (1, "begin"),
            (1, DataOperation("update", "z", Row(5, 7))),
            (1, DataOperation("read")),
            (1, DataOperation("read", a_equals=5)),
            (1, "commit"),
        )
        self.assertEqual(list(expected), playground.schedule)
        self.assertEqual(5, playground.position)
        self.assertEqual(OWN, playground.scenario.value)

    def test_previous_grid_is_closed(self) -> None:
        """Moving forward builds a new grid and closes the widgets of the previous one, with their layout and style.

        Would fail if the old buttons stayed open, so that they piled up in the kernel and the browser.
        """
        playground = loaded("lost update")
        old = playground.cells[0]
        playground.forward_button.click()
        self.assertIsNot(old, playground.cells[0])
        self.assertEqual(
            (None, None, None), (old.comm, old.layout.comm, old.style.comm)
        )

    def test_transaction_kept_after_add(self) -> None:
        """After T2 begins, the transaction dropdown still shows T2.

        Would fail if refreshing the choices jumped back to the first transaction.
        """
        playground = MvccPlayground()
        add(playground, 0, "begin")
        add(playground, 1, "begin")
        self.assertEqual(1, playground.transaction.value)

    def test_remove_and_add_disabled(self) -> None:
        """Removing the last operation at the end moves the position along; remove is disabled on an empty
        schedule, add once four transactions have ended, and a click that arrives anyway changes nothing.

        Would fail if the position stayed after the end of the shortened schedule, a button stayed enabled, or a
        second click on a button the browser has not disabled yet appended an operation or removed from nothing.
        """
        playground = loaded("lost update")
        playground.cells[-1].click()
        playground.remove_button.click()
        self.assertEqual((7, 7), (len(playground.schedule), playground.position))
        empty = MvccPlayground()
        self.assertTrue(empty.remove_button.disabled)
        # called directly, as ipywidgets would swallow an error raised in a click handler:
        empty.remove_last()
        self.assertEqual([], empty.schedule)
        for index in range(4):
            add(empty, index, "begin")
            add(empty, index, "commit")
        self.assertTrue(empty.add_button.disabled)
        # called directly, as ipywidgets would swallow an error raised in a click handler:
        empty.add_operation()
        self.assertEqual(8, len(empty.schedule))

    def test_begin_t1_after_t2(self) -> None:
        """With only these operations of Fekete et al.'s scenario left, T1 may begin and T2 may go on:

        ```text
        T1          T2
                    begin
                    read all
        ```

        Would fail if only the next number (T3) were offered to begin.
        """
        playground = loaded("read-only anomaly (Fekete et al.)")
        for _ in range(9):
            playground.remove_button.click()
        self.assertEqual((("T1 (new)", 0), ("T2", 1)), playground.transaction.options)
        # once both operations ran: T2 began first and got the store's id 1, T1 has not begun:
        playground.cells[-1].click()
        self.assertEqual(
            ["time", "T1", "T2"],
            [label.value for label in playground.grid.children[:3]],
        )
        self.assertEqual("begin (ts 1)", playground.cells[0].description)
        playground.transaction.value = 0
        self.assertEqual((("begin", "begin"),), playground.operation.options)

    def test_aborted_and_committed_colours(self) -> None:
        """At the end of lost update in method 2, T1's commit is green, T2's aborted commit and T2's row are red.

        ```text
        T1                          T2
        begin
                                    begin
        read all → {x}
                                    read all → {x}
        update x ← (a=1, b=1)
        commit
                                    update x ← (a=1, b=2)
                                    commit -> aborted
        ```

        Would fail if an aborted last operation were coloured as merely the last one run, or a successful commit
        as an ordinary operation.
        """
        playground = loaded("lost update")
        playground.cells[-1].click()
        self.assertEqual(CELL_COLOURS["committed"], backgrounds(playground)[5])
        self.assertEqual(CELL_COLOURS["aborted"], backgrounds(playground)[7])
        self.assertIn(
            f'<tr style="background:{STATUS_COLOURS["aborted"]}"><td>T2</td>',
            playground.state.value,
        )

    def test_skipped_colour(self) -> None:
        """An operation of a transaction the store aborted at a write is skipped and shown darker than a planned one.

        ```text
        T1                          T2
        begin
                                    begin
        update x ← (a=1, b=0)
                                    update x ← (a=1, b=0) -> aborted (T1 writes x)
                                    read all -> skipped
        ```

        Would fail if a skipped operation were coloured as one that ran or as a planned one.
        """
        playground = MvccPlayground()
        add(playground, 0, "begin")
        add(playground, 1, "begin")
        add(playground, 0, "update")
        add(playground, 1, "update")
        add(playground, 1, "read all")
        self.assertEqual(
            [CELL_COLOURS["aborted"], CELL_COLOURS["skipped"]],
            backgrounds(playground)[3:],
        )

    def test_store_table(self) -> None:
        """At the end of lost update with method 2 (the default mode), the store shows both committed versions of x,
        each with its timestamp and its writer, and nobody writing x.

        ```text
        T1                          T2
        begin
                                    begin
        read all → {x}
                                    read all → {x}
        update x ← (a=1, b=1)
        commit
                                    update x ← (a=1, b=2)
                                    commit -> aborted
        ```

        Would fail if a version lost its timestamp or writer, or a version being written were shown.
        """
        playground = loaded("lost update")
        playground.cells[-1].click()
        # the cells of the store's row for x, after the cell with the key:
        row: str = playground.state.value.split("<tr><td><b>x</b></td>")[1]
        row = row.split("</tr>")[0]
        self.assertIn("ts 0 initial: (a=1, b=0)</span>", row)
        self.assertIn("ts 3 T1: (a=1, b=1)</span>", row)
        # T2's commit was aborted in validation, which removed its work-in-progress version: no version of T2 and
        # nobody writing:
        self.assertNotIn("T2", row)
        self.assertTrue(row.endswith("<td></td>"), row)

    def test_snapshot_plus_own_writes(self) -> None:
        """In lost update, after T1 updated x but before it commits, the column "snapshot + own writes" shows T1's
        uncommitted version of x for T1 and the committed one for T2.

        ```text
        T1                          T2
        begin
                                    begin
        read all → {x}
                                    read all → {x}
        update x ← (a=1, b=1)
        ```

        Would fail if the column showed only the snapshot without the transaction's own writes, or another
        transaction's uncommitted write.
        """
        playground = loaded("lost update")
        playground.cells[4].click()
        self.assertIn("<th>snapshot + own writes</th>", playground.state.value)
        self.assertIn(
            "<td>T1</td><td>running</td><td>{x: (a=1, b=1)}</td>",
            playground.state.value,
        )
        self.assertIn(
            "<td>T2</td><td>running</td><td>{x: (a=1, b=0)}</td>",
            playground.state.value,
        )

    def test_checksum_that_changed_is_red(self) -> None:
        """In write skew via phantom with method 1, after T1's commit, T2's checksum now is shown in red, T1's
        without now.

        The operations that have run (T2's commit has not run yet):

        ```text
        T1                          T2
        begin
                                    begin
        read a==1 → {x}
                                    read a==1 → {x}
        update y ← (a=1, b=0)
                                    delete x
        commit
        ```

        Would fail if the checksums column were missing in method 1, shown in method 2, or a changed checksum were
        not marked.
        """
        playground = loaded("write skew via phantom (insert and delete)")
        playground.mode.value = "method 1"
        playground.cells[6].click()
        t_1, t_2 = run_to(
            tuple(playground.schedule), playground.initial_state, "method 1", 7
        ).transactions
        self.assertIn(
            f"<td>a==1: at read {t_1.checksums[0].at_read[:8]}</td>",
            playground.state.value,
        )
        self.assertIn(
            f'<span style="background:{STATUS_COLOURS["aborted"]}">a==1: at read '
            f"{t_2.checksums[0].at_read[:8]} · now {t_2.checksums[0].now[:8]}</span>",
            playground.state.value,
        )
        playground.mode.value = "method 2"
        self.assertNotIn("checksums", playground.state.value)

    def test_changed_checksum_of_a_transaction_that_wrote_nothing(self) -> None:
        """In lost update with method 1, after T1's commit, T2 has only read: its checksum now differs, but it is
        not red, as the store does not validate a transaction that wrote nothing.

        The operations that have run (T2's update of x and its commit have not run yet):

        ```text
        T1                          T2
        begin
                                    begin
        read all → {x}
                                    read all → {x}
        update x ← (a=1, b=1)
        commit
        ```

        Would fail if a changed checksum were marked as a failing commit for a transaction that has not written.
        """
        playground = loaded("lost update")
        playground.mode.value = "method 1"
        playground.cells[5].click()
        self.assertIn("all: at read ", playground.state.value)
        self.assertIn("(wrote nothing: not validated)", playground.state.value)
        self.assertNotIn(
            f'<span style="background:{STATUS_COLOURS["aborted"]}',
            playground.state.value,
        )

    def test_error_stops_the_run(self) -> None:
        """Deleting an object the store does not have stops the run: the cell is orange, the verdict red with the
        error's quotes escaped, and the position stays at the error, so forward is disabled.

        Initially x = (a=1, b=0) and y = (a=0, b=0), without z:

        ```text
        T1
        begin
        delete z -> error (KeyError: 'z')
        commit -> not run
        ```

        Would fail if a raised error were coloured as a normal operation or as an abort, the state were not
        escaped, or the position moved past the error, where nothing would change on the screen.
        """
        playground = MvccPlayground()
        add(playground, 0, "begin")
        playground.key.value = "z"
        add(playground, 0, "delete")
        add(playground, 0, "commit")
        self.assertEqual(CELL_COLOURS["error"], backgrounds(playground)[1])
        self.assertEqual(2, playground.position)
        self.assertTrue(playground.forward_button.disabled)
        self.assertIn(
            f"background:{VERDICT_COLOURS['error']}; padding:6px\">The run stopped: delete z: raised "
            "KeyError: &#x27;z&#x27;.</div>",
            playground.state.value,
        )
