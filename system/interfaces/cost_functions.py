"""Abstract cost-function interface for join-order query optimization."""

from __future__ import annotations

from abc import ABC, abstractmethod

from system.query_optimization.cardinality_table import CardinalityTable
from system.query_optimization.problems import Problem


class CostFunction(ABC):
    """
    A cost function used to compute the costs of joining two problems.
    """

    @abstractmethod
    def estimate_join_costs(
        self,
        left: Problem,
        right: Problem,
        cardinality_table: CardinalityTable,
        plan_table: "PlanTable",
    ) -> int:
        """
        Computes the costs for the left and right input.
        :param left: The left problem.
        :param right: The right problem.
        :param cardinality_table: The cardinality table to be used.
        :param plan_table: The plan table for the enumeration.
        :return: The costs of joining the left and right problems.
        """
        pass

    @abstractmethod
    def estimate_filter_costs(
        self,
        problem: Problem,
        cardinality_table: CardinalityTable,
    ) -> int:
        """
        Computes the costs to filter the problem.
        :param problem: The problem.
        :param cardinality_table: The cardinality table to be used.
        :return: The costs of filtering the problem.
        """
        pass
