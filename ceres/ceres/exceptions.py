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
