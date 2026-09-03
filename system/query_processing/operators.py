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

"""Concrete query-processing operators: scan, filter, simple hash join, semi-join, print, collect, count."""

import math
import pickle
import re

from system.interfaces.query_processing.operators import Operator


class Relation(Operator):
    """
    Relation operator to iterate over the given list of tuples.
    """

    def __init__(self, name: str, data: list) -> None:
        """Create a relation operator over an in-memory list of tuples.

        :param name: Relation name.
        :param data: The tuples this operator iterates over.
        """
        super().__init__(None, None)
        self.name = name
        self.data = data

    def interpret_open(self):
        """See :meth:`Operator.interpret_open`.

        Source operator: pushes every tuple of the in-memory list to the parent.
        """
        # iterate over each tuple in list
        for tup in self.data:
            # push current tuple to parent operator
            self.parent.interpret_next(tup)

    def interpret_next(self, tup):
        """See :meth:`Operator.interpret_next`.

        Unreachable: a source operator has no child that could push to it.
        """
        # unreachable as this operator does not have a child operator that could call this method
        raise AssertionError("Expected to be unreachable")

    def interpret_close(self):
        """See :meth:`Operator.interpret_close`.

        Leaf/source operator: no child to close.
        """
        # leaf/source operator: no child operator to close

    def compile(self, emit):
        """See :meth:`Operator.compile`.

        Not supported for in-memory relations.
        """
        raise NotImplementedError

    def dump(self, indent):
        """See :meth:`Operator.dump`."""
        print(self.indent_(indent) + f"Relation({self.name})")


class Scan(Operator):
    """
    Scan operator to iterate over the given number of tuples in the underlying storage file.
    """

    def __init__(self, file: str, num_tuples: int = math.inf) -> None:
        """Create a scan operator over a pickled storage file.

        :param file: Path to the storage file holding the pickled tuples.
        :param num_tuples: Maximum number of tuples to read; unbounded by default.
        """
        super().__init__(None, None)
        self.file = file
        self.num_tuples = num_tuples

    def interpret_open(self):
        """See :meth:`Operator.interpret_open`.

        Source operator: reads the pickled tuples from the storage file and
        pushes up to ``num_tuples`` of them to the parent.
        """
        # open file serving as storage
        with open(self.file, "rb") as f:
            # initialize iteration counter
            i = 0
            # iterate over each tuple in file
            for tup in pickle.load(f):
                if i < self.num_tuples:
                    # push current tuple to parent operator
                    self.parent.interpret_next(tup)
                    # increment iteration counter
                    i += 1
                else:
                    # abort iteration
                    break

    def interpret_next(self, tup):
        """See :meth:`Operator.interpret_next`.

        Unreachable: a source operator has no child that could push to it.
        """
        # unreachable as this operator does not have a child operator that could call this method
        raise AssertionError("Expected to be unreachable")

    def interpret_close(self):
        """See :meth:`Operator.interpret_close`.

        Leaf/source operator: no child to close.
        """
        # leaf/source operator: no child operator to close

    def compile(self, emit):
        """See :meth:`Operator.compile`.

        Emits a loop over the pickled file, optionally bounded by ``num_tuples``.
        """
        if self.num_tuples == math.inf:
            return f"with open('{self.file}', 'rb') as f:\n    for tup in pickle.load(f):\n        {self.indent_emit_(emit, 2)}"
        return (
            f"with open('{self.file}', 'rb') as f:\n    i = 0\n    for tup in pickle.load(f):\n        "
            f"if i < {self.num_tuples}:\n            {self.indent_emit_(emit, 3)}\n            i += 1\n        else:\n            break"
        )

    def dump(self, indent):
        """See :meth:`Operator.dump`."""
        if self.num_tuples == math.inf:
            print(self.indent_(indent) + f"Scan({self.file})")
        else:
            print(self.indent_(indent) + f"Scan({self.file}, {self.num_tuples})")


class Filter(Operator):
    """
    Filter operator to select tuples according to the given predicate.
    """

    def __init__(self, child: Operator, pred: str):
        """Create a filter operator over a single child.

        :param child: The child operator supplying the tuples to filter.
        :param pred: Predicate expression evaluated per tuple.
        """
        super().__init__(None, [child])
        self.pred = pred
        child.set_parent(self)

    def interpret_open(self):
        """See :meth:`Operator.interpret_open`.

        Opens the single child operator.
        """
        # open child operator
        self.children[0].interpret_open()

    def interpret_next(self, tup):
        """See :meth:`Operator.interpret_next`.

        Pushes the tuple to the parent only if the predicate evaluates to true.
        """
        # check predicate for given tuple
        if eval(self.pred, {}, tup):
            # push current tuple to parent operator
            self.parent.interpret_next(tup)

    def interpret_close(self):
        """See :meth:`Operator.interpret_close`.

        Closes the single child operator.
        """
        # close child operator
        self.children[0].interpret_close()

    def compile(self, emit):
        """See :meth:`Operator.compile`.

        Wraps the child's compiled code in an ``if`` guarding on the predicate.
        """
        compiled_pred = re.sub("([a-zA-Z]+)", r"tup['\1']", self.pred)
        return self.children[0].compile(
            f"if {compiled_pred}:\n    {self.indent_emit_(emit)}"
        )

    def dump(self, indent):
        """See :meth:`Operator.dump`."""
        print(self.indent_(indent) + f"Filter on `{self.pred}`")
        self.children[0].dump(indent + 2)


