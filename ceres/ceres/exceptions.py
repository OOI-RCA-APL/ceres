from __future__ import annotations


class CeresException(Exception):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class ReloadException(CeresException):
    pass


class ReloadAlreadyActiveException(ReloadException):
    pass


class ConfigException(CeresException):
    pass


# class ComponentLoadException(CeresException):
#     pass


class ConnectionException(CeresException):
    pass


class ConnectionInactiveException(ConnectionException):
    pass


class ConnectionLostException(ConnectionException):
    pass


class ConnectionDecodeException(ConnectionException):
    pass
