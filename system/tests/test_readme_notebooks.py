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
"""Tests that the README notebook table matches the notebooks in ``notebooks/``.

The README section ``## Notebooks`` lists every notebook in a hand-maintained
table (one table per tutorial chapter) with a link to the file and a Binder
badge that opens it. These tests fail when the table and the directory drift
apart: a notebook missing from the table or listed but not existing, a notebook
listed twice, a row that does not have the exact expected form, a row whose
label, file link and Binder target disagree, or a Binder link that points to the
wrong host, repository or branch.
"""

import re
import unittest
from collections import Counter
from pathlib import Path
from typing import NamedTuple

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
README_PATH: Path = REPO_ROOT / "README.md"
NOTEBOOKS_DIR: Path = REPO_ROOT / "notebooks"

SECTION_HEADING: str = "## Notebooks"
TABLE_HEADER: str = "| Notebook | Topic | Launch |"

# Every Binder link must open the notebook from this repository's main branch.
BINDER_PREFIX: str = (
    "https://mybinder.org/v2/gh/explaindb/explaindb/main?urlpath=lab/tree/notebooks/"
)

# One table row, matched against the whole line (shown wrapped here):
#   | [Data-Layout](notebooks/Data-Layout.ipynb) | Row vs. column ...
#   | [![Open Data-Layout on Binder](https://mybinder.org/badge_logo.svg)]
#     (<BINDER_PREFIX>Data-Layout.ipynb) |
# Captures the label, the linked notebook file and the Binder target file.
ROW_PATTERN: re.Pattern[str] = re.compile(
    r"\| \[(?P<label>[^\]]+)\]\(notebooks/(?P<file>[^/()]+\.ipynb)\)"
    r" \| [^|]+"
    r" \| \[!\[Open [^\]]+ on Binder\]\(https://mybinder\.org/badge_logo\.svg\)\]\("
    + re.escape(BINDER_PREFIX)
    + r"(?P<target>[^/()]+\.ipynb)\) \|"
)

# A Markdown table separator line such as ``|---|---|---|``.
SEPARATOR_PATTERN: re.Pattern[str] = re.compile(r"\|(\s*:?-+:?\s*\|)+")


class NotebookRow(NamedTuple):
    """One parsed data row of the README notebook table."""

    line: str
    label: str
    file: str
    target: str


def notebooks_section(text: str) -> list[str]:
    """Return the lines of the README section ``## Notebooks``.

    The section runs from the ``## Notebooks`` line up to, but excluding, the
    next line starting with ``"## "`` (with the space), or to the end of the
    text. The chapter sub-headings (``### ...``) inside the section therefore
    do not end it.

    Raises ``AssertionError`` with a clear message if the text has no
    ``## Notebooks`` heading, rather than returning an empty section.

    @param text: the README content.
    @return: the section's lines, starting with the heading line.
    """
    lines: list[str] = text.splitlines()
    if SECTION_HEADING not in lines:
        raise AssertionError(
            f"README.md has no line {SECTION_HEADING!r}; the notebook table "
            "must live in that section."
        )
    start: int = lines.index(SECTION_HEADING)
    end: int = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return lines[start:end]


def data_rows(section: list[str]) -> list[str]:
    """Return the table lines of the section that are neither header nor separator.

    @param section: the lines of the ``## Notebooks`` section.
    @return: every line starting with ``|`` except table headers and separators.
    """
    return [
        line
        for line in section
        if line.startswith("|")
        and line != TABLE_HEADER
        and not SEPARATOR_PATTERN.fullmatch(line)
    ]


def parse_rows(rows: list[str]) -> list[NotebookRow]:
    """Parse the data rows that match :data:`ROW_PATTERN`; skip the others.

    Rows that do not match are reported by
    :meth:`ReadmeNotebookTableTest.test_every_row_has_expected_form`.

    @param rows: data rows as returned by :func:`data_rows`.
    @return: the parsed rows, in README order.
    """
    parsed: list[NotebookRow] = []
    for line in rows:
        match: re.Match[str] | None = ROW_PATTERN.fullmatch(line)
        if match is not None:
            parsed.append(
                NotebookRow(line, match["label"], match["file"], match["target"])
            )
    return parsed


