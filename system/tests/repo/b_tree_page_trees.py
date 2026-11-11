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

"""The four trees and the two queries of the B-tree page (``visualizations/b-tree.html``), as two tests compare them.

The page builds its start tree from the nested lists ``START`` in its script and inserts the keys ``PUTS`` one after
the other with ``insertTree``, its JavaScript copy of the rules of ``BPlusTree.put`` (``system/indexes/btree.py``). It
writes the start tree and the tree after each insert into ``data-trees`` of its stage. Two tests check these trees
against ``EXPECTED_DIGESTS``: ``BTreePageTest`` in ``test_visualizations.py`` the trees the page writes, and
``test_b_tree_page_data.py`` the trees the real ``BPlusTree`` makes from ``START`` and ``PUTS``. Together they show
that the page's trees are the code's. The same two tests check the film's point query and range query on the start
tree against ``EXPECTED_POINT_PATH`` and ``EXPECTED_RANGE_HITS``: the page writes them into ``data-point-path`` and
``data-range-hits``, and the real ``BPlusTree`` gives them with ``get`` and ``get_all_in_range``.

This module uses the standard library only: the CI job ``visualization_test`` installs nothing but Playwright, so the
browser test cannot import ``system.indexes`` (which needs IPython and graphviz).
"""

import hashlib
import json
import re
from pathlib import Path

# Anchored to this file so discovery works regardless of the caller's cwd.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
B_TREE_PAGE: Path = REPO_ROOT / "visualizations" / "b-tree.html"

# a tree as plain data, as the page writes it into data-trees: a leaf is the list of its keys, an inner node a dict
# {"keys": [...], "children": [...]}:
type Tree = list[int] | dict[str, list[int] | list[Tree]]

# a tree as the page's START writes it: an inner node is the list of its subtrees, a leaf the list of its keys; unlike
# Tree, without the keys of the inner nodes:
type NestedLeaves = list[int] | list[NestedLeaves]

# the SHA-256 digest of each tree in canonical form (see canonical()): the start tree, then the tree after each of the
# three puts. Taken from the trees that the real BPlusTree(8, 16) makes from the page's START and PUTS
# (test_b_tree_page_data.py); a list, so that a failing test shows which of the four trees differs:
EXPECTED_DIGESTS: list[str] = [
    "9a63bab611f3da2a3960a120c14842739037bc9ef7e8284f769f4e2271e3f466",
    "c908bdcf0f1673e44da19a0054b8955424c20e00be76b70cafce4af900e30b65",
    "eebf8b8b2fe760c782b352dfd6d8855d00508d2c1c1cb27e375a2f964e507d42",
    "522a5b6295f59e0f6db5100a4b88e12a19017aaa7d18309c063c9cb8189cee89",
]

# the film's point query (its key, 7013, is POINT_KEY in the page, see read_queries()): the keys of each node on its
# way, from the root down to the leaf that holds the key, as the code's get() visits them on the start tree. The leaf's
# 16 keys are two lists joined with +, only so that black keeps them on two lines instead of one key per line:
EXPECTED_POINT_PATH: list[list[int]] = [
    [2114, 3161, 4164, 4866, 5797, 7381, 8212, 9159],
    [5911, 6063, 6250, 6476, 6631, 6812, 7068, 7237],
    [6847, 6876, 6903, 6932, 6961, 6998, 7031, 7048],
    [6998, 6999, 7002, 7008, 7010, 7012, 7013, 7014]
    + [7016, 7017, 7020, 7021, 7022, 7025, 7027, 7030],
]

# the film's range query (from 6267 to 6306, both included: RANGE in the page, see read_queries()): the keys that the
# code's get_all_in_range() finds on the start tree:
EXPECTED_RANGE_HITS: list[int] = [
    6268,
    6269,
    6271,
    6274,
    6275,
    6276,
    6277,
    6283,
    6286,
    6288,
    6290,
    6293,
    6294,
    6297,
    6299,
    6300,
    6305,
]

# the leaves that the film's range query reads, by their least keys: those the code's get_all_in_range() scans, from
# the leaf its way down lands in to the one with the first key after the range:
EXPECTED_RANGE_LEAVES: list[int] = [6250, 6271, 6299]

# a range whose least key falls between two leaves (6269 ends one, 6271 begins the next), on a copy of the page in
# BTreePageTest: the code's way down to 6270 lands in the leaf before the gap, so get_all_in_range() scans it as well,
# and so must the page:
BETWEEN_LEAVES_RANGE: tuple[int, int] = (6270, 6306)
EXPECTED_BETWEEN_LEAVES: list[int] = [6250, 6271, 6299]


