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
"""Tests that the README section ``## Visualizations`` matches the pages in ``visualizations/``.

The section has one subsection per page (see CONTRIBUTING.md, section Visualizations): a heading
with the page's name linked to the page, a preview image linked to the page as well, the topic and,
for a page with a notebook, the notebook with its Binder badge. A page's name is its path in
``visualizations/`` without ``.html``. These tests fail when the section and the folders drift
apart: a page without a subsection or a subsection without a page, a page listed twice, a subsection
not in the expected form, a heading or preview that links to another page, a preview that is not the
page's image, a page without its preview or a preview without its page, or a notebook link to a
notebook that does not exist, with another label or with a Binder badge that opens another notebook.
They do not check the topic text, the order of the parts in a subsection, whether a page that
should link a notebook does, what a preview's alt text says (only that it is not empty or a
placeholder), or the notebook name in the alt text of a Binder badge.
"""

import re
import tempfile
import unittest
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from system.tests.repo.test_readme_notebooks import BINDER_PREFIX

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
README_PATH: Path = REPO_ROOT / "README.md"
PAGES_DIR: Path = REPO_ROOT / "visualizations"
PREVIEWS_DIR: Path = REPO_ROOT / "docs" / "images" / "visualizations"
NOTEBOOKS_DIR: Path = REPO_ROOT / "notebooks"

SECTION_HEADING: str = "## Visualizations"
FORM_HINT: str = "see CONTRIBUTING.md, section Visualizations"

# The README opens each page through htmlpreview.github.io (see CONTRIBUTING.md), from the main branch.
PAGE_URL_PREFIX: str = (
    "https://htmlpreview.github.io/?https://github.com/explaindb/explaindb/blob/main/visualizations/"
)

# The heading of a subsection: ### [clock-scan](<PAGE_URL_PREFIX>clock-scan.html)
HEADING_PATTERN: re.Pattern[str] = re.compile(
    r"### \[(?P<name>[^\]]+)\]\((?P<url>[^()\s]+)\)"
)

# The preview: [<img src="docs/images/visualizations/clock-scan.jpg" width="480" alt="…">](<page URL>)
PREVIEW_PATTERN: re.Pattern[str] = re.compile(
    r'\[<img src="docs/images/visualizations/(?P<image>[^"]+\.jpg)" width="480"'
    r' alt="(?P<alt>[^"]*)">\]\((?P<url>[^()\s]+)\)'
)

# The notebook line and, on the next line, its Binder badge:
#   Notebook: [Shared-Scan](notebooks/Shared-Scan.ipynb)
#   [![Open Shared-Scan on Binder](https://mybinder.org/badge_logo.svg)](<BINDER_PREFIX>Shared-Scan.ipynb)
NOTEBOOK_PATTERN: re.Pattern[str] = re.compile(
    r"Notebook: \[(?P<label>[^\]]+)\]\(notebooks/(?P<file>[^/()]+\.ipynb)\)"
)
BADGE_PATTERN: re.Pattern[str] = re.compile(
    r"\[!\[Open [^\]]+ on Binder\]\(https://mybinder\.org/badge_logo\.svg\)\]\("
    + re.escape(BINDER_PREFIX)
    + r"(?P<target>[^/()]+\.ipynb)\)"
)


class MalformedSubsection(ValueError):
    """A subsection of the section ``## Visualizations`` is not in the expected form; the message says why."""


@dataclass(frozen=True)
class NotebookLink:
    """The notebook of a visualization, as its subsection links it.

    ``label`` is the link text of the notebook line and ``file`` the notebook it links to;
    ``target`` is the notebook the Binder badge on the next line opens.
    """

    label: str
    file: str
    target: str


@dataclass(frozen=True)
class Subsection:
    """One parsed subsection of the README section ``## Visualizations``."""

    heading: str
    name: str
    heading_url: str
    preview_image: str
    preview_url: str
    notebook: NotebookLink | None


def readme_section(text: str, heading: str) -> list[str]:
    """Return the lines of a README section, from its heading to the next ``"## "`` heading.

    Raises ``AssertionError`` with a clear message if the text has no such heading line, rather
    than returning an empty section.

    @param text: the README content.
    @param heading: the section's heading line, e.g. ``"## Visualizations"``.
    @return: the section's lines, starting with the heading line.
    """
    lines: list[str] = text.splitlines()
    if heading not in lines:
        raise AssertionError(f"README.md has no line {heading!r}.")
    start: int = lines.index(heading)
    end: int = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return lines[start:end]


