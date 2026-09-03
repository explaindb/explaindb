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

"""Problem type representing relation subsets as bit sequences for join enumeration."""

from __future__ import annotations
from system.bit_sequences import IntegerBitSequence
from typing import Iterator


class Problem(IntegerBitSequence):
    """
    Given a query graph of length n, a "problem" is a BitSequence of length n where each bit corresponds to a relation in the query graph.
    Note that these operations only work if there 1-1-mapping between positions in the bit sequence and relations,
    i.e., each bit always represents the same relation.

    This class defines additional operations for integer bit sequences to efficiently store and manage subsets of
    relations.
    """

    def __hash__(self) -> int:
        """
        Defines the hash value for the problem.
        :return: The hash of the problem.
        """
        return self.number

    def get_next(self, n: Problem) -> Problem:
        """
        Returns the next problem in a problem enumeration w.r.t to the problem n.
        The idea here is that we have a superset n, whose subsets we want to enumerate, where self is assumed
        to be subset of n. By applying the formula below to self, we obtain another subset n, which is the next larger
        (in terms of the represented integer) subset. Repeating this process will eventually
        allow us to enumerate all subsets of the superset n.
        :param n: The problem n whose problems are to be enumerated.
        :return: The next subset as a problem.
        """
        # The line below utilizes some bit-magic, so let's analyze what we want to achieve, and how this is done by
        # using the formula below. Assume we want to enumerate all subsets of the number 011010. For that we starting with
        # the least significant bit 000010. The next largest subset would be 001000. In order to obtain this number, we
        # first subtract the number representing n from the number representing self, which yields a 2-complemented
        # signed integer, i.e., 101000, which only contains the desired subset, as well as additional set bits due to the
        # 2-complements. In order to remove this additional bits, we then use a bitwise & to only get the desired subset
        # 01000. Repeating this process would then yield all possible subsets of n.
        return Problem((self.number - n.number) & n.number, len(self))

    def get_smaller_or_equal_relations(self) -> Problem:
        """
        Returns the problem containing all relations with a smaller/equal relation id (i.e. the bit representing the relation)
        than the smallest id in self.
        :return: The problem containing all relations with a smaller/equal relation id than the smallest id in self.
        """

        # The smallest id in the current problem is represented by the least significant bit, e.g., for the number
        # 010100, the least significant bit would be 2, and the corresponding problem would be 000100.
        # We now want a problem containing all relations whose id is smaller/equal than 2. For that we make
        # one bitshift to the left, yielding 001000, which is then subtracted by 1, yielding 000111
        return Problem((self.get_least_significant_bit().number << 1) - 1, len(self))

    def get_relation_id(self) -> int:
        """
        Returns the relation id of the problem, if it is a singleton (i.e. only one bit is set to True).
        :return: The relation id.
        """
        if self.number.bit_count() != 1:
            raise ValueError("The problem must be a singleton.")
        return self.number.bit_length() - 1

    @staticmethod
    def create_all_false_bit_sequence(represented_number_of_bits: int = 0) -> Problem:
        """See :meth:`BitSequence.create_all_false_bit_sequence`.

        Returns the empty problem (no relation selected) as a :class:`Problem`.
        """
        return Problem(0, represented_number_of_bits)

    class SingletonIterator:
        """
        An iterator to iterate through all singletons (i.e. a problem with only one bit set) of a given problem.
        """

        def __init__(self, problem: Problem):
            """
            :param problem: The problem to iterate.
            """
            self.problem: Problem = problem
            self.key_iterator: IntegerBitSequence.SetBitsIterator = (
                IntegerBitSequence.SetBitsIterator(problem)
            )

        def __iter__(self):
            return self

        def __next__(self) -> Problem:
            """Returns the next set bit of the problem as a singleton problem."""
            return Problem.get_problem_for_relation(
                next(self.key_iterator), len(self.problem)
            )

    def __iter__(self) -> Iterator[Problem]:
        """See :meth:`BitSequence.__iter__`.

        Yields each set bit as a singleton :class:`Problem` instead of as an
        integer position.
        """
        return Problem.SingletonIterator(self)

    def as_set(self) -> set[int]:
        """See :meth:`BitSequence.as_set`.

        Bypasses the singleton-yielding :meth:`__iter__` and returns the raw
        relation-id integers whose bit is set to True.
        """
        return set(bit for bit in Problem.SetBitsIterator(self))

    class SingletonReverseIterator:
        """
        An iterator to traverse the singletons (i.e. a problem with only one bit set) of a problem in reverse order,
        i.e., starting with the singleton containing the most-significant bit.
        """

        def __init__(self, problem: Problem):
            """
            :param problem: The problem to iterate.
            """
            # Just utilize a reverse bit iterator, and create singletons based on the returned values
            self.problem: Problem = problem
            self.key_reverse_iterator: Problem.SetBitsReverseIterator = (
                Problem.SetBitsReverseIterator(problem)
            )

        def __iter__(self):
            return self

        def __next__(self) -> Problem:
            """Returns the next set bit (from most to least significant) as a singleton problem."""
            return Problem.get_problem_for_relation(
                next(self.key_reverse_iterator), len(self.problem)
            )

    def __reversed__(self) -> Iterator[Problem]:
        """See :meth:`BitSequence.__reversed__`.

        Yields each set bit as a singleton :class:`Problem`, from the most to the
        least significant bit, instead of as an integer position.
        """
        return Problem.SingletonReverseIterator(self)

    @staticmethod
    def get_problem_for_relation(relation_id: int, number_of_bits: int) -> Problem:
        """
        Transform a relation id into the corresponding singleton problem.
        :param relation_id: The relation id.
        :param number_of_bits: The number of bits represented by the underlying join graph.
        :return: The relation as a problem.
        """
        return Problem(1 << relation_id, number_of_bits)

    @staticmethod
    def get_problem_with_all_relations(graph_size: int) -> Problem:
        """
        Get a problem containing all relations of given graph size.
        :param graph_size: The graph size.
        :return: A problem containing all relations of the given graph size.
        """
        # Get a problem with all bits set:
        return Problem((1 << graph_size) - 1, graph_size)

    class ProblemIterator:
        """
        An iterator that enumerates all problems of the given superset problem. It starts with the optionally passed
        start problem or with the least-significant-bit-singleton if no such argument was passed. Further, it stops when the
        optionally given limit problem is reached, or when all problems were enumerated when no such argument was given.
        """

        def __init__(
            self,
            superset_problem: Problem,
            start_problem: Problem | None = None,
            stop_problem: Problem | None = None,
        ):
            """
            :param superset_problem: The superset problem.
            :param start_problem: The optional problem to start the enumeration from.
            :param stop_problem: The optional problem to stop the enumeration with.
            """
            self.superset_problem: Problem = superset_problem

            # If no start problem is given, start with the singleton of the least significant bit, as its numeric values
            # is the smallest out of all possible subsets of the superset.
            self.current_problem = (
                start_problem
                if start_problem is not None
                else superset_problem.get_least_significant_bit()
            )

            # Additionally define a problem, which, when reached, will stop the enumeration. Otherwise, just set it to
            # the empty set, which means that all possible subsets will be enumerated eventually, without creating
            # any duplicates
            self.stop_problem = stop_problem if stop_problem is not None else Problem()

        def __iter__(self):
            return self

        def __next__(self) -> Problem:
            """Returns the next subset of the superset problem, stopping once the stop problem is reached."""
            # If we have reached the stop problem, end the iteration
            if self.current_problem == self.stop_problem:
                raise StopIteration

            # The current problem is either the start problem, or the next problem from the previous iteration, and thus
            # the problem we need to return
            returned_problem: Problem = self.current_problem

            # Get next subset w.r.t to the superset represented by the superset_problem
            self.current_problem = self.current_problem.get_next(self.superset_problem)

            return returned_problem

    @staticmethod
    def enumerate_all_problems(
        superset_problem: Problem,
        start_problem: Problem | None = None,
        stop_problem: Problem | None = None,
    ) -> ProblemIterator:
        """
        Enumerate all problems of the given superset problem.
        :param superset_problem: The problems whose problems are to be enumerated.
        :param start_problem: The optional problem to start the enumeration with.
        :param stop_problem: The optional problem after which the enumeration will stop.
        :return: An iterator to traverse through all problems of the given superset problem.
        """
        return Problem.ProblemIterator(superset_problem, start_problem, stop_problem)

    @staticmethod
    def get_all_problems(superset_problem: Problem) -> list[Problem]:
        """
        Computes all problems of a given superset problem and returns them as list. This helper method is useful when
        a list of subsets is utilized multiple times, so there is no need to regenerate the problems from scratch.
        :param superset_problem: The problem whose subsets are to be enumerated.
        :return: The list that stores all subsets as problems.
        """
        problems: list[Problem] = []

        for next_problem in Problem.enumerate_all_problems(superset_problem):
            problems.append(next_problem)

        return problems
