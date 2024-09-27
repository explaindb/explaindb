import itertools
from abc import ABC, abstractmethod
from collections import deque
from typing import Deque
from system.plan_enumeration.subproblems import Subproblem


class JoinGraph:
    """
    A join graph for a query. Internally, it uses an adjacency list to represent the graph.
    """

    def __init__(self):
        self.adjacency_matrix = dict()

    def __len__(self) -> int:
        return len(self.adjacency_matrix)

    def __iter__(self):
        return iter(self.adjacency_matrix)

    def add_relation(self, relation_id: int):
        """
        Adds a relation to a join graph.
        :param relation_id: The number of the relation to be used.
        """

        # Store relation in adjacency matrix
        self.adjacency_matrix[relation_id] = Subproblem()

    def add_join(self, left_relation: int, right_relation: int):
        """
        Adds a join between the left and the right relation.
        :param left_relation: The id of the left relation.
        :param right_relation: The id of the right relation.
        """
        left_problem = Subproblem.get_problem_for_relation(left_relation)
        right_problem = Subproblem.get_problem_for_relation(right_relation)

        if (
            left_relation not in self.adjacency_matrix
            or right_relation not in self.adjacency_matrix
        ):
            raise ValueError(
                "You can not join relation that are not yet added to the join graph"
            )

        self.adjacency_matrix[left_relation] += right_problem
        self.adjacency_matrix[right_relation] += left_problem

    def are_connected(self, left: Subproblem, right: Subproblem) -> bool:
        """
        Checks whether the left and right subproblem are connected.
        :param left: The left subproblem.
        :param right: The right subproblem.
        :return: True, if the subproblems are connected, False if not.
        """
        # Get all subproblems that are connected with the left subproblem
        connected_with_left: Subproblem = left
        for problem in left:
            connected_with_left |= self.adjacency_matrix[problem.get_relation_id()]
        return (connected_with_left & right) != Subproblem()

    def is_connected(self, problem: Subproblem) -> bool:
        """
        Checks whether the problem is connected in the join graph.
        :param problem: The problem to be checked.
        :return: True, if the problem is connected, False if not.
        """
        # Starting Singleton for the DFS
        visited: Subproblem = problem.get_lsb_problem()
        # Use stack
        to_be_checked: Deque[int] = deque([visited.get_relation_id()])
        # Perform regular DFS
        while to_be_checked:
            next_relation: int = to_be_checked.pop()
            # Each neighbor is a singleton problem
            for neighbor in self.adjacency_matrix[next_relation] & problem:
                if not neighbor.overlaps(visited):
                    visited |= neighbor
                    to_be_checked.append(neighbor.get_relation_id())

        # If all problems were visited, we know that the entire problem is connected
        return visited == problem

    def get_neighbors(self, s: Subproblem) -> Subproblem:
        """
        Get all neighbors of a given problem s (excluding s).
        :param s: The set whose neighbors are of interest.
        :return: The neighbors as subproblem.
        """
        # Start with empty problem
        neighbors: Subproblem = Subproblem()

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
        pass


class ChainQueryFactory(JoinGraphFactory):
    """
    Creates a chain query of the given size.
    """

    @staticmethod
    def construct_join_graph(num_nodes: int) -> JoinGraph:
        """
        Create a join graph for a chain query.
        :param num_nodes: The number of relations in the join graph.
        :return: The chain join graph.
        """

        chain_query = JoinGraph()

        for i in range(num_nodes):
            chain_query.add_relation(i)

        for i in range(num_nodes - 1):
            chain_query.add_join(i, i + 1)

        return chain_query


class StarQueryFactory(JoinGraphFactory):
    """
    Creates a star query of the given size.
    """

    @staticmethod
    def construct_join_graph(num_nodes: int) -> JoinGraph:
        """
        Create a join graph for a star query.
        :param num_nodes: The number of relations in the join graph.
        :return: The star join graph.
        """

        star_query = JoinGraph()

        for i in range(num_nodes):
            star_query.add_relation(i)

        for i in range(1, num_nodes):
            star_query.add_join(0, i)  # 0 is the fact table

        return star_query


class CycleQueryFactory(JoinGraphFactory):
    """
    Creates a cycle query of the given size.
    """

    @staticmethod
    def construct_join_graph(num_nodes: int) -> JoinGraph:
        """
        Create a join graph for a cycle query.
        :param num_nodes: The number of relations in the join graph.
        :return: The cycle join graph.
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
        """
        Create a join graph for a clique query.
        :param num_nodes: The number of relations in the join graph.
        :return: The clique join graph.
        """

        clique_query = JoinGraph()

        for i in range(num_nodes):
            clique_query.add_relation(i)

        for tup in itertools.product(range(num_nodes), range(num_nodes)):
            clique_query.add_join(tup[0], tup[1])

        return clique_query
