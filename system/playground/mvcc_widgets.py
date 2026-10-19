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

"""Widgets of the MVCC playground: build a schedule by clicking, load a scenario, run it operation by operation."""

from __future__ import annotations

import html
from typing import cast

import ipywidgets as widgets

from system.playground.mvcc_playground import (
    MODES,
    Checksum,
    Mode,
    RunState,
    Verdict,
    run_to,
)
from system.playground.mvcc_scenarios import SCENARIOS, Scenario, make_scenario
from system.playground.schedules import (
    DataOperation,
    Operation,
    Row,
    Schedule,
    ScheduledOperation,
    StoredObject,
    format_read_result,
)

# at most 4 transactions, so that the verdict tries at most 4! = 24 serial orders:
MAX_TRANSACTIONS: int = 4
# what a running transaction may do next:
RUNNING_OPERATIONS: tuple[str, ...] = (
    "read all",
    "read a==",
    "update",
    "delete",
    "commit",
    "abort",
)
KEYS: tuple[str, ...] = ("x", "y", "z")
# the labels of the modes' buttons, which name the isolation level (where there is one) and how each mode decides
# which transactions to abort:
MODE_LABELS: dict[Mode, str] = {
    "method 1": "serializable - method 1 (re-run reads, checksums)",
    "method 2": "serializable - method 2 (write sets)",
    "snapshot isolation": "snapshot isolation - first updater wins",
    "no validation": "no validation",
}
# the scenario to start from when building a schedule of one's own:
EMPTY: Scenario = make_scenario(
    "empty", "Build a schedule of your own.", {"x": Row(1, 0), "y": Row(0, 0)}, []
)
# the scenarios to choose from; the dropdown's value is the position in this tuple, or OWN for "own schedule":
CHOICES: tuple[Scenario, ...] = (EMPTY, *SCENARIOS)
OWN: int = -1
# The playground sets no text colour: its text keeps the colour of the theme, dark in a light theme and light in a
# dark one. Its backgrounds are translucent tints, which show light over a light page and dark over a dark one, so
# that the theme's text is readable on them in both, also where tints lie on each other (test_mvcc_widgets.PaletteTest
# checks the contrast).
# background colours: of a transaction's status, and of the verdict by its kind:
STATUS_COLOURS: dict[str, str] = {
    "not begun": "rgba(128,128,128,0.15)",
    "running": "rgba(255,193,7,0.3)",
    "committed": "rgba(76,175,80,0.35)",
    "aborted": "rgba(244,67,54,0.35)",
}
VERDICT_COLOURS: dict[str, str] = {
    "pending": STATUS_COLOURS["not begun"],
    "error": STATUS_COLOURS["aborted"],
    "nothing committed": STATUS_COLOURS["not begun"],
    "serializable": STATUS_COLOURS["committed"],
    "serializable in another order": "rgba(255,152,0,0.3)",
    "not serializable": STATUS_COLOURS["aborted"],
}
# background of an operation's button in the schedule grid, by what the operation did:
CELL_COLOURS: dict[str, str] = {
    # faint, and the operation is written in italics (see show_grid):
    "planned": "rgba(128,128,128,0.06)",
    "skipped": "rgba(128,128,128,0.45)",
    "error": "rgba(255,152,0,0.3)",
    "aborted": STATUS_COLOURS["aborted"],
    "committed": STATUS_COLOURS["committed"],
    "ran last": STATUS_COLOURS["running"],
    "ran": "rgba(33,150,243,0.25)",
    # the read that returns something else in the order of the serialization points (see Verdict.marked_position):
    "differs": "rgba(156,39,176,0.35)",
}
# one style for the boxes that set apart the editing controls, the store, the transactions and the verdict (a style
# element in an HTML widget applies to the whole page). The rows of the tables get no background from the theme: a
# theme's stripes for every other row or for the row under the mouse would hide the boxes' tints, so the rule for tr
# is more specific than those of PyCharm (table tr:nth-child(even)) and JupyterLab (.jp-RenderedHTMLCommon tbody
# tr:nth-child(odd) and tbody tr:hover); a row's own background (style attribute) still wins. Lines separate the cells
# of the tables; "div" makes the rule more specific than a theme's rule for td that removes borders:
BOX_STYLE: str = (
    "<style>.mvcc-box {border:1px solid rgba(128,128,128,0.5); background:rgba(128,128,128,0.08); padding:6px; "
    "margin:6px 0} "
    "div.mvcc-box table tr:nth-child(n), div.mvcc-box table tr:hover {background:transparent} "
    "div.mvcc-box table {border-collapse:collapse} "
    "div.mvcc-box th, div.mvcc-box td {border:1px solid rgba(128,128,128,0.5)}</style>"
)
# the header row and the column "time" of the schedule grid: grey (stronger than a planned operation, fainter than a
# skipped one, so that the three stand apart):
HEADER_STYLE: dict[str, str] = {"background": "rgba(128,128,128,0.25)"}
# the frame of the operation that ran last in the schedule grid, a grey that shows on light and dark pages:
FRAME: str = "2px solid #808080"
# a committed version in the store table, framed so that the versions of a key stand apart (a grey that shows on light
# and dark pages):
VERSION_BOX: str = (
    "border:1px solid #bbbbbb; padding:1px 4px; margin-right:4px; white-space:nowrap"
)


