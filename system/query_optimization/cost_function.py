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
        """See :meth:`CostFunction.estimate_join_costs`.

        C_out variant: the join cost is the estimated output cardinality of the join plus the costs already
        accumulated for the left and right sub-problems.
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
        """See :meth:`CostFunction.estimate_filter_costs`.

        C_out variant: the filter cost is the estimated cardinality of the (singleton) problem.
        """
        return cardinality_table.get_cardinality_estimation(problem)
