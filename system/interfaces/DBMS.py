from abc import ABC

from system.interfaces.query_processing import QueryInterface


class DBMS(QueryInterface, ABC):
    """Database Management System interface"""

    pass
