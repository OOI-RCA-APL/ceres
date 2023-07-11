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
        return f"{type(self).__name__}({repr(str(self))})"


@lru_cache(maxsize=500)
def _compile(pattern: "AddressSelector") -> StrPattern:
    segments = []
    for segment in pattern.split("|"):
        segment = segment.strip()

        if not segment.startswith("@"):
            segment = "@" + segment

        segment.replace(".", r"\.")

        if segment.endswith(":all"):
            segment = segment[: -len(":all")]
            if segment == "@":
                segment += r".*"
            else:
                segment += r"($|\..+)"
        elif segment.endswith(":children"):
            segment = segment[: -len(":children")]
            segment += r"[^.]+$" if segment == "@" else r"\.[^.]+$"
        elif segment.endswith(":descendants"):
            segment = segment[: -len(":descendants")]
            segment += r".+" if segment == "@" else r"\..+$"
        elif segment.endswith(":ancestors"):
            address = Address(segment[: -len(":ancestors")])
            segment = ("(" + "|".join(address.ancestors) + ")").replace(".", r"\.")

        segments.append(segment)

    return re.compile("^" + "|".join(segments) + "$")


NAME_PATTERN = NameType.regex.pattern[1:-1]
MODIFIER_PATTERN = r":(all|children|descendants|ancestors)+"
SEGMENT_PATTERN = rf"@|{MODIFIER_PATTERN}|@?[a-z-A-Z_\-.]+({MODIFIER_PATTERN})?"


class AddressSelector(AddressLike):
    regex = re.compile(rf"^{SEGMENT_PATTERN}(\|{SEGMENT_PATTERN})*$")

    @classmethod
    def __get_validators__(cls) -> Any:
        yield cls.validate

    def matches(self, address: "AbsoluteAddress", root: "AbsoluteAddress | None" = None) -> bool:
        resolved = address.relative_to(root) if root is not None else address
        if resolved is None:
            return False

        return self.compile().match(resolved) is not None

    def __or__(self, other: "AddressSelector") -> "AddressSelector":
        return AddressSelector(f"{self}|{other}")

    def compile(self) -> StrPattern:
        return _compile(self)

    @property
    def simple(self) -> bool:
        return Address.regex.match(self) is not None


class Address(AddressSelector):
    regex = re.compile(rf"^@|@?{NAME_PATTERN}(\.{NAME_PATTERN})*$")

    @property
    def name(self) -> Name | None:
        self = self.as_relative()
        if self is None:
            return None
        if "." not in self:
            return str(self)

        return self[self.rindex(".") + 1 :] or None

    @property
    def parent(self) -> Self | None:
        if "." in self:
            return Address(self[: self.rindex(".")]) or None

        if self.is_root:
            return None

        if self.startswith("@"):
            return Address(self[1:])

        return None

    @property
    def depth(self) -> int:
        self = self.as_relative()
        if self is None:
            return 0

        return self.count(".") + 1

    @property
    def path(self) -> Sequence[Self]:
        self = self.as_relative()
        path: list[Self] = []
        current = self

        while current is not None:
            path.append(current)
            current = current.parent

        return list(reversed(path))

    @property
    def ancestors(self) -> Sequence[Self]:
        ancestors: list[Self] = []
        current = self.parent

        while current is not None:
            ancestors.append(current)
            current = current.parent

        return ancestors

    @property
    def names(self) -> Sequence[Name]:
        self = self.as_relative()
        if self is None:
            return []
        return [name for name in self.split(".") if name]

    @property
    @override
    def simple(self) -> bool:
        return True

    @property
    def is_root(self) -> bool:
        return self == "@"

    @property
    def is_absolute(self) -> bool:
        return self.startswith("@")

    @property
    def is_relative(self) -> bool:
        return not self.is_absolute

    def __truediv__(self, other: str) -> Self:
        return type(self)(f"{self}{'.' if not self.is_root else ''}{other.strip('.')}")

    def contains(self, other: "Address") -> bool:
        self = self.as_absolute()
        other = other.as_absolute()

        return self.is_root or self == other or other.startswith(f"{self}.")

    def relative_to(self, root: "AbsoluteAddress") -> "Address | None":
        if self.is_absolute:
            return self

        if self.startswith(root):
            return Address(self[len(root) :])

        return None

    def as_relative(self) -> "Address | None":
        stripped = self.lstrip("@")
        if not stripped:
            return None

        return Address(stripped)

    def as_absolute(self) -> "AbsoluteAddress":
        return AbsoluteAddress(self)


class AbsoluteAddress(Address):
    regex = re.compile(rf"^@({NAME_PATTERN}(\.{NAME_PATTERN})*)*$")

    @override
    @classmethod
    def validate(cls, value: str) -> Self:
        if isinstance(value, cls):
            return value

        if cls.regex.match(value) is None:
            value = "@" + value
        if cls.regex.match(value) is None:
            raise ValueError(f"{value!r} must match regex {cls.regex.pattern}")

        return str.__new__(cls, value)
