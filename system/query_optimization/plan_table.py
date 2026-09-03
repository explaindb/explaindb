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

"""Plan table implementations for dynamic-programming join-order enumeration."""

from __future__ import annotations

from system.interfaces.query_optimization.planning import PlanTable
from system.query_optimization.problems import Problem
from system.query_optimization.join_graph import JoinGraph
from system.interfaces.cost_functions import CostFunction
from system.query_optimization.cardinality_table import CardinalityTable
import itertools


class StandardPlanTable(PlanTable):
    """
    A standard plan table used for enumeration. It stores for each problem the best costs and plan.
    """

    def __init__(
        self,
        join_graph: JoinGraph,
        cost_function: CostFunction,
        cardinality_table: CardinalityTable,
    ):
        """
        Create a standard plan table and initialize it with the singleton base entries.
        :param join_graph: The underlying join graph.
        :param cost_function: The cost function used to estimate costs.
        :param cardinality_table: The cardinality table used for estimations.
        """
        # A mapping from each problem to a tuple storing the costs and plan for the problem
        self.entries: dict[Problem, tuple] = dict()
        self._create_base_entries(join_graph, cost_function, cardinality_table)

    def _create_base_entry(self, entry: Problem, cost: int):
        """See :meth:`PlanTable._create_base_entry`."""
        self.entries[entry] = (
            cost,
            entry.get_relation_id(),
        )

    def _update_join_entry(self, left: Problem, right: Problem, costs: int):
        """See :meth:`PlanTable._update_join_entry`."""
        self.entries[left | right] = (
            costs,
            (
                self.entries[left][1],
                self.entries[right][1],
            ),
        )

    def __contains__(self, problem: Problem) -> bool:
        """See :meth:`PlanTable.__contains__`."""
        return problem in self.entries

    def get_costs_for_problem(self, problem: Problem):
        """See :meth:`PlanTable.get_costs_for_problem`."""
        return self.entries[problem][0]

    def get_plan_for_problem(self, problem: Problem):
        """See :meth:`PlanTable.get_plan_for_problem`."""
        return self.entries[problem][1]


class SizeBasedPlanTable(PlanTable):
    """
    A plan table used for enumeration. It stores for each problem the best costs and plan. Unlike the StandardPlanTable,
    it orders problems based on their size to allow an efficient enumeration over them.
    """

    def __init__(
        self,
        join_graph: JoinGraph,
        cost_function: CostFunction,
        cardinality_table: CardinalityTable,
    ):
        """
        Create a size-based plan table and initialize it with the singleton base entries.
        :param join_graph: The underlying join graph.
        :param cost_function: The cost function used to estimate costs.
        :param cardinality_table: The cardinality table used for estimations.
        """
        # Store problems ordered by their size
        # Sizes of k can then be accessed via the index k-1
        self.entries: list[dict[Problem, tuple]] = [
            dict() for _ in join_graph.adjacency_matrix
        ]
        self.size_lists = [
            [] for _ in join_graph.adjacency_matrix
        ]  # Used to avoid having to create iterators multiple times
        self._create_base_entries(join_graph, cost_function, cardinality_table)

    def _create_base_entry(self, entry: Problem, cost: int):
        """See :meth:`PlanTable._create_base_entry`.

        Stores the entry in the size-1 bucket of the size-indexed table.
        """
        self.entries[0][entry] = (
            cost,
            entry.get_relation_id(),
        )

    def _update_join_entry(self, left: Problem, right: Problem, costs: int):
        """See :meth:`PlanTable._update_join_entry`.

        Stores the combined entry in the bucket for its size (index is its number
        of relations minus one).
        """
        combined: Problem = left | right
        self.entries[combined.bit_count() - 1][combined] = (
            costs,
            (
                self.entries[left.bit_count() - 1][left][1],
                self.entries[right.bit_count() - 1][right][1],
            ),
        )

    def __contains__(self, problem: Problem) -> bool:
        """See :meth:`PlanTable.__contains__`.

        Looks the problem up in the bucket for its size (index is its number of
        relations minus one).
        """
        return problem in self.entries[problem.bit_count() - 1]

    def entries_with_size(self, k: int, start_index: int = 0):
        """
        Returns an iterator to all elements with size k.
        :param k: The size to iterate through.
        :param start_index: The optional start index to iterate through.
        :return: An iterator to the list of problems with size k.
        """
        if len(self.size_lists[k - 1]) == 0:
            self.size_lists[k - 1] = list(self.entries[k - 1])
        return itertools.islice(self.size_lists[k - 1], start_index, None)

    def get_costs_for_problem(self, problem: Problem):
        """See :meth:`PlanTable.get_costs_for_problem`."""
        return self.entries[problem.bit_count() - 1][problem][0]

    def get_plan_for_problem(self, problem: Problem):
        """See :meth:`PlanTable.get_plan_for_problem`."""
        return self.entries[problem.bit_count() - 1][problem][1]
