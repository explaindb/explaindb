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
"""Tests that the project logo in ``docs/images/logo/`` is safe to embed and that the README shows it.

The logo is a wordmark in two SVGs, ``explaindb-logo-light.svg`` for light and ``explaindb-logo-dark.svg`` for dark
backgrounds, each on its own background; the README shows them in a ``<picture>``, which picks the one that fits the
reader's theme. The avatar ``explaindb-avatar.png`` is exported from ``explaindb-avatar.svg``.

These tests fail if one of the three SVGs uses an element or an attribute outside the few that the flat drawings
need (so nothing that can run code or load other files, such as a script, a style sheet, embedded HTML, an image or
a link); a ``<title>`` or ``<desc>`` with an element inside; a colour that is not ``none`` or a hex colour ``#rgb``
or ``#rrggbb``; an attribute value with ``url(`` (a reference to a gradient or another file) or a backslash (a CSS
escape); a document type declaration, a CDATA section, a processing instruction other than a leading XML
declaration, an encoding other than UTF-8 in that declaration or a comment that starts with ``>`` or ``->``; or no
``viewBox``. They fail if the avatar PNG is not 512 × 512, and if the README does not show the logo above its
title: no ``<img>`` before the first ``# `` line; an ``<img>`` that is not the light logo or has a ``srcset``;
``<source>`` tags other than exactly one with the dark logo for a dark theme, in the ``<picture>`` of the ``<img>``
and before it; no blank line between the HTML block and the title (without it the title shows as plain text); an
image path (the ``src`` of the ``<img>`` or the ``srcset`` of a ``<source>``) that is absolute, leads out of the
repository or does not name a file with exactly this letter case; a ``srcset`` with more than one path or with a
size or density after the path; or an alt text that is empty or a placeholder.

They cannot tell whether the PNG still shows the same picture as the avatar SVG, or whether the light logo, the
dark logo and the avatar show the same robot: after changing the avatar SVG, export the PNG again with the
``rsvg-convert`` command in its header comment. They do not check how the README looks when rendered either.
"""

import re
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

# Anchored to this test file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
README_PATH: Path = REPO_ROOT / "README.md"
LOGO_DIR: Path = REPO_ROOT / "docs" / "images" / "logo"
PNG_PATH: Path = LOGO_DIR / "explaindb-avatar.png"

# The SVGs: the logo for light and for dark backgrounds, and the avatar that the PNG is exported from.
SVG_PATHS: tuple[Path, ...] = (
    LOGO_DIR / "explaindb-logo-light.svg",
    LOGO_DIR / "explaindb-logo-dark.svg",
    LOGO_DIR / "explaindb-avatar.svg",
)

# The condition under which the README's <picture> shows the dark logo:
DARK_MEDIA: str = "(prefers-color-scheme: dark)"

SVG_NAMESPACE: str = "http://www.w3.org/2000/svg"

# The elements the logos may use, all in the SVG namespace: shapes, groups, a title and a description. Any other
# element is a problem, also those that run code (script, set, animate), style the drawing from a style sheet
# (style) or embed HTML or other files (foreignObject, image, use):
ALLOWED_ELEMENTS: frozenset[str] = frozenset(
    {
        "svg",
        "g",
        "rect",
        "ellipse",
        "circle",
        "polygon",
        "path",
        "line",
        "title",
        "desc",
    }
)

# The attributes the logos may use, all without a namespace: the size and accessible name of the drawing,
# placement, colours, opacity and line style, and the geometry of the shapes. Any other attribute is a problem,
# also event handlers (onload), links (href, xlink:href) and inline style sheets (style):
ALLOWED_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "viewBox",
        "width",
        "height",
        "role",
        "aria-label",
        "transform",
        "fill",
        "opacity",
        "stroke",
        "stroke-width",
        "stroke-linecap",
        "stroke-linejoin",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "d",
        "points",
    }
)

# The attributes that hold a colour, and the values they may have: none or a hex colour #rgb or #rrggbb.
COLOUR_ATTRIBUTES: frozenset[str] = frozenset({"fill", "stroke"})
COLOUR_PATTERN: re.Pattern[str] = re.compile(r"none|#(?:[0-9a-fA-F]{3}){1,2}")

# The elements that hold plain text only, no other element:
TEXT_ONLY_ELEMENTS: frozenset[str] = frozenset({"title", "desc"})

# The only processing instruction an SVG may have: an XML declaration at the very start, e.g. <?xml version="1.0"?>,
# and the encoding it declares, e.g. encoding="UTF-8":
XML_DECLARATION: re.Pattern[str] = re.compile(r"<\?xml\s[^>]*\?>")
DECLARED_ENCODING: re.Pattern[str] = re.compile(
    r"""\sencoding\s*=\s*["']([^"']*)["']"""
)

# Every PNG file starts with these 8 bytes.
PNG_SIGNATURE: bytes = b"\x89PNG\r\n\x1a\n"

# Alt texts that say nothing about the image, compared stripped and in lower case; "…" and "..." are what
# an example in the documentation would write.
PLACEHOLDER_ALTS: frozenset[str] = frozenset({"", "logo", "image", "…", "..."})


