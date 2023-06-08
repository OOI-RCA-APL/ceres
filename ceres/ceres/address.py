import re
from typing import Any, final

from typing_extensions import Self

from ceres.data import Name, NameType


@final
class Address(str):
    regex = re.compile(rf"^({NameType.get_pattern()}(\.{NameType.get_pattern()})*)?$")

    @classmethod
    def __get_validators__(cls) -> Any:
        yield cls.validate

    def __new__(cls, obj: str, /) -> Self:
        if isinstance(obj, cls):
            return obj

        return str.__new__(cls, cls.validate(obj))

    @classmethod
    def validate(cls, value: str) -> Self:
        if isinstance(value, cls):
            return value

        if cls.regex.match(value) is None:
            raise ValueError(f"{value!r} must match regex {cls.regex.pattern}")

        return str.__new__(cls, value)

    @property
    def unit(self) -> Name | None:
        return self.head

    @property
    def head(self) -> Name | None:
        if not self:
            return None
        if "." not in self:
            return self

        return self[: self.index(".")] or None

    @property
    def tail(self) -> Self | None:
        if not self or "." not in self:
            return None

        return Address(self[self.index(".") + 1 :]) or None

    @property
    def component(self) -> Name | None:
        if not self or "." not in self:
            return None

        return self[self.rindex(".") + 1 :] or None

    @property
    def name(self) -> Name | None:
        return self.component

    @property
    def parent(self) -> Self | None:
        if not self:
            return None
        if "." not in self:
            return Address("")

        return Address(self[: self.rindex(".")]) or None

    @property
    def depth(self) -> int:
        if not self:
            return 0

        return self.count(".") + 1

    @property
    def names(self) -> list[str]:
        return [names for names in self.split(".") if names]

    @property
    def path(self) -> list[Self]:
        path: list[Self] = []
        current = self

        while current is not None:
            path.append(current)
            current = current.parent

        return list(reversed(path))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({repr(str(self))})"

    def __truediv__(self, other: str) -> Self:
        return Address(f"{self}{'.' if self else ''}{other.strip('.')}")

    def contains(self, other: Self) -> bool:
        return not self or self == other or other.startswith(f"{self}.")
