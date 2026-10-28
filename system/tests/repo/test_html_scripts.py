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
"""Tests for the CI helper ``.ci/html_scripts.py`` that writes the inline JavaScript of HTML pages for Semgrep.

``.ci`` is not an importable package, so the module is loaded from its file path.
"""

import contextlib
import importlib.util
import io
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
SCRIPT_PATH: Path = REPO_ROOT / ".ci" / "html_scripts.py"


def load_script() -> ModuleType:
    """Loads ``.ci/html_scripts.py`` as a module."""
    spec = importlib.util.spec_from_file_location("html_scripts", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script: ModuleType = load_script()


def write_page(directory: Path, name: str, text: str) -> Path:
    """Writes an HTML page with the given text and returns its path."""
    path: Path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def run_main(arguments: list[str]) -> tuple[int, str, str]:
    """Runs the script's ``main`` with the given arguments; returns its exit status, its output and its error output."""
    output: io.StringIO = io.StringIO()
    errors: io.StringIO = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        status: int = script.main(arguments)
    return status, output.getvalue(), errors.getvalue()


class PageCodeTest(unittest.TestCase):
    """Checks that the inline JavaScript of a page is placed at its line and column in the page."""

    def test_text_on_the_line_of_the_tag_keeps_its_column(self) -> None:
        """Text right after ``<script>`` and right before ``</script>`` keeps its line and column in the page."""
        # a script on lines 5 to 7, indented by two spaces; its text starts directly after <script> and ends
        # directly before </script>:
        files, skipped = script.page_code(
            "<!DOCTYPE html>\n"
            "<html>\n"
            "<body>\n"
            "<p>Counter</p>\n"
            "  <script>let a = 1;\n"
            "  a += 1;\n"
            "  show(a);</script>\n"
            "</body>\n"
            "</html>\n"
        )
        # lines 1 to 4 are empty; on line 5, let starts at column 10 as in the page; lines 6 and 7 are the page's
        # lines up to </script>; nothing follows the script:
        self.assertEqual(
            ["\n\n\n\n          let a = 1;\n  a += 1;\n  show(a);\n"], files
        )
        self.assertEqual([], skipped)

    def test_start_tag_over_two_lines_puts_the_text_on_the_line_of_its_end(
        self,
    ) -> None:
        """For a start tag split over two lines, the text starts on the line of the tag's ``>``, at its column there."""
        # <script on line 2, its attribute and > on line 3, directly followed by the text:
        files, skipped = script.page_code(
            "<p>Module</p>\n"
            "<script\n"
            ' type="module">import { f } from "./f.js";\n'
            "f();</script>\n"
        )
        # the import is on line 3 at column 15, right after type="module">:
        self.assertEqual(
            ['\n\n               import { f } from "./f.js";\nf();\n'], files
        )
        self.assertEqual([], skipped)

    def test_two_scripts_are_written_at_their_lines(self) -> None:
        """Two ``<script>`` elements get a file each, in the order of the page, each with its text at its line."""
        # one script in the head on line 3 and one in the body on line 7:
        files, skipped = script.page_code(
            "<html>\n"
            "<head>\n"
            "<script>const title = 'two';</script>\n"
            "</head>\n"
            "<body>\n"
            "<p>Text</p>\n"
            "<script>document.title = title;</script>\n"
            "</body>\n"
            "</html>\n"
        )
        # the first file holds line 3, the second line 7, both at column 8, after <script>; in each file, all
        # other lines are empty, so the second file does not hold the first script:
        self.assertEqual(
            [
                "\n\n        const title = 'two';\n",
                "\n\n\n\n\n\n        document.title = title;\n",
            ],
            files,
        )
        self.assertEqual([], skipped)

    def test_two_scripts_on_one_line_get_a_file_each(self) -> None:
        """Two ``<script>`` elements on one line get a file each, each with its text at its column in the page."""
        # a() starts at column 8, after <script>, and b() at column 29, after <script>a();</script><script>:
        self.assertEqual(
            ([" " * 8 + "a();\n", " " * 29 + "b();\n"], []),
            script.page_code("<script>a();</script><script>b();</script>\n"),
        )

    def test_empty_script_gets_no_file(self) -> None:
        """An empty ``<script></script>`` gets no file, so the first file holds the script after it."""
        # b() starts at column 25, after <script></script><script>:
        self.assertEqual(
            ([" " * 25 + "b();\n"], []),
            script.page_code("<script></script><script>b();</script>\n"),
        )

    def test_all_pages_of_the_repository_are_written_at_their_lines(self) -> None:
        """The inline JavaScript of every HTML page in the repository is written in full, each line at its place."""
        # the tracked HTML pages, with the ending .html or .htm in any case:
        names: list[str] = subprocess.run(
            # safe.directory: in CI, the checkout may belong to another user than the tests:
            ["git", "-c", f"safe.directory={REPO_ROOT}", "ls-files", "-z", "--"]
            + [":(icase)*.html", ":(icase)*.htm"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split("\0")
        # a <script> element and its text, as a simple regex reads it:
        element: re.Pattern[str] = re.compile(
            r"<script\b[^>]*>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL
        )
        checked: int = 0
        # one sub-test per page, so a failure names it; page_code raises a PageError for a page it cannot write:
        for name in sorted(filter(None, names)):
            with self.subTest(page=name):
                # read as main reads a page, which turns \r\n into \n:
                text: str = (REPO_ROOT / name).read_text(encoding="utf-8")
                files: list[str] = script.page_code(text)[0]
                checked += bool(files)
                # the files hold the words of the page's inline JavaScript and nothing else, also on a page
                # without any; of the <script> elements the regex finds, those count that page_code writes when
                # given the element alone:
                expected: list[str] = [
                    word
                    for match in element.finditer(text)
                    if script.page_code(match.group(0))[0]
                    for word in match.group(1).split()
                ]
                self.assertEqual(expected, "".join(files).split())
                # every line with code holds the text of the page's line with the same number, at the same
                # column:
                page_lines: list[str] = text.split("\n")
                for code in files:
                    for number, line in enumerate(code.split("\n"), start=1):
                        stripped: str = line.strip()
                        if stripped:
                            column: int = line.index(stripped)
                            self.assertEqual(
                                stripped,
                                page_lines[number - 1][column : column + len(stripped)],
                                f"line {number}",
                            )
        # the test fails if no page has inline JavaScript, so it cannot pass without checking anything:
        self.assertGreater(checked, 0)


class ScriptKindTest(unittest.TestCase):
    """Checks which ``<script>`` elements are written as JavaScript and which are listed as not scanned."""

    def test_javascript_scripts_are_written(self) -> None:
        """A ``<script>`` that browsers run as JavaScript, by its ``type`` or ``language``, is written."""
        # without type, with an empty or a bare type, a module, a JavaScript type in another case and with spaces,
        # an empty language or one that makes text/javascript; type counts before language, and of two type
        # attributes the first:
        for attributes in [
            "",
            ' type=""',
            " type",
            ' type="module"',
            ' type=" Text/JavaScript "',
            ' language="JavaScript"',
            ' language=""',
            ' type="module" language="VBScript"',
            ' type="module" type="text/template"',
        ]:
            with self.subTest(attributes=attributes):
                page_text: str = f"<script{attributes}>f();</script>\n"
                # the text is written right after the start tag, and nothing is listed:
                self.assertEqual(
                    ([" " * page_text.index("f();") + "f();\n"], []),
                    script.page_code(page_text),
                )

    def test_other_scripts_are_listed_not_written(self) -> None:
        """A ``<script>`` that browsers do not run as JavaScript is not written, but listed with its line and type."""
        # JSON, an import map, a language that is not JavaScript; type counts before language, and of two type
        # attributes the first:
        for attributes, kind in [
            (' type="application/json"', "application/json"),
            (' type="importmap"', "importmap"),
            (' language="VBScript"', "text/vbscript"),
            (' type="text/template" language="JavaScript"', "text/template"),
            (' type="text/template" type="module"', "text/template"),
        ]:
            with self.subTest(attributes=attributes):
                # a script on line 2 with the text f(), which must not be written:
                self.assertEqual(
                    ([], [f"line 2: <script type={kind!r}>, not JavaScript"]),
                    script.page_code(f"<p>\n<script{attributes}>f();</script>\n"),
                )

    def test_script_start_in_a_skipped_script_is_no_error(self) -> None:
        """``<script`` in the text of a script that is not written is part of that text, not an error."""
        # a JSON script whose text holds <script>:
        self.assertEqual(
            ([], ["line 1: <script type='application/json'>, not JavaScript"]),
            script.page_code(
                '<script type="application/json">{"html": "<script>"}</script>\n'
            ),
        )

    def test_script_with_src_is_listed_only_with_inline_text(self) -> None:
        """The text of a ``<script src=...>`` is not written; the script is listed only if its text is not blank."""
        # a script with src and text on line 2, then scripts with src and an empty or a blank text:
        files, skipped = script.page_code(
            "<head>\n"
            '<script src="app.js">init();</script>\n'
            '<script src="lib.js"></script>\n'
            '<script src="util.js">\n'
            "</script>\n"
            "</head>\n"
        )
        # nothing is written, and only the script on line 2 is listed:
        self.assertEqual([], files)
        self.assertEqual(
            ["line 2: <script src=...>, browsers load the file instead"], skipped
        )

    def test_uppercase_tag_and_attribute_are_read_as_lowercase(self) -> None:
        """``<SCRIPT TYPE="MODULE">`` is a module script that ``</SCRIPT>`` closes, so its text is written."""
        # f() starts at column 22, after the start tag:
        self.assertEqual(
            ([" " * 22 + "f();\n"], []),
            script.page_code('<SCRIPT TYPE="MODULE">f();</SCRIPT>\n'),
        )


class PageErrorTest(unittest.TestCase):
    """Checks that markup which browsers may read differently from Python's parser raises a PageError, and that
    similar markup which browsers read the same way is written."""

    def test_markup_read_differently_by_browsers_fails(self) -> None:
        """Markup that browsers may read differently from Python's parser raises a PageError naming its line."""
        # the start of each message, as a regex; for <textarea>, it depends on the Python version:
        unread: str = re.escape(
            "<script that Python's parser did not read as a start tag"
        )
        foreign: str = re.escape("a <script> inside <svg> or <math>")
        # each page has the markup on line 2; the <script> in <textarea> is not closed, so that Python versions
        # before 3.12.12, which read it as a start tag, raise a PageError on line 2 as well:
        for case, page_text, message in [
            (
                "a <script> that is never closed",
                "<p>\n<script>f();\n",
                re.escape("a <script> that is never closed"),
            ),
            (
                "a self-closing <script/>",
                "<p>\n<script/>\n",
                re.escape("a self-closing <script/>"),
            ),
            (
                "a </script> without <script>",
                "<p>\n</script>\n",
                re.escape("a </script> while no <script> is open"),
            ),
            ("<script in a comment", "<p>\n<!-- <SCRIPT>f();</SCRIPT> -->\n", unread),
            ("<script in CDATA", "<p>\n<![CDATA[ <script>f();</script> ]]>\n", unread),
            (
                "<script in an attribute value",
                '<p>\n<a title="<script>f();</script>">x</a>\n',
                unread,
            ),
            (
                "<script in <textarea>",
                "<p>\n<textarea><script>f();</textarea>\n",
                f"({unread}|{re.escape('a <script> that is never closed')})",
            ),
            (
                "<script in <style> inside <svg>",
                "<svg><style>\n<script>f();</script>\n</style></svg>\n",
                unread,
            ),
            ("a <script> in <svg>", "<svg>\n<script>f();</script>\n</svg>\n", foreign),
            (
                "a <script> in <math>",
                "<math>\n<script>f();</script>\n</math>\n",
                foreign,
            ),
            (
                "a <script> in <svg> after a stray </math>",
                "<svg></math>\n<script>&#101;val(location.hash)</script>\n</svg>\n",
                foreign,
            ),
            (
                "a <script> in <svg> after a stray </svg>",
                "</svg><svg>\n<script>f();</script>\n</svg>\n",
                foreign,
            ),
            (
                "a <script> in an outer <svg> after </math> closed an inner <math>",
                "<svg><math></math>\n<script>f();</script>\n</svg>\n",
                foreign,
            ),
            (
                "a <script> in an outer <svg> after an inner <svg> closed",
                "<svg><svg></svg>\n<script>f();</script>\n</svg>\n",
                foreign,
            ),
        ]:
            with self.subTest(case=case):
                with self.assertRaisesRegex(script.PageError, "^line 2: " + message):
                    script.page_code(page_text)

    def test_script_start_after_a_comment_start_in_a_script_fails(self) -> None:
        """``<!--`` and then ``<script`` in a script's text raise a PageError, as browsers then skip a ``</script>``."""
        # browsers run the script up to the second </script>, including eval(x), while Python's parser ends it at
        # the first:
        with self.assertRaisesRegex(
            script.PageError, r"^line 6: a </script> while no <script> is open"
        ):
            script.page_code(
                "<script>\n<!--<script>\n</script>\neval(x)\n-->\n</script>\n"
            )

    def test_tag_named_like_script_and_escaped_text_are_no_error(self) -> None:
        """``&lt;script`` and an element such as ``<script-card>`` are no ``<script`` start, so the page is written."""
        # escaped text and a custom element on line 1, a script on line 2:
        self.assertEqual(
            (["\n        f();\n"], []),
            script.page_code(
                "<p>&lt;script&gt; <script-card></script-card></p>\n<script>f();</script>\n"
            ),
        )

    def test_script_start_in_a_script_text_is_written(self) -> None:
        """``<script`` in a script's own text, in any case and on any of its lines, is written as part of the text."""
        # a script on lines 2 and 3 whose strings hold <script> on its first line and <SCRIPT ...> on its second:
        self.assertEqual(
            (
                [
                    '\n        let a = "<script>";\n'
                    "  let b = \"<SCRIPT type='module'>\";\n\n"
                ],
                [],
            ),
            script.page_code(
                "<p>\n"
                '<script>let a = "<script>";\n'
                "  let b = \"<SCRIPT type='module'>\";\n"
                "</script>\n"
            ),
        )

    def test_script_after_a_closed_svg_is_written(self) -> None:
        """A ``<script>`` after ``</svg>`` is written, as browsers read it as an HTML script again."""
        # an SVG drawing on line 1 that is closed before the script on line 2:
        self.assertEqual(
            (["\n        draw();\n"], []),
            script.page_code(
                '<svg viewBox="0 0 10 10"><rect width="5" height="5"/></svg>\n'
                "<script>draw();</script>\n"
            ),
        )


class MainTest(unittest.TestCase):
    """Checks the command line of the script."""

    def test_writes_the_script_of_a_page_at_its_lines(self) -> None:
        """A page's inline JavaScript goes to ``OUTPUT_DIR/<page path>.1.js``, each line at its line in the page."""
        with tempfile.TemporaryDirectory() as directory:
            root: Path = Path(directory)
            # a page in the folder pages with a multi-line script whose text starts with a line break on line 5,
            # with a nosemgrep comment on line 6 for the eval on line 7:
            (root / "pages").mkdir()
            page: Path = write_page(
                root / "pages",
                "hello.html",
                "<!DOCTYPE html>\n"
                "<html>\n"
                "<body>\n"
                "<p>Hello</p>\n"
                "<script>\n"
                "  // nosemgrep: javascript.browser.security.eval-detected.eval-detected\n"
                "  eval(location.hash);\n"
                "</script>\n"
                "</body>\n"
                "</html>\n",
            )
            # run the script in the temporary directory with a relative page path, hiding its progress output:
            output: Path = root / "out"
            with contextlib.chdir(root), contextlib.redirect_stdout(io.StringIO()):
                status: int = script.main([str(output), str(page.relative_to(root))])
            # the script succeeds and writes out/pages/hello.html.1.js, keeping the page's folder; lines 6 and 7
            # are those of the page, so the nosemgrep comment stays right before its line; all other lines are
            # empty, also line 5 with <script> and line 8 with </script>:
            self.assertEqual(0, status)
            self.assertEqual(
                "\n\n\n\n\n"
                "  // nosemgrep: javascript.browser.security.eval-detected.eval-detected\n"
                "  eval(location.hash);\n"
                "\n",
                (output / "pages" / "hello.html.1.js").read_text(encoding="utf-8"),
            )

    def test_scripts_of_a_page_are_numbered_from_1(self) -> None:
        """The inline scripts of a page go to ``.1.js``, ``.2.js``, ... in page order; skipped scripts get no number."""
        with tempfile.TemporaryDirectory() as directory:
            # an inline script on line 1, a JSON script on line 2 and another inline script on line 3:
            page: Path = write_page(
                Path(directory),
                "two.html",
                "<script>a();</script>\n"
                '<script type="application/json">{"answer": 42}</script>\n'
                "<script>b();</script>\n",
            )
            output: Path = Path(directory) / "out"
            status, _, _ = run_main([str(output), str(page)])
            # the script succeeds and writes exactly two files, a() to the first and b() to the second:
            self.assertEqual(0, status)
            self.assertEqual(
                ["two.html.1.js", "two.html.2.js"],
                sorted(path.name for path in output.iterdir()),
            )
            self.assertEqual(
                "        a();\n", (output / "two.html.1.js").read_text(encoding="utf-8")
            )
            self.assertEqual(
                "\n\n        b();\n",
                (output / "two.html.2.js").read_text(encoding="utf-8"),
            )

    def test_page_with_only_skipped_scripts_gets_no_file(self) -> None:
        """A page whose only script is not written is listed as not scanned and without inline JavaScript."""
        with tempfile.TemporaryDirectory() as directory:
            # a page whose only script loads a file and has inline text, which browsers do not run:
            page: Path = write_page(
                Path(directory),
                "loader.html",
                '<head>\n<script src="app.js">init();</script>\n</head>\n',
            )
            output: Path = Path(directory) / "out"
            status, progress, _ = run_main([str(output), str(page)])
            # the script succeeds, lists the script on line 2 and the page, and creates no output directory:
            self.assertEqual(0, status)
            self.assertEqual(
                f"{page}: not scanned: line 2: <script src=...>, browsers load the file instead\n"
                f"{page}: no inline JavaScript\n",
                progress,
            )
            self.assertFalse(output.exists())

    def test_page_without_inline_javascript_does_not_stop_the_next_page(self) -> None:
        """After a page without inline JavaScript, the script goes on with the next page."""
        with tempfile.TemporaryDirectory() as directory:
            # a page without any script, then a page with one:
            first: Path = write_page(
                Path(directory), "plain.html", "<p>no script</p>\n"
            )
            second: Path = write_page(
                Path(directory), "app.html", "<script>b();</script>\n"
            )
            output: Path = Path(directory) / "out"
            status, _, _ = run_main([str(output), str(first), str(second)])
            # the script succeeds and writes the script of the second page:
            self.assertEqual(0, status)
            self.assertEqual(
                "        b();\n", (output / "app.html.1.js").read_text(encoding="utf-8")
            )

    def test_path_with_dot_dot_fails(self) -> None:
        """A relative page path with ``..`` stops the script with status 1, as it could leave the output directory."""
        with tempfile.TemporaryDirectory() as directory:
            root: Path = Path(directory)
            # a page next to the folder work, from which the script is run with the path ../page.html:
            write_page(root, "page.html", "<script>f();</script>\n")
            (root / "work").mkdir()
            with contextlib.chdir(root / "work"):
                status, _, errors = run_main(["out", "../page.html"])
            # the script fails, names the path, and writes nothing, not even the output directory:
            self.assertEqual(1, status)
            self.assertIn("../page.html: contains ..", errors)
            self.assertEqual([], list((root / "work").iterdir()))

    def test_page_error_fails_without_writing_a_file(self) -> None:
        """A page that raises a PageError stops the script with status 1, naming page and line; it gets no file."""
        with tempfile.TemporaryDirectory() as directory:
            # a valid script on line 1, then a script on line 3 that is commented out:
            page: Path = write_page(
                Path(directory),
                "broken.html",
                "<script>let ok = 1;</script>\n"
                "<p>\n"
                "<!-- <script>old();</script> -->\n",
            )
            output: Path = Path(directory) / "out"
            status, _, errors = run_main([str(output), str(page)])
            # the error names the page and line 3; not even the valid script is written:
            self.assertEqual(1, status)
            self.assertIn(f"{page}: line 3: ", errors)
            self.assertFalse(output.exists())

    def test_windows_and_old_mac_line_endings_keep_the_lines(self) -> None:
        """A page with ``\\r\\n`` or ``\\r`` line endings gets its code at the same lines, with ``\\n`` line endings."""
        for ending in ["\r\n", "\r"]:
            with self.subTest(ending=repr(ending)):
                with tempfile.TemporaryDirectory() as directory:
                    # a script on lines 3 and 4; newline="" writes the line endings unchanged:
                    page: Path = Path(directory) / "endings.html"
                    page.write_text(
                        ending.join(
                            [
                                "<p>Counter</p>",
                                "<p>",
                                "  <script>let a = 1;",
                                "  f(a);</script>",
                                "",
                            ]
                        ),
                        encoding="utf-8",
                        newline="",
                    )
                    output: Path = Path(directory) / "out"
                    status, _, _ = run_main([str(output), str(page)])
                    # the code is on lines 3 and 4, at the columns of the page, and no \r is left; the file is read
                    # as bytes, as reading it as text would turn \r into \n:
                    self.assertEqual(0, status)
                    self.assertEqual(
                        "\n\n          let a = 1;\n  f(a);\n",
                        (output / "endings.html.1.js").read_bytes().decode("utf-8"),
                    )

    def test_two_pages_for_the_same_file_fail(self) -> None:
        """If two pages would be written to the same file, the script stops with exit status 1."""
        with tempfile.TemporaryDirectory() as directory:
            # two pages with the same name in different folders, given as absolute paths; for an absolute path the
            # script keeps only the file name, so both would be written to out/same.html.1.js:
            pages: list[Path] = []
            for subdirectory, code in [("first", "a();"), ("second", "b();")]:
                (Path(directory) / subdirectory).mkdir()
                pages.append(
                    write_page(
                        Path(directory) / subdirectory,
                        "same.html",
                        f"<script>{code}</script>\n",
                    )
                )
            output: Path = Path(directory) / "out"
            status, _, errors = run_main([str(output), *map(str, pages)])
            # the second page stops the script with exit status 1 and an error message naming it; the file
            # written for the first page is kept:
            self.assertEqual(1, status)
            self.assertIn(
                f"{pages[1]}: {output / 'same.html.1.js'} exists already", errors
            )
            self.assertEqual(
                "        a();\n",
                (output / "same.html.1.js").read_text(encoding="utf-8"),
            )

    def test_html_and_htm_pages_of_the_same_name_do_not_clash(self) -> None:
        """Pages ``a.html`` and ``a.htm`` in one folder are written to ``a.html.1.js`` and ``a.htm.1.js``."""
        with tempfile.TemporaryDirectory() as directory:
            html: Path = write_page(
                Path(directory), "a.html", "<script>a();</script>\n"
            )
            htm: Path = write_page(Path(directory), "a.htm", "<script>b();</script>\n")
            output: Path = Path(directory) / "out"
            status, _, _ = run_main([str(output), str(html), str(htm)])
            # both pages get a file of their own:
            self.assertEqual(0, status)
            self.assertEqual(
                "        a();\n", (output / "a.html.1.js").read_text(encoding="utf-8")
            )
            self.assertEqual(
                "        b();\n", (output / "a.htm.1.js").read_text(encoding="utf-8")
            )

    def test_without_pages_writes_nothing(self) -> None:
        """With an output directory but no pages, the script writes nothing and succeeds."""
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(0, script.main([str(Path(directory) / "out")]))
            self.assertFalse((Path(directory) / "out").exists())

    def test_without_arguments_fails(self) -> None:
        """Without an output directory the script prints its usage and exits with status 2."""
        # the usage the script prints is its module docstring, which names OUTPUT_DIR:
        status, _, usage = run_main([])
        self.assertEqual(2, status)
        self.assertIn("OUTPUT_DIR", usage)


if __name__ == "__main__":
    unittest.main()
