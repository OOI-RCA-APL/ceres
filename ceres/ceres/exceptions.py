class CeresException(Exception):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class ConfigException(CeresException):
    pass


class ComponentLoadException(CeresException):
    pass


class ConnectionException(CeresException):
    pass


class ConnectionInactiveException(ConnectionException):
    pass


class DisconnectException(ConnectionException):
    pass
