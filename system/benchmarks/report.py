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

"""Writes the static HTML report of the store benchmarks from the results of a full run.

Run as ``python -m system.benchmarks.report`` after :mod:`system.benchmarks.run`; it reads
``benchmarks/results.json`` and writes ``benchmarks/index.html``, a single page without scripts or external
resources, from the template ``report_template.html`` next to this module.
"""

from __future__ import annotations

import argparse
import html
import json
import string
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

from system.benchmarks.charts import (
    Bar,
    BarGroup,
    BarRow,
    Labels,
    Language,
    LogAxis,
    Point,
    Series,
    bar_chart,
    decades,
    format_count,
    format_decade,
    format_factor,
    format_seconds,
    line_chart,
)
from system.benchmarks.run import (
    MICRO_WORKLOADS,
    REPORT,
    RESULTS,
    TPS_WORKLOADS,
    Config,
    Measurement,
    Provenance,
    configs,
)
from system.benchmarks.workloads import MIN_SECONDS, Fingerprint

# the languages in the order the page shows them, which is their order in `Language`:
LANGUAGES: tuple[Language, ...] = get_args(Language)
# every chart description ends with this sentence:
SEE_TABLE: str = "All numbers are in the table below."
# the range of plausible seconds per operation; outside it, a value is an error, and the log axes could not
# draw it:
SECONDS_RANGE: tuple[float, float] = (1e-12, 1e6)


@dataclass(frozen=True)
class Pair:
    """The Python and the Rust measurement of one benchmark."""

    python: Measurement
    rust: Measurement

    def of(self, language: Language) -> Measurement:
        """Returns the measurement of `language`."""
        return self.python if language == "python" else self.rust

    @property
    def speedup(self) -> float:
        """How many times as fast Rust is as Python: the Python median divided by the Rust median."""
        return self.python.median / self.rust.median


@dataclass(frozen=True)
class Results:
    """The results of a full run: the machine and commit, and both measurements of every benchmark."""

    provenance: Provenance
    repetitions: int
    # in the order of `configs(quick=False)`:
    pairs: dict[Config, Pair]


def per_second(measurement: Measurement) -> float:
    """Returns the operations per second of a measurement, from its median."""
    return 1 / measurement.median


def is_number(value: object) -> bool:
    """Returns whether a value read from JSON is a number; `True` and `False` are not."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_count(value: object, at_least: int = 0) -> bool:
    """Returns whether a value read from JSON is a whole number of at least `at_least`; `True` and `False` are
    not.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= at_least


def parse_measurement(entry: dict[str, Any], repetitions: int) -> Measurement:
    """Returns the measurement of one entry of the results file; `parse_results` checks that its benchmark
    belongs to a full run.

    Raises ValueError unless it is of a known language, its benchmark fields have the right types, and it has
    `repetitions` seconds in `SECONDS_RANGE` and as many pass counts of at least 1. A missing or unknown key raises
    KeyError or TypeError.
    """
    language: str = entry["language"]
    config: Config = Config(**entry["config"])
    seconds: list[Any] = list(entry["seconds_per_operation"])
    passes: list[Any] = list(entry["passes"])
    if language not in LANGUAGES:
        raise ValueError(f"{config}: unknown language {language!r}")
    if not isinstance(config.workload, str) or not all(
        is_count(v) for v in (config.method, config.objects, config.operations)
    ):
        raise ValueError(f"{language} {config}: a benchmark field of the wrong type")
    if len(seconds) != repetitions or len(passes) != repetitions:
        raise ValueError(f"{language} {config}: not {repetitions} repetitions")
    low, high = SECONDS_RANGE
    if not all(is_number(v) and low <= v <= high for v in seconds):
        raise ValueError(
            f"{language} {config}: seconds outside {low:g} to {high:g} (or not a number)"
        )
    if not all(is_count(v, 1) for v in passes):
        raise ValueError(
            f"{language} {config}: a pass count that is not a whole number of at least 1"
        )
    fingerprint: Fingerprint = Fingerprint(**entry["fingerprint"])
    if not all(is_count(v) for v in vars(fingerprint).values()):
        raise ValueError(
            f"{language} {config}: a fingerprint field that is not a whole number"
        )
    return Measurement(
        language, config, [float(v) for v in seconds], passes, fingerprint
    )


