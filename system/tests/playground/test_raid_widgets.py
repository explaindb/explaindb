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
"""Tests for the widgets of the RAID playground, driven without a kernel via values and clicks."""

from __future__ import annotations

import html
import json
import logging
import re
import unittest
from pathlib import Path

import ipywidgets as widgets

from system.playground.raid_playground import (
    DEFAULT_DEVICE_TYPES,
    PRESETS,
    Configuration,
    DeviceKind,
    DeviceType,
    Structure,
    configuration,
    metrics,
)
from system.playground.raid_widgets import (
    BLOCK_COLOURS,
    BOX_STYLE,
    DISK_COLOURS,
    LEGEND,
    MIN_COLUMN_WIDTH,
    NO_INNER,
    OWN,
    VERDICT_COLOURS,
    WHOLE_MEMBER_NOTE,
    ClickMode,
    NumberRow,
    Panel,
    RaidPlayground,
    better,
    column_width,
    disk_name,
    number_rows,
    numbers_html,
    swatch,
)
from system.tests.playground.test_mvcc_widgets import THEMES, blend, contrast


class RaiseHandlerErrors(logging.Handler):
    """Raises the exception of a click handler again: ipywidgets catches it and only logs it as a warning (see
    ``CallbackDispatcher``), so that a test would go on as if the click had worked."""

    def emit(self, record: logging.LogRecord) -> None:
        """Raises the exception the record was logged with, if any."""
        if record.exc_info is not None and record.exc_info[1] is not None:
            raise record.exc_info[1]


def press(button: widgets.Button) -> None:
    """Clicks a button; an exception of one of its click handlers is raised, not only logged."""
    # the logger ipywidgets logs exceptions of click handlers to: traitlets' logger "traitlets", as long as no
    # traitlets application and no IPython shell runs (traitlets is installed with ipywidgets, but not declared, so it
    # is not imported):
    logger: logging.Logger = logging.getLogger("traitlets")
    handler = RaiseHandlerErrors()
    logger.addHandler(handler)
    try:
        button.click()
    finally:
        logger.removeHandler(handler)


def click(playground: RaidPlayground, panel: Panel, slot: int, mode: ClickMode) -> None:
    """Chooses the click mode ``mode`` and clicks the disk in ``slot`` of ``panel``."""
    playground.click_mode.value = mode
    press(panel.disk_buttons[slot])


def colours(panel: Panel) -> list[str]:
    """Returns the background colour of every disk button of ``panel``, in slot order."""
    return [button.style.button_color for button in panel.disk_buttons]


def block_backgrounds(panel: Panel, slot: int) -> list[str]:
    """Returns the background of every block below the disk in ``slot`` of ``panel``, from the first row down."""
    return re.findall(
        r'<td style="background:([^"]+)">', panel.block_columns[slot].value
    )


def block_cells(panel: Panel, slot: int) -> list[tuple[str, str]]:
    """Returns the background and the text of every block below the disk in ``slot`` of ``panel``, from the first
    row down."""
    return re.findall(
        r'<td style="background:([^"]+)">([^<]*)</td>',
        panel.block_columns[slot].value,
    )


def bold_values(panel: Panel) -> list[str]:
    """Returns the values shown in bold in the numbers of ``panel``."""
    return re.findall(r"<td><b>([^<]*)</b></td>", panel.numbers.value)


def number_texts(panel: Panel) -> dict[str, str]:
    """Returns every value in the numbers of ``panel`` by its label, whether it is shown in bold or not."""
    return dict(re.findall(r"<th>([^<]*)</th><td>(?:<b>)?([^<]*)", panel.numbers.value))


def rows_of(config: Configuration) -> list[NumberRow]:
    """Returns the numbers shown below ``config`` with the default device types."""
    return number_rows(config, metrics(config, DEFAULT_DEVICE_TYPES))


def mark(playground: RaidPlayground, panel: Panel) -> None:
    """Fails disk a of ``panel`` and makes its disk b slow."""
    click(playground, panel, 0, "failed")
    click(playground, panel, 1, "slow")


def descriptions(panel: Panel) -> list[str]:
    """Returns the labels of the disk buttons of ``panel``, in slot order, e.g. ``a fast failed``."""
    return [button.description for button in panel.disk_buttons]


def descendants(widget: widgets.Widget) -> list[widgets.Widget]:
    """Returns ``widget`` and every widget inside it, at any depth."""
    found: list[widgets.Widget] = [widget]
    for child in getattr(widget, "children", ()):
        found += descendants(child)
    return found


def number_labels(panel: Panel) -> list[str]:
    """Returns the labels of the numbers of ``panel``, from the top down."""
    return re.findall(r"<th>([^<]*)</th>", panel.numbers.value)


def groups(panel: Panel) -> list[tuple[str, list[str]]]:
    """Returns the dashed boxes of the disks of ``panel``: per box its title and the labels of its disk buttons."""
    found: list[tuple[str, list[str]]] = []
    for group in panel.disks.children:
        # a box holds its title, then a row of columns, each with its disk's button on top:
        title, row = group.children
        found.append(
            (
                re.sub("<[^>]+>", "", title.value),
                [column.children[0].description for column in row.children],
            )
        )
    return found


# the background of the boxes, from the rule for .raid-box in BOX_STYLE:
BOX_RULE = re.search(r"\.raid-box\s*\{[^}]*background:\s*([^;}\s]+)", BOX_STYLE)
assert BOX_RULE, "BOX_STYLE has no rule for .raid-box with a background"
BOX_BACKGROUND: str = BOX_RULE.group(1)
# every background the playground puts behind text, by name, as the tints that lie on the page, the lowest first: the
# legend lies on the page; the disk buttons, the blocks, the verdicts and the numbers (also those in bold, and A alone
# without B) lie in the box of their panel:
BACKGROUNDS: dict[str, tuple[str, ...]] = {
    "box": (BOX_BACKGROUND,),
    **{
        f"disk {kind}": (BOX_BACKGROUND, colour)
        for kind, colour in DISK_COLOURS.items()
    },
    **{
        f"block {kind}": (BOX_BACKGROUND, colour)
        for kind, colour in BLOCK_COLOURS.items()
    },
    **{f"legend {kind}": (colour,) for kind, colour in BLOCK_COLOURS.items()},
    **{
        f"verdict {readable}": (BOX_BACKGROUND, colour)
        for readable, colour in VERDICT_COLOURS.items()
    },
}


