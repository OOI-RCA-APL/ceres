class CeresException(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class StartupException(CeresException):
    pass


class StartupConfigCheckFailedException(StartupException):
    pass


class StartupDatabaseInitFailedException(StartupException):
    pass


class ComponentException(CeresException):
    pass


class ComponentClassInvalidException(CeresException):
    pass


class ComponentNotLoadedException(CeresException):
    pass


class ConnectionException(ComponentException):
    pass


class ConnectionInactiveException(ConnectionException):
    pass


class ConnectionLostException(ConnectionException):
    pass


class ConnectionDecodeException(ConnectionException):
    pass


class ParseException(CeresException):
    pass
