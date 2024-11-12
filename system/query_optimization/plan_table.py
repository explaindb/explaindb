from __future__ import annotations

from system.interfaces.query_optimization.planning import PlanTable
from system.query_optimization.subproblems import Subproblem
from system.query_optimization.join_graph import JoinGraph
from system.interfaces.cost_functions import CostFunction
from system.query_optimization.cardinality_table import CardinalityTable
import itertools


class StandardPlanTable(PlanTable):
    """
    A standard plan table used for enumeration. It stores for each subproblem the best costs and plan.
    """

    def __init__(
        self,
        join_graph: JoinGraph,
        cost_function: CostFunction,
        cardinality_table: CardinalityTable,
    ):
        # A mapping from each subproblem to a tuple storing the costs and plan for the subproblem
        self.entries: dict[Subproblem, tuple] = dict()
        self._create_base_entries(join_graph, cost_function, cardinality_table)

    def _create_base_entry(self, entry: Subproblem, cost: int):
        """
        Creates the base entry for given entry.
        :param entry: The entry as a subproblem.
        :param cost: The cost to be inserted.
        """
        self.entries[entry] = (
            cost,
            entry.get_relation_id(),
        )

    def _update_join_entry(self, left: Subproblem, right: Subproblem, costs: int):
        """
        Updates the entry corresponding to the subproblem obtained by combining the left and right subproblems.
        :param left: The left subproblem.
        :param right: The right subproblem.
        :param costs: The new costs.
        """
        self.entries[left | right] = (
            costs,
            (
                self.entries[left][1],
                self.entries[right][1],
            ),
        )

    def __contains__(self, subproblem: Subproblem) -> bool:
        """
        Check whether the subproblem is contained in the plantable
        :param subproblem: The subproblem to check
        :return: True, if the subproblem is contained, False if not
        """
        return subproblem in self.entries

    def get_costs_for_subproblem(self, subproblem: Subproblem):
        """
        Returns the current best costs for the subproblem.
        :param subproblem: The subproblem.
        :return: The costs for the subproblem.
        """
        return self.entries[subproblem][0]

    def get_plan_for_subproblem(self, subproblem: Subproblem):
        """
        Returns the current best plan for the subproblem.
        :param subproblem: The subproblem.
        :return: The plan for the subproblem.
        """
        return self.entries[subproblem][1]


class SizeBasedPlanTable(PlanTable):
    """
    A plan table used for enumeration. It stores for each subproblem the best costs and plan. Unlike the StandardPlanTable,
    it orders subproblems based on their size to allow an efficient enumeration over them.
    """

    def __init__(
        self,
        join_graph: JoinGraph,
        cost_function: CostFunction,
        cardinality_table: CardinalityTable,
    ):
        # Store subproblems ordered by their size
        # Sizes of k can then be accessed via the index k-1
        self.entries: list[dict[Subproblem, tuple]] = [
            dict() for _ in join_graph.adjacency_matrix
        ]
        self.size_lists = [
            [] for _ in join_graph.adjacency_matrix
        ]  # Used to avoid having to create iterators multiple times
        self._create_base_entries(join_graph, cost_function, cardinality_table)

    def _create_base_entry(self, entry: Subproblem, cost: int):
        """
        Creates the base entry for given entry.
        :param entry: The entry as a subproblem.
        :param cost: The cost to be inserted.
        """
        self.entries[0][entry] = (
            cost,
            entry.get_relation_id(),
        )

    def _update_join_entry(self, left: Subproblem, right: Subproblem, costs: int):
        """
        Updates the entry corresponding to the subproblem obtained by combining left and right subproblems.
        :param left: The left subproblem.
        :param right: The right subproblem.
        :param costs: The new costs.
        """
        combined: Subproblem = left | right
        self.entries[len(combined) - 1][combined] = (
            costs,
            (
                self.entries[len(left) - 1][left][1],
                self.entries[len(right) - 1][right][1],
            ),
        )

    def __contains__(self, subproblem: Subproblem) -> bool:
        """
        Check whether the subproblem is contained in the plan table.
        :param subproblem: The subproblem to check.
        :return: True, if the subproblem is contained, False if not.
        """
        return subproblem in self.entries[len(subproblem) - 1]

    def entries_with_size(self, k: int, start_index: int = 0):
        """
        Returns an iterator to all elements with size k.
        :param k: The size to iterate through.
        :param start_index: The optional start index to iterate through.
        :return: An iterator to the list of subproblems with size k.
        """
        if len(self.size_lists[k - 1]) == 0:
            self.size_lists[k - 1] = list(self.entries[k - 1])
        return itertools.islice(self.size_lists[k - 1], start_index, None)

    def get_costs_for_subproblem(self, subproblem: Subproblem):
        """
        Returns the current best costs for the subproblem.
        :param subproblem: The subproblem.
        :return: The costs for the subproblem.
        """
        return self.entries[len(subproblem) - 1][subproblem][0]

    def get_plan_for_subproblem(self, subproblem: Subproblem):
        """
        Returns the current best plan for the subproblem.
        :param subproblem: The subproblem.
        :return: The plan for the subproblem.
        """
        return self.entries[len(subproblem) - 1][subproblem][1]
