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

"""Cardinality table storing and estimating relation and join cardinalities."""

from __future__ import annotations
from system.query_optimization.problems import Problem


class CardinalityTable:
    """
    A simple cardinality table used to store cardinalities for problems. Normally, cardinalities are obtained by
    using system statistics to make an estimation about the sizes of the results.
    """

    def __init__(self):
        """Create an empty cardinality table."""
        # A mapping from a problem to its cardinality estimation
        self.entries: dict[Problem, int] = {}

    def get_cardinality_estimation(self, problem: Problem) -> int:
        """
        Returns the cardinality estimation for the problem.
        :param problem: The problem.
        :return: The cardinality for the problem.
        """
        if problem not in self.entries:
            raise ValueError("problem is not in the cardinality table.")
        return self.entries[problem]

    def update_cardinality_estimation(self, problem: Problem, cardinality: int):
        """
        Updates the cardinality estimation of the problem to the given cardinality.
        :param problem: The problem.
        :param cardinality: The cardinality.
        """
        self.entries[problem] = cardinality

    def estimate_join_cardinality(self, left: Problem, right: Problem) -> int:
        """
        Returns the join cardinality estimation for the left and right problem.
        :param left: The left problem.
        :param right: The right problem.
        :return: The join cardinality of the left and right problem.
        """
        join_problem: Problem = left | right
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
