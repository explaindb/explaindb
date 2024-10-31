from dataclasses import dataclass


@dataclass(frozen=True)
class IndexProperties:
    """A class representing an index on the store."""

    attribute: str
    operator: str
    # index: object | None = None


@dataclass(frozen=True)
class Index:
    """A class representing an index on the store."""

    # TODO: implement the index API here
    pass
