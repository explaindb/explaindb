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
        # A mapping from each problem to a tuple storing the costs and plan for the problem
        self.entries: dict[Problem, tuple] = dict()
        self._create_base_entries(join_graph, cost_function, cardinality_table)

    def _create_base_entry(self, entry: Problem, cost: int):
        """
        Creates the base entry for given entry.
        :param entry: The entry as a problem.
        :param cost: The cost to be inserted.
        """
        self.entries[entry] = (
            cost,
            entry.get_relation_id(),
        )

    def _update_join_entry(self, left: Problem, right: Problem, costs: int):
        """
        Updates the entry corresponding to the problem obtained by combining the left and right problems.
        :param left: The left problem.
        :param right: The right problem.
        :param costs: The new costs.
        """
        self.entries[left | right] = (
            costs,
            (
                self.entries[left][1],
                self.entries[right][1],
            ),
        )

    def __contains__(self, problem: Problem) -> bool:
        """
        Check whether the problem is contained in the plantable
        :param problem: The problem to check
        :return: True, if the problem is contained, False if not
        """
        return problem in self.entries

    def get_costs_for_problem(self, problem: Problem):
        """
        Returns the current best costs for the problem.
        :param problem: The problem.
        :return: The costs for the problem.
        """
        return self.entries[problem][0]

    def get_plan_for_problem(self, problem: Problem):
        """
        Returns the current best plan for the problem.
        :param problem: The problem.
        :return: The plan for the problem.
        """
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
        """
        Creates the base entry for given entry.
        :param entry: The entry as a problem.
        :param cost: The cost to be inserted.
        """
        self.entries[0][entry] = (
            cost,
            entry.get_relation_id(),
        )

    def _update_join_entry(self, left: Problem, right: Problem, costs: int):
        """
        Updates the entry corresponding to the problem obtained by combining left and right problems.
        :param left: The left problem.
        :param right: The right problem.
        :param costs: The new costs.
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
        """
        Check whether the problem is contained in the plan table.
        :param problem: The problem to check.
        :return: True, if the problem is contained, False if not.
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
        """
        Returns the current best costs for the problem.
        :param problem: The problem.
        :return: The costs for the problem.
        """
        return self.entries[problem.bit_count() - 1][problem][0]

    def get_plan_for_problem(self, problem: Problem):
        """
        Returns the current best plan for the problem.
        :param problem: The problem.
        :return: The plan for the problem.
        """
        return self.entries[problem.bit_count() - 1][problem][1]