class SHJ(Operator):
    """
    Simple-hash join operator to join the two children inputs according to the given join attributes.
    """

    def __init__(
        self,
        left_child: Operator,
        right_child: Operator,
        left_attr: str,
        right_attr: str,
    ):
        """Create a simple-hash join over a left (build) and right (probe) child.

        :param left_child: Build-side child operator.
        :param right_child: Probe-side child operator.
        :param left_attr: Join attribute on the build side.
        :param right_attr: Join attribute on the probe side.
        """
        super().__init__(None, [left_child, right_child])
        self.left_attr = left_attr
        self.right_attr = right_attr
        left_child.set_parent(self)
        right_child.set_parent(self)

    def interpret_open(self):
        """See :meth:`Operator.interpret_open`.

        Builds the hash table from the left child, then probes it with the right child.
        """
        # create fresh hash table
        self.ht = {}
        # set to build phase
        self.is_build_phase = True
        # open build child operator
        self.children[0].interpret_open()
        # set to probe phase
        self.is_build_phase = False
        # open probe child operator
        self.children[1].interpret_open()

    def interpret_next(self, tup):
        """See :meth:`Operator.interpret_next`.

        In the build phase inserts the tuple into the hash table; in the probe
        phase joins it with matching build tuples and pushes the merged tuples.
        """
        # check if build phase is active
        if self.is_build_phase:
            # insert current tuple into hash table
            self.ht.setdefault(tup[self.left_attr], []).append(tup)
        else:
            # probe hash table for current tuple and iterate over results
            for tup2 in self.ht.get(tup[self.right_attr], []):
                # merge current tuple with probed result and push it to parent operator
                self.parent.interpret_next(tup | tup2)

    def interpret_close(self):
        """See :meth:`Operator.interpret_close`.

        Closes both child operators.
        """
        # close children operators
        self.children[0].interpret_close()
        self.children[1].interpret_close()

    def compile(self, emit):
        """See :meth:`Operator.compile`.

        Emits the build loop over the left child followed by the probe loop over
        the right child.
        """
        return (
            "ht = dict()\n"
            + self.children[0].compile(
                f"ht.setdefault(tup['{self.left_attr}'], list()).append(tup)"
            )
            + "\n"
            + self.children[1].compile(
                f"for tup2 in ht.get(tup['{self.right_attr}'], list()):\n    tup = tup | tup2\n    {self.indent_emit_(emit)}"
            )
        )

    def dump(self, indent):
        """See :meth:`Operator.dump`."""
        print(self.indent_(indent) + f"SHJ on `{self.left_attr}={self.right_attr}`")
        self.children[0].dump(indent + 2)
        self.children[1].dump(indent + 2)


class SemiJ(Operator):
    """
    (Left) Semi-join operator to reduce the first input relation based on the join results according to the given join attributes with the second input relation.
    """

    def __init__(
        self,
        left_child: Operator,
        right_child: Operator,
        left_attr: str,
        right_attr: str,
    ):
        """Create a left semi-join over a left (probe) and right (build) child.

        :param left_child: Probe-side child operator, whose tuples are reduced.
        :param right_child: Build-side child operator.
        :param left_attr: Join attribute on the probe (left) side.
        :param right_attr: Join attribute on the build (right) side.
        """
        super().__init__(None, [left_child, right_child])
        self.left_attr = left_attr
        self.right_attr = right_attr
        left_child.set_parent(self)
        right_child.set_parent(self)

    def interpret_open(self):
        """See :meth:`Operator.interpret_open`.

        Builds the hash table from the RIGHT child, then probes it with the LEFT child.
        """
        # create fresh hash table
        self.ht = {}
        # set to build phase
        self.is_build_phase = True
        # open RIGHT child as build operator
        self.children[1].interpret_open()
        # set to probe phase
        self.is_build_phase = False
        # open LEFT child as probe operator
        self.children[0].interpret_open()

    def interpret_next(self, tup):
        """See :meth:`Operator.interpret_next`.

        In the build phase inserts the right tuple into the hash table; in the
        probe phase pushes the left tuple unchanged if a match exists (no merge).
        """
        # check if build phase is active
        if self.is_build_phase:
            # insert current tuple into hash table
            self.ht.setdefault(tup[self.right_attr], []).append(tup)
        else:
            # probe hash table for current tuple
            if self.ht.get(tup[self.left_attr], []):
                # push matching tuple to parent operator
                self.parent.interpret_next(tup)

    def interpret_close(self):
        """See :meth:`Operator.interpret_close`.

        Closes both child operators.
        """
        # close children operators
        self.children[0].interpret_close()
        self.children[1].interpret_close()

    def compile(self, emit):
        """See :meth:`Operator.compile`.

        Not supported for the semi-join operator.
        """
        raise NotImplementedError

    def dump(self, indent):
        """See :meth:`Operator.dump`."""
        print(self.indent_(indent) + f"SemiJ on `{self.left_attr}={self.right_attr}`")
        self.children[0].dump(indent + 2)
        self.children[1].dump(indent + 2)