def distance(first: str, second: str, under: tuple[float, float, float]) -> float:
    """Returns how far apart two tints look over the opaque colour ``under``, from 0 to 441 (black to white)."""
    return (
        sum((a - b) ** 2 for a, b in zip(blend(first, under), blend(second, under)))
        ** 0.5
    )


class PaletteTest(unittest.TestCase):
    """The playground's colours are readable in light and dark themes, as its text keeps the theme's colour."""

    def test_text_is_readable_on_every_background(self) -> None:
        """The theme's text has a contrast of at least 4.5 (WCAG AA) on every background in every theme.

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

    def test_colours_side_by_side_differ(self) -> None:
        """The colours that stand side by side differ clearly in every theme: those of a slow, a fast and a failed
        disk, and those of a data block, a parity block and a block on a failed disk that is orange or red.

        Would fail if two of them looked alike in a theme, e.g. a slow disk and a failed one, or a parity block and an
        orange one.
        """
        disks: list[str] = list(DISK_COLOURS.values())
        blocks: list[str] = list(BLOCK_COLOURS.values())
        pairs: list[tuple[str, str]] = [
            (first, second)
            for group in (disks, blocks)
            for index, first in enumerate(group)
            for second in group[index + 1 :]
        ]
        for theme, (page, _) in THEMES.items():
            box: tuple[float, float, float] = blend(BOX_BACKGROUND, page)
            for first, second in pairs:
                with self.subTest(theme=theme, first=first, second=second):
                    # at least 25 of the distance 441 between black and white, so the two look different at a glance:
                    self.assertGreaterEqual(distance(first, second, box), 25)

    def test_no_fixed_text_colour(self) -> None:
        """Neither the boxes nor the legend, the headers, the disks, their blocks, the verdicts or the numbers set a
        text colour of their own, so the text keeps the theme's.

        Would fail if black text were set anywhere, which is unreadable on the dark backgrounds of a dark theme.
        """
        # a text colour in CSS, but not a background-color:
        text_colour = re.compile(r"(?<![-\w])color\s*:")
        self.assertIsNone(text_colour.search(BOX_STYLE))
        self.assertIsNone(text_colour.search(LEGEND))
        # A as RAID 5 with a slow disk, then with one and two failed disks, so that every colour is shown once:
        playground = RaidPlayground()
        panel: Panel = playground.panels[0]
        panel.preset.value = "RAID 5"
        click(playground, panel, 0, "slow")
        for slot in (1, 2):
            click(playground, panel, slot, "failed")
            shown: list[widgets.HTML] = [
                panel.header,
                panel.verdict,
                panel.numbers,
                *panel.block_columns,
            ]
            for widget in shown:
                self.assertIsNone(text_colour.search(widget.value))
        for button in panel.disk_buttons:
            self.assertIsNone(button.style.text_color)

    def test_theme_rows_do_not_colour_the_tables(self) -> None:
        """The theme gives the rows of the tables in the boxes no background, even where it stripes or highlights
        rows; a block's own background still shows. The playground shows this style, and each panel, which holds the
        tables of its blocks and of its numbers, is such a box.

        Would fail if the rule lost its ``div`` prefix or its ``:nth-child(n)`` or ``:hover`` selector, so that the
        rows of the numbers got the stripes of a dark theme, or if the style were not shown or a panel were not a
        box.
        """
        self.assertIn(
            "div.raid-box table tr:nth-child(n), div.raid-box table tr:hover {background:transparent}",
            BOX_STYLE,
        )
        # the playground shows the style:
        playground = RaidPlayground()
        self.assertTrue(
            any(
                isinstance(widget, widgets.HTML) and widget.value == BOX_STYLE
                for widget in descendants(playground.widget)
            )
        )
        # each panel is a box with the tables of its blocks and its numbers inside:
        for panel in playground.panels:
            self.assertIn("raid-box", panel.widget.get_state()["_dom_classes"])
            inside: list[widgets.Widget] = descendants(panel.widget)
            for table in [*panel.block_columns, panel.numbers]:
                self.assertIn(table, inside)


# the notebook that shows the playground:
NOTEBOOK: Path = Path(__file__).parents[3] / "notebooks" / "RAID-Playground.ipynb"


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

    def test_introduction_comes_before_the_setup(self) -> None:
        """The introduction stands before the first code cell, as in the MVCC playground.

        Would fail if the notebook opened with the cell that sets up the import path.
        """
        cells: list[dict] = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
        first_code: int = next(
            index for index, cell in enumerate(cells) if cell["cell_type"] == "code"
        )
        self.assertTrue(
            any(
                "# RAID Playground" in "".join(cell["source"])
                for cell in cells[:first_code]
            )
        )


class PressTest(unittest.TestCase):
    """The helper that clicks buttons in these tests."""

    def test_errors_of_click_handlers_are_raised(self) -> None:
        """An exception in a click handler is raised by ``press``, although ipywidgets only logs it.

        Would fail if ``press`` let the exception pass silently, so that a broken handler went unnoticed.
        """
        button = widgets.Button()

        def fail(_: widgets.Button) -> None:
            """A click handler that always fails."""
            raise RuntimeError("the handler failed")

        button.on_click(fail)
        with self.assertRaisesRegex(RuntimeError, "the handler failed"):
            press(button)


class DiskNameTest(unittest.TestCase):
    """The names of the disks."""

    def test_letters_as_in_spreadsheet_columns(self) -> None:
        """The disks are a to z, then aa, ab and so on.

        Would fail if a name repeated or the 27th disk had no name of two letters.
        """
        self.assertEqual(
            ["a", "b", "z", "aa", "ab", "az", "ba", "jj"],
            [disk_name(slot) for slot in (0, 1, 25, 26, 27, 51, 52, 269)],
        )


class NumbersTest(unittest.TestCase):
    """The numbers below a configuration, and which of two configurations has the better value in each row."""

    def test_rows_of_raid_5(self) -> None:
        """RAID 5 over four fast disks shows its numbers as rounded, grouped texts; each score is the value itself,
        except that the blow-up's is its negative, as a lower blow-up is better, the failure counts' is the share of
        survived combinations (4 of 4 gives 1.0), and the disks have none.

        Would fail if a value were formatted without its unit or thousands separator, if a score were taken from
        another row, or if the blow-up's score were not negated, so that the higher blow-up won.
        """
        self.assertEqual(
            [
                NumberRow("disks", "4 (0 slow, 4 fast)", None),
                NumberRow("storage blow-up", "1.33 ×", -4 / 3),
                NumberRow("usable share of the raw capacity", "75%", 0.75),
                NumberRow("sequential read (MB/s)", "600", 600),
                NumberRow("sequential write (MB/s)", "300", 300),
                NumberRow("random read (IOPS)", "8,000", 8000),
                NumberRow("random write (IOPS)", "1,143", 1143),
                NumberRow("survives 1 failed disk", "4 of 4", 1.0),
                NumberRow("survives 2 failed disks", "0 of 6", 0.0),
                NumberRow("survives 3 failed disks", "0 of 4", 0.0),
            ],
            rows_of(configuration(PRESETS["RAID 5"])),
        )

    def test_no_count_for_more_failed_disks_than_disks(self) -> None:
        """RAID 1 over two disks shows "—" without a score for three failed disks, and "0 of 1" for its only double
        failure.

        Would fail if the missing count were shown as "0 of 0" or given a score, which would let it be compared.
        """
        self.assertEqual(
            [
                NumberRow("survives 2 failed disks", "0 of 1", 0.0),
                NumberRow("survives 3 failed disks", "—", None),
            ],
            rows_of(configuration(PRESETS["RAID 1"]))[-2:],
        )

    def test_better_values(self) -> None:
        """Of RAID 0 over four disks and RAID 1 over two, RAID 0 has the lower blow-up and the higher value in every
        row of capacity and performance, RAID 1 survives a larger share of single failures (all 2 against none of
        4); neither is better in the disks, which have no score, in the double failures, which both survive in none
        of their combinations (0 of 6 against 0 of 1), or in the triple failures, which RAID 1 cannot have. The
        result is the same in either order. The missing triple failures of RAID 1 over two disks are not compared with
        the 4 of 4 of RAID 1 over four disks either.

        Would fail if the higher blow-up won, if the comparison were turned round for the second configuration, or
        if a row without a score or with equal scores counted as better for one of them, e.g. if a missing count
        were compared as 0.
        """
        raid_0: list[NumberRow] = rows_of(configuration(PRESETS["RAID 0"]))
        raid_1: list[NumberRow] = rows_of(configuration(PRESETS["RAID 1"]))
        # the rows from the blow-up to the random write IOPS, and the single failures:
        performance: set[int] = {1, 2, 3, 4, 5, 6}
        self.assertEqual((performance, {7}), better(raid_0, raid_1))
        self.assertEqual(({7}, performance), better(raid_1, raid_0))
        # "—" against "4 of 4" for three failed disks, the last row, is in neither:
        four_disks: list[NumberRow] = rows_of(configuration(Structure(1, 4, None, 1)))
        self.assertEqual(("—", "4 of 4"), (raid_1[-1].text, four_disks[-1].text))
        first_better, second_better = better(raid_1, four_disks)
        self.assertNotIn(9, first_better | second_better)

    def test_failure_counts_compare_by_share(self) -> None:
        """Failure counts compare by the share of survived combinations, not by their number: RAID 5 over four disks
        ("4 of 4") ties with RAID 1 over two ("2 of 2") in the single failures, and RAID 1+0 ("4 of 6") is better
        than RAID 5+0 ("9 of 15") in the double failures.

        Would fail if the numbers of survived combinations were compared, so that the larger array won only by
        having more combinations.
        """
        # the single failures, the eighth row: both survive all of them:
        raid_5: list[NumberRow] = rows_of(configuration(PRESETS["RAID 5"]))
        raid_1: list[NumberRow] = rows_of(configuration(PRESETS["RAID 1"]))
        self.assertEqual(("4 of 4", "2 of 2"), (raid_5[7].text, raid_1[7].text))
        first_better, second_better = better(raid_5, raid_1)
        self.assertNotIn(7, first_better | second_better)

        # the double failures, the ninth row: 4 of 6 is the larger share than 9 of 15:
        raid_10: list[NumberRow] = rows_of(configuration(PRESETS["RAID 1+0"]))
        raid_50: list[NumberRow] = rows_of(configuration(PRESETS["RAID 5+0"]))
        self.assertEqual(("4 of 6", "9 of 15"), (raid_10[8].text, raid_50[8].text))
        first_better, second_better = better(raid_10, raid_50)
        self.assertIn(8, first_better)
        self.assertNotIn(8, second_better)

    def test_values_that_look_the_same_are_ties(self) -> None:
        """RAID 5 over three RAID 5 arrays of six disks and RAID 5 over six RAID 5 arrays of three both show a
        blow-up of "1.80 ×", although the first is computed a tiny bit lower (1.7999999999999998); every other row
        is the same as well, so neither panel has a value in bold.

        Would fail if the scores alone decided, so that the first panel showed "1.80 ×" in bold against the same
        "1.80 ×" of the other.
        """
        first: list[NumberRow] = rows_of(configuration(Structure(5, 3, 5, 6)))
        second: list[NumberRow] = rows_of(configuration(Structure(5, 6, 5, 3)))
        # the same text, but different scores:
        self.assertEqual(first[1].text, second[1].text)
        self.assertNotEqual(first[1].score, second[1].score)
        self.assertEqual((set(), set()), better(first, second))

    def test_same_text_is_a_tie_whatever_the_scores(self) -> None:
        """Two rows that show the same text are a tie, even if their scores differ clearly; with different texts,
        the higher score is better.

        Would fail if better() compared only the scores, or compared the texts instead of the scores where they
        differ.
        """
        # the same text, scores 1 and 2:
        same: tuple[list[NumberRow], list[NumberRow]] = (
            [NumberRow("value", "1.80 ×", 1.0)],
            [NumberRow("value", "1.80 ×", 2.0)],
        )
        self.assertEqual((set(), set()), better(*same))
        # different texts, the second higher by its score, although "10" comes before "9" as text:
        different: tuple[list[NumberRow], list[NumberRow]] = (
            [NumberRow("value", "9", 9.0)],
            [NumberRow("value", "10", 10.0)],
        )
        self.assertEqual((set(), {0}), better(*different))

    def test_numbers_html_bolds_exactly_the_given_rows(self) -> None:
        """``numbers_html`` shows one table row per number, with its label and its value, the value in bold exactly
        in the rows given.

        Would fail if a row were bolded by its position counted from 1, or if a value in bold lost its label.
        """
        rows: list[NumberRow] = rows_of(configuration(PRESETS["RAID 5"]))
        shown: str = numbers_html(rows, {1, 7})
        # every label once, in order:
        self.assertEqual(
            [row.label for row in rows], re.findall(r"<th>([^<]*)</th>", shown)
        )
        # exactly the blow-up and the single failures in bold:
        self.assertEqual(
            [("storage blow-up", "1.33 ×"), ("survives 1 failed disk", "4 of 4")],
            re.findall(r"<th>([^<]*)</th><td><b>([^<]*)</b></td>", shown),
        )


class RaidPlaygroundTest(unittest.TestCase):
    """The playground's widgets, driven through their values and button clicks."""

    def test_defaults(self) -> None:
        """The playground starts with A as RAID 0+1 and B as RAID 1+0, four fast disks each with four rows of blocks,
        and the numbers below each panel with the same labels.

        Would fail if the panels started with other presets, too few rows or other numbers in A than in B.
        """
        playground = RaidPlayground()
        a, b = playground.panels
        # the presets and the headers:
        self.assertEqual(("RAID 0+1", "RAID 1+0"), (a.preset.value, b.preset.value))
        self.assertIn(
            "<b>A: RAID 0+1</b> (RAID 1 over 2 RAID 0 arrays of 2 disks each)",
            a.header.value,
        )
        self.assertIn(
            "<b>B: RAID 1+0</b> (RAID 0 over 2 RAID 1 arrays of 2 disks each)",
            b.header.value,
        )
        # four fast disks a to d, each with four data blocks:
        for panel in (a, b):
            self.assertEqual([DISK_COLOURS["fast"]] * 4, colours(panel))
            self.assertEqual(
                ["a fast", "b fast", "c fast", "d fast"],
                [button.description for button in panel.disk_buttons],
            )
            self.assertEqual(
                [[BLOCK_COLOURS["data"]] * 4] * 4,
                [block_backgrounds(panel, slot) for slot in range(4)],
            )
        # the same rows of numbers in both panels:
        self.assertEqual(number_labels(a), number_labels(b))

    def test_default_device_types(self) -> None:
        """The playground starts with the device types of the RAID tests: a slow disk reads 100 and writes 50 MB/s
        and does 1000 random reads and 400 random writes per second, a fast disk twice as much.

        Would fail if the inputs started with other values, or a fast disk were not twice as fast in every value.
        """
        self.assertEqual(
            {
                "slow": DeviceType(100, 50, 1000, 400),
                "fast": DeviceType(200, 100, 2000, 800),
            },
            RaidPlayground().device_types(),
        )

    def test_legend_is_shown(self) -> None:
        """The playground shows the legend, which explains the labels of data and parity blocks in the colours of
        the blocks and the orange and red of blocks on failed disks.

        Would fail if the legend were not shown, showed a colour that the blocks do not use or lacked one they use,
        or showed an example on another colour than the one it explains, e.g. "orange" on red.
        """
        playground = RaidPlayground()
        # the legend is one of the playground's widgets:
        self.assertIn(
            LEGEND,
            [
                widget.value
                for widget in descendants(playground.widget)
                if isinstance(widget, widgets.HTML)
            ],
        )
        # exactly the colours of the blocks:
        self.assertEqual(
            set(BLOCK_COLOURS.values()), set(re.findall(r"background:([^;]+);", LEGEND))
        )
        # every example on the colour it explains:
        examples: tuple[tuple[str, str], ...] = (
            ("data", "0"),
            ("parity", "P[0^1]"),
            ("parity", "p[0^2]"),
            ("recoverable", "orange"),
            ("lost", "red"),
        )
        for kind, text in examples:
            self.assertIn(swatch(BLOCK_COLOURS[kind], text), LEGEND)

    def test_click_failed_toggles(self) -> None:
        """In the mode "failed", a click on a disk marks it failed and colours it red; a second click repairs it.

        Would fail if a click marked another slot than the one clicked, did not toggle, or changed the preset.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        # the first click fails disk b:
        click(playground, a, 1, "failed")
        self.assertEqual({1}, a.failed)
        self.assertEqual(DISK_COLOURS["failed"], colours(a)[1])
        self.assertEqual("b fast failed", a.disk_buttons[1].description)
        self.assertIn("Failed disks: b", a.verdict.value)
        # the second click repairs it:
        click(playground, a, 1, "failed")
        self.assertEqual(set(), a.failed)
        self.assertEqual([DISK_COLOURS["fast"]] * 4, colours(a))
        self.assertEqual("RAID 0+1", a.preset.value)

    def test_click_slow_and_fast(self) -> None:
        """In the modes "slow" and "fast", a click makes the disk of that kind and colours it accordingly.

        Would fail if the kind were set for another slot or the preset switched to "own" on a click.
        """
        playground = RaidPlayground()
        b: Panel = playground.panels[1]
        # disk c becomes slow:
        click(playground, b, 2, "slow")
        self.assertEqual(["fast", "fast", "slow", "fast"], b.kinds)
        self.assertEqual(DISK_COLOURS["slow"], colours(b)[2])
        self.assertIn("<td>4 (1 slow, 3 fast)</td>", b.numbers.value)
        # and fast again:
        click(playground, b, 2, "fast")
        self.assertEqual(["fast"] * 4, b.kinds)
        self.assertEqual(DISK_COLOURS["fast"], colours(b)[2])
        self.assertEqual("RAID 1+0", b.preset.value)

    def test_fail_disks_a_and_d_in_both_panels(self) -> None:
        """With disks a and d failed, RAID 0+1 loses data by the model, as each stripe lost a disk, although every
        block is still on b or c: its blocks on a and d are orange and a note explains the difference. RAID 1+0 keeps
        a disk of each mirrored pair and reads all data, without a note.

        Would fail if the verdict followed the blocks instead of survives(), the note were missing or shown where
        both agree, or the blocks on the failed disks were red.
        """
        playground = RaidPlayground()
        a, b = playground.panels
        for panel in (a, b):
            for slot in (0, 3):
                click(playground, panel, slot, "failed")
        # A: data lost by the model, the blocks on a and d orange, with the note:
        self.assertIn(
            f'background:{VERDICT_COLOURS[False]}; padding:6px"><b>Data is lost.</b> Failed disks: a, d',
            a.verdict.value,
        )
        self.assertIn(html.escape(WHOLE_MEMBER_NOTE), a.verdict.value)
        for slot in (0, 3):
            self.assertEqual(
                [BLOCK_COLOURS["recoverable"]] * 4, block_backgrounds(a, slot)
            )
        # B: all data readable, no note:
        self.assertIn(
            f'background:{VERDICT_COLOURS[True]}; padding:6px"><b>All data can be read.</b> Failed disks: a, d',
            b.verdict.value,
        )
        self.assertNotIn(html.escape(WHOLE_MEMBER_NOTE), b.verdict.value)

    def test_lost_blocks_are_red_without_a_note(self) -> None:
        """With disks a and c failed in RAID 0+1, the even blocks have lost both copies: the blocks on a and c are
        red, and there is no note, as the blocks agree with the model.

        Would fail if lost blocks were orange or the note were shown although a block is lost.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        for slot in (0, 2):
            click(playground, a, slot, "failed")
        self.assertEqual([BLOCK_COLOURS["lost"]] * 4, block_backgrounds(a, 0))
        self.assertEqual([BLOCK_COLOURS["lost"]] * 4, block_backgrounds(a, 2))
        self.assertIn("Data is lost.", a.verdict.value)
        self.assertNotIn(html.escape(WHOLE_MEMBER_NOTE), a.verdict.value)

    def test_better_values_are_bold(self) -> None:
        """Of RAID 0+1 and RAID 1+0, only B's 4 of 6 survived double failures is better than A's 2 of 6 and in bold;
        all other rows are equal and in neither panel bold.

        Would fail if ties were in bold, or the better value were chosen the wrong way round.
        """
        playground = RaidPlayground()
        a, b = playground.panels
        self.assertEqual([], bold_values(a))
        self.assertEqual(["4 of 6"], bold_values(b))

    def test_switch_b_off_and_on(self) -> None:
        """Without B, A takes the full width, B is hidden and no value is in bold; switched on again, both share the
        width and the better value is bold again.

        Would fail if B stayed visible, A kept half the width, or a value stayed in bold with nothing to compare.
        """
        playground = RaidPlayground()
        a, b = playground.panels
        # B off:
        playground.compare_b.value = False
        self.assertEqual(
            ("100%", "none"), (a.widget.layout.width, b.widget.layout.display)
        )
        self.assertEqual(([], []), (bold_values(a), bold_values(b)))
        # B on again:
        playground.compare_b.value = True
        self.assertEqual(
            ("50%", None), (a.widget.layout.width, b.widget.layout.display)
        )
        self.assertEqual(["4 of 6"], bold_values(b))

    def test_numbers_stand_at_the_bottom_of_each_panel(self) -> None:
        """The numbers are the last part of each panel and pushed to its bottom, so that the rows of A and B stand at
        the same height also when the disks of A and B are of different height.

        Would fail if the numbers were not last, or lost the automatic top margin that pushes them down.
        """
        playground = RaidPlayground()
        a, b = playground.panels
        b.preset.value = "RAID 5+0"
        for panel in (a, b):
            self.assertIs(panel.numbers, panel.widget.children[-1])
            self.assertTrue(panel.numbers.layout.margin.startswith("auto "))
        self.assertEqual(number_labels(a), number_labels(b))

    def test_disks_are_grouped_by_inner_array(self) -> None:
        """A single-level array shows all its disks in one box named after its level; RAID 5+0 shows one box per
        RAID 5 array, with the disks a to c and d to f.

        Would fail if a single-level array got a box per disk, or a nested array mixed the disks of its inner arrays.
        """
        playground = RaidPlayground()
        a, b = playground.panels
        a.preset.value = "RAID 5"
        b.preset.value = "RAID 5+0"
        self.assertEqual(
            [("RAID 5", ["a fast", "b fast", "c fast", "d fast"])], groups(a)
        )
        self.assertEqual(
            [
                ("RAID 5 #1", ["a fast", "b fast", "c fast"]),
                ("RAID 5 #2", ["d fast", "e fast", "f fast"]),
            ],
            groups(b),
        )

    def test_inner_raid_5_raises_inner_members(self) -> None:
        """Choosing RAID 5 as B's inner level raises its members per inner array from 2 to 3, builds six disks and
        switches the preset to "own".

        Would fail if the inner slider kept 2 members, so that the configuration were rejected, or if the disks were
        not rebuilt.
        """
        playground = RaidPlayground()
        b: Panel = playground.panels[1]
        b.inner_level.value = 5
        self.assertEqual(3, b.inner_members.value)
        # two RAID 5 arrays of three disks each, no longer the preset:
        self.assertEqual(Structure(0, 2, 5, 3), b.structure)
        self.assertEqual(6, len(b.disk_buttons))
        self.assertEqual(OWN, b.preset.value)
        self.assertIn("<b>B: RAID 5+0</b>", b.header.value)

    def test_member_count_change_clears_marks(self) -> None:
        """Changing A's number of outer members clears its failed and slow disks.

        Would fail if marks of the old slots were kept for disks that now sit in other inner arrays.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        click(playground, a, 0, "failed")
        click(playground, a, 1, "slow")
        # three stripes of two disks instead of two:
        a.outer_members.value = 3
        self.assertEqual(set(), a.failed)
        self.assertEqual(["fast"] * 6, a.kinds)
        self.assertEqual([DISK_COLOURS["fast"]] * 6, colours(a))

    def test_level_change_keeps_marks(self) -> None:
        """Changing only A's inner level from RAID 0 to RAID 1 keeps its failed and slow disks, and the new
        structure (RAID 1 over mirrored pairs) survives the failure of disks a and c.

        Would fail if the marks were cleared on a change that keeps every disk in its inner array.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        for slot in (0, 2):
            click(playground, a, slot, "failed")
        click(playground, a, 1, "slow")
        # only the inner level changes:
        a.inner_level.value = 1
        self.assertEqual(Structure(1, 2, 1, 2), a.structure)
        self.assertEqual(
            ({0, 2}, ["fast", "slow", "fast", "fast"]), (a.failed, a.kinds)
        )
        self.assertIn("All data can be read.", a.verdict.value)

    def test_preset_with_same_member_counts_keeps_marks(self) -> None:
        """Choosing the preset RAID 1+0 in A, which has the same member counts as RAID 0+1, keeps A's marks and
        judges them anew.

        Would fail if choosing a preset always cleared the marks, so that the two structures could not be compared
        on the same failures.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        for slot in (0, 2):
            click(playground, a, slot, "failed")
        click(playground, a, 1, "slow")
        self.assertIn("Data is lost.", a.verdict.value)
        # the same failures in RAID 1+0:
        a.preset.value = "RAID 1+0"
        self.assertEqual(PRESETS["RAID 1+0"], a.structure)
        self.assertEqual(
            ({0, 2}, ["fast", "slow", "fast", "fast"]), (a.failed, a.kinds)
        )
        self.assertIn("All data can be read.", a.verdict.value)

    def test_single_level_has_no_inner_members(self) -> None:
        """Choosing no inner level for A makes a single-level array over its outer members and disables the inner
        slider.

        Would fail if the inner slider's value still multiplied the number of disks.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        a.inner_level.value = NO_INNER
        self.assertEqual(Structure(1, 2, None, 1), a.structure)
        self.assertEqual(2, len(a.disk_buttons))
        self.assertTrue(a.inner_members.disabled)

    def test_old_disk_buttons_are_closed(self) -> None:
        """Rebuilding the disks closes the old buttons, with their layout and style, and the tables of their blocks.

        Would fail if the old widgets stayed open, so that they piled up in the kernel and the browser.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        old_button: widgets.Button = a.disk_buttons[0]
        old_blocks: widgets.HTML = a.block_columns[0]

        # the old widgets are open before the rebuild, so that the checks below can fail:
        for widget in (old_button, old_button.layout, old_button.style, old_blocks):
            self.assertIsNotNone(widget.comm)

        # three stripes instead of two rebuild the disks; the old widgets are closed:
        a.outer_members.value = 3
        self.assertIsNot(old_button, a.disk_buttons[0])
        self.assertEqual(
            (None, None, None),
            (old_button.comm, old_button.layout.comm, old_button.style.comm),
        )
        self.assertIsNone(old_blocks.comm)

    def test_device_input_updates_numbers(self) -> None:
        """Raising the sequential read of a fast disk to 500 MB/s raises that of both default arrays from 800 to
        2,000 MB/s.

        Would fail if the numbers did not observe the device inputs or read another field than the one changed.
        """
        playground = RaidPlayground()
        row: str = "<th>sequential read (MB/s)</th><td>{0}</td>"
        for panel in playground.panels:
            self.assertIn(row.format("800"), panel.numbers.value)
        playground.device_inputs[("fast", "sequential_read")].value = 500
        for panel in playground.panels:
            self.assertIn(row.format("2,000"), panel.numbers.value)

    def test_blocks_of_raid_5(self) -> None:
        """For A as RAID 5 over four disks, every disk shows four blocks, the parity on its own colour; the blocks
        of a single failed disk turn orange, those of two failed disks red.

        Would fail if the parity had the colour of data, or a failed disk's blocks kept their colours.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        a.preset.value = "RAID 5"
        self.assertIn("(RAID 5 over 4 disks)", a.header.value)
        # disk d holds the parity of row 0:
        data, parity = BLOCK_COLOURS["data"], BLOCK_COLOURS["parity"]
        self.assertEqual([parity, data, data, data], block_backgrounds(a, 3))
        self.assertIn(">P[0^1^2]</td>", a.block_columns[3].value)
        # disk b fails: its blocks can be rebuilt:
        click(playground, a, 1, "failed")
        self.assertEqual([BLOCK_COLOURS["recoverable"]] * 4, block_backgrounds(a, 1))
        # disk c fails as well: the blocks of both are lost:
        click(playground, a, 2, "failed")
        for slot in (1, 2):
            self.assertEqual([BLOCK_COLOURS["lost"]] * 4, block_backgrounds(a, slot))


