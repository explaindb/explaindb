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
"""Tests that every third-party package imported in ``system/`` is declared in ``pyproject.toml``.

A package that is installed only because a declared package depends on it
disappears as soon as that package drops the dependency, and the import fails.
These tests parse every ``.py`` file under ``system/``, collect the top-level
modules of its absolute imports and check that each of them, apart from the
standard library and the repository's own modules, belongs to a distribution
declared in ``pyproject.toml``: in the main dependencies or in a dependency
group.
"""

import ast
import importlib.metadata
import re
import sys
import tomllib
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
SYSTEM_DIR: Path = REPO_ROOT / "system"
PYPROJECT: Path = REPO_ROOT / "pyproject.toml"

# Directories whose packages and modules count as the repository's own: the
# repository root (e.g. ``system``, ``tools``) and ``docs/api``, which
# test_javadoc_hook.py puts on ``sys.path`` to import ``conf`` and ``javadoc``.
FIRST_PARTY_DIRS: tuple[Path, ...] = (REPO_ROOT, REPO_ROOT / "docs" / "api")

# Imported modules whose distribution is knowingly not declared yet, each with a
# comment saying why and until when; empty while every import is declared.
NOT_YET_DECLARED: frozenset[str] = frozenset()

# The distribution name at the start of a requirement such as
# ``black[jupyter]==26.10.1`` (PEP 508).
REQUIREMENT_NAME: re.Pattern[str] = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    """Return a distribution name normalised as in PEP 503.

    @param name: a distribution name, e.g. ``PyYAML`` or ``jupyter_events``.
    @return: the name in lowercase with every run of ``-``, ``_`` and ``.``
        replaced by a single ``-``, e.g. ``pyyaml`` or ``jupyter-events``.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def imported_modules(source: str, filename: str = "<unknown>") -> set[str]:
    """Return the top-level modules of all absolute imports in a source text.

    Relative imports (``from . import x``) name the importing package itself
    and are skipped.

    @param source: the text of a Python module.
    @param filename: the file the text comes from, named in syntax errors.
    @return: e.g. ``{"yaml", "system"}`` for ``import yaml`` and
        ``from system.DBMS import DBMS``.
    """
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def first_party_modules() -> set[str]:
    """Return the names of the repository's own packages and modules.

    @return: the names of the directories and ``.py`` files in
        :data:`FIRST_PARTY_DIRS`, without the ``.py`` suffix.
    """
    names: set[str] = set()
    for directory in FIRST_PARTY_DIRS:
        for path in directory.iterdir():
            if path.is_dir():
                names.add(path.name)
            elif path.suffix == ".py":
                names.add(path.stem)
    return names


def third_party_imports() -> dict[str, list[str]]:
    """Return the third-party modules imported by the ``.py`` files under ``system/``.

    @return: a map from each imported top-level module that is neither in the
        standard library nor one of :func:`first_party_modules` to the files
        (relative to the repository root) that import it.
    """
    own: set[str] = first_party_modules()
    importers: dict[str, list[str]] = {}
    for path in sorted(SYSTEM_DIR.rglob("*.py")):
        source: str = path.read_text(encoding="utf-8")
        for module in imported_modules(source, filename=str(path)):
            if module in sys.stdlib_module_names or module in own:
                continue
            importers.setdefault(module, []).append(str(path.relative_to(REPO_ROOT)))
    return importers


def declared_distributions(pyproject: dict[str, Any]) -> set[str]:
    """Return the distributions declared in a parsed ``pyproject.toml``.

    Entries of a dependency group that include another group
    (``{include-group = "..."}``) name no distribution and are skipped.

    @param pyproject: the file as parsed by ``tomllib``.
    @return: the normalised names (see :func:`normalize`) of the main
        dependencies and of the dependencies of every dependency group.
    """
    requirements: list[str | dict[str, Any]] = list(
        pyproject["project"]["dependencies"]
    )
    for group in pyproject.get("dependency-groups", {}).values():
        requirements.extend(group)
    names: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, str):
            continue
        match: re.Match[str] | None = REQUIREMENT_NAME.match(requirement)
        if match:
            names.add(normalize(match.group(1)))
    return names


def distributions_of(module: str, installed: Mapping[str, list[str]]) -> set[str]:
    """Return the normalised names of the distributions that provide a module.

    A module that is not installed (e.g. Playwright, which only the CI jobs of
    the browser tests and of the type check install) is assumed to come from
    the distribution of the same name.

    @param module: a top-level module name, e.g. ``yaml``.
    @param installed: a map from top-level module to distribution names, as
        returned by ``importlib.metadata.packages_distributions()``.
    @return: e.g. ``{"pyyaml"}`` for ``yaml``.
    """
    return {normalize(name) for name in installed.get(module, [module])}


class HelperTest(unittest.TestCase):
    """Tests for the helpers on hand-written sources and ``pyproject.toml`` data."""

    def test_only_top_level_modules_of_absolute_imports_are_collected(self) -> None:
        """Both import forms count with their top-level module; relative imports do not.

        Would fail if a dotted name was kept whole, if an import inside a
        function was missed, or if a relative import counted as a third-party
        module of the same name.
        """
        # both import forms, an import inside a function and two relative imports:
        source: str = (
            "import yaml, IPython.core.display_functions\n"
            "from attr import dataclass\n"
            "from . import sibling\n"
            "from .graphs import draw\n"
            "def f():\n"
            "    import graphviz\n"
        )
        self.assertEqual(
            imported_modules(source), {"yaml", "IPython", "attr", "graphviz"}
        )

    def test_declared_distributions_cover_main_dependencies_and_groups(self) -> None:
        """Names come from the main dependencies and every group, normalised.

        Would fail if extras or version pins stayed part of the name, if names
        were compared unnormalised (``PyYAML`` against ``pyyaml``), if a group
        was ignored, or if an ``include-group`` entry broke the parsing.
        """
        # a pyproject.toml with extras, pins, mixed spelling and an included group:
        pyproject: dict[str, Any] = {
            "project": {"dependencies": ["black[jupyter]==26.10.1", "PyYAML==6.0.3"]},
            "dependency-groups": {
                "browser-tests": ["playwright==1.64.1"],
                "all": [{"include-group": "browser-tests"}, "Jupyter_Events>=0.1"],
            },
        }
        self.assertEqual(
            declared_distributions(pyproject),
            {"black", "pyyaml", "playwright", "jupyter-events"},
        )

    def test_a_module_maps_to_its_distributions_or_to_its_own_name(self) -> None:
        """An installed module maps to its distributions, a missing one to its own name.

        Would fail if the import name was compared with the declared names
        directly (``yaml`` is not ``pyyaml``), or if a module that is not
        installed, such as Playwright in the CI job py_test, was reported as
        undeclared although its distribution has the same name.
        """
        # an installed module whose distribution has another name:
        installed: dict[str, list[str]] = {"yaml": ["PyYAML"]}
        self.assertEqual(distributions_of("yaml", installed), {"pyyaml"})

        # a module that is not installed:
        self.assertEqual(distributions_of("playwright", installed), {"playwright"})


class DeclaredImportsTest(unittest.TestCase):
    """Every third-party package imported in ``system/`` is declared."""

    def test_imports_are_found_and_the_repository_s_own_modules_skipped(self) -> None:
        """Third-party imports are found; ``system`` and ``tools`` are not among them.

        Would fail if the files were not found or misparsed, which would let the
        check below pass on nothing, or if the repository's own packages were
        reported as undeclared.
        """
        # some third-party module is imported, e.g. graphviz in btree.py:
        imports: dict[str, list[str]] = third_party_imports()
        self.assertIn("graphviz", imports)

        # the repository's own packages are skipped:
        self.assertNotIn("system", imports)
        self.assertNotIn("tools", imports)

    def test_every_imported_third_party_package_is_declared(self) -> None:
        """Each imported third-party module belongs to a declared distribution.

        Would fail if code in ``system/`` imported a package that is installed
        only because a declared package depends on it, or if a module in
        :data:`NOT_YET_DECLARED` was no longer imported, so that its entry
        could hide a later undeclared import.
        """
        # the declared distributions and the installed module-to-distribution map:
        declared: set[str] = declared_distributions(
            tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        )
        installed: Mapping[str, list[str]] = importlib.metadata.packages_distributions()

        # every imported module that is not exempted belongs to one of them:
        imports: dict[str, list[str]] = third_party_imports()
        for module, files in sorted(imports.items()):
            if module in NOT_YET_DECLARED:
                continue
            with self.subTest(module=module):
                distributions: set[str] = distributions_of(module, installed)
                listed: str = ", ".join(sorted(distributions))
                origin: str = (
                    f"distribution {listed}"
                    if module in installed
                    else f"not installed, assumed distribution {listed}"
                )
                self.assertTrue(
                    distributions & declared,
                    f"{module} ({origin}) is imported in {', '.join(files)} but "
                    "not declared in pyproject.toml. Add it with an exact pin to "
                    "the dependencies (a package that only tests in a CI job "
                    "with a dependency group need goes into that group), then "
                    "run uv lock and regenerate .binder/requirements.txt (see "
                    "CONTRIBUTING.md, section Dependencies).",
                )

        # every exempted module is still imported, so a stale entry is removed:
        for module in sorted(NOT_YET_DECLARED):
            with self.subTest(exempted=module):
                self.assertTrue(
                    module in imports,
                    f"{module} is no longer imported in system/; remove it from "
                    "NOT_YET_DECLARED.",
                )


if __name__ == "__main__":
    unittest.main()
