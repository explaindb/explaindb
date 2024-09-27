from __future__ import annotations
from system.plan_enumeration.subproblems import Subproblem


class CardinalityTable:
    """
    A simple cardinality table used to store cardinalities for subproblems. Normally, cardinalities are obtained by
    using system statistics to make an estimation about the sizes of the results.
    """

    def __init__(self):
        # A mapping from a subproblem to its cardinality estimation
        self.entries: dict[Subproblem, int] = dict()

    def get_cardinality_estimation(self, subproblem: Subproblem) -> int:
        """
        Returns the cardinality estimation for the subproblem.
        :param subproblem: The subproblem.
        :return: The cardinality for the subproblem.
        """
        if subproblem not in self.entries:
            raise ValueError("Subproblem is not in the cardinality table.")
        return self.entries[subproblem]

    def update_cardinality_estimation(self, subproblem: Subproblem, cardinality: int):
        """
        Updates the cardinality estimation of the subproblem to the given cardinality.
        :param subproblem: The subproblem.
        :param cardinality: The cardinality.
        """
        self.entries[subproblem] = cardinality

    def estimate_join_cardinality(self, left: Subproblem, right: Subproblem) -> int:
        """
        Returns the join cardinality estimation for the left and right subproblem.
        :param left: The left subproblem.
        :param right: The right subproblem.
        :return: The join cardinality of the left and right subproblem.
        """
        join_problem: Subproblem = left | right
        if join_problem in self.entries:
            return self.entries[join_problem]
        else:
            # Use Cartesian Product for estimation
            self.update_cardinality_estimation(
                join_problem,
                self.get_cardinality_estimation(left)
                * self.get_cardinality_estimation(right),
            )
            return self.entries[join_problem]
