from abc import abstractmethod, ABC


class Clause(ABC):
    @abstractmethod
    def evaluate(self, _object) -> bool:
        pass


class WHERE_Clause(Clause):
    """A WHERE clause in SQL is a clause that specifies a filter condition for selecting data. The condition is
    evaluated to true, false, or unknown.
    """

    def __init__(self, attribute: str, operator: str, constant):
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
        """Evaluates the WHERE clause against a row of data."""
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
        super().__init__()
        self.clauses = clauses

    def evaluate(self, _object) -> bool:
        """Evaluates the disjunction against a row of data."""
        return any(clause.evaluate(_object) for clause in self.clauses)


class TrueClause(Clause):
    """A clause that always evaluates to True."""

    def evaluate(self, _object) -> bool:
        """Returns True."""
        return True


class FalseClause(Clause):
    """A clause that always evaluates to False."""

    def evaluate(self, _object) -> bool:
        """Returns False."""
        return False
