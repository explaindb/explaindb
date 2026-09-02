"""Utilities to randomize cardinalities and run and visualize join-plan enumeration."""

from __future__ import annotations
from system.query_optimization.problems import Problem
from system.query_optimization.join_graph import JoinGraph
from system.query_optimization.cardinality_table import CardinalityTable
from system.query_optimization.cost_function import C_Out
from system.interfaces.cost_functions import CostFunction
import random


def randomize_cardinalities(
    cardinalities: CardinalityTable, number_of_relations: int, seed: int
):
    """
    Randomizes the problem sizes for the given number of relation.
    :param cardinalities: The dictionary to store the sizes.
    :param number_of_relations: The number of singleton problems to be considered.
    :param seed: The seed for the random cardinalities.
    """
    random.seed(seed)
    next_problem: Problem = Problem(1, number_of_relations)
    complete_problem: Problem = Problem.get_problem_with_all_relations(
        number_of_relations
    )

    while next_problem != Problem():
        cardinalities.update_cardinality_estimation(
            next_problem, random.randint(0, 1000)
        )
        next_problem = next_problem.get_next(complete_problem)


def randomize_cardinalities_and_enumerate_join_graph(
    join_graph: JoinGraph,
    plan_enumerator: "PlanEnumerator",
    print_info: bool = False,
) -> tuple[int, tuple, int]:
    """
    Create an example graph and prints its best plan.
    :param join_graph: The join_graph to use.
    :param plan_enumerator: The Plan enumerator to be used.
    :param print_info: A flag to indicate whether to print additional information during enumeration.
    :return: A tuple, consisting of the costs of the best plan, the best plan as a tuple and the number of csg-cmp pairs that were enumerated.
    """

    # Define cardinalities of problems
    cardinality_table: CardinalityTable = CardinalityTable()
    randomize_cardinalities(cardinality_table, len(join_graph), 42)

    # Define C_out CostFunction
    cost_function: CostFunction = C_Out()

    # Enumerate all plans to find the cheapest costs and best plan
    join_costs, join_plan, enumerated_pairs = plan_enumerator.enumerate(
        join_graph, cardinality_table, cost_function, print_info
    )

    results: tuple[int, tuple, int] = (
        join_costs,
        join_plan,
        enumerated_pairs,
    )

    return results


def print_results(results: tuple[int, tuple, int]):
    print(
        f"The best join plan is {visualize_join_plan(results[1])} with costs {results[0]}!"
        f" Overall, we needed to enumerate {results[2]} pairs."
    )


def visualize_join_plan(join_plan: tuple | int) -> str:
    if isinstance(join_plan, int):
        return str(join_plan)
    return f"({visualize_join_plan(join_plan[0])}⋈{visualize_join_plan(join_plan[1])})"