def shown_tag(tag: str) -> str:
    """Return a tag name as the messages show it: without the namespace if that is the SVG namespace.

    ``ElementTree`` writes a name in a namespace as ``{namespace}name``, e.g. the SVG element ``script`` as
    ``{http://www.w3.org/2000/svg}script``. A name in another namespace keeps it, so that an XHTML ``div`` does not
    look like an SVG element.

    @param tag: the tag as ``ElementTree`` gives it.
    @return: e.g. ``"script"`` or ``"{http://www.w3.org/1999/xhtml}div"``.
    """
    return tag.removeprefix(f"{{{SVG_NAMESPACE}}}")


def text_problems(text: str) -> list[str]:
    """Return the problems of an SVG that only its text shows, because ``ElementTree`` hides these parts.

    They are ``<!DOCTYPE``, a CDATA section, a processing instruction other than an XML declaration at the very
    start, an encoding other than UTF-8 in that declaration, and a comment that starts with ``>`` or ``->``;
    :func:`svg_problems` says why each is a problem. The text is searched as it is, so a match inside a comment
    counts as well.

    @param text: the content of the SVG file.
    @return: one message per problem; empty if there is none.
    """
    # no document type declaration and no CDATA section:
    problems: list[str] = []
    if "<!DOCTYPE" in text:
        problems.append("a document type declaration <!DOCTYPE …>")
    if "<![CDATA[" in text:
        problems.append("a CDATA section <![CDATA[ … ]]>")

    # no processing instruction but a leading XML declaration, and that declares no encoding but UTF-8:
    declaration: re.Match[str] | None = XML_DECLARATION.match(text)
    rest: str = text
    if declaration is not None:
        rest = text[declaration.end() :]
        encoding: re.Match[str] | None = DECLARED_ENCODING.search(declaration[0])
        if encoding is not None and encoding[1].lower() != "utf-8":
            problems.append(
                f"the encoding {encoding[1]!r} in the XML declaration is not UTF-8"
            )
    for instruction in re.finditer(r"<\?([^\s?]*)", rest):
        problems.append(f"the processing instruction <?{instruction[1]} …?>")

    # no comment that HTML ends at once; XML allows no "--" inside a comment, so a match starts a comment or,
    # rarely, ends one whose text ends in "<!"; both count:
    for comment in re.finditer(r"<!--->|<!-->", text):
        problems.append(f"a comment {comment[0]} that HTML ends at once")
    return problems


def svg_problems(text: str) -> list[str]:
    r"""Return what makes an SVG unfit to embed as the logo: anything outside the few parts a flat drawing needs.

    The checks allow only what the logo needs, so a part that can run code or load something (a script, a style
    sheet, embedded HTML, an image, a link, an animation that sets a link, an event handler) is a problem without
    being named here. A problem is

    - an element that is not one of :data:`ALLOWED_ELEMENTS` in the SVG namespace; a root element that is not
      ``<svg>`` in the SVG namespace (without it, a browser does not show the file as an image); a root ``<svg>``
      without a ``viewBox`` (without it, the logo does not scale to the width the README gives it);
    - a ``<title>`` or ``<desc>`` that contains an element: both hold plain text, and a parser that reads the SVG
      as HTML may end them at another closing tag than XML does;
    - an attribute that is not one of :data:`ALLOWED_ATTRIBUTES`, so also every attribute in a namespace, such as
      ``xlink:href`` (the ``xmlns`` declarations are no attributes to ``ElementTree``);
    - a ``fill`` or ``stroke`` that is not ``none`` or a hex colour ``#rgb`` or ``#rrggbb``;
    - in the value of any attribute, ``url(`` in any letter case (a reference to a gradient or to another file) or
      a backslash (CSS reads it as an escape, so ``u\72l(`` is ``url(``).

    ``ElementTree`` hides the following parts, so they are searched in the text, also inside comments
    (:func:`text_problems`):

    - ``<!DOCTYPE`` (it can declare entities);
    - a CDATA section ``<![CDATA[``: the logo needs none, and a parser that reads the SVG as HTML may end it
      elsewhere than XML does;
    - a processing instruction ``<?…?>`` (such as a style sheet with ``<?xml-stylesheet …?>``) other than an XML
      declaration ``<?xml …?>`` at the very start;
    - an encoding other than UTF-8 (in any letter case) in that XML declaration: a browser decodes the file in the
      declared encoding, while the tests read it as UTF-8, so the two could see different documents;
    - a comment that starts with ``>`` or ``->`` (``<!-->``, ``<!--->``): XML reads it up to the next ``-->``,
      but HTML ends it right there, so the markup after it would count when the SVG is put into a web page.

    Names and values are compared with their letter case, as XML does, except ``url(`` and the encoding. Apart from
    these searches in the text, comments are not checked (a ``<`` in a comment is fine, the license header has
    ``<https://…>``), and neither is the text inside an element.

    @param text: the content of the SVG file.
    @return: one message per problem, those found in the text (see :func:`text_problems`) first, then those of the
        elements in document order; empty if the SVG is fine.
    """
    problems: list[str] = text_problems(text)
    try:
        root: ET.Element = ET.fromstring(text)
    except ET.ParseError as error:
        return problems + [f"the SVG is not well-formed XML: {error}"]

    # the root is an <svg> in the SVG namespace, with a viewBox:
    if root.tag != f"{{{SVG_NAMESPACE}}}svg":
        problems.append(
            f"the root element {root.tag!r} is not <svg> in the namespace {SVG_NAMESPACE}"
        )
    elif "viewBox" not in root.attrib:
        problems.append("the root <svg> has no viewBox")

    # every other element and every attribute is one the logo needs, and every value is a plain one:
    allowed_tags: set[str] = {f"{{{SVG_NAMESPACE}}}{name}" for name in ALLOWED_ELEMENTS}
    for element in root.iter():
        tag: str = shown_tag(element.tag)
        if element is not root and element.tag not in allowed_tags:
            problems.append(
                f"<{tag}> is not one of the allowed elements in the SVG namespace"
            )
        if tag in TEXT_ONLY_ELEMENTS and len(element) > 0:
            problems.append(f"<{tag}> contains an element, but may hold text only")
        for name, value in element.attrib.items():
            if name not in ALLOWED_ATTRIBUTES:
                problems.append(f"the attribute {name} on <{tag}> is not allowed")
            if name in COLOUR_ATTRIBUTES and not COLOUR_PATTERN.fullmatch(value):
                problems.append(
                    f"the {name} {value!r} on <{tag}> is not none or a hex colour #rgb or #rrggbb"
                )
            if "url(" in value.lower():
                problems.append(f"url( in the attribute {name} on <{tag}>")
            if "\\" in value:
                problems.append(f"a backslash in the attribute {name} on <{tag}>")
    return problems


