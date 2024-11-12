from __future__ import annotations

from abc import ABC, abstractmethod

from system.query_optimization.cardinality_table import CardinalityTable
from system.query_optimization.subproblems import Subproblem


class CostFunction(ABC):
    """
    A cost function used to compute the costs of joining two subproblems.
    """

    @abstractmethod
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
        pass

    @abstractmethod
    def estimate_filter_costs(
        self,
        subproblem: Subproblem,
        cardinality_table: CardinalityTable,
    ) -> int:
        """
        Computes the costs to filter the subproblem.
        :param subproblem: The subproblem.
        :param cardinality_table: The cardinality table to be used.
        :return: The costs of filtering the subproblem.
        """
        pass
