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

"""Write the inline JavaScript of HTML pages as JavaScript files, so that Semgrep can scan it.

Semgrep applies only its HTML rules to ``.html`` files, never its JavaScript rules to the text of
a ``<script>`` element. The CI job ``semgrep_sast`` (see ``.gitlab-ci.yml``) therefore calls this
script with an output directory and the HTML pages a merge request changes::

    python3 .ci/html_scripts.py OUTPUT_DIR PAGE.html [PAGE.html ...]

For the n-th inline JavaScript ``<script>`` of a page it writes
``OUTPUT_DIR/<path of the page>.<n>.js``: the script's text at its line and column in the page,
all other lines empty, so that the line and column of a finding are those in the page. Each
script gets a file of its own, as browsers run each on its own. A page without inline JavaScript
gets no file.

A ``<script>`` counts as JavaScript as in the HTML specification: without ``type`` and
``language``, with an empty ``type``, with a ``type`` that is one of ``JAVASCRIPT_TYPES`` or
``module`` (without case and surrounding spaces), or, without ``type``, with an empty
``language`` or one that makes ``text/<language>`` such a type. A duplicate attribute counts
only the first time, as in browsers. Browsers do not run the text of a ``<script>`` with ``src``.
Every ``<script>`` with non-blank text that is not written is listed, so that reviewers see what
is not scanned.

The scan catches honest mistakes; like Semgrep's rules, it is no defence against code that is
hidden on purpose. Where Python's parser could read a page differently from a browser, so that a
script could drop out of the scan unnoticed, the script stops with an error instead:

- on ``<script`` that Python's parser does not read as a start tag, e.g. in a comment or in a
  ``<style>`` inside ``<svg>``, where browsers may run it (write ``&lt;script`` in such text);
- on a ``<script>`` that is never closed: the page is broken, and browsers do not run it;
- on a self-closing ``<script/>``: browsers ignore the slash, so the text after it, up to the next
  ``</script>``, belongs to the script;
- on a ``</script>`` while no ``<script>`` is open, e.g. after ``<!--`` and ``<script`` in a
  script's text, where browsers ignore the first ``</script>``;
- on a ``<script>`` inside ``<svg>`` or ``<math>``: there browsers may read or run it differently
  (directly inside ``<svg>`` they decode character references such as ``&quot;`` in its text).

Not caught: deliberate tricks that hide an ``<svg>`` from Python's parser (e.g. in an unusual
comment) or keep it open in browsers (e.g. with ``<desc>`` or ``<foreignObject>``), pages in an
encoding other than UTF-8, and differences in the parser of Python versions before 3.12.12.

Not extracted: inline event handlers (``onclick="..."``), ``javascript:`` URLs and
``<iframe srcdoc="...">``.

Only the standard library is used, as the script runs in the Semgrep image.
"""

import bisect
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

# the JavaScript MIME types of the HTML specification ("JavaScript MIME type essence match"):
JAVASCRIPT_TYPES: frozenset[str] = frozenset(
    {
        "application/ecmascript",
        "application/javascript",
        "application/x-ecmascript",
        "application/x-javascript",
        "text/ecmascript",
        "text/javascript",
        "text/javascript1.0",
        "text/javascript1.1",
        "text/javascript1.2",
        "text/javascript1.3",
        "text/javascript1.4",
        "text/javascript1.5",
        "text/jscript",
        "text/livescript",
        "text/x-ecmascript",
        "text/x-javascript",
    }
)
# the elements inside which browsers do not read a <script> as an HTML script:
FOREIGN_ELEMENTS: frozenset[str] = frozenset({"svg", "math"})
# what browsers read as the start of a <script> tag, in any case:
SCRIPT_START: re.Pattern[str] = re.compile(
    r"<script[\t\n\f\r />]", re.IGNORECASE | re.ASCII
)


class PageError(Exception):
    """A page whose inline JavaScript cannot be written so that it matches what a browser runs."""