def png_size(data: bytes) -> tuple[int, int]:
    """Return the width and height of a PNG image from its header.

    A PNG file starts with an 8-byte signature followed by the IHDR chunk: 4 bytes length, the 4 bytes ``IHDR``,
    then width and height as 4-byte big-endian numbers.

    @param data: the content of the PNG file.
    @return: ``(width, height)`` in pixels.
    @raise ValueError: if the data does not start with the PNG signature, has no IHDR chunk right after it, or
        ends before the width and height.
    """
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG file: it does not start with the PNG signature")
    if data[12:16] != b"IHDR":
        raise ValueError("the PNG file has no IHDR chunk right after its signature")
    if len(data) < 24:
        raise ValueError(
            "the PNG file ends inside its IHDR chunk, before the width and height"
        )
    width, height = struct.unpack(">II", data[16:24])
    return width, height


class MalformedLogoBlock(ValueError):
    """The README has no logo block before its title in the expected form; the message says why.

    The title is the first line that starts with ``# ``. The first ``<img>`` before the title must have a ``src`` and
    no ``srcset``; every ``<source>`` before the title must stand in the ``<picture>`` of that ``<img>``, before it;
    and the line right before the title must be blank. :func:`logo_problems` checks the image files and the alt
    text; nothing else before the title is checked.
    """


@dataclass(frozen=True)
class LogoSource:
    """A ``<source>`` tag in the ``<picture>`` of the README's logo, before its ``<img>``.

    ``srcset`` is the image file, ``media`` the condition under which a browser shows it instead of the ``<img>``,
    e.g. ``(prefers-color-scheme: dark)``; each is empty if the tag does not have it.
    """

    srcset: str
    media: str


@dataclass(frozen=True)
class LogoImage:
    """The image above the README's title, as its ``<img>`` tag and the ``<source>`` tags of its ``<picture>`` give it.

    ``src`` is the image file, ``alt`` the alt text (empty if the tag has none), ``sources`` the ``<source>`` tags in
    README order (none if the ``<img>`` stands in no ``<picture>``).
    """

    src: str
    alt: str
    sources: tuple[LogoSource, ...] = ()


class LogoBlockParser(HTMLParser):
    """Collects the attributes of the first ``<img>`` tag of an HTML text and of the ``<source>`` tags for it.

    A ``<source>`` counts only inside the ``<picture>`` of that ``<img>`` and before the ``<img>`` (a browser would
    also ignore one wrapped in another element there, which this parser does not notice). A ``<source>`` after the
    ``<img>``, outside a ``<picture>`` or in a ``<picture>`` without the ``<img>`` is recorded in ``misplaced``
    instead. ``HTMLParser`` reads a tag that spans several lines, lower-cases the
    attribute names and decodes character references such as ``&amp;`` in the values.
    """

    def __init__(self) -> None:
        """Start without tags; ``image`` stays None until the first ``<img>``."""
        super().__init__()
        self.image: dict[str, str | None] | None = None
        self.sources: list[dict[str, str | None]] = []
        self.misplaced: list[str] = []
        self.in_picture: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """See :meth:`HTMLParser.handle_starttag`. Keeps the first ``<img>`` and the ``<source>`` tags for it."""
        if tag == "picture":
            self.in_picture = True
        elif tag == "img" and self.image is None:
            self.image = dict(attrs)
        elif tag == "source":
            if self.image is not None:
                self.misplaced.append("a <source> after the logo <img>")
            elif not self.in_picture:
                self.misplaced.append("a <source> outside a <picture>")
            else:
                self.sources.append(dict(attrs))

    def handle_endtag(self, tag: str) -> None:
        """See :meth:`HTMLParser.handle_endtag`. A ``<picture>`` that ends before the ``<img>`` keeps no source."""
        if tag == "picture":
            self.in_picture = False
            if self.image is None and self.sources:
                self.misplaced.append(
                    "a <source> in a <picture> without the logo <img>"
                )
                self.sources = []


