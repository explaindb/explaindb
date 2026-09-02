"""Join graph model and factories for chain, star, cycle, and clique queries."""

import itertools
from abc import ABC, abstractmethod
from collections import deque
from typing import Deque
from system.query_optimization.problems import Problem


class JoinGraph:
    """
    A join graph for a query. Internally, it uses an adjacency list to represent the graph.
    """

    def __init__(self, number_of_relations: int):
        """
        Create an empty join graph over the given number of relations.
        :param number_of_relations: The number of relations (nodes) in the join graph.
        """
        self.number_of_relations: int = number_of_relations
        self.adjacency_matrix: list[Problem] = [
            Problem.create_all_false_bit_sequence(self.number_of_relations)
            for _ in range(number_of_relations)
        ]

    def __len__(self) -> int:
        """Returns the number of relations (nodes) in the join graph."""
        return len(self.adjacency_matrix)

    def __iter__(self):
        """Iterates over the relation ids (0 to n-1) of the join graph."""
        return iter(range(len(self)))

    def add_join(self, left_relation: int, right_relation: int):
        """
        Adds a join between the left and the right relation.
        :param left_relation: The id of the left relation.
        :param right_relation: The id of the right relation.
        """
        if any(
            size >= len(self.adjacency_matrix)
            for size in [left_relation, right_relation]
        ):
            raise ValueError("A relation is not part of the join graph!")
        left_problem = Problem.get_problem_for_relation(left_relation, len(self))
        right_problem = Problem.get_problem_for_relation(right_relation, len(self))

        self.adjacency_matrix[left_relation] += right_problem
        self.adjacency_matrix[right_relation] += left_problem

    def are_connected(self, left: Problem, right: Problem) -> bool:
        """
        Checks whether the left and right problem are connected.
        :param left: The left problem.
        :param right: The right problem.
        :return: True, if the problems are connected, False if not.
        """
        # Get all problems that are connected with the left problem
        connected_with_left: Problem = left
        for problem in left:
            connected_with_left |= self.adjacency_matrix[problem.get_relation_id()]
        return (connected_with_left & right) != Problem()

    def is_connected(self, problem: Problem) -> bool:
        """
        Checks whether the problem is connected in the join graph.
        :param problem: The problem to be checked.
        :return: True, if the problem is connected, False if not.
        """
        # Starting Singleton for the DFS
        visited: Problem = problem.get_least_significant_bit()

        # Use stack
        to_be_checked: Deque[int] = deque([visited.get_relation_id()])

        # Perform regular DFS
        while to_be_checked:
            next_relation: int = to_be_checked.pop()

            # Each neighbor is a singleton problem
            for neighbor in self.adjacency_matrix[next_relation] & problem:
                if not neighbor.intersects(visited):
                    visited |= neighbor
                    to_be_checked.append(neighbor.get_relation_id())

        # If all problems were visited, we know that the entire problem is connected
        return visited == problem

    def get_neighbors(self, s: Problem) -> Problem:
        """
        Get all neighbors of a given problem s (excluding s).
        :param s: The set whose neighbors are of interest.
        :return: The neighbors as problem.
        """
        # Start with empty problem
        neighbors: Problem = Problem.create_all_false_bit_sequence(
            self.number_of_relations
        )

        # Add each connected neighbor from all relations in S
        for problem in s:
            neighbors += self.adjacency_matrix[problem.get_relation_id()]

        # Remove S from neighbors given that they are already included
        return neighbors - s


class JoinGraphFactory(ABC):
    """
    A simple, abstract factory class to create certain join graph schemes.
    """

    @staticmethod
    @abstractmethod
    def construct_join_graph(num_nodes: int) -> JoinGraph:
        """
        Construct a join graph following this factory's scheme.
        :param num_nodes: The number of relations in the join graph.
        :return: The constructed join graph.
        """
        pass


class ChainQueryFactory(JoinGraphFactory):
    """
    Creates a chain query of the given size.
    """

    @staticmethod
    def construct_join_graph(num_nodes: int) -> JoinGraph:
        """See :meth:`JoinGraphFactory.construct_join_graph`.

        Builds a chain query, joining each relation ``i`` with relation ``i + 1``.
        """

        chain_query = JoinGraph(num_nodes)

        for i in range(num_nodes - 1):
            chain_query.add_join(i, i + 1)

        return chain_query


class StarQueryFactory(JoinGraphFactory):
    """
    Creates a star query of the given size.
    """

    @staticmethod
    def construct_join_graph(num_nodes: int) -> JoinGraph:
        """See :meth:`JoinGraphFactory.construct_join_graph`.

        Builds a star query, joining the fact table (relation ``0``) with every
        other relation.
        """

        star_query = JoinGraph(num_nodes)

        for i in range(1, num_nodes):
            star_query.add_join(0, i)  # 0 is the fact table

        return star_query


class CycleQueryFactory(JoinGraphFactory):
    """
    Creates a cycle query of the given size.
    """

    @staticmethod
    def construct_join_graph(num_nodes: int) -> JoinGraph:
        """See :meth:`JoinGraphFactory.construct_join_graph`.

        Builds a cycle query, i.e., a chain query with an additional edge closing
        the last relation back to the first.
        """
        cycle_query = ChainQueryFactory.construct_join_graph(num_nodes)

        # A cycle is just a chain with an additional edge
        cycle_query.add_join(num_nodes - 1, 0)
        return cycle_query


class CliqueQueryFactory(JoinGraphFactory):
    """
    Creates a clique query of the given size.
    """

    @staticmethod
    def construct_join_graph(num_nodes: int) -> JoinGraph:
        """See :meth:`JoinGraphFactory.construct_join_graph`.

        Builds a clique query, joining every relation with every relation
        (self-joins included).
        """

        clique_query = JoinGraph(num_nodes)

        for tup in itertools.product(range(num_nodes), range(num_nodes)):
            clique_query.add_join(tup[0], tup[1])

        return clique_query
