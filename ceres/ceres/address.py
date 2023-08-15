import re
from functools import lru_cache
from typing import Any, Sequence

from typing_extensions import Self, override

from ceres.data import Name, NameType, StrPattern

_NAME = NameType.regex.pattern[1:-1]
_MODIFIER = r":(all|children|descendants|ancestors)+"
_SEGMENT = rf"~|@?[a-z-A-Z_\-.]+({_MODIFIER})?|@|{_MODIFIER}"


class AddressSelector(str):
    regex: StrPattern = re.compile(rf"^{_SEGMENT}(\|{_SEGMENT})*$")

    @classmethod
    def __get_validators__(cls) -> Any:
        yield cls.validate

    @property
    def segments(self) -> Sequence["AddressSelector"]:
        return [AddressSelector(segment) for segment in self.split("|")]

    def __new__(cls, obj: str | Sequence[str], /) -> Self:
        if isinstance(obj, cls):
            return obj

        return str.__new__(cls, cls.validate(obj))

    @classmethod
    def validate(cls, value: Any) -> Self:
        if isinstance(value, cls):
            return value

        if not isinstance(value, str):
            if not (isinstance(value, Sequence) and all(isinstance(item, str) for item in value)):
                raise TypeError(f"{value!r} must be a string or sequence of strings")

            value = "|".join(value)

        if cls.regex.match(value) is None:
            raise ValueError(f"{value!r} must match regex {cls.regex.pattern}")

        return str.__new__(cls, value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({repr(str(self))})"

    def matches(self, address: "DynamicAddress", root: "Address | None" = None) -> bool:
        resolved = address.relative_to(root) if root is not None else address
        if resolved is None:
            return False

        return self.compile().match(resolved) is not None

    def __or__(self, other: "AddressSelector") -> "AddressSelector":
        return AddressSelector(f"{self}|{other}")

    def compile(self) -> StrPattern:
        return _compile_selector(self)


@lru_cache(maxsize=500)
def _compile_selector(pattern: "AddressSelector") -> StrPattern:
    # TODO: Handle bare :all correctly.
    segments = []

    for segment in pattern.split("|"):
        if segment == "~":
            segments.append("~")
            continue

        segment = segment.strip()

        # TODO: This shouldn't be happening.
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
            address = DynamicAddress(segment[: -len(":ancestors")])
            segment = ("(" + "|".join(address.ancestors) + ")").replace(".", r"\.")

        segments.append(segment)

    return re.compile("^" + "|".join(segments) + "$")


class DynamicAddress(AddressSelector):
    regex = re.compile(rf"^~|@|@?{_NAME}(\.{_NAME})*$")

    def __new__(cls, obj: str, /) -> Self:
        if isinstance(obj, cls):
            return obj

        return str.__new__(cls, cls.validate(obj))

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
        if self.is_root:
            return None

        if "." in self:
            return type(self)(self[: self.rindex(".")]) or None

        if self.startswith("@"):
            return type(self)("@")

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
    def is_server(self) -> bool:
        return self == "~"

    @property
    def is_root(self) -> bool:
        return self == "@"

    @property
    def is_component(self) -> bool:
        return not self.is_server

    @property
    def is_absolute(self) -> bool:
        return self.is_server or self.startswith("@")

    @property
    def is_relative(self) -> bool:
        return not self.is_absolute

    def __truediv__(self, other: str) -> Self:
        if self.is_server:
            return self

        return type(self)(f"{self}{'.' if not self.is_root else ''}{other.strip('.')}")

    def relative_to(self, root: "Address") -> "DynamicAddress | None":
        if self.is_absolute:
            return self

        if self.startswith(root):
            return DynamicAddress(self[len(root) :])

        return None

    def as_relative(self) -> "DynamicAddress | None":
        if self.is_server:
            return None

        stripped = self.lstrip("@")
        if not stripped:
            return None

        return DynamicAddress(stripped)

    def as_absolute(self) -> "Address":
        return Address(self)


class Address(DynamicAddress):
    regex = re.compile(rf"^~|@({_NAME}(\.{_NAME})*)*$")

    @classmethod
    def server(cls) -> "Address":
        return _SERVER

    @classmethod
    def root(cls) -> "Address":
        return _ROOT

    @override
    @classmethod
    def validate(cls, value: Any) -> Self:
        if isinstance(value, cls):
            return value

        if cls.regex.match(value) is None:
            value = "@" + value
        if cls.regex.match(value) is None:
            raise ValueError(f"{value!r} must match regex {cls.regex.pattern}")

        return str.__new__(cls, value)

    def contains(self, other: "Address") -> bool:
        if self.is_server:
            return True
        return other == self or (
            (not other.is_server) and (other.startswith(f"{self}.") or self.is_root)
        )


_SERVER = Address("~")
_ROOT = Address("@")
