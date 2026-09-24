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

"""Toy train-network simulation exploring uniform load partitioning in a DBMS."""

from __future__ import annotations
from abc import ABC, abstractmethod
import random as rnd

rnd.seed(42)

# This is a simple simulation of a train network with gates and platforms inspired by the game
# "Tschu-tschu, kleine Eisenbahn" by Haba:
# https://gesellschaftsspiele.spielen.de/uploads/files/3693/5ab95956e4559.pdf
# The binary tree used in the game is represented by a binary RailElement tree of Gate(s) and Platform(s).

# Do all platforms get visited equally often?
# What if we partitioned data or any type of load like that in a DBMS? Would that make sense and create a uniform
# distribution?


class RailElement(ABC):
    """A rail element is either a Gate or a Platform. It has an id and can find a reachable platform."""

    id_counter: int = 0

    def __init__(self):
        """Assigns this element a process-wide unique id from the shared counter."""
        self.id = RailElement.id_counter
        RailElement.id_counter += 1

    @abstractmethod
    def find_reachable_platform(self) -> Platform:
        """Finds a reachable platform, i.e. this is the platform we end up at if we follow the current positions of
        the gates recursively."""

    @abstractmethod
    def show(self, rec_depth: int = 0):
        """Shows the content of this element."""


class Gate(RailElement):
    """A gate has a position ("left" or "right") and two children RailElements (left and right)."""

    def __init__(self, left: RailElement = None, right: RailElement = None):
        """Creates a gate with a random initial position and two child elements.

        :param left: the child reached when the position is ``"left"``.
        :param right: the child reached when the position is ``"right"``.
        """
        super().__init__()
        self.position = rnd.choice(["left", "right"])
        self.left = left
        self.right = right

    def switch(self):
        """Switches the position of the gate."""
        self.position = "left" if self.position == "right" else "right"

    def __repr__(self):
        """Renders as ``Gate<id>(<position>)``, e.g. ``Gate3(left)``."""
        return f"Gate{self.id}({self.position})"

    def find_reachable_platform(self) -> Platform:
        """Follows the current position into the corresponding child.

        :return: the platform reached by recursing into the ``left`` or
            ``right`` child according to this gate's current position.
        """
        return (
            self.left.find_reachable_platform()
            if self.position == "left"
            else self.right.find_reachable_platform()
        )

    def show(self, rec_depth: int = 0):
        """Prints this gate, then recursively both children one level deeper.

        :param rec_depth: indentation depth in tab stops for this gate.
        """
        print("\t" * rec_depth, self)
        self.left.show(rec_depth + 1)
        self.right.show(rec_depth + 1)


class Platform(RailElement):
    """A platform has a counter that is increased every time a train visits it."""

    def __init__(self, visit_counter: int = 0):
        """Creates a platform.

        :param visit_counter: the initial visit count (default 0).
        """
        super().__init__()
        self.visit_counter = visit_counter

    def __repr__(self):
        """Renders as ``Platform<id>(<visit_counter>)``, e.g. ``Platform7(42)``."""
        return f"Platform{self.id}({self.visit_counter})"

    def find_reachable_platform(self) -> Platform:
        """Returns self."""
        return self

    def increase_visit_counter(self):
        """Increases the visit counter by one."""
        self.visit_counter += 1

    def show(self, rec_depth: int = 0):
        """Prints this platform.

        :param rec_depth: indentation depth in tab stops for this platform.
        """
        print("\t" * rec_depth, self)


class GateTree:
    """A complete binary tree of gates (inner nodes) and platforms (leaves).

    The tree has ``number_of_gate_levels`` levels of gates and therefore
    ``2 ** number_of_gate_levels`` platforms as leaves. Flat lists of all gates
    and all platforms are kept alongside the root for random access.
    """

    def __init__(self, number_of_gate_levels: int):
        """Builds the tree and records its gates and platforms.

        :param number_of_gate_levels: number of gate levels; the tree ends in
            ``2 ** number_of_gate_levels`` platforms.
        """
        # flat list of all gates in the tree:
        self.gates: list[Gate] = []

        self.number_of_gate_levels = number_of_gate_levels

        # flat list of all platforms in the tree:
        self.platforms: list[Platform] = []

        self.root: RailElement = self._build_tree()

    def _build_tree(self, tree_depth: int = 0) -> RailElement:
        """Builds a binary tree of gates and platforms.
        Inner nodes are gates, leaves are platforms.
        """
        if tree_depth == self.number_of_gate_levels:
            _platform: Platform = Platform()
            self.platforms.append(_platform)
            return _platform
        left: RailElement = self._build_tree(tree_depth + 1)
        right: RailElement = self._build_tree(tree_depth + 1)
        _gate: Gate = Gate(left=left, right=right)
        self.gates.append(_gate)
        return _gate

    def show(self):
        """Prints the whole tree starting at the root."""
        self.root.show()

    def find_reachable_platform(self) -> Platform:
        """Follows the current gate positions from the root.

        :return: the platform reached from the root given the gates' positions.
        """
        return self.root.find_reachable_platform()


# Playground demo: build a gate tree, run a million random walks recording how
# often each platform is reached, then print the tree. Guarded so it runs only
# on direct execution (`python partitioning.py`), not on import -- importing the
# module (e.g. from a notebook or the docs build) must have no side effect.
if __name__ == "__main__":
    gt = GateTree(3)
    # gt.show()

    for i in range(1000000):
        # find the reachable platform:
        platform: Platform = gt.find_reachable_platform()
        # increase the visit counter:
        platform.increase_visit_counter()
        # switch a random gate:
        gate: Gate = rnd.choice(gt.gates)
        gate.switch()

    # print the tree including the visit counters of all platforms:
    gt.show()
