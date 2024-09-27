import unittest
from system.plan_enumeration.subproblems import Subproblem
from system.plan_enumeration.cost_function import CostFunction, C_Out
from system.plan_enumeration.plan_table import (
    PlanTable,
    StandardPlanTable,
    SizeBasedPlanTable,
)
from system.plan_enumeration.cardinality_table import CardinalityTable
from system.plan_enumeration.join_graph import (
    JoinGraph,
    ChainQueryFactory,
    CycleQueryFactory,
    StarQueryFactory,
    CliqueQueryFactory,
)


class PlanEnumerationTests(unittest.TestCase):
    def test_SubproblemOperations(self):
        x: Subproblem = Subproblem(0b1010)
        y: Subproblem = Subproblem(0b10010)
        self.assertNotEqual(x, y)
        self.assertNotEqual(x, 0b1010)
        self.assertEqual(x, Subproblem(0b1010))
        self.assertEqual(x + y, Subproblem(0b11010))
        self.assertEqual(x - y, Subproblem(0b1000))
        self.assertEqual(y - x, Subproblem(0b10000))
        self.assertEqual(x + y, x + y)
        self.assertEqual(x - y, x - y)
        self.assertEqual(hash(x), 0b1010)
        self.assertEqual(hash(y), 0b10010)
        self.assertEqual(len(x), 0b10)
        self.assertEqual(len(x), len(y))
        self.assertSetEqual({1, 3}, x.as_set())
        self.assertSetEqual({1, 4}, y.as_set())
        self.assertEqual(str(x), str(x.as_set()))
        self.assertTrue(x.overlaps(y))
        self.assertTrue(y.overlaps(x))
        self.assertEqual(x.get_lsb_problem(), Subproblem(0b10))
        self.assertEqual(y.get_lsb_problem(), Subproblem(0b10))
        self.assertEqual(y.get_lsb_problem(), x.get_lsb_problem())
        self.assertFalse(x.contains(y))
        self.assertFalse(y.contains(x))
        self.assertTrue(y.contains(Subproblem(0b10000)))
        self.assertEqual(x.get_b_min(), Subproblem(0b11))
        with self.assertRaises(ValueError):
            x.get_relation_id()
        self.assertEqual(Subproblem(0b10000).get_relation_id(), 4)
        self.assertEqual(Subproblem(0b100000), Subproblem.get_problem_for_relation(5))
        self.assertEqual(Subproblem.get_complete_problem(0b100), Subproblem(0b1111))

    def test_SingletonIterator(self):
        x: Subproblem = Subproblem(0b1011)
        expected_problems: list[Subproblem] = [
            Subproblem(0b1),
            Subproblem(0b10),
            Subproblem(0b1000),
        ]
        enumerated_problems: list[Subproblem] = []

        for next_problem in x:
            enumerated_problems.append(next_problem)

        self.assertListEqual(expected_problems, enumerated_problems)

        expected_reversed_problems: list[Subproblem] = [
            Subproblem(0b1000),
            Subproblem(0b10),
            Subproblem(0b1),
        ]
        enumerated_reversed_problems: list[Subproblem] = []

        for next_problem in reversed(x):
            enumerated_reversed_problems.append(next_problem)

        self.assertListEqual(expected_reversed_problems, enumerated_reversed_problems)

    def test_SubproblemIterator(self):
        x: Subproblem = Subproblem(0b10110)
        expected_problems: list[Subproblem] = [
            Subproblem(0b10),
            Subproblem(0b100),
            Subproblem(0b110),
            Subproblem(0b10000),
            Subproblem(0b10010),
            Subproblem(0b10100),
            Subproblem(0b10110),
        ]
        enumerated_problems: list[Subproblem] = []

        for next_problem in Subproblem.enumerate_all_subproblems(x):
            enumerated_problems.append(next_problem)
        self.assertListEqual(expected_problems, enumerated_problems)
        self.assertListEqual(Subproblem.get_all_subproblems(x), enumerated_problems)

        adapted_expected_problems: list[Subproblem] = expected_problems[2:5]
        adapted_enumerated_problems: list[Subproblem] = []
        for next_problem in Subproblem.enumerate_all_subproblems(
            x, Subproblem(0b110), Subproblem(0b10100)
        ):
            adapted_enumerated_problems.append(next_problem)
        self.assertListEqual(adapted_expected_problems, adapted_enumerated_problems)

    def test_enumeration_utilities(self):
        chain_query: JoinGraph = ChainQueryFactory.construct_join_graph(3)
        card_table: CardinalityTable = CardinalityTable()
        card_table.update_cardinality_estimation(Subproblem(0b1), 20)
        card_table.update_cardinality_estimation(Subproblem(0b10), 30)
        card_table.update_cardinality_estimation(Subproblem(0b100), 40)
        card_table.update_cardinality_estimation(Subproblem(0b110), 30)
        card_table.update_cardinality_estimation(Subproblem(0b111), 10)

        c_out: CostFunction = C_Out()

        self.assertFalse(chain_query.is_connected(Subproblem(0b101)))
        self.assertFalse(chain_query.are_connected(Subproblem(0b1), Subproblem(0b100)))
        self.assertEqual(chain_query.get_neighbors(Subproblem(0b10)), Subproblem(0b101))

        self.assertEqual(c_out.estimate_filter_costs(Subproblem(0b1), card_table), 20)
        self.assertEqual(c_out.estimate_filter_costs(Subproblem(0b10), card_table), 30)
        self.assertEqual(c_out.estimate_filter_costs(Subproblem(0b100), card_table), 40)

        standard_plan_table: StandardPlanTable = StandardPlanTable(
            chain_query, c_out, card_table
        )

        self.assertEqual(
            c_out.estimate_join_costs(
                Subproblem(0b1), Subproblem(0b10), card_table, standard_plan_table
            ),
            650,  # Cartesian Product
        )

        self.assertEqual(
            c_out.estimate_join_costs(
                Subproblem(0b10), Subproblem(0b100), card_table, standard_plan_table
            ),
            100,
        )

        size_based_plan_table: SizeBasedPlanTable = SizeBasedPlanTable(
            chain_query, c_out, card_table
        )

        def _test_plan_table(plan_table: PlanTable):
            plan_table.update_table(
                Subproblem(0b1), Subproblem(0b10), card_table, c_out
            )
            plan_table.update_table(
                Subproblem(0b10), Subproblem(0b100), card_table, c_out
            )
            plan_table.update_table(
                Subproblem(0b11), Subproblem(0b100), card_table, c_out
            )
            plan_table.update_table(
                Subproblem(0b110), Subproblem(0b1), card_table, c_out
            )

            self.assertTrue(Subproblem(0b1) in plan_table)
            self.assertEqual(plan_table.get_costs_for_subproblem(Subproblem(0b1)), 20)
            self.assertTrue(Subproblem(0b10) in plan_table)
            self.assertEqual(plan_table.get_costs_for_subproblem(Subproblem(0b10)), 30)
            self.assertTrue(Subproblem(0b100) in plan_table)
            self.assertEqual(plan_table.get_costs_for_subproblem(Subproblem(0b100)), 40)
            self.assertTrue(Subproblem(0b11) in plan_table)
            self.assertEqual(plan_table.get_costs_for_subproblem(Subproblem(0b11)), 650)
            self.assertTrue(Subproblem(0b110) in plan_table)
            self.assertEqual(
                plan_table.get_costs_for_subproblem(Subproblem(0b110)), 100
            )
            self.assertTrue(Subproblem(0b111) in plan_table)
            self.assertEqual(
                plan_table.get_costs_for_subproblem(Subproblem(0b111)), 130
            )

        _test_plan_table(standard_plan_table)
        _test_plan_table(size_based_plan_table)

        enumerated_entries: list[Subproblem] = []
        expected_entries: list[Subproblem] = [Subproblem(0b10), Subproblem(0b100)]
        for entry in size_based_plan_table.entries_with_size(1, 1):
            enumerated_entries.append(entry)

        self.assertListEqual(enumerated_entries, expected_entries)

    def test_chain_query(self):
        chain_query: JoinGraph = ChainQueryFactory.construct_join_graph(5)

        self.assertEqual(chain_query.get_neighbors(Subproblem(0b1)), Subproblem(0b10))
        self.assertEqual(chain_query.get_neighbors(Subproblem(0b10)), Subproblem(0b101))
        self.assertEqual(
            chain_query.get_neighbors(Subproblem(0b100)), Subproblem(0b1010)
        )
        self.assertEqual(
            chain_query.get_neighbors(Subproblem(0b1000)), Subproblem(0b10100)
        )
        self.assertEqual(
            chain_query.get_neighbors(Subproblem(0b10000)), Subproblem(0b1000)
        )

    def test_cycle_query(self):
        cycle_query: JoinGraph = CycleQueryFactory.construct_join_graph(5)

        self.assertEqual(
            cycle_query.get_neighbors(Subproblem(0b1)), Subproblem(0b10010)
        )
        self.assertEqual(cycle_query.get_neighbors(Subproblem(0b10)), Subproblem(0b101))
        self.assertEqual(
            cycle_query.get_neighbors(Subproblem(0b100)), Subproblem(0b1010)
        )
        self.assertEqual(
            cycle_query.get_neighbors(Subproblem(0b1000)), Subproblem(0b10100)
        )
        self.assertEqual(
            cycle_query.get_neighbors(Subproblem(0b10000)), Subproblem(0b1001)
        )

    def test_star_query(self):
        star_query: JoinGraph = StarQueryFactory.construct_join_graph(5)

        self.assertEqual(star_query.get_neighbors(Subproblem(0b1)), Subproblem(0b11110))
        self.assertEqual(star_query.get_neighbors(Subproblem(0b10)), Subproblem(0b1))
        self.assertEqual(star_query.get_neighbors(Subproblem(0b100)), Subproblem(0b1))
        self.assertEqual(star_query.get_neighbors(Subproblem(0b1000)), Subproblem(0b1))
        self.assertEqual(star_query.get_neighbors(Subproblem(0b10000)), Subproblem(0b1))

    def test_clique_query(self):
        clique_query: JoinGraph = CliqueQueryFactory.construct_join_graph(5)

        self.assertEqual(
            clique_query.get_neighbors(Subproblem(0b1)), Subproblem(0b11110)
        )
        self.assertEqual(
            clique_query.get_neighbors(Subproblem(0b10)), Subproblem(0b11101)
        )
        self.assertEqual(
            clique_query.get_neighbors(Subproblem(0b100)), Subproblem(0b11011)
        )
        self.assertEqual(
            clique_query.get_neighbors(Subproblem(0b1000)), Subproblem(0b10111)
        )
        self.assertEqual(
            clique_query.get_neighbors(Subproblem(0b10000)), Subproblem(0b01111)
        )


if __name__ == "__main__":
    unittest.main(
        argv=["ignored", "-v"],
        defaultTest="PlanEnumerationTests",
        verbosity=2,
        exit=False,
    )