def readme_rows() -> list[str]:
    """Return the data rows of the notebook table in the repository README.

    @return: the data rows of the ``## Notebooks`` section of ``README.md``.
    """
    return data_rows(notebooks_section(README_PATH.read_text(encoding="utf-8")))


class NotebooksSectionTest(unittest.TestCase):
    """Tests for the section extraction on small hand-written READMEs."""

    def test_section_ends_at_next_level_two_heading_only(self) -> None:
        """``###`` sub-headings stay in the section; the next ``"## "`` heading ends it.

        Would fail if the end check used ``startswith("##")`` (cutting the table
        off at the first chapter heading) or ignored the next section.
        """
        text: str = "\n".join(
            [
                "# Title",
                "## Notebooks",
                "### Indexing",
                "| row |",
                "## Next",
                "| other |",
            ]
        )
        self.assertEqual(
            notebooks_section(text), ["## Notebooks", "### Indexing", "| row |"]
        )

    def test_missing_heading_fails_loudly(self) -> None:
        """A README without ``## Notebooks`` fails instead of yielding no rows.

        Would fail if a renamed heading silently produced an empty section, so
        the table checks would compare nothing.
        """
        with self.assertRaisesRegex(AssertionError, "## Notebooks"):
            notebooks_section("# Title\n## Notebook overview\n| row |\n")


class ReadmeNotebookTableTest(unittest.TestCase):
    """The README notebook table agrees with the notebooks in ``notebooks/``."""

    def test_table_has_rows(self) -> None:
        """The section contains at least one data row.

        Would fail if the table was removed or moved out of the section, which
        would otherwise let every other check pass on an empty table.
        """
        self.assertGreater(len(readme_rows()), 0)

    def test_every_row_has_expected_form(self) -> None:
        """Every data row matches the exact expected row form.

        Would fail if a row was malformed or its Binder link used another host,
        repository or branch -- such a row would otherwise be skipped silently.
        """
        bad: list[str] = [
            line for line in readme_rows() if not ROW_PATTERN.fullmatch(line)
        ]
        if bad:
            self.fail(
                "README notebook rows not in the expected form "
                f"(link | topic | Binder badge to {BINDER_PREFIX}<file>):\n"
                + "\n".join(repr(line) for line in bad)
            )

    def test_table_lists_exactly_the_notebooks(self) -> None:
        """The table lists every notebook in ``notebooks/`` and nothing else.

        Would fail if a notebook was added, renamed or removed without updating
        the README table.
        """
        listed: set[str] = {row.file for row in parse_rows(readme_rows())}
        # Non-recursive on purpose: Jupyter's git-ignored .ipynb_checkpoints/
        # would otherwise make this fail locally but pass in CI.
        on_disk: set[str] = {path.name for path in NOTEBOOKS_DIR.glob("*.ipynb")}
        missing: list[str] = sorted(on_disk - listed)
        extra: list[str] = sorted(listed - on_disk)
        problems: list[str] = []
        if missing:
            problems.append(
                "Notebooks missing from the README table (add them to the README "
                f"table or delete them): {', '.join(missing)}"
            )
        if extra:
            problems.append(
                "README table lists notebooks that do not exist in notebooks/: "
                + ", ".join(extra)
            )
        if problems:
            self.fail("\n".join(problems))

    def test_no_notebook_listed_twice(self) -> None:
        """Each notebook appears in only one row.

        Would fail if a row was copied into a second chapter, which
        ``test_table_lists_exactly_the_notebooks`` cannot see (it compares sets).
        """
        counts: Counter[str] = Counter(row.file for row in parse_rows(readme_rows()))
        duplicates: list[str] = sorted(name for name, n in counts.items() if n > 1)
        if duplicates:
            self.fail(f"Notebooks listed twice in the README: {', '.join(duplicates)}")

    def test_label_link_and_binder_target_agree(self) -> None:
        """Per row, the Binder target is the linked file and the label is its stem.

        Would fail if a copied row kept another notebook's Binder link or label.
        The badge's alt text is not compared (deferred, see
        docs/changes/004-readme-notebook-sync).
        """
        for row in parse_rows(readme_rows()):
            with self.subTest(notebook=row.file):
                self.assertEqual(
                    row.target, row.file, f"Binder target differs in: {row.line}"
                )
                self.assertEqual(
                    row.label, Path(row.file).stem, f"Label differs in: {row.line}"
                )


if __name__ == "__main__":
    unittest.main()