class Print(Operator):
    """
    Print operator to print tuples to the console.
    """

    def __init__(self, child: Operator):
        """Create a print operator over a single child.

        :param child: The child operator supplying the tuples to print.
        """
        super().__init__(None, [child])
        child.set_parent(self)

    def interpret_open(self):
        """See :meth:`Operator.interpret_open`.

        Opens the single child operator.
        """
        # open child operator
        self.children[0].interpret_open()

    def interpret_next(self, tup):
        """See :meth:`Operator.interpret_next`.

        Prints the tuple's values to the console; this is a sink, so nothing is pushed.
        """
        # print current tuple
        print(tuple(tup.values()))

    def interpret_close(self):
        """See :meth:`Operator.interpret_close`.

        Closes the single child operator.
        """
        # close child operator
        self.children[0].interpret_close()

    def compile(self):
        """See :meth:`Operator.compile`.

        Sink operator: emits the child's code with a leading ``import pickle`` and
        a ``print`` of each tuple. Takes no ``emit`` argument.
        """
        # import pickle module here s.t. it appears at the beginning of the compiled code
        return "import pickle\n\n" + self.children[0].compile(
            "print(tuple(tup.values()))"
        )

    def dump(self):
        """See :meth:`Operator.dump`.

        Sink operator: takes no ``indent`` argument.
        """
        print("Print")
        self.children[0].dump(2)


class Collect(Operator):
    """
    Collect operator to collect all resulting tuples.
    """

    def __init__(self, child: Operator):
        """Create a collect operator over a single child.

        :param child: The child operator supplying the tuples to collect.
        """
        super().__init__(None, [child])
        child.set_parent(self)

    def interpret_open(self):
        """See :meth:`Operator.interpret_open`.

        Resets the result list and opens the single child operator.
        """
        # create fresh result list
        self.result = []
        # open child operator
        self.children[0].interpret_open()

    def interpret_next(self, tup):
        """See :meth:`Operator.interpret_next`.

        Appends the tuple's values to the result list; this is a sink, so nothing is pushed.
        """
        # add current tuple to result
        self.result.append(tuple(tup.values()))

    def interpret_close(self):
        """See :meth:`Operator.interpret_close`.

        Closes the single child operator.
        """
        # close child operator
        self.children[0].interpret_close()

    def compile(self):
        """See :meth:`Operator.compile`.

        Sink operator: emits the child's code collecting each tuple into a
        ``result`` list. Takes no ``emit`` argument.
        """
        # import pickle module here s.t. it appears at the beginning of the compiled code
        return "import pickle\n\nresult = list()\n" + self.children[0].compile(
            "result.append(tuple(tup.values()))"
        )

    def dump(self):
        """See :meth:`Operator.dump`.

        Sink operator: takes no ``indent`` argument.
        """
        print("Collect")
        self.children[0].dump(2)


class Count(Operator):
    """
    Count operator to count all resulting tuples.
    """

    def __init__(self, child: Operator):
        """Create a count operator over a single child.

        :param child: The child operator whose tuples are counted.
        """
        super().__init__(None, [child])
        child.set_parent(self)

    def interpret_open(self):
        """See :meth:`Operator.interpret_open`.

        Resets the tuple counter and opens the single child operator.
        """
        # reset number of tuples
        self.num_tuples = 0
        # open child operator
        self.children[0].interpret_open()

    def interpret_next(self, tup):
        """See :meth:`Operator.interpret_next`.

        Increments the tuple counter; this is a sink, so nothing is pushed.
        """
        # increment number of tuples
        self.num_tuples += 1

    def interpret_close(self):
        """See :meth:`Operator.interpret_close`.

        Closes the single child operator.
        """
        # close child operator
        self.children[0].interpret_close()

    def compile(self):
        """See :meth:`Operator.compile`.

        Sink operator: emits the child's code incrementing a ``num_tuples``
        counter. Takes no ``emit`` argument.
        """
        # import pickle module here s.t. it appears at the beginning of the compiled code
        return "import pickle\n\nnum_tuples = 0\n" + self.children[0].compile(
            "num_tuples += 1"
        )

    def dump(self):
        """See :meth:`Operator.dump`.

        Sink operator: takes no ``indent`` argument.
        """
        print("Count")
        self.children[0].dump(2)
