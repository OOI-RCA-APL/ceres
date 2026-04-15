import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Final, Literal, Self, override

from pydantic_core import CoreSchema, SchemaSerializer
from pydantic_core.core_schema import no_info_after_validator_function, to_string_ser_schema

from ceres.__internal__.utilities.caching import LRUCache
from ceres.__internal__.utilities.classes import class_property
from ceres.__internal__.utilities.collections import seq
from ceres.data.types import _NAME_PATTERN

if TYPE_CHECKING:
    from pydantic import GetCoreSchemaHandler
    from sqlalchemy.sql import ColumnElement, SQLColumnExpression

_NAME = _NAME_PATTERN[1:-1]
_MODIFIER = r":(all|children|descendants)"
_SEGMENT = rf"\~({_MODIFIER})?|@?[a-z-A-Z_\-.]+({_MODIFIER})?|@({_MODIFIER})?|{_MODIFIER}"

__all__ = [
    "AddressSelector",
    "DynamicAddress",
    "Address",
]


class AddressSelector:
    __slots__ = ("_text",)

    _cache: LRUCache[str, Self] = LRUCache(256)

    REGEX: Final = re.compile(rf"^{_SEGMENT}(\|{_SEGMENT})*$")

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, *args: Any) -> Self:
        return self

    @override
    def __reduce__(self) -> tuple[type[Self], tuple[str]]:
        return type(self), (self._text,)

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        schema = no_info_after_validator_function(
            cls,
            handler(Any),
            serialization=to_string_ser_schema(when_used="unless-none"),
        )

        cls.__pydantic_serializer__ = SchemaSerializer(schema)
        return schema

    @property
    def text(self) -> str:
        return self._text

    @property
    def segments(self) -> Sequence[AddressSelector]:
        return [AddressSelector(segment) for segment in self._text.split("|")]

    def __init__(self, value: str | AddressSelector | Sequence[str | AddressSelector], /) -> None:
        value = seq(value)

        segments: list[str] = []
        for segment in value:
            if isinstance(segment, str):
                pass
            elif isinstance(segment, AddressSelector):
                segment = segment._text
            else:
                raise ValueError(
                    f"{value!r} must be an instance of {str}, {Sequence[str]} or {AddressSelector}"
                )

            segments.append(segment)

        value = "|".join(segments)

        if not self.REGEX.match(value):
            raise ValueError(f"{value!r} must match regex {self.REGEX.pattern}")

        assert isinstance(value, str)
        self._text: Final[str] = value

    def __new__(cls, value: str | AddressSelector | Sequence[str | AddressSelector], /) -> Self:
        if isinstance(value, cls):
            return value

        if isinstance(value, str):
            cached = cls._cache.get(value)
        elif isinstance(value, AddressSelector):
            cached = cls._cache.get(value._text)
        else:
            cached = None

        if cached is not None:
            return cached

        instance = super().__new__(cls)
        cls.__init__(instance, value)
        cls._cache[instance._text] = instance
        return instance

    @override
    def __str__(self) -> str:
        return self._text

    @override
    def __hash__(self) -> int:
        return hash(self._text)

    @override
    def __eq__(self, other: Any) -> bool:
        return isinstance(other, AddressSelector) and self._text == other._text

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, AddressSelector):
            return NotImplemented

        return self._text < other._text

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({repr(self._text)})"

    def __or__(self, other: AddressSelector) -> AddressSelector:
        return AddressSelector(f"{self}|{other}")

    def _get_normalized_segments(self) -> Sequence[AddressSelector]:
        segments: list[AddressSelector] = []
        for segment in self._text.split("|"):
            if segment == "all":
                segment = ":all"

            segments.append(AddressSelector(segment))

        return segments

    def as_absolute(self, root: Address) -> AddressSelector:
        segments: list[str] = []

        if root.is_engine:
            root = Address.ROOT

        for segment in self._get_normalized_segments():
            if segment._text.startswith(":"):
                segments.append(root._text + segment._text)
            elif segment._text.startswith("~") or segment._text.startswith("@"):
                segments.append(segment._text)
            else:
                if root._text == "~" or root._text == "@":
                    segments.append(root._text + segment._text)
                else:
                    segments.append(root._text + "." + segment._text)

        return AddressSelector(segments)

    def matches(self, address: Address, root: Address) -> bool:
        address = Address(address)
        self = self.as_absolute(root)

        for segment in self._get_normalized_segments():
            if ":" not in segment._text:
                if address == segment:
                    return True

                continue

            base, modifier = segment._text.split(":")

            if base == "~":
                if modifier == "all":
                    return True
                elif modifier == "descendants":
                    if address._text != "~":
                        return True
                elif modifier == "children":
                    if address._text == "@":
                        return True

                continue

            if base == "@":
                if modifier == "all":
                    if address._text != "~":
                        return True
                elif modifier == "descendants":
                    if address._text != "~" and address._text != "@":
                        return True
                elif modifier == "children":
                    return address._text.startswith("@") and len(address._text) > 1

                continue

            if modifier == "all":
                if address._text == base or address._text.startswith(base + "."):
                    return True
            elif modifier == "descendants":
                if address._text.startswith(f"{base}."):
                    return True
            elif modifier == "children":
                if (
                    address._text.startswith(f"{base}.")
                    and address._text[len(base) + 2 :].count(".") == 0
                ):
                    return True

        return False

    def matches_expression(
        self,
        address: SQLColumnExpression[Address],
        root: Address,
    ) -> ColumnElement[bool]:
        from sqlalchemy.sql import expression, or_

        self = self.as_absolute(root)

        conditions: list[ColumnElement[bool]] = []

        for segment in self._get_normalized_segments():
            if ":" not in segment._text:
                conditions.append(address == segment)
                continue

            base, modifier = segment._text.split(":")

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
    REGEX: Final = re.compile(rf"^~|@|@?{_NAME}(\.{_NAME})*$")  # type: ignore

    _cache: LRUCache[str, Self] = LRUCache(256)

    def __init__(self, value: str | AddressSelector, /) -> None:
        super().__init__(value)

    def __new__(cls, value: str | AddressSelector, /) -> Self:
        if not isinstance(value, str | AddressSelector):
            raise ValueError(f"{value!r} must be an instance of {str} or {AddressSelector}")

        if isinstance(value, str):
            if value == "all":
                raise ValueError(f"{value!r} cannot be used as an address")

        return super().__new__(cls, value)

    @property
    def name(self) -> str | None:
        self = self.as_relative()
        if self is None:
            return None
        if "." not in self._text:
            return str(self)

        return self._text[self._text.rindex(".") + 1 :] or None

    @property
    def container(self) -> Self:
        parent = self.parent
        if parent is None:
            return type(self)("~")

        return parent

    @property
    def parent(self) -> Self | None:
        if self.is_root:
            return None

        if "." in self._text:
            return type(self)(self._text[: self._text.rindex(".")]) or None

        if self._text.startswith("@"):
            return type(self)("@")

        return None

    @property
    def depth(self) -> int:
        self = self.as_relative()
        if self is None:
            return 0

        return self._text.count(".") + 1

    @property
    def path(self) -> Sequence[Self]:
        path: list[Self] = []
        current: Self | None = self

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
    def names(self) -> Sequence[str]:
        self = self.as_relative()
        if self is None:
            return []
        return [name for name in self._text.split(".") if name]

    @property
    def is_engine(self) -> bool:
        return self._text == "~"

    @property
    def is_root(self) -> bool:
        return self._text == "@"

    @property
    def is_absolute(self) -> bool:
        return self.is_engine or self._text.startswith("@")

    @property
    def is_relative(self) -> bool:
        return not self.is_absolute

    def __truediv__(self, other: str | DynamicAddress) -> Self:
        other = DynamicAddress(other)
        if self.is_engine:
            return self

        return type(self)(f"{self._text}{'.' if not self.is_root else ''}{other._text.strip('.')}")

    @override
    def as_absolute(self, root: Address) -> Address:
        root = Address(root)
        if self.is_absolute:
            return Address(self)

        return root / self

    def as_relative(self) -> DynamicAddress | None:
        if self.is_engine:
            return None

        stripped = self._text.lstrip("@")
        if not stripped:
            return None

        return DynamicAddress(stripped)

    @property
    def base(self) -> str | None:
        if self._text == "all":
            return None
        if ":" not in self._text:
            return str(self)

        return self._text[: self._text.rindex(":")] or None

    def modify(self, modifier: Literal["all", "descendants", "children"]) -> AddressSelector:
        return AddressSelector(f"{self.base or ''}:{modifier}")

    def all(self) -> AddressSelector:
        return self.modify("all")

    def descendants(self) -> AddressSelector:
        return self.modify("descendants")

    def children(self) -> AddressSelector:
        return self.modify("children")


class Address(DynamicAddress):
    REGEX: Final = re.compile(rf"^~|@({_NAME}(\.{_NAME})*)*$")  # type: ignore

    @class_property
    @classmethod
    def ENGINE(cls) -> Address:
        return _ENGINE

    @class_property
    @classmethod
    def ROOT(cls) -> Address:
        return _ROOT

    _cache: LRUCache[str, Self] = LRUCache(256)

    def __init__(self, value: str | AddressSelector, /) -> None:
        super().__init__(value)

    def __new__(cls, obj: str | AddressSelector, /) -> Self:
        return super().__new__(cls, obj)

    @classmethod
    def engine(cls) -> Address:
        return _ENGINE

    @classmethod
    def root(cls) -> Address:
        return _ROOT

    def contains(self, other: Address) -> bool:
        if self.is_engine:
            return True
        return other == self or (
            (not other.is_engine) and (other._text.startswith(f"{self._text}.") or self.is_root)
        )


_ENGINE = Address("~")
_ROOT = Address("@")
