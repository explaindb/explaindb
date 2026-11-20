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

"""Widgets of the RAID playground: two RAID arrays side by side, with their disks, blocks and numbers.

Disks are failed or marked slow or fast by clicking; the blocks below each disk and the numbers below each array
change at once.
"""

from __future__ import annotations

import html
from collections.abc import Set
from typing import Literal, NamedTuple, cast

import ipywidgets as widgets

from system.playground.raid_playground import (
    DEFAULT_DEVICE_TYPES,
    DEFAULT_KIND,
    DEVICE_KINDS,
    FAILED_DISK_COUNTS,
    LEVELS,
    MAX_MEMBERS,
    MIN_MEMBERS,
    PRESETS,
    BlockCell,
    Configuration,
    DeviceKind,
    DeviceType,
    Level,
    Metrics,
    Structure,
    all_blocks_readable,
    all_data_readable,
    block_rows,
    configuration,
    disk_blocks,
    layout,
    metrics,
)
from system.storage.RAID.cost_model import FailureCount

# what a click on a disk does: mark it failed (or working again), or make it slow or fast:
ClickMode = Literal["failed", "slow", "fast"]
CLICK_MODES: tuple[ClickMode, ...] = ("failed", "slow", "fast")
# the preset dropdown shows this once a level or a member count was changed by hand:
OWN: str = "own"
# the value of the inner level dropdown for a single-level array:
NO_INNER: int = -1
# the four values of a device type, in the order of the columns of the device types' table:
DEVICE_FIELDS: tuple[tuple[str, str], ...] = (
    ("sequential_read", "sequential read (MB/s)"),
    ("sequential_write", "sequential write (MB/s)"),
    ("read_IOPS", "random read (IOPS)"),
    ("write_IOPS", "random write (IOPS)"),
)
# The playground sets no text colour, so its text keeps the colour of the theme; its backgrounds are translucent
# tints, as in the MVCC playground (see mvcc_widgets.py), that show light over a light page and dark over a dark one.
# background of a disk button by the disk's kind, or red if it has failed:
DISK_COLOURS: dict[str, str] = {
    "slow": "rgba(128,128,128,0.3)",
    "fast": "rgba(33,150,243,0.25)",
    "failed": "rgba(244,67,54,0.35)",
}
# background of a block in a disk column: a data block or a parity block on a working disk, or a block on a failed
# disk by its state, orange if what it holds can still be read or rebuilt, red if it is lost:
BLOCK_COLOURS: dict[str, str] = {
    "data": "rgba(128,128,128,0.12)",
    "parity": "rgba(156,39,176,0.25)",
    "recoverable": "rgba(255,152,0,0.35)",
    "lost": DISK_COLOURS["failed"],
}
# background of the verdict: all data readable or not:
VERDICT_COLOURS: dict[bool, str] = {
    True: "rgba(76,175,80,0.35)",
    False: "rgba(244,67,54,0.35)",
}
# one style for the boxes of the panels, the disk groups and the tables (see BOX_STYLE in mvcc_widgets.py for why
# the rules for the rows and cells are as specific as they are). The text of an HTML widget has the line height of a
# widget's row (28 pixels), which the tables of the blocks and the numbers set back to that of normal text. The
# blocks are written in a fixed-width font and never wrap, so that every block has the height of one line and the
# rows of all disks stand at the same height; the numbers never wrap either, so that their rows in A and B have the
# same height. The verdict, whose note may take two lines, has the line height of normal text as well:
BOX_STYLE: str = (
    "<style>.raid-box {border:1px solid rgba(128,128,128,0.5); background:rgba(128,128,128,0.08); padding:6px; "
    "margin:6px 0} "
    ".raid-group {border:1px dashed rgba(128,128,128,0.6); padding:4px; margin:2px} "
    "div.raid-box table tr:nth-child(n), div.raid-box table tr:hover {background:transparent} "
    "div.raid-box table {border-collapse:collapse} "
    "div.raid-box th, div.raid-box td {border:1px solid rgba(128,128,128,0.5); padding:2px 8px} "
    "div.raid-box table.raid-blocks {width:100%; line-height:1.5} "
    "div.raid-box table.raid-blocks td {padding:0 2px; text-align:center; white-space:nowrap; "
    "font-family:monospace} "
    "div.raid-box table.raid-numbers {line-height:1.5; white-space:nowrap} "
    "div.raid-box table.raid-numbers th {text-align:left} "
    "div.raid-verdict {line-height:1.5}</style>"
)
# the narrowest disk column in pixels, enough for a button such as "aa slow failed":
MIN_COLUMN_WIDTH: int = 110
# a disk column is wider if a block needs it: about 8 pixels per character of the fixed-width font, plus the padding
# and the lines of the cell:
CHARACTER_WIDTH: int = 8
CELL_PADDING: int = 12


