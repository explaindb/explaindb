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

"""A parser for the tests of the HTML report of the store benchmarks: elements, their nesting, text and SVGs."""

from dataclasses import dataclass
from html.parser import HTMLParser

# HTML elements without an end tag; all other elements are closed explicitly or self-closing (SVG):
VOID_ELEMENTS: frozenset[str] = frozenset(
    {"area", "base", "br", "col", "hr", "img", "input", "link", "meta", "source", "wbr"}
)


@dataclass
class Element:
    """A start tag of the page: its name, its attributes, the open elements around it (outermost first) and the
    text directly inside it.
    """

    tag: str
    attributes: dict[str, str]
    ancestors: list["Element"]
    text: str = ""

    def inside(self, test_id: str) -> bool:
        """Returns whether an enclosing element has the ``data-testid`` `test_id`."""
        return any(a.test_id == test_id for a in self.ancestors)

    def within(self, other: "Element") -> bool:
        """Returns whether `other` encloses this element."""
        return any(a is other for a in self.ancestors)

    @property
    def test_id(self) -> str:
        """Returns the ``data-testid`` of the element, empty if it has none."""
        return self.attributes.get("data-testid", "")


@dataclass
class Svg:
    """An ``<svg>`` element with its ``<title>`` and ``<desc>`` children (None if missing)."""

    element: Element
    title: Element | None = None
    desc: Element | None = None


class PageParser(HTMLParser):
    """Collects every start tag of a page with its enclosing elements and its text, and the titles and
    descriptions of SVGs.
    """

    def __init__(self) -> None:
        """Starts with no elements read."""
        super().__init__()
        self.elements: list[Element] = []
        self.svgs: list[Svg] = []
        self.open_elements: list[Element] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Records the element and keeps it open unless it is a void element."""
        element: Element = self.record(tag, attrs)
        if tag not in VOID_ELEMENTS:
            self.open_elements.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Records a self-closing element without keeping it open."""
        self.record(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        """Closes the innermost open element named `tag` and everything opened inside it."""
        for index in range(len(self.open_elements) - 1, -1, -1):
            if self.open_elements[index].tag == tag:
                del self.open_elements[index:]
                return

    def handle_data(self, data: str) -> None:
        """Adds text to the innermost open element."""
        if self.open_elements:
            self.open_elements[-1].text += data

    def record(self, tag: str, attrs: list[tuple[str, str | None]]) -> Element:
        """Returns the new element, after adding it to `elements` and, for SVG parts, to `svgs`."""
        element: Element = Element(
            tag, {k: v or "" for k, v in attrs}, list(self.open_elements)
        )
        self.elements.append(element)
        parent: Element | None = self.open_elements[-1] if self.open_elements else None
        if tag == "svg":
            self.svgs.append(Svg(element))
        elif tag in ("title", "desc") and parent is not None and parent.tag == "svg":
            svg: Svg = next(s for s in self.svgs if s.element is parent)
            if tag == "title":
                svg.title = element
            else:
                svg.desc = element
        return element


def parse(page: str) -> PageParser:
    """Returns the parser after it has read `page`."""
    parser: PageParser = PageParser()
    parser.feed(page)
    parser.close()
    return parser
