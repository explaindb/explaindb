from __future__ import annotations
from math import log2


class Subproblem:
    """
    Defines a bitset to efficiently store subsets.
    """

    def __init__(self, number: int = 0):
        self.bitset: int = number

    def __add__(self, other: Subproblem):
        """
        Adds two subproblems, i.e. compute their union.
        :param other: The other subproblem.
        :return: The union of self and other as a subproblem.
        """
        return Subproblem(self.bitset | other.bitset)

    def __sub__(self, other: Subproblem):
        """
        Subtracts other from self, i.e. computes self & not other.
        :param other: The other subproblem.
        :return: The subtraction of self and other as a subproblem.
        """
        return Subproblem(self.bitset & ~other.bitset)

    def __str__(self) -> str:
        """
        Returns the string representation of the bitset.
        :return: The string representation.
        """
        return str(self.as_set())

    def __repr__(self) -> str:
        """
        Returns the string representation of the subproblem.
        :return: The string representation.
        """
        return str(self)

    def __hash__(self):
        """
        Returns the hash value of the problem, in this case just the bitset.
        :return: The hash of the subproblem.
        """
        return self.bitset

    def __len__(self) -> int:
        """
        Returns the length of the problem, i.e. the number of contained relations.
        :return: The number of relations.
        """
        return self.bitset.bit_count()

    def __getstate__(self) -> dict:
        """
        Transforms the object into a dictionary.
        """
        return {"bitset": self.bitset}

    def as_set(self) -> set[int]:
        """
        Returns the bitset as a set of integers that are presented by it.
        :return: A set containing all positions that are set to 1.
        """
        return_set: set[int] = set()
        for problem in Subproblem.SingletonIterator(self):
            return_set.add(int(log2(problem.bitset)))
        return return_set

    class SingletonIterator:
        """
        An iterator to traverse through all singleton problems in the given problem.
        """

        def __init__(self, subproblem: Subproblem):
            self.bitset: int = subproblem.bitset

        def __iter__(self):
            return self

        def __next__(self) -> Subproblem:
            if self.bitset == 0:
                raise StopIteration
            relation_id: int = (
                self.bitset & -self.bitset
            ).bit_length() - 1  # trailing zeroes
            self.bitset &= self.bitset - 1  # reset first set bet
            return Subproblem.get_problem_for_relation(relation_id)

    def __iter__(self) -> SingletonIterator:
        """
        Returns an iterator to iterate through all singleton subproblems, from the LSB to the MSB.
        :return: An iterator to iterate through all singleton subproblems.
        """
        return iter(Subproblem.SingletonIterator(self))

    class SingletonReverseIterator:
        """
        A reverse iterator to traverse through the singleton problems of a subproblem in reversed order.
        """

        def __init__(self, subproblem: Subproblem):
            self.bitset = subproblem.bitset

        def __iter__(self):
            return self

        def __next__(self):
            if self.bitset == 0:
                raise StopIteration
            relation_id: int = self.bitset.bit_length() - 1  # id of highest relation
            self.bitset &= (1 << relation_id) - 1  # reset highest set bit
            return Subproblem.get_problem_for_relation(relation_id)

    def __reversed__(self) -> SingletonReverseIterator:
        """
        Returns an iterator to iterate through all singleton subproblems in reversed order, i.e. from the MSB to the LSB.
        :return: An iterator to iterate through all singleton subproblems in reversed order.
        """
        return iter(Subproblem.SingletonReverseIterator(self))

    def __eq__(self, other: Subproblem):
        """
        Checks two problems for equality.
        :param other: The other subproblem.
        :return: True, if both bitsets are equal, False if not.
        """
        if not isinstance(other, Subproblem):
            return False
        return other.bitset == self.bitset

    def __and__(self, other: Subproblem):
        """
        Returns the bitwise & between this and the other subproblem
        :return: The bitwise & as a subproblem.
        """
        return Subproblem(self.bitset & other.bitset)

    def __or__(self, other: Subproblem):
        """
        Returns the bitwise | between this and the other subproblem
        :return: The bitwise | as a subproblem.
        """
        return Subproblem(self.bitset | other.bitset)

    def overlaps(self, other: Subproblem):
        """
        Checks whether self and other share some common relations.
        :param other: The other subproblem.
        :return: True, if some relations are shared, False if not.
        """
        return (self.bitset & other.bitset) != 0

    def get_lsb_problem(self):
        """
        Returns the relation represented by the lsb as a subproblem.
        :return: The lsb relation as a subproblem.
        """
        return Subproblem(self.bitset & -self.bitset)

    def get_msb_problem(self):
        """
        Returns the relation represented by the msb as a subproblem.
        :return: The msb relation as a subproblem.
        """
        return Subproblem.get_problem_for_relation(self.bitset.bit_length() - 1)

    def get_next(self, n: Subproblem):
        """
        Returns the next subproblem in a subproblem enumeration w.r.t to the problem n.
        :param n: The problem n whose subproblems are to be enumerated.
        :return: The next subset as a subproblem.
        """
        return Subproblem(self.bitset - n.bitset) & n

    def contains(self, other: Subproblem):
        """
        Checks whether other subproblem is contained in self.
        :param other: The other problem.
        :return: True, of other is contained in self, False if not.
        """
        return self.bitset & other.bitset == other.bitset

    def get_b_min(self):
        """
        Returns the problem containing all problems that are smaller/equal than the smallest problem in self.
        :return: The problem containing all problems that are smaller/equal than the smallest problem in self.
        """
        return Subproblem((self.get_lsb_problem().bitset << 1) - 1)

    def get_relation_id(self):
        """
        Returns the relation id of the problem, if it is a singleton.
        :return: The relation id.
        """
        if self.bitset.bit_count() != 1:
            raise ValueError("The bitset is not a singleton.")
        return self.bitset.bit_length() - 1

    @staticmethod
    def get_problem_for_relation(relation_id: int):
        """
        Transform a relation id into the corresponding singleton problem.
        :param relation_id: The relation id.
        :return: The relation as a problem.
        """
        return Subproblem(1 << relation_id)

    @staticmethod
    def get_complete_problem(size: int):
        """
        Get a full problem of the given size.
        :param size: The size of the whole problem.
        :return: A problem containing all relations.
        """
        return Subproblem((1 << size) - 1)

    class SubproblemIterator:
        """
        An iterator that enumerates all subproblems of the whole subproblem. It starts with the optionally passed
        start problem or with the LSB subproblem if no such argument was passed. Further, it stops when the
        optionally given limit problem is reached, or when all subproblems were enumerated when no such argument was given.
        """

        def __init__(
            self,
            complete_problem: Subproblem,
            start_problem: Subproblem | None = None,
            stop_problem: Subproblem | None = None,
        ):
            self.complete_problem = complete_problem
            self.current_problem = (
                start_problem if start_problem else complete_problem.get_lsb_problem()
            )
            self.limit_problem = stop_problem if stop_problem else Subproblem()

        def __iter__(self):
            return self

        def __next__(self):
            if self.current_problem == self.limit_problem:
                raise StopIteration
            returned_problem: Subproblem = self.current_problem
            self.current_problem = self.current_problem.get_next(self.complete_problem)
            return returned_problem

    @staticmethod
    def enumerate_all_subproblems(
        complete_problem: Subproblem,
        start_problem: Subproblem | None = None,
        stop_problem: Subproblem | None = None,
    ) -> SubproblemIterator:
        """
        Enumerate all subproblems of the given complete problem.
        :param complete_problem: The problems whose subproblems are to be enumerated.
        :param start_problem: The optional problem to start the enumeration with.
        :param stop_problem: The optional subproblem after which the enumeration will stop.
        :return: An iterator to traverse through all subproblemse of the complete problem.
        """
        return Subproblem.SubproblemIterator(
            complete_problem, start_problem, stop_problem
        )

    @staticmethod
    def get_all_subproblems(complete_problem: Subproblem) -> list[Subproblem]:
        """
        Computes all subproblems of a given complete problem and returns them.
        :param complete_problem: The problem to be used for the subproblem generation.
        :return: The list that stores subsets.
        """
        subproblems: list[Subproblem] = []

        for next_problem in Subproblem.enumerate_all_subproblems(complete_problem):
            subproblems.append(next_problem)

        return subproblems
