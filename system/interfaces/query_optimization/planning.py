from __future__ import annotations

from abc import ABC, abstractmethod

from system.interfaces.cost_functions import CostFunction
from system.plan_enumeration.cardinality_table import CardinalityTable
from system.plan_enumeration.join_graph import JoinGraph
from system.plan_enumeration.subproblems import Subproblem


class PlanTable(ABC):
    """
    A plan table stores information relevant for the enumeration to make use of dynamic programming.
    For example, it can store for each subproblem the corresponding costs and plan.
    """

    def _create_base_entries(
        self,
        join_graph: JoinGraph,
        cost_function: CostFunction,
        cardinality_table: CardinalityTable,
    ):
        """
        Initialize the plan table with the entries for singleton problems.
        :param join_graph: The underlying join graph.
        :param cost_function: The cost function to be used.
        :param cardinality_table: The cardinality table.
        """
        for relation_id in join_graph:
            relation_subproblem: Subproblem = Subproblem.get_problem_for_relation(
                relation_id
            )
            self._create_base_entry(
                relation_subproblem,
                cost_function.estimate_filter_costs(
                    relation_subproblem, cardinality_table
                ),
            )

    def update_table(
        self,
        s1: Subproblem,
        s2: Subproblem,
        cardinality_table: CardinalityTable,
        cost_function: CostFunction,
    ):
        """
        Updates the table for the given csg-cmp pair (S1, S2)
        :param s1: The csg problem.
        :param s2: The cmp problem.
        :param cardinality_table: The cardinality table to be used.
        :param cost_function: The cost function to be used.
        """
        # Combined problem
        combined: Subproblem = s1 | s2

        # Use the smallest input as left input (by convention)
        if cardinality_table.get_cardinality_estimation(
            s1
        ) <= cardinality_table.get_cardinality_estimation(s2):
            left, right = s1, s2
        else:
            left, right = s2, s1

        # Compute plan costs
        plan_costs: int = cost_function.estimate_join_costs(
            left=left, right=right, cardinality_table=cardinality_table, plan_table=self
        )

        # Update plan table
        if combined not in self or plan_costs < self.get_costs_for_subproblem(combined):
            self._update_join_entry(left, right, plan_costs)

    @abstractmethod
    def _create_base_entry(self, entry: Subproblem, cost: int):
        """
        Creates the base entry for given entry.
        :param entry: The entry as a subproblem.
        :param cost: The cost to be inserted.
        """
        pass

    @abstractmethod
    def _update_join_entry(self, left: Subproblem, right: Subproblem, costs: int):
        """
        Updates the entry corresponding to the subproblem obtained by combining left and right subproblems.
        :param left: The left subproblem.
        :param right: The right subproblem.
        :param costs: The new costs.
        """
        pass

    @abstractmethod
    def __contains__(self, subproblem: Subproblem) -> bool:
        """
        Check whether the subproblem is contained in the plantable
        :param subproblem: The subproblem to check
        :return: True, if the subproblem is contained, False if not
        """
        pass

    @abstractmethod
    def get_costs_for_subproblem(self, subproblem: Subproblem):
        """
        Returns the current best costs for the subproblem.
        :param subproblem: The subproblem.
        :return: The costs for the subproblem.
        """
        pass

    @abstractmethod
    def get_plan_for_subproblem(self, subproblem: Subproblem):
        """
        Returns the current best plan for the subproblem.
        :param subproblem: The subproblem.
        :return: The plan for the subproblem.
        """
        pass
