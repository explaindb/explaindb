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

# Test modules use self-documenting method/class names and module-level
# fixtures, so pylint's naming and docstring checks are relaxed here.
# pylint: disable=invalid-name,missing-class-docstring,missing-function-docstring
"""Tests for join-plan enumeration and problem (relation-subset) operations."""

import contextlib
import io
import unittest
from system.query_optimization.problems import Problem
from system.query_optimization.cost_function import C_Out
from system.interfaces.cost_functions import CostFunction
from system.query_optimization.plan_table import (
    StandardPlanTable,
    SizeBasedPlanTable,
)
from system.interfaces.query_optimization.planning import PlanEnumerator, PlanTable
from system.query_optimization.cardinality_table import CardinalityTable
from system.query_optimization.join_graph import (
    JoinGraph,
    ChainQueryFactory,
    CycleQueryFactory,
    StarQueryFactory,
    CliqueQueryFactory,
)
from system.query_optimization.plan_enumeration import (
    DP_Size,
    DP_Sub,
    DP_CCP,
    generate_connected_problems,
    generate_ccp_pairs,
)
from system.query_optimization.utils import randomize_cardinalities


class PlanEnumerationTests(unittest.TestCase):
    def test_problemOperations(self):
        """
        Problem bit-set operations: equality, union/difference, hash, length, as_set, intersection, least-significant
        bit, and containment.
        """
        # two problems over a query with 5 relations, bit i stands for relation i: x = {1, 3} and y = {1, 4}:
        x: Problem = Problem(0b01010, 5)
        y: Problem = Problem(0b10010, 5)
        # two problems are equal if the same bits are set (a plain int is never equal to a problem); + is the set
        # union and - is the set difference:
        self.assertNotEqual(x, y)
        self.assertNotEqual(x, 0b1010)
        self.assertEqual(x, Problem(0b1010, 5))
        self.assertEqual(x + y, Problem(0b11010, 5))
        self.assertEqual(x - y, Problem(0b1000, 5))
        self.assertEqual(y - x, Problem(0b10000, 5))
        # hash() is the underlying integer and len() the number of relations in the query (5), not the number of set
        # bits; as_set() returns the ids of the contained relations, which is also what str() prints:
        self.assertEqual(hash(x), 0b1010)
        self.assertEqual(hash(y), 0b10010)
        self.assertEqual(len(x), 5)
        self.assertEqual(len(x), len(y))
        self.assertSetEqual({1, 3}, x.as_set())
        self.assertSetEqual({1, 4}, y.as_set())
        self.assertEqual(str(x), str(x.as_set()))
        # both problems contain relation 1, so they intersect, and bit 1 is the lowest set bit of both:
        self.assertTrue(x.intersects(y))
        self.assertTrue(y.intersects(x))
        self.assertEqual(x.get_least_significant_bit(), Problem(0b10, 5))
        self.assertEqual(y.get_least_significant_bit(), Problem(0b10, 5))
        self.assertEqual(y.get_least_significant_bit(), x.get_least_significant_bit())
        # contains_bit_sequence() checks for a superset: a problem contains itself and its subsets, but neither x
        # nor y contains the other:
        self.assertFalse(x.contains_bit_sequence(y))
        self.assertTrue(x.contains_bit_sequence(x))
        self.assertFalse(y.contains_bit_sequence(x))
        self.assertTrue(y.contains_bit_sequence(y))
        self.assertTrue(y.contains_bit_sequence(Problem(0b10000, 5)))
        # get_smaller_or_equal_relations() gives all relations with an id up to the smallest id in x (1), i.e. {0, 1};
        # get_relation_id() works only for a problem with exactly one relation and raises a ValueError otherwise:
        self.assertEqual(x.get_smaller_or_equal_relations(), Problem(0b11, 5))
        with self.assertRaises(ValueError):
            x.get_relation_id()
        self.assertEqual(Problem(0b10000, 5).get_relation_id(), 4)
        # build the problem of a single relation id and the problem with all relations of a query:
        self.assertEqual(Problem(0b100000, 6), Problem.get_problem_for_relation(5, 6))
        self.assertEqual(Problem.get_problem_with_all_relations(4), Problem(0b1111, 4))

    def test_SingletonIterator(self):
        """
        Iterating a problem yields its relations as singleton problems, forward and in reverse.
        """
        # x = {0, 1, 3}; iterating it yields one singleton problem per relation, from the lowest to the highest id:
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

        # reversed() yields the same singletons, from the highest to the lowest id:
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
        # x = {1, 2, 4}; its non-empty subsets, ordered by their integer value:
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

        # enumerate the subsets one by one; get_all_problems() returns the same list in one go:
        for next_problem in Problem.enumerate_all_problems(x):
            enumerated_problems.append(next_problem)
        self.assertListEqual(expected_problems, enumerated_problems)
        self.assertListEqual(Problem.get_all_problems(x), enumerated_problems)

        # enumerate only a range: from the start problem {1, 2} (included) up to the stop problem {2, 4} (excluded):
        adapted_expected_problems: list[Problem] = expected_problems[2:5]
        adapted_enumerated_problems: list[Problem] = []
        for next_problem in Problem.enumerate_all_problems(
            x, Problem(0b110, 5), Problem(0b10100, 5)
        ):
            adapted_enumerated_problems.append(next_problem)
        self.assertListEqual(adapted_expected_problems, adapted_enumerated_problems)

    def test_enumeration_utilities(self):
        """
        Join-graph connectivity, C_out costs, and plan tables for a chain query: both implementations keep the
        cheaper plan, agree on costs and best plans, and the size-based one lists its entries by size.
        """
        # a chain query R0 - R1 - R2 with cardinalities for the three base relations, for the join of R1 and R2, and
        # for the join of all three relations; there is no entry for the join of R0 and R1:
        chain_query: JoinGraph = ChainQueryFactory.construct_join_graph(3)
        card_table: CardinalityTable = CardinalityTable()
        card_table.update_cardinality_estimation(Problem(0b1, 3), 20)
        card_table.update_cardinality_estimation(Problem(0b10, 3), 30)
        card_table.update_cardinality_estimation(Problem(0b100, 3), 40)
        card_table.update_cardinality_estimation(Problem(0b110, 3), 30)
        card_table.update_cardinality_estimation(Problem(0b111, 3), 10)

        c_out: CostFunction = C_Out()

        # R0 and R2 are not joined with each other, so {R0, R2} is not connected; R1 is joined with both:
        self.assertFalse(chain_query.is_connected(Problem(0b101, 3)))
        self.assertFalse(chain_query.are_connected(Problem(0b1, 3), Problem(0b100)))
        self.assertEqual(chain_query.get_neighbors(Problem(0b10, 3)), Problem(0b101))

        # C_out charges a base relation with its cardinality:
        self.assertEqual(c_out.estimate_filter_costs(Problem(0b1, 3), card_table), 20)
        self.assertEqual(c_out.estimate_filter_costs(Problem(0b10, 3), card_table), 30)
        self.assertEqual(c_out.estimate_filter_costs(Problem(0b100, 3), card_table), 40)

        # a new plan table already holds one entry per base relation, with the filter costs from above:
        standard_plan_table: StandardPlanTable = StandardPlanTable(
            chain_query, c_out, card_table
        )

        # C_out of a join = estimated output cardinality + costs of both inputs (taken from the plan table); the
        # cardinality table has no entry for R0 and R1, so it estimates the Cartesian product 20 * 30 = 600 (and
        # stores it), giving 600 + 20 + 30:
        self.assertEqual(
            c_out.estimate_join_costs(
                Problem(0b1, 3), Problem(0b10, 3), card_table, standard_plan_table
            ),
            650,
        )

        # for R1 and R2 the cardinality table has an entry, giving 30 + 30 + 40:
        self.assertEqual(
            c_out.estimate_join_costs(
                Problem(0b10, 3), Problem(0b100, 3), card_table, standard_plan_table
            ),
            100,
        )

        # the size-based plan table stores the same entries, but grouped by their number of relations:
        size_based_plan_table: SizeBasedPlanTable = SizeBasedPlanTable(
            chain_query, c_out, card_table
        )

        def _test_plan_table(plan_table: PlanTable) -> None:
            """Fills the given plan table with the joins of the chain query and checks its costs and plans."""
            # add the joins {R0, R1} and {R1, R2}, then two alternative ways to join all three relations:
            # {R0, R1} with R2, and R0 with {R1, R2}:
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

            # the base relations keep their filter costs:
            self.assertTrue(Problem(0b1, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b1, 3)), 20)
            self.assertTrue(Problem(0b10, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b10, 3)), 30)
            self.assertTrue(Problem(0b100, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b100, 3)), 40)
            # the two-relation joins get the costs computed above:
            self.assertTrue(Problem(0b11, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b11, 3)), 650)
            self.assertTrue(Problem(0b110, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b110, 3)), 100)
            # for all three relations the cheaper alternative is kept: R0 with {R1, R2} costs 10 + 20 + 100 = 130,
            # whereas {R0, R1} with R2 costs 10 + 40 + 650 = 700:
            self.assertTrue(Problem(0b111, 3) in plan_table)
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b111, 3)), 130)

            # adding the more expensive alternative again does not replace the cheaper plan:
            plan_table.update_table(
                Problem(0b11, 3), Problem(0b100, 3), card_table, c_out
            )
            self.assertEqual(plan_table.get_costs_for_problem(Problem(0b111, 3)), 130)

            # a plan is a relation id or a nested pair (left, right), with the input of smaller cardinality on the
            # left; the best plan for all three relations joins R0 (20 rows) with the join of R1 and R2 (30 rows):
            self.assertEqual(plan_table.get_plan_for_problem(Problem(0b11, 3)), (0, 1))
            self.assertEqual(plan_table.get_plan_for_problem(Problem(0b110, 3)), (1, 2))
            self.assertEqual(
                plan_table.get_plan_for_problem(Problem(0b111, 3)), (0, (1, 2))
            )

        # both plan-table implementations must yield the same costs and plans:
        _test_plan_table(standard_plan_table)
        _test_plan_table(size_based_plan_table)

        # list the entries with one relation (R0, R1, R2 in insertion order), skipping the first one (start index 1):
        enumerated_entries: list[Problem] = []
        expected_entries: list[Problem] = [Problem(0b10, 3), Problem(0b100, 3)]
        for entry in size_based_plan_table.entries_with_size(1, 1):
            enumerated_entries.append(entry)

        self.assertListEqual(enumerated_entries, expected_entries)

    def test_chain_query(self):
        """
        Neighbours of every relation in a chain join graph.
        """
        chain_query: JoinGraph = ChainQueryFactory.construct_join_graph(5)

        # in the chain R0 - R1 - R2 - R3 - R4, the two ends have one neighbour and every inner relation has two:
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
        Neighbours of every relation in a cycle join graph.
        """
        cycle_query: JoinGraph = CycleQueryFactory.construct_join_graph(5)

        # the cycle is the chain R0 - R1 - R2 - R3 - R4 plus the join of R4 and R0,
        # so every relation has two neighbours:
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
        Neighbours of every relation in a star join graph.
        """
        star_query: JoinGraph = StarQueryFactory.construct_join_graph(5)

        # R0 is the centre of the star (the fact table) and is joined with all other relations, each of which is
        # joined with R0 only:
        self.assertEqual(star_query.get_neighbors(Problem(0b1, 5)), Problem(0b11110))
        self.assertEqual(star_query.get_neighbors(Problem(0b10, 5)), Problem(0b1))
        self.assertEqual(star_query.get_neighbors(Problem(0b100, 5)), Problem(0b1))
        self.assertEqual(star_query.get_neighbors(Problem(0b1000, 5)), Problem(0b1))
        self.assertEqual(star_query.get_neighbors(Problem(0b10000, 5)), Problem(0b1))

    def test_clique_query(self):
        """
        Neighbours of every relation in a clique join graph.
        """
        clique_query: JoinGraph = CliqueQueryFactory.construct_join_graph(5)

        # every relation is joined with every relation, itself included,
        # but get_neighbors() never returns the relation itself:
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

    def test_plan_enumerators(self):
        """
        DPsize, DPsub and DPccp find the same best plan with the same costs on a chain of five relations, and
        enumerate 73, 42 and 20 pairs.
        """
        join_graph: JoinGraph = ChainQueryFactory.construct_join_graph(5)
        cardinality_table: CardinalityTable = CardinalityTable()
        # set the cardinalities of the connected problems, by size; size 1:
        cardinality_table.update_cardinality_estimation(Problem(0b1, 5), 5000)
        cardinality_table.update_cardinality_estimation(Problem(0b10, 5), 4000)
        cardinality_table.update_cardinality_estimation(Problem(0b100, 5), 500)
        cardinality_table.update_cardinality_estimation(Problem(0b1000, 5), 100)
        cardinality_table.update_cardinality_estimation(Problem(0b10000, 5), 1000)

        # size 2:
        cardinality_table.update_cardinality_estimation(Problem(0b11, 5), 100)
        cardinality_table.update_cardinality_estimation(Problem(0b110, 5), 500)
        cardinality_table.update_cardinality_estimation(Problem(0b1100, 5), 100)
        cardinality_table.update_cardinality_estimation(Problem(0b11000, 5), 100)

        # size 3:
        cardinality_table.update_cardinality_estimation(Problem(0b111, 5), 500)
        cardinality_table.update_cardinality_estimation(Problem(0b1110, 5), 50)
        cardinality_table.update_cardinality_estimation(Problem(0b11100, 5), 100)

        # size 4:
        cardinality_table.update_cardinality_estimation(Problem(0b1111, 5), 10)
        cardinality_table.update_cardinality_estimation(Problem(0b11110, 5), 100)

        # size 5:
        cardinality_table.update_cardinality_estimation(Problem(0b11111, 5), 10)

        # the expected best plan and costs, and the number of pairs each algorithm enumerates:
        best_plan: tuple = (
            (((3, 2), 1), 0),
            4,
        )
        best_costs: int = 10770
        algorithm_pairs: dict[str, int] = {
            "DP_Sub": 42,
            "DP_Size": 73,
            "DP_CCP": 20,
        }

        def _test_plan_costs(enumeration_algorithm: PlanEnumerator) -> None:
            """Runs the given enumerator on the chain query and checks its best plan, costs and number of pairs."""
            costs, plan, enumerated_pairs = enumeration_algorithm.enumerate(
                join_graph, cardinality_table, C_Out(), False
            )
            self.assertEqual(plan, best_plan)
            self.assertEqual(costs, best_costs)
            self.assertEqual(
                enumerated_pairs,
                algorithm_pairs[enumeration_algorithm.__class__.__name__],
            )

        _test_plan_costs(DP_Size())
        _test_plan_costs(DP_Sub())
        _test_plan_costs(DP_CCP())

    def test_csg_enumeration(self):
        """
        generate_connected_problems yields every connected problem of a chain of five relations exactly once,
        starting from the highest relation.
        """
        chain_query: JoinGraph = ChainQueryFactory.construct_join_graph(5)
        # each singleton from the highest relation down, followed by the connected problems it is extended to:
        correct_csgs: list[Problem] = [
            Problem(0b10000, 5),
            Problem(0b1000, 5),
            Problem(0b11000, 5),
            Problem(0b100, 5),
            Problem(0b1100, 5),
            Problem(0b11100, 5),
            Problem(0b10, 5),
            Problem(0b110, 5),
            Problem(0b1110, 5),
            Problem(0b11110, 5),
            Problem(0b1, 5),
            Problem(0b11, 5),
            Problem(0b111, 5),
            Problem(0b1111, 5),
            Problem(0b11111, 5),
        ]

        csgs_without_duplicates: list[Problem] = list(
            generate_connected_problems(chain_query)
        )

        self.assertListEqual(csgs_without_duplicates, correct_csgs)

    def test_ccp_helper_enumeration(self):
        """
        generate_ccp_pairs yields every csg-cmp pair of a chain of five relations exactly once, grouped by csg in the
        order in which generate_connected_problems yields the csgs.
        """
        chain_query: JoinGraph = ChainQueryFactory.construct_join_graph(5)

        # the pairs grouped by their csg, in the order generate_connected_problems yields the csgs:
        correct_ccps: list[tuple[Problem, Problem]] = [
            (Problem(0b1000, 5), Problem(0b10000, 5)),
            (Problem(0b100, 5), Problem(0b1000, 5)),
            (Problem(0b100, 5), Problem(0b11000, 5)),
            (Problem(0b1100, 5), Problem(0b10000, 5)),
            (Problem(0b10, 5), Problem(0b100, 5)),
            (Problem(0b10, 5), Problem(0b1100, 5)),
            (Problem(0b10, 5), Problem(0b11100, 5)),
            (Problem(0b110, 5), Problem(0b1000, 5)),
            (Problem(0b110, 5), Problem(0b11000, 5)),
            (Problem(0b1110, 5), Problem(0b10000, 5)),
            (Problem(0b1, 5), Problem(0b10, 5)),
            (Problem(0b1, 5), Problem(0b110, 5)),
            (Problem(0b1, 5), Problem(0b1110, 5)),
            (Problem(0b1, 5), Problem(0b11110, 5)),
            (Problem(0b11, 5), Problem(0b100, 5)),
            (Problem(0b11, 5), Problem(0b1100, 5)),
            (Problem(0b11, 5), Problem(0b11100, 5)),
            (Problem(0b111, 5), Problem(0b1000, 5)),
            (Problem(0b111, 5), Problem(0b11000, 5)),
            (Problem(0b1111, 5), Problem(0b10000, 5)),
        ]

        generated_ccps = list(generate_ccp_pairs(chain_query))
        self.assertListEqual(generated_ccps, correct_ccps)

    def test_csg_enumeration_on_cycle(self):
        """
        generate_connected_problems yields every connected problem of the cycle R0 - R1 - R2 - R3 - R0 (the example
        of the notebook) exactly once, also where a problem can grow in two directions.
        """
        cycle_query: JoinGraph = CycleQueryFactory.construct_join_graph(4)

        # the connected problems: {0} grows by {1}, by {3} and by both at once:
        self.assertListEqual(
            [problem.as_set() for problem in generate_connected_problems(cycle_query)],
            [
                {3},
                {2},
                {2, 3},
                {1},
                {1, 2},
                {1, 2, 3},
                {0},
                {0, 1},
                {0, 3},
                {0, 1, 3},
                {0, 1, 2},
                {0, 2, 3},
                {0, 1, 2, 3},
            ],
        )

    def test_ccp_helper_enumeration_on_cycle(self):
        """
        generate_ccp_pairs yields every csg-cmp pair of the cycle R0 - R1 - R2 - R3 - R0 exactly once, grouped by
        csg in the order in which generate_connected_problems yields the csgs.
        """
        cycle_query: JoinGraph = CycleQueryFactory.construct_join_graph(4)

        # the csg-cmp pairs, grouped by csg; for the csg {0}, the cmps start with {3} and then {1}:
        self.assertListEqual(
            [(s1.as_set(), s2.as_set()) for s1, s2 in generate_ccp_pairs(cycle_query)],
            [
                ({2}, {3}),
                ({1}, {2}),
                ({1}, {2, 3}),
                ({1, 2}, {3}),
                ({0}, {3}),
                ({0}, {2, 3}),
                ({0}, {1}),
                ({0}, {1, 2}),
                ({0}, {1, 2, 3}),
                ({0, 1}, {3}),
                ({0, 1}, {2}),
                ({0, 1}, {2, 3}),
                ({0, 3}, {2}),
                ({0, 3}, {1}),
                ({0, 3}, {1, 2}),
                ({0, 1, 3}, {2}),
                ({0, 1, 2}, {3}),
                ({0, 2, 3}, {1}),
            ],
        )

    def test_plan_enumerators_on_cycle(self):
        """
        DPsize, DPsub and DPccp find the same best plan with the same costs on the cycle R0 - R1 - R2 - R3 - R0 with
        the notebook's random cardinalities, enumerate 44, 23 and 18 pairs, and print nothing without print_info.
        """
        cycle_query: JoinGraph = CycleQueryFactory.construct_join_graph(4)

        # with the notebook's random cardinalities (seed 42), all three enumerators find the plan (3⋈((1⋈0)⋈2)) with
        # costs 2011; DPsize enumerates 44 pairs, DPsub 23 and DPccp only the 18 valid ones:
        for plan_enumerator, pairs in ((DP_Size(), 44), (DP_Sub(), 23), (DP_CCP(), 18)):
            with self.subTest(plan_enumerator=plan_enumerator.__class__.__name__):
                cardinality_table: CardinalityTable = CardinalityTable()
                randomize_cardinalities(cardinality_table, 4, 42)
                output: io.StringIO = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result: tuple[int, tuple, int] = plan_enumerator.enumerate(
                        cycle_query, cardinality_table, C_Out()
                    )
                self.assertEqual(result, (2011, (3, ((1, 0), 2)), pairs))

                # print_info is off by default, so nothing is printed:
                self.assertEqual(output.getvalue(), "")

    def _enumerate_chain_of_three(
        self, plan_enumerator: PlanEnumerator
    ) -> tuple[int, list[str]]:
        """
        Runs the given enumerator with print_info on a chain query R0 - R1 - R2 and captures what it prints.
        :param plan_enumerator: The enumerator to run.
        :return: A tuple, consisting of the number of enumerated pairs the enumerator returns and its printed lines.
        """
        # random cardinalities with a fixed seed and C_out; the printed pairs depend only on the join graph, not on
        # the cardinalities:
        chain_query: JoinGraph = ChainQueryFactory.construct_join_graph(3)
        cardinality_table: CardinalityTable = CardinalityTable()
        randomize_cardinalities(cardinality_table, 3, 42)
        cost_function: CostFunction = C_Out()

        # run the enumerator and collect its output line by line:
        output: io.StringIO = io.StringIO()
        with contextlib.redirect_stdout(output):
            _, _, enumerated_pairs = plan_enumerator.enumerate(
                chain_query, cardinality_table, cost_function, print_info=True
            )
        return enumerated_pairs, output.getvalue().splitlines()

    def test_DP_Size_prints_enumerated_pairs(self):
        """
        DPsize prints every pair it enumerates on a chain of three relations, valid or not, in size order, and a
        summary.
        """
        enumerated_pairs, lines = self._enumerate_chain_of_three(DP_Size())

        # all pairs of plan-table entries whose sizes add up to 2, then to 3; a pair is invalid if its two problems
        # overlap or are not joined with each other:
        self.assertListEqual(
            [
                "Enumerated valid pair {0}, {1}.",
                "Enumerated invalid pair {0}, {2}.",
                "Enumerated valid pair {1}, {2}.",
                "Enumerated invalid pair {0}, {0, 1}.",
                "Enumerated valid pair {0}, {1, 2}.",
                "Enumerated invalid pair {1}, {0, 1}.",
                "Enumerated invalid pair {1}, {1, 2}.",
                "Enumerated valid pair {2}, {0, 1}.",
                "Enumerated invalid pair {2}, {1, 2}.",
                "9 pairs were enumerated, out of which 4 were valid!",
            ],
            lines,
        )
        # the returned count includes the invalid pairs:
        self.assertEqual(enumerated_pairs, 9)

    def test_DP_Sub_prints_enumerated_pairs(self):
        """
        DPsub prints every pair it enumerates on a chain of three relations, splitting each connected problem in
        increasing-integer order, and a summary.
        """
        enumerated_pairs, lines = self._enumerate_chain_of_three(DP_Sub())

        # the connected problems {0, 1}, {1, 2} and {0, 1, 2} are split into disjoint halves; the pair {1}, {0, 2} is
        # invalid because {0, 2} is not connected:
        self.assertListEqual(
            [
                "Enumerated valid pair {0}, {1}",
                "Enumerated valid pair {1}, {2}",
                "Enumerated valid pair {0}, {1, 2}",
                "Enumerated invalid pair {1}, {0, 2}",
                "Enumerated valid pair {0, 1}, {2}",
                "5 pairs were enumerated, out of which 4 were valid",
            ],
            lines,
        )
        # the returned count includes the invalid pair:
        self.assertEqual(enumerated_pairs, 5)

    def test_DP_CCP_prints_enumerated_pairs(self):
        """
        DPccp prints every csg-cmp pair it enumerates on a chain of three relations, all of them valid, and a
        summary.
        """
        enumerated_pairs, lines = self._enumerate_chain_of_three(DP_CCP())

        # the connected subgraphs are generated from the highest relation down, so the pair {1}, {2} comes first:
        self.assertListEqual(
            [
                "Enumerated valid pair {1}, {2}",
                "Enumerated valid pair {0}, {1}",
                "Enumerated valid pair {0}, {1, 2}",
                "Enumerated valid pair {0, 1}, {2}",
                "Enumerated 4 valid pairs",
            ],
            lines,
        )
        self.assertEqual(enumerated_pairs, 4)


if __name__ == "__main__":
    unittest.main(
        argv=["ignored", "-v"],
        defaultTest="PlanEnumerationTests",
        verbosity=2,
        exit=False,
    )
