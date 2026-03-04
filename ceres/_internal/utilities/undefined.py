from enum import Enum
from typing import override

_value = object()


class UndefinedType(Enum):
    Instance = _value

    @override
    def __repr__(self) -> str:
        return self.__str__()

    @override
    def __str__(self) -> str:
        return "Undefined"

    def __bool__(self) -> bool:
        return False


Undefined = UndefinedType.Instance
