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
"""Tests for the Javadoc-to-reST docstring hook in docs/api/javadoc.py."""

import os
import sys
import unittest
from unittest import mock

# ``docs/api`` is not a package, so it is added to ``sys.path`` to import the
# hook module directly (mirrors how the Sphinx conf.py loads it).
_DOCS_API = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs",
    "api",
)
if _DOCS_API not in sys.path:
    sys.path.insert(0, _DOCS_API)

import conf  # noqa: E402  (the Sphinx config module, holding the autodoc hook)
from javadoc import find_residual_tags, javadoc_to_rest  # noqa: E402


class JavadocToRestTest(unittest.TestCase):

    def test_single_line_param_and_return(self):
        """A summary plus single-line @param/@return tags convert to reST fields.

        Would fail if @param/@return rewriting broke, or if the summary and its
        trailing blank line were altered instead of passed through untouched.
        """
        lines = [
            "Adds a mapping.",
            "",
            "@param key: the key",
            "@param value: the value to associate with the key",
            "@return: None or a PutInfo object",
        ]
        self.assertEqual(
            javadoc_to_rest(lines),
            [
                "Adds a mapping.",
                "",
                ":param key: the key",
                ":param value: the value to associate with the key",
                ":returns: None or a PutInfo object",
            ],
        )

    def test_multiline_javadoc_param_folds_continuation(self):
        """A wrapped @param description folds onto its single :param: line.

        Would fail if continuation folding stopped joining wrapped lines, leaving
        a stray unindented paragraph after the field instead of one folded line.
        """
        lines = [
            "@param input_data: the data to load, given as a sequence of",
            "key/value pairs to insert in bulk.",
        ]
        self.assertEqual(
            javadoc_to_rest(lines),
            [
                ":param input_data: the data to load, given as a sequence of "
                "key/value pairs to insert in bulk.",
            ],
        )

    def test_colonless_javadoc_tags_convert(self):
        """Colon-less @param/@return tags (no ``:`` after the tag) also convert.

        Would fail if the tag regexes required the colon, letting the colon-less
        form used in system/queues and system/stores fall through unconverted
        into the rendered output without any Sphinx warning.
        """
        lines = [
            "@param memory_limit The memory limit in bytes to use for the queue.",
            "@return The number of elements inserted into this queue so far.",
        ]
        self.assertEqual(
            javadoc_to_rest(lines),
            [
                ":param memory_limit: The memory limit in bytes to use for the queue.",
                ":returns: The number of elements inserted into this queue so far.",
            ],
        )

    def test_native_rest_return_folds_and_is_verbatim(self):
        """A native :return: field folds its continuation and is not rewritten.

        Would fail if native reST fields lost their continuation folding, or if
        :return: were rewritten to :returns: instead of kept verbatim.
        """
        lines = [
            ":return: A PutInfo instance: NoSplit if it fit, or SplitHappens (wrapping",
            "the two new nodes and the pivot) if this insertion caused a split.",
        ]
        self.assertEqual(
            javadoc_to_rest(lines),
            [
                ":return: A PutInfo instance: NoSplit if it fit, or SplitHappens "
                "(wrapping the two new nodes and the pivot) if this insertion "
                "caused a split.",
            ],
        )

    def test_blank_line_closes_field(self):
        """A blank line after a field stops the following prose from folding in.

        Would fail if the blank-line close were dropped, so trailing prose was
        wrongly appended to the preceding :param: body.
        """
        lines = [
            "@param key: the key",
            "",
            "This paragraph is separate prose, not part of the parameter.",
        ]
        self.assertEqual(
            javadoc_to_rest(lines),
            [
                ":param key: the key",
                "",
                "This paragraph is separate prose, not part of the parameter.",
            ],
        )

    def test_prose_only_unchanged(self):
        """A docstring with no tags is returned exactly as given.

        Would fail if prose lines before any field were folded together or
        otherwise rewritten instead of passed through verbatim.
        """
        lines = [
            "This index maps keys to values.",
            "",
            "It supports point lookups and range scans.",
        ]
        self.assertEqual(javadoc_to_rest(lines), lines)

    def test_empty_description_keeps_trailing_space(self):
        """An empty @param/@return description converts with a trailing space.

        Would fail if the empty-body f-string output changed; the trailing space
        after ``:param key:`` / ``:returns:`` is a known cosmetic artefact of the
        ``f":param {name}: {desc}"`` template when the description is empty, not
        an idealized ``:param key:`` with no trailing space.
        """
        # Known cosmetic limitation: the f-string always emits the separating
        # space, so an empty description yields a trailing space. Asserting the
        # real output locks the current (harmless) behaviour.
        self.assertEqual(javadoc_to_rest(["@param key:"]), [":param key: "])
        self.assertEqual(javadoc_to_rest(["@return"]), [":returns: "])

    def test_directive_without_blank_line_folds_into_field(self):
        """A ``.. note::`` directly after a field folds into the field body.

        Would fail if continuation folding stopped swallowing a directive that
        has no blank line before it. Known limitation: a directive with no
        preceding blank line is folded into the field; the corpus always
        separates them with a blank line, so this never bites in practice.
        """
        lines = ["@param key: the key", ".. note:: this is a note"]
        self.assertEqual(
            javadoc_to_rest(lines),
            [":param key: the key .. note:: this is a note"],
        )


