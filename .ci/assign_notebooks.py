#!/usr/bin/env python3
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

"""Assign notebooks to parallel CI jobs via LPT bin-packing (minimises makespan).

The notebook test job runs with GitLab's ``parallel`` keyword across several
instances. This script decides which notebooks each instance runs so that the
instances finish at roughly the same time -- instead of the round-robin-by-file-
size heuristic it replaces, which ignored actual run time.

It reads per-notebook run-time weights from ``notebook_weights.tsv`` (next to
this file), discovers the notebooks in the current working directory, and
greedily assigns them -- heaviest first -- to the least-loaded bin (Longest
Processing Time first). It prints the notebooks assigned to this instance
(``CI_NODE_INDEX``, 1-based), one per line, by bare file name. The CI job runs
this from the ``notebooks/`` directory (see ``.gitlab-ci.yml``, ``ipynb_test``)
so the printed names resolve directly.

Notebooks without a recorded weight get a default weight so newly added
notebooks still run and are spread sensibly rather than piling onto one bin.
Every notebook present is assigned to exactly one bin, so the union over all
instances always covers the full set.
"""

from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

# Weights file lives next to this script (found via its own path, so it resolves
# regardless of the working directory); notebooks are globbed from the current
# working directory, which the CI job sets to ``notebooks/``.
WEIGHTS_FILE: Path = Path(__file__).with_name("notebook_weights.tsv")

# Seconds assumed for a notebook missing from the weights file. Chosen around
# the middle of the observed range so an unrecorded notebook is neither ignored
# nor allowed to dominate a bin.
DEFAULT_WEIGHT: float = 5.0


def load_weights(path: Path) -> dict[str, float]:
    """Parse the tab-separated ``<seconds>\\t<notebook>`` weights file.

    Blank lines and lines starting with ``#`` are ignored. Returns a mapping
    from notebook file name to its recorded run time in seconds; an empty
    mapping if the file does not exist.
    """
    weights: dict[str, float] = {}
    if not path.exists():
        return weights
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped: str = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        seconds, _, name = stripped.partition("\t")
        weights[name.strip()] = float(seconds.strip())
    return weights


def assign(
    notebooks: list[str], weights: dict[str, float], num_bins: int
) -> list[list[str]]:
    """LPT-pack ``notebooks`` into ``num_bins`` bins minimising the maximum load.

    Notebooks are placed heaviest first; each goes to the currently least-loaded
    bin. Ties are broken deterministically (by notebook name, then bin index) so
    the assignment is stable across runs and instances.
    """
    bins: list[list[str]] = [[] for _ in range(num_bins)]
    loads: list[float] = [0.0] * num_bins
    ordered: list[str] = sorted(
        notebooks, key=lambda nb: (-weights.get(nb, DEFAULT_WEIGHT), nb)
    )
    for nb in ordered:
        target: int = min(range(num_bins), key=lambda b: (loads[b], b))
        bins[target].append(nb)
        loads[target] += weights.get(nb, DEFAULT_WEIGHT)
    return bins


def discover_notebooks() -> list[str]:
    """Return the sorted notebook file names in the current working directory.

    The names line up with the keys in ``notebook_weights.tsv``. A single-star
    glob is used on purpose so a stray ``.ipynb_checkpoints/`` is never picked up.
    """
    return sorted(glob.glob("*.ipynb"))


def main() -> None:
    """Print this CI instance's slice of the notebooks, one bare name per line."""
    num_bins: int = int(os.environ.get("CI_NODE_TOTAL", "1"))
    index: int = int(os.environ.get("CI_NODE_INDEX", "1"))  # 1-based
    weights: dict[str, float] = load_weights(WEIGHTS_FILE)
    notebooks: list[str] = discover_notebooks()
    bins: list[list[str]] = assign(notebooks, weights, num_bins)

    # Log the full packing to stderr so the CI log shows how balanced it is.
    for bin_index, names in enumerate(bins, start=1):
        total: float = sum(weights.get(nb, DEFAULT_WEIGHT) for nb in names)
        print(
            f"[pack] node {bin_index}/{num_bins}: {total:6.1f}s  {names}",
            file=sys.stderr,
        )

    for nb in bins[index - 1]:
        print(nb)


if __name__ == "__main__":
    main()
