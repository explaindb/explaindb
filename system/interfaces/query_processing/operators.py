"""Abstract interface for query-processing operators."""

from abc import ABC, abstractmethod
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
        Interpreter: `close()` method in push-based iterator model, i.e., closes the operator. This may be used to free
        resources like temporary files.
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
