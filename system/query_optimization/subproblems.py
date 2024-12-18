from __future__ import annotations
from system.bit_sequences import IntegerBitSequence


class Subproblem(IntegerBitSequence):
    """
    Defines additional operations for integer bit sequences to efficiently store and manage subsets of relations.
    """

    def __hash__(self) -> int:
        """
        Defines the hash value for the subproblem.
        :return: The hash of the subproblem.
        """
        return self.number

    def overlaps(self, other: Subproblem) -> bool:
        """
        Checks whether self and other share some common relations.
        :param other: The other subproblem.
        :return: True, if some relations are shared, False if not.
        """
        return (self.number & other.number) != 0

    def get_lsb_problem(self) -> Subproblem:
        """
        Returns the relation represented by the lsb as a subproblem.
        :return: The lsb relation as a subproblem.
        """
        return Subproblem(self.number & -self.number)

    def get_msb_problem(self) -> Subproblem:
        """
        Returns the relation represented by the msb as a subproblem.
        :return: The msb relation as a subproblem.
        """
        return Subproblem.get_problem_for_relation(self.number.bit_length() - 1)

    def get_next(self, n: Subproblem) -> Subproblem:
        """
        Returns the next subproblem in a subproblem enumeration w.r.t to the problem n.
        :param n: The problem n whose subproblems are to be enumerated.
        :return: The next subset as a subproblem.
        """
        return Subproblem(self.number - n.number) & n

    def contains(self, other: Subproblem) -> bool:
        """
        Checks whether other subproblem is contained in self.
        :param other: The other problem.
        :return: True, of other is contained in self, False if not.
        """
        return self.number & other.number == other.number

    def get_b_min(self) -> Subproblem:
        """
        Returns the problem containing all problems that are smaller/equal than the smallest problem in self.
        :return: The problem containing all problems that are smaller/equal than the smallest problem in self.
        """
        return Subproblem((self.get_lsb_problem().number << 1) - 1)

    def get_relation_id(self):
        """
        Returns the relation id of the problem, if it is a singleton.
        :return: The relation id.
        """
        if self.number.bit_count() != 1:
            raise ValueError("The bit_sequence is not a singleton.")
        return self.number.bit_length() - 1

    def as_set(self) -> set[int]:
        return set(key for key in IntegerBitSequence.SetBitsIterator(self))

    def set_bits(self) -> int:
        return self.number.bit_count()

    def __invert__(self) -> Subproblem:
        return type(self)(~self.number)

    class SingletonIterator:
        def __init__(self, subproblem: Subproblem):
            self.key_iterator: IntegerBitSequence.SetBitsIterator = (
                IntegerBitSequence.SetBitsIterator(subproblem)
            )

        def __iter__(self):
            return self

        def __next__(self) -> Subproblem:
            return Subproblem.get_problem_for_relation(next(self.key_iterator))

    def __iter__(self):
        return Subproblem.SingletonIterator(self)

    class KeyReverseIterator:
        def __init__(self, bit_sequence: IntegerBitSequence):
            self.number: int = bit_sequence.number

        def __next__(self) -> int:
            if self.number == 0:
                raise StopIteration
            key: int = self.number.bit_length() - 1  # id of highest relation
            self.number &= (1 << key) - 1  # reset highest set bit
            return key

    class SingletonReverseIterator:
        def __init__(self, subproblem: Subproblem):
            self.key_reverse_iterator: Subproblem.KeyReverseIterator = (
                Subproblem.KeyReverseIterator(subproblem)
            )

        def __iter__(self):
            return self

        def __next__(self) -> Subproblem:
            return Subproblem.get_problem_for_relation(next(self.key_reverse_iterator))

    def __reversed__(self):
        return Subproblem.SingletonReverseIterator(self)

    @staticmethod
    def get_problem_for_relation(relation_id: int) -> Subproblem:
        """
        Transform a relation id into the corresponding singleton problem.
        :param relation_id: The relation id.
        :return: The relation as a problem.
        """
        return Subproblem(1 << relation_id)

    @staticmethod
    def get_complete_problem(size: int) -> Subproblem:
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

        def __next__(self) -> Subproblem:
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
