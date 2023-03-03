from ceres.errors import ProcedureError


class CeresException(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EngineException(CeresException):
    pass


class EngineConfigCheckFailedException(EngineException):
    pass


class EngineDatabaseInitException(EngineException):
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