def readme_logo(text: str) -> LogoImage:
    """Return the logo above the README's title; raise :class:`MalformedLogoBlock` if it is not there.

    The title is the first line that starts with ``"# "``, and the logo the first ``<img>`` tag before it, with the
    ``<source>`` tags before it in its ``<picture>``. The line right before the title must be blank: the HTML block
    with the logo ends only at a blank line, so without it the title would belong to the HTML block and show as
    plain text.

    @param text: the README content.
    @return: the logo's ``src``, ``alt`` and ``<source>`` tags.
    @raise MalformedLogoBlock: if the README has no title line, no ``<img>`` before it or no blank line right before
        it; if the first ``<img>`` before the title has no ``src`` or has a ``srcset`` (which browsers prefer to
        ``src``); or if a ``<source>`` before the title does not stand in the ``<picture>`` of that ``<img>``,
        before it.
    """
    # the title line:
    lines: list[str] = text.splitlines()
    title: int | None = next(
        (i for i, line in enumerate(lines) if line.startswith("# ")), None
    )
    if title is None:
        raise MalformedLogoBlock("the README has no title line starting with '# '")

    # the first <img> and its <source> tags before the title:
    parser: LogoBlockParser = LogoBlockParser()
    parser.feed("\n".join(lines[:title]))
    parser.close()
    if parser.image is None:
        raise MalformedLogoBlock("no complete <img> tag before the title line")

    # a blank line ends the HTML block before the title (there is a line before it, the one with the <img>):
    if lines[title - 1].strip():
        raise MalformedLogoBlock(
            f"no blank line directly before the title line, but {lines[title - 1]!r}"
        )

    # the image file is required, a missing alt text is reported by logo_problems:
    src: str | None = parser.image.get("src")
    if not src:
        raise MalformedLogoBlock("the <img> before the title line has no src")

    # the <img> has no srcset of its own, and every <source> is one for it:
    if "srcset" in parser.image:
        raise MalformedLogoBlock(
            "the logo <img> has a srcset, which browsers prefer to its src;"
            " use a <source> in its <picture> instead"
        )
    if parser.misplaced:
        raise MalformedLogoBlock(parser.misplaced[0])
    sources: tuple[LogoSource, ...] = tuple(
        LogoSource(srcset=source.get("srcset") or "", media=source.get("media") or "")
        for source in parser.sources
    )
    return LogoImage(src=src, alt=parser.image.get("alt") or "", sources=sources)


def unlisted_part(relative: Path, root: Path) -> str | None:
    """Return the first part of a path that its folder does not list with exactly this name, or None.

    The names come from the folder listing, so they keep their letter case also on a file system that ignores it
    (macOS): a folder with ``logo.svg`` does not list ``Logo.svg``, just as GitLab and GitHub do not find it.

    @param relative: a path relative to ``root``, e.g. ``docs/images/logo/explaindb-logo-light.svg``.
    @param root: the folder the path starts in.
    @return: the first part that is not listed, e.g. ``"Logo.svg"``; None if every part is.
    """
    folder: Path = root
    for part in relative.parts:
        if not folder.is_dir() or part not in {
            child.name for child in folder.iterdir()
        }:
            return part
        folder = folder / part
    return None


def path_problem(name: str, path: str, root: Path) -> str | None:
    """Return what is wrong with a path of the README's logo block; None if it names a file in the repository.

    The path must be relative and stay inside ``root``, and each of its parts must be in the listing of its folder
    with exactly this letter case (see :func:`unlisted_part`); a URL is no such path either. The last part must be a
    file, not a folder.

    @param name: what the path is, for the message, e.g. ``"the logo"``.
    @param path: the path as the README gives it, e.g. ``"docs/images/logo/explaindb-logo-light.svg"``.
    @param root: the folder that the path is relative to, the repository root.
    @return: the message, e.g. ``"the logo 'Logo.svg' is no file in the repository: …"``; None if the path is fine.
    """
    base: Path = root.resolve()
    resolved: Path = (base / path).resolve()
    if Path(path).is_absolute():
        return f"{name} {path!r} is an absolute path, not one relative to the repository root"
    if not resolved.is_relative_to(base):
        return f"{name} {path!r} leads out of the repository"
    part: str | None = unlisted_part(resolved.relative_to(base), base)
    if part is not None:
        return (
            f"{name} {path!r} is no file in the repository: no {part!r}"
            " (names are compared with their letter case)"
        )
    if not resolved.is_file():
        return f"{name} {path!r} is a folder, not a file"
    return None


def logo_problems(logo: LogoImage, root: Path) -> list[str]:
    """Return what is wrong with the README's logo: an image that is no file in the repository, or no real alt text.

    ``src`` and the ``srcset`` of every ``<source>`` must name a file in the repository (see :func:`path_problem`).
    A ``srcset`` must hold a single path: no list of paths and no size or density after the path. The alt text must
    not be empty or one of :data:`PLACEHOLDER_ALTS`, in any letter case.

    @param logo: the logo, as :func:`readme_logo` returns it.
    @param root: the folder that ``src`` and ``srcset`` are relative to, the repository root.
    @return: one message per problem; empty if the logo is fine.
    """
    # src names a file in the repository:
    problems: list[str] = []
    problem: str | None = path_problem("the logo", logo.src, root)
    if problem is not None:
        problems.append(problem)

    # so does the srcset of every <source>, with a single path:
    for source in logo.sources:
        entries: list[str] = source.srcset.split()
        if len(entries) != 1 or "," in source.srcset:
            problems.append(
                f"the <source> srcset {source.srcset!r} is not a single path"
            )
        elif (
            problem := path_problem("the <source> srcset", entries[0], root)
        ) is not None:
            problems.append(problem)

    # the alt text describes the logo:
    if logo.alt.strip().lower() in PLACEHOLDER_ALTS:
        problems.append(f"the logo's alt text {logo.alt!r} is empty or a placeholder")
    return problems


