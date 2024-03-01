from abc import ABC
from decimal import Decimal
from enum import Enum
from types import MethodType
from typing import Annotated, Any, Callable, Literal, TypeAlias

from pydantic import ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from typing_extensions import Unpack

from ceres.address import Address
from ceres.data import Color, DataObject, ImmutableDataObject, Name
from ceres.internal.utilities import StrEnum, strify


class ElementType(StrEnum):
    BUTTON = "button"
    ROW = "row"
    COLUMN = "column"
    CAROUSEL = "carousel"
    TEXT = "text"
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


class _BaseElement(DataObject, ABC):
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
        **kwargs: Any,
    ) -> None:
        from ceres.component import Component

        if address is None:
            if not isinstance(action, MethodType):
                raise ValueError("address must be specified if action is not a bound method")
            elif not isinstance(action.__self__, Component):
                raise ValueError("method passed as action must be bound to a component")

            address = action.__self__.address

        if not isinstance(action, str):
            from ceres.component import ActionBinding, get_method_binding

            binding = get_method_binding(action, ActionBinding)
            if not binding:
                raise ValueError(f"function {strify(action)} has no action binding")

            action = binding.name

        super().__init__(
            **{
                "title": title,
                "address": address,
                "action": action,
                "color": color,
                **kwargs,
            }
        )


class Row(_BaseElement):
    type: Literal[ElementType.ROW] = ElementType.ROW
    sizing: Sizing = Sizing.GROW
    justify: Justify = Justify.START
    align: Align = Align.START
    children: list["Element"]


class Column(_BaseElement):
    type: Literal[ElementType.COLUMN] = ElementType.COLUMN
    sizing: Sizing = Sizing.GROW
    justify: Justify = Justify.START
    align: Align = Align.START
    children: list["Element"]


class Carousel(_BaseElement):
    type: Literal[ElementType.CAROUSEL] = ElementType.CAROUSEL
    height: int | str | None = None
    children: list["Element"]


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
        color: Color | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            **{
                "value": value,
                "variant": variant,
                "color": color,
                **kwargs,
            }
        )


AtomicValue: TypeAlias = StrictBool | StrictInt | StrictFloat | Decimal | StrictStr


class State(_BaseElement):
    class Option(ImmutableDataObject):
        value: AtomicValue
        label: str
        color: Color
        icon: str | None = None
        description: str | None = None

    type: Literal[ElementType.STATE] = ElementType.STATE
    value: AtomicValue
    options: list[Option]


class Gauge(_BaseElement):
    class ColorStop(ImmutableDataObject):
        value: float
        color: Color

    type: Literal[ElementType.GAUGE] = ElementType.GAUGE
    value: float
    unit: str | None = None
    min: float
    max: float
    color: list[ColorStop] | Color | None = None


class Chart(_BaseElement):
    type: Literal[ElementType.CHART] = ElementType.CHART
    value: dict[str, object]
    height: int


class PaletteColor(Color, Enum):
    PRIMARY = Color("#0089ab")
    SECONDARY = Color("#26a69a")
    ACCENT = Color("#9c27b0")
    DARK = Color("#1d1d1d")
    POSITIVE = Color("#21ba45")
    NEGATIVE = Color("#c10015")
    INFO = Color("#31ccec")
    WARNING = Color("#f2c037")


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
        **kwargs: Any,
    ) -> None:
        from ceres.component import Component

        if address is None:
            if not isinstance(query, MethodType):
                raise ValueError("address must be specified if query is not a bound method")
            elif not isinstance(query.__self__, Component):
                raise ValueError("method passed as query must be bound to a component")

            address = query.__self__.address

        if not isinstance(query, str):
            from ceres.component import QueryBinding, get_method_binding

            binding = get_method_binding(query, QueryBinding)
            if not binding:
                raise ValueError(f"function {strify(query)} has no query binding")

            query = binding.name

        super().__init__(
            **{
                "address": address,
                "query": query,
                **kwargs,
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
        **kwargs: Any,
    ) -> None:
        super().__init__(
            title=title,
            address=address,
            query=query,
            **kwargs,
        )


Element = Annotated[  # type: ignore
    Button | Row | Column | Carousel | Text | State | Gauge | Chart | Render | Display,
    Field(discriminator="type"),
]


__update_forward_refs()