def subsections(section: list[str]) -> list[list[str]]:
    """Split a section into its subsections, each starting with its ``### `` heading line.

    @param section: the lines of the section; lines before the first ``### `` heading are dropped.
    @return: the lines of each subsection, in README order.
    """
    result: list[list[str]] = []
    for line in section:
        if line.startswith("### "):
            result.append([line])
        elif result:
            result[-1].append(line)
    return result


def heading_name(lines: list[str]) -> str | None:
    """Return the page name in the heading of a subsection, or None if the heading is not a linked name.

    @param lines: the lines of the subsection, starting with its heading line.
    @return: the name, e.g. ``"clock-scan"``.
    """
    heading: re.Match[str] | None = HEADING_PATTERN.fullmatch(lines[0])
    return heading["name"] if heading is not None else None


def parse_subsection(lines: list[str]) -> Subsection:
    """Parse one subsection; raise :class:`MalformedSubsection` if it is not in the expected form.

    A preview line is a line with ``<img`` or ``docs/images/``; the notebook line starts with
    ``Notebook:``, and its Binder badge is the next line. Any other line that mentions ``.ipynb``
    or ``mybinder.org`` is an error, so a notebook link in another form is not skipped silently.
    :meth:`ReadmeVisualizationsTest.test_every_subsection_has_expected_form` reports the errors.

    @param lines: the lines of the subsection, starting with its heading line.
    @return: the parsed subsection.
    """
    # the heading is a name with a link (where it points is checked by the tests below):
    heading: re.Match[str] | None = HEADING_PATTERN.fullmatch(lines[0])
    if heading is None:
        raise MalformedSubsection("the heading is not ### [<name>](<link>)")

    # exactly one preview, an HTML image 480 pixels wide with a real alt text and a link:
    previews: list[str] = [
        line for line in lines[1:] if "<img" in line or "docs/images/" in line
    ]
    if len(previews) != 1:
        raise MalformedSubsection(f"{len(previews)} preview lines instead of one")
    preview: re.Match[str] | None = PREVIEW_PATTERN.fullmatch(previews[0])
    if preview is None:
        raise MalformedSubsection(
            'the preview is not [<img src="docs/images/visualizations/<name>.jpg"'
            f' width="480" alt="…">](<link>): {previews[0]!r}'
        )
    # CONTRIBUTING.md writes the alt text as "…", so a copied example would keep that placeholder:
    if not preview["alt"].strip(" .…"):
        raise MalformedSubsection("the preview has no alt text")

    # at most one notebook line, with its Binder badge on the next line:
    notebook_lines: list[int] = [
        i for i, line in enumerate(lines) if line.startswith("Notebook:")
    ]
    if len(notebook_lines) > 1:
        raise MalformedSubsection(
            f"{len(notebook_lines)} notebook lines instead of one"
        )
    notebook: NotebookLink | None = None
    if notebook_lines:
        i: int = notebook_lines[0]
        link: re.Match[str] | None = NOTEBOOK_PATTERN.fullmatch(lines[i])
        if link is None:
            raise MalformedSubsection(
                "the notebook line is not Notebook: [<name>](notebooks/<name>.ipynb): "
                f"{lines[i]!r}"
            )
        after: str | None = lines[i + 1] if i + 1 < len(lines) else None
        badge: re.Match[str] | None = (
            BADGE_PATTERN.fullmatch(after) if after is not None else None
        )
        if badge is None:
            raise MalformedSubsection(
                "the line after the notebook line is not its Binder badge"
                " [![Open <name> on Binder](https://mybinder.org/badge_logo.svg)]"
                f"({BINDER_PREFIX}<name>.ipynb): "
                + (repr(after) if after is not None else "no line")
            )
        notebook = NotebookLink(link["label"], link["file"], badge["target"])

    # no other line links a notebook or Binder:
    known: set[int] = {i for j in notebook_lines for i in (j, j + 1)}
    for i, line in enumerate(lines):
        if i not in known and (".ipynb" in line or "mybinder.org" in line):
            raise MalformedSubsection(
                f"a notebook or Binder link outside the notebook line and its badge: {line!r}"
            )
    return Subsection(
        lines[0],
        heading["name"],
        heading["url"],
        preview["image"],
        preview["url"],
        notebook,
    )


