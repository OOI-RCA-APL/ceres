import re
from functools import lru_cache
from typing import Any, Sequence

from typing_extensions import Self, override

from ceres.data import Name, NameType, StrPattern


class AddressLike(str):
    regex: StrPattern

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

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({repr(str(self))})"


@lru_cache(maxsize=100)
def _compile(pattern: "AddressPattern") -> StrPattern:
    return re.compile("^" + pattern.replace(".", r"\.").replace("*", r".*") + "$")


class AddressPattern(AddressLike):
    regex = re.compile(rf"^({NameType.get_pattern()}|[.*|])*$")

    @classmethod
    def __get_validators__(cls) -> Any:
        yield cls.validate

    def matches(self, address: "Address", root: "Address | None" = None) -> bool:
        resolved = address.relative_to(root) if root is not None else address
        if resolved is None:
            return False

        return self.compile().match(resolved) is not None

    def __or__(self, other: "AddressPattern") -> "AddressPattern":
        return AddressPattern(f"{self}|{other}")

    def compile(self) -> StrPattern:
        return _compile(self)

    @property
    def simple(self) -> bool:
        return Address.regex.match(self) is not None


class Address(AddressPattern):
    regex = re.compile(rf"^({NameType.get_pattern()}(\.{NameType.get_pattern()})*)?$")

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
    def name(self) -> Name | None:
        if not self or "." not in self:
            return None

        return self[self.rindex(".") + 1 :] or None

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
    def path(self) -> Sequence[Self]:
        path: list[Self] = []
        current = self

        while current is not None:
            if current:
                path.append(current)
            current = current.parent

        return list(reversed(path))

    @property
    def names(self) -> Sequence[Name]:
        return [name for name in self.split(".") if name]

    @property
    @override
    def simple(self) -> bool:
        return True

    def __truediv__(self, other: str) -> Self:
        return Address(f"{self}{'.' if self else ''}{other.strip('.')}")

    def contains(self, other: Self) -> bool:
        return not self or self == other or other.startswith(f"{self}.")

    def relative_to(self, root: Self) -> Self | None:
        if self.startswith(root):
            return self.__class__(self[len(root) :])

        return None
