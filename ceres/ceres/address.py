import re
from typing import TYPE_CHECKING, Any, Sequence

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function
from typing_extensions import Self, override

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement, SQLColumnExpression
else:
    SQLColumnExpression = object
    ColumnElement = object

from ceres.data import NAME_TYPE_PATTERN, Name

_NAME = NAME_TYPE_PATTERN[1:-1]
_MODIFIER = r":(all|children|descendants)"
_SEGMENT = rf"\~({_MODIFIER})?|@?[a-z-A-Z_\-.]+({_MODIFIER})?|@|{_MODIFIER}"


class AddressSelector(str):
    regex = re.compile(rf"^{_SEGMENT}(\|{_SEGMENT})*$")

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        return no_info_after_validator_function(cls.validate, handler(str))

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

    def __or__(self, other: "AddressSelector") -> "AddressSelector":
        return AddressSelector(f"{self}|{other}")

    def as_absolute(self, root: "Address") -> "AddressSelector":
        segments: list[str] = []

        if root.is_server:
            root = Address.root()

        for segment in self.segments:
            if segment.startswith(":"):
                segments.append(root + segment)
            elif segment.startswith("~") or segment.startswith("@"):
                segments.append(segment)
            else:
                if segment == "~" or segment == "@":
                    segments.append(root + segment)
                else:
                    segments.append(root + "." + segment)

        return AddressSelector(segments)

    def matches(self, address: "Address", root: "Address") -> bool:
        address = Address(address)
        self = self.as_absolute(root)

        for segment in self.segments:
            if ":" not in segment:
                if address == segment:
                    return True

            base, modifier = segment.split(":")

            if base == "~":
                if modifier == "all":
                    return True
                elif modifier == "descendants":
                    if address != "~":
                        return True
                elif modifier == "children":
                    if address == "@":
                        return True

                continue

            if base == "@":
                if modifier == "all":
                    if address != "~":
                        return True
                elif modifier == "descendants":
                    if address != "~" and address != "@":
                        return True
                elif modifier == "children":
                    return address.startswith("@") and len(address) > 1

                continue

            if modifier == "all":
                if address == base or address.startswith(base + "."):
                    return True
            elif modifier == "descendants":
                if address.startswith(f"{base}."):
                    return True
            elif modifier == "children":
                if address.startswith(f"{base}.") and address[len(base) + 2 :].count(".") == 0:
                    return True

        return False

    def matches_expression(
        self,
        address: "SQLColumnExpression[Address]",
        root: "Address",
    ) -> "ColumnElement[bool]":
        from sqlalchemy.sql import expression, or_

        self = self.as_absolute(root)

        conditions: list[ColumnElement[bool]] = []

        for segment in self.segments:
            if ":" not in segment:
                conditions.append(address == segment)
                continue

            base, modifier = segment.split(":")

            if base == "~":
                if modifier == "all":
                    conditions.append(expression.true())
                elif modifier == "descendants":
                    conditions.append(address != "~")
                elif modifier == "children":
                    conditions.append(address == "@")

                continue

            if base == "@":
                if modifier == "all":
                    conditions.append(address != "~")
                elif modifier == "descendants":
                    conditions.append(address.like("@_%"))
                elif modifier == "children":
                    conditions.append(address.like("@_%") & address.not_like("%.%"))

                continue

            if modifier == "all":
                conditions.append((address == base) | address.startswith(f"{base}."))
            elif modifier == "descendants":
                conditions.append(address.startswith(f"{base}."))
            elif modifier == "children":
                conditions.append(address.startswith(f"{base}.") & address.not_like(f"{base}.%."))

        return or_(*conditions)


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

    def as_absolute(self, root: "Address") -> "Address":
        root = Address(root)
        if self.is_absolute:
            return Address(self)

        return root / self

    def as_relative(self) -> "DynamicAddress | None":
        if self.is_server:
            return None

        stripped = self.lstrip("@")
        if not stripped:
            return None

        return DynamicAddress(stripped)


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
        if not isinstance(value, str):
            raise TypeError(f"{value!r} must be an instance of {str}")

        original = value

        if cls.regex.match(value) is None:
            value = "@" + value
        if cls.regex.match(value) is None:
            raise ValueError(f"{original!r} must match regex {cls.regex.pattern}")

        return str.__new__(cls, value)

    def contains(self, other: "Address") -> bool:
        if self.is_server:
            return True
        return other == self or (
            (not other.is_server) and (other.startswith(f"{self}.") or self.is_root)
        )


_SERVER = Address("~")
_ROOT = Address("@")
