"""Tests for join-plan enumeration and problem (relation-subset) operations."""

import unittest
from system.query_optimization.problems import Problem
from system.query_optimization.cost_function import C_Out
from system.interfaces.cost_functions import CostFunction
from system.query_optimization.plan_table import (
    StandardPlanTable,
    SizeBasedPlanTable,
)
from system.interfaces.query_optimization.planning import PlanTable
from system.query_optimization.cardinality_table import CardinalityTable
from system.query_optimization.join_graph import (
    JoinGraph,
    ChainQueryFactory,
    CycleQueryFactory,
    StarQueryFactory,
    CliqueQueryFactory,
)


class PlanEnumerationTests(unittest.TestCase):
    def test_problemOperations(self):
        """
        Problem bit-set operations: equality, union/difference, hash, length, as_set, intersection, least-significant bit, and containment.
        """
        x: Problem = Problem(0b01010, 5)
        y: Problem = Problem(0b10010, 5)
        self.assertNotEqual(x, y)
        self.assertNotEqual(x, 0b1010)
        self.assertEqual(x, Problem(0b1010, 5))
        self.assertEqual(x + y, Problem(0b11010, 5))
        self.assertEqual(x - y, Problem(0b1000, 5))
        self.assertEqual(y - x, Problem(0b10000, 5))
        self.assertEqual(hash(x), 0b1010)
        self.assertEqual(hash(y), 0b10010)
        self.assertEqual(len(x), 5)
        self.assertEqual(len(x), len(y))
        self.assertSetEqual({1, 3}, x.as_set())
        self.assertSetEqual({1, 4}, y.as_set())
        self.assertEqual(str(x), str(x.as_set()))
        self.assertTrue(x.intersects(y))
        self.assertTrue(y.intersects(x))
        self.assertEqual(x.get_least_significant_bit(), Problem(0b10, 5))
        self.assertEqual(y.get_least_significant_bit(), Problem(0b10, 5))
        self.assertEqual(y.get_least_significant_bit(), x.get_least_significant_bit())
        self.assertFalse(x.contains_bit_sequence(y))
        self.assertTrue(x.contains_bit_sequence(x))
        self.assertFalse(y.contains_bit_sequence(x))
        self.assertTrue(y.contains_bit_sequence(y))
        self.assertTrue(y.contains_bit_sequence(Problem(0b10000, 5)))
        self.assertEqual(x.get_smaller_or_equal_relations(), Problem(0b11, 5))
        with self.assertRaises(ValueError):
            x.get_relation_id()
        self.assertEqual(Problem(0b10000, 5).get_relation_id(), 4)
        self.assertEqual(Problem(0b100000, 6), Problem.get_problem_for_relation(5, 6))
        self.assertEqual(Problem.get_problem_with_all_relations(4), Problem(0b1111, 4))

    def test_SingletonIterator(self):
        """
        Iterating a problem yields its relations as singleton problems, forward and in reverse.
        """
        x: Problem = Problem(0b1011, 4)
        expected_problems: list[Problem] = [
            Problem(0b1, 4),
            Problem(0b10, 4),
            Problem(0b1000, 4),
        ]
        enumerated_problems: list[Problem] = []

        for next_problem in x:
            enumerated_problems.append(next_problem)

        self.assertListEqual(expected_problems, enumerated_problems)

        expected_reversed_problems: list[Problem] = [
            Problem(0b1000, 4),
            Problem(0b10, 4),
            Problem(0b1, 4),
        ]
        enumerated_reversed_problems: list[Problem] = []

        for next_problem in reversed(x):
            enumerated_reversed_problems.append(next_problem)

        self.assertListEqual(expected_reversed_problems, enumerated_reversed_problems)

    def test_problemIterator(self):
        """
        Enumerating all subsets of a superset problem in increasing-integer order.
        """
        x: Problem = Problem(0b10110, 5)
        expected_problems: list[Problem] = [
            Problem(0b10, 5),
            Problem(0b100, 5),
            Problem(0b110, 5),
            Problem(0b10000, 5),
            Problem(0b10010, 5),
            Problem(0b10100, 5),
            Problem(0b10110, 5),
        ]
        enumerated_problems: list[Problem] = []

        for next_problem in Problem.enumerate_all_problems(x):
            enumerated_problems.append(next_problem)
        self.assertListEqual(expected_problems, enumerated_problems)
        self.assertListEqual(Problem.get_all_problems(x), enumerated_problems)

        adapted_expected_problems: list[Problem] = expected_problems[2:5]
        adapted_enumerated_problems: list[Problem] = []
        for next_problem in Problem.enumerate_all_problems(
            x, Problem(0b110, 5), Problem(0b10100, 5)
        ):
            adapted_enumerated_problems.append(next_problem)
        self.assertListEqual(adapted_expected_problems, adapted_enumerated_problems)

    def test_enumeration_utilities(self):
        """
        End-to-end plan enumeration: cost and optimal plans agree across both plan-table implementations.
        """
        chain_query: JoinGraph = ChainQueryFactory.construct_join_graph(3)
        card_table: CardinalityTable = CardinalityTable()
        card_table.update_cardinality_estimation(Problem(0b1, 3), 20)
        card_table.update_cardinality_estimation(Problem(0b10, 3), 30)
        card_table.update_cardinality_estimation(Problem(0b100, 3), 40)
        card_table.update_cardinality_estimation(Problem(0b110, 3), 30)
        card_table.update_cardinality_estimation(Problem(0b111, 3), 10)

        c_out: CostFunction = C_Out()

        self.assertFalse(chain_query.is_connected(Problem(0b101, 3)))
        self.assertFalse(chain_query.are_connected(Problem(0b1, 3), Problem(0b100)))
        self.assertEqual(chain_query.get_neighbors(Problem(0b10, 3)), Problem(0b101))

        self.assertEqual(c_out.estimate_filter_costs(Problem(0b1, 3), card_table), 20)
        self.assertEqual(c_out.estimate_filter_costs(Problem(0b10, 3), card_table), 30)
        self.assertEqual(c_out.estimate_filter_costs(Problem(0b100, 3), card_table), 40)

        standard_plan_table: StandardPlanTable = StandardPlanTable(
            chain_query, c_out, card_table
        )

        self.assertEqual(
            c_out.estimate_join_costs(
                Problem(0b1, 3), Problem(0b10, 3), card_table, standard_plan_table
            ),
            650,  # Cartesian Product
        )

        self.assertEqual(
            c_out.estimate_join_costs(
                Problem(0b10, 3), Problem(0b100, 3), card_table, standard_plan_table
            ),
            100,
        )

        size_based_plan_table: SizeBasedPlanTable = SizeBasedPlanTable(
            chain_query, c_out, card_table
        )

        def _test_plan_table(plan_table: PlanTable):
            plan_table.update_table(
                Problem(0b1, 3), Problem(0b10, 3), card_table, c_out
            )
            plan_table.update_table(
                Problem(0b10, 3), Problem(0b100, 3), card_table, c_out
            )
            plan_table.update_table(
                Problem(0b11, 3), Problem(0b100, 3), card_table, c_out
            )
            plan_table.update_table(
                Problem(0b110, 3), Problem(0b1, 3), card_table, c_out
            )

            self.assertTrue(Problem(0b1, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b1, 3)), 20)
            self.assertTrue(Problem(0b10, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b10, 3)), 30)
            self.assertTrue(Problem(0b100, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b100, 3)), 40)
            self.assertTrue(Problem(0b11, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b11, 3)), 650)
            self.assertTrue(Problem(0b110, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b110, 3)), 100)
            self.assertTrue(Problem(0b111, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b111, 3)), 130)

        _test_plan_table(standard_plan_table)
        _test_plan_table(size_based_plan_table)

        enumerated_entries: list[Problem] = []
        expected_entries: list[Problem] = [Problem(0b10, 3), Problem(0b100, 3)]
        for entry in size_based_plan_table.entries_with_size(1, 1):
            enumerated_entries.append(entry)

        self.assertListEqual(enumerated_entries, expected_entries)

    def test_chain_query(self):
        """
        Neighbour and connectivity relations for a chain join graph.
        """
        chain_query: JoinGraph = ChainQueryFactory.construct_join_graph(5)

        self.assertEqual(chain_query.get_neighbors(Problem(0b1, 5)), Problem(0b10))
        self.assertEqual(chain_query.get_neighbors(Problem(0b10, 5)), Problem(0b101))
        self.assertEqual(chain_query.get_neighbors(Problem(0b100, 5)), Problem(0b1010))
        self.assertEqual(
            chain_query.get_neighbors(Problem(0b1000, 5)), Problem(0b10100)
        )
        self.assertEqual(
            chain_query.get_neighbors(Problem(0b10000, 5)), Problem(0b1000)
        )

    def test_cycle_query(self):
        """
        Neighbour and connectivity relations for a cycle join graph.
        """
        cycle_query: JoinGraph = CycleQueryFactory.construct_join_graph(5)

        self.assertEqual(cycle_query.get_neighbors(Problem(0b1, 5)), Problem(0b10010))
        self.assertEqual(cycle_query.get_neighbors(Problem(0b10, 5)), Problem(0b101))
        self.assertEqual(cycle_query.get_neighbors(Problem(0b100, 5)), Problem(0b1010))
        self.assertEqual(
            cycle_query.get_neighbors(Problem(0b1000, 5)), Problem(0b10100)
        )
        self.assertEqual(
            cycle_query.get_neighbors(Problem(0b10000, 5)), Problem(0b1001)
        )

    def test_star_query(self):
        """
        Neighbour and connectivity relations for a star join graph.
        """
        star_query: JoinGraph = StarQueryFactory.construct_join_graph(5)

        self.assertEqual(star_query.get_neighbors(Problem(0b1, 5)), Problem(0b11110))
        self.assertEqual(star_query.get_neighbors(Problem(0b10, 5)), Problem(0b1))
        self.assertEqual(star_query.get_neighbors(Problem(0b100, 5)), Problem(0b1))
        self.assertEqual(star_query.get_neighbors(Problem(0b1000, 5)), Problem(0b1))
        self.assertEqual(star_query.get_neighbors(Problem(0b10000, 5)), Problem(0b1))

    def test_clique_query(self):
        """
        Neighbour and connectivity relations for a clique join graph.
        """
        clique_query: JoinGraph = CliqueQueryFactory.construct_join_graph(5)

        self.assertEqual(clique_query.get_neighbors(Problem(0b1, 5)), Problem(0b11110))
        self.assertEqual(clique_query.get_neighbors(Problem(0b10, 5)), Problem(0b11101))
        self.assertEqual(
            clique_query.get_neighbors(Problem(0b100, 5)), Problem(0b11011)
        )
        self.assertEqual(
            clique_query.get_neighbors(Problem(0b1000, 5)), Problem(0b10111)
        )
        self.assertEqual(
            clique_query.get_neighbors(Problem(0b10000, 5)), Problem(0b01111)
        )


if __name__ == "__main__":
    unittest.main(
        argv=["ignored", "-v"],
        defaultTest="PlanEnumerationTests",
        verbosity=2,
        exit=False,
    )
