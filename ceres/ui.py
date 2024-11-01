from __future__ import annotations

from abc import ABC
from decimal import Decimal
from enum import Enum
from textwrap import dedent
from types import MethodType
from typing import Annotated, Any, Callable, Literal, Sequence, TypeAlias, TypedDict, Unpack

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)

from ceres._internal.lazy import lazy_imports
from ceres.address import Address
from ceres.data import Color, DataObject, ImmutableDataObject, Name, StrEnum

with lazy_imports(__name__):
    from ceres._internal import util


class ElementType(StrEnum):
    BUTTON = "button"
    ROW = "row"
    COLUMN = "column"
    CAROUSEL = "carousel"
    TEXT = "text"
    HTML = "html"
    STATE = "state"
    GAUGE = "gauge"
    CHART = "chart"
    RENDER = "render"
    DISPLAY = "display"


class Justify(StrEnum):
    START = "start"
    CENTER = "center"
    END = "end"
    SPACE_BETWEEN = "space-between"
    SPACE_EVENLY = "space-evenly"


class Align(StrEnum):
    START = "start"
    CENTER = "center"
    END = "end"


class Sizing(StrEnum):
    SHRINK = "shrink"
    GROW = "grow"


_element_classes: list[type[DataObject]] = []


def __update_forward_refs() -> None:
    for current in _element_classes:
        current.model_rebuild()


class _BaseElementArgs(TypedDict, total=False):
    css_style: str | dict[str, str] | None
    css_class: str | list[str] | None


class _BaseElement(DataObject, ABC):
    type: ElementType
    css_style: str | dict[str, str] | None = None
    css_class: str | list[str] | None = None

    def __init_subclass__(cls, **kwargs: Unpack[ConfigDict]):
        super().__init_subclass__(**kwargs)
        _element_classes.append(cls)
        return cls