class LogoHelpersTest(unittest.TestCase):
    """Tests for the helper functions on small hand-written SVGs, PNG headers, README parts and a temporary folder."""

    # the root attributes of a valid SVG:
    ROOT: str = f'xmlns="{SVG_NAMESPACE}" viewBox="0 0 10 10"'

    def _svg(self, body: str = "", root: str = ROOT) -> str:
        """Return a small valid SVG, with more content and other root attributes if given.

        @param body: content after the SVG's one ``<rect>``, e.g. ``"<script>alert(1)</script>"``.
        @param root: the attributes of the root ``<svg>``.
        @return: the SVG text.
        """
        return f'<svg {root}><rect width="10" height="10" fill="#fff"/>{body}</svg>'

    def test_svg_problems_accepts_every_allowed_element_attribute_and_colour(
        self,
    ) -> None:
        """An SVG with a leading XML declaration, a comment and every allowed element and attribute has no problem.

        Would fail if a name the logo may use were missing from the allowlists or misspelt there, if ``none`` or a
        hex colour with three or six digits were rejected, or if the XML declaration, its encoding ``utf-8`` in
        lower case or a comment counted as a problem.
        """
        text: str = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<!-- a ring on a dark tile -->\n"
            f'<svg xmlns="{SVG_NAMESPACE}" viewBox="0 0 100 100" width="100" height="100"'
            ' role="img" aria-label="A ring">'
            "<title>A ring</title><desc>A ring on a dark tile</desc>"
            '<rect x="0" y="0" width="100" height="100" rx="8" ry="8" fill="#0b0f16"/>'
            '<g transform="translate(50 50)" fill="none" stroke="#2E6" stroke-width="5"'
            ' stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="0" cy="0" r="30"/><ellipse cx="0" cy="0" rx="20" ry="10"/>'
            '<path d="M-10 0 H10"/><line x1="0" y1="-10" x2="0" y2="10"/>'
            '<polygon points="0,-8 8,8 -8,8" fill="#000" opacity="0.3"/>'
            "</g></svg>"
        )
        self.assertEqual(svg_problems(text), [])

    def test_svg_problems_rejects_everything_outside_the_allowlists(self) -> None:
        """Each SVG with one part outside the allowlists, a reference or a missing root rule is reported for it.

        Would fail if one of the checks were missing or too lax, e.g. if an element were checked against a list of
        forbidden elements (missing ``<set>``, ``<animate>`` or an XHTML element) or by its name without the
        namespace, a ``<title>`` or ``<desc>`` with an element inside passed, an attribute in a namespace passed,
        ``url(`` were compared with its letter case, a CSS escape or a colour name passed, a document type
        declaration, CDATA section, processing instruction or encoding other than UTF-8 went unnoticed because
        ``ElementTree`` hides them (also after an XML declaration), or a comment that HTML ends at once passed, also
        inside the ``<svg>``; or if the message named another problem.
        """
        # the SVG the variants start from is fine, also after an XML declaration without an encoding:
        self.assertEqual(svg_problems(self._svg()), [])
        self.assertEqual(svg_problems('<?xml version="1.0"?>' + self._svg()), [])

        # each variant changes the valid SVG in one place; the problem names that place:
        xlink: str = 'xmlns:xlink="http://www.w3.org/1999/xlink"'
        variants: dict[str, tuple[str, str]] = {
            "<script>": (
                self._svg("<script>alert(1)</script>"),
                "<script> is not one of the allowed elements in the SVG namespace",
            ),
            "<style>": (
                self._svg("<style>rect { fill: red }</style>"),
                "<style> is not one of the allowed elements in the SVG namespace",
            ),
            "<foreignObject>": (
                self._svg('<foreignObject width="10" height="10"/>'),
                "<foreignObject> is not one of the allowed elements in the SVG namespace",
            ),
            "<image href=…>": (
                self._svg('<image href="x.png" width="10" height="10"/>'),
                "<image> is not one of the allowed elements in the SVG namespace",
            ),
            "<set> that sets a link": (
                self._svg('<set attributeName="href" to="javascript:alert(1)"/>'),
                "<set> is not one of the allowed elements in the SVG namespace",
            ),
            "<animate> that sets a link": (
                self._svg('<animate attributeName="xlink:href" values="x.svg"/>'),
                "<animate> is not one of the allowed elements in the SVG namespace",
            ),
            "XHTML element": (
                self._svg('<div xmlns="http://www.w3.org/1999/xhtml">x</div>'),
                "<{http://www.w3.org/1999/xhtml}div> is not one of the allowed elements"
                " in the SVG namespace",
            ),
            "allowed name in the XHTML namespace": (
                self._svg('<rect xmlns="http://www.w3.org/1999/xhtml"/>'),
                "<{http://www.w3.org/1999/xhtml}rect> is not one of the allowed elements"
                " in the SVG namespace",
            ),
            "<title> with an element inside": (
                self._svg(
                    "<title><title><!-- </title><script>alert(1)</script> --></title></title>"
                ),
                "<title> contains an element, but may hold text only",
            ),
            "<desc> with an element inside": (
                self._svg("<desc><g/></desc>"),
                "<desc> contains an element, but may hold text only",
            ),
            "<?xml-stylesheet?>": (
                '<?xml-stylesheet href="x.css"?>' + self._svg(),
                "the processing instruction <?xml-stylesheet …?>",
            ),
            "<?xml-stylesheet?> after the XML declaration": (
                '<?xml version="1.0"?> <?xml-stylesheet href="x.css"?>' + self._svg(),
                "the processing instruction <?xml-stylesheet …?>",
            ),
            "encoding other than UTF-8": (
                '<?xml version="1.0" encoding="Shift_JIS"?>' + self._svg(),
                "the encoding 'Shift_JIS' in the XML declaration is not UTF-8",
            ),
            "CDATA section": (
                self._svg("<title><![CDATA[A ring]]></title>"),
                "a CDATA section <![CDATA[ … ]]>",
            ),
            "comment <!--> inside the <svg>": (
                self._svg("<!--><script>alert(1)</script>-->"),
                "a comment <!--> that HTML ends at once",
            ),
            "comment <!--->": (
                "<!---><script>alert(1)</script>-->" + self._svg(),
                "a comment <!---> that HTML ends at once",
            ),
            "<!DOCTYPE> after the XML declaration": (
                '<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"'
                ' "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">' + self._svg(),
                "a document type declaration <!DOCTYPE …>",
            ),
            "event handler": (
                self._svg(root=f'{self.ROOT} onload="alert(1)"'),
                "the attribute onload on <svg> is not allowed",
            ),
            "href": (
                self._svg('<g href="https://example.org"/>'),
                "the attribute href on <g> is not allowed",
            ),
            "xlink:href": (
                self._svg(f'<g {xlink} xlink:href="#x"/>'),
                "the attribute {http://www.w3.org/1999/xlink}href on <g> is not allowed",
            ),
            "url( in an attribute that holds no colour": (
                self._svg('<path d="url(#g)"/>'),
                "url( in the attribute d on <path>",
            ),
            "URL( in capitals": (
                self._svg('<circle r="5" stroke="URL(#g)"/>'),
                "url( in the attribute stroke on <circle>",
            ),
            "url( as a CSS escape": (
                self._svg(r'<circle r="5" stroke="u\72l(#g)"/>'),
                "a backslash in the attribute stroke on <circle>",
            ),
            "inline style sheet": (
                self._svg('<circle r="5" style="fill:red"/>'),
                "the attribute style on <circle> is not allowed",
            ),
            "colour name": (
                self._svg('<circle r="5" fill="red"/>'),
                "the fill 'red' on <circle> is not none or a hex colour #rgb or #rrggbb",
            ),
            "no viewBox": (
                self._svg(root=f'xmlns="{SVG_NAMESPACE}"'),
                "the root <svg> has no viewBox",
            ),
            "root without the SVG namespace": (
                self._svg(root='viewBox="0 0 10 10"'),
                f"the root element 'svg' is not <svg> in the namespace {SVG_NAMESPACE}",
            ),
        }
        for case, (text, problem) in variants.items():
            with self.subTest(case=case):
                self.assertIn(problem, svg_problems(text))

    def test_svg_problems_reports_broken_xml(self) -> None:
        """A text that is not well-formed XML yields exactly one problem, which says so.

        Would fail if the parse error escaped as an exception instead of a message, or if checks on a half-read
        tree added problems of their own.
        """
        problems: list[str] = svg_problems(self._svg("<g>"))
        self.assertEqual(len(problems), 1, problems)
        self.assertRegex(problems[0], "^the SVG is not well-formed XML: mismatched tag")

    def test_png_size_reads_a_header_and_rejects_other_data(self) -> None:
        """``png_size`` reads width and height from a PNG header and raises ValueError for other data.

        Would fail if width and height were swapped, a GIF saved under the avatar's name passed, a file cut off
        inside the IHDR chunk raised a ``struct.error`` instead, or a PNG whose first chunk is not IHDR was read as
        if it were; or if the message named another problem.
        """
        # the signature and an IHDR chunk of a 640 × 480 image, with bit depth, colour type and the flags:
        header: bytes = (
            PNG_SIGNATURE
            + struct.pack(">I", 13)
            + b"IHDR"
            + struct.pack(">II", 640, 480)
            + b"\x08\x06\x00\x00\x00"
        )
        self.assertEqual(png_size(header), (640, 480))

        # each variant breaks the header in one place; the message names that place:
        variants: dict[str, tuple[bytes, str]] = {
            "GIF": (b"GIF89a" + header[6:], "^not a PNG file"),
            "cut off inside IHDR": (header[:20], "ends inside its IHDR chunk"),
            "first chunk not IHDR": (
                header.replace(b"IHDR", b"IDAT"),
                "no IHDR chunk right after its signature",
            ),
        }
        for case, (data, reason) in variants.items():
            with self.subTest(case=case):
                with self.assertRaisesRegex(ValueError, reason):
                    png_size(data)

    def test_readme_logo_reads_the_logo_and_rejects_malformed_blocks(self) -> None:
        """``readme_logo`` returns the ``<img>`` and ``<source>`` tags above the title and raises for a malformed block.

        Would fail if a tag over several lines, a character reference in the alt text or a ``<source>`` were read
        wrongly (e.g. ``srcset`` and ``media`` swapped, or the ``<source>`` taken as the ``<img>``), or if one of these
        variants passed: the ``<img>`` after the title, no blank line before the title, only a ``## `` heading, an
        ``<img>`` without ``src`` or with a ``srcset``, a ``<source>`` after the ``<img>``, outside a ``<picture>`` or
        in a ``<picture>`` without the ``<img>``; or if the message named another problem.
        """
        # a logo block in the README's form: a <picture> with a <source> for a dark theme and the <img> over two
        # lines, with &amp; in its alt text:
        source: str = f'<source media="{DARK_MEDIA}" srcset="docs/logo-dark.svg">'
        image: str = (
            '<img src="docs/logo.svg" width="120"\n       alt="A cylinder &amp; a lens">'
        )
        self.assertEqual(
            readme_logo(
                f"<p>\n  <picture>\n    {source}\n    {image}\n  </picture>\n</p>\n"
                "\n# ExplainDB\n\nText.\n"
            ),
            LogoImage(
                src="docs/logo.svg",
                alt="A cylinder & a lens",
                sources=(LogoSource(srcset="docs/logo-dark.svg", media=DARK_MEDIA),),
            ),
        )

        # each variant has exactly one fault; the message names it:
        variants: dict[str, tuple[str, str]] = {
            "<img> after the title": (
                f"# ExplainDB\n\n<p>\n  {image}\n</p>\n",
                "no complete <img> tag before the title line",
            ),
            "no blank line before the title": (
                f"<p>\n  {image}\n</p>\n# ExplainDB\n",
                "no blank line directly before the title line",
            ),
            "no title": (
                f"<p>\n  {image}\n</p>\n\n## ExplainDB\n",
                "no title line starting with '# '",
            ),
            "<img> without src": (
                '<p>\n  <img width="120" alt="A cylinder">\n</p>\n\n# ExplainDB\n',
                "has no src",
            ),
            "<img> with a srcset": (
                '<p>\n  <img src="docs/logo.svg" srcset="docs/logo-dark.svg" alt="A cylinder">'
                "\n</p>\n\n# ExplainDB\n",
                "the logo <img> has a srcset",
            ),
            "<source> after the <img>": (
                f"<p>\n  <picture>\n    {image}\n    {source}\n  </picture>\n</p>\n\n# ExplainDB\n",
                "a <source> after the logo <img>",
            ),
            "<source> without <picture>": (
                f"<p>\n  {source}\n  {image}\n</p>\n\n# ExplainDB\n",
                "a <source> outside a <picture>",
            ),
            "<source> in a <picture> without the <img>": (
                f"<p>\n  <picture>{source}</picture>\n  {image}\n</p>\n\n# ExplainDB\n",
                "a <source> in a <picture> without the logo <img>",
            ),
        }
        for case, (text, reason) in variants.items():
            with self.subTest(case=case):
                with self.assertRaisesRegex(MalformedLogoBlock, reason):
                    readme_logo(text)

    def test_logo_problems_rejects_wrong_paths_and_placeholder_alt_texts(
        self,
    ) -> None:
        """A logo path that is no file in the repository with exactly this name, or a placeholder alt text, is reported.

        The wrong letter case is checked against a real folder, so on macOS, whose file system finds ``Logo.svg``
        also as ``logo.svg``, only the folder listing rejects it. Would fail if an absolute path into the repository,
        a path out of it, a URL, a missing file, a folder or a name in another letter case passed as ``src``, a
        ``srcset`` to a missing file, in another letter case, with more than one path or with a density after the
        path passed, or an ``<img>`` without ``alt`` or a placeholder alt text in another letter case; or if the
        message named another problem.
        """
        with tempfile.TemporaryDirectory() as directory:
            # a repository with the logo images/logo.svg and its dark twin, and a file next to the repository:
            root: Path = Path(directory) / "repo"
            (root / "images").mkdir(parents=True)
            (root / "images" / "logo.svg").write_text("<svg/>", encoding="utf-8")
            (root / "images" / "logo-dark.svg").write_text("<svg/>", encoding="utf-8")
            (Path(directory) / "elsewhere.svg").write_text("<svg/>", encoding="utf-8")
            alt: str = "A cylinder under a lens"
            dark: LogoSource = LogoSource("images/logo-dark.svg", DARK_MEDIA)
            self.assertEqual(
                logo_problems(LogoImage("images/logo.svg", alt, (dark,)), root), []
            )

            # each variant changes src, alt or the srcset of the <source>; the one problem names it:
            absolute: str = str(root / "images" / "logo.svg")
            url: str = "https://example.org/logo.svg"
            variants: dict[str, tuple[LogoImage, str]] = {
                "absolute path": (
                    LogoImage(absolute, alt),
                    f"the logo {absolute!r} is an absolute path, not one relative to the repository root",
                ),
                "path out of the repository": (
                    LogoImage("../elsewhere.svg", alt),
                    "the logo '../elsewhere.svg' leads out of the repository",
                ),
                "URL": (
                    LogoImage(url, alt),
                    f"the logo {url!r} is no file in the repository: no 'https:'"
                    " (names are compared with their letter case)",
                ),
                "missing file": (
                    LogoImage("images/missing.svg", alt),
                    "the logo 'images/missing.svg' is no file in the repository:"
                    " no 'missing.svg' (names are compared with their letter case)",
                ),
                "file name in another letter case": (
                    LogoImage("images/Logo.svg", alt),
                    "the logo 'images/Logo.svg' is no file in the repository:"
                    " no 'Logo.svg' (names are compared with their letter case)",
                ),
                "folder name in another letter case": (
                    LogoImage("Images/logo.svg", alt),
                    "the logo 'Images/logo.svg' is no file in the repository:"
                    " no 'Images' (names are compared with their letter case)",
                ),
                "folder": (
                    LogoImage("images", alt),
                    "the logo 'images' is a folder, not a file",
                ),
                "srcset to a missing file": (
                    LogoImage(
                        "images/logo.svg",
                        alt,
                        (LogoSource("images/missing-dark.svg", DARK_MEDIA),),
                    ),
                    "the <source> srcset 'images/missing-dark.svg' is no file in the repository:"
                    " no 'missing-dark.svg' (names are compared with their letter case)",
                ),
                "srcset in another letter case": (
                    LogoImage(
                        "images/logo.svg",
                        alt,
                        (LogoSource("images/Logo-dark.svg", DARK_MEDIA),),
                    ),
                    "the <source> srcset 'images/Logo-dark.svg' is no file in the repository:"
                    " no 'Logo-dark.svg' (names are compared with their letter case)",
                ),
                "srcset with two paths": (
                    LogoImage(
                        "images/logo.svg",
                        alt,
                        (
                            LogoSource(
                                "images/logo-dark.svg,images/logo.svg", DARK_MEDIA
                            ),
                        ),
                    ),
                    "the <source> srcset 'images/logo-dark.svg,images/logo.svg' is not a single path",
                ),
                "srcset with a density": (
                    LogoImage(
                        "images/logo.svg",
                        alt,
                        (LogoSource("images/logo-dark.svg 2x", DARK_MEDIA),),
                    ),
                    "the <source> srcset 'images/logo-dark.svg 2x' is not a single path",
                ),
                # readme_logo gives an <img> without alt the alt text "":
                "<img> without alt": (
                    readme_logo('<p><img src="images/logo.svg"></p>\n\n# ExplainDB\n'),
                    "the logo's alt text '' is empty or a placeholder",
                ),
            }
            for placeholder in ["", "Logo", "image", "…", "..."]:
                variants[f"alt={placeholder!r}"] = (
                    LogoImage("images/logo.svg", placeholder),
                    f"the logo's alt text {placeholder!r} is empty or a placeholder",
                )
            for case, (logo, problem) in variants.items():
                with self.subTest(case=case):
                    self.assertEqual(logo_problems(logo, root), [problem])


