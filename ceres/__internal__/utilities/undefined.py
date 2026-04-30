from enum import Enum
from typing import override

_value = object()


class UndefinedType(Enum):
    """Sentinel enum used to represent an explicitly undefined or missing value.

    Use ``Undefined`` (the sole member) instead of ``None`` when ``None`` is a valid value.
    """

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
