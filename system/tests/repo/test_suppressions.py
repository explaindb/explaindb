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
"""Tests for the CI helper ``.ci/suppressions.py`` that lists the Semgrep suppressions for the reviewers.

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
from unittest import mock

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
SCRIPT_PATH: Path = REPO_ROOT / ".ci" / "suppressions.py"
CI_CONFIG: Path = REPO_ROOT / ".gitlab-ci.yml"

# a rule ID as the job log names it:
RULE: str = "python.lang.security.audit.eval-detected.eval-detected"
# the long s, which Semgrep reads as "s" when it looks for a suppression in any case:
LONG_S: str = "\u017f"


def load_script() -> ModuleType:
    """Loads ``.ci/suppressions.py`` as a module."""
    spec = importlib.util.spec_from_file_location("suppressions", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script: ModuleType = load_script()


def run_main(arguments: list[str], stdin: bytes = b"") -> tuple[int, bytes, str]:
    """Runs the script's ``main`` with the given arguments and standard input.

    @param arguments: the command line arguments
    @param stdin: the bytes on standard input
    @return: the exit status, the bytes on standard output and the text on standard error
    """
    # the script writes bytes to sys.stdout.buffer, here this BytesIO:
    written: io.BytesIO = io.BytesIO()
    output: io.TextIOWrapper = io.TextIOWrapper(written, encoding="utf-8")
    errors: io.StringIO = io.StringIO()
    with (
        mock.patch("sys.stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")),
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(errors),
    ):
        status: int = script.main(arguments)
    output.flush()
    return status, written.getvalue(), errors.getvalue()


def diff(path: str, added: list[bytes]) -> bytes:
    """Returns a diff as ``git diff -U0`` writes it for a new file with the given lines.

    @param path: the path of the new file; its header lines contain it
    @param added: the lines of the file, without line breaks
    @return: the diff, with a line break after every line
    """
    header: list[bytes] = [
        f"diff --git a/{path} b/{path}".encode(),
        b"new file mode 100644",
        b"index 0000000..1111111",
        b"--- /dev/null",
        f"+++ b/{path}".encode(),
        f"@@ -0,0 +1,{len(added)} @@".encode(),
    ]
    return b"".join(line + b"\n" for line in header + [b"+" + line for line in added])


def form_checks() -> dict[str, str]:
    """Returns the form checks of the job ``semgrep_sast``: the pattern of each ``grep -vE``, by the file it reads.

    @return: the pattern for ``/tmp/suppressions`` (Python files), ``/tmp/notebook_suppressions`` and
    ``/tmp/html_suppressions``
    """
    text: str = CI_CONFIG.read_text(encoding="utf-8")
    found: list[tuple[str, str]] = re.findall(r"grep -vE '([^']+)' (/tmp/\w+)", text)
    checks: dict[str, str] = {file: pattern for pattern, file in found}
    # each file is checked only once, so that no check is lost in the dictionary:
    assert len(checks) == len(found), found
    return checks


def rejected(pattern: str, listing: bytes) -> bytes:
    """Returns the lines of a listing that a form check rejects, as the job runs it (``grep -vE``).

    @param pattern: the pattern of the form check
    @param listing: the output of the script
    @return: the rejected lines; empty if every line has the form
    """
    result: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["grep", "-vE", pattern], input=listing, capture_output=True, check=False
    )
    # grep exits with 0 if it printed a line, with 1 if not, and with 2 on an error, e.g. a broken pattern:
    assert result.returncode in (0, 1), result.stderr
    return result.stdout


class SuppressionTest(unittest.TestCase):
    """Checks which lines count as a suppression: those that Semgrep could read as one."""

    def test_word_in_any_case_counts(self) -> None:
        """A line counts if it contains ``nosem`` in any case, also inside other text."""
        for line in [
            f"# nosemgrep: {RULE}",
            "x = 1  # NOSEMGREP",
            "// NoSem",
            "s = 'nosemgrep'",
        ]:
            with self.subTest(line=line):
                self.assertTrue(script.is_suppression(line))

    def test_long_s_counts(self) -> None:
        """A line counts if it contains the long s ``ſ`` instead of ``s``, as Semgrep folds it to ``s``."""
        self.assertTrue(script.is_suppression(f"x = 1  # no{LONG_S}emgrep"))
        self.assertTrue(script.is_suppression(f"// NO{LONG_S}EMGREP: {RULE}"))

    def test_other_lines_do_not_count(self) -> None:
        """A line without the word does not count, nor does one with letters that Semgrep does not fold to it."""
        for line in [
            "x = eval(input())",
            "# nose, semgrep",
            # full-width letters and a soft hyphen inside the word:
            "# \uff4e\uff4f\uff53\uff45\uff4d\uff47\uff52\uff45\uff50",
            "# nos\u00ademgrep",
        ]:
            with self.subTest(line=line):
                self.assertFalse(script.is_suppression(line))


class PrintableTest(unittest.TestCase):
    """Checks how a line is turned into text for the listing."""

    def test_utf8_text_is_kept(self) -> None:
        """A line in UTF-8 keeps its characters, also tabs, carriage returns and non-ASCII letters."""
        self.assertEqual(
            f"\t# no{LONG_S}emgrep\r",
            script.printable(f"\t# no{LONG_S}emgrep\r".encode()),
        )

    def test_nul_and_bytes_that_are_not_utf8_are_written_as_escapes(self) -> None:
        """A NUL byte becomes ``\\x00`` and a byte that is not UTF-8 ``\\xNN``, so the text has no NUL."""
        text: str = script.printable(b"# nosemgrep: rule\x00 eval(x) \xff")
        self.assertEqual("# nosemgrep: rule\\x00 eval(x) \\xff", text)
        self.assertNotIn("\0", text)


class DiffTest(unittest.TestCase):
    """Checks which lines of a diff are listed."""

    def test_added_lines_with_a_suppression_are_listed(self) -> None:
        """The added lines that contain a suppression are listed as they stand in the diff, with their ``+``."""
        # a new file with a line of code, an indented suppression and one with the long s at the end of a line:
        listed: list[str] = script.diff_suppressions(
            io.BytesIO(
                diff(
                    "a.py",
                    [
                        b"x = 1",
                        f"    # nosemgrep: {RULE}".encode(),
                        f"eval(x)  # no{LONG_S}emgrep".encode(),
                    ],
                )
            )
        )
        # both suppressions are listed, the line of code is not:
        self.assertEqual(
            [f"+    # nosemgrep: {RULE}", f"+eval(x)  # no{LONG_S}emgrep"], listed
        )

    def test_text_after_a_nul_byte_is_searched(self) -> None:
        """An added line with a suppression after a NUL byte is listed, with ``\\x00`` for the NUL."""
        listed: list[str] = script.diff_suppressions(
            io.BytesIO(diff("a.py", [b"eval(x)  # \x00 nosemgrep"]))
        )
        self.assertEqual(["+eval(x)  # \\x00 nosemgrep"], listed)

    def test_headers_and_removed_lines_are_not_listed(self) -> None:
        """Only added lines inside a hunk count: never the file's header lines, nor removed lines.

        The header ``+++ b/<path>`` starts with ``+`` like an added line; it comes before the first ``@@`` of its
        file, also after the hunk of a file before it.
        """
        # two files whose paths contain the word: the first one with a removed and an added suppression, the
        # second one only with code:
        changed: bytes = (
            b"diff --git a/nosemgrep.py b/nosemgrep.py\n"
            b"index 1111111..2222222 100644\n"
            b"--- a/nosemgrep.py\n"
            b"+++ b/nosemgrep.py\n"
            b"@@ -3 +3 @@\n"
            b"-# nosemgrep: old-rule\n"
            b"+# nosemgrep: new-rule\n"
        ) + diff("NOSEM/b.py", [b"x = 1"])
        # only the added suppression of the first file is listed:
        self.assertEqual(
            ["+# nosemgrep: new-rule"],
            script.diff_suppressions(io.BytesIO(changed)),
        )

    def test_added_line_that_starts_with_plus_signs_is_listed(self) -> None:
        """An added line ``++ b/<path>`` stands in the diff exactly like a header, ``+++ b/<path>``, and is listed."""
        listed: list[str] = script.diff_suppressions(
            io.BytesIO(diff("a.py", [b"++ b/x.py  # nosemgrep"]))
        )
        self.assertEqual(["+++ b/x.py  # nosemgrep"], listed)

    def test_lines_are_split_at_line_feeds_only(self) -> None:
        """A carriage return or another line separator does not end a line, as in ``git diff`` and ``grep``."""
        listed: list[str] = script.diff_suppressions(
            io.BytesIO(diff("a.py", ["x = 1\r# nosemgrep\u2028y = 2".encode()]))
        )
        self.assertEqual(["+x = 1\r# nosemgrep\u2028y = 2"], listed)


class DirectoryTest(unittest.TestCase):
    """Checks which lines of the files below a directory are listed."""

    def test_lines_are_listed_with_path_and_line_number(self) -> None:
        """Each line with a suppression is listed as ``<path>:<line number>:<line>``, files in sorted order."""
        with tempfile.TemporaryDirectory() as directory:
            root: Path = Path(directory)
            # a file in a subfolder with a suppression on line 2, and a file at the top level of the directory, after
            # it in sorted order, with a suppression in capitals on line 1 and one with the long s on line 3:
            (root / "pages").mkdir()
            (root / "pages" / "b.js").write_bytes(
                f"f();\n// nosemgrep: {RULE}\neval(x);\n".encode()
            )
            (root / "z.py").write_bytes(
                f"# NOSEMGREP\nx = 1\neval(x)  # no{LONG_S}emgrep\n".encode()
            )
            # the subfolder's file comes first, as pages/b.js sorts before z.py:
            self.assertEqual(
                [
                    f"{root / 'pages' / 'b.js'}:2:// nosemgrep: {RULE}",
                    f"{root / 'z.py'}:1:# NOSEMGREP",
                    f"{root / 'z.py'}:3:eval(x)  # no{LONG_S}emgrep",
                ],
                script.directory_suppressions(root),
            )

    def test_line_numbers_count_line_feeds_only(self) -> None:
        """Line numbers count ``\\n`` only, as ``grep -n`` does; a NUL byte is written as ``\\x00``."""
        with tempfile.TemporaryDirectory() as directory:
            root: Path = Path(directory)
            # a carriage return and a form feed on line 1, which do not end the line, and a suppression after a NUL
            # byte on line 2:
            (root / "a.js").write_bytes(b"f();\rg();\x0c\neval(x); // \x00 nosemgrep\n")
            self.assertEqual(
                [f"{root / 'a.js'}:2:eval(x); // \\x00 nosemgrep"],
                script.directory_suppressions(root),
            )


class FormCheckTest(unittest.TestCase):
    """Checks the listing against the form checks of the job ``semgrep_sast`` (``grep -vE`` in ``.gitlab-ci.yml``).

    Each listed line must be a comment line of its own that names a rule; the check prints every other line.
    """

    def test_job_checks_the_listings_of_this_script(self) -> None:
        """The job checks the suppressions of Python files, notebooks and HTML pages, each listed by this script.

        The Python files are read from ``git diff --text``, so that a file with a NUL byte is not taken for a
        binary file, whose lines ``git diff`` would not show.
        """
        text: str = CI_CONFIG.read_text(encoding="utf-8")
        # the script writes each listing, from the diff or from the directory of the converted code; -I keeps a
        # module in .ci/ from replacing one of the standard library:
        listings: dict[str, str] = {
            file: source
            for source, file in re.findall(
                r"python3 -I \.ci/suppressions\.py (\S+) > (/tmp/\w+)", text
            )
        }
        self.assertEqual(
            {
                "/tmp/suppressions": "--diff",
                "/tmp/notebook_suppressions": "/tmp/notebook_code",
                "/tmp/html_suppressions": "/tmp/html_scripts",
            },
            listings,
        )
        # a form check reads each of these listings, and no other file:
        self.assertEqual(set(listings), set(form_checks()))
        # the diff of the Python files reaches the script with --text:
        self.assertRegex(
            text,
            r"git diff --text -U0 [^\n|]*\| python3 -I \.ci/suppressions\.py --diff",
        )
        # no listing is made with grep or awk, which fold ASCII letters only:
        self.assertNotRegex(text, r"grep -\w*r\w* ['\"]?nosem|tolower")

    def test_suppressions_in_the_form_pass(self) -> None:
        """A suppression in the form, on a line of its own and indented or not, passes all three checks."""
        checks: dict[str, str] = form_checks()
        # a Python file in a diff, with an indented suppression, is listed and passes:
        status, listing, _ = run_main(
            ["--diff"], diff("a.py", [f"    # nosemgrep: {RULE}".encode()])
        )
        self.assertEqual(0, status)
        self.assertEqual(f"+    # nosemgrep: {RULE}\n".encode(), listing)
        self.assertEqual(b"", rejected(checks["/tmp/suppressions"], listing))
        # the converted code of a notebook and the JavaScript of an HTML page, written to files, are listed and pass:
        for file, line in [
            ("/tmp/notebook_suppressions", f"# nosemgrep: {RULE}"),
            ("/tmp/html_suppressions", f"  // nosemgrep: {RULE}"),
        ]:
            with self.subTest(file=file), tempfile.TemporaryDirectory() as directory:
                (Path(directory) / "code").write_text(
                    f"{line}\neval(x)\n", encoding="utf-8"
                )
                status, listing, _ = run_main([directory])
                self.assertEqual(0, status)
                self.assertEqual(
                    f"{Path(directory) / 'code'}:1:{line}\n".encode(), listing
                )
                self.assertEqual(b"", rejected(checks[file], listing))

    def test_other_spellings_and_bytes_are_rejected(self) -> None:
        """Lines that are not in the form are listed, and all three checks reject each of them.

        Among them are the long s and a suppression in the form followed by a NUL byte and code, both of which Semgrep
        honours: if the listing missed such a line or cut it at the NUL, the checks would let it through.
        """
        checks: dict[str, str] = form_checks()
        # a Python file in a diff, and the converted code of a notebook or the JavaScript of an HTML page in a file:
        for file, comment in [
            ("/tmp/suppressions", "#"),
            ("/tmp/notebook_suppressions", "#"),
            ("/tmp/html_suppressions", "//"),
        ]:
            # the long s, a NUL byte, a byte that is not UTF-8, no rule, a suppression after code, capitals:
            lines: list[bytes] = [
                f"{comment} no{LONG_S}emgrep: {RULE}".encode(),
                f"{comment} nosemgrep: {RULE}".encode() + b"\x00 eval(x)",
                f"{comment} nosemgrep: {RULE}".encode() + b"\xff",
                f"{comment} nosemgrep".encode(),
                f"eval(x)  {comment} nosemgrep: {RULE}".encode(),
                f"{comment} NOSEMGREP: {RULE}".encode(),
            ]
            with self.subTest(file=file), tempfile.TemporaryDirectory() as directory:
                if file == "/tmp/suppressions":
                    listing: bytes = run_main(["--diff"], diff("a.py", lines))[1]
                else:
                    (Path(directory) / "code").write_bytes(b"\n".join(lines) + b"\n")
                    listing = run_main([directory])[1]
                # every line is listed, without a NUL byte, and the check rejects (prints) every listed line:
                self.assertEqual(len(lines), listing.count(b"\n"))
                self.assertNotIn(b"\x00", listing)
                self.assertEqual(listing, rejected(checks[file], listing))


class MainTest(unittest.TestCase):
    """Checks the command line of the script."""

    def test_diff_on_standard_input_is_listed(self) -> None:
        """With ``--diff``, the suppressions of the diff on standard input are printed, one per line, in UTF-8."""
        status, output, _ = run_main(
            ["--diff"], diff("a.py", [f"x  # no{LONG_S}emgrep".encode(), b"y = 2"])
        )
        self.assertEqual(0, status)
        self.assertEqual(f"+x  # no{LONG_S}emgrep\n".encode(), output)

    def test_nothing_found_prints_nothing_and_succeeds(self) -> None:
        """Without suppressions, the script prints nothing and exits with status 0."""
        self.assertEqual((0, b"", ""), run_main(["--diff"], diff("a.py", [b"x = 1"])))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual((0, b"", ""), run_main([directory]))

    def test_missing_directory_fails(self) -> None:
        """A directory that does not exist fails with status 1, so that no suppression goes unlisted unnoticed."""
        with tempfile.TemporaryDirectory() as directory:
            status, output, errors = run_main([str(Path(directory) / "missing")])
        self.assertEqual(1, status)
        self.assertEqual(b"", output)
        self.assertIn("missing", errors)

    def test_wrong_arguments_fail(self) -> None:
        """Without an argument or with more than one, the script prints its usage and exits with status 2."""
        for arguments in [[], ["--diff", "dir"]]:
            with self.subTest(arguments=arguments):
                status, _, usage = run_main(arguments)
                self.assertEqual(2, status)
                self.assertIn("--diff", usage)


if __name__ == "__main__":
    unittest.main()