class Button(_BaseElement):
    type: Literal[ElementType.BUTTON] = ElementType.BUTTON
    title: str
    address: Address
    action: Name
    color: Color | None = None

    def __init__(
        self,
        *,
        title: str,
        address: Address | None = None,
        action: Name | Callable[..., Any],
        color: Color | None = None,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        from ceres.component import Component

        if address is None:
            if not isinstance(action, MethodType):
                raise ValueError("address must be specified if action is not a bound method")
            elif not isinstance(action.__self__, Component):
                raise ValueError("method passed as action must be bound to a component")

            address = action.__self__.system.address

        if not isinstance(action, str):
            from ceres.component import ActionBinding, get_component_method_binding

            binding = get_component_method_binding(action, ActionBinding)
            if not binding:
                raise ValueError(f"function {util.strify(action)} has no action binding")

            action = binding.name

        super().__init__(
            **{
                "title": title,
                "address": address,
                "action": action,
                "color": color,
                **kwargs,  # type: ignore
            }
        )


class Row(_BaseElement):
    type: Literal[ElementType.ROW] = ElementType.ROW
    sizing: Sizing = Sizing.GROW
    justify: Justify = Justify.START
    align: Align = Align.START
    children: list[Element]

    def __init__(
        self,
        children: Sequence[Element],
        *,
        sizing: Sizing = Sizing.GROW,
        justify: Justify = Justify.START,
        align: Align = Align.START,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        super().__init__(
            **{
                "children": children,
                "sizing": sizing,
                "justify": justify,
                "align": align,
                **kwargs,  # type: ignore
            }
        )


class Column(_BaseElement):
    type: Literal[ElementType.COLUMN] = ElementType.COLUMN
    sizing: Sizing = Sizing.GROW
    justify: Justify = Justify.START
    align: Align = Align.START
    children: list[Element]

    def __init__(
        self,
        children: Sequence[Element],
        *,
        sizing: Sizing = Sizing.GROW,
        justify: Justify = Justify.START,
        align: Align = Align.START,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        super().__init__(
            **{
                "children": children,
                "sizing": sizing,
                "justify": justify,
                "align": align,
                **kwargs,  # type: ignore
            }
        )


class Carousel(_BaseElement):
    type: Literal[ElementType.CAROUSEL] = ElementType.CAROUSEL
    height: int | str | None = None
    children: list[Element]

    def __init__(
        self,
        children: Sequence[Element],
        *,
        height: int | str | None = None,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        super().__init__(
            **{
                "children": children,
                "height": height,
                **kwargs,  # type: ignore
            }
        )


class TextVariant(StrEnum):
    TITLE_1 = "title1"
    TITLE_2 = "title2"
    TITLE_3 = "title3"
    BODY_1 = "body1"
    BODY_2 = "body2"
    TH = "th"
    DESCRIPTION = "description"
    VALUE = "value"


class Text(_BaseElement):
    type: Literal[ElementType.TEXT] = ElementType.TEXT
    variant: TextVariant = TextVariant.BODY_2
    value: str
    color: Color | None = None

    def __init__(
        self,
        value: Any,
        variant: TextVariant = TextVariant.BODY_2,
        *,
        color: Color | str | None = None,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        super().__init__(
            **{
                "value": value,
                "variant": variant,
                "color": color,
                **kwargs,  # type: ignore
            }
        )


class HTML(_BaseElement):
    type: Literal[ElementType.HTML] = ElementType.HTML
    value: str

    def __init__(self, value: str, **kwargs: Any) -> None:
        super().__init__(
            **{
                "value": value,
                **kwargs,  # type: ignore
            }
        )

    @field_validator("value")
    def _validate_value(cls, value: str) -> str:
        from xml.etree import ElementTree

        try:
            ElementTree.fromstring(value)
        except SyntaxError:
            raise ValueError("must be valid HTML/XML")

        return dedent(value).strip()


AtomicValue: TypeAlias = StrictBool | StrictInt | StrictFloat | Decimal | StrictStr


class State(_BaseElement):
    class Option(DataObject):
        value: AtomicValue
        label: str
        color: Color
        icon: str | None = None
        description: str | None = None

        def __init__(
            self,
            value: AtomicValue,
            *,
            label: str,
            color: Color | str,
            icon: str | None = None,
            description: str | None = None,
            **kwargs: Any,
        ) -> None:
            super().__init__(
                **{
                    "value": value,
                    "label": label,
                    "color": color,
                    "icon": icon,
                    "description": description,
                    **kwargs,
                }
            )

    type: Literal[ElementType.STATE] = ElementType.STATE
    value: AtomicValue
    options: list[Option]

    def __init__(
        self,
        value: AtomicValue,
        options: Sequence[Option],
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        super().__init__(
            **{
                "value": value,
                "options": options,
                **kwargs,  # type: ignore
            }
        )


class Gauge(_BaseElement):
    class ColorStop(ImmutableDataObject):
        value: float
        color: Color

        def __init__(self, value: float, color: Color | str, **kwargs: Any) -> None:
            super().__init__(**{"value": value, "color": color, **kwargs})

    type: Literal[ElementType.GAUGE] = ElementType.GAUGE
    value: float
    min: float
    max: float
    unit: str | None = None
    color: list[ColorStop] | Color | None = None

    def __init__(
        self,
        value: float,
        min: float,
        max: float,
        *,
        unit: str | None = None,
        color: list[ColorStop] | Color | str | None = None,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        super().__init__(
            **{
                "value": value,
                "unit": unit,
                "min": min,
                "max": max,
                "color": color,
                **kwargs,  # type: ignore
            }
        )


class Chart(_BaseElement):
    type: Literal[ElementType.CHART] = ElementType.CHART
    value: dict[str, object]
    height: int | str

    def __init__(
        self,
        value: dict[str, object],
        *,
        height: int | str,
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        super().__init__(
            **{
                "value": value,
                "height": height,
                **kwargs,  # type: ignore
            }
        )


class PaletteColor(Color, Enum):
    PRIMARY = Color("#0089ab")
    SECONDARY = Color("#26a69a")
    ACCENT = Color("#9c27b0")
    POSITIVE = Color("#21ba45")
    NEGATIVE = Color("#c10015")
    INFO = Color("#31ccec")
    WARNING = Color("#ff9d00")


class _BaseRenderer(_BaseElement):
    type: Literal[ElementType.RENDER] | Literal[ElementType.DISPLAY] = ElementType.RENDER
    title: str
    address: Address
    query: Name

    def __init__(
        self,
        *,
        address: Address | None = None,
        query: Name | Callable[..., Any],
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        from ceres.component import Component

        if address is None:
            if not isinstance(query, MethodType):
                raise ValueError("address must be specified if query is not a bound method")
            elif not isinstance(query.__self__, Component):
                raise ValueError("method passed as query must be bound to a component")

            address = query.__self__.system.address

        if not isinstance(query, str):
            from ceres.component import QueryBinding, get_component_method_binding

            binding = get_component_method_binding(query, QueryBinding)
            if not binding:
                raise ValueError(f"function {util.strify(query)} has no query binding")

            query = binding.name

        super().__init__(
            **{
                "address": address,
                "query": query,
                **kwargs,  # type: ignore
            }
        )


class Render(_BaseRenderer):
    type: Literal[ElementType.RENDER] = ElementType.RENDER


class Display(_BaseRenderer):
    type: Literal[ElementType.DISPLAY] = ElementType.DISPLAY
    title: str

    def __init__(
        self,
        *,
        title: str,
        address: Address | None = None,
        query: Name | Callable[..., Any],
        **kwargs: Unpack[_BaseElementArgs],
    ) -> None:
        super().__init__(
            **{
                "title": title,
                "address": address,
                "query": query,
                **kwargs,  # type: ignore
            }
        )


Element: TypeAlias = Annotated[  # type: ignore
    Button | Row | Column | Carousel | Text | HTML | State | Gauge | Chart | Render | Display,
    Field(discriminator="type"),
]


__update_forward_refs()