def readme_subsections() -> list[list[str]]:
    """Return the subsections of the section ``## Visualizations`` of the repository README.

    @return: the lines of each subsection.
    """
    text: str = README_PATH.read_text(encoding="utf-8")
    return subsections(readme_section(text, SECTION_HEADING))


def parsed_subsections() -> list[Subsection]:
    """Return the subsections of the repository README that are in the expected form.

    The others are skipped here and reported by
    :meth:`ReadmeVisualizationsTest.test_every_subsection_has_expected_form`.

    @return: the parsed subsections, in README order.
    """
    parsed: list[Subsection] = []
    for lines in readme_subsections():
        try:
            parsed.append(parse_subsection(lines))
        except MalformedSubsection:
            pass
    return parsed


def page_names() -> set[str]:
    """Return the name of every page: its path in ``visualizations/`` without ``.html``.

    @return: e.g. ``{"clock-scan", "row-or-column", ...}``.
    """
    return {
        path.relative_to(PAGES_DIR).with_suffix("").as_posix()
        for path in PAGES_DIR.rglob("*.html")
    }


def files_in(directory: Path) -> set[str]:
    """Return the paths of the files in a folder and its subfolders, without hidden files.

    The names come from the folder listing, so they keep their case also on a file system that
    ignores it (macOS): ``Clock-Scan.jpg`` is not ``clock-scan.jpg``. Hidden files are skipped, so
    that a ``.DS_Store`` that macOS puts into a folder (``.gitignore`` keeps it out of the
    repository) does not count.

    @param directory: the folder.
    @return: the paths relative to the folder, e.g. ``{"clock-scan.jpg", ...}``.
    """
    return {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    }