def next_operations(schedule: Schedule) -> dict[int, list[str]]:
    """Returns, for every transaction that may get an operation next, the operations it may get.

    A running transaction may get any data operation, commit or abort; the transaction with the lowest number that
    has not begun may only begin, as long as fewer than :data:`MAX_TRANSACTIONS` have begun. So a schedule built from
    these choices numbers its transactions T1, T2, ... without gaps, begins each one first and runs nothing after
    its commit or abort.

    @return: the operations (``begin`` or :data:`RUNNING_OPERATIONS`) by transaction index (0 is T1)
    """
    began: set[int] = set()
    ended: set[int] = set()
    for scheduled in schedule:
        if scheduled.operation == "begin":
            began.add(scheduled.transaction_index)
        elif scheduled.operation in ("commit", "abort"):
            ended.add(scheduled.transaction_index)
    choices: dict[int, list[str]] = {
        index: list(RUNNING_OPERATIONS) for index in sorted(began - ended)
    }
    if len(began) < MAX_TRANSACTIONS:
        # the lowest index that has not begun: usually index len(began), i.e. the next number; a scenario may begin
        # T2 before T1 (Fekete et al.), and with some of its operations removed T1 has not begun yet:
        choices[min(set(range(len(began) + 1)) - began)] = ["begin"]
    return choices


def make_operation(kind: str, key: str, a: int, b: int) -> Operation:
    """Returns the operation chosen in the dropdowns and number fields.

    ``key``, ``a`` and ``b`` are ignored where they do not apply.

    @param kind: ``begin`` or one of :data:`RUNNING_OPERATIONS`
    @return: the operation, e.g. ``DataOperation("update", "x", Row(1, 0))`` for ``update``
    """
    if kind in ("begin", "commit", "abort"):
        return cast(Operation, kind)
    if kind == "read all":
        return DataOperation("read")
    if kind == "read a==":
        return DataOperation("read", a_equals=a)
    if kind == "update":
        return DataOperation("update", key, Row(a, b))
    return DataOperation("delete", key)


def offer(dropdown: widgets.Dropdown, options: list[tuple[str, object]]) -> None:
    """Sets the options of ``dropdown``: it keeps its value if that is still offered, else shows the first option."""
    old: object = dropdown.value
    # setting the options moves ipywidgets' dropdown to the first option (or to none), so the old value is put back:
    dropdown.options = options
    values: list[object] = [value for _, value in options]
    dropdown.value = old if old in values else (values[0] if values else None)


def cell_colour(  # pylint: disable=too-many-return-statements
    text: str, position: int, operations_run: int
) -> str:
    """Returns the background of an operation's button in the schedule grid.

    The outcome is read from the line run_schedule writes into the schedule table's log, e.g. ``(read all:
    skipped)``, ``delete z: raised KeyError: 'z'``, ``update x ← (a=1, b=2): aborted`` or ``commit (ts 3)``.

    @param text: what the operation did (from the schedule table's log) or, if it has not run, the operation
    @param position: the operation's position in the schedule, from 0
    @param operations_run: how many operations have run
    @return: a value of :data:`CELL_COLOURS`
    """
    if position >= operations_run:
        return CELL_COLOURS["planned"]
    if text.startswith("("):
        # its transaction was aborted before:
        return CELL_COLOURS["skipped"]
    if ": raised " in text:
        # the store stopped the run with an error (the transaction is not aborted):
        return CELL_COLOURS["error"]
    if text.endswith(": aborted"):
        return CELL_COLOURS["aborted"]
    if text.startswith("commit ("):
        # a commit that succeeded (the frame still marks it if it ran last):
        return CELL_COLOURS["committed"]
    if position == operations_run - 1:
        return CELL_COLOURS["ran last"]
    return CELL_COLOURS["ran"]


