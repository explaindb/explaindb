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

"""Convert the project's Javadoc-style docstring tags into reST field lists for Sphinx autodoc.

The codebase documents parameters and return values with Javadoc tags
(``@param name: ...``, ``@return: ...``) while cross-references already use reST
roles (``:meth:`X```). Sphinx autodoc understands reST field lists but not
Javadoc tags, so this module rewrites the tags into ``:param name:`` /
``:returns:`` fields and re-attaches multi-line tag descriptions to the field
body (an unindented continuation line would otherwise render as a separate
paragraph). reST roles in the text are left untouched.
"""

import re

# A ``@param NAME: description`` tag; NAME in group 1, description in group 2.
# The colon is optional: the corpus also writes ``@param NAME description``.
_PARAM_RE = re.compile(r"^\s*@param\s+(\w+)\s*:?\s*(.*)$")
# A ``@return: description`` / ``@returns description`` tag; description in 1.
# The colon is optional here too, matching the colon-less form in the corpus.
_RETURN_RE = re.compile(r"^\s*@returns?\s*:?\s*(.*)$")
# A native reST field already written as ``:param foo:`` / ``:returns:`` / etc.
# These are left as-is but still opened for continuation folding, because some
# docstrings use reST fields directly and wrap their description across lines.
_REST_FIELD_RE = re.compile(
    r"^\s*:(param|parameter|type|returns?|rtype|raises?|yields?|ivar|var)\b"
)
# A leftover Javadoc tag that conversion did not rewrite (e.g. a malformed
# ``@param`` with no name). Used to detect silent conversion misses.
_RESIDUAL_RE = re.compile(r"^\s*@(param|returns?)\b")


def javadoc_to_rest(lines: list[str]) -> list[str]:
    """Rewrite Javadoc parameter/return tags in a docstring into reST field lists.

    ``@param name: text`` becomes ``:param name: text`` and ``@return: text``
    (or ``@returns:``) becomes ``:returns: text``. Native reST fields already in
    the docstring (``:param:``, ``:returns:``, ``:raises:``, ...) are kept as
    written. In both cases a line that continues a field's description across a
    wrap is appended to that field's body instead of being left as an unindented
    paragraph, which reST would otherwise mis-render.

    The transform starts joining continuation lines only once the first field
    has been seen, so the summary and free-text description above the fields are
    left exactly as written.

    @param lines: the docstring lines as autodoc supplies them (no trailing
    newlines); not modified in place.
    @return: a new list of lines with the tags converted.
    """
    out: list[str] = []
    # Index in ``out`` of the field line currently open for continuation, or -1.
    open_field: int = -1

    for line in lines:
        param_match = _PARAM_RE.match(line)
        return_match = _RETURN_RE.match(line)

        if param_match is not None:
            out.append(f":param {param_match.group(1)}: {param_match.group(2)}")
            open_field = len(out) - 1
        elif return_match is not None:
            out.append(f":returns: {return_match.group(1)}")
            open_field = len(out) - 1
        elif _REST_FIELD_RE.match(line) is not None:
            # A reST field written directly in the source: keep it, but open it
            # so any wrapped continuation lines fold into its body.
            out.append(line)
            open_field = len(out) - 1
        elif open_field >= 0 and line.strip() != "":
            # Non-blank line following a tag: treat as a continuation of that
            # tag's description and fold it onto the field line.
            out[open_field] = f"{out[open_field]} {line.strip()}"
        else:
            # Blank line, or prose before any tag: closes any open field.
            out.append(line)
            open_field = -1

    return out


def find_residual_tags(lines: list[str]) -> list[str]:
    """Return any lines carrying a ``@param``/``@return`` tag that will not convert.

    Run on the *original* (pre-conversion) docstring lines, this flags Javadoc
    tags that :func:`javadoc_to_rest` cannot rewrite -- a line that opens with
    ``@param``/``@return`` but matches neither conversion pattern (for example a
    malformed ``@param`` with no parameter name). Inspecting the input rather
    than the converted output is deliberate: a malformed tag placed right after a
    valid field would be folded into that field's body and so vanish from the
    output, escaping detection. Such a tag would otherwise render into the HTML
    without any Sphinx warning; the caller turns a non-empty result into a
    warning so the ``-W`` build gate catches it.

    @param lines: the original docstring lines, before conversion.
    @return: the offending lines, stripped of surrounding whitespace; empty if
    every tag is convertible.
    """
    return [
        line.strip()
        for line in lines
        if _RESIDUAL_RE.match(line) is not None
        and _PARAM_RE.match(line) is None
        and _RETURN_RE.match(line) is None
    ]
