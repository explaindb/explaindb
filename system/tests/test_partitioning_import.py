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

# Test modules use self-documenting method/class names, so pylint's naming and
# docstring checks are relaxed here.
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring
"""Regression test: importing system.playground.partitioning has no side effect."""

import os
import subprocess
import sys
import unittest

# Repo root: three levels up from system/tests/this_file.py.
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


class PartitioningImportTest(unittest.TestCase):

    def test_import_produces_no_output(self):
        """Importing the module prints nothing and returns promptly.

        The module holds a playground demo (build a gate tree, run a million
        random walks, print the tree). Guarded under ``if __name__ ==
        "__main__"``, that demo runs only on direct execution. Would fail if the
        demo ran at import time again: the printed tree would appear on stdout
        (and the million-iteration loop would stall the import). Run in a
        subprocess so the check is immune to Python's module import cache.
        """
        result = subprocess.run(
            [sys.executable, "-c", "import system.playground.partitioning"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
