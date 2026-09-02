"""Abstract plan-table interface for join-order enumeration."""

from __future__ import annotations

from abc import ABC, abstractmethod

from system.interfaces.cost_functions import CostFunction
from system.query_optimization.cardinality_table import CardinalityTable
from system.query_optimization.join_graph import JoinGraph
from system.query_optimization.problems import Problem


class PlanTable(ABC):
    """
    A plan table stores information relevant for the enumeration to make use of dynamic programming.
    For example, it can store for each problem the corresponding costs and plan.
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
            relation_problem: Problem = Problem.get_problem_for_relation(
                relation_id, len(join_graph)
            )
            self._create_base_entry(
                relation_problem,
                cost_function.estimate_filter_costs(
                    relation_problem, cardinality_table
                ),
            )

    def update_table(
        self,
        s1: Problem,
        s2: Problem,
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
        combined: Problem = s1 | s2

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
        if combined not in self or plan_costs < self.get_costs_for_problem(combined):
            self._update_join_entry(left, right, plan_costs)

    @abstractmethod
    def _create_base_entry(self, entry: Problem, cost: int):
        """
        Creates the base entry for given entry.
        :param entry: The entry as a problem.
        :param cost: The cost to be inserted.
        """
        pass

    @abstractmethod
    def _update_join_entry(self, left: Problem, right: Problem, costs: int):
        """
        Updates the entry corresponding to the problem obtained by combining left and right problems.
        :param left: The left problem.
        :param right: The right problem.
        :param costs: The new costs.
        """
        pass

    @abstractmethod
    def __contains__(self, problem: Problem) -> bool:
        """
        Check whether the problem is contained in the plantable
        :param problem: The problem to check
        :return: True, if the problem is contained, False if not
        """
        pass

    @abstractmethod
    def get_costs_for_problem(self, problem: Problem):
        """
        Returns the current best costs for the problem.
        :param problem: The problem.
        :return: The costs for the problem.
        """
        pass

    @abstractmethod
    def get_plan_for_problem(self, problem: Problem):
        """
        Returns the current best plan for the problem.
        :param problem: The problem.
        :return: The plan for the problem.
        """
        pass