def swatch(colour: str, text: str) -> str:
    """Shows a short text on a background, as an example of a colour in the legend.

    @param colour: the background
    @param text: the text
    @return: the HTML
    """
    return (
        f'<span style="background:{colour}; padding:0 4px">{html.escape(text)}</span>'
    )


# the legend of the blocks below the disks:
LEGEND: str = (
    "<b>Blocks</b> below each disk, row by row: "
    f"{swatch(BLOCK_COLOURS['data'], '0')} a data block, "
    f"{swatch(BLOCK_COLOURS['parity'], 'P[0^1]')} the parity (XOR) of the blocks 0 and 1, "
    f"{swatch(BLOCK_COLOURS['parity'], 'p[0^2]')} the parity of an inner RAID 5 array over the other blocks of its "
    "row in that array. On a failed disk: "
    f"{swatch(BLOCK_COLOURS['recoverable'], 'orange')} what the block holds can still be read or rebuilt, "
    f"{swatch(BLOCK_COLOURS['lost'], 'red')} it is lost."
)
# the note below a verdict of lost data where every block can still be read on its own:
WHOLE_MEMBER_NOTE: str = (
    "Block by block, every data block can still be read (orange), but the model, like a typical RAID 0+1 "
    "controller, counts an array member that lost data as failed as a whole."
)


def disk_name(slot: int) -> str:
    """Returns the name of the disk in a slot: a to z, then aa, ab and so on, as spreadsheets name their columns.

    Disks have letters, so that they are not mistaken for the numbers of the blocks below them.

    @param slot: the slot, from 0
    @return: the name, e.g. ``a`` for slot 0 and ``aa`` for slot 26
    """
    name: str = ""
    # the slot plus 1 written in base 26 with the digits a to z, which has no zero:
    rest: int = slot + 1
    while rest:
        rest, digit = divmod(rest - 1, 26)
        name = chr(ord("a") + digit) + name
    return name


def describe(config: Configuration) -> str:
    """Describes the structure of a configuration in words.

    @param config: the configuration
    @return: e.g. ``RAID 1 over 2 RAID 0 arrays of 2 disks each``
    """
    if config.inner_level is None:
        return f"RAID {config.outer_level} over {config.outer_members} disks"
    return (
        f"RAID {config.outer_level} over {config.outer_members} RAID {config.inner_level} arrays "
        f"of {config.inner_members} disks each"
    )


def slots_text(slots: Set[int]) -> str:
    """Lists disks by their names.

    @param slots: the slots of the disks
    @return: their names in slot order, e.g. ``a, d``, or ``none``
    """
    return ", ".join(disk_name(slot) for slot in sorted(slots)) or "none"


