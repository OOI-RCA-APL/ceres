from typing import Generic, TypeVar

from ceres.errors import Error, ProcedureError


class CeresException(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EngineException(CeresException):
    pass


class ConfigCheckFailedException(EngineException):
    pass


class EngineDatabaseInitFailedException(EngineException):
    pass


class ComponentException(CeresException):
    pass


class ComponentClassInvalidException(CeresException):
    pass


class ConnectionException(ComponentException):
    pass


class ConnectionInactiveException(ConnectionException):
    pass


class ConnectionLostException(ConnectionException):
    pass


class ParseException(CeresException):
    pass


class ProcedureException(CeresException):
    error: ProcedureError

    def __init__(self, error: ProcedureError) -> None:
        super().__init__("error occurred while running procedure")
        self.error = error


class DatabaseException(CeresException):
    pass


class DatabaseDumpException(EngineException):
    pass


class DatabaseLoadException(EngineException):
    pass


_ErrorT = TypeVar("_ErrorT", bound=Error)


class Failure(Exception, Generic[_ErrorT]):
    def __init__(self, error: _ErrorT) -> None:
        self.error = error
        self.message = str(error.type)