class FindResidualTagsTest(unittest.TestCase):

    def test_malformed_param_tags_reported_as_residual(self):
        """Javadoc tags that conversion cannot rewrite are reported.

        ``find_residual_tags`` runs on the original docstring lines. Would fail
        if it stopped flagging tags ``javadoc_to_rest`` cannot rewrite (a bare
        ``@param`` with no name, and ``@param  : x`` whose colon precedes the
        name) — exactly the silent conversion misses the Sphinx ``-W`` gate
        relies on this to catch.
        """
        original = ["@param", "@param  : x"]
        self.assertEqual(find_residual_tags(original), ["@param", "@param  : x"])

    def test_malformed_tag_after_valid_field_still_reported(self):
        """A malformed tag folded into a preceding field is still reported.

        This is the guard's whole point: ``javadoc_to_rest`` folds the bare
        ``@param`` into the valid field's body, so it vanishes from the output.
        Would fail if ``find_residual_tags`` inspected the converted output
        instead of the original lines, missing the silent conversion failure.
        """
        original = ["@param key: the key", "@param"]
        # Folding removes the stray tag from the converted output...
        self.assertEqual(javadoc_to_rest(original), [":param key: the key @param"])
        # ...but scanning the original still surfaces it.
        self.assertEqual(find_residual_tags(original), ["@param"])

    def test_fully_converted_docstring_has_no_residuals(self):
        """A docstring whose tags all convert yields no residual tags.

        Would fail if ``find_residual_tags`` flagged well-formed ``@param`` /
        ``@return`` tags (which the converter handles) and raised a spurious
        Sphinx warning on every correctly documented docstring.
        """
        original = ["Adds a mapping.", "", "@param key: the key", "@return: None"]
        self.assertEqual(find_residual_tags(original), [])


class ProcessDocstringHookTest(unittest.TestCase):

    def test_converts_lines_in_place(self):
        """The autodoc hook writes converted lines back into the passed list.

        autodoc only picks up changes made to the same list object it passed in.
        The caller's list holding the converted content after the call is what
        proves the write-back: a regression from ``lines[:] = ...`` to a
        rebinding ``lines = ...`` would leave the caller's list with the original
        ``@param``/``@return`` content, failing the assertion below and silently
        disabling conversion site-wide in the real build.
        """
        lines = ["@param key: the key", "@return: the value"]
        conf._process_docstring(None, "method", "m", None, None, lines)
        self.assertEqual(lines, [":param key: the key", ":returns: the value"])

    def test_warns_on_residual_tag(self):
        """A tag conversion cannot rewrite triggers a warning (drives ``-W``).

        Would fail if the residual check were dropped, so a silent conversion
        miss no longer failed the ``sphinx-build -W`` gate.
        """
        with mock.patch.object(conf.logger, "warning") as warn:
            conf._process_docstring(None, "method", "m", None, None, ["@param"])
        warn.assert_called_once()

    def test_no_warning_when_all_converted(self):
        """A well-formed docstring produces no warning.

        Would fail if the hook flagged valid tags, raising a spurious warning
        (and, under ``-W``, a build error) on every correctly documented object.
        """
        with mock.patch.object(conf.logger, "warning") as warn:
            conf._process_docstring(None, "method", "m", None, None, ["@param k: v"])
        warn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