def verdict_html(readable: bool, blocks_readable: bool, failed: Set[int]) -> str:
    """Shows whether all data can be read with the failed disks, on a green or red background.

    @param readable: whether all data can be read, as :func:`all_data_readable` decides it
    @param blocks_readable: whether every block can be read on its own, see :func:`all_blocks_readable`
    @param failed: the slots of the failed disks
    @return: the HTML, with :data:`WHOLE_MEMBER_NOTE` where data is lost but every block can be read
    """
    text: str = "All data can be read." if readable else "Data is lost."
    note: str = (
        f"<br><small>{html.escape(WHOLE_MEMBER_NOTE)}</small>"
        if blocks_readable and not readable
        else ""
    )
    return (
        f'<div class="raid-verdict" style="background:{VERDICT_COLOURS[readable]}; padding:6px">'
        f"<b>{text}</b> Failed disks: {slots_text(failed)}{note}</div>"
    )


def block_colour(cell: BlockCell) -> str:
    """Returns the background of a block in a disk column.

    @param cell: the block and its state
    @return: a value of :data:`BLOCK_COLOURS`: by the state on a failed disk, else by whether it is data or parity
    """
    if cell.state != "ok":
        return BLOCK_COLOURS[cell.state]
    return BLOCK_COLOURS[
        "data" if cell.block.logical_block_ID is not None else "parity"
    ]


def blocks_html(cells: list[BlockCell]) -> str:
    """Shows the blocks of one disk as a table with one row per block.

    @param cells: the blocks and their states, from the first row to the last
    @return: the HTML
    """
    rows: str = "".join(
        f'<tr><td style="background:{block_colour(cell)}">{html.escape(cell.block.text)}</td></tr>'
        for cell in cells
    )
    return f'<table class="raid-blocks">{rows}</table>'


def column_width(config: Configuration) -> int:
    """Returns the width of the disk columns of a configuration, the same for all its disks.

    @param config: the configuration
    @return: the width in pixels: :data:`MIN_COLUMN_WIDTH`, or more if the longest block needs it
    """
    longest: int = max(
        len(block.text)
        for column in layout(config, block_rows(config))
        for block in column
    )
    return max(MIN_COLUMN_WIDTH, CHARACTER_WIDTH * longest + CELL_PADDING)


def count_text(count: FailureCount | None) -> str:
    """Shows a failure count.

    @param count: the count, None if the array has fewer disks than fail
    @return: ``survived of total``, or ``—`` without a count
    """
    return "—" if count is None else f"{count.survived} of {count.total}"


class NumberRow(NamedTuple):
    """One row of the numbers below a configuration."""

    # the label, the same in every panel:
    label: str
    # the value as shown:
    text: str
    # the value as a score where a higher score is better, so that the better value of two panels can be shown in
    # bold; for a failure count the share of the survived combinations, so that a larger array does not win only by
    # having more combinations; None where no value is better (the disks) or the array has too few disks for a count:
    score: float | None


def number_rows(config: Configuration, result: Metrics) -> list[NumberRow]:
    """Returns the numbers shown below a configuration, row by row, with the same labels for every configuration.

    A lower storage blow-up is better; in every other row with a score a higher value is better: a larger usable
    share, more throughput or IOPS, a larger share of survived combinations of failed disks (e.g. "2 of 2" ties with
    "4 of 4", and "4 of 6" beats "9 of 15").

    @param config: the configuration
    @param result: its metrics
    @return: the rows, from the disks to the failure counts
    """
    # the disks, then what the array costs and how fast it is, one row each:
    slow: int = config.kinds.count("slow")
    rows: list[NumberRow] = [
        NumberRow(
            "disks", f"{config.disks} ({slow} slow, {config.disks - slow} fast)", None
        ),
        NumberRow(
            "storage blow-up",
            f"{result.storage_blow_up:.2f} ×",
            -result.storage_blow_up,
        ),
        NumberRow(
            "usable share of the raw capacity",
            f"{result.usable_share:.0%}",
            result.usable_share,
        ),
        NumberRow(
            "sequential read (MB/s)",
            f"{result.sequential_read:,}",
            result.sequential_read,
        ),
        NumberRow(
            "sequential write (MB/s)",
            f"{result.sequential_write:,}",
            result.sequential_write,
        ),
        NumberRow("random read (IOPS)", f"{result.read_IOPS:,}", result.read_IOPS),
        NumberRow("random write (IOPS)", f"{result.write_IOPS:,}", result.write_IOPS),
    ]
    # one row per number of failed disks:
    rows += [
        NumberRow(
            f"survives {failed} failed disk{'s' if failed > 1 else ''}",
            count_text(count),
            None if count is None else count.survived / count.total,
        )
        for failed, count in zip(FAILED_DISK_COUNTS, result.failure_counts)
    ]
    return rows


