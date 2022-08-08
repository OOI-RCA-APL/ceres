class CeresException(Exception):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class ConfigException(CeresException):
    pass


class ObjectLoadException(CeresException):
    pass