class BlocksTest(unittest.TestCase):
    """The blocks below the disks: their colours on failed disks, how many rows they fill and how wide their
    columns are."""

    def test_orange_and_red_blocks_in_one_panel(self) -> None:
        """With disks a, b and d failed in RAID 0+1, the blocks on a are orange, as c still holds them, while those
        on b and d are red, as both copies of the odd blocks are gone; the blocks on c keep the colour of data.

        Would fail if the widget coloured the blocks of all failed disks of a panel alike, e.g. by the verdict for
        the whole array.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        for slot in (0, 1, 3):
            click(playground, a, slot, "failed")
        # a orange, b and d red, c as before:
        orange, red = BLOCK_COLOURS["recoverable"], BLOCK_COLOURS["lost"]
        self.assertEqual(
            [[orange] * 4, [red] * 4, [BLOCK_COLOURS["data"]] * 4, [red] * 4],
            [block_backgrounds(a, slot) for slot in range(4)],
        )

    def test_parity_on_a_failed_disk(self) -> None:
        """With disks a and b failed, the inner parity ``p[2^3]`` on a is orange in RAID 5+1, as the mirror still
        holds the blocks 2 and 3; the inner parity ``p[4^6]`` on a is red in RAID 5+0, as block 4 on b is lost and
        no other disk holds it.

        Would fail if a parity block on a failed disk were coloured by its own inner array alone, or if parity on a
        failed disk were always orange or always red.
        """
        # A as RAID 5+1 and B as RAID 5+0, each with a and b failed:
        playground = RaidPlayground()
        a, b = playground.panels
        a.preset.value = "RAID 5+1"
        b.preset.value = "RAID 5+0"
        for panel in (a, b):
            for slot in (0, 1):
                click(playground, panel, slot, "failed")
        # the second block below disk a of each panel:
        self.assertEqual((BLOCK_COLOURS["recoverable"], "p[2^3]"), block_cells(a, 0)[1])
        self.assertEqual((BLOCK_COLOURS["lost"], "p[4^6]"), block_cells(b, 0)[1])

    def test_one_block_row_per_disk_but_at_least_four(self) -> None:
        """Below every disk of RAID 5 over six disks stand six blocks, one of them parity, so that the parity goes
        round all disks; below each disk of RAID 1 over two disks stand four blocks.

        Would fail if the widget showed a fixed number of rows, or one row per disk without the lower bound of four.
        """
        playground = RaidPlayground()
        a, b = playground.panels
        # A as RAID 5 over six disks, B as RAID 1 over two:
        a.preset.value = "RAID 5"
        a.outer_members.value = 6
        b.preset.value = "RAID 1"
        # six rows below each disk of A, one of them parity:
        for slot in range(6):
            backgrounds: list[str] = block_backgrounds(a, slot)
            self.assertEqual(6, len(backgrounds))
            self.assertEqual(1, backgrounds.count(BLOCK_COLOURS["parity"]))
        # four rows below each disk of B:
        self.assertEqual([4, 4], [len(block_backgrounds(b, slot)) for slot in (0, 1)])

    def test_columns_are_as_wide_as_the_longest_block(self) -> None:
        """The disk columns of every preset have the smallest width, as their blocks are short; in RAID 5+5 over
        three arrays of three disks, the longest block ``p[P[20^21]^22]`` of 14 characters needs 8 * 14 + 12 = 124
        pixels, and every disk button and every table of blocks of the panel gets that width.

        Would fail if a long block widened only its own column, so that the rows of the disks no longer lined up, if
        the width ignored the longest block, or if it fell below the smallest width.
        """
        # the smallest width for the short blocks of the presets, more for RAID 5+5:
        for name, structure in PRESETS.items():
            with self.subTest(preset=name):
                self.assertEqual(
                    MIN_COLUMN_WIDTH, column_width(configuration(structure))
                )
        self.assertEqual(124, column_width(configuration(Structure(5, 3, 5, 3))))
        # A as RAID 5+5: RAID 5 as the outer and the inner level raises both member counts to 3:
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        a.outer_level.value = 5
        a.inner_level.value = 5
        self.assertEqual(Structure(5, 3, 5, 3), a.structure)
        # the longest block is shown, as parity:
        self.assertIn(
            (BLOCK_COLOURS["parity"], "p[P[20^21]^22]"),
            [cell for slot in range(9) for cell in block_cells(a, slot)],
        )
        # every button and every table of blocks is as wide:
        self.assertEqual(
            {"124px"},
            {widget.layout.width for widget in [*a.disk_buttons, *a.block_columns]},
        )


class PresetTest(unittest.TestCase):
    """The preset dropdown of a panel: it shows the chosen preset until a level or a member count is changed by
    hand, then "own"."""

    def test_chosen_preset_stays_shown(self) -> None:
        """Choosing each preset in A, one after the other, builds its structure and leaves the dropdown on it.

        Would fail if setting the controls to a preset were taken for a change by hand, which switches the dropdown
        to "own", e.g. where the preset raises a member slider's lower end.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        for name, structure in PRESETS.items():
            with self.subTest(preset=name):
                a.preset.value = name
                self.assertEqual(name, a.preset.value)
                self.assertEqual(structure, a.structure)
                self.assertIn(f"<b>A: {name}</b>", a.header.value)

    def test_changing_the_structure_shows_own(self) -> None:
        """Changing A's outer members, its members per inner array or its outer level switches A's dropdown to
        "own"; B keeps its preset.

        Would fail if one of these controls did not switch the dropdown, so that it named a preset the panel no
        longer shows, or if a change in A switched B as well.
        """
        changes: tuple[tuple[str, int], ...] = (
            ("outer_members", 3),
            ("inner_members", 3),
            ("outer_level", 0),
        )
        for control, value in changes:
            with self.subTest(control=control):
                playground = RaidPlayground()
                a, b = playground.panels
                getattr(a, control).value = value
                self.assertEqual((OWN, "RAID 1+0"), (a.preset.value, b.preset.value))

    def test_choosing_own_changes_nothing(self) -> None:
        """Choosing "own" in A's dropdown by hand keeps A's structure, its marks and its disk buttons.

        Would fail if "own" were looked up as a preset, or if it rebuilt the disks or cleared the marks.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        mark(playground, a)
        buttons: list[widgets.Button] = list(a.disk_buttons)
        # choose "own":
        a.preset.value = OWN
        self.assertEqual(PRESETS["RAID 0+1"], a.structure)
        self.assertEqual(
            ["a fast failed", "b slow", "c fast", "d fast"], descriptions(a)
        )
        # the same buttons as before, not rebuilt:
        self.assertEqual(
            [id(button) for button in buttons],
            [id(button) for button in a.disk_buttons],
        )

    def test_device_inputs_keep_presets_and_marks(self) -> None:
        """Changing any of the eight inputs of the device types leaves the presets of A and B and A's marks as they
        are.

        Would fail if a change of a device type were taken for a change of the structure, which switches the
        dropdown to "own", or rebuilt the disks and cleared their marks.
        """
        playground = RaidPlayground()
        a, b = playground.panels
        mark(playground, a)
        # triple one value after the other:
        for (kind, field), text in playground.device_inputs.items():
            with self.subTest(kind=kind, field=field):
                text.value = 3 * text.value
                self.assertEqual(
                    ("RAID 0+1", "RAID 1+0"), (a.preset.value, b.preset.value)
                )
                self.assertEqual(
                    ["a fast failed", "b slow", "c fast", "d fast"], descriptions(a)
                )


class MarksTest(unittest.TestCase):
    """When a panel keeps the marks of its disks (failed, slow) and when it clears them: it keeps them as long as
    both member counts stay the same, so that every disk keeps its place."""

    def test_marks_kept_while_member_counts_stay(self) -> None:
        """A change of the outer level that leaves both member counts as they are keeps the marks: RAID 0+1 becomes
        RAID 0+0, and RAID 5 over four disks becomes RAID 0 over four disks, whose slider keeps its four members
        although RAID 0 would allow two.

        Would fail if every change of a level cleared the marks, or if lowering a slider's lower end lowered its
        value as well.
        """
        cases: tuple[tuple[str, Structure], ...] = (
            ("RAID 0+1", Structure(0, 2, 0, 2)),
            ("RAID 5", Structure(0, 4, None, 1)),
        )
        for start, structure in cases:
            with self.subTest(start=start):
                playground = RaidPlayground()
                a: Panel = playground.panels[0]
                # A on the preset to start from, with a failed and b slow:
                a.preset.value = start
                mark(playground, a)
                # RAID 0 as the outer level:
                a.outer_level.value = 0
                self.assertEqual(structure, a.structure)
                self.assertEqual(
                    ["a fast failed", "b slow", "c fast", "d fast"], descriptions(a)
                )

    def test_marks_cleared_when_a_member_count_changes(self) -> None:
        """The marks are cleared when a member count changes: by the inner slider, by a level change that raises a
        slider to the three members of RAID 5 (outer or inner), by adding or removing the inner level, and by a
        preset with other member counts, even if it has as many disks (RAID 0+1 to RAID 5).

        Would fail if the marks were kept for disks that now sit in another inner array or at another position, or
        if only the number of disks were compared.
        """
        cases: tuple[tuple[str, str, int | str, Structure], ...] = (
            # the members per inner array, from 2 to 3:
            ("RAID 0+1", "inner_members", 3, Structure(1, 2, 0, 3)),
            # RAID 5 as the outer level raises the outer members from 2 to 3:
            ("RAID 1+0", "outer_level", 5, Structure(5, 3, 1, 2)),
            # RAID 5 as the inner level raises the members per inner array from 2 to 3:
            ("RAID 1+0", "inner_level", 5, Structure(0, 2, 5, 3)),
            # an inner level added to RAID 0 over four disks, and one removed from RAID 0+1:
            ("RAID 0", "inner_level", 0, Structure(0, 4, 0, 2)),
            ("RAID 0+1", "inner_level", NO_INNER, Structure(1, 2, None, 1)),
            # a preset with the same four disks, but other member counts:
            ("RAID 0+1", "preset", "RAID 5", Structure(5, 4, None, 1)),
        )
        for start, control, value, structure in cases:
            with self.subTest(start=start, control=control, value=value):
                playground = RaidPlayground()
                a: Panel = playground.panels[0]
                # A on the preset to start from, with a failed and b slow:
                a.preset.value = start
                mark(playground, a)
                # change the control:
                getattr(a, control).value = value
                self.assertEqual(structure, a.structure)
                disks: int = structure.outer_members * structure.inner_members
                self.assertEqual(
                    [f"{disk_name(slot)} fast" for slot in range(disks)],
                    descriptions(a),
                )
                self.assertEqual(set(), a.failed)


class MemberSliderTest(unittest.TestCase):
    """The ranges of the member sliders."""

    def test_member_sliders_follow_their_levels(self) -> None:
        """Each member slider starts at the fewest members of its level, 2 for RAID 0 and RAID 1 and 3 for RAID 5,
        and ends at 6; its lower end goes back to 2 when RAID 5 is replaced by RAID 0 or RAID 1.

        Would fail if a slider kept the lower end of RAID 5 after a change to RAID 0 or RAID 1, so that two members
        could no longer be chosen, or if it offered more members than the model accepts.
        """
        playground = RaidPlayground()
        a: Panel = playground.panels[0]
        for level, fewest in ((5, 3), (0, 2), (5, 3), (1, 2)):
            with self.subTest(level=level):
                # the same level outside and inside:
                a.outer_level.value = level
                a.inner_level.value = level
                self.assertEqual(
                    (fewest, 6), (a.outer_members.min, a.outer_members.max)
                )
                self.assertEqual(
                    (fewest, 6), (a.inner_members.min, a.inner_members.max)
                )


class DeviceTypesTest(unittest.TestCase):
    """The inputs of the device types and the numbers they drive."""

    def test_device_types_follow_the_inputs(self) -> None:
        """Every input sets its own value of its own kind of disk.

        Would fail if an input were read into another field of the device type, or into the other kind.
        """
        playground = RaidPlayground()
        fields: tuple[str, ...] = (
            "sequential_read",
            "sequential_write",
            "read_IOPS",
            "write_IOPS",
        )
        # 1 to 4 for the slow disks, 5 to 8 for the fast ones, in the order of the fields of DeviceType:
        offsets: tuple[tuple[DeviceKind, int], ...] = (("slow", 0), ("fast", 4))
        for kind, offset in offsets:
            for number, field in enumerate(fields, start=1):
                playground.device_inputs[(kind, field)].value = offset + number
        self.assertEqual(
            {"slow": DeviceType(1, 2, 3, 4), "fast": DeviceType(5, 6, 7, 8)},
            playground.device_types(),
        )

    def test_each_device_value_drives_its_numbers(self) -> None:
        """With A as RAID 5 over four slow disks and B as RAID 5 over four fast ones, tripling one value of a kind
        changes exactly the numbers of the panel with that kind that the cost model computes from it, and none of
        the other panel: sequential read and write only their own row, write IOPS only the random write, read IOPS
        the random read and the random write, as a small write in RAID 5 reads the old data and parity first.

        Would fail if a value were passed to the cost model as another one, or applied to the disks of the other
        kind.
        """
        rows_by_field: dict[str, set[str]] = {
            "sequential_read": {"sequential read (MB/s)"},
            "sequential_write": {"sequential write (MB/s)"},
            "read_IOPS": {"random read (IOPS)", "random write (IOPS)"},
            "write_IOPS": {"random write (IOPS)"},
        }
        for kind in ("slow", "fast"):
            for field, rows in rows_by_field.items():
                with self.subTest(kind=kind, field=field):
                    # A as RAID 5 over four slow disks, B as RAID 5 over four fast ones:
                    playground = RaidPlayground()
                    a, b = playground.panels
                    for panel in (a, b):
                        panel.preset.value = "RAID 5"
                    for slot in range(4):
                        click(playground, a, slot, "slow")
                    before: list[dict[str, str]] = [number_texts(a), number_texts(b)]
                    # triple the value:
                    text = playground.device_inputs[(kind, field)]
                    text.value = 3 * text.value
                    after: list[dict[str, str]] = [number_texts(a), number_texts(b)]
                    # the rows that changed, in A and in B:
                    changed: list[set[str]] = [
                        {label for label, shown in old.items() if new[label] != shown}
                        for old, new in zip(before, after)
                    ]
                    self.assertEqual(
                        [rows, set()] if kind == "slow" else [set(), rows], changed
                    )