def better(
    first: list[NumberRow], second: list[NumberRow]
) -> tuple[set[int], set[int]]:
    """Returns the rows in which each of two configurations has the better value.

    @param first: the rows of the first configuration
    @param second: the rows of the second one, with the same labels
    @return: the positions of the rows where the first is better, and those where the second is; a row in which a
        value has no score, or both have the same score or show the same text, is in neither
    """
    first_better: set[int] = set()
    second_better: set[int] = set()
    for index, (mine, theirs) in enumerate(zip(first, second)):
        # values that look the same are a tie, even where rounding hides a tiny difference of their scores (1.80 ×
        # against 1.80 ×):
        if mine.score is None or theirs.score is None or mine.text == theirs.text:
            continue
        if mine.score > theirs.score:
            first_better.add(index)
        elif theirs.score > mine.score:
            second_better.add(index)
    return first_better, second_better


def numbers_html(rows: list[NumberRow], bold: Set[int]) -> str:
    """Shows the numbers of a configuration as a table with one row per number.

    @param rows: the rows, see :func:`number_rows`
    @param bold: the positions of the rows whose value is shown in bold
    @return: the HTML
    """
    body: str = "".join(
        f"<tr><th>{html.escape(row.label)}</th>"
        + (
            f"<td><b>{html.escape(row.text)}</b></td>"
            if index in bold
            else f"<td>{html.escape(row.text)}</td>"
        )
        + "</tr>"
        for index, row in enumerate(rows)
    )
    return (
        "<b>Numbers</b> (performance with all disks working)"
        f'<table class="raid-numbers">{body}</table>'
    )


def close_tree(widget: widgets.DOMWidget) -> None:
    """Closes a widget, its children and the layout and style widgets of each, so that they do not stay open in the
    kernel and the browser.

    @param widget: the widget
    """
    child: widgets.DOMWidget
    for child in getattr(widget, "children", ()):
        close_tree(child)
    widget.layout.close()
    style: widgets.Widget | None = getattr(widget, "style", None)
    if style is not None:
        style.close()
    widget.close()