@dataclass
class Script:
    """The text of one ``<script>`` element and where it starts in its page."""

    line: int  # the line of the first character of the text, counted from 1
    column: int  # the column of the first character of the text, counted from 0
    text: str
    skip_reason: str | None  # why it is not written, None if it is inline JavaScript

    def position(self, offset: int) -> tuple[int, int]:
        """Returns the line and column in the page of the character at <offset> in the text."""
        before: str = self.text[:offset]
        if "\n" not in before:
            return self.line, self.column + offset
        return self.line + before.count("\n"), offset - before.rindex("\n") - 1


def non_javascript_type(attributes: list[tuple[str, str | None]]) -> str | None:
    """Returns the type of a ``<script>`` with these attributes if it is not JavaScript.

    @param attributes: the attributes of the start tag, in order, as ``html.parser`` gives them
    @return: None if the script is JavaScript, otherwise the type a browser sees (e.g.
    ``application/json``)
    """
    first: dict[str, str] = {}
    for name, value in attributes:
        first.setdefault(name, value or "")
    if "type" in first:
        kind: str = first["type"].strip().lower()
    elif first.get("language", ""):
        kind = "text/" + first["language"].strip().lower()
    else:
        return None
    return None if kind in ("", "module") or kind in JAVASCRIPT_TYPES else kind


class ScriptCollector(HTMLParser):
    """Collects the ``<script>`` elements of a page and the positions of their start tags."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[Script] = []
        # the line and column of every <script> start tag:
        self.start_tags: set[tuple[int, int]] = set()
        # the open <script>: the line of its start tag (None if no <script> is open), why it is
        # not written, the parts of its text so far, and the line and column of its first
        # character:
        self.open_line: int | None = None
        self.skip_reason: str | None = None
        self.parts: list[str] = []
        self.start: tuple[int, int] | None = None
        # how many <svg> and <math> elements are open around the current position:
        self.foreign: dict[str, int] = {tag: 0 for tag in FOREIGN_ELEMENTS}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Opens a ``<script>``, ``<svg>`` or ``<math>``.

        Rejects a ``<script>`` inside ``<svg>`` or ``<math>``.
        """
        if tag in FOREIGN_ELEMENTS:
            self.foreign[tag] += 1
        if tag != "script":
            return
        line: int = self.getpos()[0]
        if any(self.foreign.values()):
            raise PageError(
                f"line {line}: a <script> inside <svg> or <math>; browsers may read or run it "
                "differently there (directly inside <svg> they decode character references such "
                "as &quot; in its text); move it out"
            )
        self.start_tags.add(self.getpos())
        kind: str | None = non_javascript_type(attrs)
        self.open_line = line
        self.parts = []
        self.start = None
        if any(name == "src" for name, _ in attrs):
            self.skip_reason = (
                f"line {line}: <script src=...>, browsers load the file instead"
            )
        elif kind is not None:
            self.skip_reason = f"line {line}: <script type={kind!r}>, not JavaScript"
        else:
            self.skip_reason = None

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Rejects a self-closing ``<script/>``, which browsers treat as a start tag."""
        if tag == "script":
            raise PageError(
                f"line {self.getpos()[0]}: a self-closing <script/>; browsers ignore the slash, "
                "so the text after it, up to the next </script>, belongs to the script; write "
                "<script ...></script>"
            )

    def handle_data(self, data: str) -> None:
        """Collects the text of an open ``<script>``."""
        if self.open_line is not None:
            if self.start is None:
                self.start = self.getpos()
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Closes a ``<script>``, ``<svg>`` or ``<math>``.

        Rejects a ``</script>`` while no ``<script>`` is open.
        """
        if tag in FOREIGN_ELEMENTS and self.foreign[tag]:
            self.foreign[tag] -= 1
        if tag != "script":
            return
        if self.open_line is None:
            raise PageError(
                f"line {self.getpos()[0]}: a </script> while no <script> is open; Python's parser "
                "and browsers may read the markup before it differently"
            )
        if self.start is not None:
            self.scripts.append(
                Script(*self.start, "".join(self.parts), self.skip_reason)
            )
        self.open_line = None


