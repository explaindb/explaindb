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

"""Sphinx configuration for the ExplainDB API-reference site built from docstrings."""

import os
import sys

from sphinx.application import Sphinx
from sphinx.ext.autodoc import Options
from sphinx.util import logging as sphinx_logging

# This file's directory, resolved independently of the build's working directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
# Make the ``system`` namespace package importable so autodoc can introspect it
# (the package sits two levels up at the repo root)...
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))
# ...and this directory, so the ``javadoc`` sibling module below resolves.
sys.path.insert(0, _HERE)

from javadoc import (  # noqa: E402  (import after sys.path setup)
    find_residual_tags,
    javadoc_to_rest,
)

logger = sphinx_logging.getLogger(__name__)

project = "ExplainDB"
copyright = "2026, Prof. Dr. Jens Dittrich, Saarland University"  # noqa: A001
author = "Prof. Dr. Jens Dittrich"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
]

html_theme = "furo"

# Show classes with their members, and keep source order rather than alphabetical.
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
autodoc_member_order = "bysource"


def _process_docstring(
    app: Sphinx,
    what: str,
    name: str,
    obj: object,
    options: Options,
    lines: list[str],
) -> None:
    """autodoc-process-docstring hook: convert Javadoc tags to reST in place.

    See :func:`javadoc.javadoc_to_rest` for the transform. autodoc passes the
    docstring as the mutable list ``lines``; we replace its contents with the
    converted lines. Any Javadoc tag the conversion cannot rewrite is reported
    as a warning, which the ``-W`` build gate promotes to an error so a silent
    miss cannot slip into the rendered output. The check runs on the original
    lines (before conversion), so a malformed tag is caught even if conversion
    would have folded it into a preceding field.
    """
    residual = find_residual_tags(lines)
    lines[:] = javadoc_to_rest(lines)
    if residual:
        logger.warning(
            "unconverted Javadoc tag(s) in docstring of %s: %s",
            name,
            "; ".join(residual),
        )


def setup(app: Sphinx) -> None:
    """Register the Javadoc-to-reST docstring hook with Sphinx."""
    app.connect("autodoc-process-docstring", _process_docstring)