def parse_results(data: dict[str, Any]) -> Results:
    """Returns the results in `data`, read from a results file; see `load_results`."""
    repetitions: Any = data["repetitions"]
    if not is_count(repetitions, 1):
        raise ValueError(
            f"repetitions must be a whole number of at least 1, not {repetitions!r}"
        )
    found: dict[tuple[str, Config], Measurement] = {}
    for entry in data["measurements"]:
        measurement: Measurement = parse_measurement(entry, repetitions)
        key: tuple[str, Config] = (measurement.language, measurement.config)
        if key in found:
            raise ValueError(
                f"{measurement.language} {measurement.config}: measured twice"
            )
        found[key] = measurement
    expected: list[Config] = configs(quick=False)
    missing: list[str] = [
        f"{language} {config}"
        for config in expected
        for language in LANGUAGES
        if (language, config) not in found
    ]
    unexpected: list[str] = [
        f"{language} {config}" for language, config in found if config not in expected
    ]
    if missing or unexpected:
        raise ValueError(
            f"not the results of a full run; missing {missing}, unexpected {unexpected}"
        )
    pairs: dict[Config, Pair] = {}
    for config in expected:
        pair: Pair = Pair(found["python", config], found["rust", config])
        if pair.python.fingerprint != pair.rust.fingerprint:
            raise ValueError(f"{config}: Python and Rust did different work")
        pairs[config] = pair
    provenance: Provenance = Provenance(**data["provenance"])
    # every provenance field is text, except the number of cores and the flag for uncommitted changes:
    texts: list[object] = [
        v for k, v in vars(provenance).items() if k not in ("cores", "git_dirty")
    ]
    if not all(isinstance(v, str) for v in texts) or not isinstance(
        provenance.git_dirty, bool
    ):
        raise ValueError("a provenance field of the wrong type")
    if provenance.cores is not None and not is_count(provenance.cores, 1):
        raise ValueError(
            f"cores must be a whole number of at least 1 or null, not {provenance.cores!r}"
        )
    return Results(provenance, repetitions, pairs)


