from __future__ import annotations


class CeresException(Exception):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class ComponentException(CeresException):
    pass


class ComponentNotSetupException(CeresException):
    pass


class ConnectionException(ComponentException):
    pass


class ConnectionInactiveException(ConnectionException):
    pass


class ConnectionLostException(ConnectionException):
    pass


class ConnectionDecodeException(ConnectionException):
    pass
