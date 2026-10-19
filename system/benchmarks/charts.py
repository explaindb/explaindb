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

"""Draws the charts of the benchmark report as SVG text, and formats the numbers they show.

The charts are plain SVG without scripts or external resources, meant to be inlined into an HTML page. Their
elements carry CSS classes (``python``, ``rust``, ``line``, ``range``, ``marker``, ``bar``, ``axis``, ``grid``,
``label``, ``heading``), so the page sets the colours for light and dark mode; presentation attributes give light
colours if the page's CSS is missing. Every drawn element also carries a ``data-testid`` naming its kind (e.g.
``marker-python``, ``grid``, ``y-tick``), by which the tests select it. The module formats every number itself, so the same data always gives the same text on every machine. Each SVG element
is written on a line of its own, so that a new measurement changes the page line by line.
"""

from __future__ import annotations

import html
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

# the two implementations that are compared:
Language = Literal["python", "rust"]

# a no-break space between a number and its unit, and a narrow no-break space between groups of three digits:
UNIT_SPACE: str = "\u00a0"
THOUSANDS_SEPARATOR: str = "\u202f"

# the time units, from the smallest, with the exponent of their power of ten:
TIME_UNITS: tuple[tuple[int, str], ...] = ((-9, "ns"), (-6, "µs"), (-3, "ms"), (0, "s"))

# the colours used if the page's CSS is missing (Okabe–Ito blue and vermilion, readable for colour-blind readers):
FALLBACK_COLOURS: dict[Language, str] = {"python": "#0072B2", "rust": "#D55E00"}
GRID_COLOUR: str = "#dddddd"
AXIS_COLOUR: str = "#888888"