def load_results(path: Path) -> Results:
    """Reads the results of a full run from `path`.

    Raises ValueError, naming `path` and the problem, unless the file holds exactly the benchmarks of a full run,
    each measured once in Python and once in Rust with the same fingerprint and valid numbers (see
    `parse_measurement`), and the provenance of the run.
    """
    # OSError: the file cannot be read; KeyError and TypeError: missing or unknown keys:
    try:
        return parse_results(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError(
            f"{path}: not the results of a full run of the benchmarks: {error}"
        ) from error


def line_series(pairs: dict[Config, Pair], language: Language) -> Series:
    """Returns the line of `language` through the benchmarks of `pairs`, one point per store size."""
    points: list[Point] = []
    for config, pair in pairs.items():
        measurement: Measurement = pair.of(language)
        points.append(
            Point(
                config.objects,
                measurement.median,
                measurement.minimum,
                measurement.maximum,
            )
        )
    return Series(language, points)


def micro_charts(results: Results) -> str:
    """Returns the four line charts of the micro-benchmarks, which share one time axis, each in a panel."""
    micro: dict[Config, Pair] = {
        c: p for c, p in results.pairs.items() if c.workload in MICRO_WORKLOADS
    }
    measurements: list[Measurement] = [
        p.of(language) for p in micro.values() for language in LANGUAGES
    ]
    time_axis: LogAxis = LogAxis(
        decades(
            min(m.minimum for m in measurements), max(m.maximum for m in measurements)
        ),
        format_decade,
    )
    sizes: list[int] = sorted({c.objects for c in micro})
    size_axis: LogAxis = LogAxis(
        decades(sizes[0], sizes[-1]),
        lambda exponent: format_count(10**exponent),
        "objects in the store",
    )
    panels: list[str] = []
    for workload in MICRO_WORKLOADS:
        of_workload: dict[Config, Pair] = {
            c: p for c, p in micro.items() if c.workload == workload
        }
        series: list[Series] = [
            line_series(of_workload, language) for language in LANGUAGES
        ]
        largest, pair = max(of_workload.items(), key=lambda item: item[0].objects)
        description: str = (
            f"With {format_count(largest.objects)} objects: Python {format_seconds(pair.python.median)}, "
            f"Rust {format_seconds(pair.rust.median)} per operation. {SEE_TABLE}"
        )
        chart: str = line_chart(
            Labels(f"micro-{workload}", workload, description),
            series,
            size_axis,
            time_axis,
        )
        panels.append(f'<div class="panel">\n{chart}\n</div>')
    return "\n".join(panels)


def method_label(method: int) -> str:
    """Returns the row label of a validation method."""
    return f"method {method}"


def tps_bar(pair: Pair, language: Language) -> Bar:
    """Returns the bar of the transactions per second of `language` in `pair`, labelled with language and value."""
    value: float = per_second(pair.of(language))
    return Bar(language, value, f"{language.capitalize()} {format_count(round(value))}")


def tps_chart(results: Results) -> str:
    """Returns the bar chart of transactions per second, both languages per workload and validation method."""
    tps: dict[Config, Pair] = {
        c: p for c, p in results.pairs.items() if c.workload in TPS_WORKLOADS
    }
    groups: list[BarGroup] = []
    for workload in TPS_WORKLOADS:
        rows: list[BarRow] = [
            BarRow(
                method_label(c.method), [tps_bar(p, language) for language in LANGUAGES]
            )
            for c, p in tps.items()
            if c.workload == workload
        ]
        groups.append(BarGroup(workload, rows))
    most: dict[Language, int] = {
        language: round(max(per_second(p.of(language)) for p in tps.values()))
        for language in LANGUAGES
    }
    description: str = (
        f"Rust reaches up to {format_count(most['rust'])} transactions per second, Python up to "
        f"{format_count(most['python'])}. {SEE_TABLE}"
    )
    return bar_chart(
        Labels("tps", "Transactions per second", description),
        groups,
        lambda tick: format_count(round(tick)),
        "transactions per second",
    )


def speedup_chart(results: Results) -> str:
    """Returns the bar chart of the speed-up of Rust over Python for every benchmark."""
    groups: list[BarGroup] = []
    for workload in MICRO_WORKLOADS + TPS_WORKLOADS:
        rows: list[BarRow] = []
        for config, pair in results.pairs.items():
            if config.workload != workload:
                continue
            # the micro-benchmarks differ by store size, the transactions by validation method:
            label: str = (
                format_count(config.objects)
                if workload in MICRO_WORKLOADS
                else method_label(config.method)
            )
            rows.append(
                BarRow(label, [Bar("rust", pair.speedup, format_factor(pair.speedup))])
            )
        groups.append(BarGroup(workload, rows))
    speedups: list[float] = [p.speedup for p in results.pairs.values()]
    description: str = (
        f"Rust is between {format_factor(min(speedups))} and {format_factor(max(speedups))} as fast as Python. "
        f"{SEE_TABLE}"
    )
    return bar_chart(
        Labels("speedup", "Speed-up of Rust over Python", description),
        groups,
        lambda tick: f"{tick:g}×",
        "times as fast",
    )


def table_rows(results: Results) -> str:
    """Returns the rows of the table of all benchmarks: median and range of both languages, speed-up, and the
    commits and aborts of a pass.
    """
    rows: list[str] = []
    for config, pair in results.pairs.items():
        cells: list[str] = [
            config.workload,
            str(config.method),
            format_count(config.objects),
        ]
        for language in LANGUAGES:
            measurement: Measurement = pair.of(language)
            cells.append(format_seconds(measurement.median))
            cells.append(
                f"{format_seconds(measurement.minimum)} – {format_seconds(measurement.maximum)}"
            )
        cells.append(format_factor(pair.speedup))
        cells.append(format_count(pair.python.fingerprint.commits))
        cells.append(format_count(pair.python.fingerprint.aborts))
        rows.append(
            "<tr>"
            + "".join(f"<td>{html.escape(cell)}</td>" for cell in cells)
            + "</tr>"
        )
    return "\n".join(rows)


def provenance_items(provenance: Provenance) -> str:
    """Returns the machine, tool versions and commit of a run as the items of a description list."""
    items: list[tuple[str, str]] = [
        ("Date", provenance.date),
        ("CPU", provenance.cpu),
        ("Cores", "unknown" if provenance.cores is None else str(provenance.cores)),
        ("Architecture", provenance.machine),
        ("Operating system", provenance.os),
        ("Python", provenance.python),
        ("Rust", provenance.rustc),
        ("Commit", provenance.git_commit),
        ("Uncommitted changes", "yes" if provenance.git_dirty else "no"),
    ]
    return "\n".join(
        f"<dt>{html.escape(name)}</dt><dd>{html.escape(value)}</dd>"
        for name, value in items
    )


# the page with $placeholders; `substitute` raises KeyError for a placeholder without a value, and `$$` in the
# template writes a literal `$`:
PAGE: string.Template = string.Template(
    Path(__file__).with_name("report_template.html").read_text(encoding="utf-8")
)


def operations(results: Results, workload: str) -> int:
    """Returns the reads or transactions per pass of `workload`, the same for all its benchmarks in a full run."""
    return next(c.operations for c in results.pairs if c.workload == workload)


def store_sizes(results: Results, workloads: tuple[str, ...]) -> str:
    """Returns the store sizes of the benchmarks of `workloads` as text, e.g. ``100, 1 000 and 10 000``."""
    written: list[str] = [
        format_count(objects)
        for objects in sorted(
            {c.objects for c in results.pairs if c.workload in workloads}
        )
    ]
    return (
        written[0]
        if len(written) == 1
        else f"{', '.join(written[:-1])} and {written[-1]}"
    )


def render(results: Results) -> str:
    """Returns the HTML page of `results`. Every value is escaped where it enters markup, so the generated charts
    and table rows are inserted as they are. The numbers in the page's text come from the results and the benchmark
    settings, so that the text describes the run it shows.
    """
    speedups: list[float] = [p.speedup for p in results.pairs.values()]
    return PAGE.substitute(
        read_operations=format_count(operations(results, "read")),
        update_commit_operations=format_count(operations(results, "update_commit")),
        read_only_operations=format_count(operations(results, "read_only")),
        read_write_disjoint_operations=format_count(
            operations(results, "read_write_disjoint")
        ),
        # `operations` counts the transactions of a pass, two per pair:
        contention_pairs=format_count(
            operations(results, "read_write_contention") // 2
        ),
        micro_sizes=store_sizes(results, MICRO_WORKLOADS),
        tps_size=store_sizes(results, TPS_WORKLOADS),
        min_milliseconds=f"{MIN_SECONDS * 1000:g}",
        lowest_speedup=html.escape(format_factor(min(speedups))),
        highest_speedup=html.escape(format_factor(max(speedups))),
        repetitions=str(results.repetitions),
        micro_charts=micro_charts(results),
        tps_chart=tps_chart(results),
        speedup_chart=speedup_chart(results),
        table_rows=table_rows(results),
        provenance=provenance_items(results.provenance),
    )


def main(arguments: list[str]) -> None:
    """Writes the report from the results of a full run; exits with an error message if they are not."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="python -m system.benchmarks.report",
        description="Writes the HTML report of the store benchmarks.",
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=RESULTS,
        help="the results of a full run (default benchmarks/results.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPORT,
        help="where to write the page (default benchmarks/index.html)",
    )
    options: argparse.Namespace = parser.parse_args(arguments)
    try:
        results: Results = load_results(options.results)
    except ValueError as error:
        parser.error(str(error))
    # samefile also sees the same file under another letter case or a hard link:
    if options.output.exists() and options.output.samefile(options.results):
        parser.error("--output must not be the results file")
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(render(results), encoding="utf-8")
    print(f"wrote {options.output}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