def checksums_html(checksums: tuple[Checksum, ...], wrote: bool) -> str:
    """Shows validation method 1's checksums of a transaction's reads, shortened; on a red tint where a commit now fails.

    @param checksums: the transaction's checksums (see :class:`Checksum`)
    @param wrote: whether the transaction has written; the store does not validate a transaction that has not
    @return: one line per read, as HTML
    """
    lines: list[str] = []
    for checksum in checksums:
        # the first 8 hex digits are enough to see whether two checksums differ:
        text: str = f"{checksum.clause}: at read {checksum.at_read[:8]}"
        if checksum.now is not None:
            text += f" · now {checksum.now[:8]}"
        changed: bool = checksum.now is not None and checksum.now != checksum.at_read
        if changed and not wrote:
            text += " (wrote nothing: not validated)"
        lines.append(
            f'<span style="background:{STATUS_COLOURS["aborted"]}">{html.escape(text)}</span>'
            if changed and wrote
            else html.escape(text)
        )
    return "<br>".join(lines)


def state_html(run_state: RunState) -> str:
    """Shows the versions in the store, the transactions and the verdict as coloured HTML tables.

    @return: the store, the transactions and the verdict, each in a box, as HTML
    """
    # one row per key: the key, its committed versions oldest first, each in a box, and the version being written:
    store_rows: list[str] = []
    for obj in run_state.objects:
        versions: str = "".join(
            f'<span style="{VERSION_BOX}">{html.escape(str(version))}</span>'
            for version in obj.committed
        )
        work_in_progress: str = (
            f'<td style="background:{STATUS_COLOURS["running"]}">{html.escape(str(obj.work_in_progress))}</td>'
            if obj.work_in_progress
            else "<td></td>"
        )
        # an insert still in progress, or one whose transaction aborted, has no committed version:
        store_rows.append(
            f"<tr><td><b>{html.escape(obj.object_id)}</b></td><td>{versions or 'none'}</td>{work_in_progress}</tr>"
        )
    # validation method 1 checks checksums; the column appears once a transaction has read in that mode:
    with_checksums: bool = any(
        transaction.checksums for transaction in run_state.transactions
    )
    transaction_rows: list[str] = []
    for transaction in run_state.transactions:
        # only a running transaction has a snapshot to show:
        sees: str = (
            format_read_result(transaction.sees)
            if transaction.status == "running"
            else ""
        )
        cells: list[str] = [
            transaction.name,
            transaction.status,
            sees,
            ", ".join(transaction.read_clauses),
            ", ".join(transaction.write_set),
        ]
        checksums: str = (
            f"<td>{checksums_html(transaction.checksums, bool(transaction.write_set))}</td>"
            if with_checksums
            else ""
        )
        transaction_rows.append(
            f'<tr style="background:{STATUS_COLOURS[transaction.status]}">'
            + "".join(f"<td>{html.escape(cell)}</td>" for cell in cells)
            + f"{checksums}</tr>"
        )
    checksums_header: str = "<th>checksums (method 1)</th>" if with_checksums else ""
    return (
        '<div class="mvcc-box"><b>Store</b><table>'
        "<tr><th>key</th><th>committed versions (oldest first)</th><th>work in progress</th></tr>"
        + "".join(store_rows)
        + '</table></div><div class="mvcc-box"><b>Transactions</b><table>'
        "<tr><th>transaction</th><th>status</th><th>snapshot + own writes</th><th>read</th><th>wrote</th>"
        f"{checksums_header}</tr>"
        + "".join(transaction_rows)
        + "</table></div>"
        + verdict_html(run_state.verdict)
    )


def verdict_html(verdict: Verdict) -> str:
    """Shows the verdict in a box: its sentence on the background of its kind, then one line per serial order replayed.

    @return: the verdict as HTML
    """
    details: str = (
        '<ul style="margin:4px 0">'
        + "".join(f"<li>{html.escape(line)}</li>" for line in verdict.details)
        + "</ul>"
        if verdict.details
        else ""
    )
    return (
        f'<div class="mvcc-box"><b>Verdict</b>'
        f'<div style="background:{VERDICT_COLOURS[verdict.kind]}; padding:6px">'
        f"{html.escape(verdict.text)}{details}</div></div>"
    )