def read_start_and_puts(page: Path = B_TREE_PAGE) -> tuple[NestedLeaves, list[int]]:
    """Reads the start tree and the keys to insert from the page's script.

    @param page: the HTML file of the B-tree page
    @return: ``START``, the start tree as nested lists (root -> subtrees -> … -> leaves, each leaf its sorted keys),
        and ``PUTS``, the keys the film inserts, in their order
    @raise ValueError: if the script has no line ``const START = [...];`` or ``const PUTS = [...];``
    """
    html: str = page.read_text(encoding="utf-8")
    values: list[list] = []
    for name in ("START", "PUTS"):
        # each is one line, a JSON array, possibly followed by a comment:
        match: re.Match[str] | None = re.search(
            rf"^\s*const {name} = (\[.*\]);", html, re.MULTILINE
        )
        if match is None:
            raise ValueError(f"{page.name} has no line 'const {name} = [...];'")
        values.append(json.loads(match.group(1)))
    return values[0], values[1]


def read_queries(page: Path = B_TREE_PAGE) -> tuple[int, tuple[int, int]]:
    """Reads the keys of the film's point query and range query from the page's script.

    @param page: the HTML file of the B-tree page
    @return: ``POINT_KEY``, the key the point query looks for, and ``RANGE``, the least and the greatest key of the
        range query (both included)
    @raise ValueError: if the script has no line ``const POINT_KEY = <key>, RANGE = [<key>, <key>];``
    """
    html: str = page.read_text(encoding="utf-8")
    match: re.Match[str] | None = re.search(
        r"^\s*const POINT_KEY = (\d+), RANGE = \[(\d+), (\d+)\];", html, re.MULTILINE
    )
    if match is None:
        raise ValueError(
            f"{page.name} has no line 'const POINT_KEY = <key>, RANGE = [<key>, <key>];'"
        )
    return int(match[1]), (int(match[2]), int(match[3]))


def canonical(tree: Tree) -> str:
    """Returns the tree as compact JSON with sorted keys, the same text for the same tree in Python and in the page."""
    return json.dumps(tree, separators=(",", ":"), sort_keys=True)


def digests(trees: list[Tree]) -> list[str]:
    """Returns the SHA-256 digest of each tree in canonical form, as hex strings."""
    return [
        hashlib.sha256(canonical(tree).encode("utf-8")).hexdigest() for tree in trees
    ]


def height(tree: Tree) -> int:
    """Returns the number of levels of the tree, the leaves included (a single leaf has height 1)."""
    return (1 + height(tree["children"][0])) if isinstance(tree, dict) else 1


def outline(tree: Tree, depth: int = 0) -> str:
    """Returns the tree as readable text: one line per node, from the root down, each subtree after its root.

    An inner node is written as ``keys [...]``, a leaf as ``leaf [...]``, each indented by two spaces per level below
    the root (depth: the level of tree's root).
    """
    indent: str = "  " * depth
    if isinstance(tree, dict):
        return "\n".join(
            [f"{indent}keys {tree['keys']}"]
            + [outline(child, depth + 1) for child in tree["children"]]
        )
    return f"{indent}leaf {tree}"


def digest_mismatches(trees: list[Tree]) -> str:
    """Returns a readable report of the trees whose digest is not the expected one, for the message of a test that
    compares the digests (which, failing, would show only hexadecimal digests).

    @param trees: the start tree, then the tree after each put
    @return: for each tree whose digest differs from the one in EXPECTED_DIGESTS at its place, which tree it is and
        its outline (see outline()), and whether the number of trees differs; empty if every digest is as expected
    """
    report: list[str] = []
    for number, (tree, digest) in enumerate(zip(trees, digests(trees))):
        if number < len(EXPECTED_DIGESTS) and digest == EXPECTED_DIGESTS[number]:
            continue
        name: str = "the start tree" if number == 0 else f"the tree after put {number}"
        report.append(f"{name} is not the expected one; it is:\n{outline(tree)}")
    if len(trees) != len(EXPECTED_DIGESTS):
        report.append(f"{len(trees)} trees instead of {len(EXPECTED_DIGESTS)}")
    return "\n".join(report)


def keys_of(tree: Tree) -> list[int]:
    """Returns the keys in the leaves of the tree, from the leftmost leaf to the rightmost."""
    if isinstance(tree, dict):
        return [key for child in tree["children"] for key in keys_of(child)]
    return list(tree)