class ReadmeVisualizationsHelpersTest(unittest.TestCase):
    """Tests for the helper functions on small hand-written README parts and a temporary folder."""

    PAGE_URL: str = f"{PAGE_URL_PREFIX}clock-scan.html"

    def _subsection_without_notebook(self) -> list[str]:
        """Return the lines of a subsection in the README's form, for a page without a notebook.

        @return: heading, preview and topic of the page ``clock-scan``, separated by blank lines.
        """
        return [
            f"### [clock-scan]({self.PAGE_URL})",
            "",
            '[<img src="docs/images/visualizations/clock-scan.jpg" width="480"'
            f' alt="Three query robots ride the scan car">]({self.PAGE_URL})',
            "",
            "Clock scan: one scan runs round the clock and serves three queries.",
        ]

    def test_section_keeps_subsections_and_ends_at_next_level_two_heading(
        self,
    ) -> None:
        """``###`` subsections stay in the section; the next ``"## "`` heading ends it.

        Would fail if the end check used ``startswith("##")`` (ending the section at its first
        subsection) or ignored the next section.
        """
        text: str = "\n".join(
            [
                "# Title",
                "## Visualizations",
                "Intro.",
                "### [a](a.html)",
                "### [b](b.html)",
                "## Notebooks",
                "### Indexing",
            ]
        )
        self.assertEqual(
            readme_section(text, "## Visualizations"),
            ["## Visualizations", "Intro.", "### [a](a.html)", "### [b](b.html)"],
        )

    def test_missing_heading_fails_loudly(self) -> None:
        """A README without the heading line fails with a message naming the heading.

        Would fail if a renamed heading silently produced an empty section, so the checks on the
        real README would compare nothing.
        """
        with self.assertRaisesRegex(AssertionError, "## Visualizations"):
            readme_section(
                "# Title\n## Visualizations overview\n### [a](a.html)\n",
                "## Visualizations",
            )

    def test_subsections_split_at_level_three_headings_and_drop_the_intro(
        self,
    ) -> None:
        """Each subsection starts at its ``### `` line; the lines before the first one are dropped.

        Would fail if the intro of the section became a subsection of its own, which the form
        check would then report as malformed.
        """
        section: list[str] = [
            "## Visualizations",
            "",
            "Intro.",
            "### [a](a.html)",
            "",
            "Topic a.",
            "### [b](b.html)",
            "Topic b.",
        ]
        self.assertEqual(
            subsections(section),
            [
                ["### [a](a.html)", "", "Topic a."],
                ["### [b](b.html)", "Topic b."],
            ],
        )

    def test_parse_subsection_with_notebook(self) -> None:
        """A subsection with a notebook yields the page's name, links, preview and notebook link.

        ``parse_subsection`` only parses, so here every field has its own value, also those that the
        tests on the real README compare: the heading links to another page than it names, the
        preview shows and links to two more pages, the label is not the notebook's file name, and
        the badge opens another notebook. Would fail if a field took the wrong group of its pattern
        or another line's value (e.g. the preview link as the heading link, the label from the file
        name, or the notebook file as the Binder target), or the Binder badge on the line after the
        notebook link was not found.
        """
        # a subsection named clock-scan whose heading links to validation-interval-to-point, whose
        # preview shows elasticity-resources-follow-demand and links to row-or-column, and whose
        # notebook line is labelled "Shared Scan", with a Binder badge that opens Data-Layout:
        heading_url: str = f"{PAGE_URL_PREFIX}validation-interval-to-point.html"
        other_page_url: str = f"{PAGE_URL_PREFIX}row-or-column.html"
        lines: list[str] = [
            f"### [clock-scan]({heading_url})",
            "",
            '[<img src="docs/images/visualizations/elasticity-resources-follow-demand.jpg"'
            f' width="480" alt="Three query robots ride the scan car">]({other_page_url})',
            "",
            "Clock scan: one scan runs round the clock and serves three queries.",
            "",
            "Notebook: [Shared Scan](notebooks/Shared-Scan.ipynb)",
            "[![Open Shared-Scan on Binder](https://mybinder.org/badge_logo.svg)]"
            f"({BINDER_PREFIX}Data-Layout.ipynb)",
        ]

        # every field is parsed from its own place, the notebook with its label, file and Binder target:
        self.assertEqual(
            parse_subsection(lines),
            Subsection(
                heading=lines[0],
                name="clock-scan",
                heading_url=heading_url,
                preview_image="elasticity-resources-follow-demand.jpg",
                preview_url=other_page_url,
                notebook=NotebookLink(
                    label="Shared Scan",
                    file="Shared-Scan.ipynb",
                    target="Data-Layout.ipynb",
                ),
            ),
        )

    def test_parse_subsection_without_notebook(self) -> None:
        """A subsection without a notebook line is in the expected form and has no notebook.

        Would fail if the notebook were required, so a page without a notebook would be reported
        as malformed.
        """
        lines: list[str] = self._subsection_without_notebook()
        self.assertEqual(
            parse_subsection(lines),
            Subsection(
                heading=lines[0],
                name="clock-scan",
                heading_url=self.PAGE_URL,
                preview_image="clock-scan.jpg",
                preview_url=self.PAGE_URL,
                notebook=None,
            ),
        )

    def test_parse_subsection_rejects_malformed_subsections(self) -> None:
        """A subsection not in the expected form raises ``MalformedSubsection``, whose message says why.

        Would fail if one of these variants parsed, so the live checks would skip it without a
        word (e.g. a preview in Markdown's image syntax, a badge to another branch, or a notebook
        link outside the notebook line), or if its message named another problem.
        """
        # the parts of a subsection with a notebook, which parse without the blank lines:
        heading, _, preview, _, topic = self._subsection_without_notebook()
        notebook: str = "Notebook: [Shared-Scan](notebooks/Shared-Scan.ipynb)"
        badge: str = (
            "[![Open Shared-Scan on Binder](https://mybinder.org/badge_logo.svg)]"
            f"({BINDER_PREFIX}Shared-Scan.ipynb)"
        )
        alt: str = 'alt="Three query robots ride the scan car"'
        parse_subsection([heading, preview, topic, notebook, badge])

        # each variant changes the valid subsection in one place; the reason names that place:
        markdown_preview: str = (
            "[![Three query robots ride the scan car]"
            f"(docs/images/visualizations/clock-scan.jpg)]({self.PAGE_URL})"
        )
        variants: dict[str, tuple[list[str], str]] = {
            "heading without a link": (
                ["### clock-scan", preview, topic],
                "heading is not",
            ),
            "no preview": ([heading, topic], "0 preview lines"),
            "two previews": ([heading, preview, preview, topic], "2 preview lines"),
            "preview in Markdown image syntax": (
                [heading, markdown_preview, topic],
                "preview is not",
            ),
            'preview with width="240"': (
                [heading, preview.replace('width="480"', 'width="240"'), topic],
                "preview is not",
            ),
            'preview with alt=""': (
                [heading, preview.replace(alt, 'alt=""'), topic],
                "no alt text",
            ),
            'preview with alt="…"': (
                [heading, preview.replace(alt, 'alt="…"'), topic],
                "no alt text",
            ),
            'preview with alt="..."': (
                [heading, preview.replace(alt, 'alt="..."'), topic],
                "no alt text",
            ),
            "preview from another folder": (
                [
                    heading,
                    preview.replace("docs/images/visualizations/", "images/"),
                    topic,
                ],
                "preview is not",
            ),
            "two notebook lines": (
                [heading, preview, topic, notebook, badge, notebook, badge],
                "2 notebook lines",
            ),
            "notebook line in another form": (
                [heading, preview, topic, "Notebook: [x](../notebooks/x.ipynb)", badge],
                # anchored, as the badge message contains these words, too:
                "^the notebook line is not",
            ),
            "notebook line followed by the topic": (
                [heading, preview, notebook, topic],
                "not its Binder badge",
            ),
            "blank line between notebook line and badge": (
                [heading, preview, topic, notebook, "", badge],
                "not its Binder badge",
            ),
            "notebook line as the last line": (
                [heading, preview, topic, notebook],
                "not its Binder badge",
            ),
            "badge to another branch": (
                [heading, preview, topic, notebook, badge.replace("/main?", "/dev?")],
                "not its Binder badge",
            ),
            "notebook link in bold": (
                [heading, preview, topic, "**Notebook:** [X](notebooks/X.ipynb)"],
                "outside the notebook line",
            ),
            "Binder badge without notebook line": (
                [heading, preview, topic, badge],
                "outside the notebook line",
            ),
            "second badge after the notebook's badge": (
                [heading, preview, topic, notebook, badge, badge],
                "outside the notebook line",
            ),
        }
        for case, (lines, reason) in variants.items():
            with self.subTest(case=case):
                with self.assertRaisesRegex(MalformedSubsection, reason):
                    parse_subsection(lines)

    def test_heading_name_of_linked_and_unlinked_heading(self) -> None:
        """``heading_name`` returns the name of a linked heading and None for a heading without a link.

        Would fail if the name kept the brackets or the link, or if a heading without a link
        raised instead of returning None, so the check that the section lists exactly the pages
        would crash instead of reporting the page.
        """
        self.assertEqual(
            heading_name(self._subsection_without_notebook()), "clock-scan"
        )
        self.assertIsNone(heading_name(["### clock-scan", "", "Topic."]))

    def test_files_in_lists_files_in_subfolders_without_hidden_files(self) -> None:
        """``files_in`` returns the paths of all files below a folder, relative to it, without hidden files.

        Would fail if a ``.DS_Store`` counted as a preview without a page, a file in a subfolder
        was missed or got an absolute path, or an empty subfolder was listed as a file.
        """
        with tempfile.TemporaryDirectory() as directory:
            # two previews, one of them in a subfolder, a .DS_Store in both folders and an empty
            # subfolder:
            root: Path = Path(directory)
            (root / "sub").mkdir()
            (root / "empty").mkdir()
            for name in ["a.jpg", "sub/b.jpg", ".DS_Store", "sub/.DS_Store"]:
                (root / name).write_bytes(b"")

            # only the two previews are listed, with their paths relative to the folder:
            self.assertEqual(files_in(root), {"a.jpg", "sub/b.jpg"})