class Panel:  # pylint: disable=too-many-instance-attributes
    """One configuration of the playground: its controls, its disks with their blocks, its verdict and its numbers."""

    def __init__(self, name: str, preset: str, playground: RaidPlayground) -> None:
        """Builds the controls and the disks of a preset.

        @param name: the panel's name, e.g. ``A``
        @param preset: the name of the preset to start with, a key of :data:`PRESETS`
        @param playground: the playground, whose click mode and device types the panel uses
        """
        self.name: str = name
        self.playground: RaidPlayground = playground
        # set while the panel sets its own controls, whose observers would otherwise react:
        self.refreshing: bool = False
        # the panel's title, filled in by show():
        self.header = widgets.HTML()
        # the controls of the structure:
        full_label: dict[str, str] = {"description_width": "initial"}
        self.preset = widgets.Dropdown(
            options=[*PRESETS, OWN], value=preset, description="preset"
        )
        self.outer_level = widgets.Dropdown(
            options=[(f"RAID {level}", level) for level in LEVELS],
            description="outer level",
            style=full_label,
        )
        self.outer_members = widgets.IntSlider(
            min=2,
            max=MAX_MEMBERS,
            description="members",
            continuous_update=False,
            style=full_label,
        )
        self.inner_level = widgets.Dropdown(
            options=[("none", NO_INNER)]
            + [(f"RAID {level}", level) for level in LEVELS],
            description="inner level",
            style=full_label,
        )
        self.inner_members = widgets.IntSlider(
            min=2,
            max=MAX_MEMBERS,
            description="members per inner array",
            continuous_update=False,
            style=full_label,
        )
        # the disks, one box per inner array (one for a single-level array) with a column per disk:
        self.disks = widgets.HBox(layout=widgets.Layout(flex_flow="row wrap"))
        # the disk buttons and the tables of their blocks by slot, for clicking and reading them in tests:
        self.disk_buttons: list[widgets.Button] = []
        self.block_columns: list[widgets.HTML] = []
        self.verdict = widgets.HTML()
        # the automatic top margin pushes the numbers to the bottom of the panel; as A and B are as tall as the
        # taller of them, their rows of numbers stand at the same height:
        self.numbers = widgets.HTML(layout=widgets.Layout(margin="auto 0 0 0"))
        # the structure the disks were built for, and the marks of the disks by slot:
        self.structure: Structure = PRESETS[preset]
        self.kinds: list[DeviceKind] = []
        self.failed: set[int] = set()
        # the observers of the controls:
        self.preset.observe(lambda _: self.apply_preset(), names="value")
        for control in (
            self.outer_level,
            self.outer_members,
            self.inner_level,
            self.inner_members,
        ):
            control.observe(lambda _: self.structure_changed(), names="value")
        self.widget = widgets.VBox(
            [
                self.header,
                self.preset,
                widgets.HBox([self.outer_level, self.outer_members]),
                widgets.HBox([self.inner_level, self.inner_members]),
                self.disks,
                self.verdict,
                self.numbers,
            ],
            layout=widgets.Layout(width="50%"),
        ).add_class("raid-box")
        # set the controls to the preset without reacting to them, then build the disks:
        self.refreshing = True
        try:
            self.set_controls(self.structure)
        finally:
            self.refreshing = False
        self.rebuild(clear=True)

    @property
    def config(self) -> Configuration:
        """The panel's configuration with the kinds of its disks."""
        return configuration(self.structure, tuple(self.kinds))

    def chosen_inner_level(self) -> Level | None:
        """Returns the inner level the dropdown shows.

        @return: the level, None for a single-level array
        """
        value: int = cast(int, self.inner_level.value)
        return None if value == NO_INNER else cast(Level, value)

    def read_structure(self) -> Structure:
        """Returns the structure the controls show.

        @return: the levels and member counts; without an inner level, 1 member per inner array
        """
        inner: Level | None = self.chosen_inner_level()
        return Structure(
            cast(Level, self.outer_level.value),
            self.outer_members.value,
            inner,
            1 if inner is None else self.inner_members.value,
        )

    def set_controls(self, structure: Structure) -> None:
        """Sets the level dropdowns and the member sliders to a structure; the caller sets :attr:`refreshing`.

        @param structure: the structure to show
        """
        self.outer_level.value = structure.outer_level
        self.inner_level.value = (
            NO_INNER if structure.inner_level is None else structure.inner_level
        )
        # the sliders' lower ends first, so that they accept the member counts:
        self.adjust_sliders()
        self.outer_members.value = structure.outer_members
        if structure.inner_level is not None:
            self.inner_members.value = structure.inner_members

    def adjust_sliders(self) -> None:
        """Lets each member slider start at the fewest members of its level, which raises a smaller value to it, and
        disables the inner slider of a single-level array."""
        outer: Level = cast(Level, self.outer_level.value)
        self.outer_members.min = MIN_MEMBERS[outer]
        inner: Level | None = self.chosen_inner_level()
        self.inner_members.disabled = inner is None
        if inner is not None:
            self.inner_members.min = MIN_MEMBERS[inner]

    def apply_preset(self) -> None:
        """Sets the controls to the chosen preset and rebuilds the disks; choosing ``own`` changes nothing."""
        if self.refreshing or self.preset.value == OWN:
            return
        self.refreshing = True
        try:
            self.set_controls(PRESETS[cast(str, self.preset.value)])
        finally:
            self.refreshing = False
        self.rebuild()

    def structure_changed(self) -> None:
        """Reacts to a change of a level or a member count: adjusts the sliders, switches the preset to ``own`` and
        rebuilds the disks."""
        if self.refreshing:
            return
        self.refreshing = True
        try:
            self.adjust_sliders()
            self.preset.value = OWN
        finally:
            self.refreshing = False
        self.rebuild()

    def rebuild(self, clear: bool = False) -> None:
        """Builds the disk columns for the structure the controls show and shows the panel.

        The marks of the disks are kept if the member counts stayed the same, and cleared if one changed, also
        where a level change raised a member count or added or removed the inner level.

        @param clear: True to clear the marks in any case
        """
        # keep or clear the marks:
        old: Structure = self.structure
        self.structure = self.read_structure()
        if clear or (old.outer_members, old.inner_members) != (
            self.structure.outer_members,
            self.structure.inner_members,
        ):
            self.kinds = [DEFAULT_KIND] * (
                self.structure.outer_members * self.structure.inner_members
            )
            self.failed = set()
        # one box per inner array (one box with all disks for a single-level array), with a column per disk: its
        # button above the table of its blocks, all columns as wide as the longest block needs:
        group_size: int = (
            len(self.kinds)
            if self.structure.inner_level is None
            else self.structure.inner_members
        )
        width: str = f"{column_width(self.config)}px"
        self.disk_buttons = []
        self.block_columns = []
        groups: list[widgets.DOMWidget] = []
        for start in range(0, len(self.kinds), group_size):
            columns: list[widgets.DOMWidget] = []
            for slot in range(start, start + group_size):
                button = widgets.Button(layout=widgets.Layout(width=width))
                # the default argument binds the slot of this button now; without it, the lambda would look the
                # variable up at the click and find the last slot of the loop:
                button.on_click(lambda _, clicked=slot: self.click(clicked))
                blocks = widgets.HTML(layout=widgets.Layout(width=width))
                self.disk_buttons.append(button)
                self.block_columns.append(blocks)
                columns.append(widgets.VBox([button, blocks]))
            title: str = (
                f"RAID {self.structure.inner_level} #{start // group_size + 1}"
                if self.structure.inner_level is not None
                else f"RAID {self.structure.outer_level}"
            )
            groups.append(
                widgets.VBox(
                    [widgets.HTML(f"<small>{title}</small>"), widgets.HBox(columns)]
                ).add_class("raid-group")
            )
        # show the new boxes, then close the old ones with all their widgets: a widget that is no longer shown stays
        # open in the kernel and the browser until it is closed:
        old_groups: tuple[widgets.DOMWidget, ...] = self.disks.children
        self.disks.children = groups
        for group in old_groups:
            close_tree(group)
        self.show()

    def click(self, slot: int) -> None:
        """Marks a disk as the click mode says: toggles failed, or makes it slow or fast.

        @param slot: the disk's slot
        """
        mode: ClickMode = cast(ClickMode, self.playground.click_mode.value)
        if mode == "failed":
            self.failed ^= {slot}
        else:
            self.kinds[slot] = mode
        self.show()

    def show(self) -> None:
        """Shows the header, the marks of the disks, their blocks and the verdict, and updates the numbers."""
        config: Configuration = self.config
        self.header.value = (
            f"<b>{html.escape(self.name)}: {config.name}</b> ({describe(config)})"
        )
        # every disk's button shows its name, its kind and whether it failed, on the colour of its kind or red:
        for slot, button in enumerate(self.disk_buttons):
            failed: bool = slot in self.failed
            button.description = f"{disk_name(slot)} {self.kinds[slot]}" + (
                " failed" if failed else ""
            )
            button.style.button_color = DISK_COLOURS[
                "failed" if failed else self.kinds[slot]
            ]
        # the blocks below every disk:
        for blocks, cells in zip(self.block_columns, disk_blocks(config, self.failed)):
            blocks.value = blocks_html(cells)
        # the verdict, with the note where every block can still be read on its own; where all data can be read, so
        # can every block, which therefore needs no check of its own:
        readable: bool = all_data_readable(config, self.failed)
        self.verdict.value = verdict_html(
            readable,
            readable or all_blocks_readable(config, self.failed),
            self.failed,
        )
        self.playground.compare()