class LogoTest(unittest.TestCase):
    """The logo files in ``docs/images/logo/`` and the logo block of the README pass the checks."""

    def test_svgs_are_safe_to_embed(self) -> None:
        """The light and the dark logo and the avatar SVG use only the allowed elements, attributes and colours.

        Would fail if an edit in a drawing program added a style sheet, a script, an event handler, a link, a
        gradient referenced with ``url(...)``, a colour name or anything else outside the allowlists to one of them,
        or dropped its viewBox.
        """
        for path in SVG_PATHS:
            with self.subTest(svg=path.name):
                # utf-8-sig drops a byte order mark, which would hide the XML declaration at the very start:
                problems: list[str] = svg_problems(path.read_text(encoding="utf-8-sig"))
                if problems:
                    self.fail(
                        f"{path.relative_to(REPO_ROOT)} is not safe to embed:\n"
                        + "\n".join(problems)
                    )

    def test_avatar_is_512_by_512(self) -> None:
        """The avatar is a PNG of 512 × 512 pixels.

        Would fail if the avatar was exported at another size or saved in another format under the same name.
        """
        self.assertEqual(png_size(PNG_PATH.read_bytes()), (512, 512))

    def test_readme_shows_the_logo_above_the_title(self) -> None:
        """The README's first ``<img>`` above its title shows the light logo, and its one ``<source>`` the dark logo.

        The title is the first line that starts with ``# ``. The first ``<img>`` before the title must have a ``src``
        and no ``srcset``, the line right before the title must be blank, and the ``<source>`` tags of its
        ``<picture>`` are compared; nothing else before the title is checked. Would fail if the logo block was
        removed, moved below the title or lost the blank line before the title; if it showed another image, gave the
        ``<img>`` a ``srcset``, lost the dark logo (also by moving its ``<source>`` out of the ``<picture>`` or after
        the ``<img>``), got a second ``<source>`` or another ``media`` condition; or if it named a file that does not
        exist under exactly this name, or had no real alt text.
        """
        # the first <img> above the title shows the light logo (utf-8-sig drops a byte order mark):
        logo: LogoImage = readme_logo(README_PATH.read_text(encoding="utf-8-sig"))
        self.assertEqual(logo.src, "docs/images/logo/explaindb-logo-light.svg")

        # the one <source> shows the dark logo in a dark theme:
        self.assertEqual(
            logo.sources,
            (LogoSource("docs/images/logo/explaindb-logo-dark.svg", DARK_MEDIA),),
        )

        # the files exist with exactly these names and the alt text is not a placeholder:
        problems: list[str] = logo_problems(logo, REPO_ROOT)
        if problems:
            self.fail("The logo in README.md:\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
