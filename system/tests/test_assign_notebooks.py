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
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring
"""Tests for the CI notebook-assignment helper ``.ci/assign_notebooks.py``.

These pin the behaviour the ``notebooks/`` move must preserve: notebooks are
discovered in the current directory by their bare names (so the run-time weights
in ``notebook_weights.tsv`` resolve), the printed slice is those bare names, and
the weight-driven LPT packing across the CI's three parallel instances covers
every notebook. The CI job runs the helper from the ``notebooks/`` directory, so
the tests do the same.

``.ci`` is not an importable package, so the module is loaded from its file
path; all paths are anchored to this test file, and the module's cwd-relative
notebook glob is served by temporarily changing to the ``notebooks/`` directory.
"""

import contextlib
import importlib.util
import io
import os
import unittest
from pathlib import Path
from types import ModuleType

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
ASSIGN_PATH: Path = REPO_ROOT / ".ci" / "assign_notebooks.py"
NOTEBOOKS_DIR: Path = REPO_ROOT / "notebooks"

# The CI runs three parallel notebook instances (``parallel: 3`` in .gitlab-ci.yml).
CI_NODE_TOTAL: int = 3

# Frozen baseline of the weight-driven packing across the three CI instances.
# A packing that silently falls back to the default weight (e.g. the glob or the
# weights file stopped matching) would repack differently and fail these.
#
# These are characterisation tests coupled to the current notebook corpus:
# adding or removing a notebook, or editing ``notebook_weights.tsv``, changes
# the packing -- update EXPECTED_PACKING (and the hardcoded count/weight below)
# accordingly.
EXPECTED_PACKING: dict[int, list[str]] = {
    1: [
        "Christmas-Tree.ipynb",
        "B-tree.ipynb",
        "PlanEnumeration.ipynb",
        "Result-DB.ipynb",
        "External-Merge-Sort.ipynb",
    ],
    2: [
        "Recursive-Model-Index.ipynb",
        "RAID-Nesting-Trade-offs.ipynb",
        "Data-Layout.ipynb",
        "Bit-Sequences-in-Pandas.ipynb",
        "Z-Order-Curve.ipynb",
    ],
    3: [
        "Bitmaps-and-Bloom-Filters.ipynb",
        "CodeGen.ipynb",
        "Distributed-Joins.ipynb",
        "Top-k.ipynb",
        "Shared-Scan.ipynb",
        "Online-Aggregation.ipynb",
    ],
}


def _load_assign_module() -> ModuleType:
    """Import ``.ci/assign_notebooks.py`` by file path (it is not a package)."""
    spec = importlib.util.spec_from_file_location("assign_notebooks", ASSIGN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AssignNotebooksTest(unittest.TestCase):
    """Characterisation tests for the notebook-assignment helper."""

    def setUp(self) -> None:
        """Load the helper and run from notebooks/ so its glob resolves, as CI does."""
        self.module: ModuleType = _load_assign_module()
        self._prev_cwd: str = os.getcwd()
        self._prev_env: dict[str, str | None] = {
            key: os.environ.get(key) for key in ("CI_NODE_TOTAL", "CI_NODE_INDEX")
        }
        os.chdir(NOTEBOOKS_DIR)

    def tearDown(self) -> None:
        """Restore the working directory and the CI environment variables."""
        os.chdir(self._prev_cwd)
        for key, value in self._prev_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _slice_for(self, index: int, total: int = CI_NODE_TOTAL) -> list[str]:
        """Return the notebook lines ``main`` prints for one CI instance."""
        os.environ["CI_NODE_TOTAL"] = str(total)
        os.environ["CI_NODE_INDEX"] = str(index)
        buffer = io.StringIO()
        # main() also logs the packing to stderr; discard it to keep test output clean.
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(
            io.StringIO()
        ):
            self.module.main()
        return buffer.getvalue().splitlines()

    def test_discover_returns_bare_names_that_resolve_weights(self) -> None:
        """Discovery yields bare names so ``notebook_weights.tsv`` keys match."""
        notebooks = self.module.discover_notebooks()
        self.assertEqual(len(notebooks), 16)
        self.assertIn("Christmas-Tree.ipynb", notebooks)
        # Bare names, not paths -- otherwise weight lookup silently defaults.
        self.assertFalse(any("/" in name for name in notebooks))

        weights = self.module.load_weights(self.module.WEIGHTS_FILE)
        # A recorded weight must resolve through the real key, not the default.
        self.assertEqual(weights["Christmas-Tree.ipynb"], 7.7)
        self.assertNotEqual(weights["Christmas-Tree.ipynb"], self.module.DEFAULT_WEIGHT)

    def test_printed_slice_covers_every_notebook(self) -> None:
        """The union of the three instances is every notebook, each assigned once."""
        printed: list[str] = []
        for index in range(1, CI_NODE_TOTAL + 1):
            printed.extend(self._slice_for(index))

        # No notebook assigned twice and every one assigned exactly once.
        self.assertEqual(len(printed), 16)
        self.assertEqual(set(printed), set(self.module.discover_notebooks()))

    def test_weights_cover_exactly_the_notebooks(self) -> None:
        """Every notebook has a recorded weight and every weight names a real notebook.

        Guards against a stale ``notebook_weights.tsv`` key silently falling back
        to ``DEFAULT_WEIGHT`` -- invisible to the frozen packing when the stale
        notebook's real weight happens to equal the default.
        """
        weights = self.module.load_weights(self.module.WEIGHTS_FILE)
        self.assertEqual(set(weights), set(self.module.discover_notebooks()))

    def test_packing_matches_frozen_baseline(self) -> None:
        """The weight-driven packing reproduces the frozen assignment exactly."""
        for index, names in EXPECTED_PACKING.items():
            self.assertEqual(self._slice_for(index), names)


if __name__ == "__main__":
    unittest.main()