class MvccPlayground:  # pylint: disable=too-many-instance-attributes
    """The playground's widgets and the schedule they build; :attr:`widget` is what the notebook shows."""

    def __init__(self) -> None:
        """Builds the widgets and loads the empty scenario."""
        self.initial_state: tuple[StoredObject, ...] = EMPTY.initial_state
        self.schedule: list[ScheduledOperation] = []
        # how many operations of the schedule have run:
        self.position: int = 0
        # set while refresh() updates the widgets, whose observers would otherwise call it again:
        self.refreshing: bool = False
        # shows the descriptions in full instead of cutting them off:
        full_label: dict[str, str] = {"description_width": "initial"}
        self.scenario = widgets.Dropdown(
            options=[(s.name, index) for index, s in enumerate(CHOICES)]
            + [("own schedule", OWN)],
            description="scenario",
        )
        self.description = widgets.HTML()
        self.mode = widgets.ToggleButtons(
            options=[(MODE_LABELS[mode], mode) for mode in MODES],
            value="method 2",
            description="mode",
            style={"button_width": "auto"},
        )
        self.transaction = widgets.Dropdown(description="transaction", style=full_label)
        self.operation = widgets.Dropdown(description="operation", style=full_label)
        self.key = widgets.Dropdown(options=KEYS, description="key", style=full_label)
        self.a = widgets.IntText(
            value=1, description="a (update, read a==)", style=full_label
        )
        self.b = widgets.IntText(value=0, description="b (update)", style=full_label)
        self.add_button = widgets.Button(description="add")
        self.remove_button = widgets.Button(description="remove last")
        self.back_button = widgets.Button(description="◀ back")
        self.forward_button = widgets.Button(description="forward ▶")
        # the schedule: a header row, then one row per operation with a button in the column of its transaction:
        self.grid = widgets.GridBox()
        # the buttons of the operations in schedule order, for clicking them in tests:
        self.cells: list[widgets.Button] = []
        self.state = widgets.HTML()
        # choosing a scenario loads it; a different transaction offers other operations; the mode changes the run
        # (the other inputs are only read when "add" is clicked):
        self.scenario.observe(lambda _: self.load_scenario(), names="value")
        self.transaction.observe(lambda _: self.refresh(), names="value")
        self.mode.observe(lambda _: self.refresh(), names="value")
        self.add_button.on_click(lambda _: self.add_operation())
        self.remove_button.on_click(lambda _: self.remove_last())
        self.back_button.on_click(lambda _: self.run_up_to(self.position - 1))
        self.forward_button.on_click(lambda _: self.run_up_to(self.position + 1))
        self.widget = widgets.VBox(
            [
                self.scenario,
                self.description,
                # the modes on a row of their own, as four buttons next to the scenario dropdown get too wide:
                self.mode,
                # the controls that edit the schedule, in a box apart from the schedule (the style is for all boxes):
                widgets.VBox(
                    [
                        widgets.HTML(f"<b>Edit schedule</b>{BOX_STYLE}"),
                        widgets.HBox([self.transaction, self.operation, self.key]),
                        widgets.HBox(
                            [self.a, self.b, self.add_button, self.remove_button]
                        ),
                    ]
                ).add_class("mvcc-box"),
                self.grid,
                widgets.HBox([self.back_button, self.forward_button]),
                self.state,
            ]
        )
        self.load_scenario()

    def load_scenario(self) -> None:
        """Replaces the schedule and the initial objects by those of the chosen scenario, before its first operation."""
        # the dropdown switches to "own schedule" after an edit; choosing that loads nothing:
        if self.scenario.value == OWN:
            self.description.value = ""
            return
        scenario: Scenario = CHOICES[self.scenario.value]
        self.initial_state = scenario.initial_state
        self.schedule = list(scenario.schedule)
        self.description.value = html.escape(scenario.description)
        self.position = 0
        self.refresh()

    def add_operation(self) -> None:
        """Appends the chosen operation and runs the schedule up to it."""
        # a second click may arrive before the browser has disabled the button, when nothing is offered any more:
        if self.transaction.value is None or self.operation.value is None:
            return
        self.schedule.append(
            ScheduledOperation(
                self.transaction.value,
                make_operation(
                    self.operation.value, self.key.value, self.a.value, self.b.value
                ),
            )
        )
        self.position = len(self.schedule)
        self.refresh(edited=True)

    def remove_last(self) -> None:
        """Removes the last operation; what remains is still a schedule built from valid choices."""
        # a second click may arrive before the browser has disabled the button on an empty schedule:
        if not self.schedule:
            return
        self.schedule.pop()
        self.refresh(edited=True)

    def run_up_to(self, position: int) -> None:
        """Runs the first ``position`` operations, i.e. up to and including the operation at ``position - 1``."""
        self.position = position
        self.refresh()

    def refresh(self, edited: bool = False) -> None:
        """Updates the choices, the buttons, the schedule grid and the state after any change.

        @param edited: True if the schedule was changed by hand, so that it no longer is the chosen scenario
        """
        if self.refreshing:
            return
        self.refreshing = True
        try:
            # an edited schedule is no longer the chosen scenario (setting the dropdown to "own schedule" clears the
            # description, see load_scenario):
            if edited:
                self.scenario.value = OWN
            choices: dict[int, list[str]] = next_operations(self.schedule)
            # a transaction that may only begin does not exist yet:
            offer(
                self.transaction,
                [
                    (
                        f"T{index + 1}"
                        + (" (new)" if choices[index] == ["begin"] else ""),
                        index,
                    )
                    for index in sorted(choices)
                ],
            )
            offer(
                self.operation,
                [(kind, kind) for kind in choices.get(self.transaction.value, [])],
            )
            self.add_button.disabled = not choices
            self.remove_button.disabled = not self.schedule
            # removing an operation may leave the position after the end of the schedule, and a late click on back
            # (before the browser disables it) before its start:
            self.position = max(0, min(self.position, len(self.schedule)))
            schedule: Schedule = tuple(self.schedule)
            run_state: RunState = run_to(
                schedule, self.initial_state, self.mode.value, self.position
            )
            # an error stops the run: going further would show the same, so the position stays at the error:
            if run_state.verdict.kind == "error":
                self.position = len(run_state.log)
            self.back_button.disabled = self.position == 0
            self.forward_button.disabled = (
                self.position == len(self.schedule) or run_state.verdict.kind == "error"
            )
            self.show_grid(run_state, schedule)
            self.state.value = state_html(run_state)
        finally:
            self.refreshing = False

    def show_grid(self, run_state: RunState, schedule: Schedule) -> None:
        """Fills the schedule grid: a button per operation, coloured by whether and how it ran, and, if something went
        wrong, a column "why" that explains it in the operation's row."""
        # the column "why" appears only if there is something to explain:
        why: bool = bool(run_state.explanations)
        # the header row, then one row per operation; time points down, the column "time" numbers the operations:
        children: list[widgets.Widget] = [
            widgets.Label(text, style=HEADER_STYLE)
            for text in ["time"]
            + [transaction.name for transaction in run_state.transactions]
            + (["why"] if why else [])
        ]
        self.cells = []
        for position, scheduled in enumerate(schedule):
            # what the operation did if it ran (the log has a line per operation run), else the operation itself:
            text: str = (
                run_state.log[position].text
                if position < len(run_state.log)
                else str(scheduled.operation)
            )
            background: str = cell_colour(text, position, len(run_state.log))
            # the read that differs in the order of the serialization points (the column "why" says what it would
            # return there):
            if position == run_state.verdict.marked_position:
                background = CELL_COLOURS["differs"]
            cell = widgets.Button(
                description=text,
                tooltip=text,
                # a frame marks the operation that ran last, whatever its colour:
                layout=widgets.Layout(
                    width="auto",
                    border=(FRAME if position == len(run_state.log) - 1 else "none"),
                ),
                style={
                    "button_color": background,
                    # the operations that have not run yet are in italics:
                    "font_style": (
                        "italic" if position >= len(run_state.log) else "normal"
                    ),
                },
            )
            # clicking an operation runs the schedule up to and including it:
            cell.on_click(lambda _, end=position + 1: self.run_up_to(end))
            self.cells.append(cell)
            # the row: the operation's number, then the button in the column of its transaction, empty elsewhere:
            children += [widgets.Label(str(position + 1), style=HEADER_STYLE)] + [
                cell if index == scheduled.transaction_index else widgets.Label("")
                for index in range(len(run_state.transactions))
            ]
            # the explanation in the column "why", wrapped instead of cut off like a label:
            if why:
                children.append(
                    widgets.HTML(
                        '<div style="white-space:normal; line-height:1.3">'
                        f"{html.escape(run_state.explanations.get(position, ''))}</div>"
                    )
                )
        # at least one column, as "repeat(0, ...)" is no valid CSS:
        self.grid.layout.grid_template_columns = (
            f"45px repeat({max(1, len(run_state.transactions))}, 300px)"
            + (" minmax(250px, 1fr)" if why else "")
        )
        old: tuple[widgets.Widget, ...] = self.grid.children
        self.grid.children = children
        # the widgets of the previous grid stay open in the kernel and the browser until they are closed, with the
        # layout and style widgets each one has:
        for widget in old:
            widget.layout.close()
            if hasattr(widget, "style"):
                widget.style.close()
            widget.close()
