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
_PATH = rf"@?{_NAME}(\.{_NAME})*"
_SEGMENT = rf"\~(:(all|descendants))?|{_PATH}({_MODIFIER})?|@{_MODIFIER}|{_MODIFIER}"

__all__ = [
    "AddressSelector",
    "DynamicAddress",
    "Address",
]


class AddressSelector:
    """A pattern that selects one or more component addresses.

    Selectors support a small DSL for matching addresses by exact value or by structural
    relationship. A selector consists of one or more pipe-separated segments where each segment
    is either a literal address (e.g. `@sensor`), the special base `~` (engine), or a base
    followed by a modifier. The base `@` selects every component and requires a modifier, it
    is not a matchable address on its own:

    - `:all` matches the base itself plus every descendant.
    - `:children` matches only the immediate children of the base.
    - `:descendants` matches every descendant of the base, but not the base itself.

    Instances are interned by their textual form so equal selectors share memory.
    """

    __slots__ = ("_text",)

    _cache: LRUCache[str, Self] = LRUCache(256)

    REGEX: Final = re.compile(rf"^(?:{_SEGMENT})(\|(?:{_SEGMENT}))*$")
    """Regex used to validate the textual form of a selector."""

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
        """The selector's textual form."""
        return self._text

    @property
    def segments(self) -> Sequence[AddressSelector]:
        """The pipe-separated segments of the selector, each as its own `AddressSelector`."""
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

    def as_absolute(self, root: Address | None) -> AddressSelector:
        """Resolve relative selector segments against `root` to produce an absolute selector.

        Segments that already begin with `~`, `@`, or `:` are left untouched. Everything else is
        treated as relative to `root` and gets prefixed accordingly.

        Args:
            root: Address that relative segments resolve against. `None` or the engine resolve
                against every component.

        Returns:
            An equivalent selector whose segments are all absolute.
        """
        segments: list[str] = []
        base = "@" if root is None or root.is_engine else root._text

        for segment in self._get_normalized_segments():
            if segment._text.startswith(":"):
                segments.append(base + segment._text)
            elif segment._text.startswith("~") or segment._text.startswith("@"):
                segments.append(segment._text)
            else:
                if base == "@":
                    segments.append(base + segment._text)
                else:
                    segments.append(base + "." + segment._text)

        return AddressSelector(segments)

    def matches(self, address: Address, root: Address | None) -> bool:
        """Check whether `address` is selected by this selector when resolved against `root`.

        Args:
            address: Component address to test.
            root: Reference address used to resolve any relative segments. `None` or the engine
                resolve against every component.

        Returns:
            `True` if any segment matches `address`, `False` otherwise.
        """
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

                continue

            if base == "@":
                # With no root component, `@` selects every component, so `descendants` and `all`
                # both match anything that is not the engine.
                if modifier in ("all", "descendants"):
                    if address._text != "~":
                        return True
                elif modifier == "children":
                    if address._text.startswith("@") and "." not in address._text:
                        return True

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
        root: Address | None,
    ) -> ColumnElement[bool]:
        """Build a SQL boolean expression equivalent to `matches()` for use in queries.

        Args:
            address: SQL column expression of the address being tested.
            root: Reference address used to resolve any relative segments. `None` or the engine
                resolve against every component.

        Returns:
            A SQL `OR` of conditions, one per selector segment.
        """
        from sqlalchemy.sql import expression, or_

        from ceres.__internal__.filter import _SelectorMatch

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

                continue

            if base == "@":
                # With no root component, `@` selects every component, so `descendants` and `all`
                # both match anything that is not the engine.
                if modifier in ("all", "descendants"):
                    conditions.append(address != "~")
                elif modifier == "children":
                    conditions.append(address.like("@%") & address.not_like("%.%"))

                continue

            conditions.append(_SelectorMatch(address, base, modifier))

        return or_(*conditions)