# text size and a cautious width of one character, in SVG units; there is no font engine to measure text:
FONT_SIZE: float = 12.0
CHARACTER_WIDTH: float = 0.62 * FONT_SIZE
FONT_FAMILY: str = (
    "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)


def coordinate(value: float) -> str:
    """Returns an SVG coordinate rounded to 0.1, without a trailing ``.0`` and without ``-0``."""
    written: str = f"{value:.1f}"
    if written == "-0.0":
        return "0"
    return written[:-2] if written.endswith(".0") else written


def three_digits(value: float) -> str:
    """Returns a positive `value` below 1000 with three significant digits, e.g. ``1.00``, ``40.2``, ``286``."""
    decimals: int = max(0, 2 - math.floor(math.log10(value)))
    return f"{value:.{decimals}f}"


def format_seconds(seconds: float) -> str:
    """Returns a positive duration with three significant digits in ns, µs, ms or s, e.g. ``40.2 ns``.

    The unit is chosen after rounding, so 999.7 ns gives ``1.00 µs``, not ``1000 ns``.
    """
    for exponent, unit in TIME_UNITS:
        rounded: float = float(f"{seconds / 10.0**exponent:.3g}")
        if rounded < 1000 or unit == TIME_UNITS[-1][1]:
            return f"{three_digits(rounded)}{UNIT_SPACE}{unit}"
    raise AssertionError("unreachable: the last unit always returns")


def format_decade(exponent: int) -> str:
    """Returns the label of 10**`exponent` seconds, e.g. ``10 ns`` for -8, ``1 ms`` for -3, ``100 s`` for 2."""
    for unit_exponent, unit in TIME_UNITS:
        # each unit covers three powers of ten (1, 10 and 100 of it); seconds cover all larger ones:
        if exponent < unit_exponent + 3 or unit == TIME_UNITS[-1][1]:
            return f"{10 ** (exponent - unit_exponent)}{UNIT_SPACE}{unit}"
    raise AssertionError("unreachable: the last unit always returns")


def format_count(count: int) -> str:
    """Returns a whole number with a narrow no-break space between groups of three digits, e.g. ``47 158``."""
    return f"{count:,}".replace(",", THOUSANDS_SEPARATOR)


def format_factor(factor: float) -> str:
    """Returns a positive factor such as a speed-up with one decimal (``2.5×``), or as a whole number from 9.95 on
    (``76×``), where one decimal would show ``10.0×``.
    """
    return f"{factor:.0f}×" if factor >= 9.95 else f"{factor:.1f}×"


def decades(low: float, high: float) -> list[int]:
    """Returns the exponents of the powers of ten from the one at or below the positive `low` to the one at or
    above `high`; at least two, so that an axis always spans a power of ten.
    """
    first: int = math.floor(math.log10(low))
    last: int = max(math.ceil(math.log10(high)), first + 1)
    return list(range(first, last + 1))


def linear_ticks(maximum: float) -> list[float]:
    """Returns ticks from 0 in steps of 1, 2 or 5 times a power of ten, up to the first tick at or above the
    positive `maximum`; about five steps, at least two ticks.
    """
    raw_step: float = maximum / 5
    magnitude: float = 10.0 ** math.floor(math.log10(raw_step))
    step: float = next(
        m * magnitude for m in (1, 2, 5, 10) if m * magnitude >= raw_step
    )
    # a maximum that is a multiple of the step, but a little off in floating point, needs no further tick:
    steps: int = max(1, math.ceil(maximum / step - 1e-9))
    return [i * step for i in range(steps + 1)]


@dataclass(frozen=True)
class Labels:
    """The accessible texts of a chart: its title and a short description with its main numbers.

    The ids of the SVG start with `chart_id`, which must be unique on the page.
    """

    chart_id: str
    title: str
    description: str


def svg_open(labels: Labels, css_class: str, width: float, height: float) -> str:
    """Returns the opening ``<svg>`` tag of a chart with its title and description, which screen readers read."""
    chart_id: str = html.escape(labels.chart_id)
    return (
        f'<svg class="{html.escape(css_class)}" '
        f'viewBox="0 0 {coordinate(width)} {coordinate(height)}" role="img" '
        f'aria-labelledby="{chart_id}-title" aria-describedby="{chart_id}-desc" '
        f'font-family="{html.escape(FONT_FAMILY)}" font-size="{coordinate(FONT_SIZE)}">\n'
        f'<title id="{chart_id}-title">{html.escape(labels.title)}</title>\n'
        f'<desc id="{chart_id}-desc">{html.escape(labels.description)}</desc>'
    )


def text(
    x: float, y: float, content: str, anchor: str = "start", *, test_id: str
) -> str:
    """Returns a ``<text>`` element whose baseline is at `y`; `anchor` (start, middle or end) says which point of
    the text is at `x`, and `test_id` what kind of text it is, for the tests (``data-testid``). A text of the kind
    ``heading`` gets the CSS class ``heading``, every other text the class ``label``.
    """
    css_class: str = "heading" if test_id == "heading" else "label"
    return (
        f'<text class="{html.escape(css_class)}" data-testid="{html.escape(test_id)}" '
        f'x="{coordinate(x)}" y="{coordinate(y)}" '
        f'text-anchor="{html.escape(anchor)}">{html.escape(content)}</text>'
    )


def line(
    start: tuple[float, float],
    end: tuple[float, float],
    css_class: str,
    colour: str,
    *,
    test_id: str,
) -> str:
    """Returns a ``<line>`` element from the point `start` to `end`, with a fallback colour; `test_id` says what
    kind of line it is, for the tests (``data-testid``).
    """
    return (
        f'<line class="{html.escape(css_class)}" data-testid="{html.escape(test_id)}" '
        f'x1="{coordinate(start[0])}" y1="{coordinate(start[1])}" '
        f'x2="{coordinate(end[0])}" y2="{coordinate(end[1])}" stroke="{colour}"/>'
    )


def marker(language: Language, x: float, y: float) -> str:
    """Returns the marker of a point: a circle for Python, a square for Rust, so that colour is not the only cue."""
    colour: str = FALLBACK_COLOURS[language]
    if language == "python":
        return (
            f'<circle class="marker python" data-testid="marker-python" cx="{coordinate(x)}" cy="{coordinate(y)}" '
            f'r="4" fill="{colour}"/>'
        )
    return (
        f'<rect class="marker rust" data-testid="marker-rust" x="{coordinate(x - 3.5)}" y="{coordinate(y - 3.5)}" '
        f'width="7" height="7" fill="{colour}"/>'
    )


@dataclass(frozen=True)
class Point:
    """One point of a line chart: a typical value (the median) and the range of values at a position on the x
    axis.
    """

    x: float
    median: float
    minimum: float
    maximum: float


@dataclass(frozen=True)
class Series:
    """A line of a line chart; `language` selects colour and marker shape."""

    language: Language
    points: list[Point]


@dataclass(frozen=True)
class LogAxis:
    """A logarithmic axis from 10**`decades[0]` to 10**`decades[-1]`, with a label at each power of ten."""

    decades: list[int]
    # the label of 10**exponent:
    label: Callable[[int], str]
    # written below the x axis; the y axis has none:
    title: str = ""

    def position(self, value: float, start: float, length: float) -> float:
        """Returns where the positive `value` lies on an axis that starts at `start` and is `length` long."""
        span: int = self.decades[-1] - self.decades[0]
        return start + (math.log10(value) - self.decades[0]) / span * length


def series_elements(
    series: Series, x_of: Callable[[float], float], y_of: Callable[[float], float]
) -> list[str]:
    """Returns the line through the medians of `series`, and the range bar and marker of each point; `x_of` and
    `y_of` map values to SVG coordinates.
    """
    colour: str = FALLBACK_COLOURS[series.language]
    points: str = " ".join(
        f"{coordinate(x_of(p.x))},{coordinate(y_of(p.median))}" for p in series.points
    )
    parts: list[str] = [
        f'<polyline class="line {series.language}" data-testid="line-{series.language}" points="{points}" '
        f'fill="none" stroke="{colour}" stroke-width="2"/>'
    ]
    for p in series.points:
        x: float = x_of(p.x)
        parts.append(
            line(
                (x, y_of(p.minimum)),
                (x, y_of(p.maximum)),
                f"range {series.language}",
                colour,
                test_id=f"range-{series.language}",
            )
        )
        parts.append(marker(series.language, x, y_of(p.median)))
    return parts


# the layout of a line chart, in SVG units:
LINE_CHART_WIDTH: float = 260.0
LINE_CHART_HEIGHT: float = 230.0
LINE_CHART_LEFT: float = 56.0
LINE_CHART_RIGHT: float = 26.0
LINE_CHART_TOP: float = 30.0
LINE_CHART_BOTTOM: float = 40.0


def line_chart(
    labels: Labels, series: list[Series], x_axis: LogAxis, y_axis: LogAxis
) -> str:
    """Returns a log-log line chart with `labels.title` above the plot; each point has a marker and a bar from the
    minimum to the maximum of the repetitions.
    """
    width: float = LINE_CHART_WIDTH - LINE_CHART_LEFT - LINE_CHART_RIGHT
    height: float = LINE_CHART_HEIGHT - LINE_CHART_TOP - LINE_CHART_BOTTOM
    bottom: float = LINE_CHART_TOP + height

    def x_of(value: float) -> float:
        """Maps a value of the x axis to its SVG coordinate."""
        return x_axis.position(value, LINE_CHART_LEFT, width)

    def y_of(value: float) -> float:
        """Maps a value of the y axis to its SVG coordinate; SVG's y grows downwards."""
        return y_axis.position(value, bottom, -height)

    parts: list[str] = [
        svg_open(labels, "line-chart", LINE_CHART_WIDTH, LINE_CHART_HEIGHT)
    ]
    parts.append(
        text(
            LINE_CHART_LEFT,
            LINE_CHART_TOP - 12,
            labels.title,
            test_id="heading",
        )
    )
    for exponent in y_axis.decades:
        y: float = y_of(10.0**exponent)
        parts.append(
            line(
                (LINE_CHART_LEFT, y),
                (LINE_CHART_LEFT + width, y),
                "grid",
                GRID_COLOUR,
                test_id="grid",
            )
        )
        # 4 units below the line, the middle of a 12-unit text sits on it:
        parts.append(
            text(
                LINE_CHART_LEFT - 5,
                y + 4,
                y_axis.label(exponent),
                "end",
                test_id="y-tick",
            )
        )
    for exponent in x_axis.decades:
        x: float = x_of(10.0**exponent)
        parts.append(
            line((x, LINE_CHART_TOP), (x, bottom), "grid", GRID_COLOUR, test_id="grid")
        )
        parts.append(
            text(x, bottom + 16, x_axis.label(exponent), "middle", test_id="x-tick")
        )
    parts.append(
        text(
            LINE_CHART_LEFT + width / 2,
            LINE_CHART_HEIGHT - 6,
            x_axis.title,
            "middle",
            test_id="axis-title",
        )
    )
    for one_series in series:
        parts.extend(series_elements(one_series, x_of, y_of))
    parts.append("</svg>")
    return "\n".join(parts)


@dataclass(frozen=True)
class Bar:
    """One bar: `language` selects the colour, `label` is written after the bar's end."""

    language: Language
    value: float
    label: str


@dataclass(frozen=True)
class BarRow:
    """A row of one or more bars with a label to its left."""

    label: str
    bars: list[Bar]


@dataclass(frozen=True)
class BarGroup:
    """Rows under a common heading, e.g. the two validation methods of one workload."""

    heading: str
    rows: list[BarRow]


# the layout of a bar chart, in SVG units; narrow, so that its text stays readable on a phone:
BAR_CHART_WIDTH: float = 360.0
BAR_THICKNESS: float = 13.0
BAR_GAP: float = 3.0
ROW_GAP: float = 7.0
HEADING_HEIGHT: float = 20.0
BAR_CHART_RIGHT: float = 12.0
BAR_CHART_TOP: float = 8.0
BAR_CHART_BOTTOM: float = 40.0


@dataclass(frozen=True)
class BarLayout:
    """Where the bars of a chart go: the x of the bars' start, SVG units per unit of value, the vertical extent of
    each group's rows (grid lines are drawn only there, so that they do not cross the headings) and the bottom of
    the last row.
    """

    left: float
    scale: float
    spans: list[tuple[float, float]]
    bottom: float

    @property
    def height(self) -> float:
        """The height of the chart: the bars and, below them, the tick labels and the axis title."""
        return self.bottom + BAR_CHART_BOTTOM


def bars(
    groups: list[BarGroup], left: float, scale: float
) -> tuple[list[str], BarLayout]:
    """Returns the headings, row labels and bars of `groups` from the top of a chart down, and their layout."""
    parts: list[str] = []
    spans: list[tuple[float, float]] = []
    y: float = BAR_CHART_TOP
    for group in groups:
        y += HEADING_HEIGHT
        parts.append(text(0, y - 6, group.heading, test_id="heading"))
        top: float = y - 2
        for row in group.rows:
            row_height: float = len(row.bars) * (BAR_THICKNESS + BAR_GAP) - BAR_GAP
            parts.append(
                text(
                    left - 6,
                    y + row_height / 2 + 4,
                    row.label,
                    "end",
                    test_id="row-label",
                )
            )
            for item in row.bars:
                length: float = item.value * scale
                parts.append(
                    f'<rect class="bar {item.language}" data-testid="bar-{item.language}" '
                    f'x="{coordinate(left)}" y="{coordinate(y)}" '
                    f'width="{coordinate(length)}" height="{coordinate(BAR_THICKNESS)}" '
                    f'fill="{FALLBACK_COLOURS[item.language]}"/>'
                )
                parts.append(
                    text(
                        left + length + 4,
                        y + BAR_THICKNESS - 3,
                        item.label,
                        test_id="bar-label",
                    )
                )
                y += BAR_THICKNESS + BAR_GAP
            # the gap after a row replaces the gap after its last bar:
            y += ROW_GAP - BAR_GAP
        spans.append((top, y - ROW_GAP + 2))
    return parts, BarLayout(left, scale, spans, y)


def bar_chart(
    labels: Labels,
    groups: list[BarGroup],
    tick_label: Callable[[float], str],
    axis_title: str,
) -> str:
    """Returns a chart of horizontal bars on a linear axis from 0, for non-empty `groups` with positive values.

    The label column is as wide as the longest row label, and room for the longest bar label is kept to the right
    of the bars.
    """
    all_bars: list[Bar] = [
        item for group in groups for row in group.rows for item in row.bars
    ]
    ticks: list[float] = linear_ticks(max(item.value for item in all_bars))
    left: float = 8 + CHARACTER_WIDTH * max(
        len(row.label) for group in groups for row in group.rows
    )
    width: float = (
        BAR_CHART_WIDTH
        - left
        - BAR_CHART_RIGHT
        - max(len(item.label) for item in all_bars) * CHARACTER_WIDTH
    )
    # the scale reaches up to the last tick, which may lie beyond the longest bar:
    body, layout = bars(groups, left, width / ticks[-1])

    parts: list[str] = [svg_open(labels, "bar-chart", BAR_CHART_WIDTH, layout.height)]
    for tick in ticks:
        x: float = left + tick * layout.scale
        for top, bottom in layout.spans:
            parts.append(
                line((x, top), (x, bottom), "grid", GRID_COLOUR, test_id="grid")
            )
        parts.append(
            text(x, layout.bottom + 16, tick_label(tick), "middle", test_id="x-tick")
        )
    parts.extend(body)
    for top, bottom in layout.spans:
        parts.append(
            line((left, top), (left, bottom), "axis", AXIS_COLOUR, test_id="axis")
        )
    parts.append(
        text(
            left + width / 2,
            layout.height - 6,
            axis_title,
            "middle",
            test_id="axis-title",
        )
    )
    parts.append("</svg>")
    return "\n".join(parts)
