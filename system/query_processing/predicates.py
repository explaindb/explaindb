"""WHERE-clause predicates and clause combinators for query processing."""

from abc import abstractmethod, ABC


class Clause(ABC):
    """Interface for a WHERE-clause predicate that can be evaluated against a single object (row)."""

    @abstractmethod
    def evaluate(self, _object) -> bool:
        """Evaluate this clause against a single object (row).

        :param _object: The object (row) whose attributes the predicate is tested against.
        :return: ``True`` if the object satisfies the clause, ``False`` otherwise.
        """
        pass


class WHERE_Clause(Clause):
    """A WHERE clause in SQL is a clause that specifies a filter condition for selecting data. The condition is
    evaluated to true, false, or unknown.
    """

    def __init__(self, attribute: str, operator: str, constant):
        """Build a WHERE clause of the form ``attribute operator constant`` and sanitize it.

        :param attribute: Name of the attribute to read from the tested object.
        :param operator: Comparison operator, one of ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``.
        :param constant: Constant value the attribute is compared against.
        """
        super().__init__()
        self.attribute: str = attribute
        self.operator: str = operator
        self.constant: object = constant
        self.sanitize()

    def sanitize(self):
        """Sanitizes the WHERE clause for security reasons."""
        # we only allow the following operators:
        assert self.operator in [
            "==",
            "!=",
            "<",
            "<=",
            ">",
            ">=",
        ], "invalid operator"

        # we only allow the following attributes:
        assert self.attribute.isalpha(), "invalid attribute"

        # we only allow the following constants:
        assert isinstance(self.constant, int) or (
            isinstance(self.constant, str) and self.constant.isalnum()
        ), "invalid constant"

    def evaluate(self, _object: object) -> bool:
        """See :meth:`Clause.evaluate`.

        Reads ``self.attribute`` from the object and compares it against ``self.constant`` using ``self.operator``.
        """
        value = getattr(_object, self.attribute)
        if self.operator == "==":
            return value == self.constant
        elif self.operator == "!=":
            return value != self.constant
        elif self.operator == "<":
            return value < self.constant
        elif self.operator == "<=":
            return value <= self.constant
        elif self.operator == ">":
            return value > self.constant
        elif self.operator == ">=":
            return value >= self.constant
        else:
            raise ValueError("Invalid operator")


class Disjunction(Clause):
    """A disjunction is a logical operation that outputs true if at least one of the operands is true."""

    def __init__(self, *clauses: Clause):
        """Build a disjunction (logical OR) over the given clauses.

        :param clauses: The operand clauses combined by logical OR.
        """
        super().__init__()
        self.clauses = clauses

    def evaluate(self, _object) -> bool:
        """See :meth:`Clause.evaluate`.

        Returns ``True`` as soon as any of the contained clauses evaluates to ``True`` (logical OR).
        """
        return any(clause.evaluate(_object) for clause in self.clauses)


class TrueClause(Clause):
    """A clause that always evaluates to True."""

    def evaluate(self, _object) -> bool:
        """See :meth:`Clause.evaluate`.

        Always returns ``True``.
        """
        return True


class FalseClause(Clause):
    """A clause that always evaluates to False."""

    def evaluate(self, _object) -> bool:
        """See :meth:`Clause.evaluate`.

        Always returns ``False``.
        """
        return False