class DynamicAddress(AddressSelector):
    """An address that may be relative or absolute, with helpers for path manipulation.

    Unlike `AddressSelector`, a `DynamicAddress` always refers to a single concrete location rather
    than a pattern. It exposes properties for navigating the address tree (`parent`, `ancestors`,
    `path`, etc.) and operators for joining segments (`/`).
    """

    REGEX: Final = re.compile(rf"^(?:~|@?{_NAME}(\.{_NAME})*)$")  # type: ignore

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
        """The trailing name segment of the address, or `None` for `~`."""
        self = self.as_relative()
        if self is None:
            return None
        if "." not in self._text:
            return str(self)

        return self._text[self._text.rindex(".") + 1 :] or None

    @property
    def container(self) -> Self:
        """The parent address, or `~` (engine) if this address has no parent."""
        parent = self.parent
        if parent is None:
            return type(self)("~")

        return parent

    @property
    def parent(self) -> Self | None:
        """The parent address, or `None` if this address has no parent."""
        if "." in self._text:
            return type(self)(self._text[: self._text.rindex(".")]) or None

        return None

    @property
    def depth(self) -> int:
        """Number of name segments in the address. `~` has depth `0`."""
        self = self.as_relative()
        if self is None:
            return 0

        return self._text.count(".") + 1

    @property
    def path(self) -> Sequence[Self]:
        """The address chain from the top-level ancestor to self, inclusive."""
        path: list[Self] = []
        current: Self | None = self

        while current is not None:
            path.append(current)
            current = current.parent

        return list(reversed(path))

    @property
    def ancestors(self) -> Sequence[Self]:
        """All ancestor addresses, from immediate parent up to the top-level ancestor."""
        ancestors: list[Self] = []
        current = self.parent

        while current is not None:
            ancestors.append(current)
            current = current.parent

        return ancestors

    @property
    def names(self) -> Sequence[str]:
        """The address segments as bare names, without the leading `@`."""
        self = self.as_relative()
        if self is None:
            return []
        return [name for name in self._text.split(".") if name]

    @property
    def is_engine(self) -> bool:
        """`True` if this address refers to the engine itself (`~`)."""
        return self._text == "~"

    @property
    def is_absolute(self) -> bool:
        """`True` if this address starts at the engine or a component rather than being relative."""
        return self.is_engine or self._text.startswith("@")

    @property
    def is_relative(self) -> bool:
        """`True` if this address is not absolute and must be resolved against a base."""
        return not self.is_absolute

    def __truediv__(self, other: str | DynamicAddress) -> Self:
        other = DynamicAddress(other)
        if self.is_engine:
            return self

        return type(self)(f"{self._text}.{other._text.strip('.')}")

    @override
    def as_absolute(self, root: Address | None) -> Address:
        """Resolve this address against `root` and return the result as an absolute `Address`.

        If this address is already absolute, return it directly. Otherwise, join it onto `root`.

        Args:
            root: Base address to resolve against when this address is relative. `None` or the
                engine resolve against every component.

        Returns:
            An absolute `Address`.
        """
        if self.is_absolute:
            return Address(self)

        if root is None or root.is_engine:
            return Address(f"@{self._text}")

        return root / self

    def as_relative(self) -> DynamicAddress | None:
        """Strip the absolute prefix and return the relative form, or `None` if not possible."""
        if self.is_engine:
            return None

        return DynamicAddress(self._text.lstrip("@"))

    @property
    def base(self) -> str | None:
        """The address text with any selector modifier (`:all`, etc.) stripped."""
        if self._text == "all":
            return None
        if ":" not in self._text:
            return str(self)

        return self._text[: self._text.rindex(":")] or None

    def modify(self, modifier: Literal["all", "descendants", "children"]) -> AddressSelector:
        """Return a selector that matches `self` modified by `modifier`."""
        return AddressSelector(f"{self.base or ''}:{modifier}")

    def all(self) -> AddressSelector:
        """Return a selector matching this address and every descendant."""
        return self.modify("all")

    def descendants(self) -> AddressSelector:
        """Return a selector matching every descendant of this address."""
        return self.modify("descendants")

    def children(self) -> AddressSelector:
        """Return a selector matching only the immediate children of this address."""
        return self.modify("children")


class Address(DynamicAddress):
    """An absolute address pointing to a single component or the engine.

    The reserved value is `~` (the engine). Every component address is `@` followed by
    dot-separated names, e.g. `@parent.child.grandchild`.
    """

    REGEX: Final = re.compile(rf"^(?:~|@{_NAME}(\.{_NAME})*)$")  # type: ignore

    @class_property
    @classmethod
    def ENGINE(cls) -> Address:
        """The engine address (`~`)."""
        return _ENGINE

    _cache: LRUCache[str, Self] = LRUCache(256)

    def __init__(self, value: str | AddressSelector, /) -> None:
        super().__init__(value)

    def __new__(cls, obj: str | AddressSelector, /) -> Self:
        return super().__new__(cls, obj)

    @classmethod
    def engine(cls) -> Address:
        """Return the engine address (`~`)."""
        return _ENGINE

    def contains(self, other: Address) -> bool:
        """Return `True` if `other` is `self` or a descendant of `self`.

        The engine address contains every other address.
        """
        if self.is_engine:
            return True

        return other == self or (not other.is_engine and other._text.startswith(f"{self._text}."))


_ENGINE = Address("~")
