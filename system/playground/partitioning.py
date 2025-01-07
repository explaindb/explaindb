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
        self.id = RailElement.id_counter
        RailElement.id_counter += 1

    @abstractmethod
    def find_reachable_platform(self) -> Platform:
        """Finds a reachable platform, i.e. this is the platform we end up at if we follow the current positions of
        the gates recursively."""
        pass

    @abstractmethod
    def show(self, rec_depth: int = 0):
        """Shows the content of this element."""
        pass


class Gate(RailElement):
    """A gate has a position ("left" or "right") and two children RailElements (left and right)."""

    def __init__(self, left: RailElement = None, right: RailElement = None):
        super().__init__()
        self.position = rnd.choice(["left", "right"])
        self.left = left
        self.right = right

    def switch(self):
        """Switches the position of the gate."""
        self.position = "left" if self.position == "right" else "right"

    def __repr__(self):
        return f"Gate{self.id}({self.position})"

    def find_reachable_platform(self) -> Platform:
        return (
            self.left.find_reachable_platform()
            if self.position == "left"
            else self.right.find_reachable_platform()
        )

    def show(self, rec_depth: int = 0):
        print("\t" * rec_depth, self)
        self.left.show(rec_depth + 1)
        self.right.show(rec_depth + 1)


class Platform(RailElement):
    """A platform has a counter that is increased every time a train visits it."""

    def __init__(self, visit_counter: int = 0):
        super().__init__()
        self.visit_counter = visit_counter

    def __repr__(self):
        return f"Platform{self.id}({self.visit_counter})"

    def find_reachable_platform(self) -> Platform:
        """Returns self."""
        return self

    def increase_visit_counter(self):
        """Increases the visit counter by one."""
        self.visit_counter += 1

    def show(self, rec_depth: int = 0):
        print("\t" * rec_depth, self)


class GateTree:
    def __init__(self, number_of_gate_levels: int):
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
        else:
            left: RailElement = self._build_tree(tree_depth + 1)
            right: RailElement = self._build_tree(tree_depth + 1)
            _gate: Gate = Gate(left=left, right=right)
            self.gates.append(_gate)
            return _gate

    def show(self):
        self.root.show()

    def find_reachable_platform(self) -> Platform:
        return self.root.find_reachable_platform()


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
