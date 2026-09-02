"""The classic C_out join cost function implementation."""

from __future__ import annotations

from system.interfaces.cost_functions import CostFunction
from system.interfaces.query_optimization.planning import PlanTable
from system.query_optimization.problems import Problem
from system.query_optimization.cardinality_table import CardinalityTable


class C_Out(CostFunction):
    """
    Implements the classic cost function C_out.
    """

    def estimate_join_costs(
        self,
        left: Problem,
        right: Problem,
        cardinality_table: CardinalityTable,
        plan_table: PlanTable,
    ) -> int:
        """
        Computes the costs for the left and right input.
        :param left: The left problem.
        :param right: The right problem.
        :param cardinality_table: The cardinality table to be used.
        :param plan_table: The plan table for the enumeration.
        :return: The costs of joining the left and right problems.
        """
        return (
            cardinality_table.estimate_join_cardinality(left, right)
            + plan_table.get_costs_for_problem(left)
            + plan_table.get_costs_for_problem(right)
        )

    def estimate_filter_costs(
        self,
        problem: Problem,
        cardinality_table: CardinalityTable,
    ) -> int:
        """
        Computes the costs to filter the problem.
        :param problem: The problem .
        :param cardinality_table: The cardinality table to be used.
        :return: The costs of filtering the problem.
        """
        return cardinality_table.get_cardinality_estimation(problem)
