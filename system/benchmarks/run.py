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

"""Runs the store benchmarks in Python and Rust, checks that both did the same work, and writes the results.

Run as ``python -m system.benchmarks.run`` (about three minutes; ``--quick`` for a short trial). Each benchmark
runs in its own process per language: :mod:`system.benchmarks.workloads` and
generated/rust/examples/benchmarks/workloads.rs.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from system.benchmarks.workloads import READS, TRANSACTIONS, Fingerprint

# the repository root (this file is system/benchmarks/run.py):
ROOT: Path = Path(__file__).resolve().parents[2]
# the Rust port, where cargo runs:
RUST_FOLDER: Path = ROOT / "generated" / "rust"
# where cargo builds the Rust benchmark program; given explicitly, so a CARGO_TARGET_DIR of the environment cannot
# make the runner measure an old build:
RUST_TARGET: Path = RUST_FOLDER / "target"
# the Rust benchmark program, built by `build_rust`:
RUST_BENCHMARK: Path = RUST_TARGET / "release" / "examples" / "workloads"
# where the results go:
RESULTS: Path = ROOT / "benchmarks" / "results.json"

# runs a command (a list of arguments, no shell) in a directory and returns its standard output:
CommandRunner = Callable[[list[str], Path], str]


def run_command(arguments: list[str], directory: Path) -> str:
    """Runs `arguments` as a command without a shell in `directory` and returns its standard output; its error
    output goes to the terminal. Raises subprocess.CalledProcessError if the command fails.
    """
    return subprocess.run(
        arguments, cwd=directory, stdout=subprocess.PIPE, text=True, check=True
    ).stdout


@dataclass(frozen=True)
class Config:
    """One benchmark to run."""

    # the workload's name, see workloads.WORKLOADS:
    workload: str
    # the validation method, 1 or 2:
    method: int
    # the store size:
    objects: int
    # reads or transactions per pass (for bulkload and get: the objects):
    operations: int


@dataclass(frozen=True)
class Measurement:
    """The repetitions of one benchmark in one language."""

    # "python" or "rust":
    language: str
    # the benchmark:
    config: Config
    # seconds per operation of each repetition:
    seconds_per_operation: list[float]
    # passes of each repetition:
    passes: list[int]
    # the fingerprint of a pass, the same in every repetition:
    fingerprint: Fingerprint

    # the median, minimum and maximum below are for the HTML report (next merge request) and the tests:

    @property
    def median(self) -> float:
        """The median seconds per operation."""
        return statistics.median(self.seconds_per_operation)

    @property
    def minimum(self) -> float:
        """The smallest seconds per operation."""
        return min(self.seconds_per_operation)

    @property
    def maximum(self) -> float:
        """The largest seconds per operation."""
        return max(self.seconds_per_operation)


# the micro-benchmarks run with validation method 2 for each of these store sizes:
MICRO_WORKLOADS: tuple[str, ...] = ("bulkload", "get", "read", "update_commit")
MICRO_SIZES: tuple[int, ...] = (100, 1_000, 10_000)
# the transactions-per-second workloads run with both validation methods on a store of this size:
TPS_WORKLOADS: tuple[str, ...] = (
    "read_only",
    "read_write_disjoint",
    "read_write_contention",
)
TPS_SIZE: int = 1_000


def operations_per_pass(workload: str, objects: int) -> int:
    """Returns the reads or transactions per pass of a workload; bulkload and get work on every object."""
    if workload in ("bulkload", "get"):
        return objects
    if workload == "read":
        return READS
    return TRANSACTIONS


def configs(quick: bool) -> list[Config]:
    """Returns the benchmarks to run; `quick` keeps only the smallest store size of the micro-benchmarks."""
    sizes: tuple[int, ...] = MICRO_SIZES[:1] if quick else MICRO_SIZES
    micro: list[Config] = [
        Config(workload, 2, size, operations_per_pass(workload, size))
        for workload in MICRO_WORKLOADS
        for size in sizes
    ]
    tps: list[Config] = [
        Config(workload, method, TPS_SIZE, operations_per_pass(workload, TPS_SIZE))
        for workload in TPS_WORKLOADS
        for method in (1, 2)
    ]
    return micro + tps


# a CSV line holds the seconds per operation, the passes and the fingerprint fields:
FIELDS_PER_LINE: int = 2 + len(fields(Fingerprint))


# seconds in the forms both programs print, e.g. 0.000721, 1e-05 (Python) and 1e-5 (Rust); stricter than float(),
# which also reads " 1", "+1", "1_0", "nan" or "inf":
SECONDS: re.Pattern[str] = re.compile(r"[0-9]+(\.[0-9]+)?(e[-+]?[0-9]+)?")


def count(text: str) -> int:
    """Returns `text` as an integer; `text` must be ASCII digits only. Raises ValueError otherwise."""
    if not (text.isascii() and text.isdigit()):
        raise ValueError(f"{text!r} is not a count")
    return int(text)


def parse_output(
    language: str, config: Config, output: str, repetitions: int
) -> Measurement:
    """Parses the CSV lines a benchmark program printed (seconds per operation, passes, fingerprint fields).

    Raises ValueError if `repetitions` is less than 1 or the output does not have one line per repetition. Also
    raises ValueError if a line has the wrong number of fields, seconds not written as in `SECONDS` or not finite,
    no pass or a field that is not a count, or if the repetitions report different fingerprints.
    """
    seconds: list[float] = []
    passes: list[int] = []
    fingerprints: list[Fingerprint] = []
    if repetitions < 1:
        raise ValueError(f"{language} {config}: at least one repetition is needed")
    lines: list[str] = output.strip().splitlines()
    if len(lines) != repetitions:
        raise ValueError(
            f"{language} {config}: {len(lines)} lines instead of {repetitions} repetitions"
        )
    for line in lines:
        values: list[str] = line.split(",")
        if len(values) != FIELDS_PER_LINE:
            raise ValueError(
                f"{language} {config}: {len(values)} instead of {FIELDS_PER_LINE} fields in {line!r}"
            )
        if not SECONDS.fullmatch(values[0]) or not math.isfinite(float(values[0])):
            raise ValueError(f"{language} {config}: bad seconds in {line!r}")
        line_passes: int = count(values[1])
        if line_passes < 1:
            raise ValueError(f"{language} {config}: no pass in {line!r}")
        seconds.append(float(values[0]))
        passes.append(line_passes)
        fingerprints.append(Fingerprint(*(count(value) for value in values[2:])))
    if any(fp != fingerprints[0] for fp in fingerprints):
        raise ValueError(f"{language} {config}: repetitions did different work")
    return Measurement(language, config, seconds, passes, fingerprints[0])


def measure(
    config: Config, repetitions: int, runner: CommandRunner, rust_first: bool = False
) -> tuple[Measurement, Measurement]:
    """Runs one benchmark in Python and in Rust, each in its own process, and returns both measurements (Python's
    first). `rust_first` runs Rust first; `run` alternates it, so that neither language always runs on a machine the
    other has just warmed up.

    Raises ValueError if Python and Rust report different fingerprints, i.e. did different work.
    """
    arguments: list[str] = [
        config.workload,
        str(config.method),
        str(config.objects),
        str(config.operations),
        str(repetitions),
    ]
    commands: dict[str, list[str]] = {
        "python": [sys.executable, "-m", "system.benchmarks.workloads", *arguments],
        "rust": [str(RUST_BENCHMARK), *arguments],
    }
    outputs: dict[str, str] = {}
    for language in ("rust", "python") if rust_first else ("python", "rust"):
        outputs[language] = runner(commands[language], ROOT)
    python: Measurement = parse_output("python", config, outputs["python"], repetitions)
    rust: Measurement = parse_output("rust", config, outputs["rust"], repetitions)
    if python.fingerprint != rust.fingerprint:
        raise ValueError(
            f"{config}: Python and Rust did different work: {python.fingerprint} != {rust.fingerprint}"
        )
    return python, rust


def cpu_model(runner: CommandRunner) -> str:
    """Returns the CPU model, or the processor type if the model cannot be read."""
    try:
        if platform.system() == "Darwin":
            return runner(["sysctl", "-n", "machdep.cpu.brand_string"], ROOT).strip()
        with open("/proc/cpuinfo", encoding="utf-8") as cpuinfo:
            for line in cpuinfo:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    return platform.processor() or platform.machine()


def provenance(runner: CommandRunner) -> dict[str, object]:
    """Returns where and when the results were measured: machine (no host or user name), versions, git commit."""
    return {
        "date": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "cpu": cpu_model(runner),
        "machine": platform.machine(),
        "cores": os.cpu_count(),
        "os": platform.platform(terse=True),
        "python": platform.python_version(),
        "rustc": runner(["rustc", "--version"], RUST_FOLDER).strip(),
        "git_commit": runner(["git", "rev-parse", "HEAD"], ROOT).strip(),
        "git_dirty": runner(["git", "status", "--porcelain"], ROOT).strip() != "",
    }


def build_rust(runner: CommandRunner) -> None:
    """Builds the Rust benchmark program in release mode into `RUST_TARGET`."""
    runner(
        [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--example",
            "workloads",
            "--target-dir",
            str(RUST_TARGET),
        ],
        RUST_FOLDER,
    )


def run(quick: bool, repetitions: int, runner: CommandRunner) -> dict[str, object]:
    """Builds the Rust program, runs every benchmark in both languages and returns the results with provenance,
    which is recorded first, so that the results name the commit and working-tree state the run started from.
    """
    started_from: dict[str, object] = provenance(runner)
    build_rust(runner)
    measurements: list[dict[str, object]] = []
    all_configs: list[Config] = configs(quick)
    # the language that runs first alternates between the workloads and store sizes; both validation methods of a
    # workload and store size share it, so that it is not tied to the method:
    groups: list[tuple[str, int]] = list(
        dict.fromkeys((config.workload, config.objects) for config in all_configs)
    )
    for config in all_configs:
        print(f"measuring {config} ...", file=sys.stderr)
        group_index: int = groups.index((config.workload, config.objects))
        for measurement in measure(
            config, repetitions, runner, rust_first=group_index % 2 == 1
        ):
            measurements.append(asdict(measurement))
    return {
        "provenance": started_from,
        "repetitions": repetitions,
        "measurements": measurements,
    }


def main(arguments: list[str]) -> None:
    """Runs the benchmarks and writes the results to `benchmarks/results.json` (or `--output`)."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="python -m system.benchmarks.run",
        description="Runs the benchmarks of the MVCC store in Python and Rust.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="smallest store size of the micro-benchmarks and 3 repetitions (overrides --repetitions)",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=7,
        help="repetitions per benchmark and language, at least 1 (default 7)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS,
        help="where to write the results (default benchmarks/results.json)",
    )
    options: argparse.Namespace = parser.parse_args(arguments)
    if not options.quick and options.repetitions < 1:
        parser.error("--repetitions must be at least 1")
    repetitions: int = 3 if options.quick else options.repetitions
    results: dict[str, object] = run(options.quick, repetitions, run_command)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {options.output}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
