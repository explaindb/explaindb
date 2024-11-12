from __future__ import annotations

from system.interfaces.cost_functions import CostFunction
from system.query_optimization.subproblems import Subproblem
from system.query_optimization.cardinality_table import CardinalityTable


class C_Out(CostFunction):
    """
    Implements the classic cost function C_out.
    """

    def estimate_join_costs(
        self,
        left: Subproblem,
        right: Subproblem,
        cardinality_table: CardinalityTable,
        plan_table: "PlanTable",
    ) -> int:
        """
        Computes the costs for the left and right input.
        :param left: The left subproblem.
        :param right: The right subproblem.
        :param cardinality_table: The cardinality table to be used.
        :param plan_table: The plan table for the enumeration.
        :return: The costs of joining the left and right subproblems.
        """
        return (
            cardinality_table.estimate_join_cardinality(left, right)
            + plan_table.get_costs_for_subproblem(left)
            + plan_table.get_costs_for_subproblem(right)
        )

    def estimate_filter_costs(
        self,
        subproblem: Subproblem,
        cardinality_table: CardinalityTable,
    ) -> int:
        """
        Computes the costs to filter the subproblem.
        :param subproblem: The subproblem .
        :param cardinality_table: The cardinality table to be used.
        :return: The costs of filtering the subproblem.
        """
        return cardinality_table.get_cardinality_estimation(subproblem)
