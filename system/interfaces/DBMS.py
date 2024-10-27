from abc import ABC

from system.interfaces.query_processing.query_processing import QueryInterface
from system.interfaces.stores import ACIDStore


class DBMS(QueryInterface, ACIDStore, ABC):
    """Database Management System interface"""

    pass