def page_code(text: str) -> tuple[list[str], list[str]]:
    """Returns the inline JavaScript of a page as JavaScript files, and what it skipped.

    @param text: the text of the HTML page, with ``\\n`` as line ending
    @return: the text of one file per inline JavaScript ``<script>``, in order (none if the page has
    no inline JavaScript), and one line per ``<script>`` with non-blank text that is not written
    @raise PageError: if the result could differ from what a browser runs
    """
    collector: ScriptCollector = ScriptCollector()
    collector.feed(text)
    collector.close()
    if collector.open_line is not None:
        raise PageError(
            f"line {collector.open_line}: a <script> that is never closed; the page is broken, "
            "and browsers do not run it"
        )
    # every "<script" of the page must be a start tag the parser read, or text inside a script:
    known: set[tuple[int, int]] = collector.start_tags | {
        script.position(match.start())
        for script in collector.scripts
        for match in SCRIPT_START.finditer(script.text)
    }
    # the line (from 1) and column (from 0) of each "<script" in the page, as getpos() counts them:
    line_starts: list[int] = [0] + [
        i + 1 for i, char in enumerate(text) if char == "\n"
    ]
    for match in SCRIPT_START.finditer(text):
        line: int = bisect.bisect_right(line_starts, match.start())
        if (line, match.start() - line_starts[line - 1]) not in known:
            raise PageError(
                f"line {line}: <script that Python's parser did not read as a start tag (e.g. in "
                "a comment, or in <style> inside <svg>); browsers may run it; write &lt;script "
                "if it is meant as text"
            )
    files: list[str] = []
    for script in collector.scripts:
        if script.skip_reason is None:
            text_lines: list[str] = script.text.split("\n")
            # the first line keeps its column; a blank first line (e.g. a line break right after
            # <script>) stays empty:
            first: str = text_lines[0]
            lines: list[str] = [""] * (script.line - 1)
            lines.append(" " * script.column + first if first.strip() else "")
            files.append("\n".join(lines + text_lines[1:]) + "\n")
    skipped: list[str] = [
        script.skip_reason
        for script in collector.scripts
        if script.skip_reason is not None and script.text.strip()
    ]
    return files, skipped


def main(arguments: list[str]) -> int:
    """Writes the inline JavaScript of every given page to the output directory.

    A relative page path keeps its folders below the output directory (an absolute one only its file
    name), so that pages with the same name in different folders do not overwrite each other; if two
    pages would still be written to the same files, or a relative path contains ``..`` and so could
    be written outside the output directory, the script stops with an error.

    @param arguments: the output directory, then the page paths
    @return: the exit status: 0 on success, 1 if a page cannot be written as a browser would run
    it, two pages map to the same files or a relative path contains ``..``, 2 on missing arguments
    """
    if len(arguments) < 1:
        print(__doc__, file=sys.stderr)
        return 2
    output_dir: Path = Path(arguments[0])
    for name in arguments[1:]:
        page: Path = Path(name)
        relative: Path = Path(page.name) if page.is_absolute() else page
        if ".." in relative.parts:
            print(
                f"{page}: contains .., so it could be written outside {output_dir}",
                file=sys.stderr,
            )
            return 1
        prefix: str = str(output_dir / relative)
        if Path(f"{prefix}.1.js").exists():
            print(f"{page}: {prefix}.1.js exists already", file=sys.stderr)
            return 1
        try:
            # read_text turns \r\n and \r into \n, so that lines are counted as in the page:
            files, skipped = page_code(page.read_text(encoding="utf-8"))
        except PageError as error:
            print(f"{page}: {error}", file=sys.stderr)
            return 1
        for reason in skipped:
            print(f"{page}: not scanned: {reason}")
        if not files:
            print(f"{page}: no inline JavaScript")
        for number, code in enumerate(files, start=1):
            target: Path = Path(f"{prefix}.{number}.js")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8")
            print(f"{page} -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