class RaidPlayground:  # pylint: disable=too-few-public-methods
    """The playground's widgets: the click mode, the switch for B, the legend, the panels A and B side by side and
    the device types; :attr:`widget` is what the notebook shows."""

    def __init__(self) -> None:
        """Builds the widgets with A = RAID 0+1 and B = RAID 1+0."""
        self.click_mode = widgets.ToggleButtons(
            options=list(CLICK_MODES), value="failed", description="click marks"
        )
        self.compare_b = widgets.Checkbox(value=True, description="compare with B")
        # the four values of each device type, by kind and field:
        self.device_inputs: dict[tuple[DeviceKind, str], widgets.BoundedIntText] = {
            (kind, field): widgets.BoundedIntText(
                value=getattr(DEFAULT_DEVICE_TYPES[kind], field),
                min=1,
                max=10**7,
                layout=widgets.Layout(width="150px"),
            )
            for kind in DEVICE_KINDS
            for field, _ in DEVICE_FIELDS
        }
        # the panels call compare() while they are built, before both exist:
        self.panels: list[Panel] = []
        self.panels = [
            Panel("A", "RAID 0+1", self),
            Panel("B", "RAID 1+0", self),
        ]
        # the observers of the device types and of the switch for B:
        for text in self.device_inputs.values():
            text.observe(lambda _: self.compare(), names="value")
        self.compare_b.observe(lambda _: self.show_b(), names="value")
        # the device types as a table: a header row, then a row per kind:
        device_grid = widgets.GridBox(
            [widgets.Label("")]
            + [widgets.Label(label) for _, label in DEVICE_FIELDS]
            + [
                child
                for kind in DEVICE_KINDS
                for child in [widgets.Label(kind)]
                + [self.device_inputs[(kind, field)] for field, _ in DEVICE_FIELDS]
            ],
            layout=widgets.Layout(grid_template_columns="60px repeat(4, 170px)"),
        )
        self.widget = widgets.VBox(
            [
                widgets.HTML(BOX_STYLE),
                widgets.HBox([self.click_mode, self.compare_b]),
                widgets.HTML(LEGEND),
                widgets.HBox([panel.widget for panel in self.panels]),
                widgets.VBox(
                    [widgets.HTML("<b>Device types</b>"), device_grid]
                ).add_class("raid-box"),
            ]
        )
        self.compare()

    def device_types(self) -> dict[DeviceKind, DeviceType]:
        """Returns the device types as the inputs show them.

        @return: the performance values by kind
        """
        return {
            kind: DeviceType(
                **{
                    field: self.device_inputs[(kind, field)].value
                    for field, _ in DEVICE_FIELDS
                }
            )
            for kind in DEVICE_KINDS
        }

    def show_b(self) -> None:
        """Shows or hides B as the switch says; without B, A takes the full width and no value is in bold."""
        a, b = self.panels
        b.widget.layout.display = None if self.compare_b.value else "none"
        a.widget.layout.width = "50%" if self.compare_b.value else "100%"
        self.compare()

    def compare(self) -> None:
        """Shows the numbers below every panel, while B is shown with the better value of each row in bold; does
        nothing until both panels exist."""
        if len(self.panels) < 2:
            return
        device_types: dict[DeviceKind, DeviceType] = self.device_types()
        rows: list[list[NumberRow]] = [
            number_rows(panel.config, metrics(panel.config, device_types))
            for panel in self.panels
        ]
        bold: tuple[set[int], set[int]] = (
            better(rows[0], rows[1]) if self.compare_b.value else (set(), set())
        )
        for panel, panel_rows, panel_bold in zip(self.panels, rows, bold):
            panel.numbers.value = numbers_html(panel_rows, panel_bold)
