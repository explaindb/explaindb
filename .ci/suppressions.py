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

"""List every line that Semgrep could read as a suppression, so that reviewers see each one.

A suppression is a comment that switches off a Semgrep finding; CONTRIBUTING.md (section *Static
analysis*) shows the one form that the CI job ``semgrep_sast`` (see ``.gitlab-ci.yml``) accepts.
The job lists every line that contains the word of a suppression for the reviewers, then rejects
each listed line that does not have this form, with ``grep -vE`` and a pattern of ASCII
characters only. Semgrep finds the word in any case, also with letters that Unicode case folding
turns into its letters, such as the long s ``ſ`` (U+017F) for ``s``, and also after a NUL byte in
the line. So the script searches with Python's ``re.IGNORECASE``, which folds letters like Semgrep
does, over the whole line; the ``grep -i`` and ``awk`` of the Semgrep image fold ASCII letters
only, and its ``grep`` stops reading a line at a NUL byte.

The job calls the script in two ways::

    git diff --text -U0 BASE HEAD -- '*.py' | python3 -I .ci/suppressions.py --diff
    python3 -I .ci/suppressions.py DIRECTORY

With ``--diff``, it reads a diff from its standard input and prints every added line inside a
hunk (a line that starts with ``+`` after ``@@``, so that a header line ``+++ b/<path>`` never
counts) that contains the word, as it stands in the diff. With a directory, it prints
``<path>:<line number>:<line>`` for every such line of every file below the directory, as
``grep -rin`` does.

Lines end at ``\\n`` only, as for ``git diff`` and ``grep``. A NUL byte is printed as ``\\x00``,
and a byte that is not part of UTF-8 text as ``\\xNN``: the form check allows no backslash, so it
rejects such a line, and reviewers see where the byte is.

The word itself does not appear in this file, as the job lists every added line of a changed
Python file that contains it, and this file is one of them.

Only the standard library is used, as the script runs in the Semgrep image.
"""

import re
import sys
from collections.abc import Iterable
from pathlib import Path

# the short form of the word of a suppression, which Semgrep accepts as well and with which the
# long form starts, written in two parts (see the module docstring); with IGNORECASE, a str
# pattern also matches letters that Unicode case folding turns into its letters, e.g. "ſ":
SUPPRESSION: re.Pattern[str] = re.compile("nos" + "em", re.IGNORECASE)


def is_suppression(line: str) -> bool:
    """Returns whether Semgrep could read a line as a suppression.

    @param line: a line of code, without its line break
    @return: True if the line contains the word of a suppression in any case
    """
    return SUPPRESSION.search(line) is not None


def printable(line: bytes) -> str:
    """Returns a line as text in which NUL bytes and bytes that are not UTF-8 are written as ``\\xNN``.

    @param line: a line, without its line break
    @return: the text of the line, without NUL characters
    """
    return line.decode("utf-8", errors="backslashreplace").replace("\0", "\\x00")


def diff_suppressions(diff: Iterable[bytes]) -> list[str]:
    """Returns the added lines of a diff that Semgrep could read as a suppression.

    @param diff: the lines of a diff as ``git diff`` writes it, each with or without its ``\\n``
    @return: every line inside a hunk that starts with ``+`` and is a suppression, as it stands in
    the diff, made printable
    """
    found: list[str] = []
    in_hunk: bool = False
    for raw in diff:
        line: bytes = raw.removesuffix(b"\n")
        # a file's header lines, among them "+++ b/<path>", come between "diff --git" and its
        # first hunk header "@@ ... @@", which is no line of the file either:
        if line.startswith(b"diff --git "):
            in_hunk = False
        elif line.startswith(b"@@"):
            in_hunk = True
        elif in_hunk and line.startswith(b"+"):
            text: str = printable(line)
            if is_suppression(text):
                found.append(text)
    return found


def directory_suppressions(directory: Path) -> list[str]:
    """Returns the lines of the files below a directory that Semgrep could read as a suppression.

    @param directory: the directory whose files, also in subdirectories, are searched
    @return: ``<path>:<line number>:<line>`` for each such line, made printable, the files in
    sorted order and the lines numbered from 1
    """
    found: list[str] = []
    for path in sorted(path for path in directory.rglob("*") if path.is_file()):
        for number, line in enumerate(path.read_bytes().split(b"\n"), start=1):
            text: str = printable(line)
            if is_suppression(text):
                found.append(f"{path}:{number}:{text}")
    return found


def main(arguments: list[str]) -> int:
    """Prints the suppressions of the diff on standard input, or of the files below a directory.

    @param arguments: ``--diff``, or the directory
    @return: the exit status: 0 on success, also if nothing is found, 1 if the directory does not
    exist, 2 on wrong arguments
    """
    if len(arguments) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    if arguments[0] == "--diff":
        found: list[str] = diff_suppressions(sys.stdin.buffer)
    else:
        directory: Path = Path(arguments[0])
        if not directory.is_dir():
            print(f"{directory}: no such directory", file=sys.stderr)
            return 1
        found = directory_suppressions(directory)
    # written as UTF-8 bytes, whatever the locale of the job; backslashreplace only matters for a
    # path that is not UTF-8:
    for text in found:
        sys.stdout.buffer.write(text.encode("utf-8", errors="backslashreplace") + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
