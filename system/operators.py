from abc import ABC, abstractmethod
import math
import pickle
from typing import Self


# tuples are represented as dictionary from attribute name to attribute value
Tuple = dict


class Operator(ABC):
    """
    Abstract operator interface to construct QEPs.
    """

    def __init__(self, parent: Self | None, children: list[Self] | None):
        self.parent = parent
        self.children = children

    def set_parent(self, parent: Self) -> None:
        self.parent = parent

    @abstractmethod
    def interpret_open(self) -> None:
        """
        Interpreter: `open()` method in push-based iterator model, i.e., initializes the operator.
        """
        raise NotImplementedError

    @abstractmethod
    def interpret_next(self, tup: Tuple) -> None:
        """
        Interpreter: `next()` method in push-based iterator model, i.e., processes the given tuple and
        optionally pushes the next tuple to the parent operator.
        :param tup: Pushed tuple to process.
        """
        raise NotImplementedError

    @abstractmethod
    def interpret_close(self) -> None:
        """
        Interpreter: `close()` method in push-based iterator model, i.e., closes the operator.
        """
        raise NotImplementedError

    @abstractmethod
    def compile(self, emit: str = None) -> str:
        """
        Compiler: Compiles the QEP rooted at `self` into Python code.
        :param emit: Parent code to emit.
        :return: Compiled QEP.
        """
        raise NotImplementedError

    @abstractmethod
    def dump(self, indent: int = 0) -> None:
        """
        Prints the QEP rooted at `self`.
        :param indent: Indentation level.
        """
        raise NotImplementedError

    @staticmethod
    def indent_emit_(emit: str, n: int = 1) -> str:
        """
        Indents the given code to emit.
        :param emit: Code to emit.
        :param n: Indentation level.
        :return: Indented code to emit.
        """
        indent = "    " * n
        return f"\n{indent}".join(emit.split("\n"))

    @staticmethod
    def indent_(n: int = 1) -> str:
        """
        Creates an indentation.
        :param n: Indentation level.
        :return: Indentation.
        """
        return " " * n


class Scan(Operator):
    """
    Scan operator to iterate over the given number of tuples in the underlying storage file.
    """

    def __init__(self, file: str, num_tuples: int = math.inf) -> None:
        super().__init__(None, None)
        self.file = file
        self.num_tuples = num_tuples

    def interpret_open(self):
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
        # close parent operator
        self.parent.interpret_close()

    def interpret_next(self, tup):
        raise AssertionError("Expected to be unreachable")

    def interpret_close(self):
        raise AssertionError("Expected to be unreachable")

    def compile(self, emit):
        if self.num_tuples == math.inf:
            return f"with open('{self.file}', 'rb') as f:\n    for tup in pickle.load(f):\n        {self.indent_emit_(emit, 2)}"
        else:
            return (
                f"with open('{self.file}', 'rb') as f:\n    i = 0\n    for tup in pickle.load(f):\n        "
                f"if i < {self.num_tuples}:\n            {self.indent_emit_(emit, 3)}\n            i += 1\n        else:\n            break"
            )

    def dump(self, indent):
        print(self.indent_(indent) + f"Scan({self.file}, {self.num_tuples})")


class Filter(Operator):
    """
    Filter operator to select tuples according to the given predicate.
    """

    def __init__(self, child: Operator, pred: str):
        super().__init__(None, [child])
        self.pred = pred
        child.set_parent(self)

    def interpret_open(self):
        # open child operator
        self.children[0].interpret_open()

    def interpret_next(self, tup):
        # check predicate for given tuple
        if eval(self.pred, dict(), tup):
            # push current tuple to parent operator
            self.parent.interpret_next(tup)

    def interpret_close(self):
        # close parent operator
        self.parent.interpret_close()

    def compile(self, emit):
        return self.children[0].compile(
            f"if eval('{self.pred}', dict(), tup):\n    {self.indent_emit_(emit)}"
        )

    def dump(self, indent):
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
        super().__init__(None, [left_child, right_child])
        self.left_attr = left_attr
        self.right_attr = right_attr
        left_child.set_parent(self)
        right_child.set_parent(self)

    def interpret_open(self):
        # create fresh hash table
        self.ht = dict()
        # set to build phase
        self.is_build_phase = True
        # open build child operator
        self.children[0].interpret_open()

    def interpret_next(self, tup):
        # check if build phase is active
        if self.is_build_phase:
            # insert current tuple into hash table
            self.ht.setdefault(eval(f"tup['{self.left_attr}']"), []).append(tup)
        else:
            # probe hash table for current tuple and iterate over results
            for tup2 in self.ht.get(eval(f"tup['{self.right_attr}']"), []):
                # merge current tuple with probed result and push it to parent operator
                self.parent.interpret_next(tup | tup2)

    def interpret_close(self):
        # check if build phase has ended
        if self.is_build_phase:
            # set to probe phase
            self.is_build_phase = False
            # open probe child operator
            self.children[1].interpret_open()
        else:
            # close parent operator
            self.parent.interpret_close()

    def compile(self, emit):
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
        print(self.indent_(indent) + f"SHJ on `{self.left_attr}={self.right_attr}`")
        self.children[0].dump(indent + 2)
        self.children[1].dump(indent + 2)


class Print(Operator):
    """
    Print operator to print tuples to the console.
    """

    def __init__(self, child: Operator):
        super().__init__(None, [child])
        child.set_parent(self)

    def interpret_open(self):
        # open child operator
        self.children[0].interpret_open()

    def interpret_next(self, tup):
        # print current tuple
        print(tuple(tup.values()))

    def interpret_close(self):
        pass

    def compile(self):
        # import pickle module here s.t. it appears at the beginning of the compiled code
        return "import pickle\n\n" + self.children[0].compile(
            "print(tuple(tup.values()))"
        )

    def dump(self):
        print("Print")
        self.children[0].dump(2)


class Collect(Operator):
    """
    Collect operator to collect all resulting tuples.
    """

    def __init__(self, child: Operator):
        super().__init__(None, [child])
        child.set_parent(self)

    def interpret_open(self):
        # create fresh result list
        self.result = list()
        # open child operator
        self.children[0].interpret_open()

    def interpret_next(self, tup):
        # add current tuple to result
        self.result.append(tuple(tup.values()))

    def interpret_close(self):
        pass

    def compile(self):
        # import pickle module here s.t. it appears at the beginning of the compiled code
        return "import pickle\n\nresult = list()\n" + self.children[0].compile(
            "result.append(tuple(tup.values()))"
        )

    def dump(self):
        print("Collect")
        self.children[0].dump(2)


class Count(Operator):
    """
    Count operator to count all resulting tuples.
    """

    def __init__(self, child: Operator):
        super().__init__(None, [child])
        child.set_parent(self)

    def interpret_open(self):
        # reset number of tuples
        self.num_tuples = 0
        # open child operator
        self.children[0].interpret_open()

    def interpret_next(self, tup):
        # increment number of tuples
        self.num_tuples += 1

    def interpret_close(self):
        pass

    def compile(self):
        # import pickle module here s.t. it appears at the beginning of the compiled code
        return "import pickle\n\nnum_tuples = 0\n" + self.children[0].compile(
            "num_tuples += 1"
        )

    def dump(self):
        print("Count")
        self.children[0].dump(2)