class ReadmeVisualizationsTest(unittest.TestCase):
    """The README section ``## Visualizations`` agrees with ``visualizations/`` and its previews."""

    def test_section_has_subsections(self) -> None:
        """The section has at least one subsection.

        Would fail if the subsections were removed or got another heading level, which would
        otherwise let every other check pass on an empty section.
        """
        self.assertGreater(
            len(readme_subsections()),
            0,
            f"The README section {SECTION_HEADING!r} has no ### subsections ({FORM_HINT}).",
        )

    def test_every_subsection_has_expected_form(self) -> None:
        """Every subsection has a linked heading, one preview and at most one notebook with its badge.

        Would fail if a subsection had, for example, no preview, a preview in Markdown's image
        syntax, or a notebook link without its Binder badge; such a subsection would otherwise be
        skipped by the other checks.
        """
        problems: list[str] = []
        for lines in readme_subsections():
            try:
                parse_subsection(lines)
            except MalformedSubsection as error:
                problems.append(f"{lines[0]!r}: {error}")
        if problems:
            self.fail(
                f"README subsections of Visualizations not in the expected form ({FORM_HINT}):\n"
                + "\n".join(problems)
            )

    def test_section_lists_exactly_the_pages(self) -> None:
        """Every page in ``visualizations/`` has a subsection, and every subsection names a page.

        Would fail if a page was added, renamed or removed without updating the README. The names
        come from the headings, so a subsection with a malformed body still counts here.
        """
        # the names in the headings and the pages on disk:
        names: list[str | None] = [heading_name(s) for s in readme_subsections()]
        listed: set[str] = {name for name in names if name is not None}
        on_disk: set[str] = page_names()

        # report pages on either side only:
        problems: list[str] = []
        if on_disk - listed:
            problems.append(
                "Pages without a subsection in the README section Visualizations: "
                + ", ".join(sorted(on_disk - listed))
            )
        if listed - on_disk:
            problems.append(
                "README subsections for pages that do not exist in visualizations/: "
                + ", ".join(sorted(listed - on_disk))
            )
        if problems:
            self.fail("\n".join(problems))

    def test_no_page_listed_twice(self) -> None:
        """Each page has only one subsection.

        Would fail if a subsection was copied, which ``test_section_lists_exactly_the_pages``
        cannot see (it compares sets).
        """
        counts: Counter[str] = Counter(
            name for name in map(heading_name, readme_subsections()) if name is not None
        )
        duplicates: list[str] = sorted(name for name, n in counts.items() if n > 1)
        if duplicates:
            self.fail(f"Pages listed twice in the README: {', '.join(duplicates)}")

    def test_heading_and_preview_link_to_the_page(self) -> None:
        """The heading and the preview link to the page the heading names, and the preview is its image.

        Would fail if a copied subsection kept another page's link or preview.
        """
        for s in parsed_subsections():
            url: str = f"{PAGE_URL_PREFIX}{s.name}.html"
            with self.subTest(page=s.name, part="heading link"):
                self.assertEqual(s.heading_url, url, f"in {s.heading!r}")
            with self.subTest(page=s.name, part="preview link"):
                self.assertEqual(s.preview_url, url)
            with self.subTest(page=s.name, part="preview image"):
                self.assertEqual(s.preview_image, f"{s.name}.jpg")

    def test_previews_are_exactly_the_pages(self) -> None:
        """Every page has its preview ``<name>.jpg``, and every file among the previews belongs to a page.

        Would fail if a preview was missing, had the wrong case or another format, or stayed behind
        after its page was renamed or removed.
        """
        # the previews the pages need and the files that are there, with their case:
        needed: set[str] = {f"{name}.jpg" for name in page_names()}
        present: set[str] = files_in(PREVIEWS_DIR)

        # report files on either side only:
        problems: list[str] = []
        if needed - present:
            problems.append(
                "Pages without a preview in docs/images/visualizations/: "
                + ", ".join(sorted(needed - present))
            )
        if present - needed:
            problems.append(
                "Files in docs/images/visualizations/ that are no page's preview: "
                + ", ".join(sorted(present - needed))
            )
        if problems:
            self.fail("\n".join(problems))

    def test_notebook_links_exist_and_agree(self) -> None:
        """A linked notebook exists, its label is its name, and its Binder badge opens it.

        Would fail if a notebook was renamed or removed without updating the README, or a copied
        notebook line kept another notebook's label or Binder badge.
        """
        notebooks: set[str] = {path.name for path in NOTEBOOKS_DIR.glob("*.ipynb")}
        for s in parsed_subsections():
            if s.notebook is None:
                continue
            with self.subTest(page=s.name, part="notebook exists"):
                self.assertIn(
                    s.notebook.file, notebooks, f"no notebooks/{s.notebook.file}"
                )
            with self.subTest(page=s.name, part="label"):
                self.assertEqual(s.notebook.label, Path(s.notebook.file).stem)
            with self.subTest(page=s.name, part="Binder badge"):
                self.assertEqual(s.notebook.target, s.notebook.file)


if __name__ == "__main__":
    unittest.main()
